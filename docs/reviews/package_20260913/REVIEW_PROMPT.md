# 外部审查任务：刷刷宝 PR 合并、架构整合、业务板块、正式版进度（2026-09-13）

> 把本文件全文交给外部审查 agent。阅读清单和链接见同目录的 `README.md`。

---

你是刷刷宝项目的外部审查员。**只审查，不改代码。** 请用中文输出报告。

## 仓库与基准

- 主仓库：`github.com/Yszdhhh/shuashuabao`（私有），审查基准是 `main` 的 `b4cf93f6a2c716aa44f29abf1cd54caacaea09fa`（PR #19 的 merge commit）。
- 订阅服务端仓库：`github.com/Yszdhhh/shuashuabao-subscription-lab`（私有），分支 `feat/account-layer-20260913`（`cdf9603`）。
- 本审查包在主仓库的分支 `review/package-20260913` 上，路径 `docs/reviews/package_20260913/`。
- 这是一个 Windows 桌面自动化工具：PySide6 QWebEngine 看板 + OpenCV 模板匹配 + OCR sidecar，驱动 KK 平台上的魔兽 RPG 地图。云端是 Linux，很多测试依赖 Windows API。能跑的纯逻辑测试请跑，比如 `tests/unit/`、`tests/test_boss_order_*.py`、`tests/test_dashboard_facade.py`、`ui-v2` 下的 `npm test`。报告里注明哪些结论**经过运行验证**，哪些**只是阅读**得出的。

## 审查的四个维度

### A. PR 合并与版本收敛

1. PR #19 的合并是否正确、是否无损：
   - 用 `-s ours` 吸收旧 main（`87d9aca`）的依据，是「旧 main `7edae99` 与主线祖先 `9f813f8` 同树」，请复核；
   - merge commit 的树应该等于 PR head `79f9567` 的树；
   - 存档标签 `archive/main-7edae99-20260913` 是否存在。
2. 收敛过程有没有丢东西：对照 `docs/handoff_20260912/CONVERGENCE_REPORT_20260912.md`，以及评估文档第 6 节列出的残留工作树和未推送提交，判断有没有应该进 main 却被遗漏的改动。
3. 流程是否稳妥：实机身份门禁（Live lnk 的 SHA 必须等于 HEAD；改了 `src/shuabao` 就要重定基线）、只允许 merge commit、CI 与门禁的关系，有没有更简单、不容易出错的做法。

### B. 架构整合

1. 分层是否清晰：`desktop_app.py` → `WebConfigShell`（QWebEngine，只允许 file/qrc）→ QWebChannel `facade` = `DashboardFacade`（BRIDGE_SCHEMA_VERSION=2）→ `RunnerService`（唯一的 LIVE 入口）→ `Mediator.tick()`。有没有绕过这条链的旁路？
2. 前端（`ui-v2/index.html` 的内联全局脚本 + `src/main.ts` 适配层）与后端契约是否一致；`config/mode_specs.json` 决定模式的可见与可启动，UI 不发送 game_mode。这个约定有没有被破坏？
3. `src/shuabao/mediator.py`（约 1.5 万行的单体）：这次新增的逻辑是否遵循「策略抽成纯函数、mediator 只采集和执行」的方向（参照 `policy/boss_order.py`）？给出拆分的优先级建议。
4. 工具链：`tools/release_gate.py`、`tools/live_harness_identity.py`、`tools/live_scenario_capture.py`、`.github/workflows/ci.yml`。特别看 `_ensure_commit_available` 在浅克隆时执行 `git fetch --unshallow` 的副作用，会不会在实机启动器的路径上被触发。

### C. 业务板块（重点是 `git diff f0243f5 b4cf93f`，43 个提交，`src/` 约 1300 行）

用户已拍板的规则如下。请按这些规则审查**实现**，不要质疑规则本身：
1. **战后 Boss**：设目标序号为 T、到底后的物理末卡序号为 L。
   - T ≤ L：按序推算格位，**必须二次确认**（降阈值模板或 OCR）后才能点，**不许凭坐标盲点**；
   - T > L：点末卡；
   - 没配置目标：探底后点末卡。
