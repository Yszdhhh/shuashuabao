# OMP「执行不落地」问题诊断报告（写给我自己 + codex 交接）

## 现象
用户在 OMP 里下达的修改指令，agent 执行后"看起来完成"，但桌面看板/正式入口用不到，下次会话又重新做一遍。

## 根因（三重，全部实证）
1. **多 worktree 分裂**：同一仓库有 7 个 worktree（GameScript-Local / live-test-boss-05ed271 / shuashuabao-entitlement-test / subscription-lobby-pilot / shubao-build / 两个 codex detached）。OMP 会话目录显示曾分别在 `--C--tmp--`、`-Desktop-...GameScript-Local`、`GameScript-Core02-Core03-Integration-20260816` 启动——**改的是 A 副本，桌面快捷方式/打包脚本用的是 B 副本**。桌面 `刷刷宝.lnk` → `Desktop/ShuaBao/ShuaBao.exe`（build_identity source_sha=05ed271 旧提交）；`刷刷宝 Live 实机测试.lnk` → live-test-boss worktree。改完代码不跑 `build_release.ps1`，桌面 EXE 永远落后。
2. **无强制物理验收**：修改即宣称完成，没有 (a) 跑构建 (b) 校验 build_identity.json source_sha==HEAD (c) 启动真实进程截图。已确立三位一体铁律（AGENTS.md），但此前没有自动化闸。
3. **审查/测试在错误 cwd 跑**：pytest 在 worktree 里绿了≠主树绿。本次合并前主树还有 22 个未提交文件（subscription WIP），先 commit 再 merge 才消除漂移。

## 对策（已落地）
- 仓库唯一真相源 = `G:\刷刷宝\GameScript-Local`（trial-merge）。
- 交付闸：release_gate 4/4 + 全量 pytest + `build_release.ps1` 重建 + build_identity.source_sha 必须 == git HEAD + 桌面快捷方式指向校验。
- 每次交付附三项硬证据：改动文件清单 / 校验命令输出 / 运行态证据（PID/截图/日志）。

## 遗留风险
- codex detached worktree（C 盘两个）仍会被 codex CLI 复活，交接词里必须写明"只在 G:\刷刷宝\GameScript-Local 工作"。
- 用户侧习惯性从旧快捷方式启动，需在交接说明中强调桌面唯一入口 `刷刷宝.lnk`。
