#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import Any

from common import (
    HubError,
    IMAGE_EXTENSIONS,
    determine_resolution,
    ensure_external_tools,
    normalize_format_name,
    resolution_rank,
    run_command,
)


def _parse_fraction(raw: Any) -> float:
    text = str(raw or "").strip()
    if not text or text in {"0/0", "N/A"}:
        return 0.0
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            denominator_value = float(denominator)
            if denominator_value == 0:
                return 0.0
            return float(numerator) / denominator_value
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _parse_int(raw: Any) -> int | None:
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return None


def _parse_float(raw: Any) -> float | None:
    text = str(raw or "").strip()
    if not text or text == "N/A":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _probe_packet_count(path: Path) -> int | None:
    completed = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_packets",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_packets",
            "-of",
            "json",
            str(path),
        ]
    )
    payload = json.loads(completed.stdout or "{}")
    stream = (payload.get("streams") or [{}])[0]
    return _parse_int(stream.get("nb_read_packets"))


def probe_media(path: Path) -> dict[str, Any]:
    ensure_external_tools(["ffmpeg", "ffprobe"])
    completed = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ]
    )
    payload = json.loads(completed.stdout or "{}")
    streams = payload.get("streams") or []
    format_info = payload.get("format") or {}
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if video_stream is None:
        raise HubError(f"No video/image stream found in media file: {path}")

    width = _parse_int(video_stream.get("width"))
    height = _parse_int(video_stream.get("height"))
    if width is None or height is None:
        raise HubError(f"Failed to read media dimensions from: {path}")

    packet_count = _parse_int(video_stream.get("nb_frames")) or _parse_int(video_stream.get("nb_read_frames"))
    if packet_count is None:
        packet_count = _probe_packet_count(path)

    duration = _parse_float(format_info.get("duration")) or _parse_float(video_stream.get("duration")) or 0.0
    fps = int(round(_parse_fraction(video_stream.get("avg_frame_rate")) or _parse_fraction(video_stream.get("r_frame_rate"))))
    fps = max(fps, 0)

    suffix = normalize_format_name(path.suffix)
    format_names = [normalize_format_name(part) for part in str(format_info.get("format_name", "")).split(",") if part]
    pix_fmt = str(video_stream.get("pix_fmt", "")).lower()
    has_alpha = "a" in pix_fmt or pix_fmt in {
        "pal8",
        "rgba",
        "bgra",
        "argb",
        "abgr",
        "ya8",
    }

    is_static_image = suffix in IMAGE_EXTENSIONS and (packet_count or 0) <= 1 and duration <= 0.1
    resource_type = "image" if is_static_image else "video"

    return {
        "path": str(path.resolve()),
        "resource_type": resource_type,
        "format": suffix or (format_names[0] if format_names else ""),
        "width": width,
        "height": height,
        "resolution": determine_resolution(width, height),
        "duration": float(duration),
        "fps": fps,
        "has_alpha": has_alpha,
        "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
        "pix_fmt": pix_fmt,
        "packet_count": packet_count or 0,
        "format_names": format_names,
    }


def _scale_filter(target_short_side: int) -> str:
    return f"scale='if(gte(iw,ih),-2,{target_short_side})':'if(gte(iw,ih),{target_short_side},-2)'"


def create_video_transcode(
    source_path: Path,
    output_path: Path,
    *,
    target_resolution: str,
    target_fps: int,
    has_alpha: bool,
    has_audio: bool,
) -> None:
    target_short_side = {
        "360p": 360,
        "480p": 480,
        "540p": 540,
        "720p": 720,
        "1080p": 1080,
        "2k": 1440,
        "4k": 2160,
        "8k": 4320,
    }[target_resolution]
    video_filter = _scale_filter(target_short_side)
    args = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-vf",
        video_filter,
        "-r",
        str(target_fps),
        "-map",
        "0:v:0",
    ]
    if has_audio:
        args.extend(["-map", "0:a?", "-c:a", "copy"])
    if has_alpha:
        args.extend(
            [
                "-c:v",
                "prores_ks",
                "-profile:v",
                "4",
                "-pix_fmt",
                "yuva444p10le",
            ]
        )
    else:
        args.extend(
            [
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "18",
            ]
        )
    args.append(str(output_path))
    run_command(args)


def create_image_transcode(
    source_path: Path,
    output_path: Path,
    *,
    target_resolution: str,
    has_alpha: bool,
) -> None:
    target_short_side = {
        "360p": 360,
        "480p": 480,
        "540p": 540,
        "720p": 720,
        "1080p": 1080,
        "2k": 1440,
        "4k": 2160,
        "8k": 4320,
    }[target_resolution]
    args = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-vf",
        _scale_filter(target_short_side),
        "-frames:v",
        "1",
    ]
    if has_alpha:
        args.extend(["-f", "image2", str(output_path)])
    else:
        args.extend(["-q:v", "2", "-f", "image2", str(output_path)])
    run_command(args)


def extract_video_frames(source_path: Path, output_dir: Path) -> list[tuple[Path, float]]:
    probe = probe_media(source_path)
    duration = max(float(probe.get("duration", 0.0)), 0.0)
    if duration <= 0.0:
        timestamps = [0.0]
    else:
        timestamps = [round(duration * ratio, 3) for ratio in (0.1, 0.5, 0.9)]

    deduped: list[float] = []
    for timestamp in timestamps:
        if not deduped or not math.isclose(timestamp, deduped[-1], abs_tol=0.01):
            deduped.append(timestamp)
    if not deduped:
        deduped = [0.0]

    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[Path, float]] = []
    for index, timestamp in enumerate(deduped, start=1):
        frame_path = output_dir / f"frame_{index}.png"
        run_command(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(timestamp),
                "-i",
                str(source_path),
                "-frames:v",
                "1",
                str(frame_path),
            ]
        )
        frames.append((frame_path, timestamp))
    return frames


def build_variation_dict(path: Path, *, variation_type: str) -> dict[str, Any]:
    probe = probe_media(path)
    payload = {
        "f_name": path.name,
        "width": probe["width"],
        "height": probe["height"],
        "resolution": probe["resolution"],
        "type": variation_type,
        "format": probe["format"],
        "has_alpha": probe["has_alpha"],
    }
    if probe["resource_type"] == "video":
        payload["duration"] = probe["duration"]
        payload["fps"] = probe["fps"]
    return payload


def is_exact_video_target(variation: dict[str, Any], target: dict[str, Any]) -> bool:
    return (
        variation.get("resolution") == target.get("resolution")
        and int(variation.get("fps", 0) or 0) == int(target.get("fps", 0) or 0)
    )


def is_exact_image_target(variation: dict[str, Any], target: dict[str, Any]) -> bool:
    return variation.get("resolution") == target.get("resolution")


def target_is_realizable_from_original(resource_type: str, original_variation: dict[str, Any], target: dict[str, Any]) -> bool:
    if resolution_rank(str(original_variation.get("resolution", ""))) < resolution_rank(str(target.get("resolution", ""))):
        return False
    if resource_type == "video":
        return int(original_variation.get("fps", 0) or 0) >= int(target.get("fps", 0) or 0)
    return True
