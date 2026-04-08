#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from common import (
    DEFAULT_DESCRIPTION_LANGUAGE,
    RESOURCE_DIRS,
    contains_ascii_alpha,
    contains_cjk,
    config_path_from_hub,
    description_language_label,
    is_informative_ascii_token,
    iter_resource_types,
    load_json,
    make_variation_path,
    normalize_description_language,
    normalize_text,
    resolution_rank,
)
from llm_clients import get_openai_client
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
BM25_K1 = 1.2
BM25_B = 0.75
PHRASE_MATCH_BONUS = 1.5
FIELD_WEIGHTS = {
    "name": 2.4,
    "description": 1.0,
    "variation": 0.45,
}
ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")
CJK_SEQUENCE_RE = re.compile(r"[\u4e00-\u9fff]+")


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


def build_search_fields(resource_type: str, entry: dict[str, Any]) -> dict[str, str]:
    variation_parts: list[str] = []
    variations = entry.get("variations", [])
    if isinstance(variations, list):
        for variation in variations:
            if isinstance(variation, dict):
                variation_parts.append(stringify_variation(resource_type, variation))
    return {
        "name": str(entry.get("name", "")),
        "description": str(entry.get("description", "")),
        "variation": " ".join(part for part in variation_parts if part),
    }


def _cjk_ngram_tokens(text: str, sizes: tuple[int, ...] = (2, 3)) -> list[str]:
    tokens: list[str] = []
    for sequence in CJK_SEQUENCE_RE.findall(normalize_text(text)):
        if len(sequence) >= 2:
            tokens.append(sequence)
        for size in sizes:
            if len(sequence) < size:
                continue
            for index in range(len(sequence) - size + 1):
                tokens.append(sequence[index : index + size])
    return tokens


def tokenize_lexical_terms(text: str) -> list[str]:
    normalized = normalize_text(text)
    tokens = [token for token in ASCII_TOKEN_RE.findall(normalized) if is_informative_ascii_token(token)]
    tokens.extend(_cjk_ngram_tokens(normalized))
    return tokens


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


def resolve_description_language(config: dict[str, Any] | None, warnings: list[str]) -> str:
    raw = DEFAULT_DESCRIPTION_LANGUAGE
    if isinstance(config, dict):
        raw = config.get("description_language", DEFAULT_DESCRIPTION_LANGUAGE)
    normalized = normalize_description_language(raw)
    if normalized is None:
        warnings.append(
            "Invalid description_language in config; defaulting search language handling to en"
        )
        return DEFAULT_DESCRIPTION_LANGUAGE
    return normalized


def query_contains_description_language(query: str, description_language: str) -> bool:
    if description_language == "en":
        return contains_ascii_alpha(query)
    if description_language == "zh-CN":
        return contains_cjk(query)
    return False


def should_rewrite_query(query: str, description_language: str) -> bool:
    return not query_contains_description_language(query, description_language)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
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
        except json.JSONDecodeError:
            return None
    return None


def rewrite_query_to_description_language(
    *,
    config: dict[str, Any] | None,
    query: str,
    resource_type: str | None,
    description_language: str,
    warnings: list[str],
) -> str:
    if not isinstance(config, dict) or not should_rewrite_query(query, description_language):
        return query

    content_sense = config.get("content_sense")
    if not isinstance(content_sense, dict):
        warnings.append(
            "Query does not contain description_language text but content_sense is unavailable; using original query"
        )
        return query

    api_key_env = content_sense.get("open_ai_api_key_env")
    base_url = content_sense.get("open_ai_base_url")
    model = content_sense.get("model")
    if not all(isinstance(value, str) and value.strip() for value in (api_key_env, base_url, model)):
        warnings.append(
            "Query rewrite skipped because content_sense client config is incomplete; using original query"
        )
        return query

    if resource_type == "image":
        resource_scope = "image"
    elif resource_type == "video":
        resource_scope = "video"
    else:
        resource_scope = "resource"

    prompt = (
        "You rewrite user search queries for a local media resource hub. "
        f"The hub stores {resource_scope} descriptions strictly in {description_language_label(description_language)} "
        f"(description_language={description_language}). "
        "Rewrite the user query into concise natural search text in that language. "
        "Preserve all concrete constraints and technical literals when possible, including alpha/transparent, "
        "formats, resolution, fps, duration, camera motion, timeline hints, style, mood, and usage intent. "
        "Do not add facts that were not requested by the user. "
        'Return only valid JSON with one key: "rewritten_query".'
    )

    try:
        client = get_openai_client(
            api_key_env=str(api_key_env).strip(),
            base_url=str(base_url).strip(),
        )
        response = client.responses.create(
            model=str(model).strip(),
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_text", "text": f"Original query:\n{query}"},
                    ],
                }
            ],
        )
        parsed = _extract_json_object(getattr(response, "output_text", ""))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Query rewrite failed: {exc}; using original query")
        return query

    rewritten = str((parsed or {}).get("rewritten_query", "")).strip()
    if not rewritten:
        warnings.append("Query rewrite returned an empty query; using original query")
        return query
    return rewritten


