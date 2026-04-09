#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from common import (
    CONFIG_FILE_NAME,
    DEFAULT_CONTENT_SENSE_CACHE_TIME_HOURS,
    DEFAULT_DESCRIPTION_LANGUAGE,
    HubError,
    MAX_CONTENT_SENSE_DESCRIPTION_CHARS,
    RESOLUTIONS,
    RESOURCE_DIRS,
    config_path_from_hub,
    determine_resolution,
    iter_resource_types,
    load_json,
    normalize_description_language,
    validate_env_backed_string_config,
)
from text_vectorization import (
    RESOURCE_SEARCH_CORPUS_PROFILE,
    TEXT_VECTORIZATION_ENCODING,
    TEXT_VECTORIZATION_PROVIDER,
    TEXT_VECTORIZATION_TEXT_FIELD,
    corpus_instruction_for_resource_search,
    decode_embedding_string,
    load_text_vectorization_config,
    sha256_hex,
)


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def add_warning(warnings: list[str], message: str) -> None:
    warnings.append(message)


def is_valid_name(name: Any) -> bool:
    if not isinstance(name, str) or not name.strip():
        return False
    if name != name.strip():
        return False
    if name in {".", ".."}:
        return False
    return "/" not in name and "\\" not in name


def validate_config(config: dict[str, Any], errors: list[str]) -> None:
    raw_language = config.get("description_language", DEFAULT_DESCRIPTION_LANGUAGE)
    if normalize_description_language(raw_language) is None:
        add_error(errors, "config.description_language must be one of: en, zh-CN")

    for resource_type in ("video", "image"):
        if resource_type not in config or not isinstance(config[resource_type], dict):
            add_error(errors, f"config.{resource_type} must exist and be an object")

    content_sense = config.get("content_sense")
    video_cfg = config.get("video", {}) if isinstance(config.get("video"), dict) else {}
    image_cfg = config.get("image", {}) if isinstance(config.get("image"), dict) else {}

    for resource_type, cfg in (("video", video_cfg), ("image", image_cfg)):
        with_description = cfg.get("with_description")
        if with_description is None:
            continue
        if not isinstance(with_description, dict):
            add_error(errors, f"config.{resource_type}.with_description must be an object")
            continue
        resolution = with_description.get("resolution")
        if resolution not in RESOLUTIONS:
            add_error(errors, f"config.{resource_type}.with_description.resolution is invalid")

    for resource_type, cfg in (("video", video_cfg), ("image", image_cfg)):
        transcoders = cfg.get("transcoders", [])
        if transcoders is None:
            continue
        if not isinstance(transcoders, list):
            add_error(errors, f"config.{resource_type}.transcoders must be a list")
            continue
        seen_specs: set[tuple[Any, ...]] = set()
        for index, item in enumerate(transcoders):
            if not isinstance(item, dict):
                add_error(errors, f"config.{resource_type}.transcoders[{index}] must be an object")
                continue
            resolution = item.get("resolution")
            if resolution not in RESOLUTIONS:
                add_error(errors, f"config.{resource_type}.transcoders[{index}].resolution is invalid")
            if resource_type == "video":
                fps = item.get("fps")
                if not isinstance(fps, int) or fps <= 0:
                    add_error(errors, f"config.video.transcoders[{index}].fps must be a positive integer")
                spec = (resolution, fps)
            else:
                spec = (resolution,)
            if spec in seen_specs:
                add_error(errors, f"config.{resource_type}.transcoders contains duplicate spec {spec}")
            seen_specs.add(spec)

    requires_content_sense = any(
        isinstance(cfg, dict) and isinstance(cfg.get("with_description"), dict)
        for cfg in (video_cfg, image_cfg)
    )
    if content_sense is not None and not isinstance(content_sense, dict):
        add_error(errors, "config.content_sense must be an object when present")
    if requires_content_sense and not isinstance(content_sense, dict):
        add_error(errors, "config.content_sense must exist when with_description is enabled")
        return
    if isinstance(content_sense, dict):
        try:
            validate_env_backed_string_config(
                content_sense,
                env_key="open_ai_base_url_env",
                value_key="open_ai_base_url",
                field_name="config.content_sense",
            )
        except HubError as exc:
            add_error(errors, str(exc))
        for key in ("open_ai_api_key_env", "model"):
            value = content_sense.get(key)
            if not isinstance(value, str) or not value.strip():
                add_error(errors, f"config.content_sense.{key} must be a non-empty string")
        cache_time_hours = content_sense.get("cache_time_hours", DEFAULT_CONTENT_SENSE_CACHE_TIME_HOURS)
        if not isinstance(cache_time_hours, (int, float)) or cache_time_hours < 0:
            add_error(errors, "config.content_sense.cache_time_hours must be a non-negative number")
        if isinstance(video_cfg.get("with_description"), dict):
            mode = content_sense.get("video_understanding_mode")
            if mode not in {"frames", "direct_upload"}:
                add_error(errors, "config.content_sense.video_understanding_mode must be 'frames' or 'direct_upload'")

    try:
        load_text_vectorization_config(config, resolve_env=False)
    except HubError as exc:
        add_error(errors, str(exc))


