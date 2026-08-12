# 选卡策略接线与素材交接（2026-08-12）

面向接手的 agent。**动手前先读仓库根 `AGENTS.md`**，尤其"一 commit 一层"和
"提交前必过 `python tools/release_gate.py`"。

## 0. 背景：现在是什么状况

用户 2026-08-12 实机报了三个选卡问题，根因已定位：

| 症状 | 根因 | 位置 |
|------|------|------|
| 预设里有橙色技能却选了紫/蓝 | 预设命中后按槽位从左到右取第一个，稀有度没进排序 | `mediator.py` `_ocr_reward_choice` kind=="skill"（约 1571–1581） |
| 宝物会拿"拿了就断金币/断木材/断升级"的负面卡 | 宝物选择只有 `min(recognized, key=index)`，无偏好/无黑名单/无负面识别 | 同上 kind=="treasure"（约 1618–1622） |
| 羁绊海盗明确不勾选还是每次拿 | UI 勾选框是**偏好白名单**不是禁用；未命中就落 `_rarity_choice` → `_fallback_choice` | 同上 kind=="bond"，以及 `_find_reward_choice`（约 1749–1754） |

**另一个必须知道的事实**：`src/gamescript/choice_policy.py`（440 行确定性策略 + 50 单测）
此前**完全没有接线**——全仓搜 `choose_action` 除自身测试无任何调用点。
文档里"P0 确定性选择策略已完成"在生产里没有运行。

## 1. 已完成（本次，勿重做）

- `choice_policy.py` 扩展并补齐语义：
  - `_match_preset(..., rarity_first=True)`：技能预设间按稀有度优先
  - `PolicySettings.bond_whitelist_mode`：默认 `"hard"`，硬禁用同时封住套装/品质旁路
  - `is_negative_treasure()` / `_drop_negative_treasures()`：按描述原文判负面，勾选放行
  - `DEFAULT_QUALITY_ORDER` 补 `green`（最低档）
  - `SlotCandidate.description`：识别层填卡面描述
- `config/choice_policy.json`：配置 schema + 每项的语义注释
- `tests/contract/test_choice_semantics_contract.py`：S1–S5 契约，**已做突变验证**
  （关掉稀有度排序→15 红；硬禁用失效→3 红；负面检测失效→3 红）
- `tests/conftest.py`：让每个测试文件可独立运行（此前依赖导入顺序）

门禁现状：`python tools/release_gate.py` → PASS。

## 2. 待做 · A 组：mediator 接线（架构性，建议一人独立完成）

目标：让 `_find_reward_choice` 走 `choice_policy.choose_action`，而不是各自为政的
临时逻辑。**这是本组唯一目标，不要顺带改大厅或恢复逻辑**（跨层混提交是 8-12
两次紧急版本的直接原因）。

### A1 感知层：产出 `SlotCandidate`

把现有 `_ocr_panel_slots` 的输出映射为 `SlotCandidate(index, name, confidence, rarity, description)`：

- `rarity`：用 `_card_rarity_score` 的 band。**需先给 `RARITY_BANDS` 和
  `_card_rarity_score` 的 masks 补 green**（hue 约 35–90，sat>70，value>60），
  否则绿边卡的 rarity 恒为 None。
- `description`：新增 ROI。实机版式见 `tests/performance/fixtures/treasure_panel.png`：
  描述文字在卡名正下方、卡框内部。三槽 x 中心比例沿用 `_rarity_choice` 的
  `treasure: (0.348, 0.497, 0.646)`；描述带 y 范围需实测标定后写进配置，
  不要硬编码魔数在代码里。
- 读不到描述时留空字符串，**不要猜**——`is_negative_treasure` 对空描述返回 False，
  由白名单/品质继续把关（契约 `test_missing_description_is_not_guessed_negative`）。

### A2 决策层：调用策略

```python
decision = choose_action(PanelCandidates(
    panel_kind=kind, slots=slots, set_progress=..., has_giveup=...,
    settings=policy_settings_from(self.settings),  # 读 config/choice_policy.json
), session_state)
```

