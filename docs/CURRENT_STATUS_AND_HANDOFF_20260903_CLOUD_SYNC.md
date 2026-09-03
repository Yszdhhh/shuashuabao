# 2026-09-03：云端修复同步与本地复核

## 当前状态

本轮代码同步、必要合并修复与离线验证已完成；发行/部署和真实大厅验收仍为 **BLOCKED**，不能认定 RELEASE READY。
本记录不替代最终签名 EXE、TLS、订阅 permit 和真实游戏后置条件证据。

| 仓库 | 本地分支 / HEAD | 同步方式 |
| --- | --- | --- |
| `G:/刷刷宝/GameScript-Local` | `trial-merge` / `2a4e41ee58f3b70bd57dcc919cd13e4f6fa7ee82` | 从 `d697ed6` 快进；与 origin 相同 |
| `G:/刷刷宝/Worktrees/subscription-lab-642235c` | `integration/subscription-admin-local` / `5bca48fefbbfe93f2bdd61db9299419e941cefc4` | 本地合并提交；保留原本地 6 提交和云端 `93d0b69`；未 push |

服务端合并提交双父为 `3336a6ede6f8323d9ae92ae5efa6a0820772bf4a` 和
`93d0b691f391aa5c8f35a414b7b88a5098f5bfb1`。未部署服务，未启动游戏输入。

## 本地改动保护与必要合并处理

- 原始主仓库已跟踪修改有 **两个文件**：`src/shuabao/mediator.py` 和 `tests/test_live_scenario_capture.py`，比云端交接描述多了 mediator。
- 原始完整文件、binary diff、状态、验证日志保存在 `G:/刷刷宝/Archives/cloud-sync-20260903-01a06761/`。
- 原始 tracked stash 保留：`193f608cde60d16eda16b4936967ce2db492e35c`，标签 `before-cloud-sync-20260903-01a06761`；原有旧 stash 也保留。
- 测试文件按字节恢复，SHA256 为 `b8966836f54815d85590694977570042b5ac973456e7d0d71e6555d43a1f6a77`。
- 搜索框冲突采用云端“无锚点零输入”，没有把本地固定坐标搜索兜底重新接回运行路径。
- 本地 Tab 坐标/阈值调整导致两个离线失败：未知页点击、错误槽位。恢复云端 Tab 规则后，三份定向测试 **82 passed**。
- 验证中另一个操作再次改写 Tab 函数，加入放宽模板区域、OCR 和无条件几何兜底；该版本再次复现同两项失败。用户确认已暂停后，恢复云端 Tab 函数，其余兼容的本地修改继续保留。并发版本也保存于 `main-concurrent-overlay.patch`。
- 保留了本地 stage-page 和 room-list 判定修改；它们仍属于未提交覆盖层，离线通过不证明真实大厅正确，尤其房间列表证据盖过房内控件的判定仍需真机确认。
- 原有 artifacts、文档、临时工具均未清理或纳入提交；并发新增工具也保留。订阅仓库原有 keygate/keygen 脏子模块未更新、未清理。

## 服务端合并时补修的问题

文本合并无冲突，但本地旧 provider 仍自动签发静态身份 permit；直接合并会保留新旧两条签发路径。
本次移除旧自动签发，统一由显式 `permit_request` 经新 `PermitIssuer` 签发，保留本地管理后台、SQLite 和备份功能。

独立复核另发现空/全空白设备指纹可跳过旧 provider 的激活检查。新增两个 HTTP 回归先复现失败，再在 permit 入口拒绝空白设备标识；合法指纹原值不改写。
普通卡密查询、发行不批准、模式拒绝、缺签名上下文和空设备请求均验证为不返回 permit。

服务端全套测试：**108 passed / 5 skipped / exit 0**。5 个跳过项均为需要真实 Docker Compose 服务的 E2E。
新增 11 个 permit 接口回归及 4 个管理/持久化/备份回归。测试使用隔离签名文件、测试数据库和内存 provider，未使用真实签名文件或生产数据库。

## 主程序验证证据

