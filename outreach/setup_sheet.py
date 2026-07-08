from __future__ import annotations

import argparse

from .config import load_config
from .sender import build_store


def main() -> None:
    parser = argparse.ArgumentParser(description="Create missing tabs, headers, control values, and analytics formulas.")
    parser.add_argument("--config", default="config.json", help="Path to safe config JSON.")
    parser.add_argument("--sheet", help="Full Google Sheet URL or raw spreadsheet id.")
    args = parser.parse_args()
    config = load_config(args.config, sheet_override=args.sheet)
    store = build_store(config)
    store.ensure_all()
    print("Sheet setup complete.")


if __name__ == "__main__":
    main()
