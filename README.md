# Agent-Training-Record

给 Agent 训练记录用的公共仓库：**别人提 PR 上传脱敏后的跑分/比赛记录，维护者审核合并。**

## 目录只有两块

| 目录 | 谁维护 | 放什么 |
|---|---|---|
| **`framework/`** | 维护者 | 提交规范、JSON Schema、校验器、测试、许可 —— 也就是"规则"本身 |
| **`contributions/`** | 贡献者 | **空目录，只有 `.gitkeep`**；每人每次运行一个子目录：`contributions/<handle>/<run-id>/` |
| `.github/` | 维护者 | CI 配置。**只能放仓库根目录**，GitHub 不会读取子目录里的 workflow |

```
framework/
├── README.md                  # 提交规范与数据用途（主文档）
├── CONTRIBUTING.md            # 脱敏清单、规则编号、PR 要求
├── schema/record.schema.json  # atr/1 清单
├── scripts/validate.py        # 校验器（schema + 隐私闸门，纯标准库）
├── scripts/new_submission.py  # 生成提交骨架
├── tests/test_validate.py     # 12 个用例，含"该拒的必须拒"
├── examples/example/demo-run-001/   # 格式示例（可跑通，占位数据）
├── LICENSE                    # 代码：MIT
└── RECORDS-LICENSE.md         # 记录：CC-BY-4.0 / CC0 / MIT

contributions/
└── .gitkeep                   # 干净的空目录，等着放你的记录
```

## 三条命令

```bash
# 1. 生成自己的提交目录
python framework/scripts/new_submission.py --handle <you> --run-id 2026-11-20-bench \
  --agent pi --version 1.5.2 --model <model> \
  --kind benchmark --challenges 50 --flag-total 100 --hours 7.9 \
  --solved 37 --flags 47 --score 13800

# 2. 把 events.csv / notes.md / 脱敏会话放进该目录后自检
python framework/scripts/validate.py contributions/<you>/2026-11-20-bench

# 3. 全量复核（CI 跑的就是这条）
python framework/scripts/validate.py contributions
```

通过的提交开 PR；CI 会跑同一个校验器。**隐私没脱干净会直接红。**

## 硬性拒收

真实 flag、token/`Authorization`、私网 IP（`10.x` / `192.168.x` / `172.16-31.x`）、
绝对家目录、真实邮箱、二进制文件、单文件 >4MB、`sessions/*.jsonl` 有坏行。

完整清单与规则编号（E1–E8 / W1）见 [`framework/CONTRIBUTING.md`](framework/CONTRIBUTING.md)。

## 许可

- 工程文件（`framework/` 下的脚本、schema、CI）：MIT，见 [`framework/LICENSE`](framework/LICENSE)。
- `contributions/` 里的每份记录：著作权归提交者，按 `record.json` 的
  `consent.license` 授权，见 [`framework/RECORDS-LICENSE.md`](framework/RECORDS-LICENSE.md)。
- 只接受 `consent.redistribute: true` 的提交。
