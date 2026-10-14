# M6: Deployment and Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Power on boots straight into the kiosk; crashed or hung services restart themselves; a tagged release deploys over Tailscale with automatic rollback; the database is backed up nightly; the system survives an 8-hour soak below 80 °C; and a cloned spare SD card is ready for a 2-minute swap at the venue.

**Architecture:** kiosk-core and kiosk-vision (and kiosk-voice, if M3 chose service mode) run as **systemd user services** of the `kiosk` user with lingering on, so they can reach the desktop's PipeWire audio. Both use `Type=notify` and a watchdog. Chromium is started by labwc's autostart in a restart loop, with the output rotated by `wlr-randr`. Releases are cloned into `/opt/kiosk/releases/<tag>`, and a `current` symlink switches between them. Data and secrets live in `/var/lib/kiosk`, which deploys never touch.

**Tech Stack:** Raspberry Pi OS 64-bit (Bookworm, labwc), systemd, bash, uv, GitHub Actions, Tailscale.

**Spec:** `docs/superpowers/specs/2026-10-14-mvp-build-design.md`; baseline sections 4.5, 6, 11, 12, 16. Builds on the M1 to M5 plans.

## Global Constraints

- Work on a branch off `dev` named `task/<KEY>-<short-slug>`; commit messages are `<KEY>: short imperative summary`. Releases are tagged on `main` after `dev` is merged at a release point.
- Never add a `Co-Authored-By` trailer, a "Generated with" line, or any AI or agent attribution anywhere.
- Never commit secrets. `/var/lib/kiosk/.env` is created on the Pi by `setup.sh` with mode 600.
- No Docker (baseline 12). No new Python or npm dependencies in M6. Pi packages installed by `setup.sh` are OS tools only (`sqlite3`, `rsync`, `wlr-randr`, `python3-picamera2`, Chromium, Tailscale).
- The kiosk only runs tagged releases (`vX.Y.Z`), never a branch.
- Exhibition rules: code freeze from the evening of 20 Oct; no deploys during event hours; unattended upgrades off; Chromium and libcamera held at tested versions.
- Shell scripts use `set -euo pipefail` and pass `shellcheck`.

## Changes to the baseline

- **User services.** Baseline 6.1 implies system services. These run as user services of `kiosk` with lingering on, because the speaker and mic go through the desktop session's PipeWire. Restart is `systemctl --user restart …`; the deploy command is `ssh kiosk@kiosk /opt/kiosk/deploy.sh vX.Y.Z` (no sudo).
- **kiosk-ui.** This is labwc's autostart running `deploy/kiosk-ui.sh` (a Chromium restart loop) rather than a systemd unit: Chromium needs the Wayland session, which autostart guarantees.
- **YOLO model files** come from a fixed `models-v1` GitHub release (exported once, checksummed), not rebuilt on every release, so their checksum never changes.

## Review Focus

1. **A release that fails its health check.** The previous release is restored automatically and the command exits non-zero. (Task 3: `test_failed_health_check_restores_previous_release`)
2. **Rollback with no previous release.** It fails with a clear message and leaves the current release alone. (Task 3: `test_rollback_without_previous_fails_cleanly`)
3. **Malformed tag.** `deploy.sh main` or `deploy.sh ../x` is refused before anything is cloned. (Task 3: `test_bad_tag_is_refused`)
4. **Soak driving the kiosk while the real camera sees nobody.** Real presence must not end the simulated visitor's conversations; dev presence wins for 30 s after each dev action. (Task 1: `test_dev_presence_overrides_camera_for_a_while`)
5. **Hung event loop.** If the core loop stops ticking, systemd's watchdog restarts it. Covered by the 8-hour soak and a manual check in Task 9 (stop the process with `kill -STOP` and watch systemd restart it).

---

## File Structure

```
core/runtime.py                 + watchdog ping, dev presence window
core/app.py                     + READY=1
core/vision_link.py             + ignore camera presence during the dev window
deploy/systemd/kiosk-core.service
deploy/systemd/kiosk-vision.service
deploy/systemd/kiosk-voice.service
deploy/systemd/kiosk-backup.service
deploy/systemd/kiosk-backup.timer
deploy/journald-kiosk.conf
deploy/sudoers-kiosk
deploy/kiosk-ui.sh
deploy/labwc-autostart
deploy/deploy.sh
deploy/setup.sh
deploy/backup.sh
models/download.py              + YOLO tarball from the models-v1 release
.github/workflows/release.yml
.github/workflows/models.yml
tools/soak.py
docs/runbook.md
tests/test_deploy.py, tests/test_runtime.py (append), tests/test_vision_link.py (append)
```

---

### Task 1: Readiness, watchdog and the soak override

**Files:**
- Modify: `core/runtime.py`, `core/app.py`, `core/vision_link.py`
- Test: `tests/test_runtime.py`, `tests/test_vision_link.py` (append)

