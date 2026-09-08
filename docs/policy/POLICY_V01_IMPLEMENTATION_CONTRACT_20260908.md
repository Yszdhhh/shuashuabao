# POLICY_V01_IMPLEMENTATION_CONTRACT

```
POLICY_V01_IMPLEMENTATION_CONTRACT = FROZEN
READY_FOR_IMPLEMENTATION_AGENT     = YES_WITH_GT_GATES
SOURCE_RESEARCH_SHA                = a3bc4cdad0b11decaa578140e1a03c4b5380b8e7
FROZEN_AT                          = 2026-09-08
DOCUMENT_KIND                      = canonical, docs-only, read-only research output
```

本文件是**唯一 canonical 来源**。它由原 `POLICY_V01_IMPLEMENTATION_CONTRACT`、`CORRECTION ADDENDUM`、
`CONTRACT_FREEZE_PATCH_2` 与 `CONTROL_TOWER_FREEZE_AMENDMENT_1` 合并规范化而成，**不是串接**：
所有被取代的旧规则已从正文中**删除**，不再以任何形式保留。

被删除且不得复活的旧规则（列此仅为防止回流，正文中不存在其条款）：

| 已删除的旧规则 | 现行条款 |
|---|---|
| Runtime semantic substitution 合法（`REFRESH→GIVEUP/CLOSE` 等，记 `substituted_from` 即可） | §5.3 / §10.3 `REFUSE → fresh re-decision` |
| HIDE 可作为 CLOSE 的实现（`card_hide`/`skill_hide`/`bond_hide_btn` 绑定 CLOSE） | §2.4 / §10.6 affordance 分离 |
| `family_identity == UNKNOWN` 一律阻断所有 TAKE | §9.1 HL-1 identity scope 判定 |
| `slot_index` 参与 canonical identity | §2.2 双轴身份模型 |
| "family 从选卡候选 surface 消失" 可确认 completion | §10.4 分支 B |

证据、SHA/run/event/frame 明细、GT Claim Matrix 见配套文件
`docs/policy/POLICY_V01_EVIDENCE_APPENDIX_20260908.md`。

---

## 0. 文档状态与适用范围

### 0.1 冻结状态

本合同已冻结。冻结意味着：实现 Agent 可据此开工，且**不得**在实现过程中自行放宽本文件中的任一 gate。
任何条款变更需新的、显式的 amendment，并重新走冻结流程。

### 0.2 本合同**不**授权的事项

- 不授权修改代码、测试、fixture、threshold、baseline、配置或 Git 历史
- 不授权 build / release / Golden Run / 真实 SendInput
- 不授权触及 Corrective C-D / trial-merge 生产修复线
- 不授权评价或改动 release gate
- 不授权激活 `decide_bond_capacity`（见 §13.3 P-1）

### 0.3 阅读顺序建议

实现 Agent 应按 §2（身份与术语）→ §3（事实表示）→ §5（权威模型）→ §6/§7（快照）→ §9（三段式裁决）
→ §10（动作与结果）→ §11（验收）→ §13（就绪与前置）的顺序阅读。§4 是对冻结现状的描述，用于定位改动点。

---

## 1. 范围与证据绑定

### 1.1 双重绑定

| 类别 | 绑定 |
|---|---|
| 源码结论 | `a3bc4cdad0b11decaa578140e1a03c4b5380b8e7`，引用格式 `a3bc4cd:<path>:<line>` |
| 实机结论 | run `solo_ingame_chain_20260907_220109_971377`，引用格式 `<event_id>` / `<frame_id>` |

### 1.2 交叉引用的合法性（已核验，非假定）

主 run 的 `manifest.tested_commit_sha = b50a7203e76f0587c5c6c9b503a1619570249601`
（`production_baseline_sha = b15da05f`），**不等于**冻结研究 SHA。因此源码与 run 的交叉引用需要证明。

已完成的差分核验：

- `choice_policy.py` / `runtime_mediator.py` / `policy/` / `habit_preference.py` / `bond_capacity.py`
  在 `a3bc4cd` 与 `b50a720` 之间**无差异**
- `mediator.py` 为唯一有差异文件（`+68 / -294`），且其 diff hunk 从 `@@ -2130` 直接跳至 `@@ -4444`，
  **本合同引用的 2600–3300 区间（策略装配 / `choose_action` 调用 / 执行门 / 快照产出）完全未被触及**
- 逐构造存在性核对一致：`MechanicsPolicyView.from_repo`、`assemble_policy_settings(`、
  `skip_confirm = "差一张合成"`、`live_free_slots = max(0, 10`、`_policy_decision_to_hit`、
  `_confirmed_bond_cards` 在两 SHA 计数相同

**结论**：本合同引用范围内的交叉引用成立。超出该范围的引用需重新核验。

---

## 2. 术语与身份模型

### 2.1 为什么需要两条正交的身份轴

同一帧内可以出现**两个候选，套装标题、进度、稀有度全部相同，但不是同一张卡**（见附录，f0282：
slot1 与 slot3 同为 `肉身成圣(0/3)` SR，成员分别为雷震子与杨戬，属性行不同）。
OCR 对二者的读数完全一致（`name='肉身成圣'`，置信度 0.998 / 0.995）。

因此：**指认"这一帧这个位置的这个候选"**与**指认"这是哪张卡"**是两个不同问题，必须分开建模。

### 2.2 双轴身份模型

```
candidate_instance_id        observation-local，指认"这一帧这个位置的这个候选"
  构成 = observation_id + panel_kind + slot_index
  用途 = request.target 绑定 / 点击目标定位 / 同帧多候选消歧
  约束 = 随 observation 失效而失效
         ★必须进入 decision / request / outcome trace（见 §2.6）
         ★禁止跨帧复用
         ★禁止作为 semantic inventory / acquisition_history / active_inventory 的 key

canonical_card_id            semantic，指认"这是哪张卡"
  来源 = title_text + member_id + rarity，经 validated observer 结构化后
  约束 = ★不含 slot_index、不含 observation_id
         ★仅在 card-level identity 足够确定时才赋值；否则保持 UNKNOWN
         ★禁止用 rarity / slot_index / observation_id 拼凑出一个 semantic canonical identity
  用途 = acquisition_history / active_inventory / 跨帧关联 / 去重
```

### 2.3 身份层级

```
route_membership  ⊃  family_id  ⊇  canonical_card_id  ⊇  member_id (optional)
```

| 层 | 说明 | v0.1 地位 |
|---|---|---|
| `route_membership` | 阵营 / 路线。例：`肉身成圣` 的 `set_membership = 封神`（`a3bc4cd:config/choice_lexicon.json`） | 必需字段，可为 UNKNOWN |
| `family_id` | 套装 / 进度归属，决定 x/y 的解释与 completion 判定 | **必需**；单独即可授权 family-scoped rule |
| `canonical_card_id` | 单卡语义身份 | 可为 UNKNOWN；UNKNOWN 不阻断 family-scoped rule |
| `member_id` | 成员身份（雷震子 / 哪吒 / 杨戬 / 黄飞虎 …） | **optional**，不参与 legality；仅作 `canonical_card_id` 输入之一与遥测 |

**命名空间隔离（强制）**：`封神` 同时是一张可 TAKE 的卡（成员黄飞虎，见 f0262）**和** `set_membership`
的取值。二者必须分属不同命名空间。`route_membership` 取值必须不透明化（如 `route:fengshen`），
**禁止直接用中文卡名作为 route id**。

### 2.4 PolicyAction 与 physical execution affordance 的分离

这是两个不同层的概念，**禁止混用**。

```
PolicyAction（语义层，策略输出）
  SELECT_SLOT  取这一个候选
  REFRESH      重抽候选
  GIVEUP       放弃本次机会
  CLOSE        本次不取，结束该 panel episode
  HIDE         暂时隐藏，面板可再来      —— 状态 GATED_UNAVAILABLE（§10.5）
  WAIT         零输入等待
  NONE         无面板

physical execution affordance（执行层，模板 / 按钮）
  true_close_affordance       已验证的真正关闭 / 结束 affordance
  temporary_hide_affordance   暂时隐藏类：skill_hide / card_hide / bond_hide_btn /
                              treasure_hide_btn / hide /「暂时隐藏」
  refresh_affordance          bond_refresh_btn / skill_refresh_btn / treasure_refresh_btn / …
  giveup_affordance           skill_giveup_btn / giveUp
  slot_affordance             候选槽位点击区
```

**绑定规则**见 §10.6。核心一句：**`temporary_hide_affordance` 不得绑定 `PolicyAction.CLOSE`。**

### 2.5 SAFETY_RECOVERY_TEMP_HIDE

安全恢复链（fail-forward / watchdog）在某些帧上仍可能需要点击"暂时隐藏"以解除面板阻塞。
该行为**允许存在**，但必须独立建模：

```
SAFETY_RECOVERY_TEMP_HIDE
  ├─ 不是 PolicyAction，不经策略层产出
  ├─ 独立 telemetry 通道、独立 reason_code、独立 outcome 记录
  ├─ ★不计入 policy CLOSE 计数，不计入 policy HIDE 计数
  ├─ ★不得声称保留 offer、不得声称保留 price/成本状态、不得声称面板可原样再来
  │    （该保留语义未经验证，属 GT-blocked）
  └─ outcome 上限 = UNKNOWN；仅用于证明"面板阻塞已解除"
```

### 2.6 candidate_instance_id 的 trace 要求

`candidate_instance_id` 必须出现在以下三处，作为 observation-local target reference：

