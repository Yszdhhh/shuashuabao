# POLICY_V01_EVIDENCE_APPENDIX

```
STATUS                = FROZEN (companion to POLICY_V01_IMPLEMENTATION_CONTRACT_20260908.md)
SOURCE_RESEARCH_SHA   = a3bc4cdad0b11decaa578140e1a03c4b5380b8e7
PRIMARY_RUN           = solo_ingame_chain_20260907_220109_971377
FROZEN_AT             = 2026-09-08
DOCUMENT_KIND         = evidence record only — no new research, no derived design
```

本文件只登记**证据来源、绑定标识、GT Claim Matrix 与 BLOCKED 项**。
设计条款、合同规则、验收矩阵一律见 `POLICY_V01_IMPLEMENTATION_CONTRACT_20260908.md`。

---

## 1. 证据来源清单

| 来源 | 标识 | 说明 |
|---|---|---|
| 冻结源码 | `a3bc4cdad0b11decaa578140e1a03c4b5380b8e7` | 2026-09-08 02:26:35 +0800，`fix(runtime): close solo postgame and challenge confirmation gaps`。经 `git show a3bc4cd:<path>` / `git grep <pat> a3bc4cd` 读取；未创建冻结 worktree，未切换工作树 |
| 主 run | `solo_ingame_chain_20260907_220109_971377` | 3.1 GB；`created_at_utc 2026-09-07T14:01:10Z` → `completed_at_utc 2026-09-07T14:19:27Z` |
| run 内文件 | `manifest.json` (43 MB) / `timeline.jsonl` (23 MB) / `trace.jsonl` (968 KB) / `actions.jsonl` (41 KB) / `config_snapshot.json` / `summary.md` / `frames/` / `screens/` / `incidents/` / `cases/` / `bookmarks/` / `failures/` | — |
| 图像参考包 | `1.5.7/Images`（179 项，含 `cards/` 36 项、`boss/`、`skills/`、`numbers/`、`chuanjiaobao/`） | `IMAGE_PACK_STATIC` 层级；taxonomy 辅助，不得作 lifecycle 依据 |
| 配置 | `a3bc4cd:config/game_mechanics_kb.json`、`a3bc4cd:config/choice_lexicon.json`、run 内 `config_snapshot.json` | — |

---

## 2. SHA 绑定与交叉引用核验

### 2.1 run 的构建标识

```
manifest.tested_commit_sha              = b50a7203e76f0587c5c6c9b503a1619570249601
harness_identity.branch                 = test/solo-live-harness-20260907
harness_identity.sha                    = b50a7203e76f0587c5c6c9b503a1619570249601
harness_identity.production_baseline_sha= b15da05f4fd7313b02b2cc466e319d9683aa979c
harness_identity.runtime_kind           = SOURCE_RUNTIME
harness_identity.mode_id                = normal_farm
execution_mode                          = mediator_tick
production_handler                      = Mediator.tick
production_readiness                    = CONDITIONAL
ground_truth_only                       = false
process_exit_code                       = 4
```

**run SHA ≠ SOURCE_RESEARCH_SHA。** 因此源码与 run 的交叉引用需要证明，不得假定。

### 2.2 差分核验结果

`git diff --stat a3bc4cd b50a720 --`：

| 文件 | 结果 |
|---|---|
| `src/shuabao/choice_policy.py` | 无差异 |
| `src/shuabao/runtime_mediator.py` | 无差异 |
| `src/shuabao/policy/`（含 `mechanics_view.py`） | 无差异 |
| `src/shuabao/habit_preference.py` | 无差异 |
| `src/shuabao/bond_capacity.py` | 无差异 |
| `src/shuabao/mediator.py` | **唯一有差异**：`+68 / −294` |

`mediator.py` diff hunk 边界：`@@ -652`、`-1102`、`-1128`、`-1201`、`-1237`、`-1294`、`-2130`、
**`-4444`**、`-4463`、`-4686`、`-4750`、`-5061`、`-5125`、`-5229`、`-5276`、`-6168`、`-6195`、
`-6897`、`-7506`、`-7661`、`-7709`、`-7736`、`-7849`、`-7886`、`-7969`、`-8449`、`-8476`、`-8484`、
`-9264`、`-10717`。

⇒ **hunk 从 `-2130` 直接跳至 `-4444`；合同引用的 2600–3300 区间未被触及。**

构造存在性逐项核对（两 SHA 计数相同）：

```
MechanicsPolicyView.from_repo      a3bc4cd=1  b50a720=1
assemble_policy_settings(          a3bc4cd=1  b50a720=1
skip_confirm = "差一张合成"          a3bc4cd=1  b50a720=1
live_free_slots = max(0, 10        a3bc4cd=1  b50a720=1
_policy_decision_to_hit            a3bc4cd=2  b50a720=2
_confirmed_bond_cards              a3bc4cd=5  b50a720=5
```

