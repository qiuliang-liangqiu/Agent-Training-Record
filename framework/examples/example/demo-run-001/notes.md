# example · demo-run-001

This is a **format demo**, not a real run. Copy this directory and replace the numbers.

- agent: pi 1.5.2 (deepseek-flash, thinking high)
- task: 3 challenges / 6 flags, 1.5h
- result: 2 solved / 3 flags / 900

## 关键结论

1. triage 用 10 分钟过完 3 题，节省了开局迷路的时间。
2. 第二题卡在凭据来源，两轮 0 新增后关箱。
3. 第三题拿到 flag 后因为没看 `flag_total` 提前关了，白丢 1 面。

## 失分点

| 现象 | 根因 | 下次怎么避免 |
|---|---|---|
| 提前关箱 | 只看 `flags>=1` | 只按 `is_completed` / `flag_total` |
| 空挂 6 分钟 | 没写笔记就继续试 | 14 分钟闸门 + 三行笔记 |
