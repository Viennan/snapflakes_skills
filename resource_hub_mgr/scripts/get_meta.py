#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import HubError
from hub_ops import get_meta


def main() -> int:
    parser = argparse.ArgumentParser(description="Read one resource entry from a resource hub index.")
    parser.add_argument("--hub", required=True, help="Path to the resource hub root.")
    parser.add_argument("--type", required=True, choices=["video", "image"], help="Resource type.")
    parser.add_argument("--name", required=True, help="Resource name.")
    args = parser.parse_args()

    try:
        payload = get_meta(Path(args.hub).resolve(), args.type, args.name)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except HubError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