**Interfaces:**
- Consumes: `core.sdnotify.notify` (M4).
- Produces: `Runtime.dev_presence_until: float` (set to `clock() + 30` by every dev presence action); the runtime tick loop sends `WATCHDOG=1` once a second; the kiosk app sends `READY=1` once the runtime has started. `VisionLink` drops camera `Presence` events while `runtime.clock() < runtime.dev_presence_until` but still counts them as heartbeats.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vision_link.py`:
```python
def test_dev_presence_overrides_camera_for_a_while():
    async def go():
        now = [0.0]
        rt = Runtime(Controller(ControllerConfig()), FakeSpeech(), CannedAnswerer(delay_s=0),
                     noop, dev=True, clock=lambda: now[0])
        link = VisionLink(rt, sub=None, core_pub=FakePub(), clock=lambda: now[0])
        now[0] = 1.0
        await rt.on_ui({"type": "dev", "action": "approach"})
        await link.on_message("presence", msg())          # real camera sees nobody
        now[0] = 5.0
        await rt.handle(Tick())
        held = rt.c.state
        now[0] = 31.5
        await link.on_message("presence", msg())          # override expired
        now[0] = 35.0
        await rt.handle(Tick())
        return held, rt.c.state

    held, later = asyncio.run(go())
    assert held == "greeting"
    assert later == "farewell"
```

Append to `tests/test_runtime.py`:
```python
def test_tick_loop_pings_the_watchdog(monkeypatch):
    pings = []
    monkeypatch.setattr("core.runtime.notify", pings.append)

    async def go():
        rt, _ = make()
        rt.start()
        await asyncio.sleep(1.2)
        await rt.stop()

    asyncio.run(go())
    assert "WATCHDOG=1" in pings
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_vision_link.py tests/test_runtime.py -v`
Expected: FAIL (`held` is "farewell", since camera presence is not ignored; `notify` is not imported in `core.runtime`)

- [ ] **Step 3: Implement**

`core/runtime.py`:
- add `from core.sdnotify import notify`;
- in `__init__`: `self.dev_presence_until = 0.0`;
- replace `_tick_loop` with:
```python
    async def _tick_loop(self) -> None:
        last_ping = 0.0
        while True:
            await self.handle(Tick())
            now = time.monotonic()
            if now - last_ping >= 1.0:
                notify("WATCHDOG=1")  # systemd restarts us if the loop stops
                last_ping = now
            await asyncio.sleep(TICK_S)
```
- at the top of `_dev`, before the `if action == ...` chain:
```python
        if action in ("approach", "group", "linger", "walkpast", "leave"):
            # the soak test drives presence; ignore the real camera for a while
            self.dev_presence_until = self.clock() + 30.0
```

`core/vision_link.py`, in `on_message`, replace the `presence` branch with:
```python
        if topic == "presence":
            self.last_seen = self.clock()
            if not self.rt.c.camera_ok:
                await self.rt.handle(CameraStatus(True))
            if self.rt.dev and self.rt.clock() < self.rt.dev_presence_until:
                return
            await self.rt.handle(to_presence(payload))
```

`core/app.py`: import `from core.sdnotify import notify` and, in the lifespan, after the settings are applied and the links are started (just before `yield`), add `notify("READY=1")`.

- [ ] **Step 4: Run tests, commit**

Run: `uv run pytest -v` → all PASS

```bash
uv run ruff format . && uv run ruff check --fix .
git add core tests
git commit -m "<KEY>: signal readiness and watchdog to systemd and let soak override camera"
```

---

### Task 2: systemd units, journald, sudoers and the kiosk browser

**Files:**
- Create: `deploy/systemd/kiosk-core.service`, `deploy/systemd/kiosk-vision.service`, `deploy/systemd/kiosk-voice.service`, `deploy/journald-kiosk.conf`, `deploy/sudoers-kiosk`, `deploy/kiosk-ui.sh`, `deploy/labwc-autostart`

**Interfaces:**
- Produces: unit names `kiosk-core`, `kiosk-vision`, `kiosk-voice` (user units); paths `/opt/kiosk/current`, `/opt/kiosk/models`, `/var/lib/kiosk`.

- [ ] **Step 1: Write the units**

`deploy/systemd/kiosk-core.service`:
```ini
[Unit]
Description=IIT kiosk core: controller, answers, speech, dashboard
After=pipewire.service wireplumber.service
Wants=pipewire.service wireplumber.service
StartLimitIntervalSec=0

[Service]
Type=notify
NotifyAccess=main
WorkingDirectory=/opt/kiosk/current
Environment=KIOSK_DATA_DIR=/var/lib/kiosk
Environment=KIOSK_MODELS_DIR=/opt/kiosk/models
Environment=HF_HOME=/opt/kiosk/models/hf
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/kiosk/current/.venv/bin/python -m core
Restart=always
RestartSec=2
TimeoutStartSec=180
WatchdogSec=30

[Install]
WantedBy=default.target
```

`deploy/systemd/kiosk-vision.service`:
```ini
[Unit]
Description=IIT kiosk vision: camera presence (no images stored)
StartLimitIntervalSec=0

[Service]
Type=notify
NotifyAccess=main
WorkingDirectory=/opt/kiosk/current
Environment=KIOSK_MODELS_DIR=/opt/kiosk/models
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/kiosk/current/.venv/bin/python -m vision
Restart=always
RestartSec=2
TimeoutStartSec=60
WatchdogSec=15
CPUAffinity=2 3
Nice=5