2. **Boss 相关的任何失败都不停机**：
   - 找不到就点「当前能认出的最后一张卡」；
   - 一张都认不出时，先鼠标停车、换宽尺度重试（**识别阈值不降**），用尽后跳过并记 incident；连续 2 局出现时打 warn。
3. 传家宝没有每日上限；存档挑战中间 4 个每天 8 次，但全部照点，不为次数加判断。
4. 宝物 V：已有上次杀敌数、而当前杀敌 OCR 为 None 时先跳过，但跳过是有界的，到界后允许探测性地开一次 V。
5. 蹭车座位规则：我方成为房主、我方坐一楼、一楼离开，这三种情况都退房并拉黑。压力转移：看得见按钮就优先点；看不见绝不阻塞。

重点审查：
- `boss_order.py` 各分支（3A/3B/3C、L+1 空格证明、无滚动条判定、回底预算、`locate_exhausted`）有没有漏洞；会不会死循环或来回滚动；计数器是否按局、按页面重置；**有没有任何路径能在没有模板或 OCR 命中的情况下点击**；跳过之后传家宝弹窗和存档面板能否关掉并继续下一局。
- 宝物 V（`3af605e`、`81b3129`）：MD5 物理指纹去重会不会误拒真正的新面板，白白丢掉一次选择。
- 看板安全：`innerHTML` 拼接里有没有未转义的用户字符串或后端字符串（页面能调用 facade，所以 XSS 就等于本地执行入口）。启动摘要那一处已由 PR #20 修复，请检查**其余**位置。`set_window_layout` 的高度校验是否完整。
- 测试有效性：有没有测试把关键判断直接 patch 成固定值，从而没有真正验证它？之前就出过「把 at_bottom patch 成 True，掩盖了无滚动条时整个运行停机」的事。

### D. 正式版进度评估

复核 `RELEASE_PROGRESS_ASSESSMENT_20260913.md`：
1. 阻塞项 B1–B5 是否准确、完整。有没有漏掉的，比如打包、签名、安装器、自动更新、OCR 模型分发、隐私说明。
2. 「0.4 不等账号系统」的建议是否合理。
3. 账号层设计 `ACCOUNT_LAYER_DESIGN_20260913.md`：
   - Runtime Lease 的原子性（SQLite 部分唯一索引 + BEGIN IMMEDIATE）；
   - 断网时 10 分钟的容忍策略；
   - Permit v1 不改协议、只在签发前检查 lease，这个安全边界是否成立；
   - 老卡迁移；
   - 共享嫌疑信号与隐私边界。
4. 给出你认为的**最短发布路径**，以及每一步的验收标准。

## 已知项（不用再报）

- 严格门禁 `frozen_replay/disconnect_modal_missing=BLOCKED`（缺真实断线素材）；4 个提交标题带 UTF-8 BOM。
- 刷图 / 带队模式下战后面板还有 5 处 fail-closed（约 14800、14904、14961、15107、15371 行），已排进 R1。
- CI 里重复跑全量 pytest、没设 `fetch-depth: 0`，已排进 R1。
- GitHub 仓库没有配置 Actions secrets（B3）。

## 输出格式

1. 总体结论（3 句以内）：能不能作为 0.4 候选的代码基础；离正式发布还差什么。
2. 按 A / B / C / D 四个维度分别给出问题清单，按严重程度排序：
   - P0：会点错、崩溃、停机或造成安全问题；
   - P1：错误行为；
   - P2：健壮性或可维护性；
   - P3：小问题。

   每条写明：`文件:行号`（或文档名）、一句话描述、**具体触发场景**（什么输入或状态 → 什么错误结果）、修改建议、是否经过运行验证。
3. 测试缺口清单。
4. 已核对、没发现问题的部分（简短列一下，避免重复审查）。
5. 你建议的发布路径和验收标准。

## 约束

- **不推送 main，不开 PR，不改任何代码或配置。** 可以把报告推送到分支 `review/package-20260913`，路径 `docs/reviews/package_20260913/EXTERNAL_REVIEW_REPORT.md`，**只加这一个文件，不开 PR**。
- 不读取、也不输出任何密钥、卡密或签名材料。
