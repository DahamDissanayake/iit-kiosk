import hashlib
import io
import tarfile

import pytest

import models.download as dl


@pytest.fixture(autouse=True)
def no_archives(monkeypatch):
    monkeypatch.setattr(dl, "ARCHIVES", {})


def _make_files(root):
    for name in dl.FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())


def _write_sums(path, root, tamper=False):
    lines = []
    for name in dl.FILES:
        digest = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if tamper:
            digest = "0" * 64
        lines.append(f"{digest}  {name}")
    path.write_text("\n".join(lines) + "\n")


def test_matching_checksums_pass(tmp_path, monkeypatch):
    _make_files(tmp_path)
    sums = tmp_path / "sums.sha256"
    _write_sums(sums, tmp_path)
    monkeypatch.setattr(dl, "CHECKSUMS", sums)
    assert dl.main(["--dest", str(tmp_path)]) == 0


def test_mismatched_checksum_is_refused(tmp_path, monkeypatch, capsys):
    _make_files(tmp_path)
    sums = tmp_path / "sums.sha256"
    _write_sums(sums, tmp_path, tamper=True)
    monkeypatch.setattr(dl, "CHECKSUMS", sums)
    assert dl.main(["--dest", str(tmp_path)]) == 1
    assert "checksum mismatch" in capsys.readouterr().err


def test_file_missing_from_checksum_list_is_refused(tmp_path, monkeypatch):
    _make_files(tmp_path)
    sums = tmp_path / "sums.sha256"
    sums.write_text("")
    monkeypatch.setattr(dl, "CHECKSUMS", sums)
    assert dl.main(["--dest", str(tmp_path)]) == 1


def _make_archive(root):
    path = root / "yolo11n-export.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        data = b"weights"
        info = tarfile.TarInfo("yolo/model.param")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return path


def test_archive_is_verified_and_unpacked(tmp_path, monkeypatch):
    _make_files(tmp_path)
    archive = _make_archive(tmp_path)
    monkeypatch.setattr(dl, "ARCHIVES", {archive.name: ("http://unused", "yolo")})
    sums = tmp_path / "sums.sha256"
    _write_sums(sums, tmp_path)
    with sums.open("a") as f:
        f.write(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}" + chr(10))
    monkeypatch.setattr(dl, "CHECKSUMS", sums)
    assert dl.main(["--dest", str(tmp_path)]) == 0
    assert (tmp_path / "yolo" / "model.param").read_bytes() == b"weights"


def test_archive_with_wrong_checksum_is_not_unpacked(tmp_path, monkeypatch):
    _make_files(tmp_path)
    archive = _make_archive(tmp_path)
    monkeypatch.setattr(dl, "ARCHIVES", {archive.name: ("http://unused", "yolo")})
    sums = tmp_path / "sums.sha256"
    _write_sums(sums, tmp_path)
    with sums.open("a") as f:
        f.write(f"{'0' * 64}  {archive.name}" + chr(10))
    monkeypatch.setattr(dl, "CHECKSUMS", sums)
    assert dl.main(["--dest", str(tmp_path)]) == 1
    assert not (tmp_path / "yolo").exists()
