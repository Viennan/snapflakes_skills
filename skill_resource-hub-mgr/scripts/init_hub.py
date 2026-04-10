#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hub_ops import ensure_hub_structure

HELP_EPILOG = """Examples:
  scripts/run_python.sh init_hub.py --hub /path/to/hub
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize or confirm the directory structure of a resource hub.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--hub", required=True, help="Path to the resource hub root to create or confirm.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

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
