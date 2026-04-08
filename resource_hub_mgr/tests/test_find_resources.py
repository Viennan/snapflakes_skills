#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import find_resources


class QueryRewriteGateTests(unittest.TestCase):
    def test_query_contains_description_language_for_chinese_repo(self) -> None:
        self.assertTrue(find_resources.query_contains_description_language("蓝色加载动画", "zh-CN"))
        self.assertFalse(find_resources.query_contains_description_language("blue loading animation", "zh-CN"))
        self.assertTrue(find_resources.query_contains_description_language("蓝色 loading 动画", "zh-CN"))

    def test_query_contains_description_language_for_english_repo(self) -> None:
        self.assertTrue(find_resources.query_contains_description_language("blue loading animation", "en"))
        self.assertFalse(find_resources.query_contains_description_language("蓝色加载动画", "en"))
        self.assertTrue(find_resources.query_contains_description_language("透明 png", "en"))

    def test_should_rewrite_only_when_query_lacks_repo_language(self) -> None:
        self.assertFalse(find_resources.should_rewrite_query("蓝色加载动画", "zh-CN"))
        self.assertTrue(find_resources.should_rewrite_query("blue loading animation", "zh-CN"))
        self.assertFalse(find_resources.should_rewrite_query("蓝色 loading 动画", "zh-CN"))
        self.assertFalse(find_resources.should_rewrite_query("blue loading animation", "en"))
        self.assertTrue(find_resources.should_rewrite_query("蓝色加载动画", "en"))
        self.assertFalse(find_resources.should_rewrite_query("透明 png", "en"))


class BuildQueryPlanTests(unittest.TestCase):
    def test_query_plan_keeps_original_query_when_repo_language_present(self) -> None:
        warnings: list[str] = []
        config = {"description_language": "zh-CN"}

        query_plan = find_resources.build_query_plan(
            config=config,
            query="蓝色 loading 动画",
            resource_type="video",
            warnings=warnings,
        )

        self.assertEqual("蓝色 loading 动画", query_plan["original_query"])
        self.assertEqual("蓝色 loading 动画", query_plan["lexical_query"])
        self.assertEqual(["蓝色 loading 动画"], query_plan["vector_queries"])
        self.assertFalse(query_plan["rewritten_for_alignment"])
        self.assertEqual([], warnings)

    def test_query_plan_tracks_rewritten_variant_when_alignment_occurs(self) -> None:
        warnings: list[str] = []
        config = {"description_language": "zh-CN", "content_sense": {}}

        with patch.object(
            find_resources,
            "rewrite_query_to_description_language",
            return_value="蓝色 加载 动画",
        ) as rewrite_mock:
            query_plan = find_resources.build_query_plan(
                config=config,
                query="blue loading animation",
                resource_type="video",
                warnings=warnings,
            )

        rewrite_mock.assert_called_once_with(
            config=config,
            query="blue loading animation",
            resource_type="video",
            description_language="zh-CN",
            warnings=warnings,
        )
        self.assertEqual("blue loading animation", query_plan["original_query"])
        self.assertEqual("蓝色 加载 动画", query_plan["lexical_query"])
        self.assertEqual(
            ["blue loading animation", "蓝色 加载 动画"],
            query_plan["vector_queries"],
        )
        self.assertTrue(query_plan["rewritten_for_alignment"])
        self.assertEqual([], warnings)

    def test_query_plan_deduplicates_same_rewritten_query(self) -> None:
        warnings: list[str] = []
        config = {"description_language": "en"}

        with patch.object(
            find_resources,
            "rewrite_query_to_description_language",
            return_value="blue loading animation",
        ):
            query_plan = find_resources.build_query_plan(
                config=config,
                query="blue loading animation",
                resource_type="video",
                warnings=warnings,
            )

        self.assertEqual(["blue loading animation"], query_plan["vector_queries"])
        self.assertFalse(query_plan["rewritten_for_alignment"])


if __name__ == "__main__":
    unittest.main()