def validate_variation_common(resource_dir: Path, variation: dict[str, Any], errors: list[str]) -> Path | None:
    f_name = variation.get("f_name")
    if not isinstance(f_name, str) or not f_name or "/" in f_name or "\\" in f_name:
        add_error(errors, f"{resource_dir} index variation has invalid f_name: {f_name}")
        return None
    file_path = resource_dir / f_name
    if not file_path.exists():
        add_error(errors, f"missing managed file: {file_path}")
    format_value = variation.get("format")
    suffix = file_path.suffix.lstrip(".").lower()
    if not isinstance(format_value, str) or format_value.lower() != suffix:
        add_error(errors, f"{resource_dir} variation {f_name} has mismatched format")
    width = variation.get("width")
    height = variation.get("height")
    if not isinstance(width, int) or width <= 0 or not isinstance(height, int) or height <= 0:
        add_error(errors, f"{resource_dir} variation {f_name} has invalid dimensions")
    else:
        expected_resolution = determine_resolution(width, height)
        if variation.get("resolution") != expected_resolution:
            add_error(
                errors,
                f"{resource_dir} variation {f_name} has resolution {variation.get('resolution')}, expected {expected_resolution}",
            )
    if variation.get("type") not in {"original", "transcoded"}:
        add_error(errors, f"{resource_dir} variation {f_name} has invalid type")
    if not isinstance(variation.get("has_alpha"), bool):
        add_error(errors, f"{resource_dir} variation {f_name} must define boolean has_alpha")
    return file_path


def validate_content_sense_cache(
    resource_type: str,
    resource_dir: Path,
    cache: Any,
    managed_file_names: set[str],
    errors: list[str],
) -> None:
    if cache is None:
        return
    if not isinstance(cache, dict):
        add_error(errors, f"{resource_dir} content_sense_cache must be an object")
        return
    for key in ("provider_base_url", "api_key_env", "resource_type", "input_f_name"):
        value = cache.get(key)
        if not isinstance(value, str) or not value.strip():
            add_error(errors, f"{resource_dir} content_sense_cache.{key} must be a non-empty string")
    if cache.get("resource_type") != resource_type:
        add_error(errors, f"{resource_dir} content_sense_cache.resource_type must equal {resource_type}")
    if resource_type == "video":
        mode = cache.get("video_understanding_mode")
        if mode not in {"frames", "direct_upload"}:
            add_error(errors, f"{resource_dir} content_sense_cache.video_understanding_mode is invalid")
    else:
        mode = cache.get("video_understanding_mode", "")
        if mode not in {"", None}:
            add_error(errors, f"{resource_dir} content_sense_cache.video_understanding_mode must be empty for image")

    for key in ("input_size_bytes", "input_mtime_ns"):
        value = cache.get(key)
        if not isinstance(value, int) or value < 0:
            add_error(errors, f"{resource_dir} content_sense_cache.{key} must be a non-negative integer")

    input_f_name = cache.get("input_f_name")
    if isinstance(input_f_name, str) and input_f_name not in managed_file_names:
        add_error(errors, f"{resource_dir} content_sense_cache.input_f_name must reference a managed file")

    uploads = cache.get("uploads")
    if not isinstance(uploads, list) or not uploads:
        add_error(errors, f"{resource_dir} content_sense_cache.uploads must be a non-empty list")
        return
    for index, upload in enumerate(uploads):
        if not isinstance(upload, dict):
            add_error(errors, f"{resource_dir} content_sense_cache.uploads[{index}] must be an object")
            continue
        file_id = upload.get("file_id")
        if not isinstance(file_id, str) or not file_id.strip():
            add_error(errors, f"{resource_dir} content_sense_cache.uploads[{index}].file_id must be a non-empty string")
        purpose = upload.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            add_error(errors, f"{resource_dir} content_sense_cache.uploads[{index}].purpose must be a non-empty string")
        input_type = upload.get("input_type")
        if input_type not in {"input_image", "input_video"}:
            add_error(errors, f"{resource_dir} content_sense_cache.uploads[{index}].input_type is invalid")
        uploaded_at = upload.get("uploaded_at")
        if not isinstance(uploaded_at, str) or not uploaded_at.strip():
            add_error(errors, f"{resource_dir} content_sense_cache.uploads[{index}].uploaded_at must be a non-empty string")
        else:
            try:
                datetime.fromisoformat(uploaded_at.replace("Z", "+00:00"))
            except ValueError:
                add_error(errors, f"{resource_dir} content_sense_cache.uploads[{index}].uploaded_at must be ISO-8601")
        if "frame_time_seconds" in upload:
            value = upload.get("frame_time_seconds")
            if not isinstance(value, (int, float)) or value < 0:
                add_error(errors, f"{resource_dir} content_sense_cache.uploads[{index}].frame_time_seconds must be a non-negative number")