- 三份定向测试：`test_live_scenario_capture.py`、`test_lobby_hitch_safety_regressions.py`、`test_subscription_release_binding.py`，**82 passed**。
- 主工作树首轮 `release_gate.py`：**1359 passed / 2 xfailed / 1 skipped，4/4 PASS，exit 0**。该轮中发生并发源码改写，后已恢复到同一代码内容；最终稳定重跑结果见下面补记。
- 独立干净 `2a4e41e` 工作树门禁：**1346 passed / 2 xfailed / 13 skipped，4/4 PASS，exit 0**。该工作树缺少 gitignored OCR/真实截图资产，因此不能用其较多 skip 替代主工作树验证。
- 契约 **56 passed**；模板 **147/147**；运行素材 **386/386**，无缺失和 hash mismatch。
- `disconnect_modal_missing` 仍是既有 **BLOCKED**；未修改门禁 baseline、未用合成帧声称真机修复。
- 干净核验工作树保留于 `G:/刷刷宝/Worktrees/cloud-sync-audit-2a4e41e-20260903`。

## 云端补丁仍未闭环的审计项

1. **发行策略与验收仍不一致**：`release_signing.py` 的 manifest pin 仍为空；所有 frozen 运行时要求签名，但 `build_release.ps1` 仍将 dev/internal 标记为 unsigned。`release_harness.py` 仍未调用生产 manifest 签名 verifier，无 `.sig` 的 dev 测试仍可 PASS。
2. **部分启动入口漏接新请求上下文**：`shell/headless_runner.py:110` 与 `shell/main_window.py:4378` 仍无发行 context 调用 `check_start_permission()`；新版服务不为普通查询返回 permit，因此这些入口仍可能 `PERMIT_MISSING`。
3. **UI 状态未完全分离**：激活缓存仍可构造不含 permit 的允许状态，preflight 仍只看 allowed。最终 Runner 验签保持 fail-closed，但 UI 的“卡密有效”不能等同 LIVE 已授权。
4. **大厅补丁覆盖范围有限**：已恢复 pending→后续确认→再扫房，并停止把 cancel-ready 当点击目标；原审计要求的准备点击后等待锁、显式帧新鲜度检查、搜索输入分支的有界冷却和专用数字证据仍未完整实现。
5. **frozen 配置优先级和请求字段校验仍有限**：dev/internal 环境变量覆盖 sidecar 的规则未改；客户端 context normalization 只校验字段齐全和非空字符串，不能扩大宣称为全部畸形身份都在请求前拒绝。

双方沿用 `/v1/entitlements/validate` 加 `permit_request`，没有新增独立 `/v1/permits`。路径名称不同本身不构成协议错误。

## 当前桌面工件：未更新

- 正式入口：`C:/Users/10639/Desktop/刷刷宝.lnk` → `C:/Users/10639/Desktop/ShuaBao/ShuaBao.exe`；快捷方式工作目录一致。
- 实测桌面 source SHA：`df6fba578ffb14ae081f770e2478984cb95957cf`，渠道 `dev`。
- EXE 实际 SHA256 与旧 build identity 一致：`90a16515920b7a3d3d8918bbc10f7d1acb8bd318e25db5d6760a008cafef4231`。
- `release_manifest.json` 存在，`release_manifest.json.sig` 缺失。
- 本轮没有构建、替换 EXE、部署订阅服务或执行真实大厅输入。

下一次交付仍须先统一 frozen 签名/验收策略并注入真实 operator 公钥，完成最终签名构建，取得真实 source/manifest/channel，配置服务端批准发行和对应 permit 签名材料，再部署服务及桌面包，以最终 EXE 重做 TLS、完整授权和真实大厅验收。

## 最终稳定重跑补记

用户暂停另一操作后，最终主工作树完整门禁再次通过：**1359 passed / 2 xfailed / 1 skipped，四阶段 4/4 PASS，exit 0**。
运行前后 `mediator.py` 与原有测试文件的 SHA256 均一致，`inputs_stable=true`。
当前 mediator Git blob 为 `73d9c8cfe2af328b37ee5007433c006907367f5b`；原测试文件仍与原始备份按字节一致。

最终结果位于 `G:/刷刷宝/Archives/cloud-sync-20260903-01a06761/main-final-release-gate-result.json`，
完整日志为同目录 `main-final-release-gate.log`；服务端结果为 `server/pytest.log` 和 `server/integration-status.txt`。
最终 `git diff --check` 通过，主仓库无未解决合并；原有未跟踪路径全部仍存在。
主仓库保留两个未提交 tracked 修改及新交接文档；服务端只有原有两个脏子模块，合并提交尚未推送。
