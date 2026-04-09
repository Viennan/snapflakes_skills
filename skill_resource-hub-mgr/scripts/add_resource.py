#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import HubError
from hub_ops import add_resource


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add one or more resources into a resource hub.")
    parser.add_argument("--hub", required=True, help="Path to the resource hub root.")
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="Path to a source media file. Repeat --source to import multiple files sequentially.",
    )
    parser.add_argument(
        "--name",
        action="append",
        default=[],
        help="Optional resource name. Repeat once per --source in the same order, or omit to auto-name.",
    )
    args = parser.parse_args()
    if args.name and len(args.name) != len(args.source):
        parser.error("--name must be omitted or repeated exactly once per --source")
    return args


def _batch_payload(
    *,
    hub_root: Path,
    results: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "ok": not errors,
        "action": "add_batch",
        "hub_root": str(hub_root),
        "imported_count": len(results),
        "failed_count": len(errors),
        "results": results,
        "errors": errors,
    }


def main() -> int:
    args = parse_args()
    hub_root = Path(args.hub).resolve()
    sources = [Path(raw_source).resolve() for raw_source in args.source]
    names = list(args.name or [])

    if len(sources) == 1:
        requested_name = names[0] if names else None
        try:
            payload = add_resource(
                hub_root,
                sources[0],
                resource_name=requested_name,
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        except HubError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1

    requested_names = names if names else [None] * len(sources)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for source_path, requested_name in zip(sources, requested_names):
        try:
            results.append(
                add_resource(
                    hub_root,
                    source_path,
                    resource_name=requested_name,
                )
            )
        except HubError as exc:
            errors.append(
                {
                    "source": str(source_path),
                    "requested_name": requested_name,
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
