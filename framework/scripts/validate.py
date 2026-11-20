#!/usr/bin/env python3
"""Validate a training-record submission (schema + privacy gate).

    python framework/scripts/validate.py contributions                     # all runs
    python framework/scripts/validate.py contributions/<handle>/<run-id>   # one run
    python framework/scripts/validate.py contributions --strict --json     # CI mode

Exit code 0 = all runs valid, 1 = at least one failed (or a warning under --strict),
2 = nothing found. Only the standard library is used, so CI needs no installs.

Rules enforced
--------------
E1  record.json exists and parses
E2  schema == "atr/1" and required fields/types/enums are correct
E3  numeric ranges (0 <= solved <= challenges, ...)
E4  path layout is contributions/<handle>/<run-id>/ and handle matches the directory
E5  every file listed in `files` exists, is inside the run dir, and has an allowed type
E6  size limits per file / per run
E7  privacy scan: real flags, tokens, private IPs, absolute home paths, e-mail
E8  sessions/*.jsonl parse line by line and pass the same privacy scan
E9  challenges.jsonl rows have the required keys / enums / ranges
E10 row aggregates do not exceed the run-level numbers in record.json
W1  (warning) no notes.md / no events.csv / no metrics
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA_ID = "atr/2"
KINDS = {"benchmark", "ctf", "single", "lab", "other"}
LICENSES = {"CC-BY-4.0", "CC0-1.0", "MIT"}
ALLOWED_EXT = {".md", ".txt", ".json", ".jsonl", ".csv", ".tsv"}
FAMILIES = {"web", "pwn", "crypto", "rev", "forensics", "misc", "osint", "other"}
OUTCOMES = {"solved", "partial", "dead_end", "env_broken", "out_of_budget", "not_started"}
DIFFICULTY = {"easy", "medium", "hard", "unknown"}
TRIAGE = {"A", "B", "C", "D", ""}
TEXT_EXT = ALLOWED_EXT
MAX_FILE = 4 * 1024 * 1024
MAX_RUN = 12 * 1024 * 1024
HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}$")
RUN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")

FLAG = re.compile(r"(?i)\bflag\{([^}\r\n]{1,200})\}")
FLAG_OK = {"REDACTED", "...", "word1.word2.word3"}
SECRETS = [
    ("github-token", re.compile(r"\b(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{20,}")),
    ("auth-header", re.compile(r"(?i)\bauthorization:\s*\S{12,}")),
    ("platform-token", re.compile(r"(?i)\b(?:BENCHMARK_TOKEN|TSEC_TOKEN|CTFY_TOKEN)\s*[=:]\s*[A-Za-z0-9._-]{12,}")),
]
PRIVATE_IP = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)
IP_OK = re.compile(r"<ip>|\b10\.0\.0\.0/8\b|\b192\.168\.0\.0/16\b|\b172\.16\.0\.0/12\b")
HOME_PATH = re.compile(r"(?:/home/|/Users/|[A-Za-z]:[\\/]+Users[\\/]+)[A-Za-z0-9._-]+")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
EMAIL_OK = re.compile(r"@example\.(com|org)|noreply@|@users\.noreply\.github\.com")


class Finding:
    def __init__(self, level: str, rule: str, path: str, message: str):
        self.level, self.rule, self.path, self.message = level, rule, path, message

    def as_dict(self):
        return {"level": self.level, "rule": self.rule, "path": self.path, "message": self.message}

    def __str__(self):
        return f"  [{self.level.upper():5}] {self.rule:<6} {self.path}: {self.message}"


def scan_text(rel: str, text: str) -> list[Finding]:
    out: list[Finding] = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in FLAG.finditer(line):
            if m.group(1) not in FLAG_OK and not m.group(1).startswith("<"):
                out.append(Finding("error", "E7", rel, f"line {i}: real-looking flag"))
                break
        for name, rx in SECRETS:
            if rx.search(line):
                out.append(Finding("error", "E7", rel, f"line {i}: {name}"))
                break
        if PRIVATE_IP.search(line) and not IP_OK.search(line):
            out.append(Finding("error", "E7", rel, f"line {i}: private IP"))
        if HOME_PATH.search(line):
            out.append(Finding("error", "E7", rel, f"line {i}: absolute home path"))
        if EMAIL.search(line) and not EMAIL_OK.search(line):
            out.append(Finding("error", "E7", rel, f"line {i}: e-mail address"))
    return out


TRAJ_MARKERS = ("## 输入", "## 步骤", "## 复现")


def check_trajectory(run: Path, rel: str) -> list[Finding]:
    """单题成功路径：必须能照着复现，而不是一句'搞定了'。"""
    f: list[Finding] = []
    path = run / rel
    if not path.exists():
        return f                      # E5 已经报过缺失
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return f
    if len(text) < 120:
        f.append(Finding("error", "E11", rel, "too short to reproduce (<120 chars)"))
    for marker in TRAJ_MARKERS:
        if marker not in text:
            f.append(Finding("error", "E11", rel, f"missing section: {marker}"))
    steps = [ln for ln in text.splitlines() if re.match(r"^\s*(\d+[.)]|[-*])\s+\S", ln)]
    if len(steps) < 2:
        f.append(Finding("error", "E11", rel, "need at least 2 concrete steps under ## 步骤"))
    return f


CHALLENGE_REQUIRED = ("id", "family", "difficulty", "outcome", "minutes", "flags")


def check_challenges(run: Path, rel: str, rec: dict) -> list[Finding]:
    """Per-challenge rows: the part that actually drives rule/skill changes."""
    f: list[Finding] = []
    path = run / rel
    if not path.exists():
        return f              # E5 already reported a missing file
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return f

    rows = 0
    solved = flags = 0
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        rows += 1
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue          # E8 already reported it
        if not isinstance(row, dict):
            f.append(Finding("error", "E9", rel, f"line {i}: not an object"))
            continue
        for key in CHALLENGE_REQUIRED:
            if key not in row:
                f.append(Finding("error", "E9", rel, f"line {i}: missing {key}"))
        fam = str(row.get("family", ""))
        if fam and fam not in FAMILIES:
            f.append(Finding("error", "E9", rel, f"line {i}: family {fam!r}"))
        out = str(row.get("outcome", ""))
        if out and out not in OUTCOMES:
            f.append(Finding("error", "E9", rel, f"line {i}: outcome {out!r}"))
        diff = str(row.get("difficulty", ""))
        if diff and diff not in DIFFICULTY:
            f.append(Finding("error", "E9", rel, f"line {i}: difficulty {diff!r}"))
        tri = str(row.get("triage", ""))
        if tri not in TRIAGE:
            f.append(Finding("error", "E9", rel, f"line {i}: triage {tri!r} (A/B/C/D)"))
        for key, minimum in (("minutes", 0), ("flags", 0), ("flag_total", 0), ("reopens", 0)):
            v = row.get(key, 0)
            if not isinstance(v, (int, float)) or v < minimum:
                f.append(Finding("error", "E9", rel, f"line {i}: {key} must be >= {minimum}"))
        ft = row.get("flag_total")
        if isinstance(row.get("flags"), int) and isinstance(ft, int) and ft > 0:
            if row["flags"] > ft:
                f.append(Finding("error", "E9", rel, f"line {i}: flags > flag_total"))
        elif ft is not None and not isinstance(ft, int):
            f.append(Finding("error", "E9", rel, f"line {i}: flag_total must be an int or omitted"))
        if row.get("outcome") == "solved":
            solved += 1
        if isinstance(row.get("flags"), int):
            flags += row["flags"]


    res = rec.get("result") or {}
    task = rec.get("task") or {}
    if rows and isinstance(task.get("challenges"), int) and rows > task["challenges"]:
        f.append(Finding("error", "E10", rel,
                         f"{rows} rows but task.challenges={task['challenges']}"))
    if isinstance(res.get("flags"), int) and flags > res["flags"]:
        f.append(Finding("error", "E10", rel,
                         f"rows claim {flags} flags but result.flags={res['flags']}"))
    if isinstance(res.get("solved"), int) and solved > res["solved"]:
        f.append(Finding("error", "E10", rel,
                         f"{solved} solved rows but result.solved={res['solved']}"))
    return f


def check_record(run: Path, run_rel: str, handle_dir: str) -> tuple[dict | None, list[Finding]]:
    f: list[Finding] = []
    rec_path = run / "record.json"
    if not rec_path.exists():
        return None, [Finding("error", "E1", run_rel, "record.json missing")]
    try:
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, [Finding("error", "E1", run_rel, f"record.json unreadable: {exc}")]

    # E2 schema
    if rec.get("schema") != SCHEMA_ID:
        f.append(Finding("error", "E2", run_rel, f'schema must be "{SCHEMA_ID}"'))
    for key in ("handle", "submitted_at", "agent", "task", "result", "consent"):
        if key not in rec:
            f.append(Finding("error", "E2", run_rel, f"missing key: {key}"))
    handle = str(rec.get("handle", ""))
    if not HANDLE_RE.match(handle):
        f.append(Finding("error", "E4", run_rel, f"bad handle: {handle!r} (lowercase a-z0-9-, 2-39 chars)"))
    elif handle_dir and handle != handle_dir:
        f.append(Finding("error", "E4", run_rel, f"handle {handle!r} != directory {handle_dir!r}"))
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", str(rec.get("submitted_at", ""))):
        f.append(Finding("error", "E2", run_rel, "submitted_at must be ISO-8601 (YYYY-MM-DDTHH:MM:SSZ)"))

    agent = rec.get("agent") or {}
    for key in ("name", "version", "model"):
        if not isinstance(agent.get(key), str) or not agent.get(key):
            f.append(Finding("error", "E2", run_rel, f"agent.{key} required (string)"))

    task = rec.get("task") or {}
    if task.get("kind") not in KINDS:
        f.append(Finding("error", "E2", run_rel, f"task.kind must be one of {sorted(KINDS)}"))
    for key, minimum in (("challenges", 0), ("flag_total", 0), ("hours", 0.01)):
        v = task.get(key)
        if not isinstance(v, (int, float)) or v < minimum:
            f.append(Finding("error", "E2", run_rel, f"task.{key} must be a number >= {minimum}"))

    res = rec.get("result") or {}
    for key in ("solved", "flags", "score"):
        v = res.get(key)
        if not isinstance(v, int) or v < 0:
            f.append(Finding("error", "E2", run_rel, f"result.{key} must be a non-negative integer"))
    # E3 ranges
    if isinstance(res.get("solved"), int) and isinstance(task.get("challenges"), (int, float)):
        if res["solved"] > task["challenges"]:
            f.append(Finding("error", "E3", run_rel, "result.solved > task.challenges"))
    if isinstance(res.get("flags"), int) and isinstance(task.get("flag_total"), (int, float)):
        # flag_total == 0 表示"卷面总数未知"（CTF 常见），此时不做上限检查
        if task["flag_total"] > 0 and res["flags"] > task["flag_total"]:
            f.append(Finding("error", "E3", run_rel, "result.flags > task.flag_total"))

    consent = rec.get("consent") or {}
    if consent.get("license") not in LICENSES:
        f.append(Finding("error", "E2", run_rel, f"consent.license must be one of {sorted(LICENSES)}"))
    if consent.get("redistribute") is not True:
        f.append(Finding("error", "E2", run_rel, "consent.redistribute must be true to accept the record"))

    # E5/E6 files
    files = rec.get("files") or {}
    if isinstance(files.get("challenges"), str) and files["challenges"]:
        f.extend(check_challenges(run, files["challenges"], rec))
    if isinstance(files.get("trajectory"), str) and files["trajectory"]:
        f.extend(check_trajectory(run, files["trajectory"]))
    listed: list[str] = []
    for key in ("events", "notes", "challenges", "trajectory"):
        if isinstance(files.get(key), str) and files[key]:
            listed.append(files[key])
    for item in files.get("sessions") or []:
        if isinstance(item, str):
            listed.append(item)
    for rel in listed:
        p = (run / rel)
        try:
            p.resolve().relative_to(run.resolve())
        except ValueError:
            f.append(Finding("error", "E5", run_rel, f"path escapes the run dir: {rel}"))
            continue
        if not p.exists():
            f.append(Finding("error", "E5", run_rel, f"listed file missing: {rel}"))
            continue
        if p.suffix.lower() not in ALLOWED_EXT:
            f.append(Finding("error", "E5", run_rel, f"file type not allowed: {rel}"))
        if p.stat().st_size > MAX_FILE:
            f.append(Finding("error", "E6", run_rel, f"file too large (>4MB): {rel}"))

    # E7/E8 content scan over everything in the run dir
    total = 0
    for p in sorted(run.rglob("*")):
        if not p.is_file():
            continue
        if p.name.startswith("."):      # .gitkeep / .gitignore are scaffolding, not content
            continue
        rel = p.relative_to(run).as_posix()
        total += p.stat().st_size
        if p.suffix.lower() not in TEXT_EXT:
            f.append(Finding("error", "E5", rel, "unexpected file type in submission"))
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            f.append(Finding("error", "E5", rel, "not UTF-8 text"))
            continue
        f.extend(scan_text(rel, text))
        if p.suffix == ".jsonl":
            bad = 0
            for i, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    if bad <= 3:
                        f.append(Finding("error", "E8", rel, f"line {i}: not valid JSON"))
    if total > MAX_RUN:
        f.append(Finding("error", "E6", run_rel, "run exceeds 12MB"))

    # W1 completeness
    if not (run / "notes.md").exists():
        f.append(Finding("warn", "W1", run_rel, "no notes.md (recommended)"))
    if not files.get("events") and not files.get("sessions"):
        f.append(Finding("warn", "W1", run_rel, "no events.csv and no sessions"))
    if not rec.get("metrics"):
        f.append(Finding("warn", "W1", run_rel, "no metrics block"))
    if not files.get("challenges"):
        f.append(Finding("warn", "W2", run_rel, "challenges.jsonl missing (one row per challenge)"))
    if task.get("kind") == "single" and not files.get("trajectory"):
        f.append(Finding("warn", "W4", run_rel,
                         "kind=single without trajectory.md — the whole point is the reproducible path"))
    if task.get("kind") == "ctf" and task.get("flag_total") == 0 and not files.get("challenges"):
        f.append(Finding("warn", "W3", run_rel,
                         "CTF run without flag_total: please still provide challenges.jsonl"))
    return rec, f


def iter_runs(root: Path) -> list[Path]:
    if (root / "record.json").exists():
        return [root]
    return sorted(p.parent for p in root.rglob("record.json"))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", default=["contributions"])
    ap.add_argument("--strict", action="store_true", help="warnings are failures")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    runs: list[Path] = []
    for raw in args.paths:
        root = Path(raw)
        if not root.exists():
            print(f"skip: {raw} not found", file=sys.stderr)
            continue
        if (root / "record.json").exists():
            run, handle = root, root.parent.name
            runs.append(run)
        else:
            runs += iter_runs(root)

    if not runs:
        # An empty upload area is a valid state (nobody contributed yet) — not an error.
        print("no submissions yet (expected contributions/<handle>/<run-id>/record.json)")
        return 0

    report, failed = [], False
    for run in runs:
        rel = run.as_posix()
        _, findings = check_record(run, rel, run.parent.name)
        errors = [x for x in findings if x.level == "error"]
        warns = [x for x in findings if x.level == "warn"]
        ok = not errors and not (args.strict and warns)
        failed |= not ok
        report.append({"run": rel, "ok": ok, "findings": [x.as_dict() for x in findings]})
        if not args.json:
            print(f"{'PASS' if ok else 'FAIL'}  {rel}")
            for x in findings:
                print(x)

    if args.json:
        print(json.dumps({"ok": not failed, "runs": report}, ensure_ascii=False, indent=2))
    else:
        errs = sum(1 for r in report if not r["ok"])
        print(f"\n{len(report) - errs}/{len(report)} runs valid")
        if failed:
            print("fix the ERROR lines above, then re-run this command")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