**结论：合同引用范围内的交叉引用成立。超出该范围的引用需重新核验。**

---

## 3. run 计数骨架

### 3.1 三个并存的 tick / 事件口径（禁止合并）

```
trace_tick_count      = 814      trace.jsonl 814 行 / 814 唯一 tick
capture_tick_count    = 813      manifest.capture_ticks
frame_count           = 623      manifest.frame_count / len(frames)
event_count           = 399      manifest.event_count / len(events)
  其中 kind == "action"  = 227
```

### 3.2 动作请求与输入结果

按 `manifest.events[].action.reason` 归类：

| 语义类 | 组成 | requested | input SUCCESS |
|---|---|---|---|
| TAKE | `bond选择` 33 + `技能选择` 28 + `treasure选择` 1 | **62** | **60**（33 + 26 + 1） |
| REFRESH | `bond刷新选择` 14 + `技能刷新选择` 1 | **15** | **13**（12 + 1） |
| TAKE + REFRESH 合计 | — | **77** | 73 |
| policy HIDE | — | **0** | 0 |
| policy GIVEUP | — | **0** | 0 |

`input_status` 全分布（227 action 事件）：

```
SUCCESS                       223
CANCELLED_SENDINPUT_FAILED      2
CANCELLED_WINDOW_CHANGED        1
CANCELLED_WINDOW_OBSCURED       1
```

其他动作 reason（**均不得记为 HIDE / GIVEUP**）：
`ClearPressureMonsters` 41、`OpenBondPanel` 34、`OpenSkillPanel` 27、
`RuntimeWatchdog-EscUnstuck` 10、`EnableAutoTask` 4、`BossConfigured-scroll` 3、
`SelectEvolutionCard` 2、`CloseArchivePanel` 1、`DisableAutoTask` 1、`ClickTQTZ` 1、
`ClickEvolve` 1、`HeroFocusFallback` 1、`ContinueGame` 1、`StageStart` 1、
`SelectStage-target` 1、`OpenTreasurePanel` 1、`{金币,木材,经验,宝物}Challenge-right_click` 各 1、
`ArchiveChallenge-{skill,strengthen,gem,key,recast,blessing,skill2}` 各 1、`BossConfigured` 1。

### 3.3 postcondition 覆盖

```
manifest.events[].postcondition
  227 action 事件      → {"kind": <reason>, "observed": false, "state": "not_observed"}
  172 非 action 事件    → {"kind": null,     "observed": null,  "state": "not_applicable"}
  observed == true 计数 = 0

77 个 TAKE/REFRESH 的 postcondition.state 分布 = Counter({'not_observed': 77})

trace.jsonl[].post_confirm
  814 / 814 tick 恒为 null（非 false、非缺失 —— 从未被写入）
```

### 3.4 correlation identifier 与 freshness 原语

```
                 manifest.json  trace.jsonl  timeline.jsonl
request_id                   0            0               0
decision_id                  0            0               0
observation_id               0            0               0
state_version                0            0               0
free_slots                   0            0               0
set_progress                 0            0               0
can_refresh                  0            0               0
policy_reason                0            0               0
evidence_gen             16081          814             399
```

现存可复用的 freshness 原语：`evidence_gen`（每 tick / 每事件均有）、
`frame_fingerprint`（`1600x900:<hash>`）、`frames[].timestamp`、`frames[].hwnd`（本 run 恒 `25366644`）。

### 3.5 策略输入的可回放性

```
trace.jsonl 非空 panel            = 271 tick
trace.jsonl 非空 ocr_suggestion   = 132 tick   （含 slots[].{index,name,confidence,rarity,
                                                 raw_text,rec_score,status,reason}）
free_slots / set_progress / can_refresh / owned_* / SessionState / PolicySettings
                                  = 0（全部未落盘）
```

⇒ 候选级可回放；容量 / 会话 / 预算级不可回放。

---

## 4. Freshness 证据

### 4.1 after-frame 时间关系分布（227 action 事件）

```
无 frame_after                        0
after-frame 时间前进（Δ > 0）        224      Δ 最小 0.365 s / 中位 0.867 s / 最大 3.55 s
after-frame 非前进（Δ ≤ 0）            3
```

### 4.2 三个非前进样本

| event | Δ (capture ts) | reason | input_status | frame_unchanged |
|---|---|---|---|---|
| `e0183` | 0.000 | `bond刷新选择` | `CANCELLED_WINDOW_OBSCURED` | true |
| `e0218` | **−84.010 s** | `技能选择` | `CANCELLED_SENDINPUT_FAILED` | **false** |
| `e0336` | 0.000 | `OpenSkillPanel` | **SUCCESS** | true |

### 4.3 e0218 明细（freshness 反例）

