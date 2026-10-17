#!/usr/bin/env python3
"""Synthetic single-use-code race; real SQLite writes, no network or accounts."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import hmac
from pathlib import Path
import sqlite3
import tempfile
import threading
import time

EMAIL = "alice@example.invalid"
CODE = "123456"  # Deliberately public teaching data, never a real credential.
MAX_ATTEMPTS = 5


def code_hash(code):
    return hashlib.sha256(f"{EMAIL}:{code}".encode()).hexdigest()


def seed(path, *, expires_in=60, attempts=0):
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE codes (
                id INTEGER PRIMARY KEY, email TEXT NOT NULL,
                digest TEXT NOT NULL, expires_at INTEGER NOT NULL,
                attempts INTEGER NOT NULL, consumed_at INTEGER
            );
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY, email TEXT NOT NULL
            );
        """)
        db.execute("INSERT INTO codes VALUES (1, ?, ?, ?, ?, NULL)",
                   (EMAIL, code_hash(CODE), int(time.time()) + expires_in, attempts))


def consume_vulnerable(db, token_id):
    # BUG: the caller's earlier read is stale; this update has no eligibility check.
    db.execute("UPDATE codes SET consumed_at = ? WHERE id = ?",
               (int(time.time()), token_id))
    return True


def consume_fixed(db, token_id):
    # The database decides the winner; session creation requires exactly one claim.
    now = int(time.time())
    claim = db.execute("""
        UPDATE codes SET consumed_at = ?
        WHERE id = ? AND consumed_at IS NULL
          AND expires_at > ? AND attempts < ?
    """, (now, token_id, now, MAX_ATTEMPTS))
    return claim.rowcount == 1


def sign_in(path, consume, *, code=CODE, after_read=None):
    # Each request owns an independent connection. SELECT happens before the
    # write transaction, so both requests can observe the unused row.
    db = sqlite3.connect(path, timeout=10)
    try:
        row = db.execute("""
            SELECT id, digest, expires_at, attempts, consumed_at
            FROM codes WHERE email = ?
        """, (EMAIL,)).fetchone()
        if (not row or row[4] is not None or row[2] <= int(time.time())
                or row[3] >= MAX_ATTEMPTS
                or not hmac.compare_digest(row[1], code_hash(code))):
            return False
        if after_read:
            after_read()
        with db:
            if not consume(db, row[0]):
                return False
            db.execute("INSERT INTO sessions (email) VALUES (?)", (EMAIL,))
        return True
    finally:
        db.close()


def run_case(consume, workers):
    with tempfile.TemporaryDirectory(prefix="chatnoir-email-race-") as directory:
        path = Path(directory) / "race.sqlite"
        seed(path)
        # Force every real read to see the unused row. No timing sleeps or fake
        # database responses: the only synthetic scheduling aid is this barrier.
        barrier = threading.Barrier(workers, timeout=10)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(sign_in, path, consume, after_read=barrier.wait)
                       for _ in range(workers)]
            successes = sum(future.result(timeout=15) for future in futures)
        db = sqlite3.connect(path)
        try:
            stored = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        finally:
            db.close()
        replay = sign_in(path, consume)
        legitimate = Path(directory) / "fresh-code.sqlite"
        seed(legitimate)
        return {"concurrent_sessions": successes, "stored_sessions": stored,
                "replay_sessions": int(replay),
                "legitimate_sessions": int(sign_in(legitimate, consume))}


def demonstrate():
    print("CHATNOIR / Synthetic email-code race (local SQLite)")
    results = {}
    for name, consume in (("vulnerable", consume_vulnerable), ("fixed", consume_fixed)):
        for workers in (2, 8):
            result = run_case(consume, workers)
            expected = workers if name == "vulnerable" else 1
            if result != {"concurrent_sessions": expected, "stored_sessions": expected,
                          "replay_sessions": 0, "legitimate_sessions": 1}:
                raise RuntimeError(f"Unexpected {name}/{workers} result: {result}")
            results[f"{name}/{workers}"] = result
            print(f"{name}: requests={workers}; sessions={result['stored_sessions']}; "
                  f"replay={result['replay_sessions']}; legitimate={result['legitimate_sessions']}")
    print("PASS: reproduced the race; atomic claim permits exactly one session.")
    print("Synthetic fixture only: not the Swarmix AI runtime or a scanner detection test.")
    return results


if __name__ == "__main__":
    demonstrate()
