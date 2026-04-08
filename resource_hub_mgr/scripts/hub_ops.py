#!/usr/bin/env python3
from __future__ import annotations

import copy
import shutil
import tempfile
from pathlib import Path
from typing import Any

from common import (
    DEFAULT_CONTENT_SENSE_CACHE_TIME_HOURS,
    DEFAULT_DESCRIPTION_LANGUAGE,
    HubError,
    MAX_CONTENT_SENSE_DESCRIPTION_CHARS,
    RESOURCE_DIRS,
    config_path_from_hub,
    description_language_label,
    dump_json,
    ensure_unique_resource_name,
    is_valid_resource_name,
    load_json,
    make_auto_name_candidate,
    make_variation_path,
    normalize_content_sense_description,
    normalize_description_language,
    resolution_rank,
    safe_stem_name,
    sort_variations,
)
from content_sense import sense_asset
from media_ops import (
    build_variation_dict,
    create_image_transcode,
    create_video_transcode,
    is_exact_image_target,
    is_exact_video_target,
    probe_media,
    target_is_realizable_from_original,
)
from text_vectorization import build_description_text_vector


DEFAULT_CONFIG = {
    "description_language": DEFAULT_DESCRIPTION_LANGUAGE,
    "video": {"transcoders": []},
    "image": {"transcoders": []},
}


def ensure_hub_structure(hub_root: Path) -> dict[str, Any]:
    hub_root.mkdir(parents=True, exist_ok=True)
    config_path = config_path_from_hub(hub_root)
    if config_path.exists():
        config = load_json(config_path)
        if not isinstance(config, dict):
            raise HubError("resource_hub_config.json root must be an object")
    else:
        config = copy.deepcopy(DEFAULT_CONFIG)
        dump_json(config_path, config)

    for dirname in RESOURCE_DIRS.values():
        type_dir = hub_root / dirname
        type_dir.mkdir(parents=True, exist_ok=True)
        index_path = type_dir / "index.json"
        if index_path.exists():
            data = load_json(index_path)
            if not isinstance(data, dict) or not isinstance(data.get("resources"), list):
                raise HubError(f"{index_path} must contain a resources list")
        else:
            dump_json(index_path, {"resources": []})
    return config


def load_hub_config(hub_root: Path) -> dict[str, Any]:
    config_path = config_path_from_hub(hub_root)
    if not config_path.exists():
        raise HubError(f"Config not found: {config_path}")
    config = load_json(config_path)
    if not isinstance(config, dict):
        raise HubError("resource_hub_config.json root must be an object")
    return config


def _type_dir(hub_root: Path, resource_type: str) -> Path:
    if resource_type not in RESOURCE_DIRS:
        raise HubError(f"Unsupported resource type: {resource_type}")
    return hub_root / RESOURCE_DIRS[resource_type]


def _index_path(hub_root: Path, resource_type: str) -> Path:
    return _type_dir(hub_root, resource_type) / "index.json"


def _load_index_data(hub_root: Path, resource_type: str) -> dict[str, Any]:
    index_path = _index_path(hub_root, resource_type)
    data = load_json(index_path)
    if not isinstance(data, dict) or not isinstance(data.get("resources"), list):
        raise HubError(f"Invalid index file: {index_path}")
    return data


def _write_index_data(hub_root: Path, resource_type: str, resources: list[dict[str, Any]]) -> dict[str, Any]:
    data = {"resources": sorted(resources, key=lambda item: str(item.get("name", "")))}
    dump_json(_index_path(hub_root, resource_type), data)
    return data


