# 选卡策略接线与素材交接（2026-08-12）

面向接手的 agent。**动手前先读仓库根 `AGENTS.md`**，尤其"一 commit 一层"和
"提交前必过 `python tools/release_gate.py`"。

---

## ⚠️ 并行作业须知（2026-08-12 15:20 更新）

主 agent 正在**同时进行**面板 UI 重构与核心算法。为避免撞车，先看这张表：

| 文件 / 目录 | 归属 | 外部 agent 可否改 |
|---|---|---|
| `desktop_app.py` | 主 agent（UI 重构中） | ❌ 不要动 |
| `src/gamescript/choice_policy.py` | 主 agent（已交付 `f7717fc`） | ❌ 不要动，只读它的 API |
| `config/choice_policy.json` · `config/skill_meta.json` | 主 agent | ❌ 不要动 |
| `src/gamescript/settings.py` | 主 agent（刚加 `treasure_allow_negative`） | ⚠️ 需加字段先说 |
| `tests/contract/test_choice_semantics_contract.py` | 主 agent | ❌ 不要动（可新增**别的**契约文件） |
| `src/gamescript/mediator.py` | **A 组** | ✅ |
| `assets/Images/cards/**` · `config/fetter_labels.json` · `config/choice_lexicon.json` | **B 组** | ✅ |
| `ui/**`（React 网页面板） | **C 组** | ✅（见下方 C 组改动） |
| `fixtures/**` | **D 组** | ✅ |

**起点 commit：`f7717fc`。开工前先 `git pull` / rebase 到它之后**，否则你拿到的
`PolicySettings` 是旧的（缺 `treasure_negative_names` / `bond_whitelist_mode`）。

三组彼此不冲突，可同时开三个 agent。A 组是关键路径。

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

## 4. 待做 · C 组：React 网页面板对齐（**已重新划分**）

> **改动说明**：原 C 组是"做负面宝物折叠勾选 UI"。经查，打包进 exe 的是
> **PySide6 桌面面板 `desktop_app.py`**（`GameScript.spec` 把 fastapi/uvicorn 都
> excludes 了，`ui/dist` 也不在 datas 里），React 那套只是可选网页面板。
> 折叠勾选 UI 由**主 agent 在 `desktop_app.py` 里做**，C 组不要重复实现，
> 更不要动 `desktop_app.py`。

C 组现在的范围只剩 React 面板与后端字段对齐（**低优先级，可最后做**）：

1. `ui/src/types.ts` 的 `AppSettings` 补 `treasure_allow_negative: string[]`
2. `FettersCard.tsx` 里那份 `FETTER_NAMES` 是 `config/fetter_labels.json` 的**手抄副本**，
   两处不同步会导致网页显示和后端识别对不上。改成运行时从
   `/api/options/fetter-labels` 拉取（该端点需在 `api_server.py` 新增，读同一个 json），
   删掉硬编码副本。
3. 若要在网页面板也做负面宝物勾选，**照抄桌面面板落地后的语义**：逐卡勾选、
   默认全不勾、写回 `treasure_allow_negative`。等主 agent 那版合入后再做，别抢先定义。

## 5. 待做 · D 组：负面卡描述取证（**卡名已确认，只差描述原文**）

用户 2026-08-12 已逐张确认负面宝物共 6 张，已写入 `choice_policy.json`
的 `treasure.negative_names` 并被契约锁定：

> 透支力量 · 贪婪献祭 · 金转木 · 杀敌梭哈 · 伐木契约 · 等级优势

**名字判定已经生效**（描述读不到也拦得住），所以 D 组不再是阻塞项。剩下的活是
补描述原文，让**没见过的新卡**也能被模式匹配拦住：

1. 局内开宝物面板，截到这 6 张中任意一张的帧 → 存 `fixtures/treasure_negative/`
2. 把卡面描述原文加进契约 `S3NegativeTreasureOptIn.NEGATIVE_SAMPLES`
3. 核对 `negative_patterns` 是否覆盖该措辞；不覆盖就补模式（**只补，不删**）
4. 做一条端到端断言：真实面板帧 → 该卡不被选中

红线不变：**名单外的卡不得仅凭名字可疑就拉黑**（契约
`test_missing_description_is_not_guessed_negative` 守着这条）。

## 6. 建议顺序与并行度

三条独立轨道，可同时开三个 agent：

| 轨道 | 优先级 | 阻塞谁 | 备注 |
|---|---|---|---|
| **A** mediator 接线 | 🔴 关键路径 | 用户实机体验 | A3「删三条旁路」风险最高，做完立刻跑门禁 + 实机 1 局 |
| **B** 素材词典 | 🟡 中 | 无 | 纯数据活，用户会陆续给卡牌素材 |
| **D** 描述取证 | 🟢 低 | 无 | 名字判定已生效，这步是给新卡兜底 |
| **C** React 对齐 | ⚪ 最低 | 无 | 等主 agent 的桌面面板语义落地后再做 |

**主 agent 同期在做**：面板 UI 重构（`desktop_app.py`：技能图标 + 悬停说明、
负面宝物折叠勾选、整体版式）+ 核心算法。与 A/B/D 无文件重叠。

### 每个 agent 开工前的自检

```powershell
git log --oneline -1          # 应看到 f7717fc 或更新
python tools/release_gate.py  # 起点必须是 PASS，不是 PASS 先别动手
```

收工前同样跑一遍 gate；红了先判断「哪边才对」，**不要改快照让它变绿**。

### 交回时说清三件事

1. 改了哪一层（对应 commit 拆分）
2. gate 结果（贴 4 个阶段的观测值）
3. 哪些链路的实机证据因此失效、需要重测
