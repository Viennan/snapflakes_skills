#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import HubError
from hub_ops import repair_hub

HELP_EPILOG = """Examples:
  scripts/run_python.sh repair_hub.py --hub /path/to/hub
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repair a resource hub so on-disk files and indexes match the current config.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--hub", required=True, help="Path to the resource hub root to repair.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        payload = repair_hub(Path(args.hub).resolve())
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("ok") else 1
    except HubError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
