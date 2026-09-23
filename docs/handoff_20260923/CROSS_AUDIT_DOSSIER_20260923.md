# 《重生魔兽刷刷刷》竞品深度拆解与全量分析资料交接审计卷宗 (Cross-Audit Dossier)

> **卷宗定位**：汇集前期交接分析资料、最新全套竞品深度拆解报告、实机真相推翻表、三栏裁决与下一任 Agent 交叉审计核验清单。  
> **编制人 / 署名模型**：**Gemini 3.8 Flash (High)**（Google DeepMind Antigravity）  
> **审计接收方**：下一任交叉审计 Agent（Cross-Audit / Reviewer Agent）  
> **工程基准**：`origin/feat/solo-shadow-scheduler-20260922`（commit `cbd49de` / `4fbb884`）与本地代码基线  
> **样本真源**：`C:\Users\10639\Desktop\竞品\`  
> **签署日期**：2026-09-23

---

## 〇、 审计交接背景与核心红线

本卷宗旨在将前序所有机制调研、实机 GT 事实与桌面三家竞品样本（脚本1 1.6.2/1.6.3、脚本2 护肝宝、脚本3 Python/DM）的深度逆向拆解成果**全量打包交付**给下一任交叉审计 Agent，以便展开多模型、多视角的独立核查与交叉审计。

### 🚨 审计与执行红线（不可逾越）
1. **禁止修改生产代码**：`src/shuabao/` 源码目录严禁做任何写入或修改；
2. **禁止运行竞品 EXE**：绝对严禁在宿主或沙箱中直接执行竞品二进制程序（`GameScript.exe`、`魔兽刷刷脚本在线版.exe`、`刷刷护肝宝92.exe` 等）；
3. **竞品结论仅出裁决**：竞品拆解仅输出“三栏裁决（应用/参考/REJECT）”与“差距补齐项”；拿卡默认值、策略打分权重与状态机改动统一归总架构 Agent 仲裁；
4. **合规红线**：严禁采纳任何关闭安全软件（如脚本3自带的“一键关闭系统杀毒”）或利用伪造数字签名欺骗杀软（如竞品2的签名遮蔽）的技术手法。

---

## 一、 前期交接分析资料全景打包 (Prior Handoff Materials)

在开展本次拆解之前，项目前期已完成的核心事实沉淀与机制归总资料已全部锚定，审计 Agent 应作为基础依据调阅：

| 资料名称 | 存放路径 / 引用位置 | 核心内容与事实基准 |
| :--- | :--- | :--- |
| **竞品知识总汇基线 (2026-09-10)** | [`docs/architecture/COMPETITOR_KNOWLEDGE_SYNTHESIS_20260910.md`](file:///C:/Users/10639/work/shuashuabao/docs/architecture/COMPETITOR_KNOWLEDGE_SYNTHESIS_20260910.md) | 三家竞品工程面矩阵、Top 10 可借鉴模式（否定指纹、双三次插值等）与 Top 6 永久拒绝反模式 |
| **机制与决策总归档 (2026-09-22)** | `origin/docs/research-20260922`（commit `cbd49de`）<br/>`docs/research/20260922/mechanics_solo/` | 单人模式实机机制事实（`SOLO_MECHANICS_FACTS.md`）、Boss 历史重测（`BOSS_HISTORICAL_RECHECK.md`） |
| **负面宝物证据报告** | `origin/docs/research-20260922`<br/>`docs/research/20260922/treasure/treasure_debuff_report.md` | 基于实机 25 帧 debuff 证据链确立的 19 类负面 + 2 类存疑宝物全量清单 |
| **策略分模块总图与推翻表** | [`docs/handoff_20260923/STRATEGY_MODULE_MAP_FOR_ARCHITECT.md`](file:///C:/Users/10639/work/shuashuabao/docs/handoff_20260923/STRATEGY_MODULE_MAP_FOR_ARCHITECT.md) | 四层决策引擎（L0~L3）、体术（80%力量伤而非破甲）、贪婪套（散件加和+合成吞4张）、木材非单调性实机真相推翻表 |
| **总架构审查提示词** | [`docs/handoff_20260923/HANDOFF_PROMPT_FOR_ARCHITECT.md`](file:///C:/Users/10639/work/shuashuabao/docs/handoff_20260923/HANDOFF_PROMPT_FOR_ARCHITECT.md) | 提供给总架构 Agent 的 L0~L3 机制核查清单与 P0~P2 实施路线 |

---

## 二、 本次深度拆解报告全集 (2026-09-23 Teardown Reports)

针对桌面 `C:\Users\10639\Desktop\竞品\` 产出的 8 份最新深度拆解报告已全量入库，审计 Agent 需重点审计：

```
docs/
├── handoff_20260923/
│   ├── COMPETITOR_KNOWLEDGE_INDEX.md           # 全文导航总图、Top 3 情报、三栏裁决、S1-S6 对接点
│   ├── HANDOFF_PROMPT_FOR_COMPETITOR_ANALYST.md # 竞品分析 Agent 启动提示词与 Backlog
│   ├── HANDOFF_PROMPT_FOR_ARCHITECT.md          # 总架构交接协议
│   ├── STRATEGY_MODULE_MAP_FOR_ARCHITECT.md     # 机制四层决策总图与推翻表
│   └── CROSS_AUDIT_DOSSIER_20260923.md          # 【本卷宗】全量分析与交接审计包
└── research/
    ├── COMPETITOR_FULL_ANALYSIS_20260922.md     # 三家全量总矩阵 + §7.5 缺口审计 + 1.6.2 Boss
    ├── COMPETITOR_FEATURE_EXCLUSIVITY_MATRIX_20260923.md # 独占/缺失矩阵；大厅找房与蹭车从动机制对照
    ├── COMPETITOR_GAPS_DEEP_DIVE_LANDING_20260923.md     # 稳定性看门狗 / 18 Boss 虚拟网格 / 3·4 选一落地
    ├── COMPETITOR_STATIC_OBSERVATIONS_1_6_2_20260922.md # 1.6.2 专项：界龟+55~57 Boss、命运骰子、计时
    ├── COMPETITOR_STATIC_OBSERVATIONS_1_6_3_20260923.md # 1.6.3 增量：海贼王≠海盗、不归秘境、三极卡、PDB
    ├── COMPETITOR_SCRIPT1_SETTINGS_MAP_20260923.md      # 脚本1 Settings 74 项配置与函数调用映射
    ├── COMPETITOR_STATIC_OBSERVATIONS_SCRIPT3_20260923.md# 脚本3 逆向：传家宝多房、999 安全、关 Defender
    └── COMPETITOR_STATIC_OBSERVATIONS_COMP2_20260923.md  # 竞品2 加壳包：签名遮蔽 Overlay、6 分卷 QMCZIP
