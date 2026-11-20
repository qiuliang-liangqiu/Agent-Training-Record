#!/usr/bin/env python3
"""Scaffold a submission directory: submissions/<handle>/<run-id>/.

    python scripts/new_submission.py --handle octocat --run-id 2026-11-20-bench \
        --agent pi --version 1.5.2 --model deepseek-flash \
        --kind benchmark --challenges 50 --flag-total 100 --hours 7.9 \
        --solved 37 --flags 47 --score 13800

    python scripts/new_submission.py --handle octocat --run-id demo --interactive

The generated record.json is a *template*: fill in real numbers, drop your
events.csv / notes.md / sanitized sessions into the same folder, then run
    python scripts/validate.py submissions/<handle>/<run-id>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}$")
RUN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")

TEMPLATE = """# {handle} · {run_id}

- agent: {agent} {version} ({model})
- task: {kind}, {challenges} challenges / {flag_total} flags, {hours}h
- result: {solved} solved / {flags} flags / {score} score

## 关键结论（3-5 条）

1.
2.
3.

## 失分点

| 现象 | 根因 | 下次怎么避免 |
|---|---|---|
|  |  |  |

## 脱敏自检

- [ ] 没有真实 flag（只保留 `flag{{REDACTED}}`）
- [ ] 没有平台域名 / 运行 ID / 内网 IP
- [ ] 没有 token / cookie / Authorization
- [ ] `python scripts/validate.py <this dir>` 通过
"""


def ask(prompt: str, default: str = "") -> str:
    try:
        raw = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return raw or default


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="submissions")
    ap.add_argument("--handle", default="")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--agent", default="pi")
    ap.add_argument("--version", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--thinking", default="")
    ap.add_argument("--kind", default="benchmark")
    ap.add_argument("--challenges", type=int, default=0)
    ap.add_argument("--flag-total", type=int, default=0)
    ap.add_argument("--hours", type=float, default=0.0)
    ap.add_argument("--solved", type=int, default=0)
    ap.add_argument("--flags", type=int, default=0)
    ap.add_argument("--score", type=int, default=0)
    ap.add_argument("--license", default="CC-BY-4.0")
    ap.add_argument("--interactive", action="store_true")
    args = ap.parse_args()

    if args.interactive:
        args.handle = ask("GitHub handle", args.handle)
        args.run_id = ask("run id (e.g. 2026-11-20-bench)", args.run_id)
        args.agent = ask("agent name", args.agent)
        args.version = ask("agent version", args.version)
        args.model = ask("model", args.model)
        args.thinking = ask("thinking level", args.thinking)
        args.kind = ask("task kind (benchmark/ctf/lab/other)", args.kind)
        args.challenges = int(ask("challenges", str(args.challenges)) or 0)
        args.flag_total = int(ask("flag total", str(args.flag_total)) or 0)
        args.hours = float(ask("hours", str(args.hours)) or 0)
        args.solved = int(ask("solved", str(args.solved)) or 0)
        args.flags = int(ask("flags captured", str(args.flags)) or 0)
        args.score = int(ask("score", str(args.score)) or 0)

    args.handle = args.handle.lower()
    if not HANDLE_RE.match(args.handle):
        print("handle must be lowercase a-z0-9- (2-39 chars)", file=sys.stderr)
        return 2
    if not RUN_RE.match(args.run_id):
        print("run-id must be lowercase a-z0-9._- (3-64 chars)", file=sys.stderr)
        return 2
    for key in ("version", "model"):
        if not getattr(args, key):
            print(f"--{key} is required", file=sys.stderr)
            return 2
    if not args.hours or args.hours <= 0:
        print("--hours must be > 0 (wall-clock hours of the run); "
              "run with --interactive if you want to be prompted", file=sys.stderr)
        return 2

    run = Path(args.out) / args.handle / args.run_id
    if run.exists():
        print(f"{run} already exists", file=sys.stderr)
        return 2
    (run / "sessions").mkdir(parents=True)   # empty dir: git will not track it until a file lands

    record = {
        "schema": "atr/1",
        "handle": args.handle,
        "submitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent": {"name": args.agent, "version": args.version, "model": args.model},
        "task": {
            "kind": args.kind,
            "platform": "generic",
            "challenges": args.challenges,
            "flag_total": args.flag_total,
            "hours": args.hours,
        },
        "result": {"solved": args.solved, "flags": args.flags, "score": args.score},
        "metrics": {"triage_minutes": 0, "reopen_rate": 0, "failure_stint_median_min": 0},
        "files": {"notes": "notes.md", "sessions": []},
        "consent": {"license": args.license, "redistribute": True, "attribution": args.handle},
    }
    if args.thinking:
        record["agent"]["thinking"] = args.thinking

    (run / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run / "notes.md").write_text(TEMPLATE.format(**{**vars(args), "run_id": args.run_id}), encoding="utf-8")

    print(f"created {run}")
    print("next:")
    print(f"  1) edit {run/'record.json'} (real numbers, files.sessions list)")
    print(f"  2) drop sanitized files into {run}")
    print(f"  3) python scripts/validate.py {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
