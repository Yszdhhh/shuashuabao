# 刷刷宝看板 UI 交接（2026-08-21）

权威以本文件为准。旧 `CURRENT_STATUS_AND_HANDOFF_20260812.md` 是大厅/局内逻辑考古，**不要拿它当看板交互规格**。

工作区：`G:\刷刷宝\GameScript-Local`（包名 `shuabao`）。  
**不要改** `G:\刷刷宝\Worktrees\GameScript-Core02-Core03-Integration-20260816`——桌面「CORE03 交互预览」快捷方式指向那棵隔离树，不是这份源码。

---

## 下一任先读的设计 skill（按这个顺序）

用户明确要求看板走 **克制工业风**：简洁、交互优先，不要被配色裹挟。禁止再整文件重写 `main_window.py`。

| 顺序 | 仓库 / 文件 | 用来干什么 |
|---|---|---|
| 1 | https://github.com/Leonxlnx/taste-skill → `skills/redesign-skill/SKILL.md`（install name `redesign-existing-projects`） | **现有项目改 UI 的主 skill**。先审计再小改，禁止从零重写。 |
| 2 | 同上 `skills/taste-skill/SKILL.md`（`design-taste-frontend`） | 只借反套模板纪律。注意它自己写了「Not dashboards」——本仓库是桌面控制台，**密度按 cockpit，不要按落地页那套大留白/非对称英雄区**。 |
| 3 | https://github.com/jakubkrehel/skills → `better-layout` `better-typography` `better-writing` `better-ui` `better-accessibility` | 间距层级、文案动词优先、焦点/按下、去 emoji。配色 skill（`better-colors`）默认不动，除非用户要改颜色。 |
| 4 | https://github.com/heroui-inc/heroui `skills/heroui-react/SKILL.md` | **只借语义**：一个 Primary、若干 Secondary、停止用 Danger、token 一致。本项目是 PySide6，**禁止引入 React/HeroUI/Tailwind 依赖**。 |

落地约束（已和用户确认）：

- 深色底 + **单一金色强调**。主看板不用铺满玻璃/金边渐变。玻璃只留给局内 Overlay HUD。
- 分组靠间距（组内 8、组间 16），不要靠巨型 GroupBox 撑满窗口。
- 文案动词优先，不要 emoji。
- 改现有 QSS/布局，不要再 `Write` 整份 `main_window.py`。

---

## 产品交互（已确认，不要擅自改回）

### 启动

1. `desktop_app.py` **直接 `show()` 主窗**，不再先弹出向导。
2. 主窗先是 **小窗选运行方式**（约 520×360，两张 220×128 卡）：自己刷图 / 大厅蹭车。
3. 点「自己刷图」后 **放大成大看板**（1000×780），设置和底栏「开始运行」这时才出现。
4. 「切换运行方式」缩回小窗。
5. 顶栏「快速开局」才打开向导；向导末步是 **「应用到看板」**，不点火。
6. 全软件只有底栏一个点火按钮。

### 谁能从看板启动

- **只有 `normal_farm`（自己刷图）** 能点「开始运行」。
- 蹭车 / 跟车：可看说明页，按钮文案「待验证 · 不可启动」。`config/mode_specs.json` 里这两项 `desktop_start: false`。
- 门闩：`desktop_may_start = live_enabled AND desktop_start`（`src/shuabao/shell/mode_catalog.py`）。本轮只改了 `desktop_start`，没动 `live_enabled`。

### 技能搭配（大看板 §②）

- 官方流派：**一行一个** = 短名 + 四个技能图标。不要 2 列网格。
- 默认一行「自定义 1」四个空槽；「添加自定义」可再加行。
- 点某一行：其它策略收起，只留当前行 + 「选择其他策略」。
- 点官方：套用 4 技能 + 对应羁绊。
- 点自定义：下方展开技能网格（最多 4）和羁绊/属性线，**不要逼用户去高级设置里找**。

### 后台策略，面板不展示 / 不给改

- **策略必拿宝物**（ONEPIECE / 至高进化 / …）：UI 已去掉那一行，策略层仍必拿。
- **祝福**：基础卡勾选里拿掉；`BOND_ALWAYS_CODES = ["zhufu"]`，组装白名单永远带上。后端 `choice_policy.json` 也是祝福系统必拿。
- **金转木**：从特殊宝物勾选里拿掉（`TREASURE_UI_HIDDEN`）；`negative_names` 仍拦。

高级设置里还留：房间、存档等级、其余特殊宝物、测试方案、日志。

### 主题 / 宠物 / HUD

- 假浅色主题按钮已删（`LIGHT = DARK.copy()`）。
- 宠物窗默认 `hide()`。
- 局内 Overlay HUD（停 / F12）保留，36px 胶囊。

### 技能中文名

工作区未提交配置已把「奥数箭/激光/射线」改成 **「奥术箭/激光/射线」**。测试已改断言。不要退回「奥数」。

---

## 怎么打开「最新看板」

桌面快捷方式 **`刷刷宝看板.lnk`**（不是 CORE03 那个）：

- 目标：`wscript.exe` + `G:\刷刷宝\GameScript-Local\tools\launch_dashboard.vbs`
- 已勾「以管理员身份运行」（UAC 一次，无法静默提权）
- 脚本用 **WINDOWS 子系统** 的 uv `pythonw.exe`（读 `.venv/pyvenv.cfg` 的 `home`），避免 venv 里那个其实是 CONSOLE 的 `pythonw.exe` 弹出黑框
- **禁止** `WScript.Shell.Run ..., 0`：窗口样式 0 会把 Qt 界面也藏掉，进程还占着 `%LocalAppData%\ShuaBao\ShuaBao.lock`

若双击没窗口：任务管理器结束残留 `pythonw.exe` 再开。VBS 在管理员下会尝试杀掉本仓库 venv / `desktop_app.py` 的旧 pythonw。

源码直接跑：

```powershell
cd G:\刷刷宝\GameScript-Local
python desktop_app.py
```

---

## 动过的文件（本波 UI）

| 文件 | 作用 |
|---|---|
| `src/shuabao/shell/theme_styles.py` | 工业风 token / QSS |
| `src/shuabao/shell/main_window.py` | 小窗→大窗、策略行、自定义编辑器、祝福/金转木 |
| `src/shuabao/shell/wizard_dialog.py` | 应用到看板，不点火 |
| `src/shuabao/shell/overlay_hud.py` | 36px HUD |
| `src/shuabao/shell/pet_hud.py` | 默认不弹出 |
| `src/shuabao/shell/smart_route_panel.py` | 样式收敛 |
| `desktop_app.py` | 直接 show 主窗 |
| `config/mode_specs.json` | hitch/follow `desktop_start: false` |
| `config/skill_labels.json` / `skill_meta.json` | 奥术* 未提交改名（接手前已在脏工作区） |
| `tests/test_desktop_app.py` | 对齐上述 UI 契约 |
| `tools/launch_dashboard.vbs` | 无黑框、管理员启动 |