def validate_text_vector(
    resource_dir: Path,
    description: str,
    text_vector: Any,
    text_vector_config: dict[str, Any] | None,
    errors: list[str],
    warnings: list[str],
) -> None:
    if text_vector is None:
        if text_vector_config is not None and description.strip():
            add_warning(warnings, f"{resource_dir} is missing text_vector; run repair_hub.py to backfill vectors")
        return
    if not isinstance(text_vector, dict):
        add_error(errors, f"{resource_dir} text_vector must be an object")
        return

    provider = text_vector.get("provider")
    if provider != TEXT_VECTORIZATION_PROVIDER:
        add_error(errors, f"{resource_dir} text_vector.provider must be {TEXT_VECTORIZATION_PROVIDER}")

    base_url = text_vector.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        add_error(errors, f"{resource_dir} text_vector.base_url must be a non-empty string")

    model = text_vector.get("model")
    if not isinstance(model, str) or not model.strip():
        add_error(errors, f"{resource_dir} text_vector.model must be a non-empty string")

    dimensions = text_vector.get("dimensions")
    if not isinstance(dimensions, int) or dimensions <= 0:
        add_error(errors, f"{resource_dir} text_vector.dimensions must be a positive integer")
        dimensions = None

    if text_vector.get("encoding") != TEXT_VECTORIZATION_ENCODING:
        add_error(errors, f"{resource_dir} text_vector.encoding must be {TEXT_VECTORIZATION_ENCODING}")

    if text_vector.get("text_field") != TEXT_VECTORIZATION_TEXT_FIELD:
        add_error(errors, f"{resource_dir} text_vector.text_field must be {TEXT_VECTORIZATION_TEXT_FIELD}")

    expected_text_sha = sha256_hex(description)
    if text_vector.get("text_sha256") != expected_text_sha:
        add_warning(warnings, f"{resource_dir} text_vector.text_sha256 is stale; run repair_hub.py to refresh vectors")

    instruction_profile = text_vector.get("instruction_profile")
    if not isinstance(instruction_profile, str) or not instruction_profile.strip():
        add_error(errors, f"{resource_dir} text_vector.instruction_profile must be a non-empty string")
    elif instruction_profile != RESOURCE_SEARCH_CORPUS_PROFILE:
        add_warning(
            warnings,
            f"{resource_dir} text_vector.instruction_profile does not match the current corpus profile; run repair_hub.py",
        )

    instruction_sha = text_vector.get("instruction_sha256")
    if not isinstance(instruction_sha, str) or not instruction_sha.strip():
        add_error(errors, f"{resource_dir} text_vector.instruction_sha256 must be a non-empty string")
    elif instruction_sha != sha256_hex(corpus_instruction_for_resource_search()):
        add_warning(
            warnings,
            f"{resource_dir} text_vector.instruction_sha256 is stale; run repair_hub.py to refresh vectors",
        )

    embedding = text_vector.get("embedding")
    if not isinstance(embedding, str) or not embedding.strip():
        add_error(errors, f"{resource_dir} text_vector.embedding must be a non-empty string")
    elif dimensions is not None:
        try:
            decode_embedding_string(embedding, dimensions)
        except HubError as exc:
            add_error(errors, f"{resource_dir} text_vector.embedding is invalid: {exc}")

    if text_vector_config is not None:
        if base_url != text_vector_config.get("base_url"):
            add_warning(warnings, f"{resource_dir} text_vector.base_url does not match config; run repair_hub.py")
        if model != text_vector_config.get("model"):
            add_warning(warnings, f"{resource_dir} text_vector.model does not match config; run repair_hub.py")
        if dimensions is not None and dimensions != text_vector_config.get("dimensions"):
            add_warning(warnings, f"{resource_dir} text_vector.dimensions do not match config; run repair_hub.py")


