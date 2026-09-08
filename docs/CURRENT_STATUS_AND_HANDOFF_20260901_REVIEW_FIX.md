# 当前状态与交接（2026-09-01 云端审查修复）

## 交付范围

本次修复针对云端审查报告中的 P0/P1/P2 问题，唯一工作根目录是 `G:/刷刷宝/GameScript-Local`，目标分支为 `trial-merge`，远端为 `origin/trial-merge`（GitHub：`https://github.com/Yszdhhh/shuashuabao.git`）。正式入口仍是桌面 `刷刷宝.lnk` → `Desktop/ShuaBao/ShuaBao.exe`；构建脚本会在部署后回验该路径、整包清单和快捷方式。

## 已落地修复

- **运行时安全**：Runtime watchdog 只有连续两帧不同帧号的稳定局内 HUD 才允许一次受控恢复；UNKNOWN、黑帧、战后过渡和确认中一律零输入，不再无条件按 Esc 或推进 L1 cycle。
- **大秘境入口**：确认框后改为连续两帧无战后分类 + 局内 HUD，两个确认 tick 均不执行局内动作；中断即清零，超时进入 ERROR。
- **战后 Boss**：最后可见关卡兜底只允许已分类的 `ARCHIVE_PANEL` / `HEIRLOOM_DIALOG`，非战后页面目标 miss 保持零输入。
- **Runner/看板**：预检拆出订阅、运行目录、OCR、UIPI、目标窗口和构建身份检查；启动失败保留 `FAILED` 与终止原因；运行态 DTO/HUD 读取启动快照，不受运行中改表单影响。
- **订阅与安全**：部署 sidecar 固定非敏感 endpoint/mode；只允许 HTTPS 或 loopback HTTP；快照不触发网络，授权结果短期缓存，卡密仍只走 DPAPI/env，不进入日志或构建身份。
- **Web/原生桥**：bridge schema 统一为 2，`get_bridge_info` 与 `activate_subscription` 为必需接口；生产桥接失败显式报错，不回退 mock。开发入口 `run_desktop_dev.ps1` 会检查 source/dist 身份并在需要时重建 UI。
- **发布一致性**：正式构建拒绝 dirty worktree，生成 UI `build_manifest.json`、整包 `release_manifest.json`、`build_identity.json`，部署后校验每个清单文件哈希和快捷方式目标。看板当前证据默认诚实显示 `MISSING/STALE/BLOCKED`，不以历史录像冒充当前 SHA 证据。
- **门禁与 mock**：release gate 使用全量 `python -m pytest tests -q`，冻结回放同时要求子进程退出码为 0；浏览器 mock 支持正常、订阅/运行环境失败和启动 ERROR 分支。`disconnect_modal_missing` baseline 不修改，继续 BLOCKED。

## 最终回验方式

构建完成后，`build_identity.json.source_sha` 必须等于 `git rev-parse HEAD` 且 `source_tree_clean=true`；`release_manifest_sha256`、`exe_sha256` 和快捷方式目标由 `build_release.ps1` 及以下命令复核：

```powershell
git status --short --branch
git rev-parse HEAD
python tools/release_gate.py
python -m pytest tests -q
$id = Get-Content (Join-Path $env:USERPROFILE "Desktop/ShuaBao/build_identity.json") | ConvertFrom-Json
$id.source_sha; $id.source_tree_clean; $id.release_manifest_sha256; $id.exe_sha256
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $env:USERPROFILE "Desktop/刷刷宝.lnk"))
$lnk.TargetPath
```

正式构建使用：

```powershell
powershell -ExecutionPolicy Bypass -File ./build_release.ps1
```

## 仍需真实机器确认的事项

离线测试和构建不能替代真实游戏证据。以下状态保持诚实，不宣称已完成：

- 存档入口、传家宝入口和大秘境入口需要使用本次最终构建重新跑一遍连续 HUD 后置确认，并将 bundle 绑定当前 `source_sha`、整包 manifest 哈希和 EXE 哈希。
- 时光之穴完整 NPC 入口、跟车队长开局/掉线/回房、大厅蹭车真实点击链仍需真机验证。
- `disconnect_modal_missing` 继续 `BLOCKED`；不得用合成帧、pytest 或旧截图升级为 PASS。
- 正式 gate 的标准离线结果可以为 4/4 PASS；strict release 在断线真实证据缺失前不应被描述为全绿。

本文件记录的是修复后的交付边界；具体提交 SHA 和本机产物哈希以同一提交完成构建后的 `build_identity.json` 与最终回验输出为准。
