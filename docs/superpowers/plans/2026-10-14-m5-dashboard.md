# M5: Admin Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Staff hold the gear for 3 s, enter a 6-digit PIN, and manage the kiosk: usage stats, knowledge base (add, edit, disable, delete, re-index, test a question), unmatched questions (opt-in), settings with live detection-zone calibration, PIN change, and health with restart and shutdown. Five wrong PINs lock the pad for 5 minutes; 5 idle minutes return the kiosk to Idle.

**Architecture:** A second FastAPI app (`create_admin_app`) runs in the same kiosk-core process on port 8080 (LAN), sharing the runtime, database and knowledge base with the kiosk app on 8765 (localhost). Settings overrides live in SQLite and are applied live through `SettingsApplier`. Sessions are signed HTTP-only cookies with an idle timeout. The React dashboard is built in CI and served as static files; there is no Node.js on the Pi.

**Tech Stack:** FastAPI, argon2-cffi, Starlette sessions (itsdangerous), python-multipart; Vite, React 18, TypeScript, Tailwind CSS 3, Recharts.

**Spec:** `docs/superpowers/specs/2026-10-14-mvp-build-design.md`; baseline sections 5, 7.3, 8, 9. Builds on the M1 to M4 plans.

## Global Constraints

- Work on a branch off `dev` named `task/<KEY>-<short-slug>`; commit messages are `<KEY>: short imperative summary`.
- Never add a `Co-Authored-By` trailer, a "Generated with" line, or any AI or agent attribution anywhere.
- Never commit secrets: `SESSION_SECRET` lives in `<data_dir>/.env`.
- Python dependencies added in M5: `argon2-cffi` (baseline 6). `itsdangerous` (signs the session cookie; baseline 6 asks for a "signed HTTP-only cookie") and `python-multipart` (FastAPI needs it for file uploads) are small and implied by the spec. **Confirm both with Daham before adding.**
- Dashboard dependencies are exactly those in Task 5's `package.json`, all named in baseline 6 plus their build tooling.
- The PIN is 6 digits, stored only as an argon2 hash. Five wrong tries lock for `admin.lockout_s`.
- Every `/api/*` route except `POST /api/auth/login` and `GET /api/auth/me` requires a session. `/health` and `/version` are public.
- The calibration preview shows box coordinates only, never camera pixels.
- Unmatched-question logging stays off unless turned on in Settings; the page says so.
- UI copy: plain English, sentence case, no jargon. Palette: white, black ink, red accent `#E1251B`.
- Format and lint before each commit: `uv run ruff format . && uv run ruff check --fix .`; for the dashboard, `npm run build` must pass.

## Review Focus

1. **Brute force across restarts.** The lockout counter lives in SQLite, so restarting kiosk-core must not reset it. (Task 2: `test_lockout_survives_a_new_auth_object`)
2. **Bad settings values.** A volume of 5, a cooldown of -1, or a string where a number belongs is rejected with a message, and nothing is half-saved. (Task 1: `test_invalid_update_saves_nothing`)
3. **Huge or wrong uploads.** A 50 MB file or a `.exe` gets a clear 4xx response, never a crash or a half-created source. (Task 4: `test_upload_too_large_is_rejected`, `test_unsupported_upload_is_rejected`)
4. **Session left open on a LAN laptop.** After 5 idle minutes the API refuses the session, even if the browser tab is still open. (Task 4: `test_session_expires_after_idle_time`)
5. **Restart or shutdown from the dashboard in dev.** These must refuse on a laptop, so a developer cannot shut down their own machine by accident. (Task 4: `test_system_actions_refused_in_dev`)

---

## File Structure

```
config.toml                  + [admin] restart_cmd, shutdown_cmd
pyproject.toml               + argon2-cffi, itsdangerous, python-multipart
core/sysinfo.py              read_temp(), read_mem_mb(), load1()
core/admin/__init__.py
core/admin/__main__.py       `python -m core.admin set-pin`
core/admin/settings.py       FIELDS, ZONE_KEYS, Settings
core/admin/apply.py          SettingsApplier, set_system_volume()
core/admin/auth.py           PinAuth, LoginResult
core/admin/stats.py          overview(), hourly(), start_of_today()
core/admin/health.py         ErrorBuffer, NetProbe, systemd_restarts()
core/admin/api.py            create_admin_app()
core/services.py             + settings
core/vision_link.py          + zone_source republish
core/app.py                  + SettingsApplier, apply at start
core/__main__.py             run kiosk (8765) and admin (8080) servers together
ui/js/audio.js, ui/js/main.js  music volume change without restarting the track
tools/bench.py               import system readers from core.sysinfo
dashboard/                   Vite + React app (Tasks 5 to 8)
.github/workflows/ci.yml     + dashboard build job
tests/test_settings.py, test_auth.py, test_stats.py, test_admin_api.py
```

---

### Task 1: Settings store and live apply

**Files:**
- Create: `core/admin/__init__.py` (empty), `core/admin/settings.py`, `core/admin/apply.py`
- Modify: `core/services.py`, `core/vision_link.py`, `core/app.py`, `ui/js/audio.js`, `ui/js/main.js`
- Test: `tests/test_settings.py`

**Interfaces:**
- Consumes: `Database`, `Runtime`, `Services`, `VisionLink`.
- Produces:
  - `FIELDS: dict[str, Field]`, `ZONE_KEYS = ("min_box_height_frac", "centre_band", "approach_growth", "mirror")`; `Settings(db, cfg)` with `defaults() -> dict`, `all() -> dict`, `update(changes: dict) -> dict` (raises `ValueError` naming the bad key; saves nothing on error).
  - `SettingsApplier(runtime, services, music_url, set_volume=set_system_volume)` with `async apply(values: dict)`.
  - `Services.settings: Settings`.
  - `VisionLink(..., zone_source: Callable[[], dict] | None = None)`, republishing `vision.config` every second.
  - `app.state.applier`.

- [ ] **Step 1: Write the failing tests** `tests/test_settings.py`

```python
import asyncio

import pytest

from core.admin.apply import SettingsApplier
from core.admin.settings import Settings
from core.answer import CannedAnswerer
from core.config import load_config
from core.controller.machine import Controller, ControllerConfig
from core.runtime import Runtime
from core.speech import FakeSpeech
from core.store.db import Database

CFG = load_config("config.toml")


def test_defaults_come_from_config():
    s = Settings(Database(":memory:"), CFG)
    values = s.all()
    assert values["greet_cooldown_s"] == CFG["engagement"]["greet_cooldown_s"]
    assert values["min_score"] == CFG["rag"]["min_score"]
    assert values["log_unmatched_questions"] is False


def test_update_persists_and_overrides():
    db = Database(":memory:")
    Settings(db, CFG).update({"greet_cooldown_s": 45, "quiet_mode": True})
    values = Settings(db, CFG).all()
    assert values["greet_cooldown_s"] == 45
    assert values["quiet_mode"] is True


@pytest.mark.parametrize("changes", [
    {"volume": 5},
    {"greet_cooldown_s": -1},
    {"greet_cooldown_s": "ten"},
    {"quiet_mode": "yes"},
    {"unknown": 1},
])
def test_invalid_values_are_rejected(changes):
    with pytest.raises(ValueError):
        Settings(Database(":memory:"), CFG).update(changes)


def test_invalid_update_saves_nothing():
    db = Database(":memory:")
    s = Settings(db, CFG)
    with pytest.raises(ValueError):
        s.update({"greet_cooldown_s": 30, "volume": 9})
    assert s.all()["greet_cooldown_s"] == CFG["engagement"]["greet_cooldown_s"]


class FakeServices:
    def __init__(self):
        self.answerer = CannedAnswerer()
        self.answerer.min_score = 0.5

        class U:
            enabled = False

        self.unmatched = U()


def test_applier_updates_controller_answers_privacy_music_and_volume():
    sent, volumes = [], []

    async def send(msg):
        sent.append(msg)

    rt = Runtime(Controller(ControllerConfig()), FakeSpeech(), CannedAnswerer(), send)
    services = FakeServices()
    applier = SettingsApplier(rt, services, "music.mp3", set_volume=volumes.append)
    values = {**Settings(Database(":memory:"), CFG).all(),
              "greet_cooldown_s": 40, "dwell_s": 2.0, "kids_default": True, "min_score": 0.6,
              "log_unmatched_questions": True, "quiet_mode": True, "volume": 0.8}
    asyncio.run(applier.apply(values))
    assert rt.c.cfg.greet_cooldown_s == 40
    assert rt.c.cfg.dwell_s == 2.0
    assert rt.c.cfg.kids_default is True
    assert services.answerer.min_score == 0.6
    assert services.unmatched.enabled is True
    assert {"type": "music", "url": "", "volume": values["music_volume"]} in sent
    assert volumes == [0.4]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.admin'`

- [ ] **Step 3: Implement** `core/admin/settings.py`

```python
"""Settings staff can change in the dashboard. Defaults come from config.toml (baseline 9)."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from core.store.db import Database


@dataclass(frozen=True)
class Field:
    type: type
    default: Callable[[dict], object]
    min: float | None = None
    max: float | None = None


FIELDS: dict[str, Field] = {
    "volume": Field(float, lambda c: 0.8, 0.0, 1.0),
    "music_on": Field(bool, lambda c: True),
    "music_volume": Field(float, lambda c: c["audio"]["music_volume"], 0.0, 1.0),
    "quiet_mode": Field(bool, lambda c: False),
    "kids_default": Field(bool, lambda c: c["engagement"]["kids_default"]),
    "greet_cooldown_s": Field(int, lambda c: c["engagement"]["greet_cooldown_s"], 5, 300),
    "dwell_s": Field(float, lambda c: c["vision"]["dwell_s"], 0.5, 5.0),
    "min_box_height_frac": Field(float, lambda c: c["vision"]["min_box_height_frac"], 0.05, 0.9),
    "centre_band": Field(float, lambda c: c["vision"]["centre_band"], 0.1, 1.0),
    "approach_growth": Field(float, lambda c: c["vision"]["approach_growth"], 0.02, 0.6),
    "mirror": Field(bool, lambda c: c["vision"]["mirror"]),
    "log_unmatched_questions": Field(bool, lambda c: c["privacy"]["log_unmatched_questions"]),
    "min_score": Field(float, lambda c: c["rag"]["min_score"], 0.0, 1.0),
}

ZONE_KEYS = ("min_box_height_frac", "centre_band", "approach_growth", "mirror")


def _coerce(key: str, value: object) -> object:
    if key not in FIELDS:
        raise ValueError(f"Unknown setting: {key}")
    f = FIELDS[key]
    if f.type is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    if f.type is int:
        if float(value) != int(value):
            raise ValueError(f"{key} must be a whole number")
        value = int(value)
    else:
        value = float(value)
    if (f.min is not None and value < f.min) or (f.max is not None and value > f.max):
        raise ValueError(f"{key} must be between {f.min} and {f.max}")
    return value


class Settings:
    def __init__(self, db: Database, cfg: dict) -> None:
        self.db = db
        self.cfg = cfg

    def defaults(self) -> dict:
        return {key: f.default(self.cfg) for key, f in FIELDS.items()}

    def all(self) -> dict:
        values = self.defaults()
        for row in self.db.execute("SELECT key, value FROM settings"):
            if row["key"] in FIELDS:
                values[row["key"]] = json.loads(row["value"])
        return values

    def update(self, changes: dict) -> dict:
        clean = {key: _coerce(key, value) for key, value in changes.items()}
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self.db.transaction() as conn:
            for key, value in clean.items():
                conn.execute(
                    "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                    " updated_at = excluded.updated_at",
                    (key, json.dumps(value), now),
                )
        return self.all()
```

- [ ] **Step 4: Implement** `core/admin/apply.py`