映射 `PolicyAction` → 现有动作：`SELECT_SLOT`→点对应槽位、`REFRESH`→刷新按钮、
`GIVEUP`→放弃、`CLOSE`→隐藏/关闭、`WAIT`→本 tick 零输入。

### A3 删除旁路（关键，别漏）

硬禁用要生效，必须切断这三条会绕过白名单的路径：

1. `_rarity_choice` 用于 bond/card 的兜底（约 1750）
2. `_fallback_choice`「任选第一张」（约 1753–1754）
3. `_ADVANCED_BOND_MARKERS` 那套 `have==0 且 occupancy<4` 的启发式（约 1598–1607）
   —— 它是白名单缺失时代的替代品，接线后应由白名单取代；保留会互相打架
   （现象就是"已有 1 张海盗后永远放行"）

`_rarity_choice` 本身对**宝物**仍可保留（宝物不是白名单制），但必须在负面剔除**之后**执行。

### A4 验收

- `python tools/release_gate.py` PASS（含 30 条选卡契约）
- 冻结回放里 `giveup_panel_not_fail` / `main_hud_idle` 的期望会变（技能面板动作可能
  从"刷新"变"选中某张"）。**先判断新行为对不对，再改夹具期望，然后
  `--update-baseline --reason ...`**。禁止为了变绿改快照。
- 实机 1 局验证：日志里应出现"稀有度优先"字样，且不再出现未勾选羁绊被选中。

## 3. 待做 · B 组：素材与词典（可并行，机械性）

用户会提供卡牌素材。接入三处：

1. **模板**：`assets/Images/cards/<短码>.png`。裁剪要求：只含卡面可辨识区域，
   不含边框颜色（边框由 rarity 逻辑单独判定，含进模板会让不同品质的同名卡漏匹配）。
2. **短码→中文**：`config/fetter_labels.json`（UI 的 `FettersCard.tsx` 有一份重复的
   `FETTER_NAMES`，**两处要同步**，否则 UI 显示和后端识别会不一致）。
3. **OCR 规范名**：`config/choice_lexicon.json` 的 `entries`，填 `kind`（bond/treasure/skill）、
   `aliases`（OCR 易混写法）。

每个新模板必须建**双向断言**：正样本命中 ≥0.9，且空白帧/无关帧不命中 ≤0.4。
参照 `docs/baselines/EVOLVE_TEMPLATE_RECUT_20260812.md`——进化模板就是因为缺负向
断言而误命中数百次。加进 `tools/validate_scenes.py` 的强制项。

## 4. 待做 · C 组：UI 折叠勾选（前端）

用户要求：负面宝物在宝物区**折叠**展示，逐卡打勾才会选，不勾不选。

- 前端：`ui/src/components/` 新增可折叠列表，选项来自 `config/choice_policy.json` 的
  `treasure.candidate_negative_names_unverified` + 实机已确认的负面卡名
- 写回：`treasure.allow_negative` 数组（逐卡，不是全局开关）
- 默认：全不勾

## 5. 待做 · D 组：负面卡措辞取证（需用户配合）

`config/choice_policy.json` 的 `negative_patterns` 目前是按用户口述推断的模式。
需要三张卡的**实机截图**确认准确措辞（+50万金币断金币 / 666木材断木材 / 直升25级断升级）。

拿到后：
1. 把描述原文加进契约 `S3NegativeTreasureOptIn.NEGATIVE_SAMPLES`
2. 把帧存成夹具，做一条端到端断言（面板帧 → 不选该卡）
3. `candidate_negative_names_unverified` 里被证实的移到正式名单

**在取证完成前，不得**把 `透支力量`/`贪婪献祭` 等仅凭名字可疑的卡拉黑——
名字不能证明效果。

## 6. 建议顺序

A 组（接线）是关键路径，B/C/D 可并行。A3 删旁路那步风险最高，做完立刻跑门禁 +
实机 1 局。D 组取证完成前，负面识别只对已确认措辞生效，属正常状态，不是缺陷。
