#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import HubError
from hub_ops import remove_resource


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove one resource from a resource hub.")
    parser.add_argument("--hub", required=True, help="Path to the resource hub root.")
    parser.add_argument("--name", required=True, help="Resource name.")
    parser.add_argument("--type", choices=["video", "image"], help="Optional resource type.")
    args = parser.parse_args()

    try:
        payload = remove_resource(
            Path(args.hub).resolve(),
            resource_name=args.name,
            resource_type=args.type,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except HubError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
