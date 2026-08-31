# 刷刷宝交接 2026-08-29

权威以本文件为准。上一份看板交接 `CURRENT_STATUS_AND_HANDOFF_20260821.md` 仍描述 UI 交互，不覆盖局内选卡。

## 23:38 实机（未修版本）

`C:\Users\10639\AppData\Local\ShuaBao\20260828\trace_20260828_233828.jsonl`

- 开局连续 `OpenSkillPanel`（G），到 tick 63 才第一次 F。
- 只确认拿到「经济」后就点了两次「封神」。
- tick 75 面板上出现「箭术」，当次选的是「经济」，不是箭术羁绊。奥术箭技能（箭矢连发/齐射等）来自已勾选的 `asj`。
- tick 159 `ClickEvolve` 后，英雄二选一被 `treasure_lock_btn` 判成宝物，tick 161/163 点了隐藏。
- 设置文件没有被部署清空；`cards` 与 `_shell.bond_scheme` 双写，scheme 里残留「箭术」。

桌面快捷方式 `刷刷宝.lnk` → `C:\Users\10639\Desktop\ShuaBao\ShuaBao.exe`（2026-08-29 09:55，含标题模板 `ffb3cfd`）。不是 MSI 安装包。用户设置仍在 `%LOCALAPPDATA%\ShuaBao\user_settings.json`，部署不会清空。

## 本轮已接线

- 局内循环起步改为 F；基础卡未到 80% 时继续锁 F。
- 高级卡组按白名单出现顺序一次只推进一套，当前套未到 80% 不拿下一套。
- 进化点击后 / 等英雄选择时，不再把英雄二选一判成宝物并隐藏。
- 看板加载用 `cards + bonds` 还原勾选；保存不再把 stale `bond_scheme`（箭术）写回白名单。
- 木材数值 HUD 仍未接线。界面「赌木 · 木材阈值 · 待接线」保持原样。开局和基础卡未满时只开 F，是当前能落地的替代，不是读到木头 > 300。

## 识别优先级（2026-08-29 续）

长期稳定性 > 准确度 > 速度：自己打开的面板 OCR 读名/选卡/刷新都要第二帧确认；没读到不刷新、idle 时不 Fail-Forward；live OCR 超时下限 2500ms；4 张布局先读 4 槽。

## 标题模板（2026-08-29 根源）

`G:\下载\1.5.1.zip\Images\cards` 不是 OCR 训练集，是 ~44×24 的 `matchTemplate` 标题字形。live F 以前读完 OCR 就返回，**从未**用这些图填空槽。另外短码标签和像素对不上：`jj`=经济、`tz`=挑战、`fs`=法神、`gushou`=固守、`yihuo`=异火、`mfs`=秘法师；`法术/急速/魔能` 在包根目录 `fashu/jisu/moneng`。卡住的 4 选（三国/刀刀/挑战2/3/暴击）上官方 `tz`/`baoji` 标题分 0.90/0.96，OCR 空白也能点挑战。这些字形原样打进主程序做 matchTemplate，不要拿去训 OCR。

## Stage 2A/B0 / Pre-Push Audit（2026-08-29）

- [Pre-Push Audit](distillation/PRE_PUSH_AUDIT_20260829.md) 为本轮 Stage 2A/B0 的收口证据；curated release gate 为 `4/4 PASS`，但 repo-wide pytest 当前冻结为 30 个既存失败 nodeid（含 Atlas/UI detector/历史 L0-L1 fixture/desktop/replay），所以不能写成全仓全绿。
- Panel timeout→cooldown→reopen 已用最小 harness 收口：复用 panel episode/cooldown/count，预算只计异常重开，正常 skill/bond/treasure 成功 episode 不消耗；三类 counter 独立，达到上限后永久 cooldown；仍遮挡 UI 的面板不会被忽略来伪造推进。`giveup_panel_not_fail` 已由真实三帧 replay PASS，`main_hud_idle` 已同步确认的 bond-first 真实修复。
- Panel 机制级 P0 已 CLOSED，但端到端长线程仍有最长约 381s 到 panel quarantine、接近 `round_timeout_s=3600s` 才 round fail-closed 的 stall 风险；本轮只记录，不新增 watchdog/recovery/fallback。
- `disconnect_modal_missing` 继续 `BLOCKED`，没有用合成帧更新 baseline。Coverage 阶段只做素材/评测，不接生产。

## 仍未做

- 亡灵 100 残骸 / 亡者大厅 / 邪爆、异火吞噬完再拿帝焱：没有对应计数器，不能假装已接线。
- `test_pause_overlay_clicks_resume_before_game_actions` 仍是全量 pytest 的既有回归；这不等同于 giveup baseline，后者已通过真实三帧 replay。不要为了绿灯修改无关 baseline。

## Live 看板与 Boss 选择收敛（2026-08-31）

### Root Cause Summary

- 默认 Web 看板在章节/关卡变化时调用硬编码 `STAGE_BOSS` / `STAGE_CJB`
  推荐表，直接改写 `state.boss` 与 `state.cjb`；设置恢复又在重绘名称之后覆盖
  state，造成“看板自动跳到前面关卡”和显示值可能不等于持久化值。