```
DecisionSnapshot.candidates[].candidate_instance_id
Request.target.candidate_instance_id
Outcome.target_ref.candidate_instance_id
```

禁止事项（重申）：不得作为 `acquisition_history` / `active_inventory` / 任何跨帧 ledger 的 key。
跨帧身份一律走 `canonical_card_id`；若其为 UNKNOWN，则该事实**不进入**跨帧 ledger，保持 UNKNOWN。

---

## 3. 事实表示与证据分级

### 3.1 Fact\<T\> 包装器

每个动态事实必须可表达以下六项：

```
Fact<T> {
  value:          T | UNKNOWN            # UNKNOWN 是一等公民，不是 null 的别名
  source:         SourceKind
  observation_id: ObservationId | null    # value ≠ UNKNOWN 时必填
  observed_at:    epoch_seconds | null    # value ≠ UNKNOWN 时必填
  validity:       VALID | STALE | OUT_OF_SCOPE | CONTRADICTED | UNKNOWN
  uncertainty:    { confidence: float | UNKNOWN, method: str, degraded_reason: str | null }
}
```

### 3.2 source 与 representation 是两个不同维度

**`STRUCTURED` 不是证据来源类型，而是 runtime fact representation。**
它指一个事实**已被 validated observer 结构化**、带完整 `Fact<T>` 元数据，因而可被 runtime 引用。

`vision` / `OCR` 是**来源**，不是等级。任一视觉事实，**只有在经过 validated observer 结构化之后**，
才成为 `STRUCTURED`，才可进入 legality。未经结构化的视觉事实，无论人眼多清晰，都不得进入 legality。

```
SourceKind（来源）
  OCR_LIVE / OCR_SHADOW / TEMPLATE_MATCH / PIXEL_HEURISTIC /
  CONFIG / DERIVED_LEDGER / GUIDE_TIER

Representation（表示层级）
  STRUCTURED                 已经 validated observer 结构化，带完整 Fact<T>
                             ★唯一可进入 live legality 的层级
  UNSTRUCTURED_RUN_LINKED    帧内可读、可定位到 event_id / frame_id，但无 validated observer
                             ★仅可用于：离线设计、保守 gate 的依据、感知 backlog
                             ★禁止进入 live legality；禁止作为放行 / authority 依据
  IMAGE_PACK_STATIC          参考包静态截图；taxonomy 辅助，不得作任何 lifecycle 依据
  GUIDE_TIER                 攻略来源；恒 OUT_OF_SCOPE
```

### 3.3 GUIDE_TIER 的强制丢弃

`a3bc4cd:src/shuabao/policy/mechanics_view.py:18` 的
`_DROP_KEYS = frozenset({"guide", "conflicts"})` 在解析时直接丢弃整个 `guide` 子树。
`config/game_mechanics_kb.json` 自身的
`precedence = ["official_help","live_ocr","user_card_screenshot","user_confirmed","guide"]`
亦将 `guide` 排在最后。

**该 drop 规则必须原样保留。** 冻结系统据此已经保证攻略数字（如"肉身 3 张一组"、"封神榜 need 6"、
"吞 9 升天庭"）永远到不了策略层。任何"为补齐 taxonomy 而提级 guide"的改动均属合同违规。

### 3.4 UNSTRUCTURED_RUN_LINKED 的正确用法

本次研究中有两项事实处于该层级（明细见证据附录）：

| 事实 | STRUCTURED | UNSTRUCTURED_RUN_LINKED | 处置 |
|---|---|---|---|
| 成员名（雷震子 / 哪吒 / 杨戬 / 黄飞虎） | ABSENT | PRESENT | 感知 backlog；不得进 legality |
| 替换卡牌模态 | ABSENT | PRESENT | 支撑 HL-7 的**保守拒绝**；`REPLACE_MODAL` 列入 `surface_type` backlog |

两者均属**感知缺口**，不属**证据缺口**。看得见 ≠ 可用于裁决。

---

## 4. Production Call-Path Contract（冻结现状与改动定位）

### 4.1 冻结调用链

```
RunnerService / HeadlessRunner            shell/runner_service.py, shell/headless_runner.py
   └─► execute_runtime_mediator ──► runtime_mediator.Mediator(CoreMediator)
          ctor: OCR 先强制 off，super().__init__ 后换装 ProductionShadowClient   [rm:61-88]
          prepare_live_dependencies() 全绿才放行                                 [rm:101-210]

   ├─ tick ─► _tick_main_line   [rm:295-340]   核心仲裁先行 + 活性看门狗（安全）
   ├─ tick ─► _tick_panel_fsm   [rm:475-489]   物理面板停滞看门狗（安全）
   └─► _find_reward_choice      [rm:771-820]   ⚠ 含 post-hoc 软策略覆盖（§5.2）
          └─► CoreMediator._find_reward_choice
                 └─► _ocr_reward_choice                          [med:3046-3120+]
                       ├─ _ocr_panel_slots / _slots_to_candidates
                       ├─ _extract_live_set_progress             [med:3014]
                       ├─ _bond_bar_occupancy → free_slots       [med:2990 / 3060]  ⚠ §6.4
                       ├─ _panel_has_giveup / _panel_can_refresh [med:2787 / 2802]
                       ├─ _policy_settings() (cached once)       [med:2622-2638]    ⚠ §4.3
                       ├─► choice_policy.choose_action(...)      [cp:624-665]
                       ├─ 第二帧确认门（reason 子串驱动）         [med:3081-3095]    ⚠ §4.4
                       └─► _policy_decision_to_hit(...)          [med:2867-2956]    ⚠ §5.3
   └─► act_click / act_key / act_right_click                     [rm:710-733]
          └─ PendingAction(kind, target_id, deadline, verifier)  [interaction_surface.py:107-129]
                └─ Panel FSM: WAIT_MUTATION → _confirm_panel_choice_action   [rm:491-496]
                      └─ _commit_pending_*_cards → _bond_cards_owned.append  [rm:702-708] ⚠ §6.5
```

### 4.2 具备真正 safety authority 的位置（**必须原样保留**）

| 位置 | 机制 | 为何是执行安全 |
|---|---|---|
| `rm:101-210` | `prepare_live_dependencies()`：client / start(×2) / ping / warmup / health 全绿才允许 LIVE 业务输入 | 感知未就绪 ⇒ 一切决策不可信；fail-closed |
| `rm:267-293` | 双帧 HUD 闩锁；post-game 或非 HUD ⇒ 清零；**异常 ⇒ 清零** | UNKNOWN / 异常绝不转成输入授权（全仓正面范本） |
| `rm:329-335` | ESC 预算 `_RUNTIME_WATCHDOG_MAX_ESC_ATTEMPTS = 2`，耗尽 ⇒ `Phase.ERROR` | 有界机械重试 + fail-closed |
| `rm:302-309` | 核心仲裁永远先跑；仅 `_tick_input_executed` 重置预算 | 输入成功 ≠ 业务成功，已内建 |
| `rm:391-393` | `_hide_fallback_hit()` 恒返回 `None` | 禁止未验证固定坐标点击 |
| `rm:438-473` / `405-436` | 物理面板停滞看门狗 → Fail-Forward → Fail-Closed | 已删除 3s 品质盲选（盲选=乱拿） |
| `rm:626-645` | `_find_stage_start()` 要求正向高亮确认 | **"SendInput success alone is not selection proof"** 的现成实现 |
| `rm:501-535` | 已定性面板上禁止 `_rarity_choice` 兜底 | 防止把三选一当进化弹窗盲点 |
| `med:2772-2778` | `_bump_choice_attempts()` 只在成功执行后计数 | 预算记账不被幽灵动作污染 |

以上均**不经 PolicyAction**，不受 §10 动作合同约束，保持原样。

### 4.3 MechanicsPolicyView：双重断线

**断线一（组装 / call-site）**：`a3bc4cd:src/shuabao/mediator.py:930` 构造 `self._mechanics_view`，
全仓生产代码**再无第二处读取**；唯一装配点 `med:2630-2638` 调用 `assemble_policy_settings(...)` 时
**不传 `mechanics_view=`** ⇒ `PolicySettings.mechanics_view = None` ⇒ `_mechanics_view_of()` 返回
`MechanicsPolicyView.empty()`。消费侧 schema 完好（`cp:248/374/385/534/744-748/837`）。

**断线二（evidence gate，独立成立）**：`config/game_mechanics_kb.json` 顶层 `wired_to_decision = false`，
递归扫描同时满足 `live_verified is True AND wired_to_decision is True` 的对象数 = **0**
⇒ 即使接上线，view 仍为空。

**验收要求**：仅修 call-site 得到**零可观测行为变化**。接线的验收必须绑定
"KB 中至少存在 1 条 dual-gated fact 且该 fact 改变了一个可复现的排序"（§11.1 L1-11 / §11.3 L3-01/02）。
否则即为假完成信号。

### 4.4 reason 自由文本进入控制平面（必须消除）

```
a3bc4cd:src/shuabao/mediator.py:3081-3095
    reason = str(decision.reason or "")
    skip_confirm = "差一张合成" in reason or "已持有合成" in reason
    if owned and not skip_confirm and decision.action in {SELECT_SLOT, REFRESH}:
        ...  return None      # 要求第二帧确认
```

一个中文子串匹配决定是否跳过"第二帧确认"这道防误点闸门。产出方为
`cp:1170`（`羁绊差一张合成秒选…`）与 `cp:1235`（`羁绊已持有合成优先…`）。
**任何对这两条文案的措辞改动都会静默改变安全门行为**，且无测试能捕获措辞漂移。

