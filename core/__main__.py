"""Run kiosk-core: the kiosk screen on 127.0.0.1:8765 and the dashboard on 0.0.0.0:8080.

uv run python -m core --dev
"""

import argparse
import asyncio
import logging
import secrets

import uvicorn

from core.admin.api import create_admin_app
from core.app import create_app
from core.bus import use_selector_loop_on_windows
from core.config import load_config
from core.paths import data_dir
from core.secrets import load_env
from core.services import build_services


async def serve_all(servers: list[uvicorn.Server]) -> None:
    tasks = [asyncio.create_task(s.serve()) for s in servers]
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for s in servers:  # one got the stop signal; stop the other too
        s.should_exit = True
    await asyncio.gather(*pending)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m core")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--dev", action="store_true", help="enable the dev panel and fakes")
    parser.add_argument("--mic-device", default=None, help='input device name; "" = default')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    cfg = load_config(args.config)
    env = load_env(data_dir(cfg) / ".env")
    secret = env.get("SESSION_SECRET") or (secrets.token_hex(32) if args.dev else "")
    if not secret:
        raise SystemExit(f"SESSION_SECRET missing in {data_dir(cfg) / '.env'}")
    services = build_services(cfg, dev=args.dev, env=env, mic_device=args.mic_device)
    kiosk = create_app(cfg, dev=args.dev, services=services)
    admin = create_admin_app(
        cfg,
        services,
        kiosk.state.runtime,
        kiosk.state.applier,
        dev=args.dev,
        session_secret=secret,
        get_vision_link=lambda: kiosk.state.vision_link,
    )
    use_selector_loop_on_windows()  # pyzmq needs the selector loop on Windows
    asyncio.run(
        serve_all(
            [
                uvicorn.Server(uvicorn.Config(kiosk, host="127.0.0.1", port=cfg["ui"]["port"])),
                uvicorn.Server(uvicorn.Config(admin, host="0.0.0.0", port=cfg["admin"]["port"])),
            ]
        )
    )


if __name__ == "__main__":
    main()
