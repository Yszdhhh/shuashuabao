# 看板整合简报（2026-08-14）

> 只读汇总：调研 + 测试夹收集结果，供 `desktop_app` / 控制中心对接。<br>
> **不改** `live_enabled`、不接 Mediator 点击、不 commit。<br>
> 权威方案：`CONTROL_CENTER_PET_ATLAS_PLAN_20260814.md`；蹭车细节：`MODE_SKELETON_AND_LOBBY_HITCH_20260814.md`。

---

## A. 一句话现状

看板今天只能稳启动 **自己刷图（`normal_farm`）**；跟车 / 赌木 / 站团本 / 大厅蹭车已有 ModeSpec 骨架与证据夹具，但全部 `live_enabled=false` + `desktop_start=false`；找房可跑线只在 **测试夹** dry/live，主工程零接线；控制中心 / 宠物 / 图鉴方案已定、**外壳未落地**（无 `src/gamescript/shell/`）。

命名对照：方案文写 `solo_farm`，仓库 ModeSpec 写 **`normal_farm`**——看板左栏应对齐 `config/mode_specs.json`。

---

## B. 运行方式清单（左栏该怎么展示）

| id | 左栏标签 | live_enabled | desktop_start | 看板能否启动 | 用户已确认规则 | 证据 / 夹具 | 还缺什么才敢接真机 |
|---|---|---|---|---|---|---|---|
| `normal_farm` | 自己刷图 | **true** | **true** | **能**（现有桌面唯一 LIVE） | 关卡 N-M、普通/英雄、技能≤4、羁绊≤6、负面宝物 opt-in | 现网 L0+L1；03c/08/10 测试夹长测 | 外壳门禁仍缺 RunnerService；第 4 局丢窗另案 |
| `follow_team` | 跟车 | false | false | **否**（展示+禁用） | 已在房等队长；不创房、不点开始游戏 | 仅骨架 `FollowTeamFlow`；y3 录屏**无大厅列表** | 队长已开/掉线/回房真机链；`fixtures/follow_team/` 仍空 |
| `gambling_wood` | 赌木 | false | false | **否** | 首个宝物判定后重开（竞品有字段） | 骨架；词典无「赌木」卡名；`auto_gambling_time` 未接线 | 目标卡名、完成条件、重开闭环录像 |
| `raid_wait` | 站团本 | false | false | **否** | 4–8h 等待；人工先兑换魔团本 | 骨架；LONGZHU Fail-Closed | 「兑换魔团本」入口锚点 |
| `lobby_hitch` | 大厅找房蹭车 | false | false | **否**（可展示字段，启动键禁用） | 见 §C 四条产品规则 | 短片+详片+弹窗+特殊房金准备；测试夹可跑 | 行 OCR/锁标/回列表核对方主；压力转移进 scenes；局末进入≠关窗；**禁止**把测试夹 live 当主工程 LIVE |
| `lab` | 实验室 | true（CLI） | **false** | **否**（看板不启动） | 入口只有 `tools/lab_run.py` / 测试夹 bat | `evidence_status=live_cli` | 与看板抢 `live.lock`；禁止双 Mediator |

徽章文案建议（对接控制中心方案 §5）：

- `normal_farm` → **可启动**
- `follow_team` / `gambling_wood` / `raid_wait` / `lobby_hitch` → **待验证 · 不可启动**
- `lab` → **CLI**（高级页说明，或左栏永远禁用）

预检灯必须读 `ModeSpec.live_enabled && desktop_start`（`desktop_may_start()`），托盘/热键不得旁路。

---

## C. 蹭车（`lobby_hitch`）单独一节

### C.1 产品规则（已写入 ModeSpec + `LobbyHitchFlow`）

1. 可设精确关卡（`stage_targets` 可选）；3/4 是搜索**前缀**（房间名子串），精确名优先否则进空房。<br>
2. 密码房锁定跳过（`skip_password_rooms=true`，不可关）。<br>
3. 点准备进局 → 压力转移；局末 Boss / 时光之穴 / 传家宝；打完退出。<br>
4. 顶层必选搜 `3` 或 `4`（`hitch_stage_prefix`）。

`can_start=False`，`click_intents=[]`，`evidence_status=video_detail_no_click`。

