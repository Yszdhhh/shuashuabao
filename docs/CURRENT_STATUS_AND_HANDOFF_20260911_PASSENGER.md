# 2026-09-11 蹭车/跟车完整链路交接

## 结论与固定身份

- 对齐起点：`integration/formal-g0-live-20260911` @ `e017026ca9abff237bfd1f3f867a92a309a18df7`。
- Production 提交：`adc6fb5792e6f366c046385343578d3efca9f45c`。
- Harness rebaseline 提交：`b862e38c7ecbda969ba5959d0de03682b7fc00ae`。
- Production 固定工作树：`G:\刷刷宝\Worktrees\prod-source-3904913-20260911`（detached，clean）。
- 开发/Harness 工作树：`G:\刷刷宝\GameScript-Local`，分支 `fix/live-hitch-follow-closure-20260911`。

## 本轮行为变化

1. 压力转移只在蹭车自然经过大厅搜房、进房 Ready、房主开局后武装。中途启动或中途接管局内 HUD 不再检查或点击压力转移。
2. 房间黑名单保持进程内，不持久化；误开单人选关/游戏大厅时拉黑当前房间，进入 `QUIT -> NEXT`，优先点击右上“退出游戏”，再点击中间确认。
3. 蹭车与跟车共用乘客局内契约：黑商、宝物、四挑战、物品栏/个人背包到公共背包、胜利页、存档挑战、时光之穴、传家宝链保持一致；跟车仍不搜房、不换分房、不点 RoomStart。
4. 公共背包手势固定为：右键物品栏源物品 -> 左键个人背包空格 -> fresh 状态重新扫描 -> 右键个人背包物品 -> 左键公共背包空格。个人背包优先于物品栏排空，并在链结束后关闭背包。
5. 传家宝 Boss 结果确认且弹窗关闭后，除旧 `zhuangbei` toast 外，识别右侧至少三行、近等距且横向对齐的绿色“已获取”装备列表。用户附件 `img_v3_0215e_cd7a770c-d93c-43aa-beef-446d5eaf181g.png` 已做本机真实截图探针并命中。
6. 跟车未启用秘境时，传家宝装备已获取或 Victory 后退出；启用秘境时，传家宝后点击“继续游戏”，进入秘境，直到秘境失败、游戏失败或房主/玩家离开证据触发退出。
7. 跟车配置面板补出 `cjb_boss`、`sgzx_boss`、`auto_secret_realm`。

## 验证结果

- 定向回归：`187 passed, 61 subtests passed`。
- Launcher 使用固定 `ProductionSourceRoot` 的 `SOURCE_RUNTIME` 时不再把仓库内未参与执行的旧 `dist/ShuaBao.exe` 带入身份门禁；真实使用 EXE 的入口仍保留原 SHA 校验。PowerShell Parser `0` 错误，Launcher UTF-8 BOM 保持。
- L0 起点预检若首次命中最小化旧游戏窗、随后等待阶段已重新捕获并确认 KK 房间列表，以最终窗口状态裁决，不再残留过时的 `game window unavailable`；最终窗口仍不可用时继续 fail-closed、零输入。
- Harness 身份：`production_code_diff=CLEAN`、`ready_for_gt=true`、`match=READY`。
- 最终发布门禁（提交态，同一次运行）：
  - pytest：`1953 passed, 2 xfailed, 1 skipped`
  - frozen replay：PASS（`disconnect_modal_missing` 仍按既有缺素材合同保持 BLOCKED）
  - scene templates：PASS，`148 ok, 0 missing`
  - contract：PASS，`56 passed`
  - 汇总：`PASS（阶段 4/4 通过）`

## 实机测试入口

桌面快捷方式 `C:\Users\10639\Desktop\刷刷宝 Live 实机测试.lnk` 应指向：

- Launcher：`G:\刷刷宝\GameScript-Local\live_scenario_launcher.ps1`
- `ProductionSourceRoot`：`G:\刷刷宝\Worktrees\prod-source-3904913-20260911`
- `ProductionSourceSha`：`adc6fb5792e6f366c046385343578d3efca9f45c`
- 测试：`13 PRIMARY HITCH_FULL_NATURAL_E2E`，`hitch_cycle_num=5`。

实机 PASS 必须以本次新 capture bundle 的 trace/manifest 为准；离线回归和用户旧附件不替代 5 局真实链路证据。

## 2026-09-11 本轮实机复盘与修正

- 实机 bundle `hitch_lobby_chain_20260911_133833_722525` 实际只进入 1 次房间，`game_count=0` 、`pressure_confirmed=0` ，不是 5 局 PASS；结束原因为操作员点击 HUD 停止。
- Harness 现在将进局 HUD 只记为中间证据，只在观察器完成配置局数并真实回大厅后才提升 authoritative target；`hitch_cycle_num=5` 时观察器需满 5 轮。
- Production candidate 新提交 `adc6fb5792e6f366c046385343578d3efca9f45c`：蹇车房间发现「开始游戏」+首排红色「房主」标记时，认定客户被提升为房主，走现有有界退房（退出按钮使用专用模板兜底），不点 RoomStart。
- 大厅搜索默认扩为 `4,3,速`，桌面快捷预设同步；用户自定义搜索词仍按原样保留。
- 本机发现两个无父进程 OCR `python` 孤儿（PID `53188`/`57860`，合计约 460MB），已尝试精确结束，但 Windows 返回 `Access is denied`；未终止 KK 平台本体。
- 回归：`121 passed` （针对 capture/hitch/mode）；桌面 shortcut 已同步到新 candidate SHA。
