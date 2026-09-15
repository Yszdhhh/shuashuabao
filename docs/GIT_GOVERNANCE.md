# ShuaBao Git 治理与本地 Guardrails

状态日期：2026-09-15

本文件只描述 Git / 仓库治理，不改变游戏逻辑、发布逻辑或真机验收标准。业务改动纪律仍以 `AGENTS.md` 与 `docs/CONTRIBUTING_GATE.md` 为准。

## 1. 当前约束

`main` 的唯一正常前进方式是 GitHub Pull Request 的 merge commit。本地 `main` 只用于跟随 `origin/main`，不得直接开发、提交或推送。

截至 2026-09-15，GitHub 对本私有仓库返回：当前账户计划不提供该仓库的 Branch Protection Rules。因此现阶段无法把 required checks / 禁止直推等约束做成 GitHub 服务端硬门禁。本仓库使用 tracked hooks 作为补偿控制，但它们不能等价替代服务器端保护。

一旦账户计划支持私有仓库 Branch Protection，应优先启用服务端保护，并保留本地 hooks 作为第二道防线。

## 2. 每个 clone / 工作根只需执行一次

在仓库根目录运行：

```powershell
python scripts/setup_git_guardrails.py
python scripts/setup_git_guardrails.py --check
```

安装脚本只修改当前仓库的 local Git config，不修改 global Git config。它会设置：

- `core.hooksPath=.githooks`
- `pull.ff=only`
- `fetch.prune=true`
- `push.default=simple`
- 在支持 POSIX execute bit 的系统上确保 tracked hooks 可执行

`--check` 为只读自检；配置或 hook 缺失时返回非零退出码。

## 3. 当前三道本地 Git 门禁

### `pre-commit`

禁止直接在本地 `main` 创建 commit。开发必须从 `origin/main` 创建 topic branch / worktree。

### `pre-push`

禁止任何直接更新远端 `refs/heads/main` 的 push，包括普通 push、force push 和删除 main。topic branch 可以正常 push。

### `pre-merge-commit`

禁止在本地 `main` 生成 merge commit。正常的 `git merge --ff-only origin/main` 是 fast-forward，不生成 merge commit，因此仍然允许。

## 4. 推荐日常流程

```powershell
git fetch origin
git switch -c <topic> origin/main
# 修改、验证、commit
git push -u origin HEAD
# GitHub 上开 PR，使用 merge commit 合入 main
```

合并后本地 `main` 只做：

```powershell
git fetch origin
git switch main
git merge --ff-only origin/main
python scripts/setup_git_guardrails.py --check
```

如果本地 `main` 已经存在未推送提交，不要直接 reset 或删除。先按 `AGENTS.md` 的恢复纪律把提交救到 topic branch，再对齐 `origin/main`。

## 5. 明确限制

本地 hooks 仍然可以被 `--no-verify`、直接 GitHub/API 写入或人为修改本地 Git config 绕过，因此它们是事故防线，不是权限边界。任何绕过都应视为流程事故并在交接中记录。

当前 Actions 若在 runner / 账户层未获得执行机会，不能把红色 run 当成代码测试失败；同样，也不能因为本地测试通过就声称 cloud-certified。云端执行环境恢复后仍需补跑仓库定义的 CI / strict release / frozen OCR 门禁。
