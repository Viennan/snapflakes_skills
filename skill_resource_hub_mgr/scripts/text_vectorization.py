#!/usr/bin/env python3
from __future__ import annotations

import base64
import binascii
import hashlib
import struct
from typing import Any

from common import HubError
from llm_clients import get_ark_client

TEXT_VECTORIZATION_PROVIDER = "volcengine_ark"
TEXT_VECTORIZATION_ENCODING = "base64-f32le"
TEXT_VECTORIZATION_TEXT_FIELD = "description"
DEFAULT_TEXT_VECTORIZATION_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
TEXT_VECTORIZATION_MODEL = "doubao-embedding-vision-251215"
DEFAULT_TEXT_VECTORIZATION_DIMENSIONS = 1024
RESOURCE_SEARCH_QUERY_PROFILE = "resource_search_query_text_v1"
RESOURCE_SEARCH_CORPUS_PROFILE = "resource_search_corpus_text_v1"


def load_text_vectorization_config(config: dict[str, Any]) -> dict[str, Any] | None:
    raw = config.get("text_vectorization")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise HubError("text_vectorization must be an object when present")

    api_key_env = raw.get("api_key_env")
    if not isinstance(api_key_env, str) or not api_key_env.strip():
        raise HubError("text_vectorization.api_key_env must be a non-empty string")

    base_url = raw.get("base_url", DEFAULT_TEXT_VECTORIZATION_BASE_URL)
    if not isinstance(base_url, str) or not base_url.strip():
        raise HubError("text_vectorization.base_url must be a non-empty string")

    model = raw.get("model", TEXT_VECTORIZATION_MODEL)
    if not isinstance(model, str) or not model.strip():
        raise HubError("text_vectorization.model must be a non-empty string")

    dimensions = raw.get("dimensions", DEFAULT_TEXT_VECTORIZATION_DIMENSIONS)
    if not isinstance(dimensions, int) or dimensions <= 0:
        raise HubError("text_vectorization.dimensions must be a positive integer")

    return {
        "api_key_env": api_key_env.strip(),
        "base_url": base_url.strip(),
        "model": model.strip(),
        "dimensions": dimensions,
    }


def corpus_instruction_for_resource_search() -> str:
    return "Instruction:Compress the text into one word.\nQuery:"


def query_instruction_for_resource_search(resource_type: str | None = None) -> str:
    if resource_type == "image":
        instruction = (
            "Retrieve the resource description text that best matches the user's description "
            "of image content, style, usage, atmosphere, and subjective preferences"
        )
    elif resource_type == "video":
        instruction = (
            "Retrieve the resource description text that best matches the user's description "
            "of video content, temporal changes, style, usage, atmosphere, and subjective preferences"
        )
    else:
        instruction = (
            "Retrieve the resource description text that best matches the user's description "
            "of resource content, style, usage, atmosphere, and subjective preferences"
        )
    return f"Target_modality: text.\nInstruction:{instruction}\nQuery:"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_hex(text: str) -> str:
    return _sha256_text(text)


def _load_client(api_key_env: str, base_url: str):
    return get_ark_client(api_key_env=api_key_env, base_url=base_url)


def _extract_embedding(response: Any) -> list[float]:
    data = getattr(response, "data", None)
    embedding = getattr(data, "embedding", None) if data is not None else None
    if embedding is None and isinstance(response, dict):
        data = response.get("data")
        if isinstance(data, dict):
            embedding = data.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise HubError("Text vectorization response did not contain a valid embedding")
    try:
        return [float(value) for value in embedding]
    except (TypeError, ValueError) as exc:
        raise HubError("Text vectorization response contained non-numeric embedding values") from exc


def _embed_text(
    *,
    vector_config: dict[str, Any],
    text: str,
    instruction: str,
) -> list[float]:
    client = _load_client(
        str(vector_config["api_key_env"]),
        str(vector_config["base_url"]),
    )
    try:
        response = client.multimodal_embeddings.create(
            model=str(vector_config["model"]),
            encoding_format="float",
            dimensions=int(vector_config["dimensions"]),
            input=[{"type": "text", "text": text}],
            extra_body={"instructions": instruction},
        )
    except Exception as exc:  # noqa: BLE001
        raise HubError(f"Text vectorization failed: {exc}") from exc
    embedding = _extract_embedding(response)
    expected_dimensions = int(vector_config["dimensions"])
    if len(embedding) != expected_dimensions:
        raise HubError(
            "Text vectorization returned an unexpected dimension: "
            f"expected {expected_dimensions}, got {len(embedding)}"
        )
    return embedding


