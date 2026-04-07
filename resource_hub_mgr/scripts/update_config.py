#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from common import config_path_from_hub, dump_json, load_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read or update resource_hub_config.json.")
    parser.add_argument("--hub", required=True, help="Path to the resource hub root.")
    parser.add_argument("--print", dest="print_config", action="store_true", help="Print the full config.")
    parser.add_argument("--get", action="append", default=[], metavar="PATH", help="Read a dotted path.")
    parser.add_argument(
        "--set",
        action="append",
        nargs=2,
        default=[],
        metavar=("PATH", "VALUE"),
        help="Set a dotted path to a JSON value or raw string.",
    )
    parser.add_argument(
        "--delete",
        action="append",
        default=[],
        metavar="PATH",
        help="Delete a dotted path.",
    )
    return parser.parse_args()


def split_path(path: str) -> list[str]:
    parts = [part.strip() for part in path.split(".") if part.strip()]
    if not parts:
        raise ValueError("Path must not be empty.")
    return parts


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def get_path(data: dict[str, Any], dotted_path: str) -> Any:
    current: Any = data
    for part in split_path(dotted_path):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted_path)
        current = current[part]
    return current


def set_path(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = split_path(dotted_path)
    current: dict[str, Any] = data
    for part in parts[:-1]:
        existing = current.get(part)
        if existing is None:
            current[part] = {}
            existing = current[part]
        if not isinstance(existing, dict):
            raise TypeError(f"Intermediate path '{part}' is not an object.")
        current = existing
    current[parts[-1]] = value


def delete_path(data: dict[str, Any], dotted_path: str) -> None:
    parts = split_path(dotted_path)
    current: dict[str, Any] = data
    for part in parts[:-1]:
        existing = current.get(part)
        if not isinstance(existing, dict):
            raise KeyError(dotted_path)
        current = existing
    if parts[-1] not in current:
        raise KeyError(dotted_path)
    del current[parts[-1]]


def main() -> int:
    args = parse_args()
    if not any([args.print_config, args.get, args.set, args.delete]):
        print("At least one of --print, --get, --set, or --delete is required.", file=sys.stderr)
        return 1

    hub_root = Path(args.hub).resolve()
    config_path = config_path_from_hub(hub_root)
    if not config_path.exists():
        print(json.dumps({"ok": False, "error": f"Config not found: {config_path}"}, ensure_ascii=False))
        return 1

    try:
        config = load_json(config_path)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"Failed to load config: {exc}"}, ensure_ascii=False))
        return 1

    if not isinstance(config, dict):
        print(json.dumps({"ok": False, "error": "Config root must be a JSON object."}, ensure_ascii=False))
        return 1

    result: dict[str, Any] = {
        "ok": True,
        "config_path": str(config_path),
        "updated": False,
        "changes": [],
        "values": {},
    }

    try:
        for path, raw_value in args.set:
            value = parse_value(raw_value)
            set_path(config, path, value)
            result["changes"].append({"op": "set", "path": path, "value": value})

        for path in args.delete:
            delete_path(config, path)
            result["changes"].append({"op": "delete", "path": path})

        if args.set or args.delete:
            dump_json(config_path, config)
            result["updated"] = True

        for path in args.get:
            result["values"][path] = get_path(config, path)

        if args.print_config:
            result["config"] = config
    except (KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
