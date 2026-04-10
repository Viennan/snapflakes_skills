#!/usr/bin/env python3
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import add_resource as add_resource_script
import find_resources as find_resources_script
import init_hub as init_hub_script
import remove_resource as remove_resource_script
import repair_hub as repair_hub_script
import update_config as update_config_script
import validate_hub as validate_hub_script


class ScriptHelpTests(unittest.TestCase):
    def assert_help_contains(
        self,
        parse_args_func,
        argv: list[str],
        expected_substrings: list[str],
    ) -> None:
        stdout = io.StringIO()
        with patch.object(sys, "argv", argv):
            with redirect_stdout(stdout):
                with self.assertRaises(SystemExit) as exc:
                    parse_args_func()

        self.assertEqual(0, exc.exception.code)
        help_text = stdout.getvalue()
        for expected in expected_substrings:
            self.assertIn(expected, help_text)

    def test_init_help_is_meaningful(self) -> None:
        self.assert_help_contains(
            init_hub_script.parse_args,
            ["init_hub.py", "--help"],
            ["--hub HUB", "Examples:"],
        )

    def test_add_help_is_meaningful(self) -> None:
        self.assert_help_contains(
            add_resource_script.parse_args,
            ["add_resource.py", "--help"],
            ["--source SOURCE", "--name NAME", "Examples:"],
        )

    def test_remove_help_is_meaningful(self) -> None:
        self.assert_help_contains(
            remove_resource_script.parse_args,
            ["remove_resource.py", "--help"],
            ["--name NAME", "--type {video,image}", "Examples:"],
        )

    def test_repair_help_is_meaningful(self) -> None:
        self.assert_help_contains(
            repair_hub_script.parse_args,
            ["repair_hub.py", "--help"],
            ["--hub HUB", "Examples:"],
        )

    def test_validate_help_is_meaningful(self) -> None:
        self.assert_help_contains(
            validate_hub_script.parse_args,
            ["validate_hub.py", "--help"],
            ["--hub HUB", "HUB_ROOT", "Examples:"],
        )

    def test_find_help_is_meaningful(self) -> None:
        self.assert_help_contains(
            find_resources_script.parse_args,
            ["find_resources.py", "--help"],
            [
                "--query QUERY",
                "--require-alpha",
                "--min-resolution {360p,480p,540p,720p,1080p,2k,4k,8k}",
                "Examples:",
            ],
        )

    def test_update_config_help_is_meaningful(self) -> None:
        self.assert_help_contains(
            update_config_script.parse_args,
            ["update_config.py", "--help"],
            ["--set PATH VALUE", "--delete PATH", "Examples:"],
        )


if __name__ == "__main__":
    unittest.main()
