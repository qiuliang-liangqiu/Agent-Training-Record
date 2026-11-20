# 记录内容的许可

`scripts/`、`schema/`、`.github/` 与本文件之外的工程文件用 MIT（见 `LICENSE`）。

`submissions/` 下的每一份记录由**提交者**保留著作权，并按 `record.json` 里的
`consent.license` 授权给本仓库及其他使用者：

- `CC-BY-4.0`：允许复制、再分发与演绎，需署名（默认选项）
- `CC0-1.0`：放弃权利，进入公有领域
- `MIT`：与代码同款宽松许可

协议全文：
- CC BY 4.0 — https://creativecommons.org/licenses/by/4.0/legalcode
- CC0 1.0 — https://creativecommons.org/publicdomain/zero/1.0/legalcode
- MIT — 见本仓库 `LICENSE`

## 提交即表示

1. 你有权公开这份记录（不是别人的私有数据，也没有违反所在平台的服务条款）；
2. 已按 `CONTRIBUTING.md` 的脱敏清单处理过；
3. 同意 `consent.license` 声明的授权方式，并允许维护者在仓库内再分发。

`consent.redistribute` 必须为 `true`，否则校验器会拒绝该提交。

## 引用与署名

论文/博客里引用时用：`Agent-Training-Record, submissions/<handle>/<run-id>`。
`consent.attribution` 非空时，请按其中写的名字署名。

## 移除请求

如果某份记录误含敏感信息，发 issue（不要公开贴敏感内容）或直接 PR 删除该目录；
维护者有权在核实后立即移除，并保留在 git 历史中删除前的内容 —— 这也是为什么
**提交前必须脱敏**，历史不会因为一个 revert 就消失。
