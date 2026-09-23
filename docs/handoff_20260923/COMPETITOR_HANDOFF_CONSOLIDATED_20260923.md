# 竞品分析线整合交接文档（给架构审查 Agent）

> **日期**：2026-09-23
> **编制**：独立交叉审计 Agent（本轮实测：只读静态，未执行任何竞品 EXE，`src/` 零触碰）
> **前序交付**：Gemini 3.8 Flash (High) 8 份拆解 + 交接卷宗（`CROSS_AUDIT_DOSSIER_20260923.md`，SHA-256 `EADE17F7…0E101`）
> **本轮动作**：真源复核 + 纠偏 + 整合。本文件为架构审查唯一入口，原始 8 份保持原样备查，凡与本文件冲突以本文件为准。

---

## 1. 资料地图（读这 1 份 + 按需下钻）

| 本文件章节 | 下钻原文（`docs/research/`） | 状态 |
|---|---|---|
| §2 真源基线 | `COMPETITOR_FULL_ANALYSIS_20260922.md`（§1–§6 总矩阵，§7.5 缺口，§1.6.2 Boss） | PASS |
| §3 四家矩阵 | `COMPETITOR_FEATURE_EXCLUSIVITY_MATRIX_20260923.md` | PASS |
| §4 落地三项 | `COMPETITOR_GAPS_DEEP_DIVE_LANDING_20260923.md`（看门狗/网格/几何） | CONDITIONAL（属新设计，需真机标定） |
| §5 脚本1全量 | `COMPETITOR_STATIC_OBSERVATIONS_1_6_2_20260922.md` + `…_1_6_3_20260923.md` | 1.6.2 PASS；1.6.3 CONDITIONAL（PDB 数字待重填，见§7） |
| §5 Settings | `COMPETITOR_SCRIPT1_SETTINGS_MAP_20260923.md` | CONDITIONAL（74→78，默认值重标，见§7） |
| §6 脚本3/竞品2 | `COMPETITOR_STATIC_OBSERVATIONS_SCRIPT3_20260923.md` + `…_COMP2_20260923.md` | 脚本3 PASS；竞品2 CONDITIONAL（按 92 版重测，见§7） |
| 前期基线 | `docs/architecture/COMPETITOR_KNOWLEDGE_SYNTHESIS_20260910.md`、`origin/docs/research-20260922`（solo 实机/19+2 负面宝物/Boss 重测） | 权威事实底座，不动 |

---

## 2. 三家竞品一页结论

| 维度 | 脚本1 GameScript 1.6.3（C# + OpenCvSharp + FlaUI） | 脚本3 魔兽刷刷（Python + 大漠 dm.dll，~21000 行） | 竞品2 刷刷护肝宝92（按键精灵 + VMP 壳） |
|---|---|---|---|
| 跟进速度 | 最快：1.6.2→1.6.3 九图增量（海贼王/不归秘境/三极卡） | 中：v91/638 文件 sha 流水线 | 慢：79→92 仅 Loader 升级，Payload 复用 |
| 感知路线 | 模板 + FlaUI UIA（与我方同路，版本一变即崩） | 找图 + 颜色 + OCR 三层 + 看门狗（24h 托管最稳，但绑死 1366×768+100%DPI+前台独占） | 绝对坐标（最脆） |
| 状态机 | 嵌套 while + Sleep + 暴力 ESC（拒抄） | 平铺轮询 + 全有界 FSM（宝物12刷/龙珠6→7/-zs≤3） | 热键脚本 |
| 商业化 | 在线授权 + 飞书 Webhook 闭环 | 试用/月卡/永久 + 更新器 | Loader+加密 Vault 解耦 + 签名 Overlay（拒抄后者） |
| 对我方价值 | 图鉴同步节奏 + 战后参数化 + 从动开关语义 | 故障安全语义 + 否定证据 + 多房隔离模型 | 打包架构思想（合法实现） |

---

## 3. 四家独占/缺口矩阵（架构行动直达）