```python
"""Applies dashboard settings to the running kiosk without a restart."""

import dataclasses
import logging
import subprocess
from collections.abc import Callable

from core.runtime import Runtime

log = logging.getLogger("kiosk.settings")


def set_system_volume(level: float) -> None:
    """Speaker volume through PipeWire; a no-op where wpctl is missing (laptops, CI)."""
    try:
        subprocess.run(
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level:.2f}"],
            check=False, timeout=3, capture_output=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        log.info("wpctl not available; volume %.2f not applied", level)


class SettingsApplier:
    def __init__(
        self,
        runtime: Runtime,
        services,
        music_url: str,
        set_volume: Callable[[float], None] = set_system_volume,
    ) -> None:
        self.runtime = runtime
        self.services = services
        self.music_url = music_url
        self.set_volume = set_volume

    async def apply(self, s: dict) -> None:
        c = self.runtime.c
        c.cfg = dataclasses.replace(
            c.cfg,
            greet_cooldown_s=s["greet_cooldown_s"],
            dwell_s=s["dwell_s"],
            kids_default=s["kids_default"],
        )
        if hasattr(self.services.answerer, "min_score"):
            self.services.answerer.min_score = s["min_score"]
        self.services.unmatched.enabled = s["log_unmatched_questions"]
        quiet = s["quiet_mode"]
        url = self.music_url if (s["music_on"] and not quiet) else ""
        self.runtime.music = {"url": url, "volume": s["music_volume"]}
        await self.runtime.send({"type": "music", **self.runtime.music})
        self.set_volume(s["volume"] * (0.5 if quiet else 1.0))
```

Quiet mode means no music and the speaker at half the set volume.

- [ ] **Step 5: Wire it in**

`core/services.py`: import `Settings`, add `settings: Settings` to `Services` (before `voice`), build it right after `db`: `settings = Settings(db, cfg)`, and pass it into the `Services(...)` call.

`core/vision_link.py`: add `zone_source: Callable[[], dict] | None = None` to `VisionLink.__init__` (store it), and in `_watch_loop` after the rate publish:
```python
            if self.zone_source:
                await self.core_pub.publish("vision.config", self.zone_source())
```

`core/app.py`:
- import `SettingsApplier` and `ZONE_KEYS`;
- after building `runtime`: `applier = SettingsApplier(runtime, services, cfg["ui"].get("music_url", ""))` and `app.state.applier = applier` (after `app` is created);
- in the lifespan, right after `runtime.start()`: `await applier.apply(services.settings.all())`;
- pass `zone_source=lambda: {k: services.settings.all()[k] for k in ZONE_KEYS}` to `VisionLink(...)`.

Remove the `music=` argument from `Runtime(...)` in `create_app` (the applier now sets `runtime.music`).

`ui/js/audio.js`: at the start of `setMusic`, after `this.musicBase = volume;`, add:
```js
    if (this.musicEl && url && this.musicEl.dataset.url === url) return; // volume change only
```
and after `this.musicEl = new Audio(url);` add `this.musicEl.dataset.url = url;`.

`ui/js/main.js`: change the music case to:
```js
    case 'music': audio.setMusic(m.url, m.volume); audio.duckFor(root.dataset.state); break;
```

- [ ] **Step 6: Run tests, commit**

Run: `uv run pytest -v` → all PASS

```bash
uv run ruff format . && uv run ruff check --fix .
git add core ui tests/test_settings.py
git commit -m "<KEY>: store dashboard settings and apply them live"
```

---

### Task 2: PIN authentication

**Files:**
- Modify: `pyproject.toml`
- Create: `core/admin/auth.py`, `core/admin/__main__.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces: `LoginResult(ok: bool, reason: str = "", retry_after_s: int = 0, tries_left: int = 0)` with reason `"wrong" | "locked" | "unset"`; `PinAuth(db, max_tries=5, lockout_s=300, clock=time.time)` with `is_set()`, `set_pin(pin)` (raises `ValueError` unless exactly 6 digits), `check(pin) -> LoginResult`; CLI `python -m core.admin set-pin`.

- [ ] **Step 1: Add the dependency**

Run: `uv add argon2-cffi`

- [ ] **Step 2: Write the failing tests** `tests/test_auth.py`

```python
import pytest

from core.admin.auth import PinAuth
from core.store.db import Database


def make(now):
    db = Database(":memory:")
    auth = PinAuth(db, max_tries=5, lockout_s=300, clock=lambda: now[0])
    return db, auth


def test_unset_pin_refuses_login():
    _, auth = make([0.0])
    assert not auth.is_set()
    assert auth.check("123456").reason == "unset"


@pytest.mark.parametrize("pin", ["12345", "1234567", "12345a", ""])
def test_pin_must_be_six_digits(pin):
    _, auth = make([0.0])
    with pytest.raises(ValueError):
        auth.set_pin(pin)


def test_correct_pin_logs_in_and_hash_is_not_plain():
    db, auth = make([0.0])
    auth.set_pin("482913")
    assert auth.check("482913").ok
    stored = db.execute("SELECT pin_hash FROM auth")[0]["pin_hash"]
    assert "482913" not in stored and stored.startswith("$argon2")


def test_five_wrong_tries_lock_for_five_minutes():
    now = [1000.0]
    _, auth = make(now)
    auth.set_pin("482913")
    results = [auth.check("000000") for _ in range(5)]
    assert [r.reason for r in results] == ["wrong"] * 4 + ["locked"]
    assert results[0].tries_left == 4
    assert auth.check("482913").reason == "locked"
    now[0] += 299
    assert auth.check("482913").reason == "locked"
    now[0] += 2
    assert auth.check("482913").ok


def test_success_resets_the_counter():
    _, auth = make([0.0])
    auth.set_pin("482913")
    for _ in range(4):
        auth.check("000000")
    assert auth.check("482913").ok
    assert auth.check("000000").tries_left == 4


def test_lockout_survives_a_new_auth_object():
    now = [0.0]
    db, auth = make(now)
    auth.set_pin("482913")
    for _ in range(5):
        auth.check("000000")
    again = PinAuth(db, clock=lambda: now[0])
    assert again.check("482913").reason == "locked"
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.admin.auth'`

- [ ] **Step 4: Implement** `core/admin/auth.py`

```python
"""6-digit staff PIN, argon2-hashed, with a lockout stored in SQLite (baseline 5.1)."""

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from core.store.db import Database

PIN_RE = re.compile(r"\d{6}")


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    reason: str = ""
    retry_after_s: int = 0
    tries_left: int = 0


class PinAuth:
    def __init__(
        self,
        db: Database,
        max_tries: int = 5,
        lockout_s: int = 300,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db = db
        self.max_tries = max_tries
        self.lockout_s = lockout_s
        self.clock = clock
        self.hasher = PasswordHasher()
        db.execute("INSERT OR IGNORE INTO auth (id) VALUES (1)")

    def _row(self):
        return self.db.execute("SELECT pin_hash, failed_count, locked_until FROM auth WHERE id = 1")[0]

    def is_set(self) -> bool:
        return bool(self._row()["pin_hash"])

    def set_pin(self, pin: str) -> None:
        if not PIN_RE.fullmatch(pin):
            raise ValueError("The PIN must be exactly 6 digits.")
        self.db.execute(
            "UPDATE auth SET pin_hash = ?, failed_count = 0, locked_until = 0 WHERE id = 1",
            (self.hasher.hash(pin),),
        )

    def check(self, pin: str) -> LoginResult:
        with self.db.lock:
            row = self._row()
            now = self.clock()
            if not row["pin_hash"]:
                return LoginResult(False, "unset")
            if row["locked_until"] > now:
                return LoginResult(False, "locked", math.ceil(row["locked_until"] - now))
            try:
                self.hasher.verify(row["pin_hash"], pin)
            except (VerificationError, InvalidHashError):
                failed = row["failed_count"] + 1
                if failed >= self.max_tries:
                    self.db.execute(
                        "UPDATE auth SET failed_count = 0, locked_until = ? WHERE id = 1",
                        (now + self.lockout_s,),
                    )
                    return LoginResult(False, "locked", self.lockout_s)
                self.db.execute("UPDATE auth SET failed_count = ? WHERE id = 1", (failed,))
                return LoginResult(False, "wrong", tries_left=self.max_tries - failed)
            self.db.execute("UPDATE auth SET failed_count = 0, locked_until = 0 WHERE id = 1")
            return LoginResult(True)
```

- [ ] **Step 5: Implement** `core/admin/__main__.py`

```python
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
```

- [ ] **Step 6: Run tests, commit**

Run: `uv run pytest tests/test_auth.py -v` → PASS

```bash
uv run ruff format . && uv run ruff check --fix .
git add pyproject.toml uv.lock core/admin/auth.py core/admin/__main__.py tests/test_auth.py
git commit -m "<KEY>: protect the dashboard with a hashed PIN and lockout"
```

---

### Task 3: Stats and health helpers

**Files:**
- Create: `core/sysinfo.py`, `core/admin/stats.py`, `core/admin/health.py`
- Modify: `tools/bench.py`
- Test: `tests/test_stats.py`

**Interfaces:**
- Produces:
  - `core.sysinfo`: `read_temp() -> float | None`, `read_mem_mb() -> tuple[int, int] | None` (total, available), `load1() -> float | None`.
  - `core.admin.stats`: `COUNTED`, `start_of_today(now=None) -> float`, `overview(db, since) -> dict` with `counts`, `avg_conversation_s`, `avg_reply_ms`; `hourly(db, since) -> list[{"hour": int, "encounters": int}]` (24 entries).
  - `core.admin.health`: `ErrorBuffer` (logging handler; `ErrorBuffer.install() -> ErrorBuffer`, `.items() -> list[dict]`), `NetProbe(host, port=443, every_s=30.0)` with `ok`, `start()`, `async stop()`, `async check() -> bool`; `systemd_restarts(unit) -> int | None`; `LLM_HOSTS`.

- [ ] **Step 1: Write the failing tests** `tests/test_stats.py`

```python
import logging
import time

from core.admin.health import ErrorBuffer
from core.admin.stats import hourly, overview, start_of_today
from core.store.db import Database
from core.store.events import EventLog


def seed(db, ts):
    log = EventLog(db, clock=lambda: ts)
    for t in ["encounter", "encounter", "greeting", "conversation_start", "question", "answered",
              "question", "unmatched", "walkaway"]:
        log.add(t)
    log.add("conversation_end", 40.0)
    log.add("conversation_end", 20.0)
    log.add("reply_latency_ms", 1800)
    log.add("reply_latency_ms", 2200)


def test_overview_counts_and_averages():
    db = Database(":memory:")
    now = time.time()
    seed(db, now)
    s = overview(db, start_of_today(now))
    assert s["counts"]["encounter"] == 2
    assert s["counts"]["question"] == 2
    assert s["counts"]["decline"] == 0
    assert s["avg_conversation_s"] == 30.0
    assert s["avg_reply_ms"] == 2000


def test_today_excludes_yesterday():
    db = Database(":memory:")
    now = time.time()
    seed(db, start_of_today(now) - 3600)
    assert overview(db, start_of_today(now))["counts"]["encounter"] == 0
    assert overview(db, 0)["counts"]["encounter"] == 2


def test_hourly_has_24_buckets():
    db = Database(":memory:")
    now = time.time()
    seed(db, now)
    rows = hourly(db, 0)
    assert len(rows) == 24
    assert sum(r["encounters"] for r in rows) == 2
    assert rows[time.localtime(now).tm_hour]["encounters"] == 2


def test_error_buffer_keeps_recent_warnings():
    buf = ErrorBuffer.install()
    logging.getLogger("kiosk.test").warning("camera hiccup")
    logging.getLogger("kiosk.test").info("not kept")
    messages = [e["message"] for e in buf.items()]
    assert "camera hiccup" in messages
    assert "not kept" not in messages
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_stats.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.admin.stats'`

- [ ] **Step 3: Implement** `core/sysinfo.py`