```
e0218   at_s = 419.734   reason = 技能选择   target = 箭矢齐射   point = [730, 457]
  frame_before = f0337_action_before   ts = 1788790088.231   at_s = 419.734
  frame_after  = f0283_action_after    ts = 1788790004.221   at_s = 334.250
  Δ(capture ts) = −84.010 s        Δ(at_s) = −85.484 s
  帧序号倒退 f0337 → f0283
  frame_unchanged = false
  input_status    = CANCELLED_SENDINPUT_FAILED
  input_result    = {"success": false, "message": "SendInput did not inject click at (730, 457)"}
```

**该样本同时证否两件事**：
`frame_unchanged == false` 不证明业务成功；且 **连"是否发生过输入"都不证明**（SendInput 未注入）。

### 4.4 `(frame_unchanged, input_status)` 联合分布

```
(false, SUCCESS)                        222
(false, CANCELLED_SENDINPUT_FAILED)       2
(false, CANCELLED_WINDOW_CHANGED)         1
(true,  CANCELLED_WINDOW_OBSCURED)        1
(true,  SUCCESS)                          1
```

---

## 5. 语义业务结果证据

### 5.1 x/y 单调递进的 9 个 family

从 `manifest.events[].evidence.ocr.slots[].raw_text` 提取：

| family | 观测到的 x/y | 首次出现（event @ at_s） |
|---|---|---|
| 祝福 | 0/3 → 1/3 → 2/3 | e0020@63.1 → e0025@70.2 → e0030@77.2 |
| 经济 | 0/3 → 1/3 → 2/3 | e0036@86.8 → e0040@92.7 → e0045@99.7 |
| 成长 | 0/4 → 1/4 → 2/4 → 3/4 | e0025@70.2 → e0054@112.9 → e0059@120.4 → e0063@126.5 |
| 挑战 | 0/3 → 1/3 → 2/3 | e0049@105.4 → e0073@141.5 → e0077@147.6 |
| 法术 | 0/3 → 1/3 → 2/3 | e0059@120.4 → e0087@162.5 → e0103@189.0 |
| 急速 | 0/3 → 1/3 → 2/3 | e0113@205.4 → e0135@247.0 → e0190@356.1 |
| 暴击 | 0/2 → 1/2 | e0030@77.2 → e0113@205.4 |
| 魔能 | 0/2 → 1/2 | e0124@227.1 → e0140@255.7 |
| 贪婪 | 0/3 → **2/3**（跳过 1/3） | e0049@105.4 → e0113@205.4 |

**两条限制**：
1. 贪婪 `Δx = 2` 是观测采样断层（观测流只在面板打开瞬间产生），**不是"一次 TAKE 加 2"**。
2. **9 个 family 中无一出现 `x == y`。** 最大观测值：祝福 2/3、经济 2/3、挑战 2/3、法术 2/3、
   急速 2/3、成长 3/4、贪婪 2/3、暴击 1/2、魔能 1/2。**completion 状态在观测流中从不可见。**

### 5.2 完成态触发的实证样本

```
急速 全部观测：
  e0113 @205.422  急速(0/3)  reason=bond选择  SUCCESS
  e0117 @211.969  急速(0/3)  reason=bond选择  SUCCESS
  e0124 @227.078  急速(0/3)  reason=bond选择  SUCCESS
  e0135 @247.000  急速(1/3)  reason=bond选择  SUCCESS
  e0190 @356.125  急速(2/3)  reason=bond选择  SUCCESS   target = ocr_bond:急速
  → 此后 急速 再未出现于任何观测；3/3 状态从不存在
```

### 5.3 配置白名单与观测 family 的重合

`config_snapshot.json`：

```
bonds = ["成长","经济","贪婪","挑战","祝福"]
cards = ["封神","封神榜","打神鞭","杏黄旗","斩仙飞刀","海盗","白赚海盗","海盗劫掠者","海盗宝藏",
         "法术","急速","魔能","暴击"]
bond_whitelist_mode = "hard"        bond_must_take = []
skills = ["asj","asjg","assx","jq"] skill_priority = ["asj","asjg","assx","jq"]
skill_custom_routes = {"asj":"damage","asjg":"flood","assx":"damage","jq":"ice","tl":"paralysis"}
auto_bond = true   auto_treasure = true   auto_devour_dan = true
stage_targets = ["1-21"]   mode_id = "normal_farm"   match_threshold = 0.85
```

`assemble_policy_settings`（`a3bc4cd:src/shuabao/choice_policy.py:403-418`）将 `bonds ∪ cards`
合并为 `bond_presets`。

§5.1 的 9 个推进 family = `{成长,经济,贪婪,挑战,祝福} ∪ {法术,急速,魔能,暴击}`
= `bonds ∪ (cards 中的 4 个羁绊类)`，**一个不多一个不少**。

`肉身成圣` **不在** `bonds` 或 `cards` 中 ⇒ 本 run 从未 TAKE 该 family，
原因是 hard whitelist 结构性排除，非随机未遇。

