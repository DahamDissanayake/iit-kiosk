"""Download model files into the models directory and verify their checksums.

uv run python -m models.download                 # verify against models/checksums.sha256
uv run python -m models.download --record        # first trusted download: write checksums
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path

import httpx

PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium"
FILES = {
    "silero_vad.onnx": "https://github.com/snakers4/silero-vad/raw/v5.1.2/src/silero_vad/data/silero_vad.onnx",
    "piper/en_US-lessac-medium.onnx": f"{PIPER}/en_US-lessac-medium.onnx",
    "piper/en_US-lessac-medium.onnx.json": f"{PIPER}/en_US-lessac-medium.onnx.json",
}
CHECKSUMS = Path(__file__).with_name("checksums.sha256")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as res:
        res.raise_for_status()
        with tmp.open("wb") as f:
            for block in res.iter_bytes():
                f.write(block)
    tmp.replace(dest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m models.download")
    parser.add_argument("--dest", default=os.environ.get("KIOSK_MODELS_DIR", "models"))
    parser.add_argument("--record", action="store_true", help="write checksums.sha256")
    args = parser.parse_args(argv)
    dest = Path(args.dest)

    expected = {}
    if CHECKSUMS.exists():
        for line in CHECKSUMS.read_text().splitlines():
            digest, name = line.split(maxsplit=1)
            expected[name] = digest

    recorded, bad = [], []
    for name, url in FILES.items():
        path = dest / name
        if not path.exists():
            print(f"downloading {name}")
            download(url, path)
        digest = sha256(path)
        recorded.append(f"{digest}  {name}")
        if not args.record and expected.get(name) != digest:
            bad.append(name)

    if args.record:
        CHECKSUMS.write_text("\n".join(recorded) + "\n")
        print(f"wrote {CHECKSUMS}")
    elif bad:
        print(f"checksum mismatch or not recorded: {', '.join(bad)}", file=sys.stderr)
        return 1
    print("models ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
