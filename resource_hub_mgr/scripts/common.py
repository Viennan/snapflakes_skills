#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from typing import Any, Iterable

CONFIG_FILE_NAME = "resource_hub_config.json"
RESOURCE_DIRS = {
    "video": "videos",
    "image": "images",
}
RESOLUTIONS = ["360p", "480p", "540p", "720p", "1080p", "2k", "4k", "8k"]
STANDARD_MIN_WH = {
    "360p": 360,
    "480p": 480,
    "540p": 540,
    "720p": 720,
    "1080p": 1080,
    "2k": 1440,
    "4k": 2160,
    "8k": 4320,
}
ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")
CJK_SEQUENCE_RE = re.compile(r"[\u4e00-\u9fff]+")
ASCII_ALPHA_RE = re.compile(r"[a-z]")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
FORMAT_NORMALIZATION = {
    "jpeg": "jpg",
    "tiff": "tif",
}
IMAGE_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "webp",
    "gif",
    "bmp",
    "tif",
    "tiff",
}
DEFAULT_CONTENT_SENSE_CACHE_TIME_HOURS = 144
DEFAULT_DESCRIPTION_LANGUAGE = "en"
MAX_CONTENT_SENSE_DESCRIPTION_CHARS = 499
MAX_AUTO_RESOURCE_NAME_CHARS = 19
DESCRIPTION_LANGUAGE_LABELS = {
    "en": "English",
    "zh-CN": "Simplified Chinese",
}
DESCRIPTION_LANGUAGE_ALIASES = {
    "en": "en",
    "english": "en",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh_cn": "zh-CN",
    "cn": "zh-CN",
    "chinese": "zh-CN",
    "simplified-chinese": "zh-CN",
    "simplified chinese": "zh-CN",
}


class HubError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


def determine_resolution(width: int, height: int) -> str:
    min_xy = min(width, height)
    if min_xy >= STANDARD_MIN_WH["8k"]:
        return "8k"
    if min_xy >= STANDARD_MIN_WH["4k"]:
        return "4k"
    if min_xy >= STANDARD_MIN_WH["2k"]:
        return "2k"
    if min_xy >= STANDARD_MIN_WH["1080p"]:
        return "1080p"
    if min_xy >= STANDARD_MIN_WH["720p"]:
        return "720p"
    if min_xy >= STANDARD_MIN_WH["540p"]:
        return "540p"
    if min_xy >= STANDARD_MIN_WH["480p"]:
        return "480p"
    return "360p"


def resolution_rank(resolution: str) -> int:
    try:
        return RESOLUTIONS.index(resolution)
    except ValueError:
        return -1


