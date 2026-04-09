#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hub_ops import ensure_hub_structure


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a resource hub.")
    parser.add_argument("--hub", required=True, help="Path to the resource hub root.")
    args = parser.parse_args()

    config = ensure_hub_structure(Path(args.hub).resolve())
    payload = {
        "ok": True,
        "action": "init",
        "hub_root": str(Path(args.hub).resolve()),
        "config": config,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