def validate_resource_entry(
    resource_type: str,
    type_dir: Path,
    item: dict[str, Any],
    with_description_enabled: bool,
    text_vector_config: dict[str, Any] | None,
    errors: list[str],
    warnings: list[str],
) -> int:
    name = item.get("name")
    resource_dir = type_dir / str(name)
    variation_count = 0

    if not is_valid_name(name):
        add_error(errors, f"{type_dir / str(name)} index entry has invalid name")
        return variation_count
    if not resource_dir.exists() or not resource_dir.is_dir():
        add_error(errors, f"index.json references missing resource directory: {resource_dir}")
        return variation_count

    variations = item.get("variations")
    if not isinstance(variations, list):
        add_error(errors, f"{resource_dir} index entry variations must be a list")
        return variation_count
    variation_count = len(variations)

    original_count = 0
    logical_specs: set[tuple[Any, ...]] = set()
    file_names: set[str] = set()
    managed_files: set[str] = set()
    normalized_variations: list[dict[str, Any]] = []

    for variation in variations:
        if not isinstance(variation, dict):
            add_error(errors, f"{resource_dir} index entry contains a non-object variation")
            continue
        normalized_variations.append(variation)
        file_path = validate_variation_common(resource_dir, variation, errors)
        f_name = variation.get("f_name")
        if isinstance(f_name, str):
            if f_name in file_names:
                add_error(errors, f"{resource_dir} index entry contains duplicate f_name: {f_name}")
            file_names.add(f_name)
            managed_files.add(f_name)
        if variation.get("type") == "original":
            original_count += 1

        resolution = variation.get("resolution")
        if resource_type == "video":
            fps = variation.get("fps")
            duration = variation.get("duration")
            if not isinstance(fps, int):
                add_error(errors, f"{resource_dir} video variation {f_name} must have integer fps")
            if not isinstance(duration, (int, float)):
                add_error(errors, f"{resource_dir} video variation {f_name} must have numeric duration")
            spec = (resolution, fps)
        else:
            spec = (resolution,)
        if spec in logical_specs:
            add_error(errors, f"{resource_dir} index entry contains duplicate logical spec {spec}")
        logical_specs.add(spec)

        if file_path is not None and variation.get("type") == "original":
            expected_original = f"original.{variation.get('format')}"
            if file_path.name != expected_original:
                add_error(errors, f"{resource_dir} original file must be named {expected_original}")
        elif file_path is not None and variation.get("type") == "transcoded":
            if resource_type == "video":
                expected_name = f"transcoded_{variation.get('resolution')}_{variation.get('fps')}.{variation.get('format')}"
            else:
                expected_name = f"transcoded_{variation.get('resolution')}.{variation.get('format')}"
            if file_path.name != expected_name:
                add_error(errors, f"{resource_dir} managed transcode file must be named {expected_name}")

    if original_count != 1:
        add_error(errors, f"{resource_dir} index entry must contain exactly one original variation")

    if normalized_variations:
        def sort_key(variation: dict[str, Any]) -> tuple[int, int, int]:
            type_rank = 0 if variation.get("type") == "original" else 1
            resolution_rank = RESOLUTIONS.index(variation.get("resolution")) if variation.get("resolution") in RESOLUTIONS else -1
            fps_value = variation.get("fps", 0) if resource_type == "video" and isinstance(variation.get("fps"), int) else 0
            return (type_rank, resolution_rank, fps_value)

        if normalized_variations != sorted(normalized_variations, key=sort_key):
            add_error(errors, f"{resource_dir} index entry variations must be sorted by type/resolution/fps")

    description = item.get("description")
    if not isinstance(description, str):
        add_error(errors, f"{resource_dir} index entry description must be a string")
        description = ""
    elif with_description_enabled and not description.strip():
        add_error(errors, f"{resource_dir} index entry description must be non-empty when with_description is enabled")
    elif len(description) > MAX_CONTENT_SENSE_DESCRIPTION_CHARS:
        add_error(
            errors,
            f"{resource_dir} index entry description must contain at most {MAX_CONTENT_SENSE_DESCRIPTION_CHARS} characters",
        )

    validate_text_vector(
        resource_dir,
        description,
        item.get("text_vector"),
        text_vector_config,
        errors,
        warnings,
    )

    validate_content_sense_cache(
        resource_type,
        resource_dir,
        item.get("content_sense_cache"),
        managed_files,
        errors,
    )

    extra_files = sorted(
        path.name
        for path in resource_dir.iterdir()
        if path.is_file() and path.name not in managed_files
    )
    for extra_file in extra_files:
        if extra_file == "meta.json":
            add_warning(warnings, f"{resource_dir} contains legacy meta.json; run repair_hub.py to remove it")
        else:
            add_warning(warnings, f"{resource_dir} contains unmanaged file: {extra_file}")

    return variation_count