### C.2 状态机摘要（17 步，全部 `implemented=false`，未知零输入）

| # | 阶段 | 要什么 | 禁什么 |
|---|---|---|---|
| 1 | see_list | 房间列表 Tab / 刷新；`create_room` 只读页锚 | 点建房 |
| 2 | type_search | 搜索框打 3\|4 | — |
| 3 | refresh_list | 「刷新」空闲（非「刷新 Ns」） | 冷却中点刷新 |
| 4 | scan_rows | OCR 名/`x/4`/游戏中/锁；跳过密码·满员·游戏中·反选 | — |
| 5 | join_row | 单击可进行 | 底栏三键（C4） |
| 6 | dismiss_full_room | 满房只取消 | 「快速加入房间」 |
| 7 | guest_ready | 准备（金/蓝）；记房主 | RoomStart / 邀请 / 退出 |
| 8 | wait_host_start | 倒计时 / 等玩家1 | 客人点开始/选关 |
| 9 | view_and_control | F1/F2（口述与 UI 不一致） | — |
| 10 | pressure_transfer | `yalizhuanyi.png` | — |
| 11 | open_challenges | 自动任务 + 四挑战 | — |
| 12 | donate_loot | 丹/绿符/英雄卡/一身神装丢 1 号 | 现网自用路径 |
| 13 | mainline_watch | 失败≥120s 且未过 5-5 才重开 | — |
| 14 | end_challenges | 进入三挑战（非关窗） | 照搬现网关传家宝 |
| 15 | after_game_exit | exit_confirm | — |
| 16 | check_host | 同房主留房，否则退房 | 读不到 → 当换人 |
| 17 | continue_list | 回列表，搜索词应还在 | — |

`never` 恒含：`color_fallback` / `quick_join` / `quick_match` / `quick_join_room` / `RoomStart` / 建房与 fallback。

### C.3 弹窗处理（只读规则 `hitch_popup_action`）

| kind | 动作 | 夹具 |
|---|---|---|
| 等级不符 / 平台提示 | **leave**（右侧灰「离开」） | `fixtures/lobby_hitch_20260814/popup_level_unmet.png` + `_leave_btn` |
| 密码房 | **cancel** | `popup_password.png` + `_cancel_btn` |
| 满房 | **cancel** | `lobby_hitch_detail_20260814/t0046.00.png` |
| create_room / quick_join / 确定 | **wait**（永不从规则返回这些） | — |

单测：`tests/test_mode_specs.py`。

### C.4 特殊房金色「准备」

- 用户静帧：`kk_special_room_ready_gold.png` / `kk_special_room_ready_waiting.png` / `kk_special_room_ready_gold_btn.png`
- 底右：金「准备」/ 绿「邀请」/ 灰「退出」；聊天催准备倒计时
- **图里没有「锁定」按钮**；`hitch_ready_label("锁定")` → `unknown`
- 关键字：准备 / 已准备 / 取消准备；禁点邀请·退出·开始游戏
- `hitch_ready_kick_seconds`：OCR「请点击准备按钮…Ns」→ 紧急日志；测试夹仅 `--live` 才点准备

### C.5 「锁定」仍缺图

若游戏另有「锁定」态，需要用户补静帧；当前规则与测试夹均按「无锁定」处理。

### C.6 测试夹怎么跑

