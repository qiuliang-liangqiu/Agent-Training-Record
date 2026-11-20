# 提交规范

## 0. 一条硬规则

**只提交能公开的内容。** 这个仓库是 public，历史记录也会保留你的提交。
不确定的东西就别放进来——少写细节不影响记录的价值，一条真实 flag 或一个 token 会立刻被拒。

## 1. 目录与命名

```
submissions/<github-handle>/<run-id>/
```

- `<github-handle>`：全部小写，只允许 `a-z 0-9 -`，必须和 PR 作者的 GitHub 用户名一致
  （CI 会比对目录名与 `record.json` 的 `handle`）。
- `<run-id>`：小写，只允许 `a-z 0-9 . _ -`，建议 `YYYY-MM-DD-<场景>`，例如
  `2026-11-20-bench`、`2026-11-18-ctf`。同一天多次提交就加后缀 `-2`、`-3`。

一个人的每次提交一个目录，**不要**把多次运行塞进同一个目录。

## 2. 必填与可选项

| 文件 | 必填 | 说明 |
|---|---|---|
| `record.json` | ✅ | 元数据与结果，见 `schema/record.schema.json` |
| `notes.md` | 建议 | 复盘：现象 → 根因 → 写死的规则；**没有会出 warning** |
| `events.csv` | 可选 | 平台导出的事件表（启动/关闭/得分） |
| `sessions/*.jsonl` | 可选 | agent 会话，**必须脱敏**；一行一个 JSON |

`record.json` 的 `files` 里列了什么，目录里就必须有什么；列了不存在 = CI 失败。

## 3. 数字怎么填

- `task.challenges` / `flag_total`：卷面总量（不是你做出来的）。
- `result.solved` / `flags` / `score`：你实际拿到的。
- `task.hours`：从第一次 `start` 到最后一次 `close` 的墙钟时间，保留一位小数。
- 校验器会检查 `solved <= challenges`、`flags <= flag_total`。

不知道的字段宁可不填（`metrics` 可以整个省略），**不要填 0 假装有数据**。

## 4. 脱敏清单（提交前逐条过）

- [ ] `flag{...}` → `flag{REDACTED}`；真的 flag 一个都不能留
- [ ] 平台域名 / 实例地址 → `<platform>`、`<host:port>`
- [ ] 内网 IP → `<ip>`；保留 `10.0.0.0/8` 这种网段说明是可以的
- [ ] 运行 ID / 题目编号 → `run-events.csv`、`demo-01`
- [ ] token / cookie / `Authorization` 头 → 删掉，不要"只留前四位"
- [ ] 绝对路径里的用户名 → `~` 或 `<user>`
- [ ] 邮箱、真实姓名、设备 ID → 删掉

会话文件（`sessions/*.jsonl`）最常见的问题：`toolResult` 里夹着 flag 和完整响应头。
建议先用 `python scripts/validate.py <dir>` 扫一遍，红灯就说明还有残留。

## 5. 本地校验

```bash
python scripts/validate.py submissions/<handle>/<run-id>
```

输出里的规则编号：

| 规则 | 含义 |
|---|---|
| E1 | `record.json` 缺失或不是合法 JSON |
| E2 | 字段缺失 / 类型不对 / 枚举值不对 |
| E3 | 数字越界（solved > challenges 等） |
| E4 | 路径或 handle 不匹配 |
| E5 | 列出的文件不存在 / 类型不允许 / 路径越界 |
| E6 | 体积超限（单文件 4MB、单次 12MB） |
| E7 | 隐私扫描命中（flag / token / 私网 IP / 绝对路径 / 邮箱） |
| E8 | `sessions/*.jsonl` 不是逐行合法 JSON |
| W1 | 建议项缺失（notes / events / sessions / metrics） |

`--strict` 会让 W1 也失败；CI 默认只对 ERROR 拦截。

## 6. PR 要求

- 一个 PR 只加一次提交（或同一人的同一批），不要顺手改别人的目录。
- 标题：`submission: <handle> <run-id>`。
- 描述里贴一行 `python scripts/validate.py submissions/<handle>/<run-id>` 的输出。
- CI 通过后再请维护者合并；需要修改就在同一个分支追加 commit。

## 7. 会被直接关掉的 PR

- 含真实 flag / token / 平台地址，且作者拒绝修改；
- 伪造数字（例如 `solved` 超过卷面、分数与题量明显不符且无说明）；
- 提交别人的记录但拿不出授权；
- 把仓库当网盘（大文件、二进制、与训练记录无关的内容）。

## 8. 想加字段？

先改 `schema/record.schema.json` + `scripts/validate.py` + 一个测试用例，再发 PR 说明用途。
向后兼容优先：新增字段必须是可选。