[Install]
WantedBy=default.target
```

`deploy/systemd/kiosk-voice.service` (enabled only when `[voice] mode = "service"`):
```ini
[Unit]
Description=IIT kiosk voice: mic, VAD and speech to text
After=pipewire.service wireplumber.service
Wants=pipewire.service wireplumber.service
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory=/opt/kiosk/current
Environment=KIOSK_MODELS_DIR=/opt/kiosk/models
Environment=HF_HOME=/opt/kiosk/models/hf
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/kiosk/current/.venv/bin/python -m voice
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
```

`deploy/journald-kiosk.conf` (installed to `/etc/systemd/journald.conf.d/kiosk.conf`):
```ini
[Journal]
SystemMaxUse=200M
RuntimeMaxUse=50M
MaxRetentionSec=14day
```

`deploy/sudoers-kiosk` (installed to `/etc/sudoers.d/kiosk`, mode 440):
```
# Lets the dashboard's "Shut down" button power off the Pi cleanly.
kiosk ALL=(root) NOPASSWD: /usr/sbin/shutdown -h now
```

- [ ] **Step 2: Write the browser launcher**

`deploy/kiosk-ui.sh`:
```bash
#!/usr/bin/env bash
# Started by labwc autostart: rotate the screen, wait for kiosk-core, run Chromium full screen.
set -euo pipefail

ROTATION=${KIOSK_ROTATION:-90}
URL=${KIOSK_URL:-http://127.0.0.1:8765/}

output=$(wlr-randr | awk '/^[A-Z]/ {print $1; exit}')
if [[ -n ${output:-} ]]; then
  wlr-randr --output "$output" --transform "$ROTATION" || true
fi

until curl -fsS -o /dev/null "$URL"; do sleep 1; done

browser=$(command -v chromium-browser || command -v chromium)
while true; do
  "$browser" \
    --kiosk --noerrdialogs --disable-infobars --no-first-run \
    --autoplay-policy=no-user-gesture-required \
    --disable-session-crashed-bubble --disable-features=TranslateUI \
    --overscroll-history-navigation=0 --disable-pinch \
    --check-for-update-interval=31536000 --password-store=basic \
    "$URL" || true
  sleep 2
done
```

`deploy/labwc-autostart` (installed to `/home/kiosk/.config/labwc/autostart`):
```
/opt/kiosk/current/deploy/kiosk-ui.sh >/tmp/kiosk-ui.log 2>&1 &
```

- [ ] **Step 3: Lint, commit**

Run: `shellcheck deploy/kiosk-ui.sh` (install shellcheck with your OS package manager, or run it in CI; see Task 5). Expected: no warnings.

```bash
git add deploy
git commit -m "<KEY>: add systemd user units and kiosk browser launcher"
```

---

### Task 3: Deploy script with health check and rollback

**Files:**
- Create: `deploy/deploy.sh`
- Test: `tests/test_deploy.py`

**Interfaces:**
- Produces: `deploy.sh vX.Y.Z` (prepare, switch, restart, health check, auto-restore), `deploy.sh --prepare vX.Y.Z`, `deploy.sh --rollback`. Environment overrides for tests: `KIOSK_ROOT`, `KIOSK_REPO`, `KIOSK_RELEASES_URL`, `KIOSK_HEALTH_URL`, `KIOSK_HEALTH_TRIES`, `KIOSK_HEALTH_WAIT`.

- [ ] **Step 1: Write the failing tests** `tests/test_deploy.py`

```python
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="needs Linux bash"
)

SCRIPT = Path("deploy/deploy.sh").resolve()

STUBS = {
    # git clone --quiet --depth 1 --branch TAG REPO DIR
    "git": 'mkdir -p "${@: -1}"\n',
    "uv": "exit 0\n",
    "systemctl": 'echo "systemctl $*" >> "$STUB_LOG"\n',
    # health check: healthy unless the current release is listed in $STUB_BROKEN
    "curl": (
        'if [[ " $* " == *" -o /dev/null "* ]]; then\n'
        '  tag=$(basename "$(readlink -f "$KIOSK_ROOT/current")")\n'
        '  grep -qx "$tag" "$STUB_BROKEN" 2>/dev/null && exit 22 || exit 0\n'
        "fi\n"
        'cat "$STUB_TAR"\n'
    ),
}


@pytest.fixture
def env(tmp_path):
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name, body in STUBS.items():
        path = stubs / name
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(0o755)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"<html></html>"
        info = tarfile.TarInfo("index.html")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    (tmp_path / "dist.tgz").write_bytes(buf.getvalue())
    root = tmp_path / "kiosk"
    (root / "releases").mkdir(parents=True)
    return {
        **os.environ,
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "KIOSK_ROOT": str(root),
        "KIOSK_REPO": "https://example.invalid/repo.git",
        "KIOSK_RELEASES_URL": "https://example.invalid/releases",
        "KIOSK_HEALTH_URL": "http://127.0.0.1:1/health",
        "KIOSK_HEALTH_TRIES": "2",
        "KIOSK_HEALTH_WAIT": "0",
        "STUB_LOG": str(tmp_path / "log"),
        "STUB_BROKEN": str(tmp_path / "broken"),
        "STUB_TAR": str(tmp_path / "dist.tgz"),
    }