def validate_index(
    hub_root: Path,
    resource_type: str,
    config: dict[str, Any] | None,
    errors: list[str],
    warnings: list[str],
) -> dict[str, int]:
    type_dir = hub_root / RESOURCE_DIRS[resource_type]
    stats = {
        "resource_count": 0,
        "variation_count": 0,
    }
    if not type_dir.exists():
        add_error(errors, f"missing directory: {type_dir}")
        return stats

    index_path = type_dir / "index.json"
    if not index_path.exists():
        add_error(errors, f"missing file: {index_path}")
        return stats

    try:
        data = load_json(index_path)
    except Exception as exc:  # noqa: BLE001
        add_error(errors, f"failed to load {index_path}: {exc}")
        return stats
    if not isinstance(data, dict):
        add_error(errors, f"{index_path} root must be an object")
        return stats

    resources = data.get("resources")
    if not isinstance(resources, list):
        add_error(errors, f"{index_path}.resources must be a list")
        return stats

    resource_cfg = config.get(resource_type, {}) if isinstance(config, dict) else {}
    with_description_enabled = isinstance(resource_cfg, dict) and isinstance(resource_cfg.get("with_description"), dict)
    try:
        text_vector_config = load_text_vectorization_config(config) if isinstance(config, dict) else None
    except HubError:
        text_vector_config = None

    names: list[str] = []
    seen_names: set[str] = set()
    for index, item in enumerate(resources):
        if not isinstance(item, dict):
            add_error(errors, f"{index_path}.resources[{index}] must be an object")
            continue
        name = item.get("name")
        if not is_valid_name(name):
            add_error(errors, f"{index_path}.resources[{index}].name is invalid")
            continue
        if name in seen_names:
            add_error(errors, f"{index_path} contains duplicate resource name: {name}")
            continue
        seen_names.add(name)
        names.append(name)
        stats["resource_count"] += 1
        stats["variation_count"] += validate_resource_entry(
            resource_type,
            type_dir,
            item,
            with_description_enabled,
            text_vector_config,
            errors,
            warnings,
        )

    if names != sorted(names):
        add_error(errors, f"{index_path}.resources must be sorted by name")

    for resource_dir in sorted(path for path in type_dir.iterdir() if path.is_dir()):
        if resource_dir.name not in seen_names:
            add_error(errors, f"resource directory missing from index.json: {resource_dir}")

    return stats


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 validate_hub.py <hub_root>", file=sys.stderr)
        return 1

    hub_root = Path(sys.argv[1]).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, Any] = {
        "resource_types": {},
    }

    if not hub_root.exists():
        add_error(errors, f"hub root does not exist: {hub_root}")
    elif not hub_root.is_dir():
        add_error(errors, f"hub root is not a directory: {hub_root}")

    config_path = config_path_from_hub(hub_root)
    if not config_path.exists():
        add_error(errors, f"missing file: {config_path}")
        config = None
    else:
        try:
            config = load_json(config_path)
        except Exception as exc:  # noqa: BLE001
            add_error(errors, f"failed to load {config_path}: {exc}")
            config = None
        if isinstance(config, dict):
            validate_config(config, errors)
        elif config is not None:
            add_error(errors, f"{CONFIG_FILE_NAME} root must be an object")

    for resource_type, _ in iter_resource_types():
        stats["resource_types"][resource_type] = validate_index(
            hub_root,
            resource_type,
            config if isinstance(config, dict) else None,
            errors,
            warnings,
        )

    payload = {
        "ok": not errors,
        "hub_root": str(hub_root),
        "errors": errors,
        "warnings": warnings,
        "stats": stats,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