```python
"""Pi system readings (None on laptops)."""

import os
from pathlib import Path


def read_temp() -> float | None:
    path = Path("/sys/class/thermal/thermal_zone0/temp")
    return int(path.read_text()) / 1000 if path.exists() else None


def read_mem_mb() -> tuple[int, int] | None:
    path = Path("/proc/meminfo")
    if not path.exists():
        return None
    info = dict(line.split(":", 1) for line in path.read_text().splitlines())
    return int(info["MemTotal"].split()[0]) // 1024, int(info["MemAvailable"].split()[0]) // 1024


def load1() -> float | None:
    return os.getloadavg()[0] if hasattr(os, "getloadavg") else None
```

In `tools/bench.py`, delete its own `read_temp` and `read_mem_mb` and add `from core.sysinfo import load1, read_mem_mb, read_temp`; use `load1()` in `bench_system`. Keep `tools.bench_vision`'s `from tools.bench import read_temp` working by leaving the name importable from `tools.bench` (the import above does that).

- [ ] **Step 4: Implement** `core/admin/stats.py`

```python
"""Overview numbers for the dashboard (baseline 5.2 and 5.3)."""

import time

from core.store.db import Database

COUNTED = ["encounter", "greeting", "conversation_start", "question", "answered", "unmatched",
           "fallback", "walkaway", "decline"]


def start_of_today(now: float | None = None) -> float:
    t = time.localtime(now if now is not None else time.time())
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def _avg(db: Database, kind: str, since: float) -> float | None:
    value = db.execute("SELECT avg(value) AS a FROM events WHERE type = ? AND ts >= ?",
                       (kind, since))[0]["a"]
    return round(value, 1) if value is not None else None


def overview(db: Database, since: float) -> dict:
    rows = db.execute(
        "SELECT type, count(*) AS n FROM events WHERE ts >= ? GROUP BY type", (since,)
    )
    counts = {t: 0 for t in COUNTED}
    counts.update({r["type"]: r["n"] for r in rows if r["type"] in counts})
    avg_reply = _avg(db, "reply_latency_ms", since)
    return {
        "counts": counts,
        "avg_conversation_s": _avg(db, "conversation_end", since),
        "avg_reply_ms": round(avg_reply) if avg_reply is not None else None,
    }


def hourly(db: Database, since: float) -> list[dict]:
    rows = db.execute(
        "SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) AS h,"
        " count(*) AS n FROM events WHERE type = 'encounter' AND ts >= ? GROUP BY h",
        (since,),
    )
    by_hour = {r["h"]: r["n"] for r in rows}
    return [{"hour": h, "encounters": by_hour.get(h, 0)} for h in range(24)]
```

- [ ] **Step 5: Implement** `core/admin/health.py`

```python
"""Health page data: recent warnings, internet reachability, systemd restart counts."""

import asyncio
import logging
import subprocess
import time
from collections import deque

LLM_HOSTS = {
    "gemini": "generativelanguage.googleapis.com",
    "anthropic": "api.anthropic.com",
    "openai": "api.openai.com",
}


class ErrorBuffer(logging.Handler):
    _installed: "ErrorBuffer | None" = None

    def __init__(self, size: int = 50) -> None:
        super().__init__(level=logging.WARNING)
        self._items: deque[dict] = deque(maxlen=size)

    @classmethod
    def install(cls) -> "ErrorBuffer":
        if cls._installed is None:
            cls._installed = cls()
            logging.getLogger().addHandler(cls._installed)
        return cls._installed

    def emit(self, record: logging.LogRecord) -> None:
        self._items.append(
            {"ts": record.created, "level": record.levelname, "logger": record.name,
             "message": record.getMessage()}
        )

    def items(self) -> list[dict]:
        return list(reversed(self._items))


class NetProbe:
    def __init__(self, host: str, port: int = 443, every_s: float = 30.0) -> None:
        self.host = host
        self.port = port
        self.every_s = every_s
        self.ok: bool | None = None
        self.checked_at: float | None = None
        self._task: asyncio.Task | None = None

    async def check(self) -> bool:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), 3)
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, TimeoutError):
            return False

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            self.ok = await self.check()
            self.checked_at = time.time()
            await asyncio.sleep(self.every_s)


def systemd_restarts(unit: str) -> int | None:
    try:
        out = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "NRestarts", "--value"],
            capture_output=True, text=True, timeout=3, check=False,
        ).stdout.strip()
        return int(out) if out.isdigit() else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
```

- [ ] **Step 6: Run tests, commit**

Run: `uv run pytest -v` → all PASS

```bash
uv run ruff format . && uv run ruff check --fix .
git add core/sysinfo.py core/admin/stats.py core/admin/health.py tools/bench.py tests/test_stats.py
git commit -m "<KEY>: compute dashboard stats and health readings"
```

---

### Task 4: Admin API and running both servers

**Files:**
- Modify: `pyproject.toml`, `config.toml`, `core/__main__.py`
- Create: `core/admin/api.py`
- Test: `tests/test_admin_api.py`

**Interfaces:**
- Consumes: everything in Tasks 1 to 3, `Services`, `Runtime`, `KnowledgeBase`, `RagAnswerer`, `AnswerError`, `ModelMismatch`, `VisionLink.preview`.
- Produces: `create_admin_app(cfg, services, runtime, applier, *, dev, session_secret, get_vision_link=lambda: None, clock=time.time, probe=None) -> FastAPI` with the routes of baseline 7.3 plus `GET /api/auth/me`, `GET /api/kb/sources/{id}` and `GET /api/vision/preview`. JSON shapes:
  - login errors: `401 {"detail": {"reason": "wrong", "tries_left": n}}`, `423 {"detail": {"reason": "locked", "retry_after_s": n}}`, `409 {"detail": {"reason": "unset"}}`;
  - `GET /api/stats` → `{counts, avg_conversation_s, avg_reply_ms, uptime_s}`;
  - `GET /api/kb/sources` → `{sources: [...], needs_reindex: bool}`;
  - `GET /api/kb/sources/{id}` → source fields plus `text` (text, menu, file) or `pairs` (qa);
  - `POST /api/kb/test` → `{status: "answered"|"unmatched"|"offline", answer, hits: [{title, heading, text, score}], threshold}`;
  - `GET /api/kb/unmatched` → `{enabled, items: [{id, ts, text}]}`;
  - `GET /api/health/detail` → `{cpu_temp_c, load1, mem_used_mb, mem_total_mb, internet_ok, llm_last_reply_ms, camera_ok, mic_ok, uptime_s, restarts, errors, dev}`.

- [ ] **Step 1: Add dependencies and config**

After Daham confirms: `uv add itsdangerous python-multipart`

Append to `[admin]` in `config.toml`:
```toml
restart_cmd = ["systemctl", "--user", "restart", "kiosk-vision", "kiosk-core"]
shutdown_cmd = ["sudo", "/usr/sbin/shutdown", "-h", "now"]
```

- [ ] **Step 2: Write the failing tests** `tests/test_admin_api.py`

```python
import pytest
from fastapi.testclient import TestClient

from core.admin.api import create_admin_app
from core.admin.apply import SettingsApplier
from core.answer import CannedAnswerer
from core.config import load_config
from core.controller.machine import Controller, ControllerConfig
from core.rag.embed import HashEmbedder
from core.runtime import Runtime
from core.services import build_services
from core.speech import FakeSpeech


class FakeProbe:
    ok = True

    def start(self):
        pass

    async def stop(self):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("KIOSK_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIOSK_MODELS_DIR", str(tmp_path / "models"))
    cfg = load_config("config.toml")
    services = build_services(cfg, dev=True, embedder=HashEmbedder(), env={}, with_voice=False)

    async def send(msg):
        pass

    runtime = Runtime(Controller(ControllerConfig()), FakeSpeech(), CannedAnswerer(delay_s=0),
                      send, menu_source=services.kb.menu_items)
    applier = SettingsApplier(runtime, services, "", set_volume=lambda v: None)
    now = [1_000_000.0]

    def make(dev=True):
        app = create_admin_app(cfg, services, runtime, applier, dev=dev, session_secret="test",
                               clock=lambda: now[0], probe=FakeProbe())
        return TestClient(app)

    return make, services, runtime, now


def login(client, pin="482913"):
    return client.post("/api/auth/login", json={"pin": pin})


def authed(env, dev=True):
    make, services, runtime, now = env
    from core.admin.auth import PinAuth

    PinAuth(services.db).set_pin("482913")
    client = make(dev)
    assert login(client).status_code == 200
    return client


def test_public_routes(env):
    with env[0]() as c:
        assert c.get("/health").json() == {"ok": True}
        assert "version" in c.get("/version").json()
        assert c.get("/api/auth/me").json() == {"auth": False}


def test_api_requires_login(env):
    with env[0]() as c:
        assert c.get("/api/stats?range=today").status_code == 401


def test_unset_pin(env):
    with env[0]() as c:
        r = login(c)
        assert r.status_code == 409 and r.json()["detail"]["reason"] == "unset"


def test_wrong_pin_then_lockout(env):
    make, services, _, _ = env
    from core.admin.auth import PinAuth

    PinAuth(services.db).set_pin("482913")
    with make() as c:
        r = login(c, "000000")
        assert r.status_code == 401 and r.json()["detail"]["tries_left"] == 4
        for _ in range(4):
            r = login(c, "000000")
        assert r.status_code == 423
        assert login(c).status_code == 423


def test_session_expires_after_idle_time(env):
    with authed(env) as c:
        now = env[3]
        assert c.get("/api/stats?range=today").status_code == 200
        now[0] += 301
        assert c.get("/api/stats?range=today").status_code == 401


def test_logout(env):
    with authed(env) as c:
        c.post("/api/auth/logout")
        assert c.get("/api/auth/me").json() == {"auth": False}


def test_change_pin_needs_current_pin(env):
    with authed(env) as c:
        assert c.post("/api/auth/pin", json={"current": "111111", "new": "222222"}).status_code == 400
        assert c.post("/api/auth/pin", json={"current": "482913", "new": "222222"}).status_code == 200
        c.post("/api/auth/logout")
        assert login(c, "222222").status_code == 200


def test_stats_shape(env):
    with authed(env) as c:
        body = c.get("/api/stats?range=all").json()
        assert set(body) == {"counts", "avg_conversation_s", "avg_reply_ms", "uptime_s"}
        assert len(c.get("/api/stats/hourly?range=today").json()) == 24


def test_knowledge_base_lifecycle_reaches_search_and_menu(env):
    _, services, runtime, _ = env
    with authed(env) as c:
        r = c.post("/api/kb/sources", data={"kind": "text", "title": "Library",
                                            "text": "The library opens at eight."})
        assert r.status_code == 200
        sid = r.json()["id"]
        assert services.kb.search("library opens")[0].source_id == sid
        detail = c.get(f"/api/kb/sources/{sid}").json()
        assert detail["text"] == "The library opens at eight."
        c.patch(f"/api/kb/sources/{sid}", json={"text": "The library opens at nine."})
        assert "nine" in services.kb.search("library opens")[0].text
        c.patch(f"/api/kb/sources/{sid}", json={"enabled": False})
        assert all(h.source_id != sid for h in services.kb.search("library opens"))
        assert c.delete(f"/api/kb/sources/{sid}").status_code == 200
        r = c.post("/api/kb/sources", data={"kind": "menu", "title": "Where is IIT?",
                                            "text": "In Colombo."})
        assert any(m.label == "Where is IIT?" for m in runtime.c.menu)
        r = c.post("/api/kb/sources", data={"kind": "qa", "title": "FAQ",
                                            "pairs": '[["Parking?", "Yes."]]'})
        assert r.status_code == 200
        listing = c.get("/api/kb/sources").json()
        assert listing["needs_reindex"] is False
        assert c.post("/api/kb/reindex").json()["sources"] == len(listing["sources"])


def test_upload_file(env):
    with authed(env) as c:
        r = c.post("/api/kb/sources", data={"kind": "file", "title": ""},
                   files={"file": ("guide.md", b"# Fees\nPaid each semester.", "text/markdown")})
        assert r.status_code == 200


def test_unsupported_upload_is_rejected(env):
    with authed(env) as c:
        r = c.post("/api/kb/sources", data={"kind": "file", "title": "x"},
                   files={"file": ("run.exe", b"MZ", "application/octet-stream")})
        assert r.status_code == 400
        assert c.get("/api/kb/sources").json()["sources"][-1]["title"] != "x"


def test_upload_too_large_is_rejected(env):
    with authed(env) as c:
        big = b"a" * (20 * 1024 * 1024 + 1)
        r = c.post("/api/kb/sources", data={"kind": "file", "title": "big"},
                   files={"file": ("big.txt", big, "text/plain")})
        assert r.status_code == 413


def test_test_a_question(env):
    with authed(env) as c:
        c.post("/api/kb/sources", data={"kind": "text", "title": "Library",
                                        "text": "The library opens at eight."})
        body = c.post("/api/kb/test", json={"question": "When does the library open?"}).json()
        assert body["status"] == "answered"
        assert body["hits"][0]["title"] == "Library"
        assert "threshold" in body


def test_unmatched_off_by_default(env):
    with authed(env) as c:
        assert c.get("/api/kb/unmatched").json() == {"enabled": False, "items": []}


def test_settings_read_write_and_apply(env):
    runtime = env[2]
    with authed(env) as c:
        assert c.get("/api/settings").json()["greet_cooldown_s"] == 20
        r = c.put("/api/settings", json={"greet_cooldown_s": 45})
        assert r.json()["greet_cooldown_s"] == 45
        assert runtime.c.cfg.greet_cooldown_s == 45
        bad = c.put("/api/settings", json={"volume": 7})
        assert bad.status_code == 400 and "volume" in bad.json()["detail"]


def test_vision_preview_404_without_vision(env):
    with authed(env) as c:
        assert c.get("/api/vision/preview").status_code == 404


def test_health_detail_shape(env):
    with authed(env) as c:
        body = c.get("/api/health/detail").json()
        assert {"cpu_temp_c", "internet_ok", "camera_ok", "mic_ok", "uptime_s", "errors",
                "dev"} <= set(body)


def test_system_actions_refused_in_dev(env):
    with authed(env) as c:
        assert c.post("/api/system/restart").status_code == 409
        assert c.post("/api/system/shutdown").status_code == 409
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_admin_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.admin.api'`