**改造要求见 §5.4。**

---

## 5. Authority Model

### 5.1 权威原则（Authority Principle）

> **Runtime 可以拒绝 unsafe execution；但 Runtime 不得再用第二套软策略，
> 推翻统一 policy 的合法 soft decision。**

操作化为三条可验收规则：

1. Runtime 对策略输出的合法返回**只有两种**：`EXECUTE(request)` 与 `REFUSE(safety_reason_code)`。
   **不存在 `SUBSTITUTE_PREFERENCE`，不存在任何形式的语义替换。**
2. Runtime 的局内状态**只能作为输入注入**统一策略，**不得**在策略输出后二次裁决。
3. `REFUSE` 之后不得直接执行别的动作；必须走 §5.3 的 re-decision 循环。

### 5.2 Runtime 第二套软策略（必须收回）

| 位置 | 性质 | 处置 |
|---|---|---|
| `rm:738-743` `_policy_settings()`：`replace(base, bond_presets=remaining)` | **状态注入（正确模式）** | **保留并推广** |
| `rm:756-769` `_maybe_open_choice_panel()`：预设拿齐即跳过羁绊面板 | 路线 / 机会成本判断，属 soft preference | **上移**为 policy 输出 `CLOSE(reason_code=ROUTE_BOND_COMPLETE)` |
| `rm:788-820` `_find_reward_choice()`：策略返回后用自己的 whitelist 复检，hard 模式下把选卡替换为关闭 | **决策后覆盖，最明确的越权**；与 `cp:1211-1216` 逻辑重复 | **删除覆盖**，改为状态注入 |

### 5.3 REFUSE → fresh re-decision（取代一切语义替换）

冻结系统在 `a3bc4cd:src/shuabao/mediator.py:2917-2947` 存在如下替换路径：
`REFRESH → GIVEUP`、`REFRESH → CLOSE`、`GIVEUP → CLOSE`。
这些是执行层在**语义层**改写动作（刷新 ≠ 放弃 ≠ 关闭，业务后果完全不同）。**全部废止。**

```
Runtime 对策略输出只有两种合法返回：
  EXECUTE(request)
  REFUSE(safety_reason_code)
      → 丢弃本次 decision
      → 采集 fresh observation（含 §6.3 action_capabilities 复测）
      → 将新的 capability observation 写入 snapshot
      → 推进 state_version
      → 以新 snapshot 重新调用 choose_action
```

**REFUSE 循环的强制约束（防死循环）**

```
R-1  REFUSE 后**必须**先写入新的 capability observation 并推进 state_version，
     才允许 re-decision。禁止在同一 state_version 上重复 decide。

R-2  禁止 deterministic REFUSE loop：
     若 (state_version 所依据的事实集, decided_action, refuse_reason_code) 与上一轮完全相同，
     即为确定性重复，**不得**再次 re-decision。

R-3  无新事实时的收口：
     → 进入 bounded WAIT（受 max_waits 约束，§10.7）
     → WAIT 预算耗尽仍无新事实 ⇒ fail-closed（交由 §4.2 安全链处理）
     ★禁止无限 re-decision，禁止无限 WAIT

R-4  `substituted_from` 字段保留在 schema 中，v0.1 期望取值**恒为 null**；
     非 null 即视为合同违规，应有断言。
```

### 5.4 结构化 reason code 替代 reason 文本

```
PolicyDecision(
  action,
  index,
  reason_code:   ReasonCode        # 封闭枚举，★唯一允许进入控制平面的字段
  reason_params: Mapping           # 结构化参数（slot_name / family_id / x / y / refresh_ordinal / …）
  explanation:   str               # 人类可读，★控制平面禁止读取（建议加断言或 lint）
)
```

v0.1 最小 `ReasonCode` 集合（由现有 reason 文案一一映射）：

```
SKILL_HOLD_NO_CONFIG          ← cp:652
SKILL_HOLD_BUDGET_EXHAUSTED   ← cp:654-661
BOND_MERGE_IMMINENT           ← cp:1170     ★驱动 skip_confirm
BOND_ALREADY_OWNED            ← cp:1235     ★驱动 skip_confirm
BOND_MUST_TAKE                ← cp:1224
BOND_BASE_NOT_READY           ← cp:1189/1191
BOND_ADVANCED_GROUP_ACTIVE    ← cp:1208/1210
BOND_PRESET_MISS_REFRESH      ← cp:1260
BOND_WHITELIST_BLOCKED        ← cp:1263
PRESET_HIT                    ← cp:1250
SET_PROGRESS_PRIORITY         ← cp:1268
QUALITY_FALLBACK              ← cp:1280
TREASURE_MUST_TAKE            ← cp:1160
NO_SAFE_CANDIDATE             ← cp:1282
ROUTE_BOND_COMPLETE           ← 新增，接收 rm:756-769 上移的语义
```

`safety_reason_code`（REFUSE 专用，与上表不同命名空间）至少包含：

```
NO_TRUE_CLOSE_AFFORDANCE      当帧无已验证 true_close_affordance
NO_TARGET_AFFORDANCE          目标 affordance 不存在（刷新 / 放弃 / 槽位）
OCR_NOT_READY                 prepare_live_dependencies 未通过
SURFACE_UNTRUSTED             surface_type / window_identity 不可信
PENDING_IN_FLIGHT             存在未结算 PendingAction
UNHANDLED_SURFACE             出现无 wired handler 的表面（如 REPLACE_MODAL）
```

**验收**：`skip_confirm` 判据从子串匹配改为
`decision.reason_code in {BOND_MERGE_IMMINENT, BOND_ALREADY_OWNED}`，并补一条测试证明
**改写 explanation 文案不改变任何控制行为**（§11.3 L3-11）。

---

## 6. DecisionSnapshot / ObservationSnapshot

### 6.1 标识与版本

```
decision_id          DecisionId       全局唯一；每次 choose_action 调用生成一个
state_version        int              单调；任何 ledger / inventory / session / capability 变更即 +1
                                      ★REFUSE 后必须推进（§5.3 R-1）
observation_id       ObservationId    本次决策所依据的观测集合根 id
observed_at          epoch_seconds    观测采集时刻（非决策时刻）
decided_at           epoch_seconds    决策产出时刻
evidence_gen         int              ★复用冻结系统现存字段（trace 814/814、events 399/399 均有）
trace_tick_count     int              ★与 capture_tick_count 分列，禁止合并
capture_tick_count   int              ★
```

### 6.2 表面与窗口

```
surface_type    Fact<SurfaceType>
                CHOICE_PANEL | HUD | POSTGAME | MERCHANT | REPLACE_MODAL | ARCHIVE | UNKNOWN_SURFACE
                ★REPLACE_MODAL 为一等取值（感知 backlog，v0.1 可恒 UNKNOWN，但枚举位必须存在）
panel_kind      Fact<PanelKind>       skill | bond | treasure | UNKNOWN
window_identity Fact<{hwnd, title, width, height, layout_supported}>
                ★layout_supported 直接来自 LayoutTransform.is_supported（med:2992）
```

### 6.3 action_capabilities（typed，必需）

策略层不得凭猜测判断某个动作是否可执行。执行可行性必须以**类型化能力**进入快照：

```
action_capabilities {
  can_take_slot:        Fact<bool>[]     # 按 candidate_instance_id 对齐的逐槽位可点击性
  can_refresh:          Fact<bool>       # refresh_affordance 是否已验证存在
  can_giveup:           Fact<bool>       # giveup_affordance 是否已验证存在
  can_true_close:       Fact<bool>       # ★true_close_affordance 是否已验证存在
  can_temporary_hide:   Fact<bool>       # ★暂时隐藏 affordance 是否存在
                                         #   仅供 SAFETY_RECOVERY_TEMP_HIDE 与遥测使用
                                         #   ★禁止被 PolicyAction.CLOSE 消费
}
```

规则：

- 每一项均为 `Fact<bool>`，UNKNOWN 合法且**不得**默认转 `true`（§8 U-6）
- `can_true_close` 与 `can_temporary_hide` 是**两个独立字段**，禁止合并、禁止互相 fallback
- `REFUSE` 之后的 re-decision **必须**携带重新观测的 `action_capabilities`（§5.3 R-1）
- `can_take_slot[]` 的元素与 `candidates[]` 通过 `candidate_instance_id` 对齐，禁止用位置隐式对齐

### 6.4 路线、预算与容量

```
route_intent    Fact<RouteIntent>   configured：skills[] / bonds[] / cards[] / skill_priority /
                                    skill_custom_routes / bond_whitelist_mode / bond_must_take
                                    ★source 恒为 CONFIG，validity 恒 VALID
route_active    Fact<RouteActive>   observed/derived：base_ready(80%) / active_advanced_group /
                                    l1_cycle_step / presets_remaining
                                    ★必须与 route_intent 分列

budget_state    Fact<{ wood, gold, pills: int|UNKNOWN,
                       attempts, refreshes, waits: int,
                       max_attempts, max_refreshes, max_waits: int }>
                                    ★attempts/refreshes/waits 来自 SessionState（cp:539-559），
                                      source = DERIVED_LEDGER
                                    ★wood / gold / pills 在 v0.1 恒 UNKNOWN

next_refresh_cost Fact<int>         ★全新字段。v0.1 无 validated observer ⇒ 值恒 UNKNOWN
draw_cost         Fact<int>         ★全新字段。v0.1 无 validated observer ⇒ 值恒 UNKNOWN
                                    ★二者永久独立：禁止共用 key、禁止互相 fallback、
                                      禁止共用同一 ROI / parser
                                    ★禁止 hard-code 任何常量（见 §6.4.1）

free_slots      Fact<int>           ★source 必须为 PIXEL_HEURISTIC
free_slots_uncertainty {
    occupied_cells: int | UNKNOWN, cells_probed: 10,
    min_pixels_threshold: int, per_cell_margin: float[] | UNKNOWN,
    layout_supported: bool }
```

