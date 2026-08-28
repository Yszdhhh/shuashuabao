# 板块 1 · 看板升级（产品整体化改造）— 执行 Agent 提示词

> 直接把本文整份复制给执行 agent。层归属：**外壳**（`desktop_app.py` → `src/gamescript/shell/`）。
>
> **接线工单已落地**（2026-08-14 23:50）：测试夹 bat 读控制室 `%LOCALAPPDATA%\ShuaBao\user_settings.json`。工单：[`01_TICKET_lab_reads_dashboard.md`](01_TICKET_lab_reads_dashboard.md)。P0 四大板块此前已在 `0c52944`。
>
> 两份权威规格必读，本文只做增量：
> 1. `docs/research/CONTROL_CENTER_PET_ATLAS_PLAN_20260814.md`（P0–P3 分期、对抗终稿、被否决的 20 个坏主意）
> 2. `docs/research/DASHBOARD_INTEGRATION_BRIEF_20260814.md`（六个 ModeSpec 的展示/禁用矩阵、命名对照）
> 再读 `AGENTS.md` 与 `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`。

## 你的任务（一句话）

把方案里已拍板但**零实现**的控制中心 P0 落地（shell 拆分 + ModeSpec 门禁 + 底栏钉死），并在其上加本轮用户新要求的四个设置大板块（技能 / 羁绊 / 宝物与资源 / 运行），全部带默认值 + 可调项 + 已有图标。

## 用户本轮拍板的产品决策（新增，方案文档里没有的）

1. **跟车、站桩（站团本）的页面形态**：采用**左栏「运行方式」卡片切换**——选了跟车，右栏整页换成跟车的选项页；不做并行第二页面。理由：同一时刻只允许一个 LIVE、门禁走 `RunnerService.start` 唯一入口、避免和「关卡难度」混淆。这与方案 §5/§6 布局一致，直接照做。
2. 设置区分**四个大板块**，每板块「默认设置 + 可调设置」两段式，默认值即当前 `config/default_settings.json` + `official_strategy_defaults.json`。
3. **图标可视化**：凡是仓库已有的图标/实机截图，直接放进对应控件（来源见下表），提升可视性。没有的显示灰块+名字，不合成。

## 四个设置大板块（`normal_farm` 右栏，P0 范围）

### ① 技能板块

- 保留现有 `SkillCardGrid`（≤4 系，短码），图标用 `assets/Images/skills/*.png`。
- 新增「**常用搭配**」下拉：数据源 `official_strategy_defaults.json` 的 5 套 `builds`（奥术箭开荒/天雷经典/天雷狂轰/剑气物理/普攻万金油）。选中即一键填充技能 4 格 + 推荐羁绊 + `reputation_type`，填充前弹 diff 确认。这就是挂账已久的「应用流派」接线（外壳层，只写 Settings，不碰策略）。
- 「**自定义组合**」：用户改动格子后，可命名保存为本地方案，落 `%LOCALAPPDATA%/ShuaBao/user_settings.json` 的 `custom_builds`（不写仓库配置）。
- 技能存档等级 16 格分组保留（0=未知），后续由板块 4 自动填充。

### ② 羁绊板块

- 保留现有 `BondCardGrid`（≤6 短码）作为最终生效白名单，图标用 `assets/Images/cards/*.png`。
- 新增「**常规羁绊方案**」视图：按 `bond_priority` 四轮结构展示默认包（round1 必做 / 属性链 / 生存 / 必选急速 / 第四轮选做），每张卡带勾选。
- 新增「**反选**」：默认包里的卡可取消勾选=本局不拿。实现为纯外壳：生效白名单 = 所选方案卡集 − 反选集，最终仍写入现有 `settings.cards` 语义（硬白名单下不在名单=永不点，无需改 L1）。注意 UI 要提示「无短码的羁绊只能看不能勾」（40 条仅知识，见 `bond_stack_catalog` vs `fetter_labels` 的不对称）。
- 三线 UR 链（智力/力量/敏捷）做成单选快捷项，来自 `attr_routes`。

### ③ 宝物与资源板块

