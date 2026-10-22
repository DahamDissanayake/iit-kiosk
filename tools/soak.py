"""8-hour soak (acceptance test 19): simulated visitors over the dev WebSocket while the real
camera, voice and LLM run. Start kiosk-core with --dev first.

    uv run python -m tools.soak --hours 8 --csv soak.csv
"""

import argparse
import csv
import json
import random
import time

from websockets.sync.client import connect

from core.sysinfo import read_temp

QUESTIONS = [
    "What courses does IIT offer?",
    "Where is the campus?",
    "What is LeapGen?",
    "How do I apply?",
    "What research happens at IIT?",
]


def wait_for_state(ws, state: str, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            msg = json.loads(ws.recv(timeout=max(0.1, end - time.time())))
        except TimeoutError:
            return False
        if msg.get("type") == "audio":
            ws.send(json.dumps({"type": "speech.ended", "id": msg["id"]}))  # no speaker needed
        if msg.get("type") == "state" and msg.get("state") == state:
            return True
    return False


def cycle(ws) -> bool:
    ws.send(json.dumps({"type": "dev", "action": "approach"}))
    if not wait_for_state(ws, "listening", 30):
        return False
    for question in random.sample(QUESTIONS, 2):
        ws.send(json.dumps({"type": "dev", "action": "ask", "text": question}))
        if not wait_for_state(ws, "listening", 45):
            return False
    ws.send(json.dumps({"type": "dev", "action": "leave"}))
    return wait_for_state(ws, "idle", 20)


def summarise(rows: list[dict]) -> dict:
    cycles = [r for r in rows if r["kind"] == "cycle"]
    temps = [r["temp_c"] for r in rows if r["temp_c"] is not None]
    span = (rows[-1]["ts"] - rows[0]["ts"]) if rows else 0
    return {
        "cycles": len(cycles),
        "failed": sum(not r["ok"] for r in cycles),
        "max_temp_c": max(temps) if temps else None,
        "hours": round(span / 3600, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.soak")
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws")
    parser.add_argument("--csv", default="soak.csv")
    parser.add_argument("--gap", type=float, default=25.0, help="seconds between visitors")
    args = parser.parse_args()

    rows: list[dict] = []
    end = time.time() + args.hours * 3600
    with open(args.csv, "w", newline="") as f:
        out = csv.DictWriter(f, fieldnames=["ts", "kind", "ok", "seconds", "temp_c"])
        out.writeheader()
        while time.time() < end:
            start = time.time()
            try:
                with connect(args.url, open_timeout=10) as ws:
                    ok = cycle(ws)
            except OSError:
                ok = False  # kiosk-core restarting counts as a failed cycle
            row = {
                "ts": round(start),
                "kind": "cycle",
                "ok": ok,
                "seconds": round(time.time() - start, 1),
                "temp_c": read_temp(),
            }
            rows.append(row)
            out.writerow(row)
            f.flush()
            print(json.dumps(row), flush=True)
            time.sleep(args.gap)
    print(json.dumps(summarise(rows)))


if __name__ == "__main__":
    main()
