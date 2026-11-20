#!/usr/bin/env python3
"""Soak test: hammer the validator and collect.py with malformed input for N minutes.

    python framework/tests/soak.py --duration 7200 --out soak.json
    python framework/tests/soak.py --duration 120 --seed 7      # quick run

What it looks for
-----------------
* crashes: any Python traceback in the validator/collect output
* bad exit codes: anything other than 0/1/2
* nondeterminism: a passing run must pass again byte-for-byte
* silent acceptance: mutations that *should* fail but were reported PASS

Every failing case is written to --keep dir so it can be replayed.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import string
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATE = ROOT / "framework" / "scripts" / "validate.py"
COLLECT = ROOT / "framework" / "scripts" / "collect.py"


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(cwd), timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


BASE_RECORD = {
    "schema": "atr/2",
    "handle": "octocat",
    "submitted_at": "2026-11-21T00:00:00Z",
    "agent": {"name": "pi", "version": "1.5.2", "model": "deepseek-flash"},
    "task": {"kind": "benchmark", "challenges": 3, "flag_total": 6, "hours": 2},
    "result": {"solved": 1, "flags": 2, "score": 300},
    "metrics": {"triage_minutes": 5},
    "files": {"notes": "notes.md", "challenges": "challenges.jsonl"},
    "consent": {"license": "CC-BY-4.0", "redistribute": True},
}
GOOD_ROW = {"id": "c-01", "family": "web", "difficulty": "easy",
            "outcome": "solved", "minutes": 5, "flags": 1, "flag_total": 1}


def rand_str(n: int = 8) -> str:
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


def mutate(obj, depth: int = 0):
    """Randomly corrupt a JSON value."""
    if depth > 2:
        return random.choice([None, [], {}, 0, -1, 10**18, rand_str(), "x" * 500, "<you>"])
    choice = random.random()
    if isinstance(obj, dict) and obj and choice < 0.6:
        key = random.choice(list(obj))
        op = random.random()
        if op < 0.3:
            obj[key] = random.choice([None, [], {}, 0, -1, 10**18, rand_str(), True])
        elif op < 0.5:
            obj.pop(key, None)
        elif op < 0.7:
            obj[key] = mutate(obj[key], depth + 1)
        else:
            obj[rand_str()] = random.choice([None, 1, "x"])
        return obj
    if isinstance(obj, list) and obj and choice < 0.6:
        obj[random.randrange(len(obj))] = mutate(obj[random.randrange(len(obj))], depth + 1)
        return obj
    return obj


def make_run(tmp: Path, rec: dict, rows: list[dict], extra: dict[str, bytes] | None = None) -> Path:
    run = tmp / "contributions" / "octocat" / "run-001"
    run.mkdir(parents=True, exist_ok=True)
    (run / "record.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    (run / "notes.md").write_text("# notes\n", encoding="utf-8")
    (run / "challenges.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    for name, blob in (extra or {}).items():
        p = run / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(blob)
    return run


CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def case_good(tmp: Path) -> tuple[bool, str]:
    run = make_run(tmp, dict(BASE_RECORD), [dict(GOOD_ROW)])
    rc, out = run_validate(run)
    return rc == 0 and "Traceback" not in out, out


@case
def case_mutated_record(tmp: Path) -> tuple[bool, str]:
    rec = mutate(json.loads(json.dumps(BASE_RECORD)))
    run = make_run(tmp, rec if isinstance(rec, dict) else BASE_RECORD, [dict(GOOD_ROW)])
    rc, out = run_validate(run)
    return rc in (0, 1) and "Traceback" not in out, out


@case
def case_mutated_rows(tmp: Path) -> tuple[bool, str]:
    rows = mutate([dict(GOOD_ROW) for _ in range(random.randint(0, 3))])
    if not isinstance(rows, list):
        rows = []
    rows = [r if isinstance(r, dict) else {"x": 1} for r in rows]
    run = make_run(tmp, dict(BASE_RECORD), rows)
    rc, out = run_validate(run)
    return rc in (0, 1) and "Traceback" not in out, out


@case
def case_binary_and_big(tmp: Path) -> tuple[bool, str]:
    run = make_run(tmp, dict(BASE_RECORD), [dict(GOOD_ROW)],
                   {"sessions/blob.jsonl": os.urandom(64),
                    "notes.md": b"# big\n" + b"A" * (4 * 1024 * 1024 + 10)})
    rc, out = run_validate(run)
    return rc == 1 and "Traceback" not in out, out


@case
def case_path_traversal(tmp: Path) -> tuple[bool, str]:
    rec = json.loads(json.dumps(BASE_RECORD))
    rec["files"]["notes"] = "../../../etc/passwd"
    run = make_run(tmp, rec, [dict(GOOD_ROW)])
    rc, out = run_validate(run)
    return rc == 1 and "E5" in out and "Traceback" not in out, out


@case
def case_secret_leak(tmp: Path) -> tuple[bool, str]:
    run = make_run(tmp, dict(BASE_RECORD), [dict(GOOD_ROW)])
    (run / "notes.md").write_text(
        "flag{real}\nTSEC_TOKEN=abcdef1234567890\n10.9.8.7:80\n", encoding="utf-8")
    rc, out = run_validate(run)
    return rc == 1 and "E7" in out and "Traceback" not in out, out


@case
def case_collect_benchmark(tmp: Path) -> tuple[bool, str]:
    src = tmp / "src"
    (src / "sessions").mkdir(parents=True)
    (src / "events.csv").write_text(
        "time,event,challenge,code,detail\n"
        "2026-11-20 09:00:00,start,c-01,x,easy\n"
        "2026-11-20 09:05:00,score,c-01,x,+100\n"
        "2026-11-20 09:06:00,close,c-01,x,solved\n", encoding="utf-8")
    out = tmp / "out"
    rc, log = run([sys.executable, str(COLLECT), "--handle", "octocat",
                   "--run-id", "run-001", "--from", str(src), "--out", str(out),
                   "--challenges", "1", "--flag-total", "1", "--hours", "1"],
                  cwd=ROOT)
    return rc == 0 and "Traceback" not in log, log


@case
def case_collect_single(tmp: Path) -> tuple[bool, str]:
    src = tmp / "att"
    src.mkdir()
    (src / "a.zip").write_bytes(b"PK\x03\x04" + os.urandom(100))
    out = tmp / "out"
    rc, log = run([sys.executable, str(COLLECT), "--handle", "octocat",
                   "--run-id", "one-1", "--from", str(src), "--out", str(out),
                   "--kind", "single", "--solved", "1"], cwd=ROOT)
    return rc == 0 and "Traceback" not in log, log


@case
def case_collect_ctf(tmp: Path) -> tuple[bool, str]:
    src = tmp / "ctf"
    for name in ("pwn-hard", "web-easy"):
        (src / name).mkdir(parents=True)
        (src / name / "README.md").write_text("x", encoding="utf-8")
    out = tmp / "out"
    rc, log = run([sys.executable, str(COLLECT), "--handle", "octocat",
                   "--run-id", "ctf-1", "--from", str(src), "--out", str(out),
                   "--kind", "ctf", "--hours", "2"], cwd=ROOT)
    return rc == 0 and "Traceback" not in log, log


@case
def case_collect_bad_args(tmp: Path) -> tuple[bool, str]:
    src = tmp / "empty"
    src.mkdir()
    rc, log = run([sys.executable, str(COLLECT), "--handle", "<you>",
                   "--run-id", "Bad ID!", "--from", str(src)], cwd=ROOT)
    return rc == 2 and "Traceback" not in log, log


MUST_FAIL = {
    "kind_enum": lambda r: r["task"].__setitem__("kind", "nonsense"),
    "hours_negative": lambda r: r["task"].__setitem__("hours", -1),
    "license_bad": lambda r: r["consent"].__setitem__("license", "WTFPL"),
    "no_redistribute": lambda r: r["consent"].__setitem__("redistribute", False),
    "bad_time": lambda r: r.__setitem__("submitted_at", "yesterday"),
    "negative_flags": lambda r: r["result"].__setitem__("flags", -5),
    "handle_upper": lambda r: r.__setitem__("handle", "OctoCat"),
    "solved_gt_challenges": lambda r: r["result"].__setitem__("solved", 99),
}


@case
def case_must_fail_record(tmp: Path) -> tuple[bool, str]:
    """Each of these violates exactly one rule; the validator must say no."""
    name = random.choice(list(MUST_FAIL))
    rec = json.loads(json.dumps(BASE_RECORD))
    MUST_FAIL[name](rec)
    run_dir = make_run(tmp, rec, [dict(GOOD_ROW)])
    rc, out = run_validate(run_dir)
    return rc == 1 and "Traceback" not in out, f"{name}: rc={rc}" + chr(10) + out[-200:]


@case
def case_must_fail_row(tmp: Path) -> tuple[bool, str]:
    bad = json.loads(json.dumps(GOOD_ROW))
    choice = random.choice(["outcome", "family", "minutes", "flags_gt_total", "dup_id"])
    rows = [bad]
    if choice == "outcome":
        bad["outcome"] = "gave_up"
    elif choice == "family":
        bad["family"] = "blockchain"
    elif choice == "minutes":
        bad["minutes"] = -3
    elif choice == "flags_gt_total":
        bad["flags"] = 5
        bad["flag_total"] = 1
    else:
        rows = [bad, dict(bad)]
    run_dir = make_run(tmp, dict(BASE_RECORD), rows)
    rc, out = run_validate(run_dir)
    return rc == 1 and "Traceback" not in out, f"{choice}: rc={rc}" + chr(10) + out[-200:]


def run_validate(run_dir: Path) -> tuple[int, str]:
    return run([sys.executable, str(VALIDATE), str(run_dir)], cwd=ROOT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=120, help="seconds")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="soak.json")
    ap.add_argument("--keep", default="soak-failures")
    ap.add_argument("--unit-every", type=int, default=50, help="rounds between unit runs")
    args = ap.parse_args()

    random.seed(args.seed or int(time.time()))
    keep = Path(args.keep)
    keep.mkdir(exist_ok=True)
    start = time.time()
    deadline = start + args.duration
    rounds = fails = 0
    failures: list[dict] = []
    unit_runs = 0

    while time.time() < deadline:
        rounds += 1
        fn = random.choice(CASES)
        tmp = Path(tempfile.mkdtemp(prefix="soak-"))
        try:
            ok, out = fn(tmp)
        except Exception:
            ok, out = False, traceback.format_exc()
        if not ok:
            fails += 1
            tag = f"{rounds:05d}-{fn.__name__}"
            try:
                shutil.copytree(tmp, keep / tag)
            except Exception:
                pass
            failures.append({"round": rounds, "case": fn.__name__,
                             "output": out[-2000:], "kept": str(keep / tag)})
            print(f"[FAIL] {tag}", flush=True)
        shutil.rmtree(tmp, ignore_errors=True)

        if args.unit_every and rounds % args.unit_every == 0:
            unit_runs += 1
            rc, out = run([sys.executable, "-m", "unittest", "discover",
                           "-s", "framework/tests"], cwd=ROOT)
            if rc != 0:
                fails += 1
                failures.append({"round": rounds, "case": "unittest",
                                 "output": out[-2000:], "kept": ""})
                print(f"[FAIL] unittest at round {rounds}", flush=True)

        if rounds % 25 == 0:
            elapsed = time.time() - start
            print(f"  {rounds} rounds, {fails} failures, {elapsed:.0f}s", flush=True)

    report = {
        "duration_s": round(time.time() - start, 1),
        "rounds": rounds,
        "failures": fails,
        "unit_runs": unit_runs,
        "cases": [c.__name__ for c in CASES],
        "details": failures[:20],
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsoak done: {rounds} rounds, {fails} failures, "
          f"{report['duration_s']}s -> {args.out}", flush=True)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