未改：`runner_service.py` 启动门闩算法、Mediator、选卡策略实现。`dual_launch_widget.py` 仍未挂到主窗，不要接。

`src/gamescript/shell/*.py` 多数是 shim 到 `shuabao`。改看板改 `shuabao`。

---

## 测试

```powershell
cd G:\刷刷宝\GameScript-Local
$env:QT_QPA_PLATFORM="offscreen"
python -m pytest tests/test_desktop_app.py tests/test_shell_progress.py -q
```

预期：`test_desktop_app` 除 **Fail-Closed** 外应绿。

**已知不修（本波 UI 范围外）**：`test_desktop_worker_writes_fail_closed_incident` patch 的是 `gamescript.mediator.Mediator`，LIVE 实际构造 `shuabao.runtime_mediator.Mediator`。不要为了绿这条去改 LIVE Mediator 类。

---

## 不要做的事

- 再整文件重写 `main_window.py`
- 把大看板当第一屏（空 GroupBox + 两张小卡漂中间）
- 启动先强制向导、向导直接 `toggle_run`
- 打开 hitch/follow 的 `desktop_start`
- 把策略必拿宝物图标加回面板
- 把祝福勾选加回基础卡、把金转木加回特殊宝物勾选
- 给 `pythonw.exe` 加 requireAdministrator 清单（会抬升所有 pythonw）
- 用 `Run ..., 0` 藏控制台
- 改 CORE03 worktree / 那个预览快捷方式
- 为绿 Fail-Closed 去改 snapshot 或 LIVE 架构

---

## 真机还要看

改的是外壳。需要人眼确认：

1. 快捷方式：无黑框、有小窗、UAC 一次、管理员后 `_is_admin()` 为真才能真机开。
2. 自己刷图 → 大看板；选流派一行收起；自定义展开技能+羁绊。
3. 蹭车页不能点火。
4. F12 HUD 仍能停。
5. 保存后 `user_settings.json` 的 skills/cards 给 `tools/lab_run.py` / 测试夹 bat 读。

---

## 追加：2026-08-21 第二波（视觉与信息密度）

用户反馈后落地，全部为 Edit 小改，未整文件重写：

- **双主题**：`ThemeTokens.LIGHT` 是真浅色（不再是 DARK.copy()）。顶栏「切换浅色/切换深色」按钮（`btn_theme`），选择存 `_shell_extras["theme"]`，随 user_settings 持久化，启动时在 `load_local_settings` 恢复。向导跟随主窗主题。
- **深色提亮**：bg_app `#0D1117→#12161C`，表面/文字整体提亮一档；金色降饱和 `#E5A93C→#DCA94E`。
- **面板级仿玻璃**：GroupBox / footer / 流派行 / 选择卡用垂直微渐变（`bg_surface_hi→bg_surface`）+ 1px 边。窗口级亚克力明确不做。
- **流派行两行式**：上行流派名（`buildTitle`），下行 图标20px+技能全名（`buildSkillName`），空槽虚线框（`buildSlot`）。行高走 QSS `min-height:64px`（盒模型生效约 86px）。**注意**：不要用 `setMinimumHeight()` 设行高——布局激活时会被 Qt 默认约束覆写回内容高，必须走 QSS。
- **字号**：基准 13→14px，小字 12→13px，标题 16→17px，输入/按钮同步加大。
- **文案收敛**：赌木/龙珠/木材阈值提示压成「名称 · 待接线/待验证」短句（测试断言「待接线」子串，勿改词）；羁绊说明改「祝福由系统必拿，无需勾选」。
- **补 QToolTip 样式**：之前是系统黄色气泡。
- 冒烟脚本：`_tmp_ui_smoke/smoke_theme.py`（双主题切换 + 流派行标签检查）。

真机需加看：浅色模式下 GroupBox 渐变与金色对比度、86px 流派行在 1000×780 下的滚动余量。

---

## 追加：2026-08-21 第三波（结构化与冗余收纳）

针对「粗糙感 / 主子菜单整体性差」的反馈：

- **二级分组扁平化**：新增 `QGroupBox#subGroup` 样式（透明底 + 顶部发丝线 + 小号标题），替代「卡里套卡」的双层边框。已应用：技能选择、羁绊、基础卡组、房间设置、技能存档等级、宝物与资源（`_section(..., flat=True)`）、特殊宝物、测试方案配置、运行日志。一级卡片（①②③）保持渐变卡样式。
- **技能区去嵌套**：删掉 custom_editor 里「技能」外层 `_section` 包裹，`grp_skill` 直接挂 `custom_lay`，objectName=subGroup；动态标题已含「已选 x/4」，原「点选最多 4 个」提示删除。
- **待接线三行并一行**：「赌木 · 木材阈值 · 待接线；龙珠 · 待验证」（测试断言的「待接线」「待验证」子串都在）。
- **lab_hint 降级**：warnHint 琥珀色 → hintLabel 次级灰（信息性非警告）。
- **小窗收纳**：chooser 角色额外隐藏 副标题/版本胶囊/主题按钮（引用存为 `lbl_subtitle`/`lbl_version`），只留 logo+标题+快速开局；dashboard 角色全部恢复。
- **状态胶囊运行态**：QSS 新增 `QLabel#statusPill[state="running"]`（绿底绿字），`update_status` 本就设置 property，现在有视觉反馈。
- **标题栏带状化**：customTitleBar 与 footerBar 同款渐变 + 发丝边，上下呼应。
- PySide6 坑：`setContentsMargins` 不接受 tuple 解包，必须四参数。
- 冒烟脚本：`_tmp_ui_smoke/smoke_structure.py`（角色切换显隐 + subGroup 清单 + 文案契约）。

---

## 追加：2026-08-21 第四波（产品感与英雄模式）

竞品对照后的结论与改动：

- **「临时工具感」根因**：Qt GroupBox 默认把小灰字标题骑在卡片边框线上。已改为标题**进卡内**（`subcontrol-origin: padding`），一级 15px/700/主文字色，subGroup 13px 次级色，全部不再压线。
- **英雄声望区块重构**：阵营下拉（每项带悬浮说明：肯瑞托=智力、探险者协会=资源）+ 目标等级(1-5) + 一行机制说明。控件名 `cmb_reputation`/`spn_reputation_level` 未变，测试零改动。
- **重要事实**：mediator 英雄链路只支持**单阵营**（`reputation_type`+`reputation_level`，运行时校验 1-5）。竞品的六阵营各自分配点数（0-10 spinbox 阵列）我们的引擎做不到，且交接禁止改 Mediator——不要画那个 UI。
- **技能附加选线（增伤/控制）：未做，阻塞在数据**。`skill_meta.json` 的 description 全空，知识库无任何路线数据。需要每技能的路线选项表（游戏内截图或 research 文档）才能建 UI，不许编造。
- 待办候选：真浅色下核对 42px 卡头留白是否过大；阵营加成说明补全（黑锋/银色/元素/守护未知）。