- [ ] **Step 4: Implement** `core/admin/api.py`

```python
"""Staff dashboard API on port 8080 (baseline 5 and 7.3)."""

import asyncio
import copy
import json
import subprocess
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from core import __version__
from core.admin.apply import SettingsApplier
from core.admin.auth import PinAuth
from core.admin.health import LLM_HOSTS, ErrorBuffer, NetProbe, systemd_restarts
from core.admin.stats import hourly, overview, start_of_today
from core.answer import AnswerError
from core.rag.kb import ModelMismatch
from core.runtime import Runtime
from core.sysinfo import load1, read_mem_mb, read_temp

DIST = Path(__file__).resolve().parents[2] / "dashboard" / "dist"
MAX_UPLOAD = 20 * 1024 * 1024
STARTED = time.time()


class PinIn(BaseModel):
    pin: str


class PinChange(BaseModel):
    current: str
    new: str


class SourcePatch(BaseModel):
    title: str | None = None
    enabled: bool | None = None
    text: str | None = None
    pairs: list[tuple[str, str]] | None = None


class Question(BaseModel):
    question: str


def create_admin_app(
    cfg: dict,
    services,
    runtime: Runtime,
    applier: SettingsApplier,
    *,
    dev: bool,
    session_secret: str,
    get_vision_link: Callable[[], object] = lambda: None,
    clock: Callable[[], float] = time.time,
    probe=None,
) -> "FastAPI":
    admin = cfg["admin"]
    auth = PinAuth(services.db, admin["pin_max_tries"], admin["lockout_s"], clock)
    kb, settings = services.kb, services.settings
    errors = ErrorBuffer.install()
    probe = probe or NetProbe(LLM_HOSTS.get(cfg["llm"]["provider"], "1.1.1.1"))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        probe.start()
        yield
        await probe.stop()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=session_secret,
                       session_cookie="kiosk_admin", same_site="strict", https_only=False)

    def session(request: Request) -> None:
        s, now = request.session, clock()
        if not s.get("auth") or now - s.get("seen", 0) > admin["session_idle_s"]:
            s.clear()
            raise HTTPException(401, "Please log in.")
        s["seen"] = now

    need = [Depends(session)]

    def since(range_: str) -> float:
        return start_of_today() if range_ == "today" else 0.0

    async def kb_call(fn, *args, **kwargs):
        try:
            result = await asyncio.to_thread(fn, *args, **kwargs)
        except KeyError:
            raise HTTPException(404, "No such source.") from None
        except ModelMismatch as e:
            raise HTTPException(409, str(e)) from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        runtime.refresh_menu()
        return result

    # ---- public ----

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/version")
    async def version() -> dict:
        return {"version": __version__}

    # ---- auth ----

    @app.get("/api/auth/me")
    async def me(request: Request) -> dict:
        s = request.session
        return {"auth": bool(s.get("auth")) and clock() - s.get("seen", 0) <= admin["session_idle_s"]}

    @app.post("/api/auth/login")
    async def login(body: PinIn, request: Request) -> dict:
        result = await asyncio.to_thread(auth.check, body.pin)
        if result.ok:
            request.session.update({"auth": True, "seen": clock()})
            return {"ok": True}
        if result.reason == "unset":
            raise HTTPException(409, {"reason": "unset"})
        if result.reason == "locked":
            raise HTTPException(423, {"reason": "locked", "retry_after_s": result.retry_after_s})
        raise HTTPException(401, {"reason": "wrong", "tries_left": result.tries_left})

    @app.post("/api/auth/logout", dependencies=need)
    async def logout(request: Request) -> dict:
        request.session.clear()
        return {"ok": True}

    @app.post("/api/auth/pin", dependencies=need)
    async def change_pin(body: PinChange) -> dict:
        if not (await asyncio.to_thread(auth.check, body.current)).ok:
            raise HTTPException(400, "The current PIN is wrong.")
        try:
            await asyncio.to_thread(auth.set_pin, body.new)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return {"ok": True}

    # ---- stats ----

    @app.get("/api/stats", dependencies=need)
    async def stats(range: str = "today") -> dict:
        return {**overview(services.db, since(range)), "uptime_s": round(time.time() - STARTED)}

    @app.get("/api/stats/hourly", dependencies=need)
    async def stats_hourly(range: str = "today") -> list[dict]:
        return hourly(services.db, since(range))

    # ---- knowledge base ----

    @app.get("/api/kb/sources", dependencies=need)
    async def sources() -> dict:
        return {"sources": [s.__dict__ for s in kb.list_sources()],
                "needs_reindex": kb.needs_reindex()}

    @app.get("/api/kb/sources/{source_id}", dependencies=need)
    async def source(source_id: int) -> dict:
        info = next((s for s in kb.list_sources() if s.id == source_id), None)
        if info is None:
            raise HTTPException(404, "No such source.")
        body = kb.get_body(source_id)
        out = dict(info.__dict__)
        if info.kind == "qa":
            out["pairs"] = json.loads(body)
        elif info.kind == "file":
            out["text"] = "\n\n".join(f"{h}\n{t}".strip() for h, t in json.loads(body))
        else:
            out["text"] = body
        return out

    @app.post("/api/kb/sources", dependencies=need)
    async def add_source(
        kind: str = Form(...),
        title: str = Form(""),
        text: str = Form(""),
        pairs: str = Form(""),
        file: UploadFile | None = File(None),
    ) -> dict:
        title = title.strip()
        if kind == "text":
            sid = await kb_call(kb.add_text, title or "Untitled", text)
        elif kind == "menu":
            if not title or not text.strip():
                raise HTTPException(400, "A menu item needs a label and an answer.")
            sid = await kb_call(kb.add_menu, title, text.strip())
        elif kind == "qa":
            try:
                parsed = [(q, a) for q, a in json.loads(pairs or "[]")]
            except (ValueError, TypeError):
                raise HTTPException(400, "Questions and answers could not be read.") from None
            if not parsed:
                raise HTTPException(400, "Add at least one question and answer.")
            sid = await kb_call(kb.add_qa, title or "Questions and answers", parsed)
        elif kind == "file":
            if file is None:
                raise HTTPException(400, "Choose a file to upload.")
            data = await file.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD:
                raise HTTPException(413, "Files must be 20 MB or smaller.")
            sid = await kb_call(kb.add_file, title, file.filename or "upload", data)
        else:
            raise HTTPException(400, f"Unknown source type: {kind}")
        return {"id": sid}

    @app.patch("/api/kb/sources/{source_id}", dependencies=need)
    async def patch_source(source_id: int, body: SourcePatch) -> dict:
        await kb_call(kb.update, source_id, title=body.title, enabled=body.enabled,
                      text=body.text, pairs=body.pairs)
        return {"ok": True}

    @app.delete("/api/kb/sources/{source_id}", dependencies=need)
    async def delete_source(source_id: int) -> dict:
        await kb_call(kb.delete, source_id)
        return {"ok": True}

    @app.post("/api/kb/reindex", dependencies=need)
    async def reindex() -> dict:
        return {"sources": await kb_call(kb.reindex)}

    @app.post("/api/kb/test", dependencies=need)
    async def test_question(body: Question) -> dict:
        question = body.question.strip()
        if not question:
            raise HTTPException(400, "Type a question.")
        top_k = cfg["rag"]["top_k"]
        hits = await kb_call(kb.search, question, top_k)
        answerer = copy.copy(services.answerer)
        if hasattr(answerer, "on_unmatched"):
            answerer.on_unmatched = None  # testing must not log visitor questions
        sentences, status = [], "answered"
        try:
            async for s in answerer.answer(question, (), False):
                sentences.append(s)
        except AnswerError as e:
            status = e.kind
        return {
            "status": status,
            "answer": " ".join(sentences) or None,
            "hits": [{"title": h.title, "heading": h.heading, "text": h.text,
                      "score": round(h.score, 3)} for h in hits],
            "threshold": settings.all()["min_score"],
        }

    @app.get("/api/kb/unmatched", dependencies=need)
    async def unmatched() -> dict:
        enabled = services.unmatched.enabled
        return {"enabled": enabled, "items": services.unmatched.list() if enabled else []}

    # ---- settings ----

    @app.get("/api/settings", dependencies=need)
    async def get_settings() -> dict:
        return settings.all()

    @app.put("/api/settings", dependencies=need)
    async def put_settings(changes: dict) -> dict:
        try:
            values = settings.update(changes)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        await applier.apply(values)
        return values

    @app.get("/api/vision/preview", dependencies=need)
    async def vision_preview() -> dict:
        link = get_vision_link()
        preview = getattr(link, "preview", None)
        if not preview:
            raise HTTPException(404, "No camera preview: kiosk-vision is not running.")
        return preview

    # ---- health and system ----

    @app.get("/api/health/detail", dependencies=need)
    async def health_detail() -> dict:
        mem = read_mem_mb()
        last = services.db.execute(
            "SELECT value FROM events WHERE type = 'reply_latency_ms' ORDER BY ts DESC LIMIT 1"
        )
        return {
            "cpu_temp_c": read_temp(),
            "load1": load1(),
            "mem_used_mb": (mem[0] - mem[1]) if mem else None,
            "mem_total_mb": mem[0] if mem else None,
            "internet_ok": probe.ok,
            "llm_last_reply_ms": round(last[0]["value"]) if last else None,
            "camera_ok": runtime.c.camera_ok,
            "mic_ok": getattr(runtime.c, "mic_ok", True),
            "uptime_s": round(time.time() - STARTED),
            "restarts": await asyncio.to_thread(systemd_restarts, "kiosk-core"),
            "errors": errors.items()[:20],
            "dev": dev,
        }

    def system_action(cmd: list[str]) -> dict:
        if dev:
            raise HTTPException(409, "Restart and shut down are disabled in dev mode.")
        asyncio.get_running_loop().call_later(1.0, lambda: subprocess.Popen(cmd))
        return {"ok": True}

    @app.post("/api/system/restart", dependencies=need)
    async def restart() -> dict:
        return system_action(admin["restart_cmd"])

    @app.post("/api/system/shutdown", dependencies=need)
    async def shutdown() -> dict:
        return system_action(admin["shutdown_cmd"])

    if DIST.exists():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="dashboard")
    return app
```

