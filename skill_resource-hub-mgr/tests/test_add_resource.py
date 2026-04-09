#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import call, patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import add_resource as add_resource_script
from common import HubError


class AddResourceCliTests(unittest.TestCase):
    def test_single_source_keeps_single_result_shape(self) -> None:
        payload = {"ok": True, "action": "add", "name": "sample"}
        stdout = io.StringIO()

        with patch.object(
            add_resource_script,
            "add_resource",
            return_value=payload,
        ) as add_resource_mock:
            with patch.object(
                sys,
                "argv",
                ["add_resource.py", "--hub", "/tmp/hub", "--source", "/tmp/a.png"],
            ):
                with redirect_stdout(stdout):
                    exit_code = add_resource_script.main()

        self.assertEqual(0, exit_code)
        self.assertEqual(payload, json.loads(stdout.getvalue()))
        add_resource_mock.assert_called_once_with(
            Path("/tmp/hub"),
            Path("/tmp/a.png"),
            resource_name=None,
        )

    def test_multi_source_imports_sequentially(self) -> None:
        stdout = io.StringIO()
        first = {"ok": True, "action": "add", "name": "first"}
        second = {"ok": True, "action": "add", "name": "second"}

        with patch.object(
            add_resource_script,
            "add_resource",
            side_effect=[first, second],
        ) as add_resource_mock:
            with patch.object(
                sys,
                "argv",
                [
                    "add_resource.py",
                    "--hub",
                    "/tmp/hub",
                    "--source",
                    "/tmp/a.png",
                    "--source",
                    "/tmp/b.png",
                ],
            ):
                with redirect_stdout(stdout):
                    exit_code = add_resource_script.main()

        self.assertEqual(0, exit_code)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual("add_batch", payload["action"])
        self.assertEqual(2, payload["imported_count"])
        self.assertEqual(0, payload["failed_count"])
        self.assertEqual([first, second], payload["results"])
        self.assertEqual([], payload["errors"])
        self.assertEqual(
            [
                call(Path("/tmp/hub"), Path("/tmp/a.png"), resource_name=None),
                call(Path("/tmp/hub"), Path("/tmp/b.png"), resource_name=None),
            ],
            add_resource_mock.call_args_list,
        )

    def test_multi_source_accepts_matching_names(self) -> None:
        stdout = io.StringIO()

        with patch.object(
            add_resource_script,
            "add_resource",
            side_effect=[
                {"ok": True, "action": "add", "name": "first"},
                {"ok": True, "action": "add", "name": "second"},
            ],
        ) as add_resource_mock:
            with patch.object(
                sys,
                "argv",
                [
                    "add_resource.py",
                    "--hub",
                    "/tmp/hub",
                    "--source",
                    "/tmp/a.png",
                    "--name",
                    "alpha",
                    "--source",
                    "/tmp/b.png",
                    "--name",
                    "beta",
                ],
            ):
                with redirect_stdout(stdout):
                    exit_code = add_resource_script.main()

        self.assertEqual(0, exit_code)
        self.assertEqual(
            [
                call(Path("/tmp/hub"), Path("/tmp/a.png"), resource_name="alpha"),
                call(Path("/tmp/hub"), Path("/tmp/b.png"), resource_name="beta"),
            ],
            add_resource_mock.call_args_list,
        )

    def test_multi_source_reports_partial_failures(self) -> None:
        stdout = io.StringIO()

        with patch.object(
            add_resource_script,
            "add_resource",
            side_effect=[
                {"ok": True, "action": "add", "name": "first"},
                HubError("broken asset"),
                {"ok": True, "action": "add", "name": "third"},
            ],
        ):
            with patch.object(
                sys,
                "argv",
                [
                    "add_resource.py",
                    "--hub",
                    "/tmp/hub",
                    "--source",
                    "/tmp/a.png",
                    "--source",
                    "/tmp/b.png",
                    "--source",
                    "/tmp/c.png",
                ],
            ):
                with redirect_stdout(stdout):
                    exit_code = add_resource_script.main()

        self.assertEqual(1, exit_code)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(2, payload["imported_count"])
        self.assertEqual(1, payload["failed_count"])
        self.assertEqual("/tmp/b.png", payload["errors"][0]["source"])
        self.assertEqual("broken asset", payload["errors"][0]["error"])

    def test_name_count_must_match_source_count(self) -> None:
        stderr = io.StringIO()
        with patch.object(
            sys,
            "argv",
            [
                "add_resource.py",
                "--hub",
                "/tmp/hub",
                "--source",
                "/tmp/a.png",
                "--source",
                "/tmp/b.png",
                "--name",
                "alpha",
            ],
        ):
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exc:
                    add_resource_script.parse_args()

        self.assertEqual(2, exc.exception.code)


if __name__ == "__main__":
    unittest.main()