---

## 追加：2026-08-21 第五波（英雄模式完整机制 + 产品化头部）

用户提供权威阵营定位表后落地：

- **FACTION_TIPS 模块级常量**（main_window.py，紧跟 FACTIONS）：六阵营完整流派定位，全部进下拉悬浮提示。
- **英雄区块补全**：声望阵营 + 挑战等级(1-5，默认 5) + **声望关卡区间** `spn_rep_stage1/2`(0-50，UI 默认 1-10，已接线 collect/apply/auto-save)。「今日声望耗尽时自动降级常规模式」胶囊 + 阵营定位提示行。`reputation_cjb_boss/sgzx_boss` 未暴露（无已验证 Boss 清单，别瞎加）。
- **产品化头部**：改双行——品牌行居中（logo+APP_NAME 20px+版本胶囊），工具行（状态灯 | 局数 | 主题 | 快速开局）。副标题「控制中心」删除。紧凑角色藏工具行只留品牌行，小窗即产品封面。
- auto_reputation 仍由「关卡难度=英雄」驱动（测试契约），没做重复开关。

**技能附加选线仍阻塞**：需要每技能路线选项数据表。

---

## 追加：2026-08-21 第六波（声望效果汇总）

- **注意**：用户提到的 `config/reputation_factions_kb.json`、`docs/research/HERO_MODE_AND_REPUTATION_SPEC_20260821.md`、`docs/evidence_reputation_20260821/` 当时**并不在本仓库**（可能在别的 agent 工作区）。本波按用户消息里的逐级词条表自建了 `config/reputation_factions_kb.json`（六阵营 × Lv1-10 词条 + BOSS 表 + 每日上限 + Fail-Forward 说明 + 每级奖励）。若那批文件后续同步进来，先 diff 再合并。
- **效果汇总卡**：英雄区块内 `repSummaryCard`（内嵌小卡），选阵营/改等级即时显示「阵营 · 等级 · 定位 · BOSS」标题行 + 「累计效果：…」1..N 级词条去重串联。信号：combo/spin → `_update_rep_summary()`，`_update_hero_visibility` 显示时刷新。
- **撤掉了上一波加的「声望关卡区间」spinbox**：IL 拆解（docs/agent_digs_20260808/hero_reputation_il.md）证实 Stage1/2 是原版「挑战难度阶段」，且我们的 mediator **根本不读** reputation_stage1/2——死配置不进 UI。Settings 字段保留未动。
- **引擎边界**：`reputation_level` 运行时校验 1-5（mediator `_tick_hero_setup` fail-closed），UI 上限保持 5。KB 里 Lv6-10 词条（玩家减益/双BOSS/极难）已入库，引擎放开校验后汇总自动覆盖，无需改 UI。
- 声望源视频：`G:\测试视频+抽帧\录屏素材\声望介绍.mp4`、`英雄挑战任务.mp4`。

---

## 追加：2026-08-21 第七波（系统标题栏染色）

用户指出「最顶上还是临时系统框」——原生 Windows 标题栏此前未处理。已修：`_apply_native_titlebar_theme()`（main_window.py 模块级函数）用 `DwmSetWindowAttribute(DWMWA_USE_IMMERSIVE_DARK_MODE)` 把系统标题栏染色，深色主题=深标题栏、浅色=浅标题栏；挂接在 `__init__` 与 `_apply_component_theme()`，切主题即时生效。**刻意不做无边框自绘标题栏**（拖拽/贴边/最大化兼容风险大）。非 win32 或调用失败静默跳过。

---

## 追加：2026-08-21 第八波（声望自由分配 + 无边框锁定 + 流派增强）

**重要语义变更（引擎）**：
- `reputation_level` 上限 5→**10**；mediator 新增 `_hero_alloc_plan()`：优先读 `settings.reputation_allocations`（dict {faction_id: points}，由看板在运行前动态附加，不进 Settings 持久化层），空则回退旧单字段。
- 英雄状态机新增 `WAIT_FACTION_SELECTED`：前一阵营加满→点下一张阵营卡（card_roi 中心）→确认选中像素翻转→重新基线并继续加点→全部分配完成后才点「开启挑战」。首个阵营保留严格初始零级门控；后续阵营在切换态已验证选中，跳过 verified==1 卡片检查。
- **多阵营连点链路仅离线时间线验证（test_hero_mode_temporal 14 passed），真机首跑需人眼盯「点第二张卡是否直接切换选中」**。

**看板 UI**：
- 声望区块改为**六阵营独立分配格**（0–10，悬浮=流派定位），替换单选下拉+等级框。`cmb_reputation`/`spn_reputation_level` 已删除，相关桌面测试已重写（驱动 `rep_alloc_spins[fid].setValue()`）。
- 可用点数 = **累计通关关数**：「通关进度」= 章节下拉+章内关卡（1-23→23、2-1→24、2-2→25、4-3 封顶 42）。持久化于 `_shell_extras["rep_alloc"] = {"<fid>": pts, ..., "_progress": [ch, st]}`。
- 校验：英雄模式至少分配 1 点；总分配 > 可用 → collect 抛 ValueError。默认给肯瑞托预置 5 点（出厂 auto_reputation=true 的兼容）。
- 效果汇总卡：多阵营词条按各自 1..N 级去重累计展示。

**窗口**：`FramelessWindowHint` 无边框 + 头部空白区按住拖动（`startSystemMove`，保留 Aero Snap）；工具行右端 ─/✕ 自绘按钮（关闭悬停红）；两种角色 `setFixedSize`（520×360 / 1000×780），**窗口不再可拖拽变形——这是用户要求的布局锁**。最大化按钮刻意不做（等比放大需求未来可用 UI 缩放档位方案）。

**流派行**：自定义流派行右上角「删除」按钮（确认弹窗；删除当前选中则清空选择）；每个技能名后附推荐属性流向小字（`config/skill_routes.json`，16 族全量，含三线 UR 链接说明）。

---

## 追加：2026-08-21 第九波（视觉细节 + 学习模式移除 + 特殊挑战下拉）

- **头部两行区隔**：品牌行与工具行之间加 `headerSeparator` 发丝线。
- **声望分配格修正**：阵营名定宽 78px + 三列等宽 stretch（修复歪斜）；每格前置六阵营**官方图**（复用 `assets/Images/lobby/hero_*_unselected.png` 视觉匹配素材，30×30）。
- **学习模式已整体移除**（用户实测用不上，测试全走实机）：`chk_learn/chk_dry` 删除，`settings.dry_run` 恒 False，汇总行不再拼「学习开」，预检黄灯条件简化为仅 `_is_admin()`。测试改为「已移除」契约。
- **特殊挑战目标下拉（新增）**：「传家宝挑战」=`cjb_boss`（chuanjiaobao/ 17 模板）、「时光之穴/Boss」=`sgzx_boss`（boss/ 52 模板）。选项来自模板文件名 stem（存 stem 含序号，显示去序号），**默认选列表最后一项**，可换、随自动保存持久化。引擎侧零改动——这两个字段本就是 boss_entry 场景的活模板名。
- `default_settings.json` 的四个 boss 字段已清空（否则出厂值覆盖「默认最后」兜底）；老用户 `%LocalAppData%` 已保存的选择优先于默认，属预期。
- 注意：`_rep_allocations/_on_rep_alloc_changed` 有 hasattr 守卫——构建期进度下拉信号早于分配格创建时会提前触发。