def encode_embedding_string(embedding: list[float]) -> str:
    packed = struct.pack(f"<{len(embedding)}f", *embedding)
    return base64.b64encode(packed).decode("ascii")


def decode_embedding_string(encoded: str, dimensions: int) -> tuple[float, ...]:
    if not isinstance(encoded, str) or not encoded.strip():
        raise HubError("text_vector.embedding must be a non-empty string")
    if not isinstance(dimensions, int) or dimensions <= 0:
        raise HubError("text_vector.dimensions must be a positive integer")
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HubError(f"Invalid base64 embedding payload: {exc}") from exc
    expected_size = dimensions * 4
    if len(raw) != expected_size:
        raise HubError(
            f"Decoded embedding size mismatch: expected {expected_size} bytes, got {len(raw)}"
        )
    return struct.unpack(f"<{dimensions}f", raw)


def cosine_similarity(left: tuple[float, ...] | list[float], right: tuple[float, ...] | list[float]) -> float:
    if len(left) != len(right):
        raise HubError("Cannot compute cosine similarity for embeddings with different dimensions")
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for lhs, rhs in zip(left, right):
        dot += float(lhs) * float(rhs)
        left_norm += float(lhs) * float(lhs)
        right_norm += float(rhs) * float(rhs)
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / ((left_norm ** 0.5) * (right_norm ** 0.5))


def _vector_metadata(
    *,
    vector_config: dict[str, Any],
    description: str,
    instruction: str,
    instruction_profile: str,
) -> dict[str, Any]:
    return {
        "provider": TEXT_VECTORIZATION_PROVIDER,
        "base_url": str(vector_config["base_url"]),
        "model": str(vector_config["model"]),
        "dimensions": int(vector_config["dimensions"]),
        "encoding": TEXT_VECTORIZATION_ENCODING,
        "text_field": TEXT_VECTORIZATION_TEXT_FIELD,
        "text_sha256": _sha256_text(description),
        "instruction_profile": instruction_profile,
        "instruction_sha256": _sha256_text(instruction),
    }


def _existing_vector_matches(existing_vector: Any, metadata: dict[str, Any]) -> bool:
    if not isinstance(existing_vector, dict):
        return False
    for key, value in metadata.items():
        if existing_vector.get(key) != value:
            return False
    try:
        decode_embedding_string(str(existing_vector.get("embedding", "")), int(metadata["dimensions"]))
    except HubError:
        return False
    return True


def build_description_text_vector(
    *,
    config: dict[str, Any],
    description: str,
    existing_vector: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    description_text = str(description or "").strip()
    if not description_text:
        return None

    vector_config = load_text_vectorization_config(config)
    if vector_config is None:
        return None

    instruction = corpus_instruction_for_resource_search()
    metadata = _vector_metadata(
        vector_config=vector_config,
        description=description_text,
        instruction=instruction,
        instruction_profile=RESOURCE_SEARCH_CORPUS_PROFILE,
    )
    if _existing_vector_matches(existing_vector, metadata):
        return dict(existing_vector)

    embedding = _embed_text(
        vector_config=vector_config,
        text=description_text,
        instruction=instruction,
    )
    return {
        **metadata,
        "embedding": encode_embedding_string(embedding),
    }


def build_query_embedding(
    *,
    config: dict[str, Any],
    query: str,
    resource_type: str | None = None,
) -> tuple[list[float], dict[str, Any]] | tuple[None, None]:
    query_text = str(query or "").strip()
    if not query_text:
        return None, None

    vector_config = load_text_vectorization_config(config)
    if vector_config is None:
        return None, None

    instruction = query_instruction_for_resource_search(resource_type)
    embedding = _embed_text(
        vector_config=vector_config,
        text=query_text,
        instruction=instruction,
    )
    return embedding, {
        "provider": TEXT_VECTORIZATION_PROVIDER,
        "base_url": str(vector_config["base_url"]),
        "model": str(vector_config["model"]),
        "dimensions": int(vector_config["dimensions"]),
        "instruction_profile": RESOURCE_SEARCH_QUERY_PROFILE,
        "instruction_sha256": _sha256_text(instruction),
    }
