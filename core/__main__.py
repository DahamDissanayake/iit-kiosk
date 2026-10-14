"""Run the kiosk screen server: `uv run python -m core --dev`."""

import argparse
import logging

import uvicorn

from core.app import create_app
from core.bus import use_selector_loop_on_windows
from core.config import load_config
from core.services import build_services


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m core")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--dev", action="store_true", help="enable the dev panel and fakes")
    parser.add_argument("--mic-device", default=None, help='input device name; "" = system default')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    cfg = load_config(args.config)
    use_selector_loop_on_windows()  # pyzmq needs the selector loop on Windows
    services = build_services(cfg, dev=args.dev, mic_device=args.mic_device)
    app = create_app(cfg, dev=args.dev, services=services)
    uvicorn.run(app, host="127.0.0.1", port=cfg["ui"]["port"])


if __name__ == "__main__":
    main()