---

## 追加：2026-08-21 第十波（挑战推荐随关卡联动）

- **新配置 `config/stage_unlocks.json`**：从 `docs/stage_breakdown_1_1_to_1_23_and_rifts_20260815.md` 表格提取的每关解锁映射（heirloom=传家宝新增 / boss=关卡最终 Boss）。**覆盖范围仅 1-1..2-3**（拆解文档所限）；2-4 以后章节待补充拆解后重跑提取脚本即可扩展。
- **联动逻辑**：用户改章节/关卡/手输目标时（同步信号），`_recommend_challenges_for_stage()` 把两个特殊挑战下拉自动跳到截至该关的最新解锁项。加载已保存设置时顺序保证「保存值胜出」：`apply_settings_to_ui` 里 `_apply_stage_target` 先触发推荐、其后的 cjb/sgzx 恢复块后执行覆盖。
- 数据缺口：1-x 关卡的传家宝解锁文档未标注（模板 01暴掠龙~09钦原 对应关 unknown），选 1-x 时传家宝保持当前值不动；后续章节同理。
- 提取脚本是一次性内联 python，未入库；重跑逻辑见本波 git diff 或按正则 `传家宝挑战新增\s*BOSS[:：]\s*\*\*([^*]+)\*\*` + BOSS 名单列末位加粗名重建。

---

## 追加：2026-08-21 第十一波（全量 Boss 清单 + 推荐修复）

- **新配置 `config/challenge_boss_catalog.json`**：传家宝 **18** 项（暴掠龙→莫阿姆）、时光之穴/Boss **53** 项（霍格→拉贾克斯将军），含全局解锁序号 `no` / 显示名 / 模板 stem。来源：assets 模板目录（已与竞品 1.4.9 Images 同步，补齐缺失的 `53拉贾克斯将军.png`、`54莫阿姆.png`）。两个下拉自动读取目录，无需改代码。
- **推荐时机 bug 修复**：构建期程序性信号会提前触发关卡推荐、覆盖「默认最后一项」。加 `_suppress_challenge_rec` 旗标（`__init__` 全程抑制，尾部解除）；`_recommend_challenges_for_stage` 见旗标即跳过。加载已存设置时仍保证「保存值优先」。
- **护肝宝66.exe 抽取结论**：PE 节名为随机串 + 10MB Authenticode 签名覆盖层，无明文/zstd/7z 特征——虚拟加壳，静态抽取不可行（运行时以管理员自解压，句柄不可达）。**放弃该来源**；竞品 1.4.9 的 Images 即完整同源素材。
- stage_unlocks 关卡映射仍只覆盖 1-1..2-3；catalog 的 `no` 字段已为后续映射预留（等 3、4 章拆解数据）。
---

## 追加：2026-08-25（OpenDesign 看板第三波：特殊宝物文案证据限定）

本波只做「文案证据限定」，**未改变任何策略/自动化/配置语义**（TDD：先加失败测试 → RED → 最小替换 → GREEN → 全量桌面测试）。

**改动文件（仅三处）**：
- `src/shuabao/shell/main_window.py`：只改 `NegativeTreasureGroup.TIP` 中两条无卡面依据的负面声明。
- `tests/test_desktop_app.py`：新增 `test_special_treasure_tooltips_do_not_claim_unverified_penalties`。
- `docs/CURRENT_STATUS_AND_HANDOFF_20260821.md`：本条。

**文案修正**：
- 「贪婪献祭」：~~长期期望为负~~ → **「每消耗500金币获得1点随机属性；收益待验证」**。可见卡面为「每消耗500金币，获得1点随机属性」，无负面句，但收益 EV 未验证，不能标纯正面，也不从默认阻断移除。
- 「等级优势」：~~之后不再升级~~ → **「立即获得当前等级×10的全属性；卡面未见副作用，完整描述待补帧」**。三帧真实卡面显示「立即获得当前等级*10的全属性」，可见区无「之后不再升级」，但完整 tooltip 裁剪区尚未排除，故仍默认阻断。
- 未创建「金币贪婪」别名——当前策略与卡牌证据中没有同名 canonical 项，按效果对应「贪婪献祭」。

**默认阻断语义未变**：`config/choice_policy.json`、`DEFAULT_NEGATIVE_NAMES`、`fixtures/treasure_negative/`、`Settings.treasure_allow_negative` 语义、运行时 choice policy 均未触碰。真实 `collect_settings_from_ui()` 默认仍返回 `treasure_allow_negative == []`（由未勾选的分区自然得出，无硬编码）。

**验证（Python 3.11.15 / pytest 9.1.1，工作树 `G:\刷刷宝\GameScript-Local`）**：
- RED：`python -m pytest tests/test_desktop_app.py -q -k special_treasure_tooltips` → `1 failed`（`AssertionError: '收益待验证' not found in '长期期望为负'`）
- GREEN：`python -m pytest tests/test_desktop_app.py -q -k "special_treasure_tooltips or negative_treasure"` → `4 passed`
- 全量：`python -m pytest tests/test_desktop_app.py -q` → `50 passed, 19 subtests passed`

**真机缺口（人工验证，本波无法覆盖）**：
- 完整「等级优势」tooltip 裁剪区内容（当前仅三帧可见卡面，裁剪区未排除）。
- 实际游戏客户区 HUD 上下 fallback / DPI / 位置。
- 游戏中 F12 / HUD 停止按钮实机触发。

---

## 追加：2026-08-25（OpenDesign 最终看板接入与验收）

**实际入口与改动边界**：`desktop_app.MainWindow` 实际导入 `shuabao.shell.smart_main_window.MainWindow`，其共享布局基类为 `shuabao.shell.main_window.MainWindow`。本波将最终看板接入该真实类链：单行标题栏、左侧运行目标栏、工作区、启动前核对窄栏与底部启动区；`更多设置` 只切换既有 `grp_advanced`。启动前核对只投影真实控件及既有预检结论，未新增启动许可判定或设置模型。

**智能路线位置修复**：离屏验收发现 `smart_route_panel` 在基类重排后仍按外层 `lay` 插入，不能保证位于工作区。已先新增真实入口回归测试（RED：`route_index == -1`），再将插入目标改为 `right_main.layout()` 中 `grp_advanced` 的直接前一项（GREEN：`1 passed`）。信号、评估器、刷新和可见性语义未改。

**HUD**：窄游戏客户区按锚定矩形宽度隐藏品牌文字与三枚摘要 chip，仍保留 logo、主状态、细节、运行中的停止按钮；宽客户区恢复摘要。`update_status()` 仍使用当前主题，F12 / Shift+F12 / HUD 停止信号和原有客户区外上方优先、下方回退定位链路未改。未增加技能内容。

