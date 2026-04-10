#!/usr/bin/env python3
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import validate_hub as validate_hub_script


class ValidateHubCliTests(unittest.TestCase):
    def test_parse_args_accepts_positional_hub_root(self) -> None:
        with patch.object(sys, "argv", ["validate_hub.py", "/tmp/hub"]):
            args = validate_hub_script.parse_args()

        self.assertEqual("/tmp/hub", args.hub_root)

    def test_parse_args_accepts_hub_flag(self) -> None:
        with patch.object(sys, "argv", ["validate_hub.py", "--hub", "/tmp/hub"]):
            args = validate_hub_script.parse_args()

        self.assertEqual("/tmp/hub", args.hub_root)

    def test_parse_args_rejects_both_hub_forms(self) -> None:
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["validate_hub.py", "--hub", "/tmp/one", "/tmp/two"]):
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exc:
                    validate_hub_script.parse_args()

        self.assertEqual(2, exc.exception.code)
        self.assertIn("either positionally or with --hub", stderr.getvalue())

    def test_parse_args_requires_a_hub_path(self) -> None:
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["validate_hub.py"]):
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exc:
                    validate_hub_script.parse_args()

        self.assertEqual(2, exc.exception.code)
        self.assertIn("a hub path is required", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