- 生产 `Mediator._maybe_challenge_configured_boss` 只搜索显式目标并有界滚动；
  目标未开放或未识别后保持零输入，没有用户要求的“最后可挑战项”兜底。
- 时光之穴分类页此前仍从 `cjb_boss + sgzx_boss` 混合候选中搜索；传家宝页
  已经只读 `cjb_boss`，两类选择的生产隔离不对称。

### Changes

- Web 看板章节/关卡只更新 `stage_targets`；Boss 与传家宝“选啥显示啥”，不再
  自动改写。恢复设置后先应用持久化 `cjb_boss` / `sgzx_boss`，再刷新名称。
- 时光之穴分类页只消费 `sgzx_boss`，传家宝分类页只消费 `cjb_boss`。
- 配置目标仍有最高优先级；仅在页面已分类、目标未命中且既有三次滚动预算耗尽
  后，生产 handler 才按正式模板编号从高到低寻找当前可见的最后一项。命中仍走
  同一个 `BossConfigured` 输入和既有业务后置条件；无模板命中、页面 `UNKNOWN`
  或未分类时继续零输入。没有新增 FSM、detector、固定坐标或 click-success PASS。

### Real-material offline evidence

同一个生产 helper 对既有真实素材只读复现：

| Material | Classified page | Last recognized template | Score | Meaning |
|---|---|---|---:|---|
| `fixtures/reborn_wow/endgame/archive_challenge_panel.png` | `ARCHIVE_PANEL` | `12卡尔加` | 0.844816 | 时光之穴列表兜底可离线复现 |
| `fixtures/reborn_wow/endgame/heirloom_challenge_bosses.png` | `HEIRLOOM_DIALOG` | `03洛卡纳哈` | 0.806868 | 早期传家宝列表可离线复现 |
| `boss_challenge_20260831_005535_200618/frames/f0006_action_before.png` | `HEIRLOOM_DIALOG` | `12战争之王` | 0.762833 | 较新实机滚动列表可离线复现 |

这些命中证明现有真机素材可继续用于触发、识别、滚动和结束判断回归；它们不是
当前 SHA 的完整业务 PASS，也不能替代真实 HUD / postcondition。

### Feature status

| Chain | Formal dashboard / production wiring | Current acceptance |
|---|---|---|
| 黑商 | 正式设置已进入生产 `Mediator`，历史真机有购买/吞噬丹触发 | `VALID BUT OLD / MISSING_REAL_SAMPLE`；当前 SHA 的 2/5/8、木材、吞噬丹 canonical 验收未齐 |
| 传家宝 | `cjb_boss` 正式接线；历史有 `BossConfigured` 成功输入和真实列表素材 | 可做定向实机，但三次完整 HUD→active→completion（含一次滚动）仍未满足，不能宣称全链 PASS |
| 时光之穴 | `sgzx_boss` 正式接线，列表/Boss 交互有历史实机素材，本轮离线兜底已验证 | 完整 NPC 进入链 Ground Truth 仍 `BLOCKED`；不能宣称正式全链可跑通 |
| 秘境 | `auto_secret_realm` 已进入同一生产 `Mediator` | 仍无合格真实 HUD + `_secret_realm_active=True`，`MISSING_REAL_SAMPLE` |
| Boss 长链 / 八卡 | 八卡与 Boss 路由均在生产 handler，历史 bundle 有八卡动作 | 当前 SHA 的最终业务后置未闭环；长链继续放在定向链路之后执行 |
| P0 生命周期 | Live 菜单只是生产 handler 的证据壳，不复制业务 FSM | 五次 start→probe→stop/F12→bundle→menu-return 仍 `MISSING_REAL_SAMPLE` |

正式看板“已接线”不等于“当前版本全链真机 PASS”。除秘境外确实存在不同程度的
历史触发成功，可直接用于离线优化和定向复测；但传家宝、时光之穴完整入口、Boss
长链和黑商 canonical 仍缺当前 SHA 的完整业务证据。

### Tests

- Web：`npm run check` PASS；`npm test` 21 passed；
  `tests/test_web_config_shell.py` 31 passed。
- Boss/挑战定向：56 passed、2 subtests passed；生产兜底的两张仓库真实 fixture、
  设置隔离、滚动优先和无模板零输入均有回归。
- `tools/release_gate.py`：4/4 PASS（340 pytest、Frozen Replay、scene templates、
  56 contracts）；`disconnect_modal_missing` 保持 `BLOCKED`。
- 全仓 `python -X faulthandler -m pytest tests -q --tb=short`：稳定运行至 100%，
  **31 failed, 1068 passed, 5 skipped, 2 xfailed, 207 subtests passed in 206.89s**。
  未再发生 `0xC0000409`；native-process / 退出阻塞已疏通，但 31 个既有普通断言
  仍为 `FAIL / OPEN`，没有改 baseline 或把精选 gate 当成全仓全绿。