**离屏验收**：以临时 app-data 真实实例化 `desktop_app.MainWindow` 和 `OverlayHud`，未启动 RunnerService、未发送输入。宽屏深/浅主题、860px 紧凑布局、窄锚定运行/停止 HUD 均已抓取；结构审查未发现主控件裁切、重叠、空白列、主题错配或停止入口丢失。紧凑状态下启动前核对在工作区之后，通过原有滚动区访问。

**最终验证（2026-08-25）**：
- `python -m py_compile desktop_app.py src/shuabao/shell/main_window.py src/shuabao/shell/smart_main_window.py src/shuabao/shell/overlay_hud.py src/shuabao/shell/theme_styles.py` → exit 0。
- `python -m pytest tests/test_desktop_app.py -q` → `51 passed, 19 subtests passed in 9.41s`。
- `python tools/release_gate.py` → exit 1，未改 `docs/baselines/GATE_BASELINE.json`。观测：pytest `741 passed, 86 failed, 2 xfailed`；frozen replay 的 `giveup_panel_not_fail` 为 FAIL 且 `disconnect_modal_missing` 为 BLOCKED；scene templates `132 ok, 0 missing` 为 PASS；contract `51 passed, 6 failed`。门禁仅 1/4 阶段通过，不能称为全门禁通过。

**审查**：Task 2 锚定紧凑态、Task 3 文案限定、智能路线位置和最终集成范围均完成 scoped review，未确认 Critical / Important finding。审查模型身份未核验；不将其称为特定模型独立审核。

**仍需真机人工验证**：实际游戏客户区的 DPI 与 HUD 上方优先/下方 fallback、F12 和 HUD 停止按钮的实时投递、实际 OCR 阶段状态，以及「等级优势」完整 tooltip 裁剪区；「贪婪献祭」成本/EV 仍未验证。特殊宝物默认阻断、识别、决策、点击和 RunnerService 核心逻辑均未变更。

---

## 追加：2026-08-25（桌面快捷方式启动角色修复）

**根因**：桌面 `刷刷宝看板.lnk` 的目标是 `wscript.exe`，参数为当前工作树 `tools/launch_dashboard_silent.vbs`；该脚本启动当前 `desktop_app.py`，并非旧 EXE。实际问题在 `MainWindow.__init__`：`load_local_settings()` 已根据 `%LOCALAPPDATA%/ShuaBao/user_settings.json` 中 `_shell.selected_mode_id` 恢复 `normal_farm` 看板，随后构造函数无条件 `_show_mode_choice()`，又将窗口锁回 `520×360` chooser，覆盖了已恢复的 dashboard。

**修复**：仅当 `user_settings.json` 不存在时显示 chooser；存在本地设置时保留加载链路已选择的 dashboard role。首次启动仍是 chooser，快捷方式启动已恢复实际已保存的 `normal_farm`，在快捷方式同一 `.venv` 解释器的离屏探针中为 `dashboard normal_farm 1000 780`，选择页隐藏、页面栈可见。

**回归**：新增 `test_saved_dashboard_mode_skips_chooser_on_next_launch`，先失败（`dashboard != chooser`）后通过。`python -m pytest tests/test_desktop_app.py -q` → `52 passed, 19 subtests passed in 9.12s`；`py_compile` 通过。未启动 RunnerService、未发送输入、未更改快捷方式、策略或本地用户设置内容。

---

## 追加：2026-08-25（桌面快捷方式真实启动与布局复核）

**真实入口与进程**：`刷刷宝看板.lnk` 继续指向 `wscript.exe` 加 `tools/launch_dashboard_silent.vbs`。脚本固定使用项目 `.venv\Scripts\pythonw.exe`，不再从 `pyvenv.cfg` 的 `home` 选择基础解释器；启动前仅终止命令行含完整带引号 `desktop_app.py` 路径的 `python.exe` / `pythonw.exe`，避免 venv launcher 派生的旧子进程持锁或残留窗口，也不会匹配 `tests/test_desktop_app.py`。`WScript.Shell.Run` 使用样式 `1`；仓库旧脚本已记录样式 `0` 会隐藏 Qt 窗口。

**真实 HWND 验证**：最终执行 VBS 后，窗口 PID `30300` 的父进程是项目 `.venv\Scripts\pythonw.exe`，其命令行指向当前工作树 `desktop_app.py`；窗口标题为 `刷刷宝 V0.3 · 重生魔兽刷刷刷`，几何为 `1000×780`。最终桌面合成截图保存在 `%LOCALAPPDATA%\Temp\shuabao-shortcut-final.png`。未启动 RunnerService 或发送自动化输入。

**布局**：已保存设置的主页面内容高为 `1551px`，因此主纵向滚动条是正常内容高度，不是布局错误。`launch_check` 原先被同一 `QGridLayout` 行拉至 `1535px`；现以 `Qt.AlignTop` 顶对齐，实际高度与 `sizeHint()` 均为 `213px`。紧凑宽度恢复三列的重排路径同样保留该对齐。新增 `test_launch_check_does_not_stretch_to_dashboard_scroll_height`，已见 RED（`1535 not less than or equal to 176`）后 GREEN。

**底边复核**：桌面合成截图的 `y=772..779` 有外来前景像素，但 Qt 控件树中 `y=765..779` 均命中 `footerBar`（`y=699..779`），可见子控件最高底边为 `y=768`。同一保存设置下的 Qt `MainWindow.grab()` 为 `1000×780`，最底行和左下 `y=779` 都是单一背景色；该碎片不是应用绘制或子控件溢出，不修改 footer。

**验证**：`cscript.exe //nologo tools/launch_dashboard_silent.vbs` 成功启动最终 PID；`python -m py_compile desktop_app.py src/shuabao/shell/main_window.py src/shuabao/shell/smart_main_window.py src/shuabao/shell/overlay_hud.py src/shuabao/shell/theme_styles.py` 退出 0；最终 `python -m pytest tests/test_desktop_app.py -q` 为 `53 passed, 19 subtests passed in 9.36s`。未运行 `release_gate`，其现有全局失败状态未改。

---

## 追加：2026-08-25（Prototype 12 原生看板迁移）

**视觉来源与运行边界**：`G:\下载\Web-Prototype (1)\dashboard-design-sandbox-12.html` 的 Prototype 12 仅作为视觉 authority。实现继续是 `desktop_app.py → shuabao.shell.smart_main_window.MainWindow → shuabao.shell.main_window.MainWindow` 的原生 PySide6 链路；未加入 WebView、浏览器状态、OpenDesign chrome、假游戏帧或假运行计时。`RunnerService`、Mediator、识别/点击和 mode spec 均未修改。

