#!/usr/bin/env python3
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from common import HubError


@lru_cache(maxsize=16)
def _cached_openai_client(api_key: str, base_url: str) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - import failure depends on environment
        raise HubError(
            "The openai package is required for content sensing. "
            "Install dependencies via scripts/run_python.sh."
        ) from exc
    return OpenAI(api_key=api_key, base_url=base_url)


@lru_cache(maxsize=16)
def _cached_ark_client(api_key: str, base_url: str) -> Any:
    try:
        from volcenginesdkarkruntime import Ark
    except ImportError as exc:  # pragma: no cover - import failure depends on environment
        raise HubError(
            "The volcengine Ark SDK is required for text vectorization. "
            "Install dependencies via scripts/run_python.sh."
        ) from exc
    return Ark(api_key=api_key, base_url=base_url)


def get_openai_client(*, api_key_env: str, base_url: str) -> Any:
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise HubError(f"Environment variable {api_key_env} is not set")
    return _cached_openai_client(api_key, base_url)


def get_ark_client(*, api_key_env: str, base_url: str) -> Any:
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise HubError(f"Environment variable {api_key_env} is not set")
    return _cached_ark_client(api_key, base_url)
