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
    # 校验器会输出中文；Windows 默认 GBK 解码会炸，固定 utf-8
    return subprocess.run([sys.executable, str(VALIDATE), *paths],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=ROOT)


ROW_GOOD = ('{"id":"c-01","family":"web","difficulty":"easy","outcome":"solved",'
            '"minutes":5,"flags":1,"flag_total":1}')


def base_record(**over) -> dict:
    rec = {
        "schema": "atr/2",
        "handle": "octocat",
        "submitted_at": "2026-11-20T09:00:00Z",
        "agent": {"name": "pi", "version": "1.5.2", "model": "deepseek-flash"},
        "task": {"kind": "benchmark", "challenges": 10, "flag_total": 20, "hours": 2.5},
        "result": {"solved": 6, "flags": 8, "score": 1200},
        "metrics": {"triage_minutes": 5},
        "files": {"notes": "notes.md", "challenges": "challenges.jsonl"},
        "consent": {"license": "CC-BY-4.0", "redistribute": True},
    }
    rec.update(over)
    return rec


class ValidatorTest(unittest.TestCase):
    def make(self, tmp: Path, record: dict, extra: dict[str, str] | None = None) -> Path:
        run_dir = tmp / "contributions" / "octocat" / "run-001"
        run_dir.mkdir(parents=True)
        (run_dir / "record.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        (run_dir / "notes.md").write_text("# notes\n", encoding="utf-8")
        (run_dir / "challenges.jsonl").write_text(ROW_GOOD + chr(10), encoding="utf-8")
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

    def test_bad_outcome_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = ROW_GOOD.replace('"solved"', '"gave_up"')
            d = self.make(Path(tmp), base_record(),
                          {"challenges.jsonl": bad + chr(10)})
            r = run(str(d))
            self.assertEqual(r.returncode, 1)
            self.assertIn("E9", r.stdout)

    def test_aggregate_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            two = ROW_GOOD + chr(10) + ROW_GOOD.replace("c-01", "c-02")
            d = self.make(Path(tmp), base_record(result={"solved": 0, "flags": 0, "score": 0}),
                          {"challenges.jsonl": two + chr(10)})
            r = run(str(d))
            self.assertEqual(r.returncode, 1)
            self.assertIn("E10", r.stdout)

    def test_missing_challenges_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.make(Path(tmp), base_record(files={"notes": "notes.md"}))
            (d / "challenges.jsonl").unlink()
            r = run(str(d))
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn("W2", r.stdout)

    def test_single_without_trajectory_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = base_record(task={"kind": "single", "challenges": 1, "flag_total": 1, "hours": 1},
                              result={"solved": 1, "flags": 1, "score": 100})
            d = self.make(Path(tmp), rec)
            r = run(str(d))
            self.assertIn("W4", r.stdout)

    def test_short_trajectory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = base_record(task={"kind": "single", "challenges": 1, "flag_total": 1, "hours": 1},
                              result={"solved": 1, "flags": 1, "score": 100},
                              files={"notes": "notes.md", "challenges": "challenges.jsonl",
                                     "trajectory": "trajectory.md"})
            d = self.make(Path(tmp), rec, {"trajectory.md": "# t" + chr(10) + chr(10) + "## 输入" + chr(10) + chr(10) + "## 步骤" + chr(10)})
            r = run(str(d))
            self.assertEqual(r.returncode, 1)
            self.assertIn("E11", r.stdout)

    def test_full_trajectory_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = base_record(task={"kind": "single", "challenges": 1, "flag_total": 1, "hours": 1},
                              result={"solved": 1, "flags": 1, "score": 100},
                              files={"notes": "notes.md", "challenges": "challenges.jsonl",
                                     "trajectory": "trajectory.md"})
            traj = ("# x 成功轨迹" + chr(10) + chr(10) + "## 输入" + chr(10) + chr(10) + "附件 evil.zip" + chr(10) + chr(10) + "## 步骤" + chr(10) + chr(10) + "1. 反编译看到 key 写死在 native 层，提取出来" + chr(10) +
                       "2. 用 key 解密 assets 里的 blob，得到路由和参数名" + chr(10) +
                       "3. 按路由发请求，回显里拿到 flag" + chr(10) + chr(10) + chr(10) + "## 复现" + chr(10) + chr(10) + "```bash" + chr(10) + "unzip evil.zip" + chr(10) + "```" + chr(10))
            d = self.make(Path(tmp), rec, {"trajectory.md": traj})
            r = run(str(d))
            self.assertEqual(r.returncode, 0, r.stdout)

    def test_example_submission_passes(self):
        r = run(str(FRAMEWORK / "examples"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_empty_contributions_dir_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "contributions"
            empty.mkdir()
            (empty / ".gitkeep").write_text("", encoding="utf-8")
            r = run(str(empty))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