def normalize_text(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def ascii_tokens(text: str) -> set[str]:
    return set(ASCII_TOKEN_RE.findall(normalize_text(text)))


def is_informative_ascii_token(token: str) -> bool:
    normalized = normalize_text(str(token))
    if not normalized or ASCII_TOKEN_RE.fullmatch(normalized) is None:
        return False
    if any(char.isdigit() for char in normalized):
        return True
    return len(normalized) >= 3


def informative_ascii_tokens(text: str) -> set[str]:
    return {token for token in ascii_tokens(text) if is_informative_ascii_token(token)}


def cjk_sequences(text: str) -> set[str]:
    return set(CJK_SEQUENCE_RE.findall(normalize_text(text)))


def cjk_ngrams(text: str, sizes: Iterable[int] = (2, 3)) -> set[str]:
    tokens: set[str] = set()
    for sequence in cjk_sequences(text):
        for size in sizes:
            if len(sequence) < size:
                continue
            for index in range(len(sequence) - size + 1):
                tokens.add(sequence[index : index + size])
    return tokens


def query_features(text: str) -> dict[str, Any]:
    normalized = normalize_text(text)
    return {
        "normalized": normalized,
        "ascii_tokens": ascii_tokens(normalized),
        "informative_ascii_tokens": informative_ascii_tokens(normalized),
        "cjk_sequences": cjk_sequences(normalized),
        "cjk_ngrams": cjk_ngrams(normalized),
    }


def contains_cjk(text: str) -> bool:
    return bool(CJK_SEQUENCE_RE.search(normalize_text(text)))


def contains_ascii_alpha(text: str) -> bool:
    return bool(ASCII_ALPHA_RE.search(normalize_text(text)))


def config_path_from_hub(hub_root: Path) -> Path:
    return hub_root / CONFIG_FILE_NAME


def normalize_description_language(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    normalized = raw.strip().lower().replace("_", "-")
    return DESCRIPTION_LANGUAGE_ALIASES.get(normalized)


def description_language_label(language: str) -> str:
    return DESCRIPTION_LANGUAGE_LABELS.get(language, language)


def iter_resource_types(requested_type: str | None = None) -> list[tuple[str, str]]:
    if requested_type is None:
        return list(RESOURCE_DIRS.items())
    if requested_type not in RESOURCE_DIRS:
        raise ValueError(f"Unsupported resource type: {requested_type}")
    return [(requested_type, RESOURCE_DIRS[requested_type])]


def make_variation_path(resource_dir: Path, variation: dict[str, Any]) -> Path:
    return resource_dir / str(variation.get("f_name", ""))


def is_valid_resource_name(name: Any) -> bool:
    if not isinstance(name, str) or not name.strip():
        return False
    if name != name.strip():
        return False
    if name in {".", ".."}:
        return False
    return "/" not in name and "\\" not in name


def normalize_format_name(raw: str) -> str:
    normalized = raw.strip().lower().lstrip(".")
    return FORMAT_NORMALIZATION.get(normalized, normalized)


def safe_stem_name(path: Path) -> str:
    stem = path.stem.strip()
    if is_valid_resource_name(stem):
        return stem
    return ""


def slugify_resource_name(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text))
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    collapsed = NON_ALNUM_RE.sub("-", ascii_only).strip("-")
    collapsed = re.sub(r"-{2,}", "-", collapsed)
    return collapsed


def _truncate_slug_to_length(slug: str, max_chars: int) -> str:
    candidate = slug.strip("-")
    if len(candidate) <= max_chars:
        return candidate
    return candidate[:max_chars].rstrip("-")


def normalize_content_sense_description(text: Any, max_chars: int = MAX_CONTENT_SENSE_DESCRIPTION_CHARS) -> str:
    normalized = " ".join(str(text or "").strip().split())
    if len(normalized) <= max_chars:
        return normalized
    truncated = normalized[:max_chars].rstrip()
    if " " in truncated:
        candidate = truncated.rsplit(" ", 1)[0].rstrip()
        if candidate:
            return candidate
    return truncated


def make_auto_name_candidate(preferred_text: str, fallback: str = "resource") -> str:
    slug = _truncate_slug_to_length(slugify_resource_name(preferred_text), MAX_AUTO_RESOURCE_NAME_CHARS)
    if slug:
        return slug
    if is_valid_resource_name(preferred_text):
        trimmed = _truncate_slug_to_length(str(preferred_text).strip().lower(), MAX_AUTO_RESOURCE_NAME_CHARS)
        if trimmed:
            return trimmed
    fallback_slug = _truncate_slug_to_length(slugify_resource_name(fallback), MAX_AUTO_RESOURCE_NAME_CHARS)
    if fallback_slug:
        return fallback_slug
    return "resource"[:MAX_AUTO_RESOURCE_NAME_CHARS]


def ensure_unique_resource_name(type_dir: Path, candidate: str) -> tuple[str, bool]:
    if not (type_dir / candidate).exists():
        return candidate, False
    suffix = 2
    while True:
        suffix_text = str(suffix)
        stem_limit = max(MAX_AUTO_RESOURCE_NAME_CHARS - len(suffix_text), 1)
        stem = _truncate_slug_to_length(candidate, stem_limit)
        final_name = f"{stem}{suffix_text}"
        if final_name and not (type_dir / final_name).exists():
            return final_name, True
        suffix += 1


def run_command(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        stdout = exc.stdout.strip()
        details = stderr or stdout or str(exc)
        raise HubError(f"Command failed: {' '.join(args)}\n{details}") from exc


def ensure_external_tools(tool_names: Iterable[str]) -> None:
    missing = [tool for tool in tool_names if shutil.which(tool) is None]
    if missing:
        raise HubError(f"Missing required external tools: {', '.join(missing)}")


def sort_variations(resource_type: str, variations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(variation: dict[str, Any]) -> tuple[int, int, int]:
        type_rank = 0 if variation.get("type") == "original" else 1
        resolution_value = resolution_rank(str(variation.get("resolution", "")))
        fps_value = int(variation.get("fps", 0) or 0) if resource_type == "video" else 0
        return (type_rank, resolution_value, fps_value)

    return sorted(variations, key=key)
