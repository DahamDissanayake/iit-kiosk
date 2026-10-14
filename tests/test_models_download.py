import hashlib

import models.download as dl


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