**该重合只证明"选择被白名单约束"，不证明因果**（见 §7 `SAME_NAME_STACK_LIFECYCLE`）。

---

## 6. 定点帧复核（六帧）

### 6.1 复核结果表

| 帧 | at_s | event / 动作 | 刷新成本 | 抽取成本 | 羁绊栏 | 肉身成圣成员（帧内可读） |
|---|---|---|---|---|---|---|
| `f0260_action_before` | 305.562 | `e0168` `bond刷新选择` SUCCESS | 🪵**40** | 🪵**100** | 7/10 → free = 3 | **雷震子** (SR) |
| `f0262_action_before` | 308.000 | `e0169` `bond选择` → `ocr_bond:封神` SUCCESS | 🪵**60** | — | 7/10 → free = 3 | **哪吒** (SR) |
| `f0282_action_before` | 334.203 | `e0182` `bond刷新选择` `CANCELLED_WINDOW_CHANGED` | 🪵**40**（本 episode 重置） | 🪵**100** | 10/10 → free = 0 | **雷震子**(slot1) + **杨戬**(slot3) |
| `f0294_action_before` | 353.562 | `e0189` `bond刷新选择` SUCCESS | 🪵**100** | — | 10/10 → free = 0 | **哪吒** (SR) |
| `f0296_action_before` | 356.125 | `e0190` `bond选择` → `ocr_bond:急速` SUCCESS | 🪵**100** | — | 10/10 → free = 0 | — |
| `f0297_action_after` | 356.156 | `e0190` 的 `frame_after` | — | — | — | **「替换卡牌」模态 + 「放弃」按钮** |

### 6.2 刷新成本与抽取成本是两处独立 UI

- 刷新成本：面板底部「刷新 🪵N」按钮，紧邻「暂时隐藏」
- 抽取成本：右侧羁绊提示面板「羁绊 🪵100 / 快捷键[F] / 花费木材进行一次羁绊卡牌抽取 /
  集齐卡牌套装**自动吞噬**」
- 刷新成本观测序列 40 → 60 → 100，且 **按 panel episode 重置**（f0262 = 60 @04:19，
  f0282 = 40 @04:45），**非全局单调**

⚠ **以上数值为 run-linked 观测样本，不是机制常量。runtime 禁止 hard-code。**

### 6.3 f0282：同帧同 family 双候选

```
slot1  肉身成圣(0/3)  SR  member = 雷震子   属性行：魔法伤害+5%(+1%) / 技能伤害+5%(+1%)
slot3  肉身成圣(0/3)  SR  member = 杨戬     属性行：力量+100(+20) / 所有伤害+3%(+0.6%)
两者套装效果行完全相同：激活[肉身成圣]套装效果 全属性增幅+10%，护甲+10，格挡+5

对应 e0182 的 OCR 读数：
  slot1  name='肉身成圣'  raw='肉身成圣(0/3)'  conf=0.998  rarity=green
  slot3  name='肉身成圣'  raw='肉身成圣(0/'   conf=0.995  rarity=orange
```

⇒ **family 级 + rarity 均不足以唯一指认候选。**

### 6.4 f0262：命名空间冲突

```
slot0  肉身成圣(0/3)  SR  member = 哪吒
slot3  封神           N   member = 黄飞虎
       [效果1] 实时检测：拥有SSR封神榜时，此卡进化为SSR仁至大帝
       [吞噬条件] 通过SSR封神榜效果吞噬
e0169 的点击 target = ocr_bond:封神，point = [1316, 475]（slot3）
```

而 `a3bc4cd:config/choice_lexicon.json` 中
`entries["肉身成圣"].set_membership = "封神"`。

⇒ `封神` 同时是**一张可 TAKE 的卡**与 **`set_membership` 的取值**，属命名空间冲突。

### 6.5 f0297：替换卡牌模态（结构化盲区）

f0297 为 `e0190` 的 `frame_after`（Δ = 31 ms）。帧内清晰可见：
「替换卡牌」标题、传入卡 `冷缩(急速)`、10 张已持有羁绊卡供选择、「放弃」按钮。

对应的结构化检索结果：

```
"替换卡牌"  manifest=0  timeline=0  trace=0  actions=0
"吞噬"      manifest=0  timeline=0  trace=0  actions=0
e0190.postcondition = {"kind":"bond选择","observed":false,"state":"not_observed"}
```

**完整因果链（run-linked visual）**：
`f0294/f0296 羁绊栏 10/10（free = 0）` → `策略经 merge 分支放行 TAKE 急速(2/3)`
（`a3bc4cd:src/shuabao/choice_policy.py:1134-1135`）→ `游戏抛出替换卡牌模态`
→ `感知层完全读不到该模态` → `postcondition.observed = false`。

---

## 7. GT Claim Matrix

