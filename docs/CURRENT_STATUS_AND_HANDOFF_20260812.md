# GameScript 当前状态与下一 Agent 交接（2026-08-12）

## 2026-08-17 2c489aa 机制收口（基线 e292132，集成 13 提交；release_gate 4/4 PASS，未真机）

工作区基线 `e292132`，机制收口代码原落到 `ba19fe7`；生产/测试 tip 现为 `2c489aa`。主 agent 刚在 `2c489aa` 执行 `python tools/release_gate.py`，退出码 0，4/4 PASS。精确记录：pytest 866 passed、2 xfailed、11 skipped；frozen_replay PASS（`disconnect_modal_missing` 仍 BLOCKED，属于既有可接受观测）；scene_templates 132 ok/0 missing；contract 72 passed/1 present。本提交只是 docs-only 证据记录，不改生产或测试行为。**未真机；离线 gate 不替代真机。**

### Policy

- 空 hard skill：直接 CLOSE，不刷。
- `choice_interval` 已接线；attempt 只计真实点击。
- trace fingerprint 值缓存。
- `attr_routes` 唯一消费 chain+support。
- `cards=[]` 与显式空 scheme / missing factory 语义分立。
- legacy `attr_route` schema 已迁移。
- mode overlay：budgets → hidden_defaults 优先；未知键忽略；统一走 `Settings._from_dict(fallback=)` 保留 base。

### Infra

- `InputExecutor` 收敛 pyautogui FailSafe，standalone 异常兼容。
- clipboard 恢复失败则清空。
- PrintWindow 尺寸不符 → invalid 空帧；mss 缺失且非前台时先 PrintWindow。
- worker 未停时 `closeEvent` ignore，保留 `live.lock`。

### 已完成集成定向回归（不是 release_gate）

- Policy / L1 / C2：229 passed + 130 subtests
- Infra：81 passed

### 真机待验证

- DPI / PrintWindow 拒帧频率
- 角点 FailSafe → ActionResult
- worker 卡死关窗 / 锁
- choice interval / attempt accounting
- `cards` 空方案与 attr 路线 UI roundtrip

### Settings fallback 隔离

`Settings._from_dict(..., fallback=)` 是浅 `replace`。唯一生产 caller `RunnerService.start` 先 `copy.deepcopy` 再 overlay。新增 caller 必须先隔离可变字段。

## 2026-08-17 CORE02/CORE03 集成批次：技能严格-全才模式 + 必拿宝物 + 挑战重观察（离线接线，未实机）

工作区 HEAD `6584445` 之上，本批次完成配置、L1 策略/状态、Settings、看板与契约测试集成；未跑真机。离线验收：策略/看板定向集 `227 passed, 109 subtests passed`；`python tools/release_gate.py` 4/4 PASS（pytest 756 passed、2 xfailed、11 skipped；frozen replay PASS；templates 132/0；contract 72 passed、1 present）。

- 技能：choice_policy.json 显式 min_confidence=0.60、allow_skill_giveup=false；选卡模式运行期推导——勾选 0–4 系 → hard（严格，只选配置系展开出的合法技能卡，宁可 WAIT/隐藏也不乱拿），5–16 系 → all_round（全才，目录可识别的合法技能卡都可选，配置系仅作聚焦优先）；两种模式共用排序 = 目录合法性（never_pick/互斥）→ 前置/链路 → 存档解锁/降伤惩罚（未知存档 fail-closed）→ 稀有度 → 焦点/非焦点 → 本地习惯分 → 配置顺序 → 槽位下标；目录未识别名无点击权。owned 只取运行时面板确认的已学技能（panel 变更/关闭后确认，每局重置），保留同卡重复次数供 x2 前置计数；缺失即未知，绝不从卡名猜测。
- 宝物：treasure.must_take_names = 原 4 个 EX（ONEPIECE/至高进化/一身神装/满级大佬）+ 全都要（覆盖实测『我全都要·获得本页全部宝物』）+ 卡牌大师；与负面名单互斥保持。
- 挑战：Settings 后端 challenge_recheck_interval_s（默认 30s，钳 5–300s）周期重观察锚定开关——ON 只安排下一次观察，不永久置 ON；OFF 点击仍标签锚点、有界、变更防抖。
- 黑商：自动购买/刷新默认零输入（仅 auto_gambling_time>0 才可能放行），看板须标实验性/未实机验证；**Merchant C6 保持 failed/unverified**，不标 wired/complete。
- 色阶：user 2026-08-17 报告技能卡可出现蓝/紫/橙/粉/红且红有多档，与 2026-08-14『技能卡只有橙紫蓝白、无红粉』冲突未解决；KB/配置只标记冲突（保留既有证据行），运行期容忍未来红/粉档、不新造 HSV 阈值。

**未验证/实机缺口**：技能 all_round 模式真实选卡是否符合预期；挑战开关周期重观察的实际间隔与无抖动点击；黑商零输入真机不误点；全都要/卡牌大师 OCR 识别与特权命中；红/粉档真实存在性与多档映射。**LabVerify 待办**：13 号真机（技能选中>0、刷新不换不放弃）复核技能模式；确认黑商默认零输入；观察挑战开关周期重观察。离线 release_gate 4/4 已由主 agent 完成，不替代真机 L 结论。

## 2026-08-16 CORE-02 Infra：选关高亮亮块恢复（U，待 L）

CORE-02 worktree 基线 `6f80f016df8a4efec5c6004fc437f7b1f574dd28` 上，真实夹具 `fixtures/lab13_200601_stage_card/02_q2_stage_select_click2_t1567.0s.jpg` 复现：选中的 1-12 亮边与标签/背景合并为超长亮块，旧 `visible_stage_rows()` 直接丢弃，`selected_stage_row()` 返回 `None`，L0 因 fail-closed 不点开始。首版 `433e7ed` 宣称"前后关卡形成唯一连续缺口才恢复"，但实现里 below 缺失时仍按单个上邻合成、且允许多块各自恢复，与描述不符并可能把推断坐标送进真实点击链路；返工 `ef72f99` 收紧为：同时存在同章节上/下邻且 `below.index == above.index + 2`、亮边评分 ≥ `SELECTED_RING_RATIO`、全程只允许一个可验证候选，任何缺失/跨章节/非 +2/亮边不足/多候选歧义一律不恢复。Lab13 恢复 1-12 的正例保留，另加 6 个 fail-closed 负例（对首版实现已验证会红）。`python tools/release_gate.py` 4/4 PASS（660 passed）为 U 证据；未跑真机，L 结论交 LabVerify。

## 2026-08-15 02:25 板块 3：海盗+宝藏蓝图入库（未接线）

`haidao_chain`：藏宝图(三)/贪婪/白赚/劫掠者 need=3 已实机；UR 毁灭战舰卡面开池 N三张+重拳先生。黄金猿=装备栏左键开宝藏（user_confirmed，语音黄金元是错字）。禁止自动点装备栏。

不改 bond_stack（贪婪不是 2）。悬赏令出战舰 vs 吞 12 出战舰两说并存，开池以卡面为准。未接决策。无链路需重新真机验证。

---

## 2026-08-15 02:15 板块 3：军团/龙族/三国/修仙 EX 攻略链入库（未接线）

四条蓝图进 `juntuan_chain` / `longzu_chain` / `sanguo_chain` / `xiuxian_chain`。实机优先。未接决策。未改 bond_stack / 实验室白名单。

实机钉住：巨龙军团开龙族池；修仙(0/3) 神秘戒指每秒敏+0.2 → 练气期；萨格拉斯灭世斩破甲2%且不拆军团池；吞食天地每400杀随机吞；大乘期拆修仙池。技能卡没有 EX 档，衍生卡是前置齐了才能在 G 里刷。

不改：不写 27/3虚空、祈求10、每营8、渡劫50%。小绿瓶仍是宝物。神秘戒指 D0 宝物标签以 t=198 羁绊为准。迦拉客隆=迦拉克隆。无链路需重新真机验证。

---

## 2026-08-15 01:30 板块 3：封神/亡灵/神兽/异火 EX 攻略链入库（未接线）

抖音+KK 攻略补进 `fengshen_chain` / `wangling_chain` / `shenshou_chain` / `yihuo_fenjue_pool.guide`。实机优先，冲突单列。未接决策。未改 bond_stack / 实验室白名单。

实机钉住：异兽蛋 60 秒后自吞开神兽池（OCR）；亡灵天灾 need=3；兵主冰霜符文技能伤害×1.25；圣人/祖龙/帝炎卡面。

不改：不写封神榜 6/9、残骸 100、符文 10、64 绿、异火 22。英雄卡巫妖进词典但 set_membership=null，不与克尔苏加德/巫妖王互设别名。焚决=焚诀错字。无链路需重新真机验证。

---

## 2026-08-15 02:10 板块 7：13 号 013800 日志结论（不抽帧）

