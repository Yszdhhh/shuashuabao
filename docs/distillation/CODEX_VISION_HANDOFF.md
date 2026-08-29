# CODEX VISION HANDOFF — Codex 视觉工程落地与接线交接书
# Gemini Stage 1 -> Codex Stage 2 实施蓝图
# 权威基准: G:\刷刷宝\GameScript-Local | 质量门禁: tools/release_gate.py

---

## 1. 实施优先级与任务清单

```
[ P0 紧急高收益改动 ] (1天内可完成)
  ├── 1. 彻底关闭宝物面板 (treasure) 的 OCR 链，改为直接盲选/HSV判色
  ├── 2. 重构 ocr_shadow/worker.py：剔除 6 重多变体与磁盘临时文件，改为单一 Gray_2x 内存推理
  ├── 3. 修复 choice_ocr.py 文本归一化：增加 \(\d+/\d+\) 正则剥离末尾进度数字
  └── 4. 修复 mediator.py 羁绊选卡：将 cards/*.png 标题字形匹配前置，空槽自动补齐

[ P1 稳定性与抗扰动优化 ] (2天内完成)
  ├── 5. 增补 config/choice_lexicon.json：扩充 30 个实机高频技能与 OCR 别名映射
  ├── 6. 英雄进化二选一面板 (hero_choice) 与宝物面板做槽位几何严格防歧义
  └── 7. L0 大厅向导与关卡选择引入 2 帧防抖与超时重试，消除 unknown_page 误报

[ P2 架构瘦身与门禁固化 ] (3天内完成)
  ├── 8. 生产发布门禁 (tools/release_gate.py) 加入 assets 白名单校验，阻止 raw 截图入包
  └── 9. 接入 vision_profiles.proposed.yaml，统一视觉参数入口
```

---

## 2. P0 任务实施具体蓝图

### 2.1 任务 P0-1：关闭宝物面板 OCR
- **涉及文件**：`src/shuabao/mediator.py` (`_ocr_panel_slots`, `_tick_panel_fsm`)
- **当前问题**：打开宝物面板时，调用 OCR 尝试读取宝物名称与长文本描述，产生 24,645 次无用报错，耗费数秒且 98.6% 失败。
- **推荐改动**：
  ```python
  # 在 _ocr_panel_slots 中：
  if kind == "treasure" or kind == "treasure_desc":
      # 宝物面板直接返回空候选，由下游策略直接执行首槽点击或隐藏
      return []
  ```
- **验证命令**：`pytest tests/test_ocr_shadow.py tests/test_mediator_choice_four_slot_integration.py`
- **预期收益**：系统 OCR 总调用量瞬间降低 54.6%，宝物面板响应由 2500ms 缩减至 150ms。

### 2.2 任务 P0-2：精简 `worker.py` 预处理管道
- **涉及文件**：`src/shuabao/vision/ocr_shadow/worker.py` (`_predict`)
- **当前问题**：每张图做 6 种 OpenCV 变换并写 6 次硬盘临时文件。`R-B` 准确率仅 6.5%，`Otsu` 仅 69.5%。
- **推荐改动**：
  ```python
  # 移除 variants 循环与 NamedTemporaryFile 磁盘 I/O
  # 统一在内存中做 Gray + 2x CUBIC 放大：
  gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
  processed = cv2.resize(gray, (0, 0), fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
  
  # 直接将 processed 传入 recognizer（通过内存 buffer 或单次推理）
  ```
- **预期收益**：OCR 单次推理耗时降至 20.8ms (p50)，消除所有磁盘临时文件读写竞争。

### 2.3 任务 P0-3：羁绊名称剔除 `(x/y)` 括号进度
- **涉及文件**：`src/shuabao/vision/choice_ocr.py` (`normalize_choice_text`)
- **当前问题**：`箭术(1/3)` 被 OCR 识别为 `新术(13)`，词典无法命中。
- **推荐改动**：
  ```python
  _PROGRESS_BRACKET_RE = re.compile(r"[\(\[（【]\s*\d+\s*/\s*\d+\s*[\)\]）】]")
  
  def normalize_choice_text(raw: str) -> str:
      if not raw:
          return ""
      text = unicodedata.normalize("NFKC", raw)
      text = _PROGRESS_BRACKET_RE.sub("", text)
      text = _DECORATOR_RE.sub("", text)
      text = _STAR_RE.sub("", text)
      text = _NEW_TOKEN_RE.sub("", text)
      text = _WS_RE.sub("", text)
      return text
  ```

### 2.4 任务 P0-4：官方 `cards/` 标题字形匹配前置
- **涉及文件**：`src/shuabao/mediator.py` (`_ocr_panel_slots`, `_match_all_preferred`)
- **当前问题**：4 选面板在 OCR 读空时直接停滞，未用官方字形 `cards/` 进行回填。
- **推荐改动**：
  在 F 键面板打开时，先对 4 个槽位运行 `assets/Images/cards/` 局部模板匹配（得分 ≥ 0.82 即直接采纳该卡名）；未命中的槽位再将紧凑裁剪送入 OCR。

---

## 3. P1 任务实施具体蓝图

### 3.1 任务 P1-5：词典别名补充 (`config/choice_lexicon.json`)
增补以下实机高频技能与常见 OCR 误识对齐：
- `爆炸扩散` -> 映射到 `爆炸箭矢` 或独立技能条目
- `奥术增幅` -> 包含 `α`, `β`, `γ` 后缀别名
- `已馨`, `日麟` -> 映射到 `已隐` / `麒麟`
- `新术` -> 映射到 `箭术`

### 3.2 任务 P1-6：英雄进化二选一防歧义
- **涉及文件**：`src/shuabao/mediator.py` (`_panel_kind_of`)
- **判定规则**：
  - 若检测到 `click_evolve` 之后，且画面中仅有 2 个有效大卡片槽位（Slot 0 和 Slot 1，Slot 2 为空/背景），**强制标记为 `hero_evolution`**；
  - **严禁将其判为 `treasure` 并触发 `treasure_hide_btn`**。

---

## 4. 回归验证与 Codex 独立复验要求

Codex 在完成上述改动后，必须在 `.venv-ocr` 环境下执行并通过以下离线与合约测试：

```powershell
# 1. 运行 OCR 独立评测门禁（必须全绿，准确率 >= 95%，延迟 p50 <= 30ms）
.\.venv-ocr\Scripts\python.exe tools/evaluate_choice_ocr.py

# 2. 运行完整单元与集成回归测试
.\.venv\Scripts\python.exe -m pytest tests -q

# 3. 运行 4 阶段全量发布门禁（退出码必须为 0）
.\.venv\Scripts\python.exe tools/release_gate.py
```

### 需要 Codex 独立复验的关键参数：
1. **4 槽羁绊面板 X 坐标偏移**：确认 1600x900 下 4 槽的中心间距是否稳定为 `[380, 570, 760, 950]`；
2. **字形匹配阈值**：复验 `cards/*.png` 在 1600x900 实机下的归一化相关系数阈值（建议推荐 `0.82`，严禁低于 `0.75`）。