`REP` = representation 层级：`STRUCTURED` / `UNSTRUCT` = `UNSTRUCTURED_RUN_LINKED` /
`IMG_PACK` = `IMAGE_PACK_STATIC` / `GUIDE` = `GUIDE_TIER`。

| Claim | 状态 | REP | 绑定证据 |
|---|---|---|---|
| `NO_STRUCTURED_POSTCONDITION_CONFIRMATION` | **TRUE** | STRUCTURED | 227/227 `observed=false, state=not_observed`；77/77 TAKE+REFRESH 同；814/814 `post_confirm=null`（§3.3） |
| `SEMANTIC_BUSINESS_OUTCOME_EVIDENCE` | **PRESENT** | STRUCTURED | 9 family 单调 x 递进（§5.1） |
| `SAME_NAME_STACK_LIFECYCLE` | **STRONG_CORRELATIVE_EVIDENCE** | STRUCTURED | §5.1 + §5.3。**已证**：x 递进真实存在且全部落在配置白名单内。**未证**：任一次 x 递进由某次具体 TAKE 引起（`request_id` 全零，§3.4；且存在 `Δx=2` 反例）。升级条件：request-correlated observer + L4-01 |
| `FRAME_ID_CHANGE_NOT_OUTCOME` | **PROVEN** | STRUCTURED | `e0218`：`frame_unchanged=false` + 两个不同 frame id，而 SendInput 未注入（§4.3） |
| `STALE_AFTER_FRAME_POSSIBLE` | **PROVEN (rare)** | STRUCTURED | 3/227 非前进；224/227 前进，Δ 中位 0.867 s（§4.1–4.2）。缺的是**强制约束**，非采集 |
| `COMPLETION_NEVER_OBSERVED` | **TRUE** | STRUCTURED | 9 family 无一出现 `x == y`；急速 2/3 被 TAKE 后再未出现（§5.1–5.2） |
| `REFRESH_COST_SEPARATE_FROM_DRAW_COST` | **CONFIRMED** | UNSTRUCT | f0260 / f0282 同帧两处独立 UI（§6.2）。★两者在结构化遥测中零存在（§3.4），无 validated observer |
| `REFRESH_COST_RESETS_PER_EPISODE` | **OBSERVED** | UNSTRUCT | f0262=60 @04:19 → f0282=40 @04:45（§6.2）。★观测样本，非常量 |
| `HIGH_COST_PLUS_FREE_SLOT_GT` | **BLOCKED_MISSING_GT** | — | 六帧中 cost ≥ 100 的三帧 free = 0；free > 0 的两帧 cost = 40/60。**无 `cost ≥ 100 ∧ free > 0` 同帧样本**（§6.1） |
| `FAMILY_LEVEL_IDENTITY_AVAILABLE` | **SUPPORTED** | STRUCTURED | `choice_lexicon.entries["肉身成圣"]` 含 `set_membership="封神"`；OCR 实读 conf 0.987–0.998（§8.1） |
| `FAMILY_ALONE_INSUFFICIENT_TO_DISAMBIGUATE` | **PROVEN** | UNSTRUCT | f0282 同帧双候选，family + rarity 均相同，OCR 读数一致（§6.3） |
| `MEMBER_IDENTITY_VISIBLE_BUT_UNSTRUCTURED` | **TRUE** | UNSTRUCT | 雷震子 / 哪吒 / 杨戬 / 黄飞虎 帧内清晰可读（f0260/f0262/f0282/f0294）；结构化检索全零（§8.2）。属**感知缺口**，非证据缺口 |
| `HETEROGENEOUS_SET_LIFECYCLE` | **BLOCKED_MISSING_GT** | — | 肉身成圣 numerator 全 run 恒 0（§8.1） |
| `FLESH_MEMBER_ROSTER`（3 张 / 4 张 / 第四成员） | **BLOCKED_MISSING_GT** | GUIDE | 唯一来源为 `game_mechanics_kb.json` 的 `guide` 块（§9.1），已被 `_DROP_KEYS` 结构性丢弃 |
| `FLESH_COMPLETION_SLOT_RELEASE` | **BLOCKED_MISSING_GT** | — | 零观测 |
| `AUTO_DEVOUR_TIMING` | **BLOCKED_MISSING_GT** | — | `"吞噬"` 结构化检索全零（§6.5）；仅有 f0260 静态提示文案「集齐卡牌套装自动吞噬」 |
| `FENGSHENBANG_INCREMENT` | **BLOCKED_MISSING_GT** | GUIDE | `board_need:6` / `board_devour_to_tian:9` 均 guide-tier（§9.1） |
| `FULL_SLOT_REPLACEMENT` | **VISUAL_OBSERVED / STRUCTURED_BLIND** | UNSTRUCT | f0297 模态可见；`"替换卡牌"` 结构化检索全零（§6.5）。可作**保守拒绝**依据（HL-7），不得作放行依据 |
| `HIDE_BUSINESS_SEMANTICS` | **BLOCKED_MISSING_GT** | — | `HIDE` / `GIVEUP` 字面在 manifest / trace / timeline / actions 中各 0 次（§3.2） |
| `TRUE_CLOSE_AFFORDANCE` | **BLOCKED_MISSING_GT** | — | `a3bc4cd:src/shuabao/runtime_mediator.py:362-370` 的模板集合几乎全为 temporary-hide 类；无已验证 true-close affordance |
| `SETTLING_WINDOW` | **BLOCKED_MISSING_GT** | — | `e0190` 的 after-frame 距 before 仅 31 ms，对慢后果明显过早；无标定 |
| `MECHANICS_KB_DUAL_GATED_FACTS` | **EMPTY (0)** | STRUCTURED | 见 §9.2 |
| `MECHANICS_VIEW_ASSEMBLY_BREAK` | **CONFIRMED** | STRUCTURED | `mediator.py:930` 构造后零读取；`mediator.py:2630-2638` 未传参（§9.3） |
| `REASON_TEXT_IN_CONTROL_PLANE` | **CONFIRMED** | STRUCTURED | `mediator.py:3081-3083` 中文子串门控第二帧确认闸门 |
| `ACTION_LIFECYCLE_UNUSED` | **CONFIRMED** | STRUCTURED | `interaction_surface.py:12-30` 定义；`cp:133` 与 `med:102` 各导入一次；生产使用零次 |
| `BOND_CAPACITY_UNWIRED` | **CONFIRMED** | STRUCTURED | `decide_bond_capacity` / `CapacityAction` 生产调用者 0；仅 `stack_need`、`load_bond_stack_catalog` 被引用（§9.4） |
| `ACQUISITION_HISTORY_APPEND_ONLY` | **CONFIRMED** | STRUCTURED | `runtime_mediator.py:680-700` 仅 `.append`；唯一移除路径为 `set_phase(MAIN_LINE)` 的 `.clear()`（`rm:748-753`） |
| `FREE_SLOTS_UNKNOWN_TO_PERMISSIVE` | **CONFIRMED** | STRUCTURED | `choice_policy.py:1122` `if free is None or free >= 3: return slots` |
| `FULL_SLOT_MERGE_PASSTHROUGH` | **CONFIRMED** | STRUCTURED | `choice_policy.py:1134-1135` `if free <= 0: allowed = merge or slot.zero_cost` |