**真实主窗**：shell 使用 204px 左运行目标栏、中央工作区、196px 顶对齐启动前核对栏和 48px footer；窄于 920px 保留既有堆叠重排。启动核对只投影 `lbl_precheck` 和真实控件值，不调用 `desktop_may_start()`、不改按钮 enable 状态、不触发启动。`更多设置` 仍切换唯一既有 `grp_advanced`，Escape 收起抽屉，`smart_route_panel` 保持在抽屉前。

**模式与向导**：chooser 和 quick wizard 都是单人/组队分段，真实 mode ids 为 `normal_farm`、`follow_team`、`lobby_hitch`；选择、已保存恢复和组队→单人回切均同步卡片与分段。当前 `mode_specs.json` 事实是三者均 `live_enabled: true` 且 `desktop_start: true`，界面徽标/提示由 `badge_text(get_spec(...))` 与 `desktop_may_start()` 推导；旧文中「仅 normal_farm 能启动」和「蹭车/跟车不可启动」已过时。快速向导只经 `apply_quick_start_selection()` 写回看板，从不调用 `toggle_run()`；恢复少于四项技能时不会由预设下拉残值扩增 payload。

**设置与 HUD**：房间开关、名称、密码和复用策略从可见控件写入 `Settings`，密码保留原样；HUD 使用 `prototype12Hud` 根对象名，保留真实状态/目标/轮次/策略 chip、停止信号、F12/Shift+F12、紧凑和锚定行为。无新的停止或启动路径。

**2026-08-25 验证**：
- `python -m py_compile desktop_app.py src/shuabao/shell/main_window.py src/shuabao/shell/smart_main_window.py src/shuabao/shell/wizard_dialog.py src/shuabao/shell/overlay_hud.py src/shuabao/shell/theme_styles.py` → exit 0。
- `python -m pytest tests/test_desktop_app.py -q` → `64 passed, 19 subtests passed in 14.67s`。
- `cscript.exe //nologo tools/launch_dashboard_silent.vbs` 打开当前工作树原生窗口，标题 `刷刷宝 V0.3 · 重生魔兽刷刷刷`，Win32 几何 `1000×780`。UIA 采样到原生产品标题区、可滚动 dashboard body、固定 footer（`切换运行方式`、`更多设置`、`开始运行`），可见状态 `待命`。未启动 RunnerService、游戏或自动化输入。

**视觉证据限制**：HWND 截图已存 `.superpowers/sdd/2026-08-25-web-prototype-native-dashboard/dashboard-shortcut-visual.png`。本会话 `inspect_image` 未配置支持图像的模型，designer 截图审查未返回且被取消；因此没有对浏览器/OpenDesign chrome 或假游戏帧“从像素确认不存在”的结论。UIA 控件树和真实原生 HWND 只证明原生桌面表面及待命状态。

**仍需真实游戏验证**：实际游戏客户区 DPI/锚定上下 fallback、运行时 F12/HUD 停止投递、OCR 阶段状态，以及 choice interval/attempt accounting。不要启动真机 BAT 或发送真实输入作为本波验收。

---

## 追加：2026-08-25（OD12 原生接线与版本防错）

**唯一视觉版本**：当前设计源固定为 `C:/Users/10639/open-design/.od/projects/77e53e4e-f466-44aa-878d-1baa278872f4/dashboard-design-sandbox-12.html`，SHA-256 为 `87853C961A229CCC70AE2032AC5BCE61E38A9E1F25ECBA962D68FD533F2AE6F1`。原生标题栏显示 `OD12 · 87853C96`；截图未出现该标识即不是本轮接受版本。两份 2026-08-25 设计规范中的旧项目路径已改为此来源。

**原生设置闭环**：跟车与蹭车页改为大尺寸目标/结束规则、运行路径、脚本接入状态和右侧启动核对。新增真实 `Settings` 字段 `follow_cycle_num`、`hitch_cycle_num`、`follow_after_room`、`hitch_after_goal`、`follow_pair_code`，均经集中值域/枚举/长度清洗并持久化。`RunnerService.start()` 在 `follow_team` / `lobby_hitch` 启动快照中把对应目标局数投影为 Mediator 已有的 `cycle_num`；单刷目标仍保留在原 `cycle_num`，互不覆盖。

**明确未伪装接线**：现有跟车自动准备、蹭车搜房和目标局数是真实运行链；双端配对同步及目标/离房后的单刷、考古、蹭车切换目前只进入运行设置，界面明确标记“状态机待接线”，未声称已经执行。异常重启仍不在跟车/蹭车主控中展示。本波未加入 WebView、依赖或新的真实输入路径。

**验证**：`python -m py_compile desktop_app.py src/shuabao/settings.py src/shuabao/shell/main_window.py src/shuabao/shell/runner_service.py` 通过；`python -m pytest tests/test_desktop_app.py -q` → `69 passed, 19 subtests passed`；`python -m pytest tests/test_mode_catalog.py -q` → `12 passed, 28 subtests passed`。离屏原生跟车页已确认标题版本、目标、预案、配对、运行路径、接入状态与启动核对均可见，未启动 RunnerService 或发送游戏输入。

---

## 追加：2026-08-25（OD12 原生桌面审计与验收修正）

**视觉权威与真实入口**：先核验 `C:/Users/10639/open-design/.od/projects/77e53e4e-f466-44aa-878d-1baa278872f4/dashboard-design-sandbox-12.html`，SHA-256 精确为 `87853C961A229CCC70AE2032AC5BCE61E38A9E1F25ECBA962D68FD533F2AE6F1`。桌面 `刷刷宝看板.lnk` 仍是 `wscript.exe` + `tools/launch_dashboard_silent.vbs`；实测进程入口为项目 `.venv/Scripts/pythonw.exe` 调用当前 `desktop_app.py`，实际 Qt 窗口标题为 `刷刷宝 V0.3 · OD12 · 87853C96 · 重生魔兽刷刷刷`。没有新建启动器、WebView 或第二套窗口。

**本轮实际缺口与修正**：真实 1000×780 截图确认，原 204px 左栏仍塞入旧横向表单，篇章/关卡/难度/局数、传家宝/Boss 与自动策略发生裁切；`desktop_app.py` 还在 `MainWindow` 恢复设置后强制写回 dark。先新增失败回归测试，再做最小修正：运行目标改为原控件的纵向紧凑排列；860px 时左栏、工作区、核对栏以及跟车/蹭车主控和核对栏纵向堆叠；核对栏补齐细节设置、基础卡组、高级卡组投影；预检颜色改读当前主题 token；入口不再覆盖已加载主题；折叠的高级配置保持自身标题高度，不再被中央列拉成大块空面板。浅色主题用深色标题/底栏外壳包住浅色纸面工作区，深色主题仍保留。RunnerService、Mediator、识别、点击和状态机未改。

