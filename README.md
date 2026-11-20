# Agent-Training-Record

**给 Agent 训练记录用的公共仓库。** 你可以把一次跑分 / 一场 CTF / 一个 lab 的**脱敏复盘和指标**
提 PR 上来；这些记录用来比较不同 Agent 配置的表现、找出共性失分点，并反向改进规则与工具。

> 这里只要**可复现的数字 + 脱敏后的笔记**，不要原始 flag、不要平台凭据、不要靶场地址。

## 提交什么

一次提交 = 一个目录：

```
submissions/
└── <你的 GitHub handle>/
    └── <run-id>/                 # 例如 2026-11-20-bench
        ├── record.json           # 必填：元数据与结果（schema 见下）
        ├── notes.md              # 建议：复盘（现象→根因→规则）
        ├── events.csv            # 可选：平台导出的事件表
        └── sessions/*.jsonl      # 可选：脱敏后的 agent 会话
```

`record.json` 的字段与校验规则在 [`schema/record.schema.json`](schema/record.schema.json)，
一句话版本：

```json
{
  "schema": "atr/1",
  "handle": "octocat",
  "submitted_at": "2026-11-20T09:00:00Z",
  "agent":  { "name": "pi", "version": "1.5.2", "model": "deepseek-flash" },
  "task":   { "kind": "benchmark", "challenges": 50, "flag_total": 100, "hours": 7.9 },
  "result": { "solved": 37, "flags": 47, "score": 13800 },
  "metrics": { "triage_minutes": 15, "reopen_rate": 0.61 },
  "files":   { "events": "events.csv", "notes": "notes.md", "sessions": [] },
  "consent": { "license": "CC-BY-4.0", "redistribute": true }
}
```

`task.kind`：`benchmark` | `ctf` | `lab` | `other`。
`metrics` 是自由键值（数字或字符串），常用：`triage_minutes`、`reopen_rate`、
`failure_stint_median_min`、`last_mile_missed`。

## 三步提交

```bash
git clone https://github.com/<you>/Agent-Training-Record.git
cd Agent-Training-Record
git checkout -b submit/<handle>-<run-id>

python scripts/new_submission.py --handle <you> --run-id <run-id> \
  --agent pi --version 1.5.2 --model <model> \
  --kind benchmark --challenges 50 --flag-total 100 --hours 7.9 \
  --solved 37 --flags 47 --score 13800

# 把 events.csv / notes.md / 脱敏会话放进该目录，然后：
python scripts/validate.py submissions/<you>/<run-id>
git add submissions/<you> && git commit -m "submission: <handle> <run-id>"
git push -u origin submit/<handle>-<run-id>
```

然后开 PR。CI 会自动跑同一个校验器；**红的就是没脱敏干净**，按提示改完再推。

没有 Python 环境也能提：直接照 `submissions/example/demo-run-001/` 复制目录、手改
`record.json`，PR 里 CI 会告诉你是哪一条不过。

## 隐私闸门（会拒收的情况）

| 拒绝条件 | 例子 |
|---|---|
| 真实 flag | `flag{...}` 里不是 `REDACTED` |
| 凭据 | `ghp_…`、`sk-…`、`Authorization: …`、`TSEC_TOKEN=…` |
| 私网地址 | `10.x`、`192.168.x`、`172.16-31.x`（`<ip>` 占位可以） |
| 绝对路径 | `/home/<name>/…`、`C:\Users\<name>\…` |
| 邮箱 | 任何真实邮箱（`noreply@`、`@example.com` 除外） |
| 二进制/超大 | 只收 `.md .txt .json .jsonl .csv .tsv`，单文件 ≤4MB、单次 ≤12MB |

平台名、运行 ID、题目编号建议一起换掉：`<platform>`、`run-events.csv`、`demo-01`。
细节见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 这些记录被用来干什么

- 横向比较：同一任务下不同模型/思考档/并发配置的分数与用时；
- 横向找病：失败 stint 中位、重开率、结尾阶段开箱数这类**行为指标**；
- 反向改进：把共性失分点写成规则（比如"只按 `is_completed`/`flag_total` 关箱"），
  再回到下一轮验证。

**不会被用来**：攻击任何平台、复现具体题目的答案、或公开任何人的身份信息。

## 许可

- `scripts/`、`schema/`、CI 配置：MIT（见 [`LICENSE`](LICENSE)）。
- `submissions/` 下的记录：由提交者保留著作权，按提交时 `consent.license`
  授权（`CC-BY-4.0` / `CC0-1.0` / `MIT`），见 [`RECORDS-LICENSE.md`](RECORDS-LICENSE.md)。
- 只接受 `consent.redistribute: true` 的记录 —— 提交即表示同意上述授权。

## 本地校验

```bash
python scripts/validate.py submissions              # 全量
python scripts/validate.py submissions/<you>/<run>  # 单条
python scripts/validate.py submissions --strict     # 警告也算失败
python -m unittest discover -s tests -v             # 校验器自身的测试
```

只用标准库，不需要 `pip install`。