#### 6.4.1 成本字段禁止 hard-code

定点复核样本中，`draw_cost` 观测值为 100，`next_refresh_cost` 观测到 40 / 60 / 100 且**按 panel
episode 重置**（非全局单调）。

**这些是 run-linked 观测值，不是机制常量。**

```
★ runtime 禁止 hard-code 100 作为 draw_cost 的默认值、fallback 或校验基准
★ runtime 禁止把 40/60/80/100 写成常量序列，禁止据此推断"第 n 次刷新成本"
★ 二者在 v0.1 均为 Fact<int> 且值恒 UNKNOWN，直到 L4-02 标定 validated observer
```

#### 6.4.2 free_slots 的产出是像素启发式

`a3bc4cd:src/shuabao/mediator.py:2990-3008` 的 `_bond_bar_occupancy` 是硬编码 10 个像素格
（`cx ∈ {603…1071}`, `y ∈ [635,680]`）的 HSV 饱和度 / 明度阈值统计，数的是"有颜色的格子"，
不是卡牌身份。它只在 frame 缺失或 layout 不支持时返回 `None`，其余一律返回精确整数 0–10，
**无置信度**。其 docstring 自称 "used only as an overflow guard"，但它实际是策略容量门的唯一权威输入。

⇒ `free_slots_uncertainty` 不是锦上添花，是**修正一个已存在的过度自信**。

### 6.5 库存与进度

```
acquisition_history  Fact<Counter<canonical_card_id | family_id>>
                     ★= 冻结系统的 _bond_cards_owned（rm:688-700），append-only
                     ★合同显式声明：本字段永不递减，仅 set_phase(MAIN_LINE) 整体清空
                     ★canonical_card_id 为 UNKNOWN 时，仅以 family_id 计数；
                       ★禁止用 candidate_instance_id 作为 key（§2.2）

active_inventory     Fact<Counter<canonical_card_id | family_id>> | UNKNOWN
                     ★全新，与上者物理分离
                     ★v0.1 初值 UNKNOWN，★禁止用 acquisition_history 顶替

persistent_effects   Fact<list<EffectId>> | UNKNOWN
                     ★合成完成后的常驻加成；v0.1 无 GT ⇒ UNKNOWN

progress             Fact<map<family_id, {x, y: int|UNKNOWN, surface_type, entity_type, raw_text}>>
                     ★x/y 必须随 surface_type + entity_type 一同存储
                     ★禁止全局统一 x/y parser（§7.2）
```

**已知缺陷（必须修）**：冻结系统的 `_bond_cards_owned` 只有 `.append`，唯一移除路径是
`set_phase(MAIN_LINE)` 的整体 `.clear()`（`rm:748-753`）。卡组合成完毕、被吞噬、槽位释放时
**没有任何 decrement**。而该 tuple 直接喂进三个决策分支：
`cp:1285-1296`（80% 基础门）、`cp:1228-1236`（已持有合成优先）、`cp:1130`（满槽 merge 放行）。
一张已合成消失的卡会永久污染这三处。**这是 `acquisition_history ≠ active_inventory` 的具体后果。**

---

## 7. Candidate Schema

### 7.1 字段

```
candidate_instance_id     ★必填。observation_id + panel_kind + slot_index（§2.2）
slot_index                int（仅作 instance 构成与点击定位，★不进 canonical）
candidate_kind            Fact<CandidateKind>
                          SKILL_CARD | BOND_STACK | BOND_SET_MEMBER | TREASURE | HERO | UNKNOWN_KIND
route_membership          Fact<RouteId>          ★不透明 id，禁止用中文卡名
family_id                 Fact<FamilyId>         ★v0.1 必需
canonical_card_id         Fact<CardId>           ★仅在 card-level identity 足够确定时赋值，否则 UNKNOWN
member_id                 Fact<MemberId>?        ★optional，不参与 legality
member_id_confidence      float | UNKNOWN        ★optional
member_id_validity        Validity               ★optional，v0.1 恒 UNKNOWN 亦合规
rarity                    Fact<Rarity>           ★skill 侧存在 catalog 覆盖（cp:707-715），
                                                   须记 source = CATALOG vs OCR_BORDER
                                                 ★禁止参与 canonical 拼装（§2.2）
title_text_raw            Fact<str>              ★原样保留（含截断样本）
progress_text_raw         Fact<str>
progress_parsed           Fact<{x, y: int|UNKNOWN}>
effect_text_raw           Fact<str>              ★负面宝物判定输入（cp:102-125）
zero_cost                 Fact<bool>             ★现存字段（cp:184），满槽分支依赖
confidence                float | UNKNOWN
validity                  Validity
uncertainty               { … }
```

### 7.2 x/y 不得使用全局统一 parser

本 run 内 OCR 表面已出现 4 种 `(kind, layout)` 组合：`(bond,4)=61`、`(skill,3)=48`、
`(skill,4)=6`、`(treasure,3)=2`。同一 `x/y` 正则跨面板即语义不同，至少已识别：
same-name bond stack progress、family progress indicator、quest kill count、stage wave、HP/stat ratio。

```
★ regex x/y 本身不构成业务 authority
★ 必须以 surface_type + entity_type + observation schema 联合解释
★ x 或 y 任一 UNKNOWN ⇒ 整个 progress fact 的 validity = UNKNOWN，不得半解释
```

### 7.3 family-level 足够，member-level 可选

- `family_id = 肉身成圣` **本身即足以**让候选进入模型并被 family-scoped rule 正常裁决
- `member_id` 为 UNKNOWN **不得**阻塞 family-level 决策
- 同帧多个同 family 候选由 `candidate_instance_id` 区分，**不需要**先解出 member 才能行动
- **禁止**在策略中写入任何形如"肉身 3 张 / 4 张 / 完成释放 N 槽"的常量（§3.3、§12）

---

## 8. UNKNOWN 传播

**UNKNOWN 绝不得默认转换为 `0` / `False` / `empty` / `available` / `legal` / `confirmed`。**

| # | 条款 |
|---|---|
| U-1 | `free_slots == UNKNOWN` **不得**与 `free_slots >= 3` 走同一分支；UNKNOWN ⇒ 施加最保守容量压力（等价 HL-7，见 HL-8）。★修 `cp:1122` 的 `if free is None or free >= 3: return slots` |
| U-2 | `active_inventory == UNKNOWN` **不得**回落为 `acquisition_history` |
| U-3 | `next_refresh_cost == UNKNOWN` **不得**当作 0 或"可负担"；UNKNOWN 下成本比较不成立，只能退回次数预算 |
| U-4 | `draw_cost == UNKNOWN` **不得**由 `next_refresh_cost` 顶替，反向亦然 |
| U-5 | identity scope UNKNOWN ⇒ 按 §9.1 HL-1 判定；**宝物侧 `allow_unnamed=True`（`cp:1275`）为已知例外**，v0.1 需显式重申或收紧，**不得静默继承** |
| U-6 | `action_capabilities` 中任一 `Fact<bool>` 为 UNKNOWN ⇒ 视为**不可用**，不得默认 `true` |
| U-7 | `panel_kind == UNKNOWN` 或 `surface_type == UNKNOWN_SURFACE` ⇒ 零输入（`rm:395-403` 已是正确先例） |
| U-8 | 分类器**抛异常** ≡ UNKNOWN，不得转成授权。`rm:286-290` 已正确；**须推广到 `PendingAction.is_confirmed`** —— 后者当前 `except: return False`（`interaction_surface.py:121-125`），把异常折成 False，应改为 `UNCONFIRMED` 而非 `CONFIRMED=False` |
| U-9 | `progress_parsed.x` 或 `.y` 任一 UNKNOWN ⇒ 整个 progress fact `validity = UNKNOWN` |
| U-10 | `GUIDE_TIER` 来源的任何字段 `validity` 恒 `OUT_OF_SCOPE`，永不进 legality |
| U-11 | `UNSTRUCTURED_RUN_LINKED` 事实**不得**进入 live legality；仅可用于离线设计、保守 gate 与感知 backlog |

---

## 9. Legality / Preference / Execution

**唯一顺序（不可交换、不可短路）：**

```
hard legality  →  soft preference / action comparison  →  execution
```

### 9.1 Hard legality（拒绝即零输入；任一命中即终止，不进入 soft 层）