- [ ] **Step 5: Run both servers from** `core/__main__.py`

```python
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
        cfg, services, kiosk.state.runtime, kiosk.state.applier,
        dev=args.dev, session_secret=secret,
        get_vision_link=lambda: kiosk.state.vision_link,
    )
    asyncio.run(serve_all([
        uvicorn.Server(uvicorn.Config(kiosk, host="127.0.0.1", port=cfg["ui"]["port"])),
        uvicorn.Server(uvicorn.Config(admin, host="0.0.0.0", port=cfg["admin"]["port"])),
    ]))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests, commit**

Run: `uv run pytest -v` → all PASS

```bash
uv run ruff format . && uv run ruff check --fix .
git add pyproject.toml uv.lock config.toml core tests/test_admin_api.py
git commit -m "<KEY>: add dashboard API on port 8080"
```

---

### Task 5: Dashboard scaffold, login and CI build

**Files:**
- Create: `dashboard/package.json`, `dashboard/tsconfig.json`, `dashboard/vite.config.ts`, `dashboard/tailwind.config.js`, `dashboard/postcss.config.js`, `dashboard/index.html`, `dashboard/src/main.tsx`, `dashboard/src/index.css`, `dashboard/src/api.ts`, `dashboard/src/useIdle.ts`, `dashboard/src/App.tsx`, `dashboard/src/PinPad.tsx`, and placeholder page modules `dashboard/src/pages/{Overview,Knowledge,TestQuestion,Unmatched,Settings,Health}.tsx` (filled in Tasks 6 to 8)
- Modify: `.github/workflows/ci.yml`, `.gitignore`

**Interfaces:**
- Consumes: the API in Task 4.
- Produces: `api` client (`get`, `post`, `put`, `patch`, `del`, `form`), `ApiError(status, body)`, the types in `api.ts`, `ON_KIOSK`, `useIdle(ms, onIdle)`, page components `export default function X()`.

- [ ] **Step 1: Config files**

`dashboard/package.json`:
```json
{
  "name": "kiosk-dashboard",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "react": "18.3.1",
    "react-dom": "18.3.1",
    "recharts": "2.13.3"
  },
  "devDependencies": {
    "@types/react": "18.3.12",
    "@types/react-dom": "18.3.1",
    "@vitejs/plugin-react": "4.3.3",
    "autoprefixer": "10.4.20",
    "postcss": "8.4.47",
    "tailwindcss": "3.4.14",
    "typescript": "5.6.3",
    "vite": "5.4.10"
  }
}
```

`dashboard/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true
  },
  "include": ["src", "vite.config.ts"]
}
```

`dashboard/vite.config.ts`:
```ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In dev, `npm run dev` proxies the API to kiosk-core on port 8080.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8080' } },
  build: { outDir: 'dist' },
});
```

`dashboard/tailwind.config.js`:
```js
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: { colors: { accent: '#E1251B', ink: '#111317' } } },
  plugins: [],
};
```

`dashboard/postcss.config.js`:
```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

`dashboard/index.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Kiosk dashboard</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Append to `.gitignore`:
```gitignore
dashboard/node_modules/
dashboard/dist/
```

- [ ] **Step 2: Styles and entry**

`dashboard/src/index.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body { @apply bg-neutral-50 text-ink antialiased; font-family: system-ui, "Segoe UI", Roboto, sans-serif; }

@layer components {
  .card { @apply rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm; }
  .btn { @apply inline-flex min-h-11 items-center justify-center rounded-full bg-ink px-5 font-semibold text-white disabled:opacity-40; }
  .btn-secondary { @apply inline-flex min-h-11 items-center justify-center rounded-full border border-neutral-300 bg-white px-5 font-semibold disabled:opacity-40; }
  .btn-danger { @apply inline-flex min-h-11 items-center justify-center rounded-full bg-accent px-5 font-semibold text-white disabled:opacity-40; }
  .tab { @apply whitespace-nowrap rounded-full px-4 py-2 text-sm font-semibold text-neutral-600; }
  .tab-active { @apply bg-ink text-white; }
  .input { @apply w-full rounded-xl border border-neutral-300 px-3 py-2 focus:border-ink focus:outline-none; }
  .label { @apply mb-1 block text-sm font-semibold text-neutral-700; }
  .muted { @apply text-sm text-neutral-500; }
}
```

`dashboard/src/main.tsx`:
```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 3: API client** `dashboard/src/api.ts`

```ts
export class ApiError extends Error {
  constructor(public status: number, public body: any) {
    const d = body?.detail;
    super(typeof d === 'string' ? d : d?.reason ?? `Request failed (${status})`);
  }
}

async function request<T>(method: string, path: string, body?: unknown, form = false): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: 'same-origin',
    headers: body !== undefined && !form ? { 'Content-Type': 'application/json' } : undefined,
    body: body === undefined ? undefined : form ? (body as FormData) : JSON.stringify(body),
  });
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : null;
  if (!res.ok) {
    if (res.status === 401 && !path.endsWith('/login')) window.dispatchEvent(new Event('kiosk:unauthorized'));
    throw new ApiError(res.status, data);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
  form: <T>(path: string, data: FormData) => request<T>('POST', path, data, true),
};

export const ON_KIOSK = ['localhost', '127.0.0.1'].includes(location.hostname);
export const KIOSK_URL = 'http://localhost:8765/';

export type Range = 'today' | 'all';
export interface Stats {
  counts: Record<string, number>;
  avg_conversation_s: number | null;
  avg_reply_ms: number | null;
  uptime_s: number;
}
export interface HourBucket { hour: number; encounters: number }
export type SourceKind = 'text' | 'qa' | 'file' | 'menu';
export interface Source {
  id: number; title: string; kind: SourceKind; filename: string | null; enabled: boolean;
  chunk_count: number; created_at: string; updated_at: string;
}
export interface SourceList { sources: Source[]; needs_reindex: boolean }
export interface SourceDetail extends Source { text?: string; pairs?: [string, string][] }
export interface Hit { title: string; heading: string; text: string; score: number }
export interface TestResult { status: 'answered' | 'unmatched' | 'offline'; answer: string | null; hits: Hit[]; threshold: number }
export interface Settings {
  volume: number; music_on: boolean; music_volume: number; quiet_mode: boolean;
  kids_default: boolean; greet_cooldown_s: number; dwell_s: number;
  min_box_height_frac: number; centre_band: number; approach_growth: number; mirror: boolean;
  log_unmatched_questions: boolean; min_score: number;
}
export interface Health {
  cpu_temp_c: number | null; load1: number | null; mem_used_mb: number | null; mem_total_mb: number | null;
  internet_ok: boolean | null; llm_last_reply_ms: number | null; camera_ok: boolean; mic_ok: boolean;
  uptime_s: number; restarts: number | null; dev: boolean;
  errors: { ts: number; level: string; logger: string; message: string }[];
}
export interface Preview { w: number; h: number; boxes: number[][] }

export function duration(s: number): string {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}
```

- [ ] **Step 4: Idle hook** `dashboard/src/useIdle.ts`

```ts
import { useEffect } from 'react';

const EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const;

export function useIdle(ms: number, onIdle: () => void): void {
  useEffect(() => {
    let timer = window.setTimeout(onIdle, ms);
    const reset = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(onIdle, ms);
    };
    EVENTS.forEach((e) => window.addEventListener(e, reset, { passive: true }));
    return () => {
      window.clearTimeout(timer);
      EVENTS.forEach((e) => window.removeEventListener(e, reset));
    };
  }, [ms, onIdle]);
}
```

- [ ] **Step 5: PIN pad** `dashboard/src/PinPad.tsx`

```tsx
import { useEffect, useState } from 'react';
import { api, ApiError } from './api';

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'clear', '0', 'back'];

function mmss(s: number) {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export default function PinPad({ onSuccess, onCancel }: { onSuccess: () => void; onCancel?: () => void }) {
  const [pin, setPin] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(value: string) {
    setBusy(true);
    try {
      await api.post('/api/auth/login', { pin: value });
      onSuccess();
    } catch (e) {
      setPin('');
      const d = e instanceof ApiError ? e.body?.detail : null;
      if (d?.reason === 'locked') setMessage(`Too many wrong tries. Try again in ${mmss(d.retry_after_s)}.`);
      else if (d?.reason === 'wrong') setMessage(`Wrong PIN. ${d.tries_left} ${d.tries_left === 1 ? 'try' : 'tries'} left.`);
      else if (d?.reason === 'unset') setMessage('No PIN is set yet. Set one on the kiosk with "python -m core.admin set-pin".');
      else setMessage('Could not reach the kiosk.');
    } finally {
      setBusy(false);
    }
  }

  function press(key: string) {
    if (busy) return;
    setMessage('');
    if (key === 'clear') return setPin('');
    if (key === 'back') return setPin((p) => p.slice(0, -1));
    const next = (pin + key).slice(0, 6);
    setPin(next);
    if (next.length === 6) void submit(next);
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (/^\d$/.test(e.key)) press(e.key);
      else if (e.key === 'Backspace') press('back');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 p-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold">Staff access</h1>
        <p className="muted mt-1">Enter the 6-digit PIN.</p>
      </div>
      <div className="flex gap-3" aria-label={`${pin.length} of 6 digits entered`}>
        {Array.from({ length: 6 }, (_, i) => (
          <span key={i} className={`h-4 w-4 rounded-full ${i < pin.length ? 'bg-ink' : 'border-2 border-neutral-300'}`} />
        ))}
      </div>
      <p className="min-h-6 text-center font-semibold text-accent" role="alert">{message}</p>
      <div className="grid grid-cols-3 gap-3">
        {KEYS.map((k) => (
          <button
            key={k}
            type="button"
            disabled={busy}
            onClick={() => press(k)}
            className={`h-20 w-20 rounded-full text-2xl font-semibold ${
              k === 'clear' || k === 'back' ? 'text-base text-neutral-600' : 'border border-neutral-200 bg-white shadow-sm active:bg-neutral-100'
            }`}
          >
            {k === 'clear' ? 'Clear' : k === 'back' ? '⌫' : k}
          </button>
        ))}
      </div>
      {onCancel && <button className="btn-secondary" onClick={onCancel}>Back to kiosk</button>}
    </div>
  );
}
```

- [ ] **Step 6: App shell** `dashboard/src/App.tsx`

```tsx
import { useCallback, useEffect, useState } from 'react';
import { api, KIOSK_URL, ON_KIOSK } from './api';
import PinPad from './PinPad';
import { useIdle } from './useIdle';
import Overview from './pages/Overview';
import Knowledge from './pages/Knowledge';
import TestQuestion from './pages/TestQuestion';
import Unmatched from './pages/Unmatched';
import Settings from './pages/Settings';
import Health from './pages/Health';

const PAGES = [
  ['overview', 'Overview', Overview],
  ['kb', 'Knowledge base', Knowledge],
  ['test', 'Test a question', TestQuestion],
  ['unmatched', 'Unmatched questions', Unmatched],
  ['settings', 'Settings', Settings],
  ['health', 'Health', Health],
] as const;
type PageId = (typeof PAGES)[number][0];

// Matches [admin] session_idle_s: the dashboard closes after 5 idle minutes (baseline 5.1).
const IDLE_MS = 5 * 60 * 1000;

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [page, setPage] = useState<PageId>('overview');

  useEffect(() => {
    api.get<{ auth: boolean }>('/api/auth/me').then((r) => setAuthed(r.auth)).catch(() => setAuthed(false));
    const onUnauthorized = () => setAuthed(false);
    window.addEventListener('kiosk:unauthorized', onUnauthorized);
    return () => window.removeEventListener('kiosk:unauthorized', onUnauthorized);
  }, []);

  const exit = useCallback(async () => {
    try { await api.post('/api/auth/logout'); } catch { /* already logged out */ }
    if (ON_KIOSK) location.href = KIOSK_URL;
    else { setAuthed(false); setPage('overview'); }
  }, []);

  useIdle(IDLE_MS, exit);

  if (authed === null) return <p className="p-8 muted">Loading…</p>;
  if (!authed) return <PinPad onSuccess={() => setAuthed(true)} onCancel={ON_KIOSK ? exit : undefined} />;

  const Current = PAGES.find(([id]) => id === page)![2];
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-neutral-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <h1 className="text-lg font-semibold">Kiosk dashboard</h1>
          <button className="btn-secondary" onClick={exit}>Exit</button>
        </div>
        <nav className="mx-auto flex max-w-5xl gap-1 overflow-x-auto px-3 pb-3">
          {PAGES.map(([id, label]) => (
            <button key={id} className={`tab ${page === id ? 'tab-active' : ''}`} onClick={() => setPage(id)}>
              {label}
            </button>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-5xl p-4">
        <Current />
      </main>
    </div>
  );
}
```

