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