| 代号 | 条件 |
|---|---|
| **HL-1** | **当前规则所需的 identity scope 为 UNKNOWN ⇒ 禁止 TAKE。** scope 按规则实际依赖的最小层级判定：<br>　`family-scoped rule` 需 `family_id ≠ UNKNOWN`（canonical / member UNKNOWN **不阻断**）<br>　`card-scoped rule` 需 `canonical_card_id ≠ UNKNOWN`（member UNKNOWN **不阻断**）<br>　`route-scoped rule` 需 `route_membership ≠ UNKNOWN`<br>　`member-scoped rule` v0.1 不存在此类规则；若出现即为合同违规<br>　执行绑定始终需 `candidate_instance_id ≠ UNKNOWN`，否则无点击目标 ⇒ `NOT_SENT`<br>　★**过度要求 identity 精度本身是一种越权** |
| HL-2 | 用户显式禁用（`bond_whitelist_mode=hard` 且不在白名单；skill 焦点集外；`treasure_negative_*`） |
| HL-3 | `surface_type == UNKNOWN_SURFACE` 或 `validity != VALID` |
| HL-4 | `panel_kind` / `window_identity` / target 不可信（hwnd 变化、layout 不支持、双帧未确认） |
| HL-5 | `budget_state` **明确**不足（UNKNOWN 不等于不足，见 U-3；UNKNOWN 走 HL-8） |
| HL-6 | 存在未完成 `pending`（`PendingAction` 未 confirm 且未过 deadline）⇒ 不重复提交 |
| **HL-7** | **`free_slots == 0` 且 replacement lifecycle 未被当前执行链支持 ⇒ 禁止 TAKE** |
| **HL-8** | **`free_slots == UNKNOWN` ⇒ 施加与 `free_slots == 0` 同级的保守约束（等价 HL-7）** |
| HL-9 | 明确已验证不可执行（`fail_closed_actions`：`-zs` 自杀、聊天切剑形态、装备栏左键；`script_rule = fail_closed_never_type`） |
| HL-10 | OCR bootstrap 未健康（`prepare_live_dependencies` 未通过） |
| HL-11 | `active_inventory == UNKNOWN` 时，任何**依赖 active 状态**的 TAKE 理由（如"合成即将完成"）降级为不可用 |
| HL-12 | 目标动作所需的 `action_capabilities` 项为 `false` 或 UNKNOWN（U-6） |

> HL-7 / HL-8 是本合同新增的 hard gate；其余为把冻结系统已有的安全语义**上移**到统一 legality 层。
> HL-7 的依据是实证的：满槽状态下策略经 merge 分支放行 TAKE，游戏抛出替换卡牌模态，
> 而感知层完全读不到该模态（详见证据附录）。

### 9.2 Soft preference（仅在通过全部 hard legality 的候选之间比较）

顺序即优先级：

```
 1. bond_must_take / treasure_must_take                cp:1214, 1157
 2. 基础 80% 门（bond_base_completion_ratio）           cp:1285-1296  ★须改用 active_inventory（U-2）
 3. 高级组顺序（bond_advanced_groups / active_adv）     cp:1193-1202, 1299+
 4. preset rank（配置顺序）                              cp:751-757
 5. near completion value（差一张合成）                  cp:1165-1171  ★须改用 active_inventory
 6. growth value / set_progress                         cp:1265-1268
 7. rarity（skill 侧 catalog 优先）                      cp:707-715, 1274-1280
 8. route preference（skill_route_preferences）          cp:243-244, 470-497
 9. skill 链条 / 角色 / 存档排序                          cp:768-780 及 skill_catalog
10. habit preference（★仅打平局）                        cp:1245 → _match_preset
11. refresh opportunity cost                            ★新增；仅当 next_refresh_cost.validity == VALID
                                                          且 draw_cost.validity == VALID 时启用；
                                                          否则该键整体不参与排序（U-3 / U-4）
12. slot index 升序（最终确定性 tie-break）              cp:30-31
```

**关键原则：soft preference 不能创造 safety authority。**
任何 soft 键不得把未通过 hard legality 的候选变为可选；不得把 UNKNOWN 变为 available；
不得在策略输出之后由任何下游组件重新裁决（§5.1 规则 2）。

### 9.3 Execution

- 执行层仅接受 `(action, index/candidate_instance_id, reason_code)`，**不接受 explanation**
- 执行层仅有 `EXECUTE` 与 `REFUSE(safety_reason_code)` 两种返回（§5.1 规则 1）
- `REFUSE` 后走 §5.3 的 R-1…R-4 循环

---

## 10. Action / Outcome Contract

### 10.1 Outcome 等级（封闭枚举，严格有序，不可跳级）

```
NOT_SENT                          决策产出但未形成 request（hard legality 拒绝 / REFUSE / idle）
CANCELLED                         request 已形成，输入被取消
                                    实证子态：CANCELLED_SENDINPUT_FAILED
                                              CANCELLED_WINDOW_CHANGED
                                              CANCELLED_WINDOW_OBSCURED
SENT_NO_FRESH_EVIDENCE            输入已发，但无满足 freshness 合同的 after-observation
FRESH_SURFACE_SEEN_BUT_AMBIGUOUS  有 fresh 观测，但无法归因到本 request
DERIVED_BUSINESS_OUTCOME          fresh 观测 + request 关联 + 语义业务变化
STRUCTURED_CONFIRMED              observer 明确验证 expected_postcondition
FAILED                            fresh 观测明确证否
UNKNOWN                           以上皆不可判定
```

**禁止的单项确认（任一单独出现均不得判为 CONFIRMED）**

```
✗ click success              ✗ SendInput success          ✗ act_key / act_click 返回 True
✗ same-frame mutation        ✗ before/after frame ID 不同
✗ frame_unchanged == false   ✗ raw pixel difference
✗ synthetic test             ✗ 静态文本猜测                ✗ 图像参考包静态截图
✗ offer absence（候选表面中该 family 缺席）—— 见 §10.4 分支 B
```

### 10.2 Freshness 合同

after-observation 必须**全部**满足：

```
F-1  observation.request_id      == request.request_id
F-2  observation.observed_at      >  request.sent_at
F-3  observation.evidence_gen     >  request.evidence_gen
F-4  observation.window_identity == request.window_identity      （hwnd + size + layout_supported）
F-5  observation.surface_type / expected_roi 与 request 声明一致
F-6  observation.fingerprint     != request.baseline_fingerprint  （必要非充分）
F-7  存在 observer-specific business mutation（见各动作 expected_postcondition）
F-8  完成态分支（§10.4 分支 B）额外要求：
     observation.observed_at - request.sent_at >= settling_window
     ★settling_window 由 L4 标定；v0.1 之前不得设常数并据此判 CONFIRMED
```

**F-1…F-8 全部满足才允许晋升到 `DERIVED_BUSINESS_OUTCOME` 或 `STRUCTURED_CONFIRMED`。
缺任一 ⇒ 最高只能到 `SENT_NO_FRESH_EVIDENCE`。**

> 落地提示：冻结系统的 freshness 采集**大体是工作的**（227 个 action 事件中 224 个的 after-frame
> 时间戳前进，Δ 中位 0.867 s）。缺的不是采集，是**强制约束**——没有任何 gate 要求 after-frame
> 必须晚于 request，所以 3 例违规静默通过。**这是加断言，不是重建管道。**

### 10.3 Request 结构

```
request_id            RequestId
decision_id           DecisionId       ← DecisionSnapshot
state_version         int              ← DecisionSnapshot
decided_action        PolicyAction
executed_action       PolicyAction     ★v0.1 必须恒等于 decided_action
substituted_from      PolicyAction?    ★v0.1 期望恒为 null；非 null 即合同违规（§5.3 R-4）
reason_code           ReasonCode       ★结构化
explanation           str              ★控制平面禁止读取
target {
  candidate_instance_id  ★observation-local target reference（§2.6）
  affordance_kind        slot / refresh / giveup / true_close
  button_template        str?
}
sent_at               epoch_seconds
evidence_gen          int
baseline_fingerprint  str
window_identity       { hwnd, size, layout_supported }
input_status          SUCCESS | CANCELLED_SENDINPUT_FAILED | CANCELLED_WINDOW_CHANGED
                      | CANCELLED_WINDOW_OBSCURED | NOT_SENT
lifecycle             ActionLifecycle  ★填充冻结系统已存在但零使用的枚举
outcome               OutcomeLevel
outcome_evidence      list<ObservationId>
```

**`ActionLifecycle` 复用说明**：`a3bc4cd:src/shuabao/interaction_surface.py:12-30` 已定义
`OBSERVED / ACTION_AUTHORIZED / INPUT_SENT / VERIFYING / CONFIRMED / UNCONFIRMED / RECOVERING`，
被 `cp:133` 与 `med:102` 各导入一次、使用零次。**应填充它，不得新建第四个枚举。**

### 10.4 TAKE

| 项 | 定义 |
|---|---|
| eligibility | 通过 HL-1…HL-12 全部；特别地 HL-7 / HL-8 硬阻断 |
| request formation | `target.candidate_instance_id` 必填；`family_id` 必填且 ≠ UNKNOWN（family-scoped 规则下）；`member_id` 可 UNKNOWN |
| input_sent / cancelled | `CANCELLED_*` ⇒ outcome 直接 `CANCELLED`，**禁止**继续做 after-observation 归因 |
| fresh observer | F-1…F-8 |
| confirmed / failed / ambiguous | 见下方分支 |

**expected_postcondition 分支**