路径：`C:\Users\10639\Desktop\测试夹\`

```bat
09-找房-只识别.bat          REM dry：画框+日志，零点击
09-找房-live.bat            REM 提权后白名单点击
python hitch_find_room.py --prepare          REM 只拷夹具/裁金准备模板
python hitch_find_room.py --prefix 3
python hitch_find_room.py --prefix 4 --stage 速30
python hitch_find_room.py --prefix 3 --live
```

模板目录：`测试夹\hitch_templates\`（leave / cancel / full_room_cancel / ready 金+蓝 / refresh / search_box）。<br>
先开 KK 停在房间列表；**不要同时开刷刷宝看板**；停 Ctrl+C；画框在 `hitch_annotate\`。

---

## D. 测试夹 vs 主工程边界

| 在测试夹 | 禁止进 Mediator / 看板 live |
|---|---|
| `hitch_find_room.py` 搜房+弹窗+准备 | 把 `--live` 白名单抄进 `mediator` 当正式 L0 |
| dry 默认；`--live` 需管理员 | `lobby_hitch.live_enabled=true`（证据未齐） |
| 复用仓库只读规则函数（`hitch_*`） | 用 `room_start` 模板点「准备」（0.84 误匹配） |
| 丢物品只识别+日志 | 无落点就右键乱丢 |
| 09 bat 与 03/08/10 实验室 bat 并列 | 看板「开始」启动蹭车；与 lab 双开 LIVE |
| 模板在 `测试夹\hitch_templates\` | 未经验证就写入 `scenes.json` 并默认点 |

主工程已有、可安全给看板读的：

- `config/mode_specs.json` + `src/gamescript/modes/{specs,flows}.py`（只读门禁与文案）
- `src/gamescript/runtime_status.py`（frozen 快照，已存在）
- 夹具目录（证据展示，不自动等于可启动）

---

## E. 看板 / 宠物 / 图鉴整合建议（对接 CONTROL_CENTER）

### E.0 命名与现状缺口

| 方案文档 | 仓库现状 |
|---|---|
| `solo_farm` | **`normal_farm`** |
| `src/gamescript/shell/` | **未创建** |
| Canvas `control-center-pet-atlas-plan.canvas.tsx` | **仓库内未找到** |
| 相位从 print hook 抠 | `desktop_app` 仍劫持 print；`RuntimeStatus` 已可替代 |

### E.1 P0 — 看板 + ModeSpec 门禁（只动外壳）

接这些字段 / 行为：

- 左栏：六个 ModeSpec id（标签用 `label`）；徽章用 `live_enabled`/`desktop_start`
- 右栏：当前 `visible_settings`；`lobby_hitch` 可摊开说明但主按钮 `setEnabled(False)`
- `RunnerService.start` → 唯一 LIVE；内部 `desktop_may_start(mode_id)`；否则 `ModeNotEnabled`、零 Mediator
- start 时 **深拷贝** Settings；用户设置写 `%LOCALAPPDATA%/ShuaBao/user_settings.json`
- 底栏钉死：摘要 + 预检 + 开始/停止；用词「运行方式」≠「关卡难度」
- 进度：有 `cycle_num` 显示局数比；否则只显示已完成局数，**禁止** phase 下标百分比
- **不**做宠物；**不**从看板启 lab；预留 `ShuaBao.live.lock`
- `desktop_app.py` 瘦身入口并再导出，保住 `tests/test_desktop_app.py`

### E.2 P1 — RuntimeStatus + 宠物

- 已有 `RuntimeStatus` / `runtime_status_from_mediator`：GUI 200ms 读快照；**删除**相位 print 解析
- 补齐方案 §8 建议字段中文表（含 `HERO_SETUP` / `RECOVER_FAILURE` / `COMPLETE`）
- 宠物：点击穿透自检失败则永不显示；不可点；托盘无「启动跟车」

### E.3 P2 — 图鉴只读（AtlasView join，禁止新 atlas.json）

| 源 | 规模 | 看板用法 |
|---|---|---|
| `config/skill_card_catalog.json` | 220 升级卡 | 只读；不可写入 `settings.skills` |
| `config/skill_meta.json` + labels + `assets/Images/skills/` | 16 主技能 | 浏览；空闲可「应用到本局」→ 网格 ≤4 |
| `config/bond_stack_catalog.json` | 65 `need` | 知识列；无短码不可勾 |
| `config/fetter_labels.json` + cards 图 | 36 短码 | 可进运行白名单 ≤6 |
| `config/choice_policy.json` | 负面 6 + EX 4 | 与首页折叠同源；EX 标「策略必拿」 |
| `fixtures/treasure_must_take/` | 4 静帧 | 「实机」标签 |
| `fixtures/ur_attr_routes/` | 9 静帧 | 羁绊图鉴证据，非独立白名单 |
| 黑商 | 探测有、货品表无 | **空态页**；全屏帧 BLOCKED；禁编货品 |

### E.4 P3

跟车/赌木/站团本/蹭车：UI 字段可继续补，**仍** `live_enabled=false`，直到 L0 另开提交 + 真机证据。

---

## F. 需要用户拍板的开放项

1. **「锁定」按钮**：是否存在？若有，补特殊房锁定态截图；否则看板文案写死「无锁定 / 只认准备」。<br>
2. **反选 UI**：`hitch_reject_list`（房间名/房主/地图）默认空——P0 看板要不要露出编辑器，还是等接线再露？<br>
3. **精确关卡 vs 模糊房**：录像进的是「速30 / 30敏10力」，不是关卡名；看板是否默认「只搜前缀、精确关卡选填」并黄字提示「录像未演示精确过滤」？<br>
4. **找房 dry 是否先挂看板**：建议 **否**——看板只展示 ModeSpec +「请用测试夹 09」链接；或只读「证据状态」徽章。不要在外壳层嵌 `hitch_find_room.py`。<br>
5. **F1/F2**：口述「两次 F2」vs UI「F1 查看英雄 / F2 返回阵地」——以哪次为准再接线。<br>
6. **蹭车局内范围**：压力转移 / 丢地 / 局末三挑战是否等找房列表稳定后再做第二阶段（推荐：是）。<br>
7. **桌面英雄 spritesheet**：有无原创像素稿；没有则 P1 剪影+文案。<br>
8. **左栏是否显示 `lobby_hitch`**：方案 §5 跟车卡写「找房证据见专项」——是否单独一张「大厅蹭车」卡（推荐：是，与 `follow_team` 分开）。

---

## G. 文件索引表

| 路径 | 角色 |
|---|---|
| `docs/research/DASHBOARD_INTEGRATION_BRIEF_20260814.md` | **本文**（看板整合入口） |
| `docs/research/CONTROL_CENTER_PET_ATLAS_PLAN_20260814.md` | 控制中心+宠物+图鉴对抗终稿 |
| `docs/research/MODE_SKELETON_AND_LOBBY_HITCH_20260814.md` | 模式骨架 + 蹭车规则/录像对照 |
| `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md` | 权威交接（顶部找房/宝物段落） |
| `config/mode_specs.json` | ModeSpec 权威 |
| `src/gamescript/modes/specs.py` | 加载 / `desktop_may_start` / overlay |
| `src/gamescript/modes/flows.py` | Flow 链 + `hitch_*` 只读规则 |
| `src/gamescript/runtime_status.py` | frozen RuntimeStatus 快照 |
| `desktop_app.py` | 现桌面单体（待拆 shell） |
| `fixtures/lobby_hitch_20260814/` | 短片+弹窗+特殊房金准备 |
| `fixtures/lobby_hitch_detail_20260814/` | 详片代表帧（列表→局内→回列表） |
| `fixtures/y3_screenrecord_20260814/` | y3 局内帧；**无房间列表** |
| `fixtures/treasure_must_take/` | EX 四宝实机 |
| `fixtures/ur_attr_routes/` | 三系 UR 散件 |
| `config/skill_card_catalog.json` | 220 升级卡 |
| `config/bond_stack_catalog.json` | 65 羁绊张数 |
| `config/choice_policy.json` | 负面 + must_take |
| `config/choice_lexicon.json` | OCR 别名（无 merchant） |
| `C:\Users\10639\Desktop\测试夹\hitch_find_room.py` | 找房可跑线 |
| `C:\Users\10639\Desktop\测试夹\09-找房-*.bat` | dry / live 入口 |
| `C:\Users\10639\Desktop\测试夹\hitch_templates\` | 找房模板 |
| `C:\Users\10639\Desktop\测试夹\README.md` | 测试夹说明 |
| `tests/test_mode_specs.py` | hitch 弹窗/准备标签单测 |
| Canvas `control-center-pet-atlas-plan.canvas.tsx` | 方案提到；**本仓库未检出** |

---

## 硬约束（整合时勿破）

- 不要把任何模式的 `live_enabled` 改成 true（除已是 true 的 `normal_farm` / lab CLI）。<br>
- C4：进房/建房禁止颜色兜底；蹭车禁止快速加入。<br>
- 一层提交：外壳 ≠ L0 点击 ≠ L1 拿卡。<br>
- 合成帧不得冒充实机证据。<br>
- 不确定 → fail-closed 零输入。
