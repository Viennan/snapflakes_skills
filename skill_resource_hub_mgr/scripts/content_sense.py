#!/usr/bin/env python3
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common import (
    DEFAULT_CONTENT_SENSE_CACHE_TIME_HOURS,
    DEFAULT_DESCRIPTION_LANGUAGE,
    HubError,
    MAX_AUTO_RESOURCE_NAME_CHARS,
    MAX_CONTENT_SENSE_DESCRIPTION_CHARS,
    description_language_label,
    make_auto_name_candidate,
    normalize_content_sense_description,
    normalize_description_language,
)
from llm_clients import get_openai_client
from media_ops import extract_video_frames, probe_media

FILE_PROCESSING_POLL_INTERVAL_SECONDS = 1.0
FILE_PROCESSING_MAX_WAIT_SECONDS = 300.0
FILE_READY_STATUSES = {"active", "processed"}
FILE_TERMINAL_ERROR_STATUSES = {"deleted", "error", "failed"}


def _load_client(config: dict[str, Any]):
    content_sense = config.get("content_sense")
    if not isinstance(content_sense, dict):
        raise HubError("content_sense config is required for content sensing")

    api_key_env = content_sense.get("open_ai_api_key_env")
    if not isinstance(api_key_env, str) or not api_key_env.strip():
        raise HubError("content_sense.open_ai_api_key_env must be a non-empty string")

    base_url = content_sense.get("open_ai_base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        raise HubError("content_sense.open_ai_base_url must be a non-empty string")
    model = content_sense.get("model")
    if not isinstance(model, str) or not model.strip():
        raise HubError("content_sense.model must be a non-empty string")

    cache_time_hours = content_sense.get("cache_time_hours", DEFAULT_CONTENT_SENSE_CACHE_TIME_HOURS)
    if not isinstance(cache_time_hours, (int, float)) or cache_time_hours < 0:
        raise HubError("content_sense.cache_time_hours must be a non-negative number")

    raw_language = config.get("description_language", DEFAULT_DESCRIPTION_LANGUAGE)
    description_language = normalize_description_language(raw_language)
    if description_language is None:
        raise HubError("description_language must be one of: en, zh-CN")

    client = get_openai_client(
        api_key_env=api_key_env.strip(),
        base_url=base_url.strip(),
    )
    return client, content_sense, model, float(cache_time_hours), description_language


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(stripped[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            raise HubError(f"Failed to parse content sense JSON response: {exc}") from exc
    raise HubError("Content sense response did not contain a JSON object")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc_iso(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _media_signature(media_path: Path) -> dict[str, Any]:
    stat = media_path.stat()
    return {
        "input_f_name": media_path.name,
        "input_size_bytes": int(stat.st_size),
        "input_mtime_ns": int(stat.st_mtime_ns),
    }


def _cache_base_record(
    *,
    content_sense: dict[str, Any],
    resource_type: str,
    media_path: Path,
) -> dict[str, Any]:
    video_mode = content_sense.get("video_understanding_mode") if resource_type == "video" else ""
    return {
        "provider_base_url": str(content_sense.get("open_ai_base_url", "")).strip(),
        "api_key_env": str(content_sense.get("open_ai_api_key_env", "")).strip(),
        "resource_type": resource_type,
        "video_understanding_mode": str(video_mode or ""),
        **_media_signature(media_path),
    }


def _normalize_cached_uploads(
    cache_record: dict[str, Any],
    *,
    expected_input_type: str,
    cache_time_hours: float,
) -> list[dict[str, Any]] | None:
    uploads = cache_record.get("uploads")
    if not isinstance(uploads, list) or not uploads:
        return None

    not_after = _utc_now() - timedelta(hours=cache_time_hours)
    normalized: list[dict[str, Any]] = []
    for upload in uploads:
        if not isinstance(upload, dict):
            return None
        file_id = upload.get("file_id")
        purpose = upload.get("purpose")
        input_type = upload.get("input_type")
        uploaded_at = _parse_utc_iso(upload.get("uploaded_at"))
        if not isinstance(file_id, str) or not file_id.strip():
            return None
        if not isinstance(purpose, str) or not purpose.strip():
            return None
        if input_type != expected_input_type:
            return None
        if uploaded_at is None:
            return None
        if cache_time_hours == 0 or uploaded_at < not_after:
            return None

        entry = {
            "file_id": file_id.strip(),
            "purpose": purpose.strip(),
            "input_type": input_type,
            "uploaded_at": _to_utc_iso(uploaded_at),
        }
        if "frame_time_seconds" in upload:
            try:
                entry["frame_time_seconds"] = float(upload["frame_time_seconds"])
            except (TypeError, ValueError):
                return None
        normalized.append(entry)
    return normalized


def _cached_uploads_for_request(
    *,
    cache_record: dict[str, Any] | None,
    content_sense: dict[str, Any],
    resource_type: str,
    media_path: Path,
    cache_time_hours: float,
) -> list[dict[str, Any]] | None:
    if cache_record is None or not isinstance(cache_record, dict):
        return None

    base_record = _cache_base_record(
        content_sense=content_sense,
        resource_type=resource_type,
        media_path=media_path,
    )
    for key, value in base_record.items():
        if cache_record.get(key) != value:
            return None

    if resource_type == "image":
        cached_uploads = _normalize_cached_uploads(
            cache_record,
            expected_input_type="input_image",
            cache_time_hours=cache_time_hours,
        )
        if cached_uploads is None or len(cached_uploads) != 1:
            return None
        return cached_uploads

    video_mode = content_sense.get("video_understanding_mode")
    if video_mode == "direct_upload":
        cached_uploads = _normalize_cached_uploads(
            cache_record,
            expected_input_type="input_video",
            cache_time_hours=cache_time_hours,
        )
        if cached_uploads is None or len(cached_uploads) != 1:
            return None
        return cached_uploads
    if video_mode == "frames":
        cached_uploads = _normalize_cached_uploads(
            cache_record,
            expected_input_type="input_image",
            cache_time_hours=cache_time_hours,
        )
        if cached_uploads is None:
            return None
        if not all("frame_time_seconds" in upload for upload in cached_uploads):
            return None
        return sorted(cached_uploads, key=lambda item: float(item["frame_time_seconds"]))
    return None


def _upload_user_data_file(client: Any, media_path: Path) -> tuple[str, str]:
    uploaded_at = _to_utc_iso(_utc_now())
    with media_path.open("rb") as handle:
        uploaded = client.files.create(file=handle, purpose="user_data")
    deadline = _utc_now() + timedelta(seconds=FILE_PROCESSING_MAX_WAIT_SECONDS)
    while True:
        current = client.files.retrieve(uploaded.id)
        status = str(getattr(current, "status", "")).strip().lower()
        if status in FILE_READY_STATUSES:
            break
        if status in FILE_TERMINAL_ERROR_STATUSES:
            raise RuntimeError(f"Uploaded file {uploaded.id} became unusable; current status={status}")
        if _utc_now() >= deadline:
            raise RuntimeError(
                f"Giving up on waiting for file {uploaded.id} to become ready after "
                f"{FILE_PROCESSING_MAX_WAIT_SECONDS} seconds."
            )
        time.sleep(FILE_PROCESSING_POLL_INTERVAL_SECONDS)
    return str(uploaded.id), uploaded_at


def _json_contract_clause(infer_name: bool, description_language: str) -> str:
    name_clause = (
        '"resource_name": a short lowercase ASCII hyphen-case name that can be used as a directory name, '
        "descriptive and not generic,"
        if infer_name
        else '"resource_name": "",'
    )
    return (
        "Return only valid JSON with these keys: "
        f"{name_clause} "
        '"description". '
        f"description must be written in {description_language_label(description_language)}, "
        f"be concise but informative, and contain fewer than {MAX_CONTENT_SENSE_DESCRIPTION_CHARS + 1} Unicode characters. "
        f"When resource_name is required, it must contain fewer than {MAX_AUTO_RESOURCE_NAME_CHARS + 1} characters."
    )


def _format_common_facts(media_probe: dict[str, Any]) -> str:
    return (
        "Authoritative technical facts from ffprobe "
        f"(do not infer or override them): has_alpha={str(bool(media_probe.get('has_alpha'))).lower()}, "
        f"width={media_probe.get('width')}, height={media_probe.get('height')}, "
        f"resolution={media_probe.get('resolution')}, format={media_probe.get('format')}."
    )


def _image_prompt_text(infer_name: bool, media_probe: dict[str, Any], description_language: str) -> str:
    alpha_guidance = (
        "The image has alpha. Mention transparent/alpha background when it is relevant to the visual result."
        if media_probe.get("has_alpha")
        else "The image does not have alpha. Do not claim transparent background."
    )
    language_guidance = (
        f"The resource hub is configured with description_language={description_language}. "
        f"You must write the description strictly in {description_language_label(description_language)}. "
        "Do not mix languages unless you must quote visible text exactly as shown in the asset."
    )
    return (
        "You are describing an image asset for a local resource hub. "
        f"{_json_contract_clause(infer_name, description_language)} "
        f"{language_guidance} "
        f"{_format_common_facts(media_probe)} "
        f"{alpha_guidance} "
        "Focus on the primary subject, composition, scene, color/style, and likely usage context. "
        "The description should be grounded in what is actually visible, not speculative."
    )


def _video_prompt_text(
    infer_name: bool,
    media_probe: dict[str, Any],
    video_mode: str,
    description_language: str,
) -> str:
    alpha_guidance = (
        "The video has alpha. Mention transparent/alpha background when it is relevant to the visual result."
        if media_probe.get("has_alpha")
        else "The video does not have alpha. Do not claim transparent background."
    )
    duration = float(media_probe.get("duration", 0.0) or 0.0)
    fps = int(media_probe.get("fps", 0) or 0)
    mode_guidance = (
        "You will receive representative frames with timestamps; infer the temporal progression conservatively from them."
        if video_mode == "frames"
        else "You will receive the video file directly; use the full timeline when describing temporal progression."
    )
    language_guidance = (
        f"The resource hub is configured with description_language={description_language}. "
        f"You must write the description strictly in {description_language_label(description_language)}. "
        "Do not mix languages unless you must quote visible text exactly as shown in the asset."
    )
    return (
        "You are describing a video asset for a local resource hub. "
        f"{_json_contract_clause(infer_name, description_language)} "
        f"{language_guidance} "
        f"{_format_common_facts(media_probe)} "
        f"Additional video facts from ffprobe: duration={duration:.3f}s, fps={fps}. "
        f"{alpha_guidance} "
        f"{mode_guidance} "
        "description must describe the video with appropriately segmented approximate time ranges "
        "covering the main timeline progression, such as '0.0-1.2s: ...; 1.2-2.5s: ...'. "
        "The video description must include scene progression, visible motion/action, and atmosphere or 运境 "
        "(mood, tone, environmental feeling). "
        "Keep the timeline segmentation proportional to the video's duration and avoid over-claiming details not supported by the media."
    )


def sense_asset(
    *,
    config: dict[str, Any],
    resource_type: str,
    media_path: Path,
    infer_name: bool,
    existing_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client, content_sense, model, cache_time_hours, description_language = _load_client(config)
    media_probe = probe_media(media_path)
    newly_uploaded_file_ids: list[str] = []
    cache_record = _cache_base_record(
        content_sense=content_sense,
        resource_type=resource_type,
        media_path=media_path,
    )

    try:
        if resource_type == "image":
            content: list[dict[str, Any]] = [
                {"type": "input_text", "text": _image_prompt_text(infer_name, media_probe, description_language)}
            ]
            cached_uploads = _cached_uploads_for_request(
                cache_record=existing_cache,
                content_sense=content_sense,
                resource_type=resource_type,
                media_path=media_path,
                cache_time_hours=cache_time_hours,
            )
            if cached_uploads is not None:
                uploads = cached_uploads
            else:
                uploaded_id, uploaded_at = _upload_user_data_file(client, media_path)
                newly_uploaded_file_ids.append(uploaded_id)
                uploads = [
                    {
                        "file_id": uploaded_id,
                        "purpose": "user_data",
                        "input_type": "input_image",
                        "uploaded_at": uploaded_at,
                    }
                ]
            content.append({"type": "input_image", "file_id": uploads[0]["file_id"]})
        else:
            video_mode = content_sense.get("video_understanding_mode")
            content = [
                {
                    "type": "input_text",
                    "text": _video_prompt_text(
                        infer_name,
                        media_probe,
                        str(video_mode),
                        description_language,
                    ),
                }
            ]
            cached_uploads = _cached_uploads_for_request(
                cache_record=existing_cache,
                content_sense=content_sense,
                resource_type=resource_type,
                media_path=media_path,
                cache_time_hours=cache_time_hours,
            )
            if video_mode == "direct_upload":
                if cached_uploads is not None:
                    uploads = cached_uploads
                else:
                    uploaded_id, uploaded_at = _upload_user_data_file(client, media_path)
                    newly_uploaded_file_ids.append(uploaded_id)
                    uploads = [
                        {
                            "file_id": uploaded_id,
                            "purpose": "user_data",
                            "input_type": "input_video",
                            "uploaded_at": uploaded_at,
                        }
                    ]
                content.append({"type": "input_video", "file_id": uploads[0]["file_id"]})
            elif video_mode == "frames":
                if cached_uploads is not None:
                    uploads = cached_uploads
                else:
                    uploads = []
                    from tempfile import TemporaryDirectory

                    with TemporaryDirectory(prefix="resource-hub-frames-") as temp_dir:
                        frames = extract_video_frames(media_path, Path(temp_dir))
                        for frame, timestamp in frames:
                            uploaded_id, uploaded_at = _upload_user_data_file(client, frame)
                            newly_uploaded_file_ids.append(uploaded_id)
                            uploads.append(
                                {
                                    "file_id": uploaded_id,
                                    "purpose": "user_data",
                                    "input_type": "input_image",
                                    "uploaded_at": uploaded_at,
                                    "frame_time_seconds": float(timestamp),
                                }
                            )
                    uploads.sort(key=lambda item: float(item["frame_time_seconds"]))

                total_duration = float(media_probe.get("duration", 0.0) or 0.0)
                for index, upload in enumerate(uploads, start=1):
                    timestamp = float(upload["frame_time_seconds"])
                    content.append(
                        {
                            "type": "input_text",
                            "text": (
                                f"Representative frame {index} captured near t={timestamp:.3f}s "
                                f"of total duration {total_duration:.3f}s."
                            ),
                        }
                    )
                    content.append({"type": "input_image", "file_id": upload["file_id"]})
            else:
                raise HubError("content_sense.video_understanding_mode must be 'frames' or 'direct_upload'")

        response = client.responses.create(
            model=model,
            input=[{"role": "user", "content": content}],
        )
        parsed = _extract_json_object(response.output_text)
    except Exception as exc:  # noqa: BLE001
        for file_id in newly_uploaded_file_ids:
            try:
                client.files.delete(file_id)
            except Exception:  # noqa: BLE001
                pass
        raise HubError(f"Content sensing failed: {exc}") from exc

    return {
        "resource_name": make_auto_name_candidate(str(parsed.get("resource_name", "")), fallback="resource")
        if infer_name
        else "",
        "description": normalize_content_sense_description(parsed.get("description", "")),
        "content_sense_cache": {
            **cache_record,
            "uploads": uploads,
        },
    }
