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

**`<...>` 是占位符，要换成你自己的值**：`<you>` = 你的 GitHub 用户名（小写，如 `octocat`），
`<model>` = 模型 id（如 `deepseek-flash`），`<run-id>` = 自己编的代号。原样照抄 `<you>` 会被拒。

```bash
# <you>=你的 GitHub 用户名   <model>=模型 id   <run-id>=自己编的代号

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

填满的等价例子（可直接复制，把 `octocat` 换成你自己）：

```bash
python framework/scripts/new_submission.py --handle octocat --run-id 2026-11-21-bench \
  --agent pi --version 1.5.2 --model deepseek-flash \
  --kind benchmark --challenges 50 --flag-total 100 --hours 7.9 \
  --solved 37 --flags 47 --score 13800
```

通过的提交开 PR；CI 会跑同一个校验器。**隐私没脱干净会直接红。**

## 怎么上传（PR 流程）

你不是这个仓库的协作者，所以**不能直接 push 到 main**，走 fork + PR。
两种方式，任选其一。

### 方式 A：本地 git（推荐）

```bash
# 1. 在 GitHub 上点右上角 Fork（得到 你的用户名/Agent-Training-Record）
git clone https://github.com/<you>/Agent-Training-Record.git
cd Agent-Training-Record

# 2. 生成你的提交目录（见上面「三条命令」/「只给了一个附件」）
python framework/scripts/collect.py --handle <you> --run-id 2026-11-21-bench \
  --from <日志目录> --challenges 50 --flag-total 100 --hours 7.9 --score 13800

# 3. 本地自检，必须通过
python framework/scripts/validate.py contributions/<you>/2026-11-21-bench

# 4. 只提交你自己那个目录
git checkout -b submit/<you>-2026-11-21
git add contributions/<you>/2026-11-21-bench
git commit -m "submission: <you> 2026-11-21-bench"
git push -u origin submit/<you>-2026-11-21
```

push 完终端会打印一行 `Create a pull request` 的链接，打开它 → 填标题
`submission: <you> 2026-11-21-bench` → 创建。

### 方式 B：只在网页上做（不想装 git）

1. Fork（右上角）
2. 在你的 fork 里点 `contributions/` → **Add file → Upload files**
3. 把整个 `<run-id>` 目录拖进去，**路径必须是** `contributions/<you>/<run-id>/…`
4. 页面下方选 “Create a new branch for this commit” → 提一个分支名（如 `submit/2026-11-21`）
5. 提交后会提示 **Compare & pull request** → 创建 PR

> 网页上传时，`record.json` / `challenges.jsonl` / `notes.md` / `events.csv` 要放在
> `<run-id>/` 里面，不是散在 `contributions/` 下。放错位置 CI 会报 E1（找不到 record.json）。

### PR 里会发生什么

| 阶段 | 内容 |
|---|---|
| 自动 CI | 跑 `validate.py contributions`（schema + 隐私扫描 + 行内一致性）+ 单测 |
| 红了 | 点开 Details 看规则号（E1–E11 / W1–W4），在同一个分支上继续 commit 即可自动重跑 |
| 绿了 | 维护者 review：数字是否自洽、脱敏是否彻底 |
| 合并 | 记录进入仓库，用于对比不同模型/配置并改进规则 |

修改 PR 不需要重开：

```bash
git add contributions/<you>/<run-id>
git commit --amend --no-edit      # 或者再加一个 commit
git push                          # 分支已跟踪，直接推
```

### 上传前最后三件事

1. `python framework/scripts/validate.py contributions/<you>/<run-id>` 本地已经过了
2. `git status` 里**只有** `contributions/<you>/…`，没有别的文件（别把 `auth.json` 带进去）
3. 没上传：附件二进制、真实 flag、token、平台地址、真名/邮箱

被拦了不知道怎么办：在 PR 里贴校验器输出，或开 issue 只写规则号（**不要贴敏感内容**）。

## 硬性拒收

真实 flag、token/`Authorization`、私网 IP（`10.x` / `192.168.x` / `172.16-31.x`）、
绝对家目录、真实邮箱、二进制文件、单文件 >4MB、`sessions/*.jsonl` 有坏行。

完整清单与规则编号（E1–E11 / W1–W4）见 [`framework/CONTRIBUTING.md`](framework/CONTRIBUTING.md)。

## 许可

- 工程文件（`framework/` 下的脚本、schema、CI）：MIT，见 [`framework/LICENSE`](framework/LICENSE)。
- `contributions/` 里的每份记录：著作权归提交者，按 `record.json` 的
  `consent.license` 授权，见 [`framework/RECORDS-LICENSE.md`](framework/RECORDS-LICENSE.md)。
- 只接受 `consent.redistribute: true` 的提交。