```
A) 非完成态     baseline.x < y - 1
   → 期望 x == baseline.x + 1，family 仍在表面
   → F 全满足 ⇒ STRUCTURED_CONFIRMED

B) 完成态触发   baseline.x == y - 1                                    ★关键分支
   → ✗ 禁止期望 x == y（该状态在观测流中从不可见）
   → ✗ 禁止以候选 surface 中该 family 缺席作为任何等级的 completion evidence
        理由：候选表面的构成是抽取 / 刷新的产物。一个 family 不再被 offer，可以仅仅因为
        随机池未抽到、刷新换页、面板关闭或路线切换。**Offer absence 不证明 stack completion。**
   → completion 只能由 request-correlated 的业务 surface 推导，至少其一：
        · active_inventory 中该 family 的 stack 归零 / 合并
        · progress surface 上该 family 的条目消失或重置（★羁绊栏 / 进度面板，非选卡候选表面）
        · persistent_effect 出现（套装效果生效）
        · 羁绊栏占用数下降（自动吞噬）
   → 上述 surface 在 v0.1 均为 UNKNOWN 或无 validated observer
     ⇒ 分支 B 的 outcome 上限 = DERIVED_BUSINESS_OUTCOME
     ⇒ 证据不足时 = FRESH_SURFACE_SEEN_BUT_AMBIGUOUS
     ⇒ ★v0.1 分支 B 不可达 STRUCTURED_CONFIRMED；解禁条件 L4-01
   → F-8（settling_window）强制适用

C) 满槽分流     free_slots == 0（或 UNKNOWN）
   → 期望 surface_type 迁移为 REPLACE_MODAL
   → v0.1 该模态无 wired handler ⇒ HL-7 / HL-8 应已在 legality 层阻断
   → 若仍到达此处 ⇒ outcome = FAILED(UNHANDLED_SURFACE)，★非 AMBIGUOUS

D) 异质 set     family_id ∈ GT-blocked 集合（如 肉身成圣）
   → expected_postcondition = UNKNOWN
   → 上限 FRESH_SURFACE_SEEN_BUT_AMBIGUOUS
```

**观测 gap 处理**：观测流只在面板打开瞬间产生。derived observer **必须容忍 gap**，
`Δx > 1` 时标 `gap = true` 并**禁止**归因为单次 TAKE。

### 10.5 REFRESH

| 项 | 定义 |
|---|---|
| eligibility | `action_capabilities.can_refresh == true`（UNKNOWN 视为不可用，U-6）**且** `refreshes < max_refreshes`。★`next_refresh_cost.validity != VALID` 时**禁止**做成本-收益比较（U-3），只走次数预算 |
| request formation | `target.affordance_kind = refresh`；记录 `refresh_ordinal` |
| expected_postcondition | 候选集指纹变化（`slot_fingerprint`，`cp:668-679`；`med:2918` 已保存 `_choice_fp_before_refresh`，**现成 baseline**）**且** `next_refresh_cost` 单调上升。后半条 v0.1 恒 UNKNOWN ⇒ 只用前半条 |
| confirmed | `STRUCTURED_CONFIRMED` 需两条都满足 ⇒ **v0.1 不可达**；可达上限 `DERIVED_BUSINESS_OUTCOME` |
| failed | 指纹未变且预算未扣 |
| ⚠ | **禁止**建立"`refresh_cost >= 100` + 空槽"的特殊 authority（`HIGH_COST_PLUS_FREE_SLOT_GT` 为 BLOCKED） |

### 10.6 CLOSE / HIDE / SAFETY_RECOVERY_TEMP_HIDE

**绑定规则**

```
CLOSE  仅可绑定 true_close_affordance
       ★禁止绑定任何 temporary_hide_affordance
       当帧 action_capabilities.can_true_close != true 时：
         → REFUSE(NO_TRUE_CLOSE_AFFORDANCE)
         → 丢弃本次 decision → 写入新 capability observation → 推进 state_version
         → fresh re-decision（§5.3 R-1…R-4）
         → 本 tick 零输入；outcome = NOT_SENT

HIDE   GATED_UNAVAILABLE
       ★v0.1 不产出该动作
       ★因此 temporary_hide_affordance 在 v0.1 中没有任何合法 PolicyAction 绑定
         （仅可作为 surface 识别特征存在于观测中，并填充 can_temporary_hide 供遥测）
       ★expected_postcondition = UNKNOWN；outcome 上限 = UNKNOWN
       ★解禁条件：L4-10

SAFETY_RECOVERY_TEMP_HIDE     见 §2.5
       ★不是 PolicyAction；独立 telemetry / reason / outcome
       ★不计入 policy CLOSE 计数，不计入 policy HIDE 计数
       ★不得声称保留 offer / price / 面板可原样再来
```

**已知后果，明确接受**：冻结系统 `_close_current_panel` / `_verified_panel_close` 依赖的模板集合
（`a3bc4cd:src/shuabao/runtime_mediator.py:362-370`）几乎全部属于 `temporary_hide_affordance`。
因此 v0.1 初期 `CLOSE` 的可执行率将显著下降，大量落 `REFUSE(NO_TRUE_CLOSE_AFFORDANCE)`。
**这是正确行为**：宁可零输入并重决策，也不得用语义不等价的按钮冒充关闭。
`true_close_affordance` 的识别与验证列入感知 backlog，其解禁与 L4-10 **互相独立**——
**不得以"先让 CLOSE 能跑"为由回退本条。**

**禁止记为 HIDE 的动作**（重申）：`RuntimeWatchdog-EscUnstuck`、`OpenBondPanel`、`OpenSkillPanel`、
`CloseArchivePanel`、`PanelFailForward-*`、任何 recovery / unstuck。

### 10.7 GIVEUP / WAIT

**GIVEUP**

| 项 | 定义 |
|---|---|
| 当前状态 | 未实证。`allow_skill_giveup` 默认 `False`（`cp:230, 362`）；技能侧恒走 `_skill_hold_or_hide`（`cp:690-697`） |
| eligibility | `action_capabilities.can_giveup == true` **且** 用户显式开启 `allow_skill_giveup` |
| expected_postcondition | 面板消失 **且** 该 panel episode 不再复现 |
| outcome 上限 | `UNKNOWN` |
| ⚠ | 不得伪装成常规可用动作；v0.1 默认可达性 = 关闭 |

**WAIT**

| 项 | 定义 |
|---|---|
| eligibility | `waits < max_waits`（`cp:128, 549`） |
| request formation | **零输入动作**：不产生 request_id，不产生 input |
| 记账 | 只增 `waits`，**不增 `attempts`**（`med:2759-2765` 已正确） |
| outcome | `NOT_SENT`（永远）；WAIT 不得晋升到任何 CONFIRMED 级别 |
| ⚠ | `max_waits` 耗尽必须落 `CLOSE` / `GIVEUP` / fail-closed，禁止无限等待（`cp:38-39` 已有此不变量，保留）。§5.3 R-3 的 bounded WAIT 复用同一预算 |

---

## 11. Acceptance Matrix

### 11.1 L1 · Pure policy unit（纯函数，无 I/O、无时钟、无读屏）

**能证明**：决策确定性与可复现性；hard legality 的拒绝行为；UNKNOWN 传播 U-1…U-11；
soft 排序键顺序；`reason_code` 与 `explanation` 的分离。
**不能证明**：任何感知正确性、执行结果、业务成功、freshness。

| # | 场景 | 断言 |
|---|---|---|
| L1-01 | family-scoped 规则下 `family_id = UNKNOWN` | 决策 ∈ {CLOSE, WAIT}，绝不 SELECT_SLOT |
| L1-01b | family-scoped 规则下 `family_id` 已知、`canonical_card_id = UNKNOWN`、`member_id = UNKNOWN` | **候选正常参与并可被 SELECT_SLOT**（HL-1 scope 判定，防越权阻断） |
| L1-01c | 同帧两个候选 family_id 相同、canonical 均 UNKNOWN | 二者由 `candidate_instance_id` 区分；决策可唯一指向其一 |
| L1-02 | `free_slots = UNKNOWN` | 与 `free_slots = 0` 同级保守；显式断言其 ≠ `free_slots = 3` 的行为 |
| L1-03 | `free_slots = 0` 且 replacement 未支持 | 不产出 SELECT_SLOT，即使候选是 merge 或 zero_cost |
| L1-04 | `next_refresh_cost = UNKNOWN, draw_cost = UNKNOWN` | 排序键 11 整体不参与；决策与不带这两字段时逐位相同 |
| L1-05 | `(cost=100, draw=100)` vs `(cost=40, draw=100)`；再交换二者取值 | 三者两两产生不同决策（证明未混淆、未 fallback） |
| L1-05b | 任意 `draw_cost` 取值 | 策略中不存在常量 100；不存在 40/60/80/100 常量序列 |
| L1-06 | `active_inventory = UNKNOWN`，`acquisition_history = {祝福:3}` | 不得触发"已持有合成优先"或 80% 基础门 |
| L1-07 | 同名 stack `progress = 2/3` | 命中 `BOND_MERGE_IMMINENT`；改 explanation 文案不改行为 |
| L1-08 | `family_id = 肉身成圣, member_id = UNKNOWN` | 候选可进入模型并被正常排序 |
| L1-09 | 同上 + 任何"肉身需 3 张 / 完成释放 N 槽"假设 | 策略中不存在该常量；`expected_postcondition = UNKNOWN` |
| L1-10 | `mechanics_view = empty` vs `= None` | 决策逐位相同（fail-closed 语义不变） |
| L1-11 | `mechanics_view` 含 1 条 dual-gated priority fact | 决策发生可复现的排序变化 |
| L1-12 | `guide`-tier 字段注入 | 被 `_DROP_KEYS` 丢弃，决策无变化 |
| L1-13 | x/y 相同但 `surface_type` 不同 | 产生不同解释；不存在全局 x/y parser |
| L1-14 | HIDE / GIVEUP | 默认配置下不出现在任何 soft preference 输出中 |
| L1-15 | `can_true_close = false / UNKNOWN` 且策略欲 CLOSE | 产出 CLOSE 后由执行层 REFUSE；**策略不得改选 temporary_hide** |
| L1-16 | 同一输入调用两次 | `PolicyDecision` 完全相同（纯函数不变量，`cp:29-31`） |

### 11.2 L2 · Recorded real-frame replay