trace：`%LocalAppData%\ShuaBao\20260815\trace_lab_20260815_013800.jsonl`。两局 / 27 分钟。

- **OCR + 零放弃：过。** 有中文卡名，技能选中 > 0（箭矢齐射/奥术箭矢/爆炸箭矢/剑气），`giveUp` = 0，定类是 skill。
- **刀刀/大圣没拿：不是策略没跑。** 看板 `advanced_packs=[]`，`cards` 只有祝福/成长/贪婪/体术/陷阵/智力/湮灭者。OCR 见过刀刀/齐天大圣/封神，同屏有基础卡就点基础卡（t992 体术压过刀刀+大圣），否则刷新掉。
- **刷新：羁绊会换牌（84 点 / 59 变）；技能 54 点全不变**，再 `skill_hide` 54。用户看不见技能刷新是真的。见 `测试夹\错误归档\E07_*.md`。
- 15 / 16 未跑。下一把 13 必须先在看板勾刀刀/大圣/封神并保存，启动行要对上 `cards`。

---

## 2026-08-15 01:25 板块 7：Infra 已交，测试夹已整理，13 未复验

InfraB `infra-layering` 两刀已落地、单测绿、真机还没跑：`deef986`（OCR 不再整局致盲）+ `6b89a50`（空名/指纹不变禁止放弃）。工单：`GameScript-InfraB\docs\handoff_20260814\07_TICKET_plate5_after_ocr_giveup.md`。