**真实设置与运行边界**：原有目标关卡、局数、难度/声望分配、传家宝/Boss、自动秘境、自动主线、自动考古、房间、技能/优先级/路线/存档、羁绊/属性线/高级卡组继续进入同一 `Settings`。仓库没有独立 `lead` ModeSpec，因此没有伪造第四种可点火模式；权威设计中的“带车”房间设置改为在 `normal_farm` 左侧目标栏复用原有 `auto_create_room / room_name / room_password / new_room_every_times`，并明确显示“带车目标局数：使用上方目标局数”，继续使用唯一 `cycle_num`。`follow_cycle_num`、`hitch_cycle_num`、`follow_after_room`、`hitch_after_goal`、`follow_pair_code` 继续保存/加载；`RunnerService.start()` 仅对跟车/蹭车目标局数做主动映射，分别写入启动快照的 `cycle_num`。三个结束/配对字段虽随 Settings 快照存在，但没有可靠房间解散、被踢、正常结束原因或双端通信接口，仍只持久化并明确显示“状态机待接线 / 同步待接线”，未声称自动执行。启动资格仍只来自 `mode_specs.json` 的 `live_enabled && desktop_start`（`desktop_may_start()`）与既有预检；当前 normal/follow/hitch 均为可启动。

**截图证据**：目录 `.superpowers/sdd/2026-08-25-od12-audit/`。`actual-light-after.png` 是通过现有 VBS 启动后的真实 HWND 1000×780 截图，含 OD12 版本标识；离屏真实 PySide6 实例另抓取 `light-wide-after.png`、`dark-wide-after.png`、`light-compact-860-after.png`、`follow-860-after.png`、`hitch-860-after.png`、`hud-running-wide-after.png`、`hud-running-compact-after.png`、`hud-stopped-after.png`。目视检查未见运行目标横向裁切、三栏重叠、核对栏纵向拉伸、跟/蹭车主控挤压或 HUD 停止入口丢失；860px 的后续区域通过唯一既有纵向滚动区访问。

**验证结果（2026-08-25）**：
- 指定七文件 `python -m py_compile ...` → exit 0。
- `python -m pytest tests/test_desktop_app.py -q` → `77 passed, 19 subtests passed`。
- `python -m pytest tests/test_mode_catalog.py -q` → `12 passed, 28 subtests passed`。
- `python tools/release_gate.py` → exit 1，未修改 `docs/baselines/GATE_BASELINE.json`：pytest `767 passed, 86 failed, 2 xfailed`；frozen replay 的 `giveup_panel_not_fail=FAIL`、`disconnect_modal_missing=BLOCKED`；scene templates `132 ok, 0 missing`；contract `51 passed, 6 failed`。门禁 1/4 阶段通过，不能称为全门禁通过。

**安全说明**：本轮只启动原生看板和离屏 Qt 组件，没有启动 RunnerService、没有启动真实游戏、没有发送真实输入。HUD 上下定位和停止路由有离屏回归；实际游戏客户区 DPI、运行时 F12/HUD 停止投递与 OCR 阶段仍需人工真机验证。

---

## 追加：2026-08-25（桌面导出包 OD12 像素结构补齐）

**视觉权威复核**：用户改为从 `C:/Users/10639/Desktop/刷刷宝源文件/` 交接。该目录的 `dashboard-design-sandbox-12.html` SHA-256 仍精确为 `87853C961A229CCC70AE2032AC5BCE61E38A9E1F25ECBA962D68FD533F2AE6F1`，与已接受 OD12 是同一字节版本；`DESIGN-HANDOFF.md` / `DESIGN-MANIFEST.json` 只作设计说明与文件索引。目录里混入的 `wscript.exe` 和 `%SystemDrive%/ProgramData/Microsoft/Windows/Caches` 未执行、未复制、未进入生产仓库。Codex 当前工具清单没有 OpenDesign MCP；应用内浏览器又按安全策略拒绝本地 `file://`，因此本轮直接读取权威 HTML/CSS/JS 与 assets，并用用户截图和原生 Qt 抓图比对，没有绕过浏览器策略。

**本轮视觉缺口（先 RED 后 GREEN）**：上一版虽已有三栏和真实字段，但仍是大号旧卡片：六阵营 spin 行、64px 官方流派卡、纯文本核对 QLabel、属性线藏在自定义编辑器。新增回归测试后改为：五条 `88px 名称 + 4×22px 图标` 的 38px 分隔行；默认不伪造一张空的“自定义 1”；声望启用时先显示当前分配的阵营图卡与总点数，“调整”再展开六阵营真实 spin；属性、发育卡组、基础卡组、高级卡组候选全部直接放在中央工作区，用现有 checkbox/Settings 语义显示为 chip；右侧改为结构化窄栏，四技能显示编号、图标和中文名，同时保留 `text()` 纯文本证据供测试。连续重建官方流派曾让旧 QWidget 等待 `deleteLater()` 而叠字，现先 `setParent(None)` 再销毁，并有重复重建测试锁定。

**样式与布局**：默认浅色产品标题栏/纸面工作区/金色主动作，右侧核对使用浅金纸面；深色主题仍完整保留。标题栏压到 42px，footer 维持紧凑固定操作区。左栏声望卡、传家宝/Boss、自动秘境/主线/考古使用原真实控件；`关卡难度` 与 hero/auto_reputation 旧契约未拆出第二套判断。Qt offscreen 在本机返回空 `QFontDatabase`，会把中文画成方框；生产 QSS 已把 `Microsoft YaHei UI` 放在 `Segoe UI` 前，实际 `windows` 平台抓图中文正常。offscreen 图只验证几何/裁切，中文可读性以原生平台抓图为准。

**未改变的真实边界**：桌面入口仍为 `刷刷宝看板.lnk → wscript.exe → tools/launch_dashboard_silent.vbs → .venv/Scripts/pythonw.exe → desktop_app.py → shuabao.shell.smart_main_window.MainWindow`。`toggle_run()`、`RunnerService`、Mediator、mode spec、预检与停止链均未重写。`follow_cycle_num` / `hitch_cycle_num` 继续映射到对应 RunnerService 启动快照的 `cycle_num`；`follow_after_room` / `hitch_after_goal` / `follow_pair_code` 继续只是持久化与快照字段，结束切换和双端同步仍明确“状态机待接线 / 同步待接线”。

**截图证据**：`.superpowers/sdd/2026-08-25-od12-audit/od12-source-folder-*.png`。原生 Windows 平台抓取浅色宽屏、深色宽屏、860px 紧凑、跟车、蹭车、宽/窄运行 HUD、停止 HUD；同名 `*-offscreen.png` 另验证相同尺寸与状态的离屏几何。宽屏首屏可见五条流派、两张当前声望卡、属性/发育/基础/高级 chip、四技能编号核对；860px 纵向堆叠且无水平裁剪；宽 HUD 显示品牌与三枚摘要 chip，窄 HUD 隐藏可选文案/chip 但保留 logo、主状态、细节和停止按钮。最终又通过现有桌面快捷方式链启动真实看板：`.venv/Scripts/pythonw.exe` 父进程与当前 `desktop_app.py` 子进程匹配，真实标题为 `刷刷宝 V0.3 · OD12 · 87853C96 · 重生魔兽刷刷刷`，1000×780 桌面合成截图为 `od12-shortcut-actual.png`。