---

## 8. 肉身成圣 / 成员身份证据明细

### 8.1 肉身成圣：全部 run 观测（11 个事件命中）

```
e0162 @294.578  slot3  raw='-肉身成圣(0/'   conf=0.987  rarity=orange   action=bond选择(target=ocr_bond:封神)
e0167 @303.187  slot2  raw='肉身成圣(0/3)'  conf=0.989  rarity=orange   action=None
e0168 @305.562  slot2  raw='肉身成圣(0/3)'  conf=0.990  rarity=orange   action=bond刷新选择
e0169 @308.000  slot0  raw='肉身成圣(0/3)'  conf=0.998  rarity=green    action=bond选择(target=ocr_bond:封神)
e0173 @314.953  slot3  raw='-肉身成圣(0/'   conf=0.987  rarity=orange   action=None
e0174 @317.344  slot3  raw='-肉身成圣(0/'   conf=0.987  rarity=orange   action=bond刷新选择
e0181 @331.891  slot1  raw='肉身成圣(0/3)'  conf=0.998  rarity=green    action=None
e0181 @331.891  slot3  raw='肉身成圣(0/'    conf=0.995  rarity=orange   action=None
e0182 @334.203  slot1  raw='肉身成圣(0/3)'  conf=0.998  rarity=green    action=bond刷新选择
e0182 @334.203  slot3  raw='肉身成圣(0/'    conf=0.995  rarity=orange   action=bond刷新选择
e0183 @337.437  slot1  raw='肉身成圣(0/3)'  conf=0.996  rarity=green    action=bond刷新选择
e0183 @337.437  slot3  raw='肉身成圣(0/'    conf=0.997  rarity=orange   action=bond刷新选择
e0184 @340.687  slot1  raw='肉身成圣(0/3)'  conf=0.998  rarity=green    action=bond刷新选择
e0184 @340.687  slot3  raw='肉身成圣(0/'    conf=0.994  rarity=orange   action=bond刷新选择
e0189 @353.562  slot1  raw='肉身成圣(0/3)'  conf=0.998  rarity=green    action=bond刷新选择
```

**关键事实**：
- family 级识别高置信可用（0.987–0.998）
- **numerator 恒为 0**，从未观测到动态推进
- `(0/` 在 e0162 / e0173 / e0174 / e0181 / e0182 / e0183 / e0184 被截断（OCR 切片盲区）
- e0181–e0184 出现**同帧双候选**（slot1 + slot3）
- `y` 读作 `3` 仅是**该表面的 OCR 文本**，不构成"3 个异质成员"的机制 authority

