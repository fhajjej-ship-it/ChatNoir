"""Concurrency proof against real independent SQLite connections and stored rows."""
from contextlib import closing
from pathlib import Path
import runpy
import sqlite3
import tempfile
import unittest

demo = runpy.run_path(str(Path(__file__).resolve().parents[1]
                            / "examples/email-code-race/demo.py"))


class EmailCodeRaceTests(unittest.TestCase):
    def test_vulnerable_two_and_eight_requests_create_multiple_sessions(self):
        for workers in (2, 8):
            with self.subTest(workers=workers):
                self.assertEqual(demo["run_case"](demo["consume_vulnerable"], workers), {
                    "concurrent_sessions": workers, "stored_sessions": workers,
                    "replay_sessions": 0, "legitimate_sessions": 1,
                })

    def test_fixed_two_and_eight_requests_persist_exactly_one_session(self):
        for workers in (2, 8):
            with self.subTest(workers=workers):
                self.assertEqual(demo["run_case"](demo["consume_fixed"], workers), {
                    "concurrent_sessions": 1, "stored_sessions": 1,
                    "replay_sessions": 0, "legitimate_sessions": 1,
                })

    def test_fixed_rejects_wrong_expired_and_exhausted_codes_without_sessions(self):
        for name, seed_options, supplied_code in (
            ("wrong", {}, "000000"), ("expired", {"expires_in": -1}, demo["CODE"]),
            ("exhausted", {"attempts": demo["MAX_ATTEMPTS"]}, demo["CODE"]),
        ):
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "codes.sqlite"
                demo["seed"](path, **seed_options)
                self.assertFalse(demo["sign_in"](path, demo["consume_fixed"], code=supplied_code))
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
                    self.assertIsNone(db.execute("SELECT consumed_at FROM codes").fetchone()[0])

    def test_fixed_rechecks_expiry_and_attempts_when_claiming_stale_read(self):
        for update in ("expires_at = 0", "attempts = 5"):
            with self.subTest(update=update), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "codes.sqlite"
                demo["seed"](path)

                def change_eligibility():
                    with closing(sqlite3.connect(path)) as db, db:
                        db.execute(f"UPDATE codes SET {update}")  # Fixed test literals only.

                self.assertFalse(demo["sign_in"](
                    path, demo["consume_fixed"], after_read=change_eligibility))
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