| 子项 | 控件与默认 | 现状标注（必须如实） |
|---|---|---|
| EX 必拿四宝 | 只读展示 ONEPIECE/至高进化/一身神装/满级大佬，图标用 `fixtures/treasure_must_take/*/source.png` | 已接策略（`must_take_names`），标「策略必拿」 |
| 负面宝物 | 保留现有逐张 opt-in 折叠区，与 `choice_policy` 同源 | 已接 |
| 赌木 | `treasure_num`（第几个宝物）+ `auto_gambling_time` 输入 | **标「待接线」**：`auto_gambling_time` 未进状态机；赌木闭环属 `gambling_wood` 模式卡（不可启动） |
| 龙珠 | `dragon_ball_count`（默认 7）+ `find_longzhu_*` 开关 | **标「待验证」**：LONGZHU 链 Fail-Closed，开关展示但真机链未通 |
| 吞噬丹 | 只读说明：满槽先吃丹→再黑商（`bond_capacity` 决策）；黑商只买木/丹 | 部分接线，不给自动购买序开关（`do_not_auto_enable`） |
| 木材阈值 | `<100 不开 F / <40 不刷新` 两个数字框 | 由板块 3 接线；接线前控件禁用置灰 |

### ④ 运行板块

- 关卡 N-M、关卡难度（普通/英雄——**不叫模式**）、局数 `cycle_num`（0=手动停）、学习模式、秘境、Dry-run。
- 底栏钉死：摘要 + 预检灯 + 开始/停止（方案 §5 共用底栏，逐字执行）。

## P0 工程骨架（照方案 §11 P0 执行，不复述细节）

- `src/gamescript/shell/{mode_catalog,runner_service,runtime_status,main_window}.py`；`desktop_app.py` 瘦身为入口并**再导出**保住 `tests/test_desktop_app.py`。
- 左栏六卡：id 对齐 `config/mode_specs.json`（是 `normal_farm`，不是方案文里的 `solo_farm`）。`follow_team`/`gambling_wood`/`raid_wait`/`lobby_hitch` 展示设置但主按钮「待验证 · 不可启动」；`lab` 只读说明。
- `RunnerService.start(mode_id, settings_snapshot)` 唯一 LIVE 入口 + `desktop_may_start()` 门禁；托盘/热键不得旁路。
- start 时**深拷贝** Settings；用户设置写 `%LOCALAPPDATA%/ShuaBao/user_settings.json`，仓库 `default_settings.json` 只当出厂默认。
- 预留 `ShuaBao.live.lock` 与实验室互斥。
- 进度显示规则、宠物（P1）、图鉴（P2，板块 2 负责）不在本次 P0。

## 已拍板结论（user 2026-08-14，直接照做，不再询问）

1. **特殊房无「锁定」按钮**：按钮字与操控与普通房一致，仅颜色不同（金/蓝）。蹭车卡说明文案写死「只认 准备/已准备/取消准备」；未来接线时按钮识别以**文字为主锚**、颜色只作辅助（防换色认不出），金蓝两套夹具并存。
2. `hitch_reject_list` 反选编辑器 **P0 不露出**，字段留在 ModeSpec 里。
3. 蹭车卡只露 **3/4 前缀模糊搜索**；「精确关卡过滤」控件本轮隐藏或灰化标「后续拓展」，不引导用户去填。
4. 蹭车流程文案按新语义更正：**F1=操作切回自身英雄**（防 G/V/F 无法操作）、**F2=回基地**（视角偏离或要点秘境/传家宝时）。
5. **P1 桌面英雄素材**：用魔兽英雄形象做小改动（user 拍板，替代原方案的"必须原创像素"）。仅本机工具内使用、不对外分发；点击穿透、不可点、遮游戏即藏等安全要求照方案 §9 执行不变。

## 硬边界

- 只动外壳层 + 对应测试 + 文档；不碰 mediator / scenes.json / choice_policy 判定；不把任何 `live_enabled` 改 true。
- 方案 §10 被否决的 20 条坏主意不得复活（可点宠物、phase 假百分比、print 正则、图鉴当白名单、双 LIVE 等）。
- 一层一个 commit：shell 拆分、四板块 UI、应用流派接线分开提交；提交前 `python tools/release_gate.py` 退出码 0。
- `collect_settings_from_ui` 的 `1-10`→`stage1/stage2` 既有 quirk 不要顺手改（L0 语义）。

## 验收

- 方案 §13 P0 测试清单逐条落地（未验证方式 start 零输入、托盘无未验证项、collect 不共享 Settings 引用、开始键首屏可见、「运行方式」≠「关卡难度」等）。
- 新增：应用流派后 4 技能 + 羁绊 + 声望与 build 定义一致；反选后生效白名单 = 方案 − 反选；赌木/龙珠/木材控件按上表正确置灰或标注。
- `pytest tests/test_desktop_app.py` + 全量 + `release_gate.py` 绿。
- 回写 `docs/CURRENT_STATUS_AND_HANDOFF_20260812.md`。
