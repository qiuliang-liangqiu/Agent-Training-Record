#!/usr/bin/env python3
"""One-shot builder: turn a finished run into a valid submission.

    python framework/scripts/collect.py --handle <you> --run-id 2026-11-20-bench \
        --from ~/run-logs --out contributions

Inputs it looks for inside --from
---------------------------------
    events.csv / *events*.csv    平台导出的事件表（time,event,challenge,code,detail）
    notes.md / notes/*.md        你的笔记（会自动脱敏后合并）
    sessions/*.jsonl             pi 会话（逐行脱敏）
    challenges.jsonl            如果你已经手写过，就用你的（只做校验）

It derives challenges.jsonl from events.csv (start→close = minutes, score = flags,
never scored = dead_end), writes record.json with totals, redacts everything on
the way in, then runs the validator and tells you exactly what to fix.

Nothing is uploaded: the output is a directory you review and commit yourself.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # repo root
validate = None                                     # filled in main()

# --------------------------------------------------------------------- redaction
FLAG = re.compile(r"(?i)\bflag\{[^}\r\n]{1,200}\}")
SECRETS = [
    re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(r"(?i)\bauthorization:\s*\S{12,}"),
    re.compile(r"(?i)\b(?:BENCHMARK_TOKEN|TSEC_TOKEN|CTFY_TOKEN|AGENT_TOKEN)\s*[=:]\s*\S{8,}"),
]
PRIVATE_IP = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)
HOME = re.compile(r"(?:/home/|[A-Za-z]:[\\/]+Users[\\/]+)[A-Za-z0-9._-]+")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def redact(text: str) -> str:
    text = FLAG.sub("flag{REDACTED}", text)
    for rx in SECRETS:
        text = rx.sub("<REDACTED>", text)
    text = PRIVATE_IP.sub("<ip>", text)
    text = HOME.sub("<user>", text)
    text = EMAIL.sub("<email>", text)
    return text


# --------------------------------------------------------------------- events
def parse_time(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def load_events(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for raw in csv.DictReader(fh):
            low = {k.strip().lower(): (v or "").strip() for k, v in raw.items()}
            rows.append({
                "time": parse_time(low.get("time", "")),
                "event": low.get("event", "").lower(),
                "challenge": low.get("challenge") or low.get("code") or "",
                "detail": low.get("detail", ""),
            })
    return [r for r in rows if r["time"] and r["challenge"]]


def derive_challenges(events: list[dict]) -> list[dict]:
    """start->close = minutes; score events = flags; never scored = dead_end."""
    opened: dict[str, dict] = {}
    rows: dict[str, dict] = {}
    for ev in events:
        code = ev["challenge"]
        row = rows.setdefault(code, {"id": code, "family": "other", "difficulty": "unknown",
                                     "outcome": "not_started", "minutes": 0.0, "flags": 0,
                                     "flag_total": 0, "reopens": 0, "triage": "",
                                     "first_signal_minutes": 0, "dead_end_reason": "",
                                     "next_move": ""})
        if ev["event"] in ("start", "started", "启动"):
            if code in opened:
                row["reopens"] += 1
            row["reopens"] += 1 if code not in opened else 0
            opened[code] = {"t": ev["time"]}
            row["outcome"] = "out_of_budget" if row["outcome"] == "not_started" else row["outcome"]
        elif ev["event"] in ("score", "scored", "得分", "submit", "submitted"):
            row["flags"] += 1
            row["flag_total"] = max(row["flag_total"], row["flags"])
            row["outcome"] = "solved"
        elif ev["event"] in ("close", "closed", "关闭"):
            start = opened.pop(code, None)
            if start:
                row["minutes"] = round((ev["time"] - start["t"]).total_seconds() / 60, 1)
            if row["flags"] and row["outcome"] != "solved":
                row["outcome"] = "partial"
            elif not row["flags"]:
                row["outcome"] = "dead_end"
    # 收尾仍开着的：算到最后一个事件
    if opened and events:
        last = max(e["time"] for e in events)
        for code, start in opened.items():
            rows[code]["minutes"] = round((last - start["t"]).total_seconds() / 60, 1)
    for row in rows.values():
        row["reopens"] = max(0, row["reopens"] - 1)
        if row["outcome"] == "not_started":
            row["outcome"] = "not_started"
    return list(rows.values())


# --------------------------------------------------------------------- collect
def gather_notes(src: Path) -> str:
    parts: list[str] = []
    main = src / "notes.md"
    if main.exists():
        parts.append(main.read_text(encoding="utf-8", errors="replace"))
    for extra in sorted(src.glob("notes/*.md")):
        parts.append(f"\n\n<!-- {extra.name} -->\n" + extra.read_text(encoding="utf-8", errors="replace"))
    return redact("\n\n".join(parts)) if parts else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--handle", required=True, help="GitHub 用户名（小写）")
    ap.add_argument("--run-id", required=True, help="例如 2026-11-20-bench")
    ap.add_argument("--from", dest="src", required=True, help="原始日志目录")
    ap.add_argument("--out", default=str(ROOT / "contributions"))
    ap.add_argument("--agent", default="pi")
    ap.add_argument("--version", default="1.5.2")
    ap.add_argument("--model", default="deepseek-flash")
    ap.add_argument("--kind", default="benchmark")
    ap.add_argument("--challenges", type=int, default=0)
    ap.add_argument("--flag-total", type=int, default=0)
    ap.add_argument("--hours", type=float, default=0)
    ap.add_argument("--solved", type=int, default=-1)
    ap.add_argument("--flags", type=int, default=-1)
    ap.add_argument("--score", type=int, default=0)
    ap.add_argument("--license", default="CC-BY-4.0")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = Path(args.src).expanduser()
    if not src.is_dir():
        print(f"not a directory: {src}", file=sys.stderr)
        return 2

    events_files = sorted(src.glob("*events*.csv")) or sorted(src.glob("*.csv"))
    events: list[dict] = []
    if events_files:
        events = load_events(events_files[0])
        print(f"events: {events_files[0].name} → {len(events)} 条")
    else:
        print("没有 events.csv：challenges.jsonl 只能空着，你需要手填")

    rows = derive_challenges(events) if events else []
    hand = src / "challenges.jsonl"
    if hand.exists():
        print("发现手写的 challenges.jsonl，用它（只做脱敏+校验）")
        rows = [json.loads(l) for l in hand.read_text(encoding="utf-8").splitlines() if l.strip()]

    solved = args.solved if args.solved >= 0 else sum(1 for r in rows if r["outcome"] == "solved")
    flags = args.flags if args.flags >= 0 else sum(r["flags"] for r in rows)
    challenges = args.challenges or len(rows)
    hours = args.hours
    if not hours and events:
        hours = round((max(e["time"] for e in events) - min(e["time"] for e in events)).total_seconds() / 3600, 2)

    run = Path(args.out) / args.handle / args.run_id
    if run.exists() and not args.dry_run:
        print(f"{run} 已存在，换个 --run-id 或先删掉", file=sys.stderr)
        return 2

    result = {"solved": solved, "flags": flags, "score": args.score}
    record = {
        "schema": "atr/2",
        "handle": args.handle,
        "submitted_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent": {"name": args.agent, "version": args.version, "model": args.model},
        "task": {"kind": args.kind, "platform": "generic",
                 "challenges": challenges, "flag_total": args.flag_total or flags, "hours": hours or 0.1},
        "result": result,
        "metrics": {"triage_minutes": 0, "reopen_rate": 0, "failure_stint_median_min": 0},
        "files": {"notes": "notes.md", "challenges": "challenges.jsonl", "sessions": []},
        "consent": {"license": args.license, "redistribute": True, "attribution": args.handle},
    }

    notes = gather_notes(src)
    print(f"challenges: {len(rows)} 行 ← {'events' if events else '手写'}")
    print(f"总计: solved={solved} flags={flags} hours={hours}")
    if args.dry_run:
        print("[dry-run] 不写文件")
        for r in rows[:5]:
            print("  ", r)
        return 0

    (run / "sessions").mkdir(parents=True, exist_ok=True)
    (run / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run / "challenges.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8")
    if notes:
        (run / "notes.md").write_text(notes, encoding="utf-8")
    if events_files:
        (run / "events.csv").write_text(redact(events_files[0].read_text(encoding="utf-8", errors="replace")),
                                        encoding="utf-8")
    sess = sorted(src.glob("sessions/**/*.jsonl")) or sorted(src.glob("*.jsonl"))
    kept = 0
    for s in sess[:5]:
        if s.name == "challenges.jsonl":
            continue
        dst = run / "sessions" / s.name
        dst.write_text(redact(s.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
        kept += 1
    if kept:
        record["files"]["sessions"] = [f"sessions/{p.name}" for p in run.joinpath("sessions").iterdir()]
        (run / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"写到 {run}（sessions: {kept}）")

    rc = __import__("subprocess").call([sys.executable,
                                        str(ROOT / "framework" / "scripts" / "validate.py"),
                                        str(run)])
    if rc != 0:
        print("\n校验没过：按上面的 ERROR 行改，然后重跑本命令（或手改那个目录）")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
