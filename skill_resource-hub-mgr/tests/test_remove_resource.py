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

import remove_resource as remove_resource_script
from common import HubError


class RemoveResourceCliTests(unittest.TestCase):
    def test_single_name_keeps_single_result_shape(self) -> None:
        payload = {"ok": True, "action": "remove", "name": "sample"}
        stdout = io.StringIO()

        with patch.object(
            remove_resource_script,
            "remove_resource",
            return_value=payload,
        ) as remove_resource_mock:
            with patch.object(
                sys,
                "argv",
                ["remove_resource.py", "--hub", "/tmp/hub", "--name", "alpha"],
            ):
                with redirect_stdout(stdout):
                    exit_code = remove_resource_script.main()

        self.assertEqual(0, exit_code)
        self.assertEqual(payload, json.loads(stdout.getvalue()))
        remove_resource_mock.assert_called_once_with(
            Path("/tmp/hub"),
            resource_name="alpha",
            resource_type=None,
        )

    def test_multi_name_removes_sequentially(self) -> None:
        stdout = io.StringIO()
        first = {"ok": True, "action": "remove", "name": "alpha"}
        second = {"ok": True, "action": "remove", "name": "beta"}

        with patch.object(
            remove_resource_script,
            "remove_resource",
            side_effect=[first, second],
        ) as remove_resource_mock:
            with patch.object(
                sys,
                "argv",
                [
                    "remove_resource.py",
                    "--hub",
                    "/tmp/hub",
                    "--name",
                    "alpha",
                    "--name",
                    "beta",
                ],
            ):
                with redirect_stdout(stdout):
                    exit_code = remove_resource_script.main()

        self.assertEqual(0, exit_code)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual("remove_batch", payload["action"])
        self.assertEqual(2, payload["removed_count"])
        self.assertEqual(0, payload["failed_count"])
        self.assertEqual([first, second], payload["results"])
        self.assertEqual([], payload["errors"])
        self.assertEqual(
            [
                call(Path("/tmp/hub"), resource_name="alpha", resource_type=None),
                call(Path("/tmp/hub"), resource_name="beta", resource_type=None),
            ],
            remove_resource_mock.call_args_list,
        )

    def test_single_type_can_apply_to_all_names(self) -> None:
        stdout = io.StringIO()

        with patch.object(
            remove_resource_script,
            "remove_resource",
            side_effect=[
                {"ok": True, "action": "remove", "name": "alpha"},
                {"ok": True, "action": "remove", "name": "beta"},
            ],
        ) as remove_resource_mock:
            with patch.object(
                sys,
                "argv",
                [
                    "remove_resource.py",
                    "--hub",
                    "/tmp/hub",
                    "--name",
                    "alpha",
                    "--name",
                    "beta",
                    "--type",
                    "image",
                ],
            ):
                with redirect_stdout(stdout):
                    exit_code = remove_resource_script.main()

        self.assertEqual(0, exit_code)
        self.assertEqual(
            [
                call(Path("/tmp/hub"), resource_name="alpha", resource_type="image"),
                call(Path("/tmp/hub"), resource_name="beta", resource_type="image"),
            ],
            remove_resource_mock.call_args_list,
        )

    def test_matching_type_count_is_supported(self) -> None:
        stdout = io.StringIO()

        with patch.object(
            remove_resource_script,
            "remove_resource",
            side_effect=[
                {"ok": True, "action": "remove", "name": "alpha"},
                {"ok": True, "action": "remove", "name": "beta"},
            ],
        ) as remove_resource_mock:
            with patch.object(
                sys,
                "argv",
                [
                    "remove_resource.py",
                    "--hub",
                    "/tmp/hub",
                    "--name",
                    "alpha",
                    "--type",
                    "image",
                    "--name",
                    "beta",
                    "--type",
                    "video",
                ],
            ):
                with redirect_stdout(stdout):
                    exit_code = remove_resource_script.main()

        self.assertEqual(0, exit_code)
        self.assertEqual(
            [
                call(Path("/tmp/hub"), resource_name="alpha", resource_type="image"),
                call(Path("/tmp/hub"), resource_name="beta", resource_type="video"),
            ],
            remove_resource_mock.call_args_list,
        )

    def test_multi_name_reports_partial_failures(self) -> None:
        stdout = io.StringIO()

        with patch.object(
            remove_resource_script,
            "remove_resource",
            side_effect=[
                {"ok": True, "action": "remove", "name": "alpha"},
                HubError("not found"),
            ],
        ):
            with patch.object(
                sys,
                "argv",
                [
                    "remove_resource.py",
                    "--hub",
                    "/tmp/hub",
                    "--name",
                    "alpha",
                    "--name",
                    "beta",
                ],
            ):
                with redirect_stdout(stdout):
                    exit_code = remove_resource_script.main()

        self.assertEqual(1, exit_code)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(1, payload["removed_count"])
        self.assertEqual(1, payload["failed_count"])
        self.assertEqual("beta", payload["errors"][0]["name"])
        self.assertEqual("not found", payload["errors"][0]["error"])

    def test_type_count_must_be_supported_shape(self) -> None:
        stderr = io.StringIO()

        with patch.object(
            sys,
            "argv",
            [
                "remove_resource.py",
                "--hub",
                "/tmp/hub",
                "--name",
                "alpha",
                "--name",
                "beta",
                "--type",
                "image",
                "--type",
                "video",
                "--type",
                "image",
            ],
        ):
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exc:
                    remove_resource_script.parse_args()

        self.assertEqual(2, exc.exception.code)


if __name__ == "__main__":
    unittest.main()
