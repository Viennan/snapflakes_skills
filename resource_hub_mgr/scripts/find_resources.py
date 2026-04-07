#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import (
    RESOURCE_DIRS,
    config_path_from_hub,
    cjk_ngrams,
    cjk_sequences,
    iter_resource_types,
    load_json,
    make_variation_path,
    normalize_text,
    query_features,
    resolution_rank,
)
from text_vectorization import (
    RESOURCE_SEARCH_CORPUS_PROFILE,
    TEXT_VECTORIZATION_ENCODING,
    TEXT_VECTORIZATION_PROVIDER,
    TEXT_VECTORIZATION_TEXT_FIELD,
    build_query_embedding,
    corpus_instruction_for_resource_search,
    cosine_similarity,
    decode_embedding_string,
    load_text_vectorization_config,
    sha256_hex,
)

LEXICAL_WEIGHT = 0.35
VECTOR_WEIGHT = 0.65


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search resource hub assets by natural-language description.")
    parser.add_argument("--hub", required=True, help="Path to the resource hub root.")
    parser.add_argument("--query", required=True, help="Natural-language search query.")
    parser.add_argument("--type", choices=sorted(RESOURCE_DIRS), help="Restrict resource type.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of results.")
    parser.add_argument("--require-alpha", action="store_true", help="Only return alpha-capable variations.")
    parser.add_argument("--min-resolution", help="Minimum logical resolution.")
    parser.add_argument("--min-fps", type=int, help="Minimum fps for video results.")
    return parser.parse_args()


def stringify_variation(resource_type: str, variation: dict[str, Any]) -> str:
    parts = [
        str(variation.get("resolution", "")),
        str(variation.get("format", "")),
    ]
    if resource_type == "video":
        parts.append(f"{variation.get('fps', '')}fps")
    if variation.get("has_alpha"):
        parts.extend(["alpha", "transparent"])
    return " ".join(part for part in parts if part)


def build_search_text(resource_type: str, entry: dict[str, Any]) -> str:
    fields = [
        resource_type,
        str(entry.get("name", "")),
        str(entry.get("description", "")),
    ]
    variations = entry.get("variations", [])
    if isinstance(variations, list):
        for variation in variations:
            if isinstance(variation, dict):
                fields.append(stringify_variation(resource_type, variation))
    return " ".join(field for field in fields if field)


def variation_matches_filters(resource_type: str, variation: dict[str, Any], args: argparse.Namespace) -> bool:
    if args.require_alpha and not variation.get("has_alpha"):
        return False
    if args.min_resolution and resolution_rank(str(variation.get("resolution"))) < resolution_rank(args.min_resolution):
        return False
    if resource_type == "video" and args.min_fps is not None:
        try:
            fps_value = int(variation.get("fps"))
        except (TypeError, ValueError):
            return False
        if fps_value < args.min_fps:
            return False
    return True


