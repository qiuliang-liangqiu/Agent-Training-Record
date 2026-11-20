"""Self-checks for scripts/validate.py — run: python -m unittest discover -s tests -v"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]      # repo root
FRAMEWORK = REPO / "framework"
ROOT = FRAMEWORK
VALIDATE = FRAMEWORK / "scripts" / "validate.py"


def run(*paths: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(VALIDATE), *paths],
                          capture_output=True, text=True, cwd=ROOT)


def base_record(**over) -> dict:
    rec = {
        "schema": "atr/1",
        "handle": "octocat",
        "submitted_at": "2026-11-20T09:00:00Z",
        "agent": {"name": "pi", "version": "1.5.2", "model": "deepseek-flash"},
        "task": {"kind": "benchmark", "challenges": 10, "flag_total": 20, "hours": 2.5},
        "result": {"solved": 6, "flags": 8, "score": 1200},
        "metrics": {"triage_minutes": 5},
        "files": {"notes": "notes.md"},
        "consent": {"license": "CC-BY-4.0", "redistribute": True},
    }
    rec.update(over)
    return rec


class ValidatorTest(unittest.TestCase):
    def make(self, tmp: Path, record: dict, extra: dict[str, str] | None = None) -> Path:
        run_dir = tmp / "submissions" / "octocat" / "run-001"
        run_dir.mkdir(parents=True)
        (run_dir / "record.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        (run_dir / "notes.md").write_text("# notes\n", encoding="utf-8")
        for rel, text in (extra or {}).items():
            p = run_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return run_dir

    def test_valid_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.make(Path(tmp), base_record())
            r = run(str(d))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_real_flag_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.make(Path(tmp), base_record(), {"notes.md": "got flag{this_is_real}\n"})
            r = run(str(d))
            self.assertEqual(r.returncode, 1)
            self.assertIn("E7", r.stdout)

    def test_redacted_flag_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.make(Path(tmp), base_record(), {"notes.md": "got flag{REDACTED}\n"})
            self.assertEqual(run(str(d)).returncode, 0)

    def test_private_ip_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.make(Path(tmp), base_record(), {"notes.md": "target 10.1.2.3:8080\n"})
            r = run(str(d))
            self.assertEqual(r.returncode, 1)
            self.assertIn("private IP", r.stdout)

    def test_token_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.make(Path(tmp), base_record(),
                          {"notes.md": "TSEC_TOKEN=abcdef1234567890abcdef\n"})
            self.assertEqual(run(str(d)).returncode, 1)

    def test_home_path_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.make(Path(tmp), base_record(), {"notes.md": "at C:/Users/alice/x\n"})
            self.assertEqual(run(str(d)).returncode, 1)

    def test_range_violation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.make(Path(tmp), base_record(result={"solved": 99, "flags": 1, "score": 1}))
            r = run(str(d))
            self.assertEqual(r.returncode, 1)
            self.assertIn("E3", r.stdout)

    def test_handle_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.make(Path(tmp), base_record(handle="someoneelse"))
            self.assertEqual(run(str(d)).returncode, 1)

    def test_missing_listed_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = base_record(files={"notes": "notes.md", "sessions": ["sessions/none.jsonl"]})
            d = self.make(Path(tmp), rec)
            r = run(str(d))
            self.assertEqual(r.returncode, 1)
            self.assertIn("missing", r.stdout)

    def test_bad_jsonl_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = base_record(files={"notes": "notes.md", "sessions": ["sessions/s.jsonl"]})
            d = self.make(Path(tmp), rec, {"sessions/s.jsonl": '{"ok":1}\nnot json\n'})
            r = run(str(d))
            self.assertEqual(r.returncode, 1)
            self.assertIn("E8", r.stdout)

    def test_path_traversal_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = base_record(files={"notes": "../../../etc/passwd"})
            d = self.make(Path(tmp), rec)
            r = run(str(d))
            self.assertEqual(r.returncode, 1)

    def test_example_submission_passes(self):
        r = run(str(REPO / "submissions"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