**能证明**：OCR / 候选抽取在真实帧上的稳定性；候选级决策在真实分布上的行为；
outcome observer 对已录制语义变化的**相关性**归因能力。
**不能证明**：满槽 / 容量 / 预算分支；任何真实输入效果；任何 GT-blocked 机制；**因果**。

⚠ **前置事实**：现有 trace 只记录了 `ocr_suggestion`（132 tick，含 slots / rarity / confidence /
raw_text），**未记录** `free_slots` / `set_progress` / `can_refresh` / `owned_*` / `SessionState` /
`PolicySettings`。⇒ **L2 的第一个交付物是让 `DecisionSnapshot` 落盘**；在此之前 L2 只能覆盖候选级。
`tools/replay_treasure_desc_equivalence.py:5` 的 docstring 声称 trace 含 policy inputs，
**就本 run 而言该说法只对 slots/rarity 成立**，实现 Agent 不得据此假设 L2 已就绪。

| # | 场景 | 断言 |
|---|---|---|
| L2-01 | 回放 132 个 `ocr_suggestion` tick | 候选抽取逐字段稳定；`肉身成圣` 以 conf ≥ 0.98 被识别为 `family_id` |
| L2-02 | 截断样本 `-肉身成圣(0/` | `progress_parsed.y = UNKNOWN`，整个 progress fact `validity = UNKNOWN`，不得补 3 |
| L2-03 | 9 个 family 的 x 序列回放 | derived observer 给出 `DERIVED_BUSINESS_OUTCOME`；`Δx > 1` 的样本被标 `gap = true` 且不归因为单次 TAKE。★断言目标为**相关性可复现 + gap 正确标注**，非因果 |
| L2-04 | `CANCELLED_SENDINPUT_FAILED` 样本回放 | outcome = `CANCELLED`（不是 SENT_NO_FRESH_EVIDENCE，更不是 CONFIRMED）；F-2 断言触发 |
| L2-05 | 两个 Δ ≤ 0 的样本回放 | 因 F-2 / F-3 失败落到 `SENT_NO_FRESH_EVIDENCE` 或 `CANCELLED`；`SUCCESS` + 同帧复用的样本不得判为 CONFIRMED |
| L2-06 | 全 227 action 事件回放 | `STRUCTURED_CONFIRMED` 计数 = 0（证明 observer 不会凭空造确认） |
| L2-07 | `acquisition_history` vs `active_inventory` | 二者分别落盘且在某一时刻不相等 |
| L2-08 | 同帧两个同 family 候选（f0282 型） | 二者 `candidate_instance_id` 不同；`canonical_card_id` 允许同为 UNKNOWN；**不得**因 rarity 相同而误合并为同一 semantic 身份 |

### 11.3 L3 · RuntimeMediator production integration（真实装配，不发真实输入）

| # | 场景 | 断言 |
|---|---|---|
| L3-01 | `_policy_settings()` 装配 | `PolicySettings.mechanics_view` 不为 None |
| L3-02 | 同上 + 当前 KB | view 为 empty **且**该事实被显式记为 `MECHANICS_KB_DUAL_GATED_FACTS = 0` 的遥测，不静默 |
| L3-03 | runtime 收到统一策略的合法 soft decision（白名单外但 soft 模式合法） | runtime 不得替换；`executed_action == decided_action`；`substituted_from == null` |
| L3-04 | runtime 局内状态变化 | 通过 `replace(base, bond_presets=remaining)` 注入策略输入，非事后覆盖 |
| L3-05 | 羁绊预设拿齐 | 由 policy 输出 `CLOSE(reason_code=ROUTE_BOND_COMPLETE)`，非 runtime 私自跳过面板 |
| L3-06 | OCR bootstrap 失败 | 零业务输入；outcome = `NOT_SENT` |
| L3-07 | UNKNOWN / 黑帧 / transition 帧 | 双帧 HUD 闩锁清零；watchdog 不发 ESC |
| L3-08 | 分类器抛异常 | 等价 UNKNOWN，零输入 |
| L3-09 | ESC 预算耗尽 | 转 `Phase.ERROR`，不无限重试 |
| L3-10 | 满槽 + 未支持 replacement | legality 层即拒绝，**零 SendInput**；outcome = `NOT_SENT(HL-7)` |
| L3-11 | `skip_confirm` 判据 | 由 `reason_code` 驱动；改 explanation 文案行为不变 |
| L3-12 | 策略输出 CLOSE 但当帧只有 temporary_hide | `REFUSE(NO_TRUE_CLOSE_AFFORDANCE)`；**零输入**；不得点击暂时隐藏 |
| L3-13 | 同上，紧接 re-decision | 新 snapshot 携带重新观测的 `action_capabilities`；`state_version` 已推进 |
| L3-14 | 同一事实集 + 同一 action + 同一 refuse reason 连续出现 | **不得**再次 re-decision；进入 bounded WAIT；WAIT 耗尽 ⇒ fail-closed（R-2 / R-3） |
| L3-15 | fail-forward 使用暂时隐藏 | 记为 `SAFETY_RECOVERY_TEMP_HIDE`，独立 telemetry；policy CLOSE / HIDE 计数均不增；无 offer / price 保留声明 |
| L3-16 | 一次完整 panel episode | `DecisionSnapshot` 全字段落盘，含 `decision_id / state_version / observation_id / action_capabilities / candidate_instance_id / free_slots_uncertainty / route_intent / route_active` |
| L3-17 | `decide_bond_capacity` | **未被任何生产路径调用**（断言调用计数为 0） |
| L3-18 | 任一 legality 判定 | 其输入 Fact 的 representation 均为 `STRUCTURED`；无 `UNSTRUCTURED_RUN_LINKED` 事实进入 legality（U-11） |

### 11.4 L4 · Live Ground Truth（需 Owner 签批）

| # | GT 门 | 需要采集的最小证据 |
|---|---|---|
| L4-01 | `SAME_NAME_STACK_LIFECYCLE` 结构化确认 | 一次 TAKE 的 request_id 关联到 fresh 观测且 x 精确 +1；`STRUCTURED_CONFIRMED > 0` |
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

## 12. Ground Truth Gates

### 12.1 gated 的操作含义

以上 §11.4 的机制在 v0.1 中：

- **可以**有 schema 位置（字段存在）
- 值必须为 **UNKNOWN**
- **不得**参与 hard legality 的**放行**（只可参与**保守拒绝**，如 HL-7）
- **不得**参与 soft preference 排序
- `expected_postcondition` 必须为 `UNKNOWN`，outcome 上限为 `FRESH_SURFACE_SEEN_BUT_AMBIGUOUS`

### 12.2 状态总表

| 代号 | 状态 |
|---|---|
| `NO_STRUCTURED_POSTCONDITION_CONFIRMATION` | **TRUE** |
| `SEMANTIC_BUSINESS_OUTCOME_EVIDENCE` | **PRESENT** |
| `SAME_NAME_STACK_LIFECYCLE` | **STRONG_CORRELATIVE_EVIDENCE**（非因果，见 §12.3） |
| `HIGH_COST_PLUS_FREE_SLOT_GT` | BLOCKED_MISSING_GT |
| `HETEROGENEOUS_SET_LIFECYCLE` | BLOCKED_MISSING_GT |
| `FLESH_MEMBER_ROSTER`（3 张 / 4 张 / 第四成员） | BLOCKED_MISSING_GT |
| `FLESH_COMPLETION_SLOT_RELEASE` | BLOCKED_MISSING_GT |
| `AUTO_DEVOUR_TIMING` | BLOCKED_MISSING_GT |
| `FENGSHENBANG_INCREMENT` | BLOCKED_MISSING_GT |
| `FULL_SLOT_REPLACEMENT` | **VISUAL_OBSERVED / STRUCTURED_BLIND** |
| `HIDE_BUSINESS_SEMANTICS` | BLOCKED_MISSING_GT |
| `TRUE_CLOSE_AFFORDANCE` | BLOCKED_MISSING_GT |
| `SETTLING_WINDOW` | BLOCKED_MISSING_GT |
| `MECHANICS_KB_DUAL_GATED_FACTS` | EMPTY（0 条） |

### 12.3 SAME_NAME_STACK_LIFECYCLE 为何不是"因果级"

9 个 family 与配置白名单的完全重合，只证明**选择被白名单约束**，
不证明**每次 x 递进由某次特定 TAKE 引起**。当前不存在 request-correlated observer
（`request_id` / `decision_id` / `observation_id` / `state_version` 在全部证据文件中零出现），
因果归因在结构上尚不可得；且存在 `Δx = 2` 的跳变样本作为反例。

```
已证：9 family 的 x 单调递进真实存在，且全部落在配置白名单内
未证：任一次 x 递进由某一次具体 TAKE request 引起
升级为 SUPPORTED 的条件：request-correlated observer 接好，且 L4-01 产出 STRUCTURED_CONFIRMED > 0
```

---

## 13. Readiness 判定与前置条件

### 13.1 判定

```
READY_FOR_IMPLEMENTATION_AGENT = YES_WITH_GT_GATES
```

### 13.2 可以立即开始做的（无 GT 依赖）

