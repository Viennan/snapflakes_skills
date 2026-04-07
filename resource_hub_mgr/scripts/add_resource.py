#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import HubError
from hub_ops import add_resource


def main() -> int:
    parser = argparse.ArgumentParser(description="Add one resource into a resource hub.")
    parser.add_argument("--hub", required=True, help="Path to the resource hub root.")
    parser.add_argument("--source", required=True, help="Path to the source media file.")
    parser.add_argument("--name", help="Optional resource name.")
    args = parser.parse_args()

    try:
        payload = add_resource(
            Path(args.hub).resolve(),
            Path(args.source).resolve(),
            resource_name=args.name,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except HubError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