### 8.2 成员名的结构化检索（全零）

```
                manifest  timeline  trace  actions   a3bc4cd:config/choice_lexicon.json
雷震                   0         0      0        0                                   0
哪吒                   0         0      0        0                                   0
杨戬                   0         0      0        0                                   0
"杨"(单字)              0         0      0        0                                   —
肉身成圣                11         0      0        0                                   1
封神                    —         —      —        —                                  23
封神榜                   3         0      0        0                                   —
```

`manifest` 中 `封神榜` 的 3 次出现全部来自 `settings.cards` 配置快照，**非观测**。
`manifest` 中 `木材` 的 131 次出现全部来自 `木材Challenge-right_click` 与 settings 快照，
**与刷新 / 抽取成本无关**。OCR slot `raw_text` 中对 `40|60|80|100` 的检索结果为**空**。

图像参考包 `Images/cards/`（36 项：`baoji` `chengzhang` `dapao` `dasheng` `dashengcanqu`
`dashengtaozhuang` `fs` `genji` `gongshen` `gunfa` `gushou` `jj` `liemoren` `liliang` `mfs`
`mingjie` `qiji` `shenfa` `shengming` `shougezhe` `shufa` `tanlan` `tishu` `tuluzhe` `tz`
`xianzhen` `xuemo` `xueshi` `yanmiezhe` `yemanren` `yihuo` `zhanshen` `zhanshu` `zhili`
`zhiming` `zhufu`）中**无任何肉身 / 雷震 / 哪吒 / 杨戬素材**。

### 8.3 lexicon 条目

```json
"肉身成圣": {
  "aliases": [], "kind": "bond", "version_seen": "guide-20260815",
  "confusions": [], "set_membership": "封神",
  "_note": "攻略：3张一组，可直接吞加速封神榜。未上帧。"
}
```

`_note` 自述 **「未上帧」**——词典作者当时即标注零实机证据。

---

## 9. 冻结源码关键证据

### 9.1 game_mechanics_kb.json 的 guide 块

```
top-level:  version = 1
            kb_id = "official_game_mechanics"
            wired_to_decision = false
            status = "official_help"
            partially_wired = ["skill_points_via_G_before_wood_F",
                               "skill_mode_strict_max_four",
                               "challenge_toggle_periodic_reobserve"]
            precedence = ["official_help","live_ocr","user_card_screenshot","user_confirmed","guide"]

guide 块:   source = ["douyin_无胆超人","douyin_在家零四一","kk_community"]
            status = "guide"     ingested_at = "2026-08-15"
            phase1.board = "封神榜"   phase1.board_need = 6   phase1.board_devour_to_tian = 9
            phase1.flesh = { "name": "肉身成圣", "bundle": 3, "note": "攻称可直接吞，加速成榜" }

fail_closed_actions:  suicide_chat (-zs / -ZS)          script_rule = fail_closed_never_type
                      sword_form_chat (-永恒/-岚/-终焉…)  script_rule = fail_closed_never_type
                      equipment_bar_lmb（装备栏左键）      script_rule = fail_closed_never_type
```

`guide` 在 `precedence` 中排**最后**，且 `a3bc4cd:src/shuabao/policy/mechanics_view.py:18` 的
`_DROP_KEYS = frozenset({"guide", "conflicts"})` 在解析时**直接丢弃整个 guide 子树**。

⇒ 冻结系统已在结构上保证攻略数字永远到不了策略层。

### 9.2 dual-gate 扫描结果

```
_dual_gated(obj) 要求：obj["live_verified"] is True AND obj["wired_to_decision"] is True
                      （mechanics_view.py:42-46，布尔身份判定，"true" 字符串 / 1 均不算）

"live_verified"      键出现次数 = 11
"wired_to_decision"  键出现次数 = 19
递归扫描同时满足 dual-gate 的对象数 = 0
```

### 9.3 MechanicsPolicyView 的两条断线

```
断线一（组装 / call-site）
  a3bc4cd:src/shuabao/mediator.py:930
      self._mechanics_view = MechanicsPolicyView.from_repo(project_root)
  ★ 全仓生产代码中 _mechanics_view 仅此一处出现，构造后从未被读取

  a3bc4cd:src/shuabao/mediator.py:2630-2638
      self._cached_policy_settings = assemble_policy_settings(
          settings=..., skill_labels=..., fetter_labels=...,
          policy_doc=self._choice_policy_doc,
          habit_name_scores=self._habit_skill_scores,
          skill_routes_doc=self._skill_routes_doc,
      )                                  # ← 无 mechanics_view=

  消费侧 schema 完好：cp:248 / 374 / 385 / 534 / 744-748 / 837

断线二（evidence gate，独立成立）
  KB 顶层 wired_to_decision = false；dual-gated fact = 0
  ⇒ 即使接上线，MechanicsPolicyView.from_repo() 仍返回空视图
```