def _resource_map(index_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resources = index_data.get("resources", [])
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(resources, list):
        return result
    for item in resources:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            result[item["name"]] = item
    return result


def _description_language(config: dict[str, Any]) -> str:
    raw_language = config.get("description_language", DEFAULT_DESCRIPTION_LANGUAGE)
    normalized = normalize_description_language(raw_language)
    if normalized is None:
        raise HubError(
            "description_language must be one of: "
            + ", ".join(sorted({DEFAULT_DESCRIPTION_LANGUAGE, "zh-CN"}))
        )
    return normalized


def get_index(hub_root: Path, resource_type: str) -> dict[str, Any]:
    return _load_index_data(hub_root, resource_type)


def _entry_with_paths(resource_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    payload = dict(entry)
    variations = payload.get("variations", [])
    if isinstance(variations, list):
        enriched: list[dict[str, Any]] = []
        for variation in variations:
            if isinstance(variation, dict):
                item = dict(variation)
                item["f_path"] = str((resource_dir / str(variation.get("f_name", ""))).resolve())
                enriched.append(item)
        payload["variations"] = enriched
    return payload


def get_meta(hub_root: Path, resource_type: str, resource_name: str) -> dict[str, Any]:
    data = _load_index_data(hub_root, resource_type)
    entry = _resource_map(data).get(resource_name)
    if entry is None:
        raise HubError(f"Resource not found in index: {resource_name}")
    return _entry_with_paths(_type_dir(hub_root, resource_type) / resource_name, entry)


def remove_resource(hub_root: Path, resource_name: str, resource_type: str | None = None) -> dict[str, Any]:
    ensure_hub_structure(hub_root)
    if resource_type is None:
        matches = [
            kind for kind in RESOURCE_DIRS if (_type_dir(hub_root, kind) / resource_name).exists()
        ]
        if not matches:
            raise HubError(f"Resource not found: {resource_name}")
        if len(matches) > 1:
            raise HubError(f"Resource name exists in multiple types, please specify type: {resource_name}")
        resource_type = matches[0]

    resource_dir = _type_dir(hub_root, resource_type) / resource_name
    if not resource_dir.exists():
        raise HubError(f"Resource not found: {resource_dir}")

    shutil.rmtree(resource_dir)
    index_data = _load_index_data(hub_root, resource_type)
    resources = [
        item
        for item in index_data.get("resources", [])
        if isinstance(item, dict) and item.get("name") != resource_name
    ]
    _write_index_data(hub_root, resource_type, resources)
    return {
        "ok": True,
        "action": "remove",
        "name": resource_name,
        "type": resource_type,
        "removed_path": str(resource_dir),
    }


def _with_description_config(config: dict[str, Any], resource_type: str) -> dict[str, Any] | None:
    resource_cfg = config.get(resource_type)
    if not isinstance(resource_cfg, dict):
        return None
    with_description = resource_cfg.get("with_description")
    return with_description if isinstance(with_description, dict) else None


def _description_enabled(config: dict[str, Any], resource_type: str) -> bool:
    return _with_description_config(config, resource_type) is not None


def _ensure_content_sense_ready(config: dict[str, Any], resource_type: str) -> None:
    if not _description_enabled(config, resource_type):
        return
    _description_language(config)
    content_sense = config.get("content_sense")
    if not isinstance(content_sense, dict):
        raise HubError("content_sense config is required when with_description is enabled")
    for key in ("open_ai_base_url", "open_ai_api_key_env", "model"):
        value = content_sense.get(key)
        if not isinstance(value, str) or not value.strip():
            raise HubError(f"content_sense.{key} must be a non-empty string")
    cache_time_hours = content_sense.get("cache_time_hours", DEFAULT_CONTENT_SENSE_CACHE_TIME_HOURS)
    if not isinstance(cache_time_hours, (int, float)) or cache_time_hours < 0:
        raise HubError("content_sense.cache_time_hours must be a non-negative number")
    if resource_type == "video":
        mode = content_sense.get("video_understanding_mode")
        if mode not in {"frames", "direct_upload"}:
            raise HubError("content_sense.video_understanding_mode must be 'frames' or 'direct_upload'")


def _sense_variation_path(
    resource_dir: Path,
    resource_type: str,
    variations: list[dict[str, Any]],
    with_description: dict[str, Any],
) -> Path:
    target_resolution = with_description.get("resolution")
    exact = next((variation for variation in variations if variation.get("resolution") == target_resolution), None)
    if exact is not None:
        return make_variation_path(resource_dir, exact)
    lowest = sorted(
        variations,
        key=lambda variation: (
            resolution_rank(str(variation.get("resolution", ""))),
            int(variation.get("fps", 0) or 0) if resource_type == "video" else 0,
        ),
    )[0]
    return make_variation_path(resource_dir, lowest)


def _normalize_text_field(value: Any) -> str:
    return str(value or "").strip()


def _build_description_payload(
    *,
    descriptions_enabled: bool,
    sensed: dict[str, Any] | None = None,
    fallback: dict[str, Any] | None = None,
) -> dict[str, str]:
    if not descriptions_enabled:
        return {
            "description": normalize_content_sense_description((fallback or {}).get("description", "")),
        }

    description = normalize_content_sense_description(
        (sensed or {}).get("description", (fallback or {}).get("description", ""))
    )
    if not description:
        raise HubError("description must be non-empty when with_description is enabled")
    if len(description) > MAX_CONTENT_SENSE_DESCRIPTION_CHARS:
        raise HubError(
            f"description must contain at most {MAX_CONTENT_SENSE_DESCRIPTION_CHARS} characters after normalization"
        )
    return {"description": description}


def _text_vector_payload_for_entry(
    *,
    config: dict[str, Any],
    description_payload: dict[str, str],
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    existing_vector = fallback.get("text_vector") if isinstance(fallback, dict) else None
    return build_description_text_vector(
        config=config,
        description=str(description_payload.get("description", "")),
        existing_vector=existing_vector if isinstance(existing_vector, dict) else None,
    )


def _apply_content_sense(
    *,
    config: dict[str, Any],
    resource_type: str,
    resource_dir: Path,
    variations: list[dict[str, Any]],
    infer_name: bool,
    existing_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with_description = _with_description_config(config, resource_type)
    if with_description is None:
        return {
            "resource_name": "",
            "description": "",
        }
    _ensure_content_sense_ready(config, resource_type)
    sense_path = _sense_variation_path(resource_dir, resource_type, variations, with_description)
    return sense_asset(
        config=config,
        resource_type=resource_type,
        media_path=sense_path,
        infer_name=infer_name,
        existing_cache=existing_cache,
    )


def _cache_payload_for_entry(
    *,
    sensed: dict[str, Any] | None = None,
    fallback: dict[str, Any] | None = None,
    managed_file_names: set[str],
) -> dict[str, Any] | None:
    candidate = None
    if isinstance(sensed, dict):
        candidate = sensed.get("content_sense_cache")
    if candidate is None and isinstance(fallback, dict):
        candidate = fallback.get("content_sense_cache")
    if not isinstance(candidate, dict):
        return None

    input_f_name = candidate.get("input_f_name")
    if not isinstance(input_f_name, str) or input_f_name not in managed_file_names:
        return None
    return candidate


def _finalize_name(
    *,
    type_dir: Path,
    source_path: Path,
    requested_name: str | None,
    sensed_name: str | None,
) -> tuple[str, dict[str, Any]]:
    if requested_name is not None:
        if not is_valid_resource_name(requested_name):
            raise HubError(f"Invalid resource name: {requested_name}")
        return requested_name, {
            "mode": "user_provided",
            "auto_named": False,
            "source": None,
            "suffix_added": False,
        }

    if sensed_name:
        candidate = make_auto_name_candidate(sensed_name, fallback=safe_stem_name(source_path) or "resource")
        mode = "content_sense"
    else:
        candidate = make_auto_name_candidate(safe_stem_name(source_path) or source_path.stem, fallback="resource")
        mode = "file_stem"

    final_name, suffix_added = ensure_unique_resource_name(type_dir, candidate)
    return final_name, {
        "mode": mode,
        "auto_named": True,
        "source": str(source_path),
        "suffix_added": suffix_added,
    }


def _managed_transcode_name(resource_type: str, target: dict[str, Any], format_name: str) -> str:
    if resource_type == "video":
        return f"transcoded_{target['resolution']}_{target['fps']}.{format_name}"
    return f"transcoded_{target['resolution']}.{format_name}"


def _materialize_transcodes(
    *,
    config: dict[str, Any],
    resource_type: str,
    resource_dir: Path,
    original_variation: dict[str, Any],
) -> list[dict[str, Any]]:
    resource_cfg = config.get(resource_type, {})
    transcoders = resource_cfg.get("transcoders", []) if isinstance(resource_cfg, dict) else []
    if not isinstance(transcoders, list):
        raise HubError(f"config.{resource_type}.transcoders must be a list")

    original_path = resource_dir / original_variation["f_name"]
    variations = [dict(original_variation)]
    for target in transcoders:
        if not isinstance(target, dict):
            continue
        if not target_is_realizable_from_original(resource_type, original_variation, target):
            continue

        if resource_type == "video":
            if any(is_exact_video_target(variation, target) for variation in variations):
                continue
            format_name = "mov" if original_variation.get("has_alpha") else "mp4"
            output_name = _managed_transcode_name(resource_type, target, format_name)
            output_path = resource_dir / output_name
            if not output_path.exists():
                create_video_transcode(
                    original_path,
                    output_path,
                    target_resolution=str(target["resolution"]),
                    target_fps=int(target["fps"]),
                    has_alpha=bool(original_variation.get("has_alpha")),
                    has_audio=bool(original_variation.get("has_audio", False)),
                )
            variations.append(build_variation_dict(output_path, variation_type="transcoded"))
        else:
            if any(is_exact_image_target(variation, target) for variation in variations):
                continue
            format_name = "png" if original_variation.get("has_alpha") else "jpg"
            output_name = _managed_transcode_name(resource_type, target, format_name)
            output_path = resource_dir / output_name
            if not output_path.exists():
                create_image_transcode(
                    original_path,
                    output_path,
                    target_resolution=str(target["resolution"]),
                    has_alpha=bool(original_variation.get("has_alpha")),
                )
            variations.append(build_variation_dict(output_path, variation_type="transcoded"))
    return sort_variations(resource_type, variations)


def _build_resource_entry(
    *,
    name: str,
    resource_type: str,
    variations: list[dict[str, Any]],
    description_payload: dict[str, str],
    cache_payload: dict[str, Any] | None,
    text_vector_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    entry = {
        "name": name,
        "variations": sort_variations(
            resource_type,
            [{k: v for k, v in variation.items() if k != "has_audio"} for variation in variations],
        ),
        **description_payload,
    }
    if cache_payload is not None:
        entry["content_sense_cache"] = cache_payload
    if text_vector_payload is not None:
        entry["text_vector"] = text_vector_payload
    return entry


def add_resource(hub_root: Path, source_path: Path, resource_name: str | None = None) -> dict[str, Any]:
    if not source_path.exists() or not source_path.is_file():
        raise HubError(f"Source file not found: {source_path}")

    config = ensure_hub_structure(hub_root)
    source_probe = probe_media(source_path)
    resource_type = str(source_probe["resource_type"])
    type_dir = _type_dir(hub_root, resource_type)
    if _description_enabled(config, resource_type):
        _ensure_content_sense_ready(config, resource_type)

    index_data = _load_index_data(hub_root, resource_type)
    existing_resources = [
        item for item in index_data.get("resources", [])
        if isinstance(item, dict)
    ]

    staging_dir = Path(tempfile.mkdtemp(prefix=".staging-", dir=str(type_dir)))
    finalized_dir: Path | None = None
    try:
        original_format = str(source_probe["format"])
        original_name = f"original.{original_format}"
        staged_original_path = staging_dir / original_name
        shutil.copy2(source_path, staged_original_path)

        original_variation = build_variation_dict(staged_original_path, variation_type="original")
        original_variation["has_audio"] = bool(source_probe.get("has_audio", False))
        variations = _materialize_transcodes(
            config=config,
            resource_type=resource_type,
            resource_dir=staging_dir,
            original_variation=original_variation,
        )

        infer_name = resource_name is None and _description_enabled(config, resource_type)
        sensed = _apply_content_sense(
            config=config,
            resource_type=resource_type,
            resource_dir=staging_dir,
            variations=variations,
            infer_name=infer_name,
        )
        final_name, naming_info = _finalize_name(
            type_dir=type_dir,
            source_path=source_path,
            requested_name=resource_name,
            sensed_name=sensed.get("resource_name") if infer_name else None,
        )
        final_dir = type_dir / final_name
        if final_dir.exists():
            raise HubError(f"Resource already exists: {final_dir}")

        description_payload = _build_description_payload(
            descriptions_enabled=_description_enabled(config, resource_type),
            sensed=sensed,
        )
        managed_file_names = {variation["f_name"] for variation in variations}
        cache_payload = _cache_payload_for_entry(
            sensed=sensed,
            managed_file_names=managed_file_names,
        )
        text_vector_payload = _text_vector_payload_for_entry(
            config=config,
            description_payload=description_payload,
        )
        entry = _build_resource_entry(
            name=final_name,
            resource_type=resource_type,
            variations=variations,
            description_payload=description_payload,
            cache_payload=cache_payload,
            text_vector_payload=text_vector_payload,
        )

        staging_dir.rename(final_dir)
        finalized_dir = final_dir
        existing_resources.append(entry)
        _write_index_data(hub_root, resource_type, existing_resources)

        return {
            "ok": True,
            "action": "add",
            "name": final_name,
            "type": resource_type,
            "resource_dir": str(final_dir),
            "auto_naming": naming_info,
            "created_files": sorted(path.name for path in final_dir.iterdir() if path.is_file()),
        }
    except Exception:
        if finalized_dir is not None and finalized_dir.exists():
            shutil.rmtree(finalized_dir, ignore_errors=True)
        else:
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def _find_original_file(resource_dir: Path) -> Path | None:
    matches = [path for path in resource_dir.iterdir() if path.is_file() and path.name.startswith("original.")]
    if len(matches) == 1:
        return matches[0]
    return None


def _managed_transcode_files(resource_dir: Path) -> list[Path]:
    return [
        path
        for path in resource_dir.iterdir()
        if path.is_file() and path.name.startswith("transcoded_")
    ]


def _legacy_entry_from_meta(
    resource_dir: Path,
    *,
    resource_type: str,
    description_language: str,
) -> dict[str, Any] | None:
    meta_path = resource_dir / "meta.json"
    if not meta_path.exists():
        return None
    loaded = load_json(meta_path)
    if not isinstance(loaded, dict):
        return None

    if description_language == "en":
        description = _normalize_text_field(
            loaded.get("description_EN", loaded.get("description_CN", loaded.get("description", "")))
        )
    else:
        description = _normalize_text_field(
            loaded.get("description_CN", loaded.get("description_EN", loaded.get("description", "")))
        )

    payload = {
        "name": str(loaded.get("name", resource_dir.name)),
        "description": description,
    }
    if isinstance(loaded.get("content_sense_cache"), dict):
        payload["content_sense_cache"] = loaded["content_sense_cache"]
    return payload


def repair_hub(hub_root: Path) -> dict[str, Any]:
    config = ensure_hub_structure(hub_root)
    description_language = _description_language(config)
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []

    for resource_type in RESOURCE_DIRS:
        type_dir = _type_dir(hub_root, resource_type)
        existing_index = _load_index_data(hub_root, resource_type)
        existing_map = _resource_map(existing_index)
        rebuilt_resources: list[dict[str, Any]] = []
        seen_dirs: set[str] = set()

        for resource_dir in sorted(path for path in type_dir.iterdir() if path.is_dir()):
            seen_dirs.add(resource_dir.name)
            try:
                original_path = _find_original_file(resource_dir)
                if original_path is None:
                    raise HubError(f"Expected exactly one original.* file in {resource_dir}")

                for transcode_path in _managed_transcode_files(resource_dir):
                    transcode_path.unlink(missing_ok=True)

                original_variation = build_variation_dict(original_path, variation_type="original")
                original_variation["has_audio"] = bool(probe_media(original_path).get("has_audio", False))
                variations = _materialize_transcodes(
                    config=config,
                    resource_type=resource_type,
                    resource_dir=resource_dir,
                    original_variation=original_variation,
                )

                legacy_entry = _legacy_entry_from_meta(
                    resource_dir,
                    resource_type=resource_type,
                    description_language=description_language,
                )
                existing_entry = existing_map.get(resource_dir.name)
                fallback_entry = (
                    existing_entry if isinstance(existing_entry, dict) else legacy_entry
                ) or legacy_entry

                if _description_enabled(config, resource_type):
                    sensed = _apply_content_sense(
                        config=config,
                        resource_type=resource_type,
                        resource_dir=resource_dir,
                        variations=variations,
                        infer_name=False,
                        existing_cache=(fallback_entry or {}).get("content_sense_cache") if isinstance(fallback_entry, dict) else None,
                    )
                else:
                    sensed = None

                description_payload = _build_description_payload(
                    descriptions_enabled=_description_enabled(config, resource_type),
                    sensed=sensed,
                    fallback=fallback_entry,
                )
                managed_file_names = {variation["f_name"] for variation in variations}
                cache_payload = _cache_payload_for_entry(
                    sensed=sensed,
                    fallback=fallback_entry,
                    managed_file_names=managed_file_names,
                )
                text_vector_payload = _text_vector_payload_for_entry(
                    config=config,
                    description_payload=description_payload,
                    fallback=fallback_entry if isinstance(fallback_entry, dict) else None,
                )
                entry = _build_resource_entry(
                    name=resource_dir.name,
                    resource_type=resource_type,
                    variations=variations,
                    description_payload=description_payload,
                    cache_payload=cache_payload,
                    text_vector_payload=text_vector_payload,
                )

                meta_path = resource_dir / "meta.json"
                if meta_path.exists():
                    meta_path.unlink()

                extra_files = [
                    path.name
                    for path in resource_dir.iterdir()
                    if path.is_file() and path.name not in managed_file_names
                ]
                for extra_file in sorted(extra_files):
                    warnings.append(f"Unmanaged file kept in {resource_dir}: {extra_file}")

                rebuilt_resources.append(entry)
                results.append(
                    {
                        "name": resource_dir.name,
                        "type": resource_type,
                        "status": "ok",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
                results.append(
                    {
                        "name": resource_dir.name,
                        "type": resource_type,
                        "status": "error",
                        "message": str(exc),
                    }
                )

        for stale_name in sorted(name for name in existing_map if name not in seen_dirs):
            warnings.append(f"Removed stale index entry from {resource_type}: {stale_name}")

        _write_index_data(hub_root, resource_type, rebuilt_resources)

    return {
        "ok": not errors,
        "action": "repair",
        "description_language": description_language_label(description_language),
        "results": results,
        "warnings": warnings,
        "errors": errors,
    }