```

---

## 三、 交叉补充分析与关键发现摘要

本模型（Gemini 3.8 Flash (High)）在交叉比对前期资料与桌面资产后，提炼出以下核心增量成果：

### 1. 脚本1 (1.6.3) 增量与工程泄露
* **海贼王 ≠ 海盗**：实机证实「海贼王 (ONEPIECE)」系跨品质专属卡（含 `haizeiwangEx.png` 觉醒形态），绝非羁绊 F 中的门卡海盗。
* **不归秘境独立落点**：新增 `buguimijing.png` 作为战后高阶挑战分支，必须独立判页，防止误触发 Fail-Closed 离场。
* **PDB 符号与 FlaUI XML**：未剥离的 `GameScript.pdb` 和 `Lan.UIAutomation.xml` 证实其采用多线程 + WPF Dispatcher 调度，且通过 FlaUI UIA 树遍历 KK 平台大厅。
* **74 项 Settings 全景映射**：详尽提取并归类了从动（`FollowTheLead`）、定时关主线（`AutoCloseMainLine`）、每局新房（`NewRoomEveryTimes`）、关卡分层 Boss（`SmallCJBoss 1/2/3`）等 74 项参数。

### 2. 竞品2 (刷刷护肝宝92) 商业化打包技术
* **数字签名遮蔽 (Authenticode Cloaking)**：PE 结构在微软合法数字签名（13.4KB）后挂载了 12.7MB XOR `0xCC` 混淆数据流。
* **6 分卷解耦载荷**：`uservar_config.ini` + `package_1..6_qmcfile.zip` 实现 Loader 与功能内核完全解耦。
* **我方借鉴**：消除明文 PNG 裸奔，构建内存解密资产 Vault（`cv2.imdecode`）。

### 3. 脚本3 (魔兽刷刷) 逆向与红旗
* **工程亮点**：`用户设置存档.json` 中的 `room_heirloom_bosses: [0, 0, 0]` 多房独立传家宝配置；像素比对异常返回 `999` 的故障安全语义；中文小字 2x 双三次插值。
* **严重违规红旗**：工程内捆绑 `一键关闭系统杀毒.zip` 暴力篡改 Windows Defender，严格拒绝（REJECT）。

---

## 四、 交给下一任审计 Agent 的核查任务单 (Audit Checklist)

请下一任审计 Agent（Reviewer / Independent Auditor）依本清单开展交叉核验并出具审计报告：

- [ ] **核查点 1（真源对应）**：核对 `COMPETITOR_SCRIPT1_SETTINGS_MAP_20260923.md` 中 74 个属性是否与 `GameScript.Models.Settings.cs` 100% 吻合；
- [ ] **核查点 2（增量图鉴）**：核对 1.6.3 新增的 9 个模板（`haizeiwang`、`buguimijing`、`lizhiji` 等）文件名、体积与时间戳是否与 `C:\Users\10639\Desktop\竞品\脚本1更新\1.6.3\Images\` 真实文件一致；
- [ ] **核查点 3（三栏裁决合理性）**：审查 `COMPETITOR_KNOWLEDGE_INDEX.md` 中的三栏裁决（应用/参考/REJECT）是否严格遵守“不盲目采纳竞品暴力 ESC 脱困”、“不破坏三本账隔离”与“不触碰免杀红线”；
- [ ] **核查点 4（S1~S6 对接点完整性）**：检查竞品各技术项是否已精准路由到总架构 S1（大厅找房）、S2（主线节奏）、S3（黑商/赌木）、S4（选卡/宝物）、S5（背包/装备）、S6（战后挑战）；
- [ ] **核查点 5（代码与环境安全）**：验证本轮所有产物是否纯属 `docs/` 目录下的文档，确认 `src/shuabao/` 未受污染，确认竞品 EXE 未被执行。

---

## 五、 卷宗签署

* **报告编制人**：Antigravity Pair Programming Agent
* **署名模型**：**Gemini 3.8 Flash (High)**
* **对接口径**：已严格与 `docs/handoff_20260923/HANDOFF_PROMPT_FOR_ARCHITECT.md` 契约对齐
* **当前状态**：全量资料就绪，封包交付独立交叉审计
