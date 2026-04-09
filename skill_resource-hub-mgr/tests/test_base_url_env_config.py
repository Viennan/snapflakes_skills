#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import find_resources
import text_vectorization
import validate_hub


class BaseUrlEnvConfigTests(unittest.TestCase):
    def test_text_vectorization_resolves_base_url_from_env(self) -> None:
        config = {
            "text_vectorization": {
                "api_key_env": "ARK_API_KEY",
                "base_url_env": "ARK_BASE_URL",
                "model": "doubao-embedding-vision-251215",
                "dimensions": 512,
            }
        }

        with patch.dict(os.environ, {"ARK_BASE_URL": "https://ark.example.invalid/api/v3"}, clear=False):
            loaded = text_vectorization.load_text_vectorization_config(config)

        self.assertIsNotNone(loaded)
        self.assertEqual("https://ark.example.invalid/api/v3", loaded["base_url"])
        self.assertEqual("ARK_BASE_URL", loaded["base_url_env"])

    def test_text_vectorization_schema_validation_does_not_require_env_value(self) -> None:
        config = {
            "text_vectorization": {
                "api_key_env": "ARK_API_KEY",
                "base_url_env": "ARK_BASE_URL",
            }
        }

        loaded = text_vectorization.load_text_vectorization_config(config, resolve_env=False)

        self.assertIsNotNone(loaded)
        self.assertEqual("ARK_BASE_URL", loaded["base_url_env"])
        self.assertNotIn("base_url", loaded)

    def test_validate_config_accepts_content_sense_base_url_env(self) -> None:
        config = {
            "description_language": "en",
            "content_sense": {
                "open_ai_api_key_env": "OPENAI_API_KEY",
                "open_ai_base_url_env": "OPENAI_BASE_URL",
                "model": "gpt-4.1-mini",
                "video_understanding_mode": "frames",
            },
            "text_vectorization": {
                "api_key_env": "ARK_API_KEY",
                "base_url_env": "ARK_BASE_URL",
            },
            "video": {"with_description": {"resolution": "720p"}},
            "image": {},
        }

        errors: list[str] = []
        validate_hub.validate_config(config, errors)

        self.assertEqual([], errors)

    def test_query_rewrite_uses_resolved_content_sense_base_url(self) -> None:
        config = {
            "description_language": "zh-CN",
            "content_sense": {
                "open_ai_api_key_env": "OPENAI_API_KEY",
                "open_ai_base_url_env": "OPENAI_BASE_URL",
                "model": "gpt-4.1-mini",
            },
        }
        warnings: list[str] = []
        fake_client = Mock()
        fake_client.responses.create.return_value = SimpleNamespace(
            output_text='{"rewritten_query":"蓝色加载动画"}'
        )

        with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://compatible.example.invalid/v1"}, clear=False):
            with patch.object(find_resources, "get_openai_client", return_value=fake_client) as client_factory:
                rewritten = find_resources.rewrite_query_to_description_language(
                    config=config,
                    query="blue loading animation",
                    resource_type="video",
                    description_language="zh-CN",
                    warnings=warnings,
                )

        client_factory.assert_called_once_with(
            api_key_env="OPENAI_API_KEY",
            base_url="https://compatible.example.invalid/v1",
        )
        self.assertEqual("蓝色加载动画", rewritten)
        self.assertEqual([], warnings)


if __name__ == "__main__":
    unittest.main()
