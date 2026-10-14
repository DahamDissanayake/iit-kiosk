"""Run the kiosk screen server: `uv run python -m core --dev`."""

import argparse
import logging

import uvicorn

from core.app import create_app
from core.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m core")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--dev", action="store_true", help="enable the dev panel and fakes")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    cfg = load_config(args.config)
    uvicorn.run(create_app(cfg, dev=args.dev), host="127.0.0.1", port=cfg["ui"]["port"])


if __name__ == "__main__":
    main()
