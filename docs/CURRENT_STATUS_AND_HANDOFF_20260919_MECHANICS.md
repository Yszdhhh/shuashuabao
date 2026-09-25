# 机制词库与 JEV 交接（2026-09-19，2026-09-20 收敛）

## 已落地

- `config/bond_stack_catalog.json`：Owner 确认 `生命` 卡组为 3 张；视频画面 OCR 双信号确认的 9 条已入 `needs`：五极山、身法、五行灵根、肉身成圣、纷争面纱、点金手、风之杖、旋涡、藏宝图。
- 已恢复未获批准却消失的 `安卡`（2）和 `宝藏`（3）；`needs` 现为 77 条。两条均未移入 `unknown`，后续不得自行删除。
- 每项保留视频 ID、首帧和观测/激活命中数。未修改 `_facts_20260919/` 的原始 CSV 或 `_raw` 列。

## JEV 边界

- 不适合游戏机制事实、选卡或运行时决策：确定性 OCR/规则更可靠，且 JEV 曾把有游戏自证的套装误判为非套装。
- 只可用于离线“刷新/隐藏 EV”的人工复核队列；输入必须包含白名单、可负担性等硬约束。网络结果不进入 `choice_policy`、`mediator` 或实时点击链路。
- `tools/jev_adjudicate_choices.py` 保持离线工具。2026-09-19 的三次独立实测已显示：缺少决定性事实时会高置信给错答案。当前进程未继承用户级 Key；本次仅作一次最小离线复核，写明“白名单外不可选、45 木材低于 80 价格、不能放弃”后，JEV 返回 `hide=1.00`。这只验证约束提示可被遵守，不能证明其可替代规则层。

## 验证

- JSON 解析及 10 项确认张数断言通过。
- `python -m pytest tests/contract/test_choice_policy_wiring_contract.py -q -p no:faulthandler`：7 passed。
- `python -m pytest tests/contract/test_choice_semantics_contract.py -q -p no:faulthandler`（集成工作树）：21 passed，30 subtests passed。

## 已撤销的旧病因

- “木材只涨不跌”和“技能积压 10–12 就是没执行”均被 `pirate-necromancy-gt-20260917/captures` 推翻。20260918_210044 在 13 次木材采样中有 5 次下降（总降 332、总涨 968），且 16 次羁绊确认获得；同局技能点击 24 次。选卡链路已具备策略→派发→click→确认的闭环。

## 价格与证据边界

- `game_mechanics_kb.json` 的羁绊三选刷新 `cost_amount` 仍为 `null`。现有 59 局 captures 与 435 条 HUD 快照不能逐事件对齐，且 F 抽与三选刷新是两笔木材支出、间隔内有击杀收入，不能反推真实单价。
- 代码内价格序列不是机制证据，已在 KB 明确标为待验证实现，不得倒灌。
- 2026-09-20 已撤销 captures 槽位标题「共用 ROI」告警：回填函数逐槽配对 `slots`/`rois`，9 组祝福/经济样本仅来自空/低置信兜底路径的窄模板集合；need=3 时同屏重复卡和同模板分数均属预期。此前对 `live_verified` 与 need 的限制解除。

## Owner 时序机制（2026-09-20）

- 已将 Owner 口述整理到 `resources.skill_bond_timing`，来源明确为 `owner_verbal_20260920`、状态为 `user_confirmed`，且 `wired_to_decision=false`。它不属于 `live_verified`，也未改变任何运行时策略。
- 技能点无上限、不过期；技能无成长性，早学晚学等效。技能点积压只表示尚未花费，并非必须清理的风险。
- 羁绊有成长与合成周期，晚获得可能错过进度；部分卡还需满足吞噬条件。已记录“击杀 200”“时间 60 秒”两个非穷尽示例，完整条件目录仍未知，不能据此外推。
- Owner 的策略意图是优先羁绊；羁绊接近成型或木材不再溢出后，再选择其他项。
- 已知策略冲突待裁：`mediator._solo_plan_panel` 当前把“技能积压 >=8”设为不看木材的紧急抢占，与上述时序机制相反。9 局中 6 局该规则影响至少 40% 的决策；`20260918_210044` 为 22 次调度（羁绊 13、技能抢占 9）。等待 TASK_H 基线测试和 Owner 裁决，本任务不改代码。

## 三路候选对账（2026-09-20）

- A（`events.csv` 面板进度）+ B（激活套装文本）+ C（`inventory.csv` 关闭后快照）三路同时命中：**0 条**，因此无新增入库候选。
- 39 条仅进度候选中，`齐天大圣`、`大乘` 获 A+C 双信号（各 70/16 个 A 命中、各 1 个 C 命中），但 B 为 0；其余 37 条仅有 A。关闭后快照只有 10 条含可解析套装进度，缺失不能当反证或冲突。
- 5 条仅激活文本候选（简术、停术、葡术、五极山门、广法师）均为 B=2、A=C=0；保留为待审，不写 need。
- `unmatched.csv` 的 27 条 `set_name` 仅作为辅助线索，未改变上述准入结论；冲突仍不写。

## 卡组 members 缺口（待 Owner 文字整理）

所有下列链路的 `members` 与 `route_order` 字段均未落库；需要 Owner 按“套装名 → 成员列表、解锁项、路线序号”提供文字版，再只写入各自的 `guide` 桶并与视频事实交叉验证。

| 链路 | 已有证据桶 | Owner 仍需补充 |
|---|---|---|
| 海盗、刀刀、亡灵、封神、龙族、军团、神兽、三国、修仙 | `live_verified` + `guide` | 每个可合成套装的 members、route_order、unlocks |
| 大圣、异火 | 旧 stages 文本，未分入 `live_verified` / `guide` | 完整 members、route_order、unlocks，以及来源归属 |

## 已定范围

- `config/` 真源为 `GameScript-Local`；本次只在该树提交指定三文件，不向 `integration/runtime-core-20260919` 复制。

## 蹭车整链考古收口（2026-09-20）

- 正式设置已固定为 `hitch_cycle_num=5`、`hitch_after_goal=arch`。此前后者只保存/回显，生产 `_finish_hitch_round()` 在第 5 局确认离局后直接停止。
- 现改为：第 5 局已验证离局 → 既有安全退房事务 → 既有单人建房/选关路由 → 考古按钮 request → fresh `kaogu`/`kaoguMode` 锚点确认；未确认时保持零输入或 Fail-Closed，绝不开始第 6 局。
- `hitch_lobby_chain` 的验收读取配置局数，且 `arch` 目标额外要求考古确认；仍需一次新的真机 13 bundle 才能声明 Live PASS。