| # | 交付项 |
|---|---|
| 1 | `DecisionSnapshot` / `ObservationSnapshot` / `Fact<T>` state model 与落盘 |
| 2 | typed `action_capabilities`（`can_take_slot[]` / `can_refresh` / `can_giveup` / `can_true_close` / `can_temporary_hide`） |
| 3 | 双轴身份：`candidate_instance_id` + `canonical_card_id`；四层身份栈；命名空间隔离 |
| 4 | family-level `Candidate` schema（`member_id` optional） |
| 5 | `acquisition_history` 与 `active_inventory` 物理分离（后者初值 UNKNOWN） |
| 6 | 统一 `hard legality → soft preference → execution` 边界；HL-1 scope 判定；新增 HL-7 / HL-8 / HL-12 |
| 7 | UNKNOWN 传播条款 U-1…U-11（尤其修 `cp:1122`） |
| 8 | 结构化 `ReasonCode` + `safety_reason_code` 替代 reason 文本进入控制平面 |
| 9 | 填充 `ActionLifecycle` + `postcondition` / `post_confirm` 槽位 |
| 10 | `request_id` / `decision_id` / `state_version` / `observation_id` / `candidate_instance_id` 关联链 |
| 11 | Freshness 合同 F-1…F-8（**加断言**，复用现有 `evidence_gen` / fingerprint / timestamp / hwnd） |
| 12 | REFUSE → fresh re-decision 循环 R-1…R-4（含 deterministic loop 检测与 bounded WAIT） |
| 13 | PolicyAction 与 affordance 分离；`SAFETY_RECOVERY_TEMP_HIDE` 独立建模 |
| 14 | 收回 runtime 第二套软策略（§5.2），保留状态注入与全部安全门（§4.2） |
| 15 | 接上 `mechanics_view` call-site **并同时**把「KB dual-gated = 0」做成显式遥测 |
| 16 | `next_refresh_cost` / `draw_cost` 作为两个永久独立字段建模（值恒 UNKNOWN，禁止 hard-code） |
| 17 | `free_slots_uncertainty` 通道 |
| 18 | outcome ledger 记录 `decided_action` / `executed_action` / `substituted_from`（期望恒 null） |
| 19 | 消歧 `_canonical_bond_name` 双实现（core 的 5 类折叠被 runtime 子类静默覆盖） |
| 20 | L1 全部 + L2-08 + L3 全部验收 |

### 13.3 必须在第一个 PR 内一并处理的前置条件

| P# | 前置条件 | 若遗漏的后果 |
|---|---|---|
| **P-1** | **不得激活 `decide_bond_capacity` / `CapacityAction`** | 仓库内已有一套完整但**零生产调用**的第三策略模型（`bond_capacity.py:121-186`），其 `USE_PILL` / `BUY_PILL` / `REPLACE_THEN_MERGE` 三分支全部依赖 GT 未闭环机制。它看起来"只差接线"，接了就是把未验证机制升级成 runtime authority。可复用其纯函数 `stack_need` / `stack_have`（已在用），可参考其不变量，**但不得接线** |
| **P-2** | **接 `mechanics_view` 必须连同 KB evidence gate 一起验收** | 只修 call-site 得到零行为变化，却会产生"已接通"的假完成信号 |
| **P-3** | **L2 回放层需先让 `DecisionSnapshot` 落盘** | 现 trace 只有候选级输入；`tools/replay_treasure_desc_equivalence.py:5` 的 docstring 会让实现 Agent 误判 L2 已就绪 |

### 13.4 无 blocker

三条前置条件均为**顺序约束**，非阻塞项。§13.2 的 20 项交付均无 GT 依赖，可立即开工。

---

## 附录 A · 冻结源码结论索引

```
a3bc4cd:src/shuabao/mediator.py:930                 MechanicsPolicyView 构造后零读取
a3bc4cd:src/shuabao/mediator.py:2630-2638           assemble_policy_settings 未传 mechanics_view
a3bc4cd:src/shuabao/mediator.py:2750-2770           _record_choice_session 只记决策不记执行
a3bc4cd:src/shuabao/mediator.py:2772-2778           _bump_choice_attempts 只在成功执行后计数
a3bc4cd:src/shuabao/mediator.py:2787 / 2802         _panel_has_giveup / _panel_can_refresh
a3bc4cd:src/shuabao/mediator.py:2867-2956           执行门 + 已废止的动作替换路径
a3bc4cd:src/shuabao/mediator.py:2990-3008           _bond_bar_occupancy 像素启发式（无不确定度）
a3bc4cd:src/shuabao/mediator.py:3014                _extract_live_set_progress
a3bc4cd:src/shuabao/mediator.py:3039-3045 / 3060    free_slots 产出，UNKNOWN 在生产者侧正确保留
a3bc4cd:src/shuabao/mediator.py:3062-3076           choose_action 唯一生产调用点
a3bc4cd:src/shuabao/mediator.py:3081-3095           ★reason 子串门控第二帧确认
a3bc4cd:src/shuabao/mediator.py:3097-3119           dry_run 学习观测（记 would-select，非玩家选择）
a3bc4cd:src/shuabao/choice_policy.py:29-31          纯函数不变量 + 固定 tie-break
a3bc4cd:src/shuabao/choice_policy.py:133            ★ActionLifecycle 死导入
a3bc4cd:src/shuabao/choice_policy.py:624-665        choose_action
a3bc4cd:src/shuabao/choice_policy.py:668-679        slot_fingerprint
a3bc4cd:src/shuabao/choice_policy.py:744-748        _mechanics_view_of → empty
a3bc4cd:src/shuabao/choice_policy.py:1117-1142      ★free_slots UNKNOWN→permissive / 满槽 merge 放行
a3bc4cd:src/shuabao/choice_policy.py:1145-1282      _decide_collectible
a3bc4cd:src/shuabao/choice_policy.py:1256-1263      REFRESH 仅次数预算，无成本比较
a3bc4cd:src/shuabao/choice_policy.py:1274-1276      宝物 allow_unnamed 已知例外
a3bc4cd:src/shuabao/choice_policy.py:1285-1296      80% 门算在 acquisition history 上
a3bc4cd:src/shuabao/policy/mechanics_view.py:18     _DROP_KEYS 丢弃 guide / conflicts
a3bc4cd:src/shuabao/policy/mechanics_view.py:42-46  dual-gate
a3bc4cd:src/shuabao/habit_preference.py:105-135     observations_to_name_scores 纯函数
a3bc4cd:src/shuabao/interaction_surface.py:12-30    ★ActionLifecycle 定义（零使用）
a3bc4cd:src/shuabao/interaction_surface.py:107-129  PendingAction（无 request_id，异常折成 False）
a3bc4cd:src/shuabao/bond_capacity.py:121-186        ★decide_bond_capacity 未接线（P-1）
a3bc4cd:src/shuabao/runtime_mediator.py:101-210     prepare_live_dependencies（安全）
a3bc4cd:src/shuabao/runtime_mediator.py:267-293     双帧 HUD 闩锁（安全，UNKNOWN 正面范本）
a3bc4cd:src/shuabao/runtime_mediator.py:329-335     ESC 预算 fail-closed（安全）
a3bc4cd:src/shuabao/runtime_mediator.py:362-370     ★_verified_panel_close 的模板集合几乎全为 temp-hide
a3bc4cd:src/shuabao/runtime_mediator.py:391-393     禁止固定坐标关闭（安全）
a3bc4cd:src/shuabao/runtime_mediator.py:626-645     ★SendInput ≠ selection proof（freshness 先例）
a3bc4cd:src/shuabao/runtime_mediator.py:650-657     _canonical_bond_name（子类覆盖父类）
a3bc4cd:src/shuabao/runtime_mediator.py:680-700     ★acquisition history append-only
a3bc4cd:src/shuabao/runtime_mediator.py:738-743     状态注入（正确模式，保留）
a3bc4cd:src/shuabao/runtime_mediator.py:756-769     ★路线跳过（软策略越权，须上移）
a3bc4cd:src/shuabao/runtime_mediator.py:788-820     ★决策后覆盖（第二套 whitelist，须删除）
a3bc4cd:config/game_mechanics_kb.json               wired_to_decision=false；dual-gated=0；guide-tier
a3bc4cd:config/choice_lexicon.json                  entries["肉身成圣"].set_membership="封神"；"未上帧"
```

---

## 附录 B · 文档谱系

```
POLICY_V01_IMPLEMENTATION_CONTRACT (原)
  + CORRECTION ADDENDUM (FIX-1 … FIX-6)
  + CONTRACT_FREEZE_PATCH_2 (P2-1 … P2-4)
  + CONTROL_TOWER_FREEZE_AMENDMENT_1 (最高优先)
  ═► 本文件（canonical，已规范化合并，被取代条款已删除）
```

`CONTROL_TOWER_FREEZE_AMENDMENT_1` 的四条要求在本文件中的落点：

| Amendment 条 | 落点 |
|---|---|
| typed `action_capabilities` | §6.3、§9.1 HL-12、§10.5/§10.6/§10.7 eligibility、§11.3 L3-13/L3-16 |
| REFUSE 后须推进 state_version；禁 deterministic REFUSE loop；bounded WAIT / fail-closed | §5.3 R-1…R-4、§10.7 WAIT、§11.3 L3-13/L3-14 |
| temp-hide 不得记作 CLOSE；`SAFETY_RECOVERY_TEMP_HIDE` 独立建模 | §2.4、§2.5、§10.6、§11.3 L3-12/L3-15 |
| `candidate_instance_id` 进 trace 且禁作 semantic key；`canonical_card_id` 条件赋值 | §2.2、§2.6、§6.5、§7.1、§10.3、§11.1 L1-01b/L1-01c、§11.2 L2-08 |
| `UNSTRUCTURED_RUN_LINKED` 仅离线 / 保守 gate / backlog | §3.2、§3.4、§8 U-11、§11.3 L3-18 |

---

**END OF CONTRACT — FROZEN 2026-09-08**
