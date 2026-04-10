#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import HubError
from hub_ops import remove_resource

HELP_EPILOG = """Examples:
  scripts/run_python.sh remove_resource.py --hub /path/to/hub --name logo
  scripts/run_python.sh remove_resource.py --hub /path/to/hub --name alpha --name beta --type image
  scripts/run_python.sh remove_resource.py --hub /path/to/hub --name alpha --type image --name intro --type video
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove one or more resources from a resource hub sequentially.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--hub", required=True, help="Path to the resource hub root.")
    parser.add_argument(
        "--name",
        action="append",
        required=True,
        help="Resource name. Repeat --name to remove multiple resources sequentially.",
    )
    parser.add_argument(
        "--type",
        action="append",
        choices=["video", "image"],
        default=[],
        help="Optional resource type. Omit it, provide one shared type, or repeat once per --name.",
    )
    args = parser.parse_args()
    if args.type and len(args.type) not in {1, len(args.name)}:
        parser.error("--type must be omitted, provided once, or repeated exactly once per --name")
    return args


def _batch_payload(
    *,
    hub_root: Path,
    results: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "ok": not errors,
        "action": "remove_batch",
        "hub_root": str(hub_root),
        "removed_count": len(results),
        "failed_count": len(errors),
        "results": results,
        "errors": errors,
    }


def main() -> int:
    args = parse_args()
    hub_root = Path(args.hub).resolve()
    names = list(args.name)
    raw_types = list(args.type or [])

    if len(names) == 1:
        requested_type = raw_types[0] if raw_types else None
        try:
            payload = remove_resource(
                hub_root,
                resource_name=names[0],
                resource_type=requested_type,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        except HubError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1

    if not raw_types:
        requested_types = [None] * len(names)
    elif len(raw_types) == 1:
        requested_types = raw_types * len(names)
    else:
        requested_types = raw_types

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for resource_name, requested_type in zip(names, requested_types):
        try:
            results.append(
                remove_resource(
                    hub_root,
                    resource_name=resource_name,
                    resource_type=requested_type,
                )
            )
        except HubError as exc:
            errors.append(
                {
                    "name": resource_name,
                    "requested_type": requested_type,
                    "error": str(exc),
                }
            )

    payload = _batch_payload(
        hub_root=hub_root,
        results=results,
        errors=errors,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
