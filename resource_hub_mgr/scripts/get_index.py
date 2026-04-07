#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import HubError
from hub_ops import get_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Read one resource-type index from a resource hub.")
    parser.add_argument("--hub", required=True, help="Path to the resource hub root.")
    parser.add_argument("--type", required=True, choices=["video", "image"], help="Resource type.")
    args = parser.parse_args()

    try:
        payload = get_index(Path(args.hub).resolve(), args.type)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except HubError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