### 9.4 bond_capacity 的接线状态

```
a3bc4cd:src/shuabao/bond_capacity.py:38-45
    class CapacityAction(str, Enum):
        TAKE / SKIP_NEW / USE_PILL / BUY_PILL / REPLACE_THEN_MERGE / ABANDON / NONE
a3bc4cd:src/shuabao/bond_capacity.py:121-186
    def decide_bond_capacity(bar, incoming, *, pills=0, progress=None,
                             on_replace_ui=False, merchant_exhausted=False) -> CapacityDecision

生产引用全集：
    a3bc4cd:src/shuabao/atlas_view.py:17       from shuabao.bond_capacity import load_bond_stack_catalog
    a3bc4cd:src/shuabao/choice_policy.py:1057  from shuabao.bond_capacity import stack_need

⇒ decide_bond_capacity / CapacityAction 的生产调用者数 = 0
⇒ 其 USE_PILL / BUY_PILL / REPLACE_THEN_MERGE 三分支全部依赖 GT 未闭环机制
```

### 9.5 habit 系统的实际能力

```
a3bc4cd:src/shuabao/habit_preference.py:55-72    habit_scores_for_panel  仅抽取 name_scores
a3bc4cd:src/shuabao/mediator.py:929              仅注入 "skill" 面板
a3bc4cd:src/shuabao/choice_policy.py:1245        仅传入 _match_preset，位于 legality 之后（打平局）
a3bc4cd:src/shuabao/habit_preference.py:105-135  observations_to_name_scores 为纯函数，
                                                 按旧策略 SELECT_SLOT 名字频率累计
a3bc4cd:src/shuabao/mediator.py:3097-3119        学习观测仅在 settings.dry_run 下写入，
                                                 记录的是策略 would-select，非玩家真实选择
a3bc4cd:src/shuabao/mediator.py:8164-8190        第二处 dry_run 学习写入（create_room_intent）

⇒ 无 production 聚合写回；无「决策 → 输入 → fresh business outcome」闭环
⇒ 不是 outcome learning，也不是已完成的 shadow outcome pipeline
```

---

## 10. BLOCKED 项汇总（需 Owner 签批的 L4 采集）

| L4 # | GT 门 | 最小采集要求 |
|---|---|---|
| L4-01 | `SAME_NAME_STACK_LIFECYCLE` 结构化确认 | 一次 TAKE 的 `request_id` 关联到 fresh 观测且 x 精确 +1；`STRUCTURED_CONFIRMED > 0` |
| L4-02 | `next_refresh_cost` / `draw_cost` validated observer | 同帧同时读出两个数值，覆盖刷新成本递增全序列与抽取成本 |
| L4-03 | `HIGH_COST_PLUS_FREE_SLOT_GT` | **同帧** `refresh_cost >= 100 AND free_slot > 0` 的已确认样本 |
| L4-04 | `HETEROGENEOUS_SET_LIFECYCLE` | 肉身成圣 numerator 从 0 变为 ≥1 的 run-linked 动态样本 |
| L4-05 | `FLESH_MEMBER_ROSTER` | 成员集齐的完整实机链（不得用图像包静态截图替代） |
| L4-06 | `FLESH_COMPLETION_SLOT_RELEASE` | 完成瞬间前后的槽位占用差 |
| L4-07 | `FULL_SLOT_REPLACEMENT` | 替换模态的出现 → 选择 → 结果的完整闭环 |
| L4-08 | `AUTO_DEVOUR_TIMING` | 吞噬触发时机与前后 inventory 差 |
| L4-09 | `FENGSHENBANG_INCREMENT` | 封神榜增量的实机观测 |
| L4-10 | `HIDE_BUSINESS_SEMANTICS` | 一次真实 policy HIDE 及其后置业务语义 |
| L4-11 | `TRUE_CLOSE_AFFORDANCE` | 已验证的真正关闭 affordance 及其后置语义（与 L4-10 独立） |
| L4-12 | `SETTLING_WINDOW` | F-8 所需的 settling_window 标定 |

---

## 11. 研究边界声明

本次研究全过程只读：

- 未修改代码、测试、fixture、threshold、baseline、配置或 Git 历史
- 未创建冻结 worktree（`Worktrees/astra-policy-review-a3bc4cd` 不存在，未创建）
- 未 checkout / reset 任何现有工作树
- 未执行 build / release / Golden Run / 真实 SendInput
- 未触及 Corrective C-D / trial-merge 生产修复线
- 未评价或改动 release gate

本文件与 `POLICY_V01_IMPLEMENTATION_CONTRACT_20260908.md` 为 docs-only 归档交付。

---

**END OF EVIDENCE APPENDIX — FROZEN 2026-09-08**