**最终验证（2026-08-25）**：
- 指定七文件 `python -m py_compile ...` → exit 0。
- `python -m pytest tests/test_desktop_app.py -q` → `82 passed, 19 subtests passed in 16.34s`。
- `python -m pytest tests/test_mode_catalog.py -q` → `12 passed, 28 subtests passed in 0.05s`。
- `python tools/release_gate.py` → exit 1，未修改 `docs/baselines/GATE_BASELINE.json`：pytest `772 passed, 86 failed, 2 xfailed`；frozen replay 的 `giveup_panel_not_fail=FAIL`、`disconnect_modal_missing=BLOCKED`；scene templates `132 ok, 0 missing`；contract `51 passed, 6 failed`。门禁仍为 1/4 阶段通过，不能称为全门禁通过。

**安全说明**：没有启动真实游戏、没有启动 RunnerService、没有发送真实输入。原生窗口抓图只短暂显示测试实例；HUD 真机 DPI/客户区上下 fallback、运行时 F12/HUD 停止投递和 OCR 状态仍须后续人工真机验证。

---

## 追加：2026-08-25（OD12 模式、挑战与组队页对齐）

**修正原因**：上一轮仍保留了两套运行方式入口：主窗内嵌 chooser 与 `GameStyleWizardDialog` 的玩法/关卡两步弹窗并存；左栏继续直接暴露“普通/英雄”长下拉，跟车/蹭车则由多个旧 GroupBox 纵向堆叠。它们与权威 OD12 的“一步确定队伍关系、回到看板配置挑战”不一致。

**本轮原生实现**：`快速开局` 现在只回到主窗内嵌 chooser，不再打开第二套两步向导；组队页补齐带车、跟车、蹭车三张卡。带车是 `normal_farm` 的原生视觉变体，复用唯一 `cycle_num` 与现有房间字段，不新增 ModeSpec 或 RunnerService 分支。普通/英雄 combo 保留为隐藏兼容状态源，用户可见投影改为 OD12 的“声望挑战”开关。传家宝与 Boss 改为紧凑选择行，并由原生图标选择面板修改同一既有 combo。跟车/蹭车收束为标题、结束规则、三步路径、配对/找房条件与执行边界的单一主控面板；目标局数和已接线行为不变，结束切换及配对仍明确待接线。界面切换仅使用 140ms 透明度进入动画，offscreen 与隐藏窗口自动禁用；没有循环动效或跨场景队列。

**回归与证据**：`python -m pytest tests/test_desktop_app.py tests/test_mode_catalog.py -q` → `97 passed, 47 subtests passed`；指定 Qt 文件 `py_compile` 通过。最新 Windows Qt 平台截图为 `.superpowers/sdd/2026-08-25-od12-audit/od12-source-folder-*-rootfix4.png`，覆盖单人/组队 chooser、带车三栏、跟车/蹭车 860px 与 HUD。权威 HTML 再核验 SHA-256 仍为 `87853C961A229CCC70AE2032AC5BCE61E38A9E1F25ECBA962D68FD533F2AE6F1`，未修改。

**全门禁真实结果**：`python tools/release_gate.py` 仍 exit 1，未更新基线：pytest `775 passed, 86 failed, 2 xfailed`；frozen replay 的 `giveup_panel_not_fail=FAIL`、`disconnect_modal_missing=BLOCKED`；scene templates `132 ok, 0 missing`；contract `51 passed, 6 failed`，总体 1/4 阶段通过。没有启动 RunnerService、真实游戏或发送游戏输入。

---

## 追加：2026-08-25（Web 壳方向撤销 + AppData 路径统一 + 原生启动修复）

**方向变更**：本会话曾按 WEB-CONFIG-SHELL-FOUNDATION-001 起了 QWebEngine 配置壳（`web_config_shell.py` / `dashboard_facade.py` / `ui-v2/`），随后按用户明确要求（保持真实原生 PySide6、不得使用 WebView）**全部撤销**：上述文件与 `ui-v2/` 目录已删除，`ShuaBao.spec` 回退到 HEAD（无 diff）。当前桌面启动链为纯原生 `desktop_app.py → shuabao.shell.smart_main_window.MainWindow`，无任何 Web 组件。期间 `desktop_app.py` 曾两次被改坏（缺 `import os` 的 NameError；误删 ROOT/window.show），已整体重写修复并经真机 VBS 启动验证（窗口标题 `刷刷宝 V0.3 · OD12 · 87853C96 · 重生魔兽刷刷刷`，进程响应正常）。

**AppData 路径统一（前置回归修复，保留）**：新增 `src/shuabao/paths.py` 唯一规范路径提供者（`%LOCALAPPDATA%\ShuaBao`，`SHUABAO_APP_DATA` 覆盖优先），`habit_preference.py` / `player_profile.py` / `incidents.default_incident_dir()` / `main_window._app_data_dir()` 全部改为经它取路径。新增 `migrate_legacy_data()`：从旧目录（`%LOCALAPPDATA%\刷刷宝` 等）**只复制、不覆盖、不删源**的幂等合并，已接入 `desktop_app.main()`（单实例锁之后执行，失败不阻塞启动）。实测本机旧目录仅含旧 `user_settings.json`，规范目录的实时配置（4682B）经 5 次真实迁移运行后原封未动——不覆盖语义经真机验证。

**验证**：`py_compile`（desktop_app/main_window/paths/incidents/habit_preference/player_profile）通过；`tests.test_app_data_paths` 3 passed；`tests.test_desktop_app` 96 passed；`tests.test_incident_archiver` 通过（与 desktop 合跑时 `test_desktop_worker_writes_fail_closed_incident` 出现的失败是该测试文档字符串自述的既有"测试顺序依赖"（unittest 先导入全部模块触发 mediator patch 失效），单独/两模块合跑均绿，非本波回归）。

**全门禁真实结果（Py3.13 解释器，169s）**：`release_gate.py` exit 1，未改 `docs/baselines/GATE_BASELINE.json`：pytest `790 passed, 85 failed, 2 xfailed`（会话前文档记载 775/86，失败减 1，无新增失败归因本波）；frozen replay 偏差仅 `giveup_panel_not_fail=FAIL`（快照 PASS），`disconnect_modal_missing=BLOCKED` 与快照一致；scene templates `132 ok, 0 missing` PASS；contract `51 passed, 6 failed`（与记载一致）。总体 1/4 阶段通过，与会话前状态持平。注意：项目 `.venv` 无 pytest，跑门禁需用系统 Py3.13（`C:/Users/10639/AppData/Local/Programs/Python/Python313/python.exe`）；用 `.venv` 解释器跑会得到"实际=0/MISSING"的假门禁结果。

**未启动 RunnerService、真实游戏或发送游戏输入。** 看板处于冻结维护态：不再为旧 PySide6 配置页加功能；后续交互类需求等用户重启 UI 方向讨论。