Create each page module as a placeholder so the app builds now (each is replaced in Tasks 6 to 8), e.g. `dashboard/src/pages/Overview.tsx`:
```tsx
export default function Overview() {
  return <p className="muted">Overview</p>;
}
```
(Same pattern for `Knowledge`, `TestQuestion`, `Unmatched`, `Settings`, `Health`, each returning its own name.)

- [ ] **Step 7: Install and build**

Run:
```bash
cd dashboard && npm install && npm run build
```
Expected: `dashboard/dist/index.html` exists, with no type errors. Commit `dashboard/package-lock.json`.

- [ ] **Step 8: CI job** — append to `.github/workflows/ci.yml` under `jobs:`

```yaml
  dashboard:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: dashboard
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: dashboard/package-lock.json
      - run: npm ci
      - run: npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: dashboard-dist
          path: dashboard/dist
```

- [ ] **Step 9: Manual check, commit**

Run `uv run python -m core --dev` and open http://localhost:8080/. Expected: the PIN pad. Set a PIN with `uv run python -m core.admin set-pin`, log in, and see the six tabs and Exit. Five wrong PINs show the lockout message with a countdown in minutes.

```bash
git add dashboard .github/workflows/ci.yml .gitignore
git commit -m "<KEY>: scaffold dashboard with PIN login and idle exit"
```

---

### Task 6: Overview and Health pages

**Files:**
- Modify: `dashboard/src/pages/Overview.tsx`, `dashboard/src/pages/Health.tsx`

**Interfaces:**
- Consumes: `api`, `Stats`, `HourBucket`, `Range`, `Health`, `duration`.

- [ ] **Step 1: Write** `dashboard/src/pages/Overview.tsx`

```tsx
import { useEffect, useState } from 'react';
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, duration, type HourBucket, type Range, type Stats } from '../api';

const CARDS: [string, string][] = [
  ['encounter', 'Encounters'],
  ['greeting', 'Greetings'],
  ['conversation_start', 'Conversations'],
  ['question', 'Questions asked'],
  ['answered', 'Answered'],
  ['unmatched', 'No match'],
  ['fallback', 'Touch menu uses'],
  ['walkaway', 'Walked away'],
  ['decline', 'Said no thanks'],
];

export default function Overview() {
  const [range, setRange] = useState<Range>('today');
  const [stats, setStats] = useState<Stats | null>(null);
  const [hours, setHours] = useState<HourBucket[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    const load = () =>
      Promise.all([api.get<Stats>(`/api/stats?range=${range}`), api.get<HourBucket[]>(`/api/stats/hourly?range=${range}`)])
        .then(([s, h]) => { if (live) { setStats(s); setHours(h); setError(''); } })
        .catch((e) => live && setError(e.message));
    load();
    const timer = window.setInterval(load, 15000);
    return () => { live = false; window.clearInterval(timer); };
  }, [range]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Overview</h2>
        <div className="flex gap-1 rounded-full bg-neutral-100 p-1">
          {(['today', 'all'] as Range[]).map((r) => (
            <button key={r} className={`tab ${range === r ? 'tab-active' : ''}`} onClick={() => setRange(r)}>
              {r === 'today' ? 'Today' : 'Since install'}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="font-semibold text-accent">{error}</p>}
      {stats && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {CARDS.map(([key, label]) => (
              <div key={key} className="card">
                <p className="muted">{label}</p>
                <p className="text-3xl font-semibold">{stats.counts[key] ?? 0}</p>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="card">
              <p className="muted">Average conversation</p>
              <p className="text-2xl font-semibold">{stats.avg_conversation_s != null ? `${Math.round(stats.avg_conversation_s)} s` : '–'}</p>
            </div>
            <div className="card">
              <p className="muted">Average time to first reply</p>
              <p className="text-2xl font-semibold">{stats.avg_reply_ms != null ? `${(stats.avg_reply_ms / 1000).toFixed(1)} s` : '–'}</p>
            </div>
            <div className="card">
              <p className="muted">Running for</p>
              <p className="text-2xl font-semibold">{duration(stats.uptime_s)}</p>
            </div>
          </div>
          <div className="card">
            <p className="mb-2 font-semibold">Busiest hours</p>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={hours}>
                  <XAxis dataKey="hour" tickFormatter={(h) => `${h}:00`} interval={2} fontSize={12} />
                  <YAxis allowDecimals={false} fontSize={12} width={32} />
                  <Tooltip formatter={(v) => [v, 'Encounters']} labelFormatter={(h) => `${h}:00`} />
                  <Bar dataKey="encounters" fill="#111317" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Write** `dashboard/src/pages/Health.tsx`

```tsx
import { useEffect, useState } from 'react';
import { api, duration, type Health as H } from '../api';

function Item({ label, value, bad = false }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="card">
      <p className="muted">{label}</p>
      <p className={`text-xl font-semibold ${bad ? 'text-accent' : ''}`}>{value}</p>
    </div>
  );
}

const yesNo = (v: boolean | null, yes: string, no: string) => (v == null ? 'Checking…' : v ? yes : no);