def build_query_plan(
    *,
    config: dict[str, Any] | None,
    query: str,
    resource_type: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    description_language = resolve_description_language(config, warnings)
    lexical_query = rewrite_query_to_description_language(
        config=config,
        query=query,
        resource_type=resource_type,
        description_language=description_language,
        warnings=warnings,
    )
    variants: list[str] = []
    for candidate in (query, lexical_query):
        normalized = normalize_text(candidate)
        if normalized and normalized not in {normalize_text(item) for item in variants}:
            variants.append(candidate)
    return {
        "description_language": description_language,
        "original_query": query,
        "lexical_query": lexical_query,
        "vector_queries": variants,
        "rewritten_for_alignment": normalize_text(lexical_query) != normalize_text(query),
    }


def build_query_embeddings_for_plan(
    *,
    config: dict[str, Any] | None,
    vector_config: dict[str, Any] | None,
    query_plan: dict[str, Any],
    resource_type: str | None,
    warnings: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(config, dict) or vector_config is None:
        return []

    embeddings: list[dict[str, Any]] = []
    for variant in query_plan.get("vector_queries", []):
        try:
            embedding, meta = build_query_embedding(
                config=config,
                query=str(variant),
                resource_type=resource_type,
            )
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Query vectorization failed for variant {variant!r}: {exc}")
            continue
        if embedding is None or meta is None:
            continue
        embeddings.append(
            {
                "query": str(variant),
                "embedding": embedding,
                "meta": meta,
            }
        )
    return embeddings


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
    if text_vector.get("base_url") != vector_config.get("base_url"):
        return "stale", None
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


def build_lexical_document(resource_type: str, entry: dict[str, Any]) -> dict[str, Any]:
    field_texts = build_search_fields(resource_type, entry)
    field_counters = {name: Counter(tokenize_lexical_terms(text)) for name, text in field_texts.items()}
    field_lengths = {name: sum(counter.values()) for name, counter in field_counters.items()}
    document_terms: set[str] = set()
    for counter in field_counters.values():
        document_terms.update(counter.keys())
    normalized_fields = {name: normalize_text(text) for name, text in field_texts.items()}
    return {
        "field_texts": field_texts,
        "field_counters": field_counters,
        "field_lengths": field_lengths,
        "document_terms": document_terms,
        "normalized_fields": normalized_fields,
    }


def build_lexical_corpus(documents: list[dict[str, Any]]) -> dict[str, Any]:
    doc_freq: Counter[str] = Counter()
    field_length_totals = {field_name: 0.0 for field_name in FIELD_WEIGHTS}
    for document in documents:
        for term in document["lexical_doc"]["document_terms"]:
            doc_freq[term] += 1
        for field_name in FIELD_WEIGHTS:
            field_length_totals[field_name] += float(document["lexical_doc"]["field_lengths"].get(field_name, 0))
    document_count = len(documents)
    avg_field_lengths = {
        field_name: (field_length_totals[field_name] / document_count) if document_count > 0 else 0.0
        for field_name in FIELD_WEIGHTS
    }
    return {
        "document_count": document_count,
        "doc_freq": doc_freq,
        "avg_field_lengths": avg_field_lengths,
    }


def _idf(document_count: int, doc_freq: int) -> float:
    if document_count <= 0 or doc_freq <= 0:
        return 0.0
    return math.log1p((document_count - doc_freq + 0.5) / (doc_freq + 0.5))


def score_resource(
    query_text: str,
    lexical_doc: dict[str, Any],
    lexical_corpus: dict[str, Any],
) -> tuple[float, list[str]]:
    query_tokens = tokenize_lexical_terms(query_text)
    if not query_tokens:
        return 0.0, []

    query_term_set = set(query_tokens)
    score = 0.0
    term_contributions: dict[str, float] = {}
    phrase_fields: list[str] = []
    document_count = int(lexical_corpus["document_count"])
    doc_freq: Counter[str] = lexical_corpus["doc_freq"]
    avg_field_lengths: dict[str, float] = lexical_corpus["avg_field_lengths"]

    for term in query_term_set:
        term_idf = _idf(document_count, int(doc_freq.get(term, 0)))
        if term_idf <= 0.0:
            continue
        for field_name, field_weight in FIELD_WEIGHTS.items():
            counter: Counter[str] = lexical_doc["field_counters"][field_name]
            tf = float(counter.get(term, 0))
            if tf <= 0.0:
                continue
            field_length = float(lexical_doc["field_lengths"].get(field_name, 0))
            avg_length = max(float(avg_field_lengths.get(field_name, 0.0)), 1.0)
            denom = tf + BM25_K1 * (1.0 - BM25_B + BM25_B * (field_length / avg_length))
            if denom <= 0.0:
                continue
            contribution = field_weight * term_idf * ((tf * (BM25_K1 + 1.0)) / denom)
            score += contribution
            term_contributions[term] = term_contributions.get(term, 0.0) + contribution

    normalized_query = normalize_text(query_text)
    if len(query_term_set) >= 2 and normalized_query:
        for field_name, normalized_text in lexical_doc["normalized_fields"].items():
            if normalized_query in normalized_text:
                phrase_fields.append(field_name)
                score += FIELD_WEIGHTS[field_name] * PHRASE_MATCH_BONUS

    reasons: list[str] = []
    if phrase_fields:
        reasons.append("full query matched fields: " + ", ".join(sorted(phrase_fields)))
    if term_contributions:
        top_terms = sorted(term_contributions.items(), key=lambda item: (-item[1], item[0]))[:4]
        reasons.append("matched lexical terms: " + ", ".join(term for term, _score in top_terms))
    return score, reasons[:4]


def lexical_normalized(score: float, max_score: float) -> float:
    if max_score <= 0.0:
        return 0.0
    return float(score) / float(max_score)


def vector_normalized(score: float | None) -> float | None:
    if score is None:
        return None
    return max(0.0, min(1.0, (float(score) + 1.0) / 2.0))


def final_rank_score(lexical_score: float, max_lexical_score: float, vector_score: float | None) -> float:
    lexical_component = lexical_normalized(lexical_score, max_lexical_score)
    vector_component = vector_normalized(vector_score)
    if vector_component is None:
        return lexical_component
    return (LEXICAL_WEIGHT * lexical_component) + (VECTOR_WEIGHT * vector_component)


def best_vector_match(
    query_embeddings: list[dict[str, Any]],
    corpus_vector: tuple[float, ...] | None,
) -> tuple[float | None, str | None]:
    if corpus_vector is None or not query_embeddings:
        return None, None
    best_score: float | None = None
    best_query: str | None = None
    for item in query_embeddings:
        score = cosine_similarity(item["embedding"], corpus_vector)
        if best_score is None or score > best_score:
            best_score = score
            best_query = str(item["query"])
    return best_score, best_query


def main() -> int:
    args = parse_args()
    hub_root = Path(args.hub).resolve()
    warnings: list[str] = []
    config = load_search_config(hub_root, warnings)

    query_plan = build_query_plan(
        config=config,
        query=args.query,
        resource_type=args.type,
        warnings=warnings,
    )

    try:
        vector_config = load_text_vectorization_config(config) if isinstance(config, dict) else None
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"text_vectorization is unavailable: {exc}; continuing with lexical-only search")
        vector_config = None

    query_embeddings = build_query_embeddings_for_plan(
        config=config,
        vector_config=vector_config,
        query_plan=query_plan,
        resource_type=args.type,
        warnings=warnings,
    )

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

            candidates.append(
                {
                    "name": name,
                    "type": resource_type,
                    "index_path": str(index_path.resolve()),
                    "description": entry.get("description", ""),
                    "best_variation": best_variation,
                    "lexical_doc": build_lexical_document(resource_type, entry),
                    "entry": entry,
                }
            )

    if not candidates:
        payload = {
            "ok": True,
            "query": args.query,
            "query_plan": query_plan,
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

    lexical_corpus = build_lexical_corpus(candidates)

    for item in candidates:
        lexical_score, lexical_reasons = score_resource(
            str(query_plan["lexical_query"]),
            item["lexical_doc"],
            lexical_corpus,
        )
        vector_status, corpus_vector = resolve_corpus_vector(
            item["entry"],
            vector_config if query_embeddings else None,
        )
        vector_score, matched_query = best_vector_match(query_embeddings, corpus_vector)
        item["lexical_score"] = lexical_score
        item["lexical_reasons"] = lexical_reasons
        item["vector_status"] = vector_status
        item["vector_score"] = vector_score
        item["vector_query"] = matched_query

    max_lexical_score = max(float(item.get("lexical_score", 0.0)) for item in candidates)
    vector_status_counts: dict[str, int] = {}
    results: list[dict[str, Any]] = []
    for item in candidates:
        vector_status = str(item["vector_status"])
        vector_status_counts[vector_status] = vector_status_counts.get(vector_status, 0) + 1
        lexical_score = float(item["lexical_score"])
        vector_score = item["vector_score"]
        if vector_score is None and lexical_score <= 0.0:
            continue

        final_score = final_rank_score(
            lexical_score=lexical_score,
            max_lexical_score=max_lexical_score,
            vector_score=vector_score,
        )
        reasons = list(item["lexical_reasons"])
        reasons.append(f"lexical score: {lexical_score:.6f}")
        if vector_score is not None:
            reasons.append(f"vector similarity: {vector_score:.6f}")
            if item.get("vector_query") and normalize_text(str(item["vector_query"])) != normalize_text(args.query):
                reasons.append(f"vector query aligned to {query_plan['description_language']}")
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
                "lexical_score": lexical_score,
                "vector_score": vector_score,
                "vector_status": vector_status,
                "match_reasons": reasons,
                "index_path": item["index_path"],
                "description": item["description"],
                "best_variation": best_variation,
            }
        )

    if query_embeddings:
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
            -float(item["lexical_score"]),
            item["type"],
            item["name"],
        )
    )

    payload = {
        "ok": True,
        "query": args.query,
        "query_plan": query_plan,
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
