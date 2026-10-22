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
        return self.db.execute(
            "SELECT pin_hash, failed_count, locked_until FROM auth WHERE id = 1"
        )[0]

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