export default function Health() {
  const [h, setH] = useState<H | null>(null);
  const [message, setMessage] = useState('');

  useEffect(() => {
    let live = true;
    const load = () => api.get<H>('/api/health/detail').then((d) => live && setH(d)).catch((e) => live && setMessage(e.message));
    load();
    const t = window.setInterval(load, 5000);
    return () => { live = false; window.clearInterval(t); };
  }, []);

  async function act(kind: 'restart' | 'shutdown') {
    const text = kind === 'restart'
      ? 'Restart the kiosk services? The screen will be blank for about 20 seconds.'
      : 'Shut down the kiosk? Wait 30 seconds before unplugging the power.';
    if (!window.confirm(text)) return;
    try {
      await api.post(`/api/system/${kind}`);
      setMessage(kind === 'restart' ? 'Restarting…' : 'Shutting down. Unplug after 30 seconds.');
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  }

  if (!h) return <p className="muted">{message || 'Loading…'}</p>;
  const temp = h.cpu_temp_c;
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Health</h2>
      {message && <p className="font-semibold">{message}</p>}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Item label="CPU temperature" value={temp != null ? `${temp.toFixed(0)} °C` : 'n/a'} bad={temp != null && temp >= 75} />
        <Item label="CPU load (1 min)" value={h.load1 != null ? h.load1.toFixed(2) : 'n/a'} />
        <Item label="Memory" value={h.mem_used_mb != null ? `${(h.mem_used_mb / 1024).toFixed(1)} of ${(h.mem_total_mb! / 1024).toFixed(1)} GB` : 'n/a'} />
        <Item label="Internet" value={yesNo(h.internet_ok, 'Connected', 'Offline')} bad={h.internet_ok === false} />
        <Item label="Last reply time" value={h.llm_last_reply_ms != null ? `${(h.llm_last_reply_ms / 1000).toFixed(1)} s` : '–'} />
        <Item label="Camera" value={h.camera_ok ? 'Working' : 'Not working'} bad={!h.camera_ok} />
        <Item label="Microphone" value={h.mic_ok ? 'Working' : 'Not working'} bad={!h.mic_ok} />
        <Item label="Running for" value={duration(h.uptime_s)} />
        <Item label="Service restarts" value={h.restarts != null ? String(h.restarts) : 'n/a'} />
      </div>
      <div className="card">
        <p className="mb-2 font-semibold">Recent problems</p>
        {h.errors.length === 0 ? (
          <p className="muted">None.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {h.errors.map((e, i) => (
              <li key={i}>
                <span className="muted">{new Date(e.ts * 1000).toLocaleTimeString()} </span>
                <span className={e.level === 'ERROR' ? 'font-semibold text-accent' : ''}>{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex flex-wrap gap-3">
        <button className="btn-secondary" disabled={h.dev} onClick={() => act('restart')}>Restart services</button>
        <button className="btn-danger" disabled={h.dev} onClick={() => act('shutdown')}>Shut down</button>
        {h.dev && <p className="muted self-center">Disabled in dev mode.</p>}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Build, check, commit**

Run: `cd dashboard && npm run build` → no errors. In dev, log in and check that Overview shows counts after a few dev-panel encounters, and that Health refreshes every 5 s.

```bash
git add dashboard/src/pages/Overview.tsx dashboard/src/pages/Health.tsx
git commit -m "<KEY>: add overview and health pages"
```

---

### Task 7: Knowledge base, Test a question, and Unmatched pages

**Files:**
- Modify: `dashboard/src/pages/Knowledge.tsx`, `dashboard/src/pages/TestQuestion.tsx`, `dashboard/src/pages/Unmatched.tsx`
- Create: `dashboard/src/QaEditor.tsx`

**Interfaces:**
- Consumes: `api`, `Source`, `SourceList`, `SourceDetail`, `SourceKind`, `TestResult`.
- Produces: `QaEditor({ pairs, onChange })`.

- [ ] **Step 1: Write** `dashboard/src/QaEditor.tsx`

```tsx
export type Pair = [string, string];

export default function QaEditor({ pairs, onChange }: { pairs: Pair[]; onChange: (p: Pair[]) => void }) {
  const set = (i: number, j: 0 | 1, v: string) =>
    onChange(pairs.map((p, k) => (k === i ? ((j === 0 ? [v, p[1]] : [p[0], v]) as Pair) : p)));
  return (
    <div className="space-y-3">
      {pairs.map(([q, a], i) => (
        <div key={i} className="grid gap-2 rounded-xl border border-neutral-200 p-3">
          <input className="input" placeholder="Question" value={q} onChange={(e) => set(i, 0, e.target.value)} />
          <textarea className="input" rows={2} placeholder="Answer" value={a} onChange={(e) => set(i, 1, e.target.value)} />
          {pairs.length > 1 && (
            <button type="button" className="justify-self-end text-sm font-semibold text-accent" onClick={() => onChange(pairs.filter((_, k) => k !== i))}>
              Remove
            </button>
          )}
        </div>
      ))}
      <button type="button" className="btn-secondary" onClick={() => onChange([...pairs, ['', '']])}>Add another</button>
    </div>
  );
}
```

- [ ] **Step 2: Write** `dashboard/src/pages/Knowledge.tsx`

```tsx
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, type Source, type SourceDetail, type SourceKind, type SourceList } from '../api';
import QaEditor, { type Pair } from '../QaEditor';

const KIND_LABEL: Record<SourceKind, string> = { text: 'Text', qa: 'Q&A', file: 'File', menu: 'Touch menu' };

function AddSource({ busy, onSubmit }: { busy: boolean; onSubmit: (data: FormData) => Promise<boolean> }) {
  const [kind, setKind] = useState<SourceKind>('text');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [pairs, setPairs] = useState<Pair[]>([['', '']]);
  const [file, setFile] = useState<File | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const data = new FormData();
    data.append('kind', kind);
    data.append('title', title);
    if (kind === 'text' || kind === 'menu') data.append('text', text);
    if (kind === 'qa') data.append('pairs', JSON.stringify(pairs.filter(([q, a]) => q.trim() && a.trim())));
    if (kind === 'file' && file) data.append('file', file);
    if (await onSubmit(data)) { setTitle(''); setText(''); setPairs([['', '']]); setFile(null); }
  }

  return (
    <form className="card space-y-3" onSubmit={submit}>
      <p className="font-semibold">Add content</p>
      <div className="flex flex-wrap gap-1">
        {(Object.keys(KIND_LABEL) as SourceKind[]).map((k) => (
          <button type="button" key={k} className={`tab ${kind === k ? 'tab-active' : ''}`} onClick={() => setKind(k)}>
            {k === 'file' ? 'Upload a file' : k === 'menu' ? 'Touch menu item' : k === 'qa' ? 'Questions and answers' : 'Paste text'}
          </button>
        ))}
      </div>
      <div>
        <label className="label">{kind === 'menu' ? 'Button label (the question)' : 'Title'}</label>
        <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={kind === 'file' ? 'Defaults to the file name' : ''} />
      </div>
      {(kind === 'text' || kind === 'menu') && (
        <div>
          <label className="label">{kind === 'menu' ? 'Answer the kiosk reads aloud' : 'Text (Markdown headings like "# Fees" are kept with their text)'}</label>
          <textarea className="input" rows={kind === 'menu' ? 3 : 8} value={text} onChange={(e) => setText(e.target.value)} />
        </div>
      )}
      {kind === 'qa' && <QaEditor pairs={pairs} onChange={setPairs} />}
      {kind === 'file' && (
        <div>
          <label className="label">PDF, Word (.docx), Markdown or text file, up to 20 MB</label>
          <input type="file" accept=".pdf,.docx,.md,.markdown,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
      )}
      <button className="btn" disabled={busy || (kind === 'file' && !file)}>{busy ? 'Working…' : 'Add'}</button>
    </form>
  );
}

function EditSource({ source, busy, onClose, onSave }: {
  source: SourceDetail; busy: boolean; onClose: () => void; onSave: (patch: object) => void;
}) {
  const [title, setTitle] = useState(source.title);
  const [text, setText] = useState(source.text ?? '');
  const [pairs, setPairs] = useState<Pair[]>(source.pairs ?? [['', '']]);
  const editable = source.kind !== 'file';
  return (
    <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/30 p-4 sm:items-center">
      <div className="card max-h-[90vh] w-full max-w-2xl space-y-3 overflow-y-auto">
        <p className="text-lg font-semibold">Edit {KIND_LABEL[source.kind].toLowerCase()}</p>
        <div>
          <label className="label">{source.kind === 'menu' ? 'Button label' : 'Title'}</label>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        {source.kind === 'qa' && <QaEditor pairs={pairs} onChange={setPairs} />}
        {(source.kind === 'text' || source.kind === 'menu') && (
          <textarea className="input" rows={10} value={text} onChange={(e) => setText(e.target.value)} />
        )}
        {!editable && (
          <>
            <p className="muted">Uploaded files can be renamed here. To change the content, delete it and upload the new file.</p>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-neutral-50 p-3 text-sm">{source.text}</pre>
          </>
        )}
        <div className="flex justify-end gap-2">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn"
            disabled={busy}
            onClick={() =>
              onSave(
                source.kind === 'qa'
                  ? { title, pairs: pairs.filter(([q, a]) => q.trim() && a.trim()) }
                  : editable ? { title, text } : { title },
              )
            }
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Knowledge() {
  const [list, setList] = useState<SourceList | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<SourceDetail | null>(null);

  const load = useCallback(() => api.get<SourceList>('/api/kb/sources').then(setList).catch((e) => setMessage(e.message)), []);
  useEffect(() => { void load(); }, [load]);

  async function run(done: string, fn: () => Promise<unknown>): Promise<boolean> {
    setBusy(true);
    setMessage('');
    try {
      await fn();
      setMessage(done);
      await load();
      return true;
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  const toggle = (s: Source) => run(s.enabled ? 'Turned off.' : 'Turned on.', () => api.patch(`/api/kb/sources/${s.id}`, { enabled: !s.enabled }));
  const remove = (s: Source) => window.confirm(`Delete "${s.title}"? This cannot be undone.`) && run('Deleted.', () => api.del(`/api/kb/sources/${s.id}`));
  const reindex = () => window.confirm('Re-index everything? This can take a few minutes.') && run('Re-indexed.', () => api.post('/api/kb/reindex'));
  const edit = (s: Source) => api.get<SourceDetail>(`/api/kb/sources/${s.id}`).then(setEditing).catch((e) => setMessage(e.message));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Knowledge base</h2>
        <button className="btn-secondary" disabled={busy} onClick={reindex}>Re-index all</button>
      </div>
      {list?.needs_reindex && (
        <p className="card border-accent font-semibold text-accent">The embedding model changed. Re-index before the kiosk can answer.</p>
      )}
      {message && <p className="font-semibold" role="status">{message}</p>}
      <AddSource busy={busy} onSubmit={(data) => run('Added. It is live for the next question.', () => api.form('/api/kb/sources', data))} />
      <div className="card overflow-x-auto p-0">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-neutral-200 text-neutral-500">
            <tr>
              <th className="p-3">Title</th><th className="p-3">Type</th><th className="p-3">Chunks</th>
              <th className="p-3">Added</th><th className="p-3">On</th><th className="p-3" />
            </tr>
          </thead>
          <tbody>
            {list?.sources.map((s) => (
              <tr key={s.id} className="border-b border-neutral-100 last:border-0">
                <td className="p-3 font-semibold">{s.title}</td>
                <td className="p-3">{KIND_LABEL[s.kind]}</td>
                <td className="p-3">{s.chunk_count}</td>
                <td className="p-3">{new Date(s.created_at).toLocaleDateString()}</td>
                <td className="p-3">
                  <button
                    role="switch"
                    aria-checked={s.enabled}
                    disabled={busy}
                    onClick={() => toggle(s)}
                    className={`h-7 w-12 rounded-full p-1 transition ${s.enabled ? 'bg-ink' : 'bg-neutral-300'}`}
                  >
                    <span className={`block h-5 w-5 rounded-full bg-white transition ${s.enabled ? 'translate-x-5' : ''}`} />
                  </button>
                </td>
                <td className="space-x-3 whitespace-nowrap p-3 text-right">
                  <button className="font-semibold" onClick={() => edit(s)}>Edit</button>
                  <button className="font-semibold text-accent" onClick={() => remove(s)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {list?.sources.length === 0 && <p className="muted p-4">No content yet.</p>}
      </div>
      {editing && (
        <EditSource
          source={editing}
          busy={busy}
          onClose={() => setEditing(null)}
          onSave={(patch) => run('Saved.', () => api.patch(`/api/kb/sources/${editing.id}`, patch)).then((ok) => ok && setEditing(null))}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Write** `dashboard/src/pages/TestQuestion.tsx`

```tsx
import { useState, type FormEvent } from 'react';
import { api, type TestResult } from '../api';

const STATUS = {
  answered: ['Answered', 'bg-ink text-white'],
  unmatched: ['No match: the kiosk says it does not have that information', 'bg-accent text-white'],
  offline: ['Language model unreachable: the kiosk shows the touch menu', 'bg-neutral-300'],
} as const;

export default function TestQuestion() {
  const [question, setQuestion] = useState('');
  const [result, setResult] = useState<TestResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function ask(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      setResult(await api.post<TestResult>('/api/kb/test', { question }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Test a question</h2>
      <form className="card flex gap-2" onSubmit={ask}>
        <input className="input" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="What would a visitor ask?" />
        <button className="btn" disabled={busy || !question.trim()}>{busy ? 'Asking…' : 'Ask'}</button>
      </form>
      {error && <p className="font-semibold text-accent">{error}</p>}
      {result && (
        <>
          <div className="card space-y-2">
            <span className={`inline-block rounded-full px-3 py-1 text-sm font-semibold ${STATUS[result.status][1]}`}>{STATUS[result.status][0]}</span>
            {result.answer && <p className="text-lg">{result.answer}</p>}
          </div>
          <div className="card space-y-3">
            <p className="font-semibold">Closest matches</p>
            <p className="muted">Matches below the line (score {result.threshold.toFixed(2)}) are not sent to the language model.</p>
            {result.hits.map((h, i) => (
              <div key={i} className="space-y-1">
                <div className="relative h-2 rounded-full bg-neutral-100">
                  <div className={`h-2 rounded-full ${h.score >= result.threshold ? 'bg-ink' : 'bg-neutral-400'}`} style={{ width: `${Math.max(0, h.score) * 100}%` }} />
                  <div className="absolute top-[-4px] h-4 w-0.5 bg-accent" style={{ left: `${result.threshold * 100}%` }} />
                </div>
                <p className="text-sm"><span className="font-semibold">{h.score.toFixed(2)} · {h.title}</span>{h.heading && ` · ${h.heading}`}</p>
                <p className="muted line-clamp-3">{h.text}</p>
              </div>
            ))}
            {result.hits.length === 0 && <p className="muted">The knowledge base is empty.</p>}
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Write** `dashboard/src/pages/Unmatched.tsx`

```tsx
import { useEffect, useState } from 'react';
import { api } from '../api';

interface Data { enabled: boolean; items: { id: number; ts: number; text: string }[] }

export default function Unmatched() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState('');
  useEffect(() => { api.get<Data>('/api/kb/unmatched').then(setData).catch((e) => setError(e.message)); }, []);

  if (error) return <p className="font-semibold text-accent">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Unmatched questions</h2>
      {!data.enabled ? (
        <div className="card">
          <p className="font-semibold">Logging is off.</p>
          <p className="muted mt-1">
            This list stores what visitors asked when the kiosk had no answer, so it stays off unless IIT turns it on in
            Settings. When on, questions are kept for 30 days and the on-screen privacy notice says so.
          </p>
        </div>
      ) : data.items.length === 0 ? (
        <p className="muted">No unmatched questions yet.</p>
      ) : (
        <ul className="card divide-y divide-neutral-100 p-0">
          {data.items.map((q) => (
            <li key={q.id} className="p-3">
              <p>{q.text}</p>
              <p className="muted">{new Date(q.ts * 1000).toLocaleString()}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Build, check, commit**

Run: `cd dashboard && npm run build` → no errors. In dev: add pasted text, see it in the table, ask about it on Test a question (status Answered with the source on top), turn it off and see it drop out of the matches, edit and delete it. Upload a small PDF. Add a touch menu item and check that it appears on the kiosk's menu sheet (Internet fail, then ask).

```bash
git add dashboard/src
git commit -m "<KEY>: manage knowledge base and test questions from the dashboard"
```

---

### Task 8: Settings page with calibration preview and PIN change

**Files:**
- Modify: `dashboard/src/pages/Settings.tsx`
- Create: `dashboard/src/ZonePreview.tsx`

**Interfaces:**
- Consumes: `api`, `Settings`, `Preview`.
- Produces: `ZonePreview({ band, minFrac, mirror })`.

- [ ] **Step 1: Write** `dashboard/src/ZonePreview.tsx`

```tsx
import { useEffect, useRef, useState } from 'react';
import { api, type Preview } from './api';

// Draws the detection zone and live person boxes. Coordinates only: no camera image exists here.
export default function ZonePreview({ band, minFrac, mirror }: { band: number; minFrac: number; mirror: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let live = true;
    const load = () =>
      api.get<Preview>('/api/vision/preview')
        .then((p) => { if (live) { setPreview(p); setMissing(false); } })
        .catch(() => live && setMissing(true));
    load();
    const t = window.setInterval(load, 500);
    return () => { live = false; window.clearInterval(t); };
  }, []);

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    const g = c.getContext('2d')!;
    const W = c.width, H = c.height;
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#F5F5F5';
    g.fillRect(0, 0, W, H);
    const left = ((1 - band) / 2) * W, right = ((1 + band) / 2) * W;
    g.fillStyle = 'rgba(225,37,27,0.08)';
    g.fillRect(left, 0, right - left, H);
    g.strokeStyle = '#E1251B';
    g.setLineDash([6, 4]);
    g.strokeRect(left, 0, right - left, H);
    g.setLineDash([]);
    g.fillStyle = '#E1251B';
    g.fillRect(6, H - minFrac * H, 6, minFrac * H); // minimum box height guide
    if (!preview) return;
    const sx = W / preview.w, sy = H / preview.h;
    for (const [x1, y1, x2, y2, score] of preview.boxes) {
      const cx = ((x1 + x2) / 2 / preview.w) * 2 - 1;
      const inZone = (y2 - y1) / preview.h >= minFrac && Math.abs(cx) <= band;
      const bx = mirror ? W - x2 * sx : x1 * sx;
      g.strokeStyle = inZone ? '#111317' : '#A3A3A3';
      g.lineWidth = inZone ? 3 : 1.5;
      g.strokeRect(bx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
      g.fillStyle = g.strokeStyle;
      g.font = '12px system-ui';
      g.fillText(score.toFixed(2), bx + 4, y1 * sy + 14);
    }
  }, [preview, band, minFrac, mirror]);

  return (
    <div className="space-y-2">
      <canvas ref={canvas} width={320} height={240} className="w-full max-w-md rounded-xl border border-neutral-200" />
      <p className="muted">
        {missing
          ? 'No live boxes: the camera service is not running.'
          : 'Black boxes count as in the zone. The red band is "in front"; the red bar on the left is the minimum height. No image is captured or saved.'}
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Write** `dashboard/src/pages/Settings.tsx`

```tsx
import { useEffect, useState, type FormEvent } from 'react';
import { api, type Settings as S } from '../api';
import ZonePreview from '../ZonePreview';

function Slider({ label, value, min, max, step, show, onChange }: {
  label: string; value: number; min: number; max: number; step: number; show: (v: number) => string; onChange: (v: number) => void;
}) {
  return (
    <label className="block">
      <span className="label flex justify-between"><span>{label}</span><span className="font-normal">{show(value)}</span></span>
      <input type="range" className="w-full accent-ink" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function Toggle({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-start justify-between gap-4">
      <span><span className="font-semibold">{label}</span>{hint && <span className="muted block">{hint}</span>}</span>
      <button type="button" role="switch" aria-checked={checked} onClick={() => onChange(!checked)}
        className={`mt-1 h-7 w-12 shrink-0 rounded-full p-1 transition ${checked ? 'bg-ink' : 'bg-neutral-300'}`}>
        <span className={`block h-5 w-5 rounded-full bg-white transition ${checked ? 'translate-x-5' : ''}`} />
      </button>
    </label>
  );
}

const pct = (v: number) => `${Math.round(v * 100)}%`;

function ChangePin() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [repeat, setRepeat] = useState('');
  const [message, setMessage] = useState('');

  async function save(e: FormEvent) {
    e.preventDefault();
    if (next !== repeat) return setMessage('The new PINs do not match.');
    try {
      await api.post('/api/auth/pin', { current, new: next });
      setMessage('PIN changed.');
      setCurrent(''); setNext(''); setRepeat('');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    }
  }

  const field = (label: string, value: string, set: (v: string) => void) => (
    <label className="block">
      <span className="label">{label}</span>
      <input className="input" inputMode="numeric" type="password" maxLength={6} value={value} onChange={(e) => set(e.target.value.replace(/\D/g, ''))} />
    </label>
  );
  return (
    <form className="card space-y-3" onSubmit={save}>
      <p className="font-semibold">Change PIN</p>
      {field('Current PIN', current, setCurrent)}
      {field('New 6-digit PIN', next, setNext)}
      {field('Repeat new PIN', repeat, setRepeat)}
      {message && <p className="font-semibold">{message}</p>}
      <button className="btn" disabled={current.length !== 6 || next.length !== 6}>Change PIN</button>
    </form>
  );
}

export default function Settings() {
  const [s, setS] = useState<S | null>(null);
  const [saved, setSaved] = useState<S | null>(null);
  const [message, setMessage] = useState('');

  useEffect(() => { api.get<S>('/api/settings').then((v) => { setS(v); setSaved(v); }).catch((e) => setMessage(e.message)); }, []);
  if (!s) return <p className="muted">{message || 'Loading…'}</p>;

  const set = <K extends keyof S>(key: K, value: S[K]) => { setS({ ...s, [key]: value }); setMessage(''); };
  const dirty = JSON.stringify(s) !== JSON.stringify(saved);

  async function save() {
    try {
      const v = await api.put<S>('/api/settings', s);
      setS(v); setSaved(v); setMessage('Saved.');
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="space-y-4 pb-24">
      <h2 className="text-xl font-semibold">Settings</h2>

      <section className="card space-y-4">
        <p className="font-semibold">Sound</p>
        <Slider label="Speaker volume" value={s.volume} min={0} max={1} step={0.05} show={pct} onChange={(v) => set('volume', v)} />
        <Toggle label="Background music" checked={s.music_on} onChange={(v) => set('music_on', v)} />
        <Slider label="Music volume" value={s.music_volume} min={0} max={1} step={0.05} show={pct} onChange={(v) => set('music_volume', v)} />
        <Toggle label="Quiet mode" hint="No music, and the voice at half volume." checked={s.quiet_mode} onChange={(v) => set('quiet_mode', v)} />
      </section>

      <section className="card space-y-4">
        <p className="font-semibold">Visitors</p>
        <Toggle label="Start in kids mode" hint="Simple, encouraging language for every new visitor." checked={s.kids_default} onChange={(v) => set('kids_default', v)} />
        <Slider label="Wait before greeting the next visitor" value={s.greet_cooldown_s} min={5} max={120} step={5} show={(v) => `${v} s`} onChange={(v) => set('greet_cooldown_s', v)} />
      </section>

      <section className="card space-y-4">
        <p className="font-semibold">Detection zone</p>
        <ZonePreview band={s.centre_band} minFrac={s.min_box_height_frac} mirror={s.mirror} />
        <Slider label="How close (minimum person height)" value={s.min_box_height_frac} min={0.05} max={0.9} step={0.01} show={pct} onChange={(v) => set('min_box_height_frac', v)} />
        <Slider label="How central (width of the zone)" value={s.centre_band} min={0.1} max={1} step={0.05} show={pct} onChange={(v) => set('centre_band', v)} />
        <Slider label="Approach sensitivity (growth needed)" value={s.approach_growth} min={0.02} max={0.6} step={0.01} show={pct} onChange={(v) => set('approach_growth', v)} />
        <Slider label="Standing time before greeting" value={s.dwell_s} min={0.5} max={5} step={0.1} show={(v) => `${v.toFixed(1)} s`} onChange={(v) => set('dwell_s', v)} />
        <Toggle label="Mirror eye direction" hint="Turn on if the eyes look away from the visitor." checked={s.mirror} onChange={(v) => set('mirror', v)} />
      </section>

      <section className="card space-y-4">
        <p className="font-semibold">Answers</p>
        <Slider label="Match threshold" value={s.min_score} min={0} max={1} step={0.01} show={(v) => v.toFixed(2)} onChange={(v) => set('min_score', v)} />
        <p className="muted">Higher means fewer but safer answers. Check changes on "Test a question".</p>
      </section>

      <section className="card space-y-4">
        <p className="font-semibold">Privacy</p>
        <Toggle
          label="Keep unmatched questions"
          hint="Stores the words of questions the kiosk could not answer, for 30 days. Only turn on with IIT's agreement; the privacy notice will say so."
          checked={s.log_unmatched_questions}
          onChange={(v) => set('log_unmatched_questions', v)}
        />
      </section>

      <ChangePin />

      <div className="fixed inset-x-0 bottom-0 border-t border-neutral-200 bg-white p-3">
        <div className="mx-auto flex max-w-5xl items-center justify-end gap-3">
          {message && <p className="font-semibold">{message}</p>}
          <button className="btn-secondary" disabled={!dirty} onClick={() => { setS(saved); setMessage(''); }}>Undo</button>
          <button className="btn" disabled={!dirty} onClick={save}>Save settings</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Privacy notice on the kiosk when logging is on**

The settings toggle says the on-screen notice will mention it (baseline 5.3). In `core/admin/apply.py` `SettingsApplier.apply`, add at the end:
```python
        await self.runtime.send({"type": "privacy", "logQuestions": s["log_unmatched_questions"]})
```
In `ui/js/strings.js` add:
```js
    privacyLogging: 'Camera checks presence only. Questions the assistant cannot answer are kept for 30 days to improve it.',
```
In `ui/js/main.js`, add `let logQuestions = false;`, a message case:
```js
    case 'privacy': logQuestions = Boolean(m.logQuestions); updatePrivacy(); break;
```
and change `updatePrivacy()` to:
```js
function updatePrivacy() {
  if (root.dataset.camera === 'off') privacy.textContent = t('privacyOff');
  else privacy.textContent = logQuestions ? t('privacyLogging') : t('privacy');
}
```
Then in `Runtime.snapshot()` (M1), keep the privacy flag for new connections: in `SettingsApplier.apply` also set `self.runtime.privacy = {"type": "privacy", "logQuestions": s["log_unmatched_questions"]}`, and in `snapshot()` add `if getattr(self, "privacy", None): msgs.insert(-1, self.privacy)`.

Add to `tests/test_settings.py`:
```python
def test_applier_announces_privacy_notice():
    sent = []

    async def send(msg):
        sent.append(msg)

    rt = Runtime(Controller(ControllerConfig()), FakeSpeech(), CannedAnswerer(), send)
    applier = SettingsApplier(rt, FakeServices(), "", set_volume=lambda v: None)
    values = {**Settings(Database(":memory:"), CFG).all(), "log_unmatched_questions": True}
    asyncio.run(applier.apply(values))
    assert {"type": "privacy", "logQuestions": True} in sent
    assert {"type": "privacy", "logQuestions": True} in rt.snapshot()
```

- [ ] **Step 4: Build, test, commit**

Run: `uv run pytest -v` → all PASS; `cd dashboard && npm run build` → no errors.

```bash
uv run ruff format . && uv run ruff check --fix .
git add dashboard/src core/admin/apply.py core/runtime.py ui tests/test_settings.py
git commit -m "<KEY>: add settings page with zone calibration and PIN change"
```

---

### Task 9: End-to-end check on the kiosk screen and a LAN laptop

**Files:** none (manual verification; fix anything found in a follow-up `issue/` branch)

- [ ] **Step 1: Build and serve the dashboard locally**

```bash
cd dashboard && npm run build && cd ..
uv run python -m core --dev
```

- [ ] **Step 2: On the kiosk page** (http://localhost:8765/?dev=1 at 1080 x 1920)

1. Tap the gear briefly. Expected: nothing opens.
2. Hold the gear 3 s. Expected: the ring fills and the PIN pad opens at http://localhost:8080/.
3. "Back to kiosk" returns to the character page.
4. Log in, then leave it untouched for 5 minutes. Expected: back on the kiosk in Idle.
5. Five wrong PINs. Expected: "Too many wrong tries. Try again in 5:00."

- [ ] **Step 3: From a laptop on the same network** (http://<pi-or-laptop-ip>:8080/)

1. Log in with the PIN. The Exit button logs out and shows the PIN pad (it does not navigate to localhost).
2. Settings: change the cooldown to 30 s and save; on the kiosk, after a visitor leaves, a new Approach within 30 s does nothing.
3. Quiet mode on: the music stops; turn it off: the music returns.
4. Turn on "Keep unmatched questions": the kiosk's privacy notice changes; ask an off-topic question; it appears on Unmatched questions.
5. Health: Restart and Shut down are disabled in dev.

---

## After M5

Merge to `dev` by pull request. M6 serves `dashboard/dist` from the release tarball on the Pi.
