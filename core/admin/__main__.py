"""Set the staff PIN on the kiosk (done with IIT at handover):

uv run python -m core.admin set-pin
"""

import argparse
import getpass
import sys

from core.admin.auth import PinAuth
from core.config import load_config
from core.paths import data_dir
from core.store.db import Database


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m core.admin")
    parser.add_argument("--config", default="config.toml")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("set-pin")
    args = parser.parse_args()
    cfg = load_config(args.config)
    auth = PinAuth(Database(data_dir(cfg) / "kiosk.db"))
    pin = getpass.getpass("New 6-digit PIN: ")
    if pin != getpass.getpass("Repeat PIN: "):
        print("PINs do not match.", file=sys.stderr)
        return 1
    try:
        auth.set_pin(pin)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    print("PIN set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
