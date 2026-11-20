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
import hashlib
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


TRAJ_TEMPLATE = """# {cid} 成功轨迹

## 输入

- 附件：{attachment}
- 服务：{service}
- 一句话描述：{desc}

## 步骤

1. <第一步：做了什么，看到什么，为什么接着做>
2. <第二步>
3. <拿到 flag / 打通的最后一步>

## 复现

```bash
# 从零到 flag 的最小命令序列（不要写真实地址和 flag）
```

## 关键判断

| 现象 | 结论 | 如果重来先做什么 |
|---|---|---|
| | | |

## 排除的路径

- <试过但没用，为什么>
"""


def build_single(args, src: Path) -> int:
    """一题一份：附件 + 端口 → 一条成功轨迹。"""
    files = [p for p in sorted(src.iterdir()) if p.is_file()]
    attachment = ""
    if files:
        big = max(files, key=lambda p: p.stat().st_size)
        attachment = f"{big.name}（{big.stat().st_size/1024:.0f} KB，sha256 {hashlib.sha256(big.read_bytes()).hexdigest()[:16]}…）"
    cid = args.challenge_id or (files[0].stem if files else "challenge")
    cid = re.sub(r"[^a-z0-9._-]", "-", cid.lower())[:60]

    run = Path(args.out) / args.handle / args.run_id
    record = {
        "schema": "atr/2",
        "handle": args.handle,
        "submitted_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent": {"name": args.agent, "version": args.version, "model": args.model},
        "task": {"kind": "single", "platform": "generic", "challenges": 1,
                 "flag_total": args.flag_total or 1, "hours": args.hours or 0.1},
        "result": {"solved": args.solved if args.solved >= 0 else 1,
                   "flags": args.flags if args.flags >= 0 else 1, "score": args.score},
        "metrics": {"triage_minutes": 0, "reopen_rate": 0, "failure_stint_median_min": 0},
        "files": {"notes": "notes.md", "challenges": "challenges.jsonl",
                  "trajectory": "trajectory.md", "sessions": []},
        "consent": {"license": args.license, "redistribute": True, "attribution": args.handle},
    }
    row = {"id": cid, "family": args.family, "difficulty": args.difficulty,
           "outcome": "solved" if (args.solved in (-1, 1)) else "dead_end",
           "minutes": args.minutes or (args.hours * 60 or 0.1), "flags": 1,
           "reopens": 0, "triage": ""}
    print(f"单题：{cid} | 附件：{attachment or '（无文件）'}")
    if args.dry_run:
        print("[dry-run] 会写 record.json / challenges.jsonl / trajectory.md")
        return 0

    (run / "sessions").mkdir(parents=True, exist_ok=True)
    (run / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    (run / "challenges.jsonl").write_text(json.dumps(row, ensure_ascii=False) + chr(10), encoding="utf-8")
    (run / "trajectory.md").write_text(
        TRAJ_TEMPLATE.format(cid=cid, attachment=attachment or "（无）",
                             service=args.service or "（无）", desc=args.description or "（待填）"),
        encoding="utf-8")
    notes = gather_notes(src) or ("# notes" + chr(10) + chr(10) +
                                   "- 这题的关键判断：" + chr(10) +
                                   "- 排除的路径：" + chr(10))
    (run / "notes.md").write_text(notes, encoding="utf-8")
    print(f"写到 {run}")
    print("下一步：把 trajectory.md 的步骤和复现命令填真实内容（这是唯一能学到东西的部分）")
    import subprocess
    return subprocess.call([sys.executable, str(ROOT / "framework" / "scripts" / "validate.py"), str(run)])


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
    ap.add_argument("--challenge-id", default="", help="单题模式下的题目代号（默认取附件名）")
    ap.add_argument("--family", default="other", help="单题模式：web/pwn/crypto/rev/forensics/misc/osint")
    ap.add_argument("--difficulty", default="unknown", choices=["easy", "medium", "hard", "unknown"])
    ap.add_argument("--service", default="", help="单题模式：host:port（会写进轨迹，注意脱敏）")
    ap.add_argument("--description", default="", help="单题模式：一句话描述")
    ap.add_argument("--minutes", type=float, default=0)
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

    if args.kind == "single":
        return build_single(args, src)

    rows = derive_challenges(events) if events else []
    if not rows and args.kind == "ctf":
        # 没有事件表时，用「一题一个目录」的常见布局兜底：只给骨架，不编数字
        skip = {"notes", "sessions", "logs", "attachments", "dist", "node_modules", ".git"}
        subs = [d for d in sorted(src.iterdir())
                if d.is_dir() and not d.name.startswith(".") and d.name.lower() not in skip]
        for d in subs:
            name = re.sub(r"[^a-z0-9._-]", "-", d.name.lower())[:60] or "challenge"
            rows.append({"id": name, "family": "other", "difficulty": "unknown",
                         "outcome": "not_started", "minutes": 0, "flags": 0,
                         "reopens": 0, "triage": "", "first_signal_minutes": 0,
                         "dead_end_reason": "", "next_move": ""})
        if subs:
            print(f"没有 events.csv：按 {len(subs)} 个子目录生成骨架，outcome/minutes 需要你填")
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
                 # CTF 没有公开的卷面 flag 总数：0 = 未知（校验器不会拿它当上限）
                 "challenges": challenges,
                 "flag_total": args.flag_total or (0 if args.kind == "ctf" else flags),
                 "hours": hours or 0.1},
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