| 领域 | 结论与行动 |
|---|---|
| 大厅 | 我方与脚本1并列第一（UIA 路线）。补 `NewRoomEveryTimes` 每局新房配置（防 KK 句柄卡死，>10h 挂机） |
| 混车从动 | 我方领先（20s 压力转移 + 滞后从动 + 房主离场 Fail-Closed）。吸纳脚本1 `OnlyTransfer` 纯工具人模式 |
| 选卡 | 我方领先（25 帧证据 19 负面硬过滤）。吸纳脚本3 `locks_text` 锁词法思想；拒绝脚本1 `Y+40` 盲点 |
| 黑商 | 我方两段式原子预算（≥440 杀敌）+ 脚本3 刷新像素哈希否定证据 + `999` 采样失败语义（永不误判资源尽） |
| 战后图鉴 | **P0 缺口**：传家宝 `21界龟`、时光 `55吞咽者布鲁/56狩猎者阿娅米斯/57无疤者奥斯里安`、`mingyuntouzi` 命运骰子、`emptyArtifact` 空槽；核查 catalog 末项「莫阿姆」疑似串项 |
| 传家宝分层 | 吸纳脚本1 `SmallCJBoss 1/2/3` + 脚本3 `room_heirloom_bosses[3]`：按阶段/按房隔离目标（前期 15 猛虎之神 → 后期 39 拉格纳罗斯/21 界龟） |
| 取证 | 学脚本1 `CaptureWin`：失败默认落 incident 截图包 |
| 通知 | 补用户可配飞书 Webhook（超时/急停/连局异常），“异常@all否则直推”节流 |
| 打包 | 中长期：Loader + 加密 Vault（内存 `imdecode`），研发明文/发行加密双轨 |

---

## 4. 落地三项（新设计，需真机标定后进 production）

1. **业务进度令牌看门狗**：心跳 + 业务令牌双轨；连续 300s 零业务推进熔断；恢复只发单一 ESC + 重校准页面身份（禁三连 ESC/盲点大厅）。
2. **18 Boss 虚拟网格**：弹窗可视 4–5 槽、`NumberOfScroll` 1–4 次滚轮、禁右键；分三阶段选 Boss（§3 传家宝分层）。
3. **3/4 选一自适应几何**：`Xi = X0 + (2i+1)/2N · W`；OCR 阶段鼠标收束安全区 `(0.5W, 0.05H)`；点击卡片下沿热区 `Y+35px` 防 Tooltip 遮挡。

---

## 5. 脚本1 Settings 78 项（已纠偏，原表“74 项”作废）

真源 `Desktop\竞品\竞品分析资产\01_参考脚本1更新\反编译源码\GameScript.Models\Settings.cs`。**原表默认值列大面积失真，不可引用；下表为实测值**：

- 房间：`RoomPassword="111"(config 里是空)/RoomName=null/NewRoomEveryTimes=false/FollowTheLead=true(原表误false)/GameMode=0(0–6: 独狼/带队/赌木/蹭车/邪修/多开/考古)/RoomTimedOutAndExited=60s(原表误0)/GameTimeOut=15/QueryTimeOut=200/MoveWindow=true(原表误false)`
- 选关：`Stage1=3/Stage2=2/StageSelectInterval=500ms(原表误0)/NumberOfScroll=1`
- 龙珠多开：`DragonBallCount=7/FindLongzhuInGame=true/FindLongzhuWhereMultiGame=false/OnlyTransfer=false/OnlyTransferWhenMultiGame=false/FindGiftWhenMultiGame=false`
- 传家宝：`CJBBoss=15猛虎之神/SmallCJBoss/2/3=同/SmallCJBCustomSetting=false/SGZXBoss=39拉格纳罗斯/ArtifactMode=3(原表误0)/ArtifactDelay=0`
- 卡组技能：`Skills=[]/Cards=[]/AutoCard=true(原表误false)/AutoWeapon=true(原表误false)/ASJJSFirst=true(原表误false)/SanlingFirst=false`；增伤 8+1 全默认 false；卡组 10 项 + 技能 16 项（`Skill.cs`）；`GetBoss()` 系读盘动态扩展，加 png 即扩展
- 声望：`AutoReputation=false/Level1–6=0/Stage1=3/Stage2=2/ReputationEffect=false`
- 时长：`BoosLiveTime=0(原拼写)/KillBossNum=600(原表误0)/DevelopTime=0/CycleNum=99(原表误0)/ArchiveBossTime=120s(原表误0, 自点传家宝 Boss 起算总预算)/TreasureNum=3(原表误0)/AutoGamblingTime=270s(原表误0)`
- 秘境：`AutoSecretRealm=false/ContinueMiJing=false`；通知：`BatFile` 飞书 Webhook
- 原表方法列（`AutoJob.FindRoom()` 等）系可读化意译，真源符号为混淆名，引用时须声明。