def choose_best_variation(
    resource_type: str,
    resource_dir: Path,
    variations: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    candidates = [variation for variation in variations if variation_matches_filters(resource_type, variation, args)]
    if not candidates:
        return None

    def sort_key(variation: dict[str, Any]) -> tuple[int, int, int]:
        resolution_value = resolution_rank(str(variation.get("resolution")))
        fps_value = int(variation.get("fps", 0) or 0) if resource_type == "video" else 0
        original_bonus = 1 if variation.get("type") == "original" else 0
        return (resolution_value, fps_value, original_bonus)

    best = sorted(candidates, key=sort_key, reverse=True)[0]
    payload = dict(best)
    payload["f_path"] = str(make_variation_path(resource_dir, best).resolve())
    return payload


def score_resource(query: str, searchable_text: str) -> tuple[int, list[str]]:
    features = query_features(query)
    haystack = normalize_text(searchable_text)
    ascii_matches = features["ascii_tokens"] & set(filter(None, haystack.split()))
    cjk_sequence_matches = features["cjk_sequences"] & cjk_sequences(haystack)
    cjk_ngram_matches = features["cjk_ngrams"] & cjk_ngrams(haystack)

    score = 0
    reasons: list[str] = []

    if features["normalized"] and features["normalized"] in haystack:
        score += 80
        reasons.append("full query matched text")
    if ascii_matches:
        score += len(ascii_matches) * 10
        reasons.append(f"matched ASCII tokens: {', '.join(sorted(ascii_matches))}")
    if cjk_sequence_matches:
        score += len(cjk_sequence_matches) * 12
        reasons.append(f"matched CJK phrases: {', '.join(sorted(cjk_sequence_matches))}")
    if cjk_ngram_matches:
        score += min(len(cjk_ngram_matches), 8) * 4
        reasons.append(f"matched {len(cjk_ngram_matches)} CJK ngrams")

    return score, reasons[:4]


def has_hard_filters(args: argparse.Namespace) -> bool:
    return any([args.require_alpha, args.min_resolution, args.min_fps is not None])


def load_search_config(hub_root: Path, warnings: list[str]) -> dict[str, Any] | None:
    config_path = config_path_from_hub(hub_root)
    if not config_path.exists():
        warnings.append("resource_hub_config.json not found; continuing with lexical search only")
        return None
    try:
        config = load_json(config_path)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Failed to load {config_path}: {exc}; continuing with lexical search only")
        return None
    if not isinstance(config, dict):
        warnings.append(f"Invalid config root object: {config_path}; continuing with lexical search only")
        return None
    return config


def resolve_corpus_vector(
    entry: dict[str, Any],
    vector_config: dict[str, Any] | None,
) -> tuple[str, tuple[float, ...] | None]:
    if vector_config is None:
        return "disabled", None

    description = str(entry.get("description", ""))
    if not description.strip():
        return "missing_description", None

    text_vector = entry.get("text_vector")
    if not isinstance(text_vector, dict):
        return "missing", None
    if text_vector.get("provider") != TEXT_VECTORIZATION_PROVIDER:
        return "invalid", None
    if text_vector.get("encoding") != TEXT_VECTORIZATION_ENCODING:
        return "invalid", None
    if text_vector.get("text_field") != TEXT_VECTORIZATION_TEXT_FIELD:
        return "invalid", None
    if text_vector.get("instruction_profile") != RESOURCE_SEARCH_CORPUS_PROFILE:
        return "stale", None
    if text_vector.get("instruction_sha256") != sha256_hex(corpus_instruction_for_resource_search()):
        return "stale", None
    if text_vector.get("text_sha256") != sha256_hex(description):
        return "stale", None
    if text_vector.get("model") != vector_config.get("model"):
        return "stale", None

    dimensions = text_vector.get("dimensions")
    if dimensions != vector_config.get("dimensions"):
        return "stale", None

    try:
        decoded = decode_embedding_string(str(text_vector.get("embedding", "")), int(dimensions))
    except Exception:  # noqa: BLE001
        return "invalid", None
    return "ok", decoded


def lexical_normalized(score: int, max_score: int) -> float:
    if max_score <= 0:
        return 0.0
    return float(score) / float(max_score)


def vector_normalized(score: float | None) -> float | None:
    if score is None:
        return None
    return max(0.0, min(1.0, (float(score) + 1.0) / 2.0))


def final_rank_score(lexical_score: int, max_lexical_score: int, vector_score: float | None) -> float:
    lexical_component = lexical_normalized(lexical_score, max_lexical_score)
    vector_component = vector_normalized(vector_score)
    if vector_component is None:
        return lexical_component
    return (LEXICAL_WEIGHT * lexical_component) + (VECTOR_WEIGHT * vector_component)


def main() -> int:
    args = parse_args()
    hub_root = Path(args.hub).resolve()
    warnings: list[str] = []
    config = load_search_config(hub_root, warnings)

    try:
        vector_config = load_text_vectorization_config(config) if isinstance(config, dict) else None
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"text_vectorization is unavailable: {exc}; continuing with lexical-only search")
        vector_config = None

    try:
        query_embedding, _query_meta = (
            build_query_embedding(config=config, query=args.query, resource_type=args.type)
            if isinstance(config, dict) and vector_config is not None
            else (None, None)
        )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Query vectorization failed: {exc}; continuing with lexical-only search")
        query_embedding = None

    candidates: list[dict[str, Any]] = []
    hard_filters_enabled = has_hard_filters(args)

    for resource_type, dirname in iter_resource_types(args.type):
        type_dir = hub_root / dirname
        index_path = type_dir / "index.json"
        if not index_path.exists():
            warnings.append(f"Missing index.json: {index_path}")
            continue

        try:
            index_data = load_json(index_path)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Failed to load {index_path}: {exc}")
            continue
        if not isinstance(index_data, dict) or not isinstance(index_data.get("resources"), list):
            warnings.append(f"Invalid index root object: {index_path}")
            continue

        for entry in index_data["resources"]:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", ""))
            resource_dir = type_dir / name
            if not resource_dir.exists():
                warnings.append(f"Missing resource directory: {resource_dir}")
                continue

            variations = entry.get("variations", [])
            if not isinstance(variations, list):
                warnings.append(f"Invalid variations list in index entry: {name}")
                continue

            best_variation = choose_best_variation(resource_type, resource_dir, variations, args)
            if hard_filters_enabled and best_variation is None:
                continue

            searchable_text = build_search_text(resource_type, entry)
            lexical_score, lexical_reasons = score_resource(args.query, searchable_text)
            vector_status, corpus_vector = resolve_corpus_vector(entry, vector_config if query_embedding is not None else None)
            vector_score = None
            if query_embedding is not None and corpus_vector is not None:
                vector_score = cosine_similarity(query_embedding, corpus_vector)

            candidates.append(
                {
                    "name": name,
                    "type": resource_type,
                    "index_path": str(index_path.resolve()),
                    "description": entry.get("description", ""),
                    "best_variation": best_variation,
                    "lexical_score": lexical_score,
                    "lexical_reasons": lexical_reasons,
                    "vector_status": vector_status,
                    "vector_score": vector_score,
                }
            )

    if not candidates:
        payload = {
            "ok": True,
            "query": args.query,
            "filters": {
                "type": args.type,
                "require_alpha": args.require_alpha,
                "min_resolution": args.min_resolution,
                "min_fps": args.min_fps,
            },
            "results": [],
            "warnings": warnings,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    max_lexical_score = max(item["lexical_score"] for item in candidates)
    vector_status_counts: dict[str, int] = {}
    results: list[dict[str, Any]] = []
    for item in candidates:
        vector_status = str(item["vector_status"])
        vector_status_counts[vector_status] = vector_status_counts.get(vector_status, 0) + 1
        if item["vector_score"] is None and int(item["lexical_score"]) <= 0:
            continue

        final_score = final_rank_score(
            lexical_score=int(item["lexical_score"]),
            max_lexical_score=max_lexical_score,
            vector_score=item["vector_score"],
        )
        reasons = list(item["lexical_reasons"])
        reasons.append(f"lexical score: {item['lexical_score']}")
        if item["vector_score"] is not None:
            reasons.append(f"vector similarity: {item['vector_score']:.6f}")
        elif vector_status not in {"disabled", "missing_description"}:
            reasons.append(f"vector status: {vector_status}")

        best_variation = item["best_variation"]
        if isinstance(best_variation, dict):
            reasons.append(
                "best variation: "
                + " ".join(
                    str(part)
                    for part in [
                        best_variation.get("resolution", ""),
                        f"{best_variation.get('fps')}fps" if item["type"] == "video" else "",
                        best_variation.get("format", ""),
                        "alpha" if best_variation.get("has_alpha") else "",
                    ]
                    if part
                )
            )

        results.append(
            {
                "name": item["name"],
                "type": item["type"],
                "final_score": final_score,
                "lexical_score": item["lexical_score"],
                "vector_score": item["vector_score"],
                "vector_status": vector_status,
                "match_reasons": reasons,
                "index_path": item["index_path"],
                "description": item["description"],
                "best_variation": best_variation,
            }
        )

    if query_embedding is not None:
        stale_count = vector_status_counts.get("stale", 0)
        missing_count = vector_status_counts.get("missing", 0)
        invalid_count = vector_status_counts.get("invalid", 0)
        if stale_count:
            warnings.append(f"{stale_count} resources have stale text vectors; run repair_hub.py to refresh them")
        if missing_count:
            warnings.append(f"{missing_count} resources are missing text vectors; run repair_hub.py to backfill them")
        if invalid_count:
            warnings.append(f"{invalid_count} resources have invalid text vectors; run repair_hub.py to rebuild them")

    results.sort(
        key=lambda item: (
            -float(item["final_score"]),
            -float(item["vector_score"]) if item["vector_score"] is not None else float("inf"),
            -int(item["lexical_score"]),
            item["type"],
            item["name"],
        )
    )

    payload = {
        "ok": True,
        "query": args.query,
        "filters": {
            "type": args.type,
            "require_alpha": args.require_alpha,
            "min_resolution": args.min_resolution,
            "min_fps": args.min_fps,
        },
        "results": results[: max(args.limit, 0)],
        "warnings": warnings,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
