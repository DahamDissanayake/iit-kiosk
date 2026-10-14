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


def test_lockout_survives_reopening_a_file_database(tmp_path):
    """A real restart: the database file is closed and opened again by a new connection."""
    path = tmp_path / "kiosk.db"
    now = [0.0]
    first = PinAuth(Database(path), clock=lambda: now[0])
    first.set_pin("482913")
    for _ in range(5):
        first.check("000000")
    second = PinAuth(Database(path), clock=lambda: now[0])
    assert second.check("482913").reason == "locked"
    now[0] += 301
    assert second.check("482913").ok