---

## 6. 红线（架构审查一票否决项，竞品线与架构线一致）

1. 关 Defender / 一键杀毒包（脚本3运营诱导，代码层无调用——按运营风险拒，不是按 API 拒）
2. 签名 Overlay 免杀（竞品2，正规签名证书路线代替）
3. 绝对坐标盲点（脚本1神器三连点 `(1210,760/810/870)`、脚本3 56 处 COORD、1366/1600 硬锁）
4. 暴力 ESC ×3 / 强退进程 / 绕过 OSK 连点
5. VMP 高熵壳（成本/误报/调试三输）
6. 海贼王提前赋权：仅许进 staging 图鉴 + `buguimijing` 独立判页锚点；`must_take`/账本特权等实机核准；海贼王≠海盗羁绊（生命周期解耦）
7. 小模板降阈（0.74–0.78）、声望 0 当战力、`DevelopTime=0` 无脑提前挑战照抄

---

## 7. 原 8 份已知勘误（架构引用时绕行）

| # | 勘误 | 影响 |
|---|---|---|
| 1 | “74 项”→实为 **78**；默认值列多处归零失真；方法名系意译 | 用§5，不用原表默认值/方法列 |
| 2 | PDB/XML 体积：报告 `74,240/53,889/203,788B` → 实测 `83,432/29,795/458,207B` | 重填后引用 |
| 3 | 竞品2 按 79 版（15.88MB）描述 92 样本（17,076,862B）；`zmtibtux` 高熵在 92 已漂移；overlay 剩余约 6MB 未知区；6 分卷功能归属系加密态推测 | 结构结论可用，版本数字与分卷功能标“未证实” |
| 4 | 术语三套并存：竞品 S1–S6 / 总图 L0~L3（L1 沉底）/ AGENTS.md 五层。对照：S1≈L0大厅，S2≈L0主线+L2预算，S3≈L2三本账+L1黑商，S4≈L3管线+L1技能羁绊宝物，S5≈L1装备，S6≈L0战后；SEC（打包）≈外壳层 | 架构落点以 AGENTS.md 五层为准，S 编号仅作竞品引用 |
| 5 | GAPS 文是新设计非竞品实测；FULL§P0“莫阿姆串项”标疑非定论 | 均须真机标定，不得直入 `src/` |

---

## 8. 给架构审查 Agent 的输入清单

- **可仲裁入库**：§3 表格行动项、§4 三项设计（标定后）、§5 开关语义（`NewRoomEveryTimes/OnlyTransfer/FollowTheLead/ArtifactMode` 的配置模型，不含竞品默认值）、staging 图鉴增量（§3 P0 缺口 + 海贼王/三极/不归秘境锚点）。
- **不仲裁**：拿卡默认值、打分权重、状态机改动——按 `HANDOFF_PROMPT_FOR_ARCHITECT.md` 走 architect 流程；未经真机验证的竞品数据绝不进 `src/shuabao/`。
- **合规确认**：本轮产物全在 `docs/`；`src/` 经 `git status` 验证零修改；竞品 EXE 零执行。