测试夹根目录只留准备测的 13 / 15 / 16。通过的进 `已完成\`（含 03c、14 验 B）。08/10/03 进 `以后\`。09/11 进 `其他线\`。核实过的事故写成 `错误归档\E01–E06`（G 判宝物、OCR 致盲放弃、UAC 丢窗、选关点偏、长测进化 0、刷新不换仍放弃）。

本会话未开 13/15/16。没看到失败 ≠ 通过。看板 LIVE 不要和 lab 同时开。

---

## 2026-08-15 01:12 板块 4：TAB 只认进图默认盘

user 更正：刚入局的 TAB 不会变，那是存档装备堆叠后的进图默认数值，不是打一半升级/拿卡后的盘。一进图就抓，不要游戏中途抓。

- `classify_tab_window`：`entry` 才进海报七格；`mid_run` / `unknown` 保持未采集。
- 现有 `fixtures/player_profile_20260814/ingame_tab_panel.png` 是中途帧，急速 49.7% 不当本号默认。
- 采集器仍不代按 TAB。人一进图按开，立刻跑 `11-画像*.bat`。
- 看板稿已改：七格现全是未采集。未碰 mediator。

---

## 2026-08-15 00:57 板块 3：刀刀/大圣攻略链入库（未接线）

抖音（无胆超人、在家零四一）+ KK 社区补进 `daodao_chain.guide` / `dasheng_chain` + lexicon。实机优先，冲突单列。

已改名：刀刀小城→小成；三元重疾→三元重戟（t=765 已有帧）；`/蓝`=`岚`，`/中烟`=`终焉`，斜杠不采。天命人从齐天大圣别名拆成散件。

不改：实验室白名单不加图纸/残躯（防狂刷）；bond_stack 不写残躯 need=6；法天象地 `set_membership` 仍是神通；不自动键入切形态。无链路需重新真机验证。

---

## 2026-08-15 板块 5：OCR 熔断致盲 + 技能空名禁止放弃（已修）

先在 InfraB 落地：`deef986`（感知）+ `6b89a50`（L1），同一套行为已同步进本工作区。

- OCR：spawn 失败打日志；熔断不整局致盲；InfraB 没有 `.venv-ocr` 时用 Local 的解释器。
- 技能：三槽无名或刷新指纹不变 → 不得 GIVEUP / 不得点放弃。实验室默认隐藏。
- 真机只跑 **13 号**。入口：`测试夹\板块5-真机入口.txt`。14 已归档。
- 未改看板 / 选关 / 词典 / EX 白名单。

---

## 2026-08-15 00:50 板块 4：画像绑定流（仍零点击）

user 拍板：要跑绑定才采；进游戏点顶栏「存档」，第一次登录入库 **装备战力 + 强化等级 + 技能等级**；TAB 属性后补合成海报。不选就不抓。

- 解析：`parse_equipment` / `build_first_login` / `build_poster`。战力/强化无标签且无 ROI → missing，不从背包数字猜。
- `--bind` 才写 `first_login_*.json`。采集器仍不代点存档（旁边是退出游戏）。
- 真机帧已入 `fixtures/player_profile_20260814/`：装备 12295/630，技能 奥术箭47 爆炎箭9 剑气13。
- 入口：`测试夹\11-画像绑定.bat`。未碰 mediator。P2 海报看板未做。

---

## 2026-08-14 23:55 板块 1：关卡表 + 基础/高级卡组（只动外壳+策略目录）

控制室现在可以选当前全部主线关，并勾基础卡组 / 属性线 / 刀刀·异火·大圣。

- 关卡：主线1 共 23 关、主线2 共 7 关、主线3 共 9 关、主线4 到 4-3。超出范围 collect 失败。`1-10`→stage1/stage2=10 quirk 未改。
- 基础技能库：16 系点选 / 再点取消（最多 4），默认展开。
- 基础卡组已写入 `official_strategy_defaults.json` → `card_packs.basic`（祝福/成长/经济/贪婪/挑战/提速/体术/固守/陷阵/急速），看板可全选/反选。
- 智力 / 力量 / 敏捷收成一行「属性线」，不展开链上各环；白名单只带门卡+UR。
- 高级卡组可选：刀刀 / 异火 / 大圣。EX（解放的圣剑 / 帝炎 / 法天象地）不进白名单。
- 生效 `settings.cards` = 基础勾选 − 反选 + 属性线 + 已开高级卡组。不再只写 6 个短码。

未改 mediator / choice_policy / live_enabled。保存后测试夹 bat 仍读同一份 `user_settings.json`。

---

## 2026-08-14 23:52 板块 3：技能卡无红色 + 拿卡逻辑对照源码

user：技能升级卡只有橙、紫、蓝、白，没有红。已入库 `card_pool_rules.skill_card_colors`；`skill_card_rarity.rarity_names` 去掉粉/红。未改 `quality_order` / HSV / mediator（B1 再动 L1）。

长测「红巨型剑气」按橙边被采成 red、再因 conf 0.575&lt;0.60 跳过理解，不是游戏有红技能卡。绿边是宝物。

对照源码后 `partially_wired` 只留 G 优先于 F。白/绿先刷、目录压 OCR 源码没有；审判排斥只在 catalog 函数，mediator 没调。必拿宝物名单、羁绊差 1 张，策略有、接线空。拿卡逻辑见索引 §1.3b。无链路需重新真机验证。

---

## 2026-08-14 23:50 板块 5：234206 技能全放弃 — OCR 致盲，不是 KB

录屏 `20260814_234206.mp4` / trace `trace_lab_20260814_234214.jsonl`。定类已是 skill。OCR 先 `spawn` 后整局 `disabled`，**零卡名**。策略等 5 帧 → 刷 3 次 → 放弃（5 次放弃、16 次刷新、0 选中）。同晚 231455 OCR 活着，会选箭矢齐射/剑气/爆炸箭矢。

**已修（2026-08-15）**：见文首板块 5 条。再跑 13 号真机验。**不是 KB**。

---

## 2026-08-14 23:50 板块 1：测试脚本读看板保存（已接线）

控制室勾技能/关卡/英雄模式 → 保存 → 测试夹 bat 读同一份 `%LOCALAPPDATA%\ShuaBao\user_settings.json`。

**谁说了算**
- 看板：`skills` / `cards` / `stage_targets` / `auto_reputation` / 声望 / `cycle_num`（仅当 bat 没传 `--games`）
- bat / CLI：`--preset --hours --games`。只有显式 `--stage / --route / --build / --skill-family` 才覆盖看板
- 禁止再强制「实验室一律非英雄」
- 没有看板文件必须退出码 2，禁止偷偷用 `default_settings.json`

**已改**
- Local + InfraB 各一份 `tools/lab_run.py`：`resolve_lab_config` / `apply_lab_preset` 不再改 `auto_reputation`
- `测试夹\13-长测-大圣刀刀封神-技能黑商进化.bat`：去掉 `--config` 和 `--stage 1-12`，改为 `--preset catalogs --hours 2 --games 4`，仍跑 InfraB
- 控制室运行板块加提示 +「保存设置」按钮（自动保存约 1 秒仍在）
- 桌面入口：`刷刷宝控制室.bat`（启动 Local `desktop_app.py`）
- 单测：`tests/test_lab_reads_dashboard.py` + 看板保存用例

**13 号以后怎么开**
1. 双击桌面「刷刷宝控制室」，勾好技能/关卡/英雄模式/羁绊，等自动保存或点「保存设置」（本机若还没有 `user_settings.json`，必须先走这一步）
2. 关掉看板 LIVE（不要和 lab 抢 `ShuaBao.live.lock`）
3. 双击 `测试夹\13-长测-大圣刀刀封神-技能黑商进化.bat`
4. 开跑 stdout 第一行应是 `config=看板 ... 关卡=... 英雄模式=开/关 skills=... cards=...`，对照看板

13 号对照卡组（必须来自看板勾选，没有写死进 lab_run）：奥术箭流 `asj/asjg/assx/jq`；刀刀链+齐天大圣+封神散件+木头；要非英雄就在看板把关卡难度设成「普通」。EX 只作 catalogs 退局默认名，不进白名单。

工单：[`docs/handoff_20260814/01_TICKET_lab_reads_dashboard.md`](handoff_20260814/01_TICKET_lab_reads_dashboard.md)。板块 7 用「先看板保存、再双击 13 号」复验。

---

## 2026-08-14 22:40 板块 7：13 号抽帧已回证，选关/选卡脚本已修（待真机复验）

夹具：`fixtures/lab13_200601_stage_card/`。13 号 bat 跑的是 **InfraB**（Local `SlotCandidate` 无 `set_name`）。

抽帧事实：三轮进局 HUD 都是 1-12；G 三选是爆炸箭矢(金)/攻速提升(绿)/闪电链(金)，有技能点，刷新不换牌；tick9 是 G 弹窗被判成 `treasure_lock`；羁绊三次点的是底栏 V，没有居中三选；195723 丢窗是管理员 CMD 抢焦点。

根因不是「旧选关/抽卡没测过」，而是 13 号只换了 bat/probe/1-12/catalogs，**没把定类守卫接到这条链路**：

- `_panel_kind_of` 把「画面强证据」放在主动按 G 之上。金卡三选 HSV 花屏 ≥60000 → 判宝物；`treasure_lock` 单独命中也直接宝物。catalogs 长开 G，OCR 用宝物槽位 → 全 `disabled` → 空刷 227。
- Local 选关还停在「同名+相邻+开始按钮」间接放行；InfraB 已有 `selected_stage_row()` 高亮确认（所以 13 号第一次点到 1-10 后会再点，最终进了 1-12）。这次把高亮确认迁回 Local。

已改（Local + InfraB）：主动按 G/F/V 优先于锁模板/HSV；`treasure_lock` 单独命中不再定宝物；Local 选关无高亮不开局。13 号 bat 开跑前把游戏拉回前台。

**下一件真机事**：再跑 13 号，盯技能选中 >0、treasure OCR 不再盖过 G、选关第一次高亮就是 1-12。

---

## 2026-08-14 20:05 板块 3/7：174547 拆解表入库 KB（分层，无第七表）

图鉴名已在。KB 补了机制与 OCR 词条：

- 已上帧 4 张 N 按 `evidence_ocr.json` 校正：风怒=火/风+4%；幽冥=燃烧+10%+双暴+毒火 3s；玄黄=敏+100/护甲+3/火+5%；阴阳双炎补三围与每秒攻击。早前「物/魔+4%」是误读。
- 拆解表 06–13 八张（陨落心炎…骨灵冷火）写入 `breakdown_scan_unverified`，**不得升格实机**（无 OCR/精选帧，且与黄阶只开 N 冲突）。
- 恐鳌戒指：`kongao_ring` + lexicon（生命之球/守护指环）。need 未测。
- 同局神器/宝物/专属见 `live_174547_sidecars`（INDEX 描述，无 OCR）。

未接决策。JPG 仍未进仓。

---

## 2026-08-14 19:58 板块 2：异火/刀刀图鉴补 join（无新表）

174547 名与词条板块 7 已入库。本步只补投影：

- EX 11 张图标 ← `fixtures/ex_finals_20260814/`（盘上有 PNG）
- 刀刀链路 ← KB `daodao_chain`：三件套 → 萌新 → 大成 → 解放的圣剑
- 异火链路 ← KB `yihuo_fenjue_pool`：黄阶 → 玄阶 → 帝炎；散件=已上帧四张 N
- `cannot_devour` 旗标 ← `ex_capstones`

**不写：** 拆解报告里陨落心炎等 06–13 的「专属技能」列（与 lexicon 攻略词条冲突，无独立帧）；`异火(168)` 当 need；恐鳌戒指/生命之球/守护指环/贪欲钥匙（词典尚无规范名）。174547 的 60 张 JPG **未进仓**（只有 INDEX/OCR），图标路径保持空，文件落地后会自动亮。

---

## 2026-08-14 19:52 板块 3：异火/刀刀/EX 对机制库的咬合（只改知识库）

板块 7 已入库卡名与链。本条只补机制交叉，未接 `choice_policy`。

- 卡池门控不只技能前置：焚诀阶位开异火池（黄阶=N 已实机）；刀刀萌新开刀刀池；EX 可能拆本套卡池。
- 吞噬分几种：集齐自动（刀刀三件套）、击杀随机吞（焚诀每 200）、累计 3 张进化、圣剑掷骰。底栏 `异火(n)` 不是 need。
- 大成 CD/触发/多段 咬合官方 CDR 80%、主技能触发、剑气/龙卷风每段都算——估值未接。
- 帝炎燃烧 vs 官方燃烧状态、圣剑无视闪避 vs 闪避覆盖真伤：冲突未测，不猜。
- 圣剑切形态聊天指令已进 `script_forbidden`（与 `-zs` 同类）。法天象地不是大圣。

索引：[`docs/research/GAME_LOGIC_LIBRARY_INDEX_20260814.md`](research/GAME_LOGIC_LIBRARY_INDEX_20260814.md) §1.2。

---

## 2026-08-14 19:45 板块 7：下一轮长测入口

双击 `测试夹\13-长测-大圣刀刀封神-技能黑商进化.bat`。InfraB + catalogs + `lab_dasheng_probe.json`。**1-12 非英雄**，`--hours 2 --games 4`。本局退出只认 F 三选点到已知 EX 名（解放的圣剑/圣人/帝炎/祖龙等）；EX 是合成出来的，不进白名单猎取，也不再 12 分钟提前走。进化面板无卡名 OCR，合成后若没在 F 露面就打完 1-12。大圣 EX 名未确认（法天象地是神通）。白名单仍是刀刀链 / 齐天大圣 / 封神散件 + 木头。停看板、录屏。

---

## 2026-08-14 19:30 板块 7：各套最终形态入库（用户卡面）

11 张 tooltip：`fixtures/ex_finals_20260814/`。海盗无 EX=UR **毁灭战舰**；其余 EX。全部**无法吞噬**。词典 + KB `ex_capstones` + 图鉴 join。

| 套装 | 最终形态 | 获取时额外 |
|---|---|---|
| 封神 | 圣人 EX | 移除法宝卡组 |
| 神兽 | 祖龙 EX | 移除神兽卡组 |
| 龙族 | 世界末日迦拉克隆 EX | 兼标签迦拉克隆 |
| 三国 | 吞食天地 EX | 每400杀随机吞1张，每吞全属性增幅+1% |
| 异火 | 帝炎 EX | 覆盖早前用户表 UR；异火榜第一 |
| 刀刀 | 解放的圣剑 EX | 移除刀刀卡组+掷骰吞噬；聊天切永恒/岚/终焉，**禁止自动键入** |
| 军团 | 萨格拉斯 EX | 按军团卡数量缩放 |
| 亡灵 | 兵主 EX | 三符文 |
| 修仙 | 大乘期 EX | 移除修仙卡组 |
| 神通 | 法天象地 EX | **不是**大圣 |
| 海盗 | 毁灭战舰 UR | 开利刃/战斗/冲浪海盗+重拳先生 |

未接决策。不要把这些名塞进 12 号硬白名单。

---

## 2026-08-14 19:25 板块 7：刀刀基础链入库（证据 **R**）

174547：幽灵系带 / 护腕 / 空灵挂坠 → 刀刀萌新 → UR 刀刀大成。已写入 lexicon `_note`、KB `card_pool_rules.daodao_chain`、`atlas_view` join `set_membership=刀刀`。need=3 不变。萌新/大成不另写 need。

大成四条：CD-20%（龙卷风暴/极寒等）、触发+50%（连环闪电/重击等）、吞其余刀刀出 UR 图纸、提升普攻与技能多段触发。帧：`fixtures/cards_174547_evidence/` 02–05、11。

**未齐：** 已吞噬面板还有更多刀刀角标件（高阶 tooltip 未采）；大圣未齐。提示词 02 / 03 / 07 已改。

---

## 2026-08-14 19:20 板块 7：异火 23 名入库（黄阶实机 + 用户表分层）

174547 只刷出 N 级异火，是因为当时停在 **焚诀·黄阶**（效果3：只把 N 级异火加入卡池）。玄/地/天阶未上帧。

已写入：lexicon 23 名 + 焚诀四阶（`set_membership=异火`）；KB `card_pool_rules.yihuo_fenjue_pool`；`atlas_view` join 异火套装件。图鉴馆提示词 `02_AGENT_ATLAS.md`、逻辑库提示词 `03_AGENT_GAME_LOGIC_KB.md` 已同步。

| 层 | 内容 |
|---|---|
| 实机 | 黄阶；阴阳双炎/风怒龙炎/幽冥毒火/玄黄炎（tooltip 榜 21/18/20/23） |
| 用户图鉴、未上帧 | 其余 19 张 + 玄/地/天阶。标签=攻略，不得标实机 |
| 冲突 | 用户表 No.17–21 与实机榜名不一致，**以 tooltip 为准** |
| 不写 | `异火(168)` 当 need；刀刀/大圣当已完成 |

刀刀 / 大圣还要补测，本条只收异火。

---

## 2026-08-14 19:10 板块 7：174547 异火/刀刀入库（证据 **R**）

拆解报告与 11 帧已在仓：`docs/cards_breakdown_20260814_174547.md` + `fixtures/cards_174547_evidence/`（视频 `录屏素材/20260814_174547.mp4` 0–850s）。本条只入库，不新开第七份表。

| 事实 | 写进哪 | 刻意不写 |
|---|---|---|
| 刀刀 need=3（F `刀刀(0/3)` + 三件套） | `bond_stack_catalog.needs.刀刀`；从 `unknown` 拿掉 | 刀刀萌新/刀刀大成 无独立 `(x/y)`，不另写 need |
| 幽灵系带 / 护腕 / 空灵挂坠 → 刀刀萌新 → UR 刀刀大成 | `choice_lexicon` 规范名 + `set_membership=刀刀` + `_note` 基础词条 | 个人面板括号加成 |
| 焚诀·黄阶开异火池；阴阳双炎/风怒龙炎/幽冥毒火/玄黄炎 | 词典 `set_membership=异火` | 焚诀·玄阶/地阶仅黄阶 tooltip，无独立帧 |
| 底栏 `异火 (168)` | 词典注：吞噬计数 | **不是** stack need=168 |

12 号 probe 已叠 `刀刀萌新/刀刀大成/幽灵系带/焚诀·黄阶/异火`。词典已同步 InfraB。停 12 再开才能吃到。Atlas（板块 2）只拼接，不必另开会话。

---

## 2026-08-14 18:11 板块 3：黑商免费刷新 120→180 秒

user 更正：黑商店铺免费刷新是 **180 秒** 一次，前记 120 作废。已改 `refresh_ledgers.kinds.black_merchant.free.interval_sec=180`。未接线、未改点击。

---

## 2026-08-14 17:45 板块 7：刀刀/齐天大圣刷出却刷新（**L** 截图）

user 两帧：F 已出 `刀刀(0/3) 幽灵系带`、`齐天大圣(0/3) 天命人`，旁边还有祝福，脚本点刷新。

根因：硬白名单只认「祝福/大圣/刀刀」字面；OCR 规范名是「敏捷祝福/幽灵系带/齐天大圣」。夹具 `fixtures/bond_daodao_20260814/f_panel_*.png`。

已改：词典套装归属（祝福变体→祝福，幽灵系带→刀刀，齐天大圣+天命人）；`lab_dasheng_probe.json` 卡序改为 刀刀/齐天大圣 优先，并加上 成长/经济/挑战。12 号跑 InfraB，词典已同步。停 12 再开才能吃到。

---

## 2026-08-14 17:35 板块 7：12 号采证回读 + 建房下载连点（**L** + 已改 L0）

`12-羁绊-大圣采证.bat` 今晚两段 trace（跑的是 InfraB）：

| 段 | 结论 | 证据 |
|---|---|---|
| `172330` | 建房 **不过** | L2/L7/L12 三次 `CreateRoom-open`，t+16.7 `create dialog confirmation timeout`。旧逻辑：点成功后 4s 不见弹窗就再点，总预算 15s / 最多 3 下 |
| `172452` | 建房过；开局狂刷是算法 | 1 次 open + confirm + RoomStart；进局后 `bond刷新选择`×16。在找白名单：刀刀 / 大圣* / 棍法 / 身法 / 成长（硬白名单，对不上就刷，实验室上限 20） |

已改（L0，Local + InfraB）：点成功后 **不再连点**，零输入等弹窗，截止延到 90s（下载地图）。`tests/test_p0a_create_room_gate.py` 新用例绿。无「下载中」模板，靠「点成功→停手等」覆盖。

狂刷 **不是找房列表刷新**，是 F 面板硬白名单。刀刀几乎不会以「刀刀」三选出现——已吞噬套装角标 ≠ F 卡名。不必再补录屏解释本条。

下一件：停掉当前 12 → 再开一次 12（吃到 InfraB 新 L0）。若仍要采刀刀词条，请悬停已吞噬 tooltip，不要指望 F 狂刷刷出「刀刀」。

---

## 2026-08-14 16:45 板块 7：刀刀词库补录（证据 **R**）

用户「已吞噬」截图确认：**刀刀 = 套装角标名**（套内每件都标「刀刀」），不是单卡专名。同屏旁证法宝/异火/封神等。

- 夹具：`fixtures/bond_daodao_20260814/`（`source_yishitun_panel.png` + README/INDEX）
- 词库：`choice_lexicon` 已加 `刀刀`、`法宝`；`bond_stack_catalog.unknown` 挂上（**need/效果/公式均未测**）
- 属性：个人面板含局外加成 → 采证只认**悬停基础词条**；本帧无 tooltip，**不许编效果**
- 临时测：`测试夹\lab_dasheng_probe.json` 的 `cards` 已叠中文 `"刀刀"`；仍不传 `--route`、不设 exit
- 下一采证：悬停橙/紫/蓝刀刀件各 ≥1，截 tooltip 原文 + 若 F 面板出现 `刀刀(x/y)` 再写 need

仍阻塞：`GameScript-Local\tools\lab_run.py` 缺失（InfraB 有）→ 板块 5。

---

## 2026-08-14 16:40 板块 7：134529 轮转拆解回传判定（证据等级 **R**，非 10 号 bat 的 L）

素材：`录屏素材/20260814_134529.mp4` + `trace_lab_20260814_134654_strength` / `135944_agility`。夹具：`fixtures/lab_verify_20260814_134529_ring/`（拆解员 INDEX 文件名与落盘不一致；检验官已从 `C:\tmp\lab_verify_20260814_134529` 补拷 focus/ 共 173 帧）。**未触发≠通过。本段不是 `10-长测-*.bat` 正式 L。**

| 判据 | 结论 | 证据 |
|---|---|---|
| C1 羁绊后转 V | **过** | strength L214→L218 开宝物；帧 `e_t0191.82_L0218_q1.jpg` |
| C2 转入进化/黑商环 | **不过**（黑商有、进化无） | 环内有 Z/黑商；底栏「点击进化」常亮但**从未点击**，亦无「本轮进化无事可做」类日志 |
| C3 Z 在环内 | **过** | 环1 L646 Pickup-Z；环2 L1323 |
| C4 EX 四宝必拿 | **未触发** | 全程宝物三选未出 ONEPIECE/至高进化/一身神装/满级大佬 |
| C5 负面 ban | **过** | L218 第3槽「等级优势」；L220 选「战意增加」，未点负面 |
| C6 黑商只买木/丹 | **不过** | L647/L972 只 refresh 未乱买（好）；L1324 `BlackMerchant-swallow_pill` 点空槽 `[1549,746]`，丹未买成 |

顺带：agility 羁绊连续 refresh×56（烧木头）——**板块 3**；进化 0 点击 / 黑商丹空槽误点——**板块 5**（既有 D2 + 新开黑商货位定位）。

阻塞下一测：`GameScript-Local\tools\lab_run.py` **缺失**（`GameScript-InfraB\tools\lab_run.py` 仍在）。**归属板块 5** 恢复后再开 10 / 12。

大圣/刀刀：已在 `测试夹\lab_dasheng_probe.json` + `12-羁绊-大圣采证.bat` 放临时采证入口（**不传 --route**；cards 含 dasheng*）。**刀刀全库零命中，规范名未确认前不许塞进白名单。** 请用户回「刀刀」游戏内全名后再加第二份 probe。

下一件真机事：①板块5恢复 `lab_run.py` → ②双击 `10-长测-技能羁绊宝物进化黑商.bat` 拿正式 **L** → ③并行可开 `12-羁绊-大圣采证.bat`（录屏）。

---

## 2026-08-14 15:40 板块 3：刷新必须分账本（只改知识库）

先前索引把「刷新」写成一律花杀敌数，是错的。user 纠正：

- **羁绊刷新**扣木头（开 F 抽卡也扣木头，是另一笔）。
- **黑商刷新**（刷店铺，不是刷英雄卡）扣杀敌；**每 180 秒免费 1 次**。
- **宝物 / 技能 / 英雄卡刷新**不花杀敌或木头，只靠宝物效果词条或局外效果卡的次数（一入局能看见；多半是充值/抽奖/前置装备）。「黑商刷英雄卡」是误粘，已删。

已写入 `config/game_mechanics_kb.json` → `refresh_ledgers`。官方 7 页「杀敌数刷新英雄/宝物/技能」原文留在 `resources.kill_count.official_text`。未改 choice_policy / mediator。`DEFAULT_MAX_REFRESHES=3` 仍是脚本策略，不是游戏规则。白/绿先刷可能在烧词条次数——改接线另立项，不和 B1 混。

---

## 2026-08-14 15:35 板块 1：控制中心 P0 已落地（只动外壳）

- 新包 `src/gamescript/shell/`：`mode_catalog` / `runner_service` / `runtime_status` / `main_window`。`desktop_app.py` 瘦身为入口并再导出，`tests/test_desktop_app.py` 仍从 `desktop_app` import。
- 左栏六个 ModeSpec（id 对齐 `config/mode_specs.json` 的 `normal_farm`，不是方案文 `solo_farm`）。只有 `normal_farm` 可启动；跟车/赌木/站团本/蹭车主按钮「待验证 · 不可启动」；实验室只读 CLI 说明。
- `RunnerService.start` 是唯一 LIVE 入口，内部 `desktop_may_start()`。未验证方式零 Mediator、零输入。托盘只有「打开控制中心 / 停止 / 退出」，没有未验证启动项。
- 底栏钉死：摘要 + 预检灯 + 开始/停止。用词「运行方式」≠「关卡难度」。
- 用户设置写 `%LOCALAPPDATA%/ShuaBao/user_settings.json`（测试可注入 `app_data`）；仓库 `default_settings.json` 只当出厂默认。`collect_settings_from_ui` 返回深拷贝；`1-10`→`stage1/stage2=10` quirk 未改。
- 四大设置板块（`normal_farm` 右栏）：技能（常用搭配 + 自定义组合 + 16 格存档等级）/ 羁绊（四轮方案 + 反选 + 三线 UR）/ 宝物与资源（EX 四宝只读「策略必拿」、负面 opt-in、赌木待接线、龙珠待验证、木材阈值置灰）/ 运行（关卡、关卡难度、局数、学习模式、秘境）。
- 已拍板文案：蹭车只认准备/已准备/取消准备、无锁定按钮、只露 3/4 前缀、精确关卡灰化「后续拓展」、F1=切自身英雄、F2=回基地。`hitch_reject_list` 编辑器未露出。
- **未改**任何 `live_enabled`、mediator / scenes.json / choice_policy 判定。未做宠物（P1）、图鉴 UI（P2）。print hook 只转发日志，不再抠 phase。
- 关闭窗口走 `stop()` + 等待，不用 `terminate()`。预留 `ShuaBao.live.lock`。
- 单测：`tests/test_desktop_app.py` + `tests/test_shell_progress.py`。
- 真机：自己刷图启动路径需要重新点一次确认（底栏 + 学习/真机确认框仍在）。跟车等不可启动，无需真机。

---

## 2026-08-14 15:25 板块 2 第 1 步：AtlasView 数据层（只读 join，无 UI）

- 新增 `src/gamescript/atlas_view.py`：运行时 join lexicon / catalog / meta / archive / rarity / bond_stack / fetter / official_strategy / policy，**没有** `atlas.json`。
- 一致性闸 `tests/test_atlas_view.py`：技能规范名 ⊆ lexicon∪catalog；负面名 = `choice_policy.treasure.negative_names`；属性链名字都能词典解析。
- 搜「极速」落到「急速」；「湮灭者」带智力链 + `fixtures/ur_attr_routes/` 三件套路径。
- `apply_to_run` 单向出口：升级卡名进不了 `settings.skills`；运行中全拒；无短码羁绊不能勾。
- 黑商页数据是空态 + 待补清单，不编货品。空说明显示「待补」，不编数值。
- 第 2 步（图鉴 UI / 应用到本局按钮 / `ATLAS_GAPS_AUTO.md`）等板块 1 shell P0 合入后再做。`shell/` 未齐，数据层先放在 `gamescript/atlas_view.py`。
- 未改 mediator / scenes.json / choice_policy 判定。无新的真机验证项。

---

## 2026-08-14 15:20 板块 3：F4 / 压力转移解禁（只改知识库，未接线）

user 拍板：这两条**分情况，不是永远禁止**。

- **压力转移**：跟车 / 蹭车**一进游戏就点**。自己开房 / 独狼 / 当 1P 仍禁止误点。
- **F4**：打不过场上挑战怪就按（主线/资源/压过来的怪都算）。还打得过时禁止误按。「打不过」判定未钉，不猜阈值。
- **`-zs` 仍绝对禁止。**

已写入 `config/game_mechanics_kb.json` → `script_situational`（从 `script_forbidden` 移出）。总索引 [`docs/research/GAME_LOGIC_LIBRARY_INDEX_20260814.md`](research/GAME_LOGIC_LIBRARY_INDEX_20260814.md) §1.9。`wired_to_decision` 仍 false。未改 mediator / choice_policy / `lobby_hitch.live_enabled`。无链路需重新真机验证。

接线另立项：压力转移走蹭车局内阶段；F4 走挑战失败恢复。都不和拿卡 B1 混提交。

---

## 2026-08-15 00:50 板块 4：画像绑定流（仍零点击）

user 拍板：要跑绑定才采；进游戏点顶栏「存档」，第一次登录入库 **装备战力 + 强化等级 + 技能等级**；TAB 属性后补合成海报。不选就不抓。

- 解析：`parse_equipment` / `build_first_login` / `build_poster`。战力/强化无标签且无 ROI → missing，不从背包数字猜。
- `--bind` 才写 `first_login_*.json`。采集器仍不代点存档（旁边是退出游戏）。
- 真机帧已入 `fixtures/player_profile_20260814/`（聊天压缩 1024x595）：装备 12295/630，技能 奥术箭47 爆炎箭9 剑气13。
- 入口：`测试夹\11-画像绑定.bat`。未碰 mediator。P2 海报看板未做。

---

## 2026-08-14 15:20 板块 4-P0：玩家画像采集器（只读，未进主循环）

新模块 `src/gamescript/player_profile.py` + `tools/profile_scan.py`。截图→OCR→`%LocalAppData%/ShuaBao/profile/`。零点击、零按键，不写 Settings、不写仓库 config。

- 技能：OCR 16 系等级徽标；conf 低 = unverified；>50 丢弃。
- TAB 属性：力/敏/智/攻速/暴击/技能急速/掉宝率等；攻速>1000% 或急速>80% 当 OCR 错丢弃。
- 真机入口：`测试夹\11-画像采集-只识别.bat`（人先停在存档技能总览或已打开 TAB）。占 `ShuaBao.live.lock`，与 08/09/10/看板 LIVE 互斥。
- 夹具约定：`fixtures/player_profile_20260814/`。整屏真机帧还没有，禁止合成。本号对照：奥术箭 47 / 爆炎箭 8 / 剑气 13。
- 未做 P1 建议引擎、P2 看板。未碰 mediator。

真机还没跑 11.bat。跑完把 profile 目录里的 PNG 拷进夹具再验收。

---

## 2026-08-12 外壳：Dry-run → 学习模式（观察记录 + 本机自适应入口）

- 层：外壳为主 + 习惯观测 API + L0 学习模式创房节流（未改大厅红线 / 真机创房确认门闩）
- 分支：`cursor/learning-mode-replace-dry-run-bb96` → PR #5；版本 **V0.3**（桌面目录 `ShuaBao-V0.3`）
- **根因**：V0.2 建了「安全测试」勾选框但**未 `addWidget` 进布局**，看板看不见；`default_settings.dry_run=true` 静默假点击 → 创房永远等不到弹窗
- 看板：首页运行区、「秘境」上方显示「学习模式（只观察记录，不实操）」；底层字段仍是 `settings.dry_run`
- 默认：**关闭**（真机实操）；开启后零真实输入，观测写入 `%LocalAppData%\ShuaBao\learning\observations_YYYYMMDD.jsonl`
- `habit_preference`：路径改 `ShuaBao`；新增 `append_learning_observation` / `observations_to_name_scores`（聚合后可进 name_scores，决策接线另开）
- L0：学习模式下创建房间只记 `LEARN_OBSERVE`，不进 pending 弹窗等待、不烧 attempts/deadline
- **云端改完不会自动出现在桌面包**；本机仓库根执行：
  `powershell -ExecutionPolicy Bypass -File .\sync_to_desktop.ps1 -SkipGate`
  （或 `build_release.ps1`）。验收：窗口标题 **V0.3**，运行区有「学习模式」勾选

---

## 2026-08-12 基建线：习惯权重 / 许可 stub / 批量抽帧 / 预设契约

- 层：感知/策略纯函数/工具（**未改** mediator LIVE 采集习惯；**未接** 许可进启动；未改大厅红线）
- `src/gamescript/habit_preference.py` + `PolicySettings.habit_name_scores`：允许集内 tie-break；空习惯行为与旧版一致
- `src/gamescript/licensing.py`：租约 fail-closed stub（机器码/到期/宽限期）
- `tools/video_breakdown.py`：支持 `--batch-dir`；已抽 `录屏素材/20260812_*.mp4` → `C:\tmp\frame_candidates_20260812\`
- 测试：`tests/test_skill_meta_presets.py`、`test_habit_preference.py`、`test_licensing_stub.py`；负面 pattern 契约收紧为仅「贪婪献祭/等级优势」靠名字
- `DEFAULT_NEGATIVE_PATTERNS` 与 JSON 对齐（消耗全部金币/将恒定/杀敌数清0/宝物效果-）

---

## 2026-08-12 调研线：外部补挖 + 双权重 + 防泄露规划

- 层：感知/素材/规划（未改 mediator / 大厅红线；未改 GATE 基线）
- 文档：`docs/research/EXTERNAL_DIG_SUPPLEMENT_20260812.md`、`SCRIPTABLE_LOGIC_MAP_20260812.md`、`MATERIAL_GAP_AND_FRAME_PLAN_20260812.md`、`DISTRIBUTION_AND_IP_PLAN_20260812.md`
- 改造：`config/skill_meta.json` 官方流派预设扩充；`config/choice_policy.json` 负面描述候选 4 条；`config/habit_preference.schema.json`（本地习惯权重、免订阅，尚未接线）
- 产品拍板：习惯权重本地免订阅；官方权重随包；许可先家庭电脑再 VPS；核心链路日后 Nuitka/原生加固（对标参考项目）
- **仍缺真机**：断线全屏、OCR blind `entries=0`、黑市全屏、4/5 选；优先吃 `录屏素材/2026081*.mp4` 再下 B 站
- 相关单测：`test_choice_policy` / `test_choice_lexicon` / choice semantics / treasure_negative / `test_desktop_app` 已过
- 面板重构 agent：可直接用 `skill_meta.presets` + habit schema；不要与本线抢 mediator

---

## 2026-08-12 L0：录屏 180825 拆解升级（六阵营几何校准）

- 素材：`fixtures/hero_modal_20260812_180825/`（来自 `录屏素材/20260812_180825.mp4` 客户区 1600×900）
- 六阵营未选中模板全部回写 `assets/Images/lobby/hero_*_unselected.png`；均 `verified=True`
- **`level_roi` 按录屏 `hero_level_zero` 滑动匹配校准**（底行 Y≈639，非公式 `y1+196`）；零级自匹配 ≥0.99
- `plus_xy` 仍为卡片相对 `(+110,+209)`，与肯瑞托 `(772,327)` 一致
- 同录屏有五阵营点加号后等级 ROI 像素突变旁证（`frame_*_peak.png`）；**仍不是**非肯瑞托完整加号确认闭环
- `20260812_110511.mp4` / `180003.mp4` 无可用英雄弹窗；勿当证据
- 验收：Dry-run 任一阵营；日志见对应 `Hero*Plus`；窗口保持 1600×900 且勿最小化

---

## 2026-08-12 外壳+L0：刷刷宝 V0.2（六阵营 + 技能/宝物分开展开）

- 桌面：`ShuaBao-V0.2` + 快捷方式 `刷刷宝 V0.2.lnk`（V0.1 归档）
- UI：去掉总「深入设置」；技能 / 宝物各自折叠；六阵营可选；运行日志默认收起
- L0：`FactionSpec` 六阵营；见上节校准后黑锋亦有未选中模板
- 真机：非肯瑞托加号闭环仍待 Dry-run/真跑确认；窗口勿最小化
- 验收：先 Dry-run 守护/元素 1 级；日志应出现 `HeroShouhuPlus` / `HeroYuansuPlus`

---

## 2026-08-12 外壳：刷刷宝 V0.1 桌面同步

- 版本约定改为用户可见「刷刷宝 V0.1」（`__version__=0.1`），不再用 `2026.08.12-rN`
- 桌面发布物：`C:\Users\10639\Desktop\ShuaBao-V0.1\` + 快捷方式 `刷刷宝 V0.1.lnk`
- 含浅色精简首页（关卡/模式/安全测试/开始；深入设置默认折叠）
- 旧 `ShuaBao-2026.08.12-r12` 与无版本「刷刷宝.lnk」已归档到 `刷刷宝-旧版归档`
- 只动外壳；局内/大厅逻辑未改。后续版本按 V0.2 / V0.3 递增

---

## 2026-08-12 外壳：桌面面板浅色精简首页

- 只动一层：**外壳**（`desktop_app.py` + `tests/test_desktop_app.py`）
- 浅色系；首页只留关卡 / 模式 / 安全测试 / 开始；技能、负面宝物、秘境、日志收入「深入设置」（默认折叠）
- 未改大厅/局内逻辑；未动门禁基线。源码预览：`调试启动_源码.bat`

---

## 2026-08-12 A 组：选卡策略 mediator 接线（L1 局内）

- 分支：`cursor/choice-policy-wiring-l1-9866`（基于 `origin/codex/ocr-hybrid@2067952`）
- 只动一层：**L1 局内选卡决策**（`src/gamescript/mediator.py` + 相关期望/契约测试）
- 已接线：`_ocr_panel_slots` → `SlotCandidate` → `choice_policy.choose_action` → SELECT/REFRESH/GIVEUP/CLOSE/WAIT
- A3 旁路已切断：bond/card 不再走 `_rarity_choice` / `_fallback_choice`；`_ADVANCED_BOND_MARKERS` 启发式已移除；宝物禁止无脑第一张
- `RARITY_BANDS` 已补 `green`；描述 ROI 按 `fixtures/treasure_negative` 的 `desc2_*` 回投标定（`y0=0.275,y1=0.420,half_w=0.088`，x 中心 `(0.348,0.497,0.646)`）
- 新增契约：`tests/contract/test_choice_policy_wiring_contract.py`

### 因此失效、需重测的实机链路

1. **技能三选一面板**：日志应出现「稀有度优先」；预设内按红>橙>紫>蓝>白>绿，不再从左到右取第一张
2. **羁绊面板**：未勾选卡不得再被品质色/启发式选中；三槽全未勾选 → WAIT/刷新/隐藏
3. **宝物面板**：负面六名单（透支力量/贪婪献祭/金转木/杀敌梭哈/伐木契约/等级优势）默认不选；描述 OCR 读失败时仍靠名字拦

### 未改（红线）

- 未改 `choice_policy.py` / `settings.py` / `config/choice_policy.json` / `desktop_app.py` / `ui/**`
- 未改大厅/恢复逻辑；未为变绿改 `GATE_BASELINE.json`

---

## 2026-08-12 B 组（感知/素材）云端交付

- 分支：`cursor/b-card-lexicon-bidirectional-1245`（基于 `2067952`）
- 层：感知/素材（未改 mediator / choice_policy / desktop_app / fixtures 真值内容）
- `tools/validate_scenes.py`：接入 `fixtures/card_template_assertions/` 双向断言（正 ≥0.9、空白 ≤0.4、无关帧不得 ≥0.9 误点；`zhufu` 面板命中锁定）
- `config/choice_lexicon.json`：六负面宝物确认在库；补 D0 证实 OCR 别名（箭失* / 全角括号资源名）
- 未伪造新卡图；36 短码与 `fetter_labels.json` 已对齐。等待用户新卡面素材的短码见 `docs/baselines/B_CARD_LEXICON_ASSERTIONS_20260812.md`
- **提醒 C 组**：`FettersCard.tsx` 的 `FETTER_NAMES` 手抄副本需同步或改 API 拉取
- 实机证据：无新增；卡面匹配链路仍需实机抽检（idle_hud 上 14 个旧文字模板 WARN>0.4 但 <0.9）
- 门禁：云端 `python tools/release_gate.py` 4/4 PASS（pytest 462 / frozen_replay 含 disconnect BLOCKED / scene_templates ok=131 / contract 32）
- **快照已在合入时按 Windows 满资产重定**：B 组提交的 462 是云端缺资产的数字，直接沿用等于把基线下调 40+ 条（gate 规则是「通过数只许涨不许跌」，低基线会让真实回归漏网）。云端数字仅作参考，不作基线

## 2026-08-12 r11 创房进房回归（当前唯一可测）

- 当前唯一桌面可测版：C:\Users\10639\Desktop\GameScript-v2026.08.12-r11
- 唯一快捷入口：C:\Users\10639\Desktop\GameScript 单人挂机脚本 v2026.08.12-r11.lnk
- r7/r8/r9/r10 已移入：C:\Users\10639\Desktop\GameScript-旧版归档
- r11 EXE SHA256：52FB83E61CC5E221748A8F6698DE1277CBCB8D643AF7E015C0C425F9A3931C1B
- File/Product version：2026.8.12.11 / build_id：2026.08.12-r11
- 配置：1-15、1600x900、dry_run=false、自动创房开、房名/密码为空

### r10 实机失败 → r11 修复

r10 已能打开并识别 584x488 创建对话框（sticky 双窗问题已修），但确认创建后仍报 create dialog confirmation timeout。

根因：create_dialog_probe 在对话框消失后 
eturn max(frames, size)，永远选中更大的平台窗 1328x945，饿死更小的房间窗 ~1224x904，永远看不到 
oom_start。

证据：%LocalAppData%\GameScript-Local\20260812\trace_20260812_102844.jsonl（全程 size 只有 1328/584，无 1224）；incident incident_103102_648_82b61749。

r11 只改捕获排序：创房探测期仍优先独立对话框；对话框没了优先带 
oom_start 的房间窗；否则回落 sticky/signal 排序。**禁止**恢复快速加入 / 房名密码 / blue 创房权限。

落点：Mediator._capture_best()；回归：	ests/test_p0a_create_room_gate.py::test_create_room_phase_does_not_starve_room_window_after_dialog_closes；全量 unittest 通过。

### 验收顺序（r11）

1. 双开 r11 → 自动创房：trace 应见 584x488/CREATE_ROOM → 确认创建 → ~1224x904 + RoomStart（EXE 不因 create dialog confirmation timeout 退出）
2. 选关 1-15 / 到 5/5
3. 完整一局 → 3 局 → 秘境 → 10 局

历史 r7/r10 文档段落保留为快照，**不能覆盖本 r11 状态**。

---

## 0. 后续 Agent 先读这里

本文是 2026-08-12 起的当前状态单一入口。以下文档是历史资料，只能用于理解过程，不能覆盖本文的状态判断：

- `docs/PROJECT_HANDOFF_NEXT_AGENT.md`：2026-08-07 旧基线；
- `docs/NEXT_STAGE_EXECUTION_BLUEPRINT_20260811.md`：重构计划，不是当前实机验收结果；
- `docs/AI_REVIEW_CONTEXT.md`、`docs/LOBBY_AUTOROOM_RESEARCH.md`：含已经过时或过度乐观的描述。

当前工作树是用户连续实测后的权威实现，尚未整理成提交：

- 分支：`codex/ocr-hybrid`
- HEAD：`8b946fa`
- 工作树：16 个 tracked 文件有修改，另有 2 个素材和 2 个测试文件未跟踪；
- 禁止执行 `git reset --hard`、`git checkout --`、批量回滚或覆盖 dirty worktree；
- 后续修改必须先看 `git status --short` 和相邻 diff，只修本次真机证据指出的第一个阻断点。

## 1. 当前桌面发布物

最新版：

- 目录：`C:\Users\10639\Desktop\GameScript-v2026.08.12-r7`
- 快捷方式：`C:\Users\10639\Desktop\GameScript 单人挂机助手 v2026.08.12-r7.lnk`
- EXE：`C:\Users\10639\Desktop\GameScript-v2026.08.12-r7\GameScript.exe`
- File/Product version：`2026.8.12.7`
- SHA256：`A3B8F74EB53441F011B2F989A106EB7169971B256A0162E256DDA14F336C7943`

旧 r5/r6 快捷方式和目录均已移入回收站；桌面只保留 r7。

当前 r7 桌面测试配置（从用户 r6 本轮配置同步，可在看板修改并保存）：

| 配置 | 当前默认值 |
|---|---|
| 关卡 | `1-12` |
| 游戏分辨率 | `1600×900` |
| Dry-run | `false` |
| OCR | `live` |
| 自动创房 | `true` |
| 英雄模式 | 开，难度 `3-4` |
| 胜利后自动挑战秘境 | 开 |
| 房名/密码实验链 | 空，不执行改名或密码输入 |

## 2. 证据等级

后续汇报必须明确使用下面哪一层证据，不得把单测通过写成实机可用：

| 等级 | 含义 | 当前状态 |
|---|---|---|
| I | 已实现 | 多个模块已达到 |
| U | 单元测试/合成回放通过 | 447 tests 通过 |
| R | 真实录像帧离线回放通过 | 秘境进入/失败退出等已有证据 |
| L | 当前桌面版本真机跑通 | **r7 待验证** |
| S | 3 局、10 局无人干预长稳 | **未达到** |

最近全量门禁：

```text
Ran 447 tests in 52.254s
OK (expected failures=2)
```

两个既有 XFAIL 是：

1. `fail_recovery_three_frames`：缺当前版本真实全屏断线/失败弹窗素材；
2. `ticket_zero_archaeology`：缺挑战券为 0 的真实连续三帧证据。

## 3. 当前工作树的主要改动

### 3.1 大厅、创房、选关

- 自动创房走直接创建，不再执行房名/密码实验链；
- 建房点击后必须等待专用建房弹窗锚点，不能凭 SendInput 成功切状态；
- 选关使用同名目标、相邻连续关卡和专用入口做语义确认；
- 当前仅接受游戏窗口 `1600×900`；
- 看板仍可调整目标关卡和英雄模式难度。

### 3.2 r6 紧急创房修复

r5 真机 trace 已确认错误，不是猜测：

- trace：`%LocalAppData%\GameScript-Local\20260812\trace_20260812_001250.jsonl`
- 画面尺寸：`1328×945` 的 KK 平台页；
- 错误动作：连续 3 次 `click:blue_button_color @ (1120,913)`；
- 候选 bbox：`[911,875,180,48]`；
- 后置结果：建房弹窗 3 次都没有出现，最终 `create dialog confirmation timeout`；
- 用户观察：该坐标实际是“快速加入”，会加入别人的房间。

同一次页面中，专用 `create_room` 模板曾以 `0.983` 命中。根因是下一帧模板短暂未命中时，`_find_map_create_room()` 降级为底部蓝色按钮，并把颜色候选错误授予点击权限。

r6 修复：

- `_find_map_create_room()` 只接受 `map_create_room` 专用模板；
- `blue_button_color`、左右位置和按钮数量都不再拥有创房点击权限；
- `config/scenes.json` 的 `map_create_room.fallback` 设为 `null`；
- 新增“两个蓝色按钮同时存在但无创建模板时返回 None”的回归测试；
- 创房专用 19 tests 和全量 446 tests 均通过。

安全含义：r6 即使模板暂时没命中，也只能零输入等待/超时停止，不能再点击快速加入。可用性是否足够仍要本轮真机验证。

### 3.3 r7 局外尺度回归修复

r6 真机 trace `trace_20260812_002654.jsonl` 连续 57 tick 都是 `context=UNKNOWN`、`map_create_room` 无命中、零输入。对应 incident 原帧实际清晰包含创建房间按钮。

根因：1328×945 平台窗口被热路径换算成 `ui_scale=0.83`，但 `map_create_room` 没列入局外绝对尺寸模板集合；生产只搜索 0.83/0.88 倍模板，而按钮资产和页面都是 1.0 倍。旧诊断工具没有模拟生产 `ui_scale`，曾产生 `map_create=True` 的假通过。

r7 修复：

- `map_create_room`、`create_room_confirm` 加入现有 `_L0_GATE_SCENES`，使用 1.0 优先的局外绝对尺度搜索；
- 诊断工具按真实帧尺寸设置 `ui_scale`；
- 新增 1328×945 / `ui_scale=0.83` 回归测试，修复前失败、修复后通过；
- r6 incident 原帧回放命中 `create_room 0.974 @ local(719,871)`；
- 真实窗口只读诊断得到 `ui_scale=0.83 context=PLATFORM_MAP map_create=True`；
- 全量 447 tests 通过；仍未恢复任何蓝色按钮点击权限。

### 3.4 局内两层循环

`src/gamescript/mediator.py` 当前把局内处理分为：

1. 画面状态抢占：选择面板、装备词缀、进化、胜败页等已知高优先级界面先处理；
2. 主动动作循环：`skill → bond → treasure → evolve → equipment → pickup → merchant → artifact`，完成后回到 skill。

已实现但仍需 r7 真机验收的能力：

- 自动主线和四挑战开启；约 120 秒复核一次，明确 OFF 才重新开启；
- G/F/V 选择面板循环；
- 技能只选配置技能，无命中时刷新，次数耗尽后放弃；
- 羁绊基础/接近合成优先，高级羁绊标记与格子占用保护；
- 宝物 OCR/品质回退；
- 进化、装备升级词缀、装备栏吞噬丹/英雄卡、Z 捡取；
- 黑商刷新/购买木材和吞噬丹；
- 神器轮询。

这些能力有单测或录像回放证据，但尚无一份 r7 真机 trace 证明它们在一整局中全部实际发生。

### 3.5 OCR

- 技能、羁绊、宝物接入 OCR sidecar；OCR 只提供名称，不提供点击坐标；
- 选择策略仍为确定性规则，技能 unknown/非配置项不能点击；
- 当前模型和 `.venv-ocr` 位于源码仓库，本机可用；主 EXE 未把 Paddle/模型完整打进包；
- 因此当前 r7 是“本机桌面包 + 本机源码 OCR 运行时”，不是可拷走即用的完全独立包。

### 3.6 胜败退出与秘境

看板新增 `胜利后自动挑战秘境`，保存到 `Settings.auto_secret_realm`，默认关闭。

已实现并通过单测/真实录像帧回放：

- 普通胜利：继续游戏 → 关闭存档面板 → 验证挑战广场 → 退出 → 标准确认 → 返回原房间；
- 普通失败：强失败两帧抢占 → 失败恢复/退出 → 标准确认 → 返回原房间；
- 秘境进入：挑战广场专用大秘境 NPC 右键 → 专用“是” → 等待过渡帧 → 验证秘境 HUD；
- 秘境自然失败：左上专用退出 → 标准退出确认 → 返回原房间；主图已胜利时不会把秘境自然结束计入普通失败三连熔断。

真实录像帧来源：`C:\Users\10639\Desktop\录屏素材\20260810_214444.mp4`。离线回放曾得到：

```text
进入：damijing (1262,247) → mijingOk (713,481) → 过渡帧零输入 → HUD
退出：failure_open_exit (76,58) → exit_confirm_btn (740,554) → PREPARE
```

仍未实现：胜利后自动完成“存档、时光之穴、传家宝”三项挑战。当前只安全关闭存档/传家宝弹窗并处理可选秘境，不得宣称战后三挑战已完成。

## 4. 本轮 r7 真机验收顺序

用户当前正在复跑。不要同时扩功能；先读取最新 trace，只修第一个可复现阻断点。

### 4.1 首先只验创房

1. 手动关闭仍开着的 r5 控制面板；
2. 双击 `GameScript 单人挂机助手 v2026.08.12-r7`；
3. 看板确认标题/日志包含 `v2026.08.12-r7`；
4. 选择普通模式更容易先验主链，关卡 `1-15`，关闭 Dry-run；
5. 平台页只允许出现 `click:create_room` / `CreateRoom-open`；
6. trace 中 **`click:blue_button_color` 必须为 0，快速加入必须为 0**；
7. 建房弹窗必须由专用锚点后置确认，再点击确认创建。

如果 r7 仍只等待不创房，保留现场和 trace；不能恢复蓝色颜色兜底。

### 4.2 一整局主链

依次检查 trace/录像中是否真实出现：

- 创建自己的房间 → 房间开始 → 选择 `1-15` → 进局；
- `EnableAutoTask`；
- 金币/木材/经验/宝物四个 `*-right_click`，任意两次输入间隔不小于 1.5 秒；
- G/F/V 及后续循环动作；
- 进化、装备、Z、黑商、神器至少到期时可执行；
- 胜利或失败退出 → 返回同一个 KK 房间 → 可开始下一局。

### 4.3 秘境

普通一整局通过后，再打开 `胜利后自动挑战秘境`：

- `OpenGreatRift`；
- `ConfirmGreatRift`；
- 挑战广场过渡帧零输入；
- 秘境 HUD 验证；
- 秘境失败两帧抢占；
- `Recovery-FAIL-FAIL_CONFIRM`；
- `Recovery-FAIL-FAIL_EXIT_CONFIRM`；
- 返回原房间并开始下一局。

### 4.4 长稳门禁

严格按以下顺序推进：

1. 1 局完全无人干预；
2. 3 局完全无人干预；
3. 10 局完全无人干预；
4. 才能讨论“长期稳定、多局无人值守”。

任一阶段只要用户手动介入，该次不计入无人值守通过。

## 5. 当前卡点和待验证事项

按优先级排列：

1. **r7 专用创房模板真机稳定性**：尺度回归已在 r6 incident 原帧和当前窗口诊断中修复，尚待真实点击与弹窗后置确认；
2. **r7 一整局动作覆盖**：局内循环功能多，但尚无当前版本全链 trace；
3. **秘境当前版本真机证据**：已实现并用原版录像真帧回放，尚未在 r7 现场跑通；
4. **普通胜败多局闭环**：单测/回放有证据，r7 尚未完成 1/3/10 局门禁；
5. **断线弹窗素材**：`missing_disconnect_modal` 仍缺，相关场景保持 XFAIL；
6. **挑战券为 0**：考古切换缺真实三帧，保持 XFAIL；
7. **战后三挑战**：存档、时光之穴、传家宝自动挑战仍是功能缺口；
8. **LONGZHU/ANCHOR_BOSS/EARLY_CHALLENGE**：未完成安全状态机的旧阶段仍 Fail-Closed；
9. **UIA**：`src/gamescript/ui/uia/` 只有骨架和单测，生产日志仍显示 `l0_uia=disabled`；当前创房走视觉专用模板，不得写成 UIA 已接线；
10. **OCR 可移植性**：桌面包依赖本机源码仓库中的模型和 `.venv-ocr`；
11. **版本可追溯性**：当前重要实现仍在 dirty worktree；真机门禁通过后再整理提交，提交前不得丢现有改动。

## 6. 日志、录像与排查入口

本地自动化 trace：

```text
%LocalAppData%\GameScript-Local\YYYYMMDD\trace_*.jsonl
%LocalAppData%\GameScript-Local\YYYYMMDD\incidents\
```

原版脚本日志：

```text
%LocalAppData%\GameScript\YYYYMMDD\log.log
```

录像：

```text
C:\Users\10639\Desktop\录屏素材\
```

排查时优先读取 JSONL 的这些字段：

```text
build_id, run_mode, settings_summary, context,
phase_before, phase_after, actions, controls,
decision, reason, interrupt_reason, scenes, ocr_suggestion
```

## 7. 后续 Agent 的执行顺序

1. 先读本文、`goal-objective.md`、最新用户描述和最新 trace；
2. 确认用户实际启动的是 r7，不要根据目录名猜版本；
3. 找到第一条错误输入或首次长期零动作的位置；
4. 用真实 trace/帧复现，补一个会在修复前失败的最小测试；
5. 只改对应识别/状态门闩，不顺手扩展新功能；
6. 跑定向测试，再跑全量测试；
7. 升版本、重新构建、校验 EXE FileVersion 和 SHA256；
8. 删除/回收旧快捷方式，只保留清晰版本号；
9. 让用户按 1 局 → 3 局 → 10 局复跑；
10. 真机通过后再提交当前 dirty worktree，并把提交哈希和发布哈希补回本文。

常用命令：

```powershell
git status --short
git diff --stat

$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -m unittest tests.test_lobby_detectors tests.test_p0a_create_room_gate -v
.\.venv\Scripts\python.exe -m unittest discover -s tests

powershell -NoProfile -ExecutionPolicy Bypass -File .\build_release.ps1
Get-FileHash 'C:\Users\10639\Desktop\GameScript-v2026.08.12-r7\GameScript.exe' -Algorithm SHA256
```

## 8. 禁止的捷径

- 不得恢复地图页通用蓝色按钮点击；
- 不得以“点击发送成功”代替页面后置确认；
- 不得因 OCR unknown 就盲点技能、羁绊或宝物；
- 不得放宽阈值、删失败样本、改分母或新增 XFAIL 来制造通过；
- 不得把录像离线回放、单测或一次人工介入运行写成长期稳定；
- 不得在当前主链未跑通时继续扩存档/时光之穴/传家宝或本地判断模型。

---

## 9. D 组负面宝物描述取证（2026-08-12 cloud）

- 素材包：`fixtures/treasure_negative/`（`DESCRIPTIONS.json` / `INDEX.json` / 六卡真机 panel+desc 裁剪；来自 `2067952`）。
- 新增契约：`tests/contract/test_treasure_negative_fixtures_contract.py`（**未改** `test_choice_semantics_contract.py`）。
- **贪婪献祭**：现有真机帧描述为「每消耗500金币，获得1点随机属性」（与 S3 正面样例同文），**patterns 拦不住**；继续靠 `treasure_negative_names` 名单拦截。若实机另有负面版本文案，需补帧。
- patterns 缺口（只补不删，交主 agent 评估追加，见 `DESCRIPTIONS.json::suggested_pattern_appends_for_main_agent`）：`消耗全部金币` · `将恒定` · `杀敌数清0` · `宝物效果-`。
- 六张均有真机面板帧；描述模式兜底仍弱，生产不阻塞（名字判定已生效）。需主 agent 接线 A 组描述 ROI 后，用本夹具做实机 OCR 回归。