def deploy(env, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def current(env):
    return Path(os.path.realpath(Path(env["KIOSK_ROOT"]) / "current")).name


def test_first_deploy_goes_live(env):
    r = deploy(env, "v1.0.0")
    assert r.returncode == 0, r.stderr
    assert current(env) == "v1.0.0"
    assert (Path(env["KIOSK_ROOT"]) / "releases/v1.0.0/dashboard/dist/index.html").exists()
    assert "restart kiosk-vision kiosk-core" in Path(env["STUB_LOG"]).read_text()


def test_second_deploy_keeps_previous(env):
    deploy(env, "v1.0.0")
    deploy(env, "v1.1.0")
    assert current(env) == "v1.1.0"
    assert Path(os.path.realpath(Path(env["KIOSK_ROOT"]) / "previous")).name == "v1.0.0"


def test_failed_health_check_restores_previous_release(env):
    deploy(env, "v1.0.0")
    Path(env["STUB_BROKEN"]).write_text("v1.1.0\n")
    r = deploy(env, "v1.1.0")
    assert r.returncode != 0
    assert current(env) == "v1.0.0"
    assert "restored v1.0.0" in r.stderr


def test_rollback(env):
    deploy(env, "v1.0.0")
    deploy(env, "v1.1.0")
    r = deploy(env, "--rollback")
    assert r.returncode == 0, r.stderr
    assert current(env) == "v1.0.0"


def test_rollback_without_previous_fails_cleanly(env):
    deploy(env, "v1.0.0")
    r = deploy(env, "--rollback")
    assert r.returncode != 0
    assert "no previous release" in r.stderr
    assert current(env) == "v1.0.0"


@pytest.mark.parametrize("tag", ["main", "../x", "v1.0", "1.0.0"])
def test_bad_tag_is_refused(env, tag):
    r = deploy(env, tag)
    assert r.returncode != 0
    assert list((Path(env["KIOSK_ROOT"]) / "releases").iterdir()) == []


def test_prepare_does_not_switch(env):
    r = deploy(env, "--prepare", "v2.0.0")
    assert r.returncode == 0, r.stderr
    assert (Path(env["KIOSK_ROOT"]) / "releases/v2.0.0").is_dir()
    assert not (Path(env["KIOSK_ROOT"]) / "current").exists()
```

- [ ] **Step 2: Run to verify it fails**

Run (Linux, WSL, or CI): `uv run pytest tests/test_deploy.py -v`
Expected: FAIL (script missing; `bash` reports "No such file or directory")

- [ ] **Step 3: Implement** `deploy/deploy.sh`

```bash
#!/usr/bin/env bash
# Deploy a tagged release on the kiosk, as the kiosk user:
#   /opt/kiosk/deploy.sh v1.2.0        prepare, switch, restart, health check (auto-restore)
#   /opt/kiosk/deploy.sh --prepare v1.2.0
#   /opt/kiosk/deploy.sh --rollback    switch back to the previous release
set -euo pipefail

ROOT=${KIOSK_ROOT:-/opt/kiosk}
REPO=${KIOSK_REPO:-https://github.com/DahamDissanayake/iit-kiosk.git}
RELEASES_URL=${KIOSK_RELEASES_URL:-https://github.com/DahamDissanayake/iit-kiosk/releases/download}
HEALTH_URL=${KIOSK_HEALTH_URL:-http://127.0.0.1:8080/health}
HEALTH_TRIES=${KIOSK_HEALTH_TRIES:-60}
HEALTH_WAIT=${KIOSK_HEALTH_WAIT:-2}
SERVICES=(kiosk-vision kiosk-core)

log() { echo "[deploy] $*"; }
die() { echo "[deploy] $*" >&2; exit 1; }

check_tag() {
  [[ $1 =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "release tags look like v1.2.3, got '$1'"
}

prepare() {
  local tag=$1 dir tmp
  check_tag "$tag"
  dir=$ROOT/releases/$tag
  if [[ -d $dir ]]; then
    log "$tag already prepared"
    return
  fi
  tmp=$dir.tmp
  rm -rf "$tmp"
  log "fetching $tag"
  git clone --quiet --depth 1 --branch "$tag" "$REPO" "$tmp"
  (cd "$tmp" && uv venv --quiet --python /usr/bin/python3 --system-site-packages \
    && uv sync --quiet --frozen --no-dev)
  mkdir -p "$tmp/dashboard/dist"
  curl -fsSL "$RELEASES_URL/$tag/dashboard-dist.tar.gz" | tar -xz -C "$tmp/dashboard/dist"
  mv "$tmp" "$dir"
}

healthy() {
  local i
  for ((i = 0; i < HEALTH_TRIES; i++)); do
    if curl -fsS -o /dev/null "$HEALTH_URL"; then
      return 0
    fi
    sleep "$HEALTH_WAIT"
  done
  return 1
}

current_target() { readlink -f "$ROOT/current" 2>/dev/null || true; }

switch_to() {
  local target=$1 old
  old=$(current_target)
  ln -sfn "$target" "$ROOT/current.new"
  mv -Tf "$ROOT/current.new" "$ROOT/current"
  if [[ -n $old && $old != "$target" ]]; then
    ln -sfn "$old" "$ROOT/previous"
  fi
  systemctl --user restart "${SERVICES[@]}"
}

deploy() {
  local tag=$1 old
  prepare "$tag"
  old=$(current_target)
  switch_to "$ROOT/releases/$tag"
  if healthy; then
    log "$tag is live"
    return
  fi
  if [[ -n $old && -d $old ]]; then
    switch_to "$old"
    healthy && die "$tag failed its health check; restored $(basename "$old")"
    die "$tag failed its health check and $(basename "$old") is not healthy either"
  fi
  die "$tag failed its health check and there is no earlier release"
}

rollback() {
  local prev
  prev=$(readlink -f "$ROOT/previous" 2>/dev/null || true)
  [[ -n $prev && -d $prev && $prev != "$(current_target)" ]] || die "no previous release to roll back to"
  log "rolling back to $(basename "$prev")"
  switch_to "$prev"
  healthy || die "$(basename "$prev") is not healthy"
  log "rolled back to $(basename "$prev")"
}

case "${1:-}" in
  --rollback) rollback ;;
  --prepare) prepare "${2:-}" ;;
  "") die "usage: deploy.sh vX.Y.Z | --prepare vX.Y.Z | --rollback" ;;
  *) deploy "$1" ;;
esac
```

Mark it executable: `git update-index --chmod=+x deploy/deploy.sh` (and the same for `deploy/kiosk-ui.sh`).

- [ ] **Step 4: Run tests, lint, commit**

Run: `uv run pytest tests/test_deploy.py -v` → PASS (on Linux/WSL/CI). `shellcheck deploy/deploy.sh` → clean.

```bash
git add deploy/deploy.sh tests/test_deploy.py
git commit -m "<KEY>: deploy tagged releases with health check and rollback"
```

---

### Task 4: Pi setup script and model release

**Files:**
- Create: `deploy/setup.sh`, `.github/workflows/models.yml`
- Modify: `models/download.py`, `models/checksums.sha256`, `models/README.md`

**Interfaces:**
- Consumes: `deploy/deploy.sh --prepare`, unit files, `models.download`.
- Produces: `sudo bash deploy/setup.sh vX.Y.Z` on a fresh Pi; `models-v1` GitHub release holding `yolo11n-export.tar.gz`; `models.download` fetching and unpacking it into `<models>/yolo`.

- [ ] **Step 1: Models release workflow** `.github/workflows/models.yml`

```yaml
name: models

on:
  workflow_dispatch:
    inputs:
      tag:
        description: Release tag for the model files
        default: models-v1

permissions:
  contents: write

jobs:
  export:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen --group export
      - run: uv run --group export python -m tools.export_yolo
      - env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "${{ inputs.tag }}" models/yolo11n-export.tar.gz \
            --title "Model files (${{ inputs.tag }})" \
            --notes "YOLO11n exported at 320 px: NCNN and OpenVINO INT8. Not a kiosk release."
```

Run it once from the Actions tab.

- [ ] **Step 2: Fetch YOLO in** `models/download.py`

Add after `FILES`:
```python
ARCHIVES = {
    "yolo11n-export.tar.gz": (
        "https://github.com/DahamDissanayake/iit-kiosk/releases/download/models-v1/"
        "yolo11n-export.tar.gz",
        "yolo",
    ),
}
```
Add `import tarfile` and, in `main()`, after the `FILES` loop (inside the same checksum bookkeeping):
```python
    for name, (url, folder) in ARCHIVES.items():
        path = dest / name
        if not path.exists():
            print(f"downloading {name}")
            download(url, path)
        digest = sha256(path)
        recorded.append(f"{digest}  {name}")
        if not args.record and expected.get(name) != digest:
            bad.append(name)
            continue
        if not (dest / folder).exists():
            with tarfile.open(path) as tar:
                tar.extractall(dest, filter="data")
```
Run `uv run python -m models.download --record` once the release exists, and commit the updated `models/checksums.sha256`. Add to `models/README.md`: "YOLO files come from the `models-v1` release; re-export only with the `models` workflow and a new tag."

- [ ] **Step 3: Write** `deploy/setup.sh`

```bash
#!/usr/bin/env bash
# One-time setup of a fresh Raspberry Pi OS (64-bit, desktop) for the kiosk.
# Image the card with Raspberry Pi Imager: user "kiosk", hostname "kiosk", Wi-Fi, SSH on.
# Then, on the Pi:
#   git clone --branch vX.Y.Z https://github.com/DahamDissanayake/iit-kiosk.git /tmp/kiosk
#   sudo bash /tmp/kiosk/deploy/setup.sh vX.Y.Z
set -euo pipefail

TAG=${1:?usage: setup.sh vX.Y.Z}
KUSER=${KIOSK_USER:-kiosk}
SRC=$(cd "$(dirname "$0")/.." && pwd)
KHOME=$(getent passwd "$KUSER" | cut -d: -f6)
KUID=$(id -u "$KUSER")
as_kiosk() { sudo -u "$KUSER" XDG_RUNTIME_DIR="/run/user/$KUID" "$@"; }

[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }

echo "== packages"
apt-get update
apt-get install -y git curl sqlite3 rsync jq wlr-randr python3-picamera2 chromium-browser

echo "== freeze OS updates for the event"
systemctl disable --now unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
mapfile -t held < <(dpkg-query -W -f='${Package}\n' 'chromium*' 'libcamera*' 'rpicam*' 'python3-picamera2' 2>/dev/null || true)
((${#held[@]})) && apt-mark hold "${held[@]}"

echo "== uv"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh \
  | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh

echo "== folders and secrets"
install -d -o "$KUSER" -g "$KUSER" /opt/kiosk /opt/kiosk/releases /opt/kiosk/models \
  /var/lib/kiosk /var/lib/kiosk/backups
if [[ ! -f /var/lib/kiosk/.env ]]; then
  umask 077
  printf 'LLM_API_KEY=\nSESSION_SECRET=%s\nBACKUP_TARGET=\n' "$(openssl rand -hex 32)" \
    > /var/lib/kiosk/.env
  chown "$KUSER:$KUSER" /var/lib/kiosk/.env
fi
install -m 755 -o "$KUSER" -g "$KUSER" "$SRC/deploy/deploy.sh" /opt/kiosk/deploy.sh

echo "== logs, sudo rule, desktop autologin"
install -D -m 644 "$SRC/deploy/journald-kiosk.conf" /etc/systemd/journald.conf.d/kiosk.conf
systemctl restart systemd-journald
install -m 440 "$SRC/deploy/sudoers-kiosk" /etc/sudoers.d/kiosk
visudo -cf /etc/sudoers.d/kiosk
raspi-config nonint do_boot_behaviour B4

echo "== user services and browser autostart"
install -d -o "$KUSER" -g "$KUSER" "$KHOME/.config/systemd/user" "$KHOME/.config/labwc"
install -m 644 -o "$KUSER" -g "$KUSER" "$SRC"/deploy/systemd/*.service "$SRC"/deploy/systemd/*.timer \
  "$KHOME/.config/systemd/user/"
install -m 644 -o "$KUSER" -g "$KUSER" "$SRC/deploy/labwc-autostart" "$KHOME/.config/labwc/autostart"
loginctl enable-linger "$KUSER"

echo "== release $TAG and models"
as_kiosk /opt/kiosk/deploy.sh --prepare "$TAG"
ln -sfn "/opt/kiosk/releases/$TAG" /opt/kiosk/current
chown -h "$KUSER:$KUSER" /opt/kiosk/current
as_kiosk env KIOSK_MODELS_DIR=/opt/kiosk/models HF_HOME=/opt/kiosk/models/hf \
  /opt/kiosk/current/.venv/bin/python -m models.download
as_kiosk env KIOSK_MODELS_DIR=/opt/kiosk/models HF_HOME=/opt/kiosk/models/hf \
  /opt/kiosk/current/.venv/bin/python -c \
  "from core.config import load_config; from core.rag.ingest import make_embedder; \
from voice.stt import make_transcriber; c = load_config('/opt/kiosk/current/config.toml'); \
make_embedder(c); make_transcriber(c['voice']); print('models warm')"

echo "== remote access"
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh

as_kiosk systemctl --user daemon-reload
as_kiosk systemctl --user enable kiosk-core kiosk-vision kiosk-backup.timer

cat <<EOF

Setup done. Still to do by hand:
  1. sudo tailscale up --ssh                 (log in to the team tailnet)
  2. sudo -u $KUSER nano /var/lib/kiosk/.env  (set LLM_API_KEY; BACKUP_TARGET optional)
  3. sudo -u $KUSER /opt/kiosk/current/.venv/bin/python -m core.admin set-pin \\
       --config /opt/kiosk/current/config.toml   (with KIOSK_DATA_DIR=/var/lib/kiosk)
  4. If [voice] mode = "service": systemctl --user enable kiosk-voice (as $KUSER)
  5. sudo reboot
EOF
```

Mark executable: `git update-index --chmod=+x deploy/setup.sh`.

- [ ] **Step 4: Lint, commit**

Run: `shellcheck deploy/setup.sh` → clean.

```bash
git add deploy/setup.sh .github/workflows/models.yml models
git commit -m "<KEY>: provision the Pi and fetch model files from a fixed release"
```

---

### Task 5: Release workflow and shell lint in CI

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: on a `vX.Y.Z` tag, a GitHub release with `dashboard-dist.tar.gz` attached (what `deploy.sh` downloads).

- [ ] **Step 1: Write** `.github/workflows/release.yml`

```yaml
name: release

on:
  push:
    tags: ['v*.*.*']

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run pytest -q
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: dashboard/package-lock.json
      - run: npm ci && npm run build
        working-directory: dashboard
      - run: tar -czf dashboard-dist.tar.gz -C dashboard/dist .
      - env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "$GITHUB_REF_NAME" dashboard-dist.tar.gz \
            --title "$GITHUB_REF_NAME" --generate-notes --verify-tag
```

- [ ] **Step 2: Add shellcheck and the deploy tests to CI**

In `.github/workflows/ci.yml`, add a step to the `python` job after `uv run pytest -q`:
```yaml
      - run: shellcheck deploy/*.sh
```
(`ubuntu-latest` ships shellcheck. `tests/test_deploy.py` already runs there via pytest.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows
git commit -m "<KEY>: publish dashboard build with each tagged release"
```

---

### Task 6: Nightly backup

**Files:**
- Create: `deploy/backup.sh`, `deploy/systemd/kiosk-backup.service`, `deploy/systemd/kiosk-backup.timer`

**Interfaces:**
- Produces: `/var/lib/kiosk/backups/kiosk-YYYY-MM-DD.db` (7 kept), copied to `BACKUP_TARGET` (an rsync destination over Tailscale SSH, set in `.env`) when set.

- [ ] **Step 1: Write** `deploy/backup.sh`

```bash
#!/usr/bin/env bash
# Nightly SQLite backup (knowledge base, stats, settings). Keeps 7 days on the Pi and
# copies the newest to BACKUP_TARGET (e.g. daham@laptop:/backups/kiosk) when set in .env.
set -euo pipefail

DATA=${KIOSK_DATA_DIR:-/var/lib/kiosk}
DEST=$DATA/backups
mkdir -p "$DEST"
file=$DEST/kiosk-$(date +%F).db
sqlite3 "$DATA/kiosk.db" ".backup '$file'"
find "$DEST" -name 'kiosk-*.db' -type f | sort | head -n -7 | xargs -r rm --

target=$(sed -n 's/^BACKUP_TARGET=//p' "$DATA/.env" 2>/dev/null || true)
if [[ -n $target ]]; then
  rsync -a "$file" "$target/"
  echo "backup copied to $target"
else
  echo "BACKUP_TARGET not set: backup kept on the Pi only" >&2
fi
```

`deploy/systemd/kiosk-backup.service`:
```ini
[Unit]
Description=IIT kiosk nightly database backup

[Service]
Type=oneshot
Environment=KIOSK_DATA_DIR=/var/lib/kiosk
ExecStart=/opt/kiosk/current/deploy/backup.sh
```

`deploy/systemd/kiosk-backup.timer`:
```ini
[Unit]
Description=Run the kiosk backup every night

[Timer]
OnCalendar=*-*-* 02:30
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 2: Lint, commit**

Run: `shellcheck deploy/backup.sh` → clean. Mark it executable with `git update-index --chmod=+x deploy/backup.sh`.

```bash
git add deploy/backup.sh deploy/systemd/kiosk-backup.*
git commit -m "<KEY>: back up the kiosk database every night"
```

---

### Task 7: Soak tool

**Files:**
- Create: `tools/soak.py`
- Test: `tests/test_soak.py`

**Interfaces:**
- Consumes: the kiosk WebSocket (`/ws`, dev actions), `core.sysinfo`.
- Produces: `python -m tools.soak --hours 8 --csv soak.csv` (needs kiosk-core running with `--dev`); `Cycle` stats; `summarise(rows) -> dict`.

- [ ] **Step 1: Write the failing test** `tests/test_soak.py`

```python
from tools.soak import summarise


def test_summary_reports_cycles_failures_and_peak_temperature():
    rows = [
        {"ts": 0, "kind": "cycle", "ok": True, "seconds": 30.0, "temp_c": 61.0},
        {"ts": 60, "kind": "cycle", "ok": False, "seconds": 90.0, "temp_c": 72.5},
        {"ts": 180, "kind": "sample", "ok": True, "seconds": 0, "temp_c": 74.0},
    ]
    s = summarise(rows)
    assert s == {"cycles": 2, "failed": 1, "max_temp_c": 74.0, "hours": 0.05}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_soak.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.soak'`

- [ ] **Step 3: Implement** `tools/soak.py`

```python
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
            row = {"ts": round(start), "kind": "cycle", "ok": ok,
                   "seconds": round(time.time() - start, 1), "temp_c": read_temp()}
            rows.append(row)
            out.writerow(row)
            f.flush()
            print(json.dumps(row), flush=True)
            time.sleep(args.gap)
    print(json.dumps(summarise(rows)))


if __name__ == "__main__":
    main()
```

`websockets` is already installed through `uvicorn[standard]`; this is not a new dependency.

- [ ] **Step 4: Run tests, commit**

Run: `uv run pytest tests/test_soak.py -v` → PASS

```bash
uv run ruff format . && uv run ruff check --fix .
git add tools/soak.py tests/test_soak.py
git commit -m "<KEY>: add 8-hour soak tool"
```

---

### Task 8: Runbook and acceptance checklist

**Files:**
- Create: `docs/runbook.md`
- Modify: `README.md`

- [ ] **Step 1: Write** `docs/runbook.md`

```markdown
# Kiosk runbook

## Release and deploy

1. Merge `dev` into `main` by pull request; CI must be green.
2. Tag `main`: `git tag v1.0.0 && git push origin v1.0.0`. The release workflow attaches
   `dashboard-dist.tar.gz`.
3. Deploy over Tailscale: `ssh kiosk@kiosk /opt/kiosk/deploy.sh v1.0.0`.
   It restarts the services and waits for `/health`; if that fails it restores the previous
   release and exits with an error.
4. Roll back by hand: `ssh kiosk@kiosk /opt/kiosk/deploy.sh --rollback`.

Code freeze from the evening of 20 Oct. No deploys during event hours.

## Useful commands (as kiosk, over Tailscale SSH)

| What | Command |
| --- | --- |
| Service status | `systemctl --user status kiosk-core kiosk-vision` |
| Live logs | `journalctl --user -u kiosk-core -f` |
| Restart | `systemctl --user restart kiosk-vision kiosk-core` |
| Reload the screen | `pkill -f chromium` (the launcher restarts it) |
| Load content | `KIOSK_DATA_DIR=/var/lib/kiosk /opt/kiosk/current/.venv/bin/python -m core.rag.ingest add-file FILE --title TITLE` (from `/opt/kiosk/current`) |
| Set the PIN | `KIOSK_DATA_DIR=/var/lib/kiosk /opt/kiosk/current/.venv/bin/python -m core.admin set-pin` |
| Temperature | `vcgencmd measure_temp` |

## Spare SD card

After the soak passes on 20 Oct:
1. Shut down from the dashboard (Health, then Shut down) and remove the card.
2. On a laptop, read the card to an image with Raspberry Pi Imager's "Use custom" backup tool
   or `sudo dd if=/dev/sdX of=kiosk-v1.0.0.img bs=4M status=progress`.
3. Write the image to the spare 64 GB card and boot it once on the bench Pi to confirm.
4. Label it "Kiosk v1.0.0 spare", with the date.

Swap at the venue: shut down, swap the card, power on. The spare has the same data as of
cloning time; content added after that must be re-added (or copy `/var/lib/kiosk/kiosk.db`
from the latest backup with `scp`).

## Venue setup, 21 Oct

1. Place the cabinet: power socket within 3 m, camera at about 1.6 m, nothing bright behind
   visitors.
2. Connect to the venue Wi-Fi: `sudo nmcli dev wifi connect "SSID" password "..."`.
3. Check the dashboard Health page: internet connected, camera and mic working, temperature normal.
4. Settings: tune the detection zone with the live preview while a colleague walks up and past.
5. Set the volume for the hall; check that music ducks when someone approaches.
6. Set the PIN with IIT's contact and give it to them.
7. Run the acceptance checklist below with IIT's contact, who signs it off.

## Acceptance checklist (baseline 16)

| # | Test | How to run it | Pass |
| --- | --- | --- | --- |
| 1 | Idle animation and music | Watch idle for 1 min | [ ] |
| 2 | Music ducks on approach | Walk up slowly | [ ] |
| 3 | One greeting per visitor | Walk up and stay 30 s | [ ] |
| 4 | Passer-by not greeted | Walk across at 2 m without stopping | [ ] |
| 5 | At most one follow-up | Stay silent after the greeting for 30 s | [ ] |
| 6 | Polite release | Say "no thanks"; separately, walk away mid-answer | [ ] |
| 7 | English question answered from content | Ask 3 of the FAQs | [ ] |
| 8 | Honest "I don't have that" | Ask "What's the weather on Mars?" | [ ] |
| 9 | Kids mode | Tap Kids mode, ask a question; no personal questions asked | [ ] |
| 10 | Settings gear needs a 3 s hold and PIN | Tap, then hold; wrong and right PIN | [ ] |
| 11 | Five wrong PINs lock for 5 min | Enter 5 wrong PINs | [ ] |
| 12 | New content answerable | Add a Q&A in the dashboard, ask it at once | [ ] |
| 13 | Stats match a counted run | 10 people walk up; compare Overview encounters | [ ] |
| 14 | No images or video stored | `find / -xdev \( -iname '*.jpg' -o -iname '*.png' -o -iname '*.mp4' -o -iname '*.h264' \) -newermt today 2>/dev/null` prints nothing | [ ] |
| 15 | Camera unplugged: touch and voice work | Power off, disconnect, boot, tap to talk | [ ] |
| 16 | Internet cut: offline menu | Unplug the Wi-Fi router or `nmcli radio wifi off`, ask a question | [ ] |
| 17 | Next visitor gets a clean session | After a visitor leaves, ask a follow-up-only question ("how long?") | [ ] |
| 18 | Music never over the voice | Listen during the greeting and answers | [ ] |
| 19 | 8 h without restart, under 80 °C | Soak log from 20 Oct (`tools.soak` summary, `NRestarts` = 0) | [ ] |

Signed off by: ____________________  Date: __________
```

- [ ] **Step 2: Point the README to it**

Add to `README.md`:
```markdown
## Kiosk operations

Setup, deploy, rollback, spare SD card, venue checklist: `docs/runbook.md`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/runbook.md README.md
git commit -m "<KEY>: add runbook and acceptance checklist"
```

---

### Task 9: Bench Pi dry run, soak and SD clone (19 to 20 Oct)

**Files:** none (record results in `docs/benchmarks.md`; problems become `issue/` branches)

- [ ] **Step 1: Release candidate**

Merge `dev` into `main` by pull request and tag `v0.9.0` as the release candidate (tags must match `vX.Y.Z`, so no `-rc` suffix). `v1.0.0` is the frozen build in Step 5.

- [ ] **Step 2: Fresh install on the bench Pi**

Follow `deploy/setup.sh`'s header from a freshly imaged card, then the "still to do" list it prints. Reboot. Expected: the Pi boots into the portrait kiosk with no keyboard or mouse touch, and the dashboard is reachable at `http://kiosk:8080/` over Tailscale.

- [ ] **Step 3: Self-recovery checks**

1. `pkill -9 -f "python -m core"`. Expected: the screen reconnects within about 10 s; `systemctl --user show kiosk-core -p NRestarts` increases by 1.
2. `pkill -STOP -f "python -m vision"`. Expected: within 15 s systemd's watchdog kills and restarts kiosk-vision; the kiosk shows "Tap to talk" briefly, then recovers.
3. Kill Chromium. Expected: it comes back in about 2 s.
4. Pull the power, plug back in. Expected: boots straight into the kiosk.

- [ ] **Step 4: 8-hour soak in the closed cabinet**

Restart kiosk-core in dev mode for the soak only (`systemctl --user edit kiosk-core`, set `ExecStart=` to add `--dev`), cover nothing (the camera keeps running for realistic load), then:
```bash
uv run python -m tools.soak --hours 8 --csv soak.csv
```
Expected summary: `failed` 0 (or only during a deliberate restart), `max_temp_c` below 80, `NRestarts` 0 for both services. Record the summary in `docs/benchmarks.md`. Then remove the `--dev` override (`systemctl --user revert kiosk-core`) and restart.

- [ ] **Step 5: Freeze and clone**

Tag `v1.0.0` from `main`, deploy it, run the acceptance checklist once on the bench, then clone the card (runbook, "Spare SD card"). Code freeze starts now.
