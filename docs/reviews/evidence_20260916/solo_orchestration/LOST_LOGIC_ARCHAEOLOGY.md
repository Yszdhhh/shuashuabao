# 单人局内“丢失/退化逻辑”考古报告（2026-09-15）

- 范围：只读考古。仓库 `G:\刷刷宝\GameScript-Local`，当前代码 `G:\刷刷宝\Worktrees\live-solo-cc17962` @ `67ab08d`。未修改任何源码、未 checkout/commit。
- 证据来源：git 历史（`git show/log -S/-G`）、`%LOCALAPPDATA%\ShuaBao\<日期>\trace*.jsonl`（08-12~09-07 桌面/lab 生产 trace）、`%LOCALAPPDATA%\GameScript-Local\2026081x`（08-11/12 旧 trace）、`%TEMP%\shuabao-captures\solo_*`（09-07~09-15 harness 包）、`%LOCALAPPDATA%\ShuaBao\user_settings.json`。
- 标记：**【证实】**=代码+trace 双证据；**【疑似】**=代码证据成立、缺实机归因或需 Owner 定语义；**【无变化】**。
- 行号均指 `67ab08d` 当前树，除非写明 `<sha>:`。

---

## 0. 结论先行（给调度的 10 行）

1. 没有任何交接文档宣称过“单人一整局 L 级实机跑通”（0812 写 `r7 待验证`，0829/0831 写 `不能宣称`/`CONDITIONAL`）。Owner 记忆里的“以前没问题”对应的是 **08-11~08-28 的桌面实机 trace**：局内 G/F/V/进化/装备/Z/黑商/神器全部在转，单卡耗时 1.0~2.0s。
2. 分水岭是 **08-29 凌晨一串提交**（f1b4bc4 / 17c52d9 / e2a2714 / 59563fd）：F 锁到 80%、决策二帧确认+OCR 2500ms 下限、**空开面板（G/V 没点数不出面板）也计入每类 episode 上限且上限=本局永久隔离**。之后 trace 立刻只剩 F（08-29_011308：bond 18，技能 0）。
3. **当前树仍在的 P0**：`WAIT_VISIBLE` 超时（=正常的“没点数/次数不足”）仍给 skill/bond/treasure 的 episode 计数 +1（mediator.py:14701-14703），用户存档里 `panel_episode_limit_per_kind=5`（旧默认值被持久化，现默认 24）→ 5 次空开就触发 60s 冷却（今天前是永久）。08-21 版本到上限只是清零计数继续。
4. `_L1_CYCLE_ORDER` 的 `order.index()` 缺陷只存在于 core Mediator；**LIVE 实际跑的 RuntimeMediator 自 01163b1(08-26) 起就覆写了按位置推进**（runtime_mediator.py:227-251）。所以 LIVE 支线（V/进化/装备/Z/黑商/神器）不可达的真实根因是：F 锁强制 target=bond + 技能步“有卡就不转”+ 每张卡 ~9s（harness 下）→ 技能点永远抽不干。
5. 速度：open→pick 中位数 08-14~08-28 为 skill 1.4-1.6s / bond 1.6-2.0s；08-29 后 bond 2.9-5.2s、skill 5.8-7.3s。其中“+1 tick”来自 e2a2714 的二帧确认；另外 **harness 每个动作同步写 2 张 1600×900 PNG**（tools/live_scenario_capture.py:1914/3572-3575，一局 1.4GB），让 09 月实机 tick 中位数从 0.3s 变成 1.3-1.5s——这部分是测试壳开销，不是生产代码。
6. 蹭车期提交误伤单人：**F4 每 20s 自动按（8262ad8, 09-03，只对非乘客生效，违背 KB“打不过才按”）**、**黑商只买吞噬丹（d7d6dc2, 09-08，全模式，2折/5折/木材礼包不再买）**、Z 只在物品栏满时捡（d0087e3, 09-12）、看门狗去输入化（f4e0ef1/f91ffda, 09-08）。
7. ui-v2 迁移：`skill_archive_levels={}` 只影响技能**排序**（前置豁免/角色 CARRY/赠卡记账），不影响合法性 → P2；`exclude_ex` 在旧看板里本来就是空操作（EX 名不在卡组列表里），无损失；真正丢的是 **提速/体术 不可选**、官方流派不再带 祝福/体术、属性线旧顺序（门卡→整链→生存）。

---

## 1. “跑通”时点：trace 证据表（按日期）

| 日期/文件 | 代码时点 | 局内实际触发（actions.reason 计数） | 单卡耗时(open→pick 中位) | tick 间隔中位 | 结论 |
|---|---|---|---|---|---|
| 08-11 `GameScript-Local\20260811\trace_20260811_205100` | ocr-hybrid-dev，**ocr_mode=off**（模板模式） | bond 83 / skill 20 / V 10 / 进化 16 / 神器 4+4 / 黑商 1，8 分钟 | **1.0s** | ~0.3s | 模板+品质色最快；技能按 `Images/skills` 族图标直点（`click:assx/asj/jq`），羁绊按品质色（`rarity_red`×78，不守白名单） |
| 08-13/14 lab `trace_lab_20260814_123717_intelligence` 等 | lab_run.py（白名单=round1+整条属性链+生存+急速+support，`panel_episode_limit_per_kind=80`） | 24 分钟 3 局：秘法师13/智力12/法神9/湮灭者9/体术9/祝福9…，skill 55 | skill 1.5 / bond 2.0 | 0.3s | **属性线在 lab 里跑通过**（KB `attr_routes.strength.chain_evidence`：lab 152022 力量→野蛮人→战神→屠戮者 1/3） |
| 08-22 `ShuaBao\20260822\trace_20260822_181735` | d919544(08-21) 工作树，桌面 v0.3 | 19.6 分钟：OpenSkill 124 / bond 102 / OpenV 52 / 进化选卡 110 / ClickEvolve 10 / 装备 20 / Z 38 / 神器 8+8 / 看门狗 Esc 2 | skill 1.4 / bond 1.4 | 0.30s | **Owner 记忆中的“正常”版本**：整环在转 |
| 08-23 `195124` / `213904` | window 分支（559413d~64ece00） | 黑商吞噬丹 3、装备、ClickTQTZ→BossConfigured→ContinueGame→CloseArchivePanel→OpenGreatRift | 1.6-1.7 | 0.31s | 提前挑战+战后雏形首次出现 |
| 08-28 `233828` | 3434f0a~75135af | skill 13 / bond 6 / V 4 / 进化 6 / 装备 1 | skill 2.0 / bond 3.4 | 0.32s | 仍是全环，最后一份“正常”生产 trace |
| 08-29 `011308` | f1b4bc4+17c52d9+e2a2714 | **bond 18，skill 0**，V 1 | bond 2.9 | 0.51s | **退化起点** |
| 09-07 harness `solo_ingame_chain_20260907_220109` | b50a720 | bond 33 / skill 28 / **F4 41** / V 1 / 进化 2；存档6卡+Boss | skill 7.3 / bond 3.5 | 1.01s | harness 开销 + F4 |
| 09-14 harness `212509` | d9a47c1 | 前 300s 只有 F，之后技能连点；**V/进化/装备/Z/黑商/神器 = 0**；ClickTQTZ×3 后 615-1166s 零输入（afc0d9e 已修） | skill 5.8 / bond 5.2 | 1.35s | |
| 09-14 harness `225835` | 498ac65 | bond 45 / skill 27 / V 0；VICTORY→存档→时光Boss→传家宝打开后直接 Dismiss→秘境×3→退出 | 5.8 / 3.6 | 1.5s | 战后链能走，局内仍缺支线 |
| 09-15 harness `000229` | 807f443 | bond 43，**skill 0**；tick≈281 起 `panel_state=COOLDOWN` 直到结束 | — | 1.32s | 252e35f 修的就是这份 |

（统计脚本：scratchpad `summ.py`/`lat.py`；tick 间隔取 MAIN_LINE 相邻 ts 差。）

---

## 2. 逐环节对比总表

| 环节 | 跑通时实现（提交/位置） | 现在实现（67ab08d） | 差异 | 判定 | 引入退化的提交 |
|---|---|---|---|---|---|
| 开局：英雄声望/自动任务/四挑战 | 7fcefa3(08-11) 4-State+settle；08-22 trace 各 1 次 | `_ensure_auto_task_enabled`/`_ensure_challenge_buttons`（mediator.py:16111-16126） | 无实质变化；09-14/15 trace 仍各点一次 | 【无变化】 | — |
| L1 环顺序/推进 | d919544 `_L1_CYCLE_ORDER`+`order.index()`（d919544:mediator.py:2736-2754）；LIVE 由 runtime 覆写按位置推进（01163b1 起） | core 今日 252e35f 改位置推进（4087-4117）；runtime 早已是位置推进（runtime_mediator.py:227-251） | core 缺陷只影响非 LIVE/单测 | 【证实，但非 LIVE 根因】 | d919544(08-21)，LIVE 不受影响 |
| F 锁（基础羁绊 80% 前强制 F） | 无；bond/skill 交替 | 4171-4181：`_bond_step_blocked()` 为 None 且 `_bond_base_progress_pending()`（3274-3286）就把 target 改成 bond | 基础名单现为 祝福/成长/经济/贪婪/挑战+3 条属性门卡+法术/急速/魔能/暴击/魔术 ≈13 张，需拿到 11 张才放开；今日仅加了“木材<500/长冷却/上次无卡 30s 退避”三道出口 | 【证实】 | f1b4bc4(08-29 00:08) 加锁；17c52d9(00:34) 开局改从 bond 起；20752af/3bc37ac(09-14) 把属性门卡并入 base 使门槛变高 |
| 技能步“有卡就不转” | 同样语义（`_finish_panel_episode` 只在本次没选才推进，d919544:6459-6472） | 14452-14464 相同 | 语义没变，但 08-22 单卡 1.4s 能很快抽干，现在 ~9s/张抽不干 → 支线饿死 | 【证实（组合效应）】 | 无单一提交；由 e2a2714 变慢放大 |
| 面板 episode 上限 | d919544:2781-2811：到上限**清零计数继续开**；空开（WAIT_VISIBLE 超时）**不计数**（d919544 同段、3434f0a 同段） | 空开计数 14701-14703；上限在 solo 分支=清零+60s 冷却+转下一步（4225-4239，今日加）；自然面板上限=60s COOLDOWN（14665-14667）；用户存档 limit=5 | 正常“没点数/次数不足”被当异常；5 次后该面板 60s 不可用 | 【证实，P0】 | **59563fd(08-29 15:35)** 空开计数+上限=`inf`；0f6cfc9(09-09) inf→60s 但每 tick 重置（000229 冻结）；252e35f 部分缓解 |
| COOLDOWN 期间 HUD 其他动作 | COOLDOWN 到期即归位 | 14965-14971：solo 且无锚点时直接 finish，今日加 | 修复 | 【已修】 | 0f6cfc9 / 59563fd |
| 羁绊选择 | 3434f0a 前 soft 白名单+祝福系统必拿；08-22 走 OCR+`_match_preset` | hard 白名单（config/choice_policy.json bond.whitelist_mode=hard，must_take=[]）；`matches_bond_preset` 子串族匹配（choice_policy.py:1458）；差一张秒选（1099-1124，4878026）；已持有合成优先（1319-1327） | soft→hard、祝福不再系统必拿（需用户勾） | 【语义变化，Owner 已拍板】 | 3434f0a(08-28) |
| 属性线 | 旧 Qt `_attr_line_tokens()` chain+support 展开（main_window.py:3137-3152）；lab 按 bond_priority 顺序拼白名单 | 今日后端按 `_ATTRIBUTE_CHAINS` 展开 chain（choice_policy.py:437-449），support 移到 ui-v2 BASIC | support（魔法师/元素师/血誓）不再随属性线自动带 | 【已查实，今日部分补】 | ui-v2 迁移 |
| 技能选择 | OCR 名→`_rank_skill_candidates` 族匹配（01163b1 起）；ocr off 时模板直点 | 3811-3828 live 只走 OCR；3901-3906 live 下禁用 `skills/*` 模板；二帧确认 3683-3702 | 多 1 tick；OCR 4+3 槽扫描 2944-2951 | 【证实：变慢】 | e2a2714(08-29)；99e6c37(09-12) 3 槽补扫放宽到 named_4≤2 |
| 刷新策略 | 羁绊 OCR miss 可刷新（08-12 版烧木头） | OCR miss 禁止刷新（3731-3733, b5d924d）；技能 focus miss 在已验证刷新钮上刷新 | 合理收紧 | 【无退化】 | b5d924d(08-29) |
| 宝物 | 08-16 878ae4e must_take（ONEPIECE 等）优先；08-22 V 52 次 | 普通模式“先滤负面，再纯按品质”，must_take 只在最高品质档内生效（choice_policy.py:1211-1250） | EX 四宝不再跨品质必拿 | 【语义变化，需 Owner 确认】 | d4aa92c(09-09，自称“产品裁决”) |
| 进化 | ClickEvolve→英雄二选一按品质（d919544 自适应阈值） | 16189-16240 同结构 + 3 次无反馈放弃 | 逻辑在，但环走不到 | 【可达性退化】 | 同 F 锁/技能饥饿 |
| 装备 | `_maybe_upgrade_equipment` 1 号位 max + 十级词缀 | 81a0e3a(08-27) Equipment FSM；16242-16248 | 08-28 后无实机样本 | 【可达性退化】 | 同上 |
| 拾取 Z | 周期按 Z（08-22：38 次/19 分钟） | 仅物品栏 2-6 全满才 Z（16261-16274） | 频率大幅下降 | 【疑似误伤】 | d0087e3(09-12 “fix(hitch)”，未按模式隔离) |
| 背包道具（吞噬丹/英雄卡） | pickup 步里 `_maybe_use_inventory_item` | 同（16279-16285） | 环走不到 | 【可达性退化】 | — |
| 黑商 | 9718d7d(08-27) Owner 定：吞噬丹+木材+2/5 折；08-30 系列修槽位 | merchant_scanner 只买吞噬丹；且需杀敌数 OCR≥0.95 才花钱（`_merchant_kill_budget_allows`） | 单人不再买木材/折扣 | 【疑似误伤，P1】 | **d7d6dc2(09-08)** 全模式收窄；d0087e3(09-12) 余额门控 |
| 神器 QWE | 7ee9d61/91e2995 周期释放 | 16181-16187 同 | 环走不到 | 【可达性退化】 | — |
| F4 清挑战怪 | 不存在；KB 08-14：“打不过才按，还打得过禁止误按” | `_maybe_clear_pressure_monsters` 每 20s 按 F4（7996-8010），只对**非乘客**（16145） | 单人每 20s 清一次场上挑战怪，可能丢挑战怪的木材/经验奖励、并占 tick | 【疑似误伤，P1】 | **8262ad8(09-03 lobby-hitch 集成)** |
| F1 英雄焦点 | 01163b1 两帧确认缺英雄面板→F1 | 7659-7718 同；仅 `_panel_state==CLOSED` 生效 | COOLDOWN 挂死时 F1 不跑（000229） | 【已修】 | 0f6cfc9；252e35f 修 |
| 看门狗 | d919544：15s 无动作→Esc+步进环；runtime 有 EscUnstuck/PanelFailForward（08-22 trace 各 1-7 次） | runtime 看门狗纯遥测（runtime_mediator.py:304-340）；core 15s 只步进环（16315-16320） | 不再按 Esc 解遮挡 | 【设计变更】 | f4e0ef1 / f91ffda(09-08) |
| 3s 品质盲选兜底 | d919544:6776-6795 | 08-22 已删（14882 注释） | 安全性原因删除 | 【不恢复】 | 01163b1 快照内 |
| 提前挑战 tqtz | 559413d(08-23)，08-23 trace 可达 Boss | 7780-7919：点凤凰图标、确认框、放弃后让出 tick | 09-14 连修 3 处 | 【已修】 | afc0d9e / 59d2c86 / 3bc37ac |
| 5-5 取消自动主线 | 始终只在 tqtz 点击时置位（01163b1:3754） | 同（7916-7917）；B3 在 solo-fixes 分支加任务栏 OCR | 从未有独立 5-5 检测；原版 1.3.8 是 5-5 波次后清怪+关主线一次 | 【无变化/从未实现】 | — |
| 胜利/失败 | fccbaa1/20cd40b | b7e636c 单人改“结束本局不停运行” | 增强 | 【无退化】 | — |
| 存档挑战 8 卡 | 85f9a2f~981d974(08-30) | f9f725f 一次扫 8 卡+一次复核 | 增强 | 【无退化】 | — |
| 传家宝 | 08-30/31 cjb_boss 配置+滚动+红色特效防误判 | 04cc18a OCR 兜底；a3e7ba7 单人直接去秘境 NPC | 225835 打开后未点 Boss 就 Dismiss（1056→1061s） | 【疑似，需看帧】 | 858f84a(“挑战次数不足即停”)? 待查 |
| 秘境 | 08-23 OpenGreatRift 雏形 | a3e7ba7/3bc37ac NPC 本体右键 | 仍缺真实 HUD 验收 | 【新增中】 | — |
| 下一局房间 | 同房间直接开始 | b5e2390(09-09) 每局离房重建 → 3bc37ac 改为仅 `new_room_every_times` 时离房 | 已修 | 【已修】 | b5e2390 |
| 无进展监督 | 无 | b7e636c：MAIN_LINE 180s 无输入→软复位，`_l1_cycle_step="bond"`（11274） | 可能把环拉回 bond | 【轻微，P2】 | b7e636c(09-14) |

---

## 3. 速度相关旧逻辑：族类/模板直拿、双帧确认的来龙去脉

| 机制 | 时间线 | 现状 | 建议 |
|---|---|---|---|
| **技能按族图标模板直拿**（`Images/skills/{asj,jq,assx...}.png` → `_match_all_preferred(skills/…)`，命中即点） | 08-06 d40811c / 08-08 13a4d1a 起；08-11 205100 trace 实证 `click:assx/asj/jq`，open→pick 1.0s | 代码仍在（mediator.py:3901-3922），但 `ocr_mode=="live"` 时 `preferred=[]` 被关掉；live 是默认值（08-12 起 trace 全部 live） | **按新架构重写**：live 下先跑族模板作为 `SlotCandidate.family` 证据；模板族∈焦点族且 OCR 名同族时单帧直点（免二帧），不一致才走二帧 |
| **羁绊按品质色选**（rarity_red） | 08-08 4cc222d；08-11 trace 78 次 | bcb3f48(08-12) A3 旁路切断，bond/card 禁品质/第一张 | **不恢复**（违背白名单） |
| **羁绊标题字模模板**（`Images/cards/*.png` 44×24 matchTemplate） | ffb3cfd(08-29) | 3066-3118：只在 OCR 空/低置信时补名，OCR 仍先跑 | 可提前为主路径：字模≥0.90 且在白名单 → 单帧直点 |
| **族匹配**（成长 匹配 成长之根） | 3434f0a(08-28) `matches_bond_preset` 子串 | 仍在（choice_policy.py:1458） | 保留 |
| 面板锚点双帧确认 | e997b39(08-12) “panel dual-frame confirm” | 14643-14645 仍在 | 保留（成本低） |
| **决策二帧确认**（同 slots 同决策第二帧才点） | **e2a2714(08-29 01:03)** “prefer OCR stability over speed” | 3683-3702；仅 `差一张合成/已持有合成` 免确认（4878026） | B2 已计划：白名单全名命中+conf≥0.95+无歧义免确认 |
| OCR 单槽超时下限 2500ms | e2a2714 | runtime 构造 `max(2500, …)`（runtime_mediator.py:81）；用户存档 1200 被抬到 2500 | 下限只影响超时尾部；可降到 1500 |
| 4 槽优先扫描 / 3 槽补扫 | e2a2714 为 `named_4<2` 才补扫；99e6c37(09-12) 放宽到 `named_4<=2` | 2944-2951：bond 常见 3 名+1 弱时每 tick 读 7 槽 | 回到 `<2`，或按 anchor 布局检测只扫一次 |
| 3s 品质盲选/固定坐标推进 | d919544 加、08-22 删 | 已删 | 不恢复 |
| Harness 同步写 PNG | test/solo-live-harness(09-07 起) | 每个动作 before/after 两张 PNG（live_scenario_capture.py:1914,3564-3575），22 分钟 1.4GB | 测试壳改异步/降采样/JPEG，否则实机测速失真 |

实测对比（open→pick 中位秒 / tick 间隔中位秒）：08-11 模板 1.0/0.3 → 08-14 lab 1.5-2.0/0.3 → 08-22 1.4/0.30 → 08-28 2.0-3.4/0.32 → 08-29 2.9/0.51 → 09-14 harness 5.2-5.8/1.35。09-14 一张技能：OPEN(305.8)→WAIT_VISIBLE(307.0)→ACTIVE 首帧 OCR 1406ms(309.2)→二帧确认+点击 1665ms(311.6)→CLOSED(313.1)→再开(314.9) ≈ 9s/张；08-22 同流程 OPEN→点 1.3s。

---

## 4. 蹭车改动误伤单人清单（09-03 以后，未按 `_passenger_mode()` 隔离或只对 solo 生效）

| 提交 | 日期 | 改动 | 对单人的作用 | 判定 |
|---|---|---|---|---|
| 8262ad8 | 09-03 | F4 每 20s（`if not self._passenger_mode()`，16145） | **只有单人**在按；与 KB `hotkeys.F4.script_rule=press_when_challenge_unwinnable` 冲突；每次占一个 tick 且重置 `_main_line_since` | 【疑似误伤 P1】 |
| d7d6dc2 | 09-08 | merchant_scanner 只买吞噬丹 | 单人丢掉 木材礼包/2折/5折 → 木材更紧（Owner 09-15：木材<500 F 买不动） | 【疑似误伤 P1】 |
| f4e0ef1 / f91ffda | 09-08 | runtime 看门狗与 Fail-Forward 去输入化 | 单人失去 Esc 解遮挡；依赖 core CLOSING | 【设计变更 P2】 |
| 0f6cfc9 | 09-09 | 面板上限 inf→60s，但 solo 分支每 tick 重置 60s | 000229 整局冻结 | 【证实，已由 252e35f 修】 |
| d4aa92c | 09-09 | 普通模式宝物纯品质序 | EX 必拿不跨档 | 【需 Owner 确认】 |
| b5e2390 | 09-09 | 每局离房重建 | 单人换房 | 【已修 3bc37ac】 |
| d0087e3 | 09-12 | Z 只在满栏时；黑商花费需杀敌数 OCR≥0.95，否则 15s 后再看 | 单人 Z 频率骤降；黑商 OCR 读不出就永远不买 | 【疑似误伤 P1/P2】 |
| 99e6c37 | 09-12 | 3/4 槽平局补扫放宽 | 每 tick 多 3 次 OCR | 【变慢 P2】 |
| 9eeec80 / b7e636c | 09-12/14 | 无进展监督扩到 normal_farm | 180s 无输入软复位环到 bond | 【轻微 P2】 |
| 57b7064 / 3af605e | 09-13 | 蹭车 V 指纹/预算 | 均在 `_passenger_mode()` 内 | 【无影响】 |

非蹭车但同样关键：**59563fd(08-29) 空开计数+永久隔离**、**f1b4bc4/17c52d9 F 锁**、**e2a2714 二帧确认**（见第 2/3 节）。

---

## 5. ui-v2 迁移丢失字段与影响

旧 Qt：`collect_settings_from_ui()`（main_window.py:4272-4343）+ `assemble_whitelist_cards()`（3181-3205）+ `_attr_line_tokens()`（3137-3152）+ `_advanced_pack_tokens()`（3154-3168）。ui-v2：`pushBondsAndAttributes()`（ui-v2/src/main.ts:246-279）、`ADV_PACK_CARDS`（236-244）、`BASIC`/`DEFAULT_PRESETS`（ui-v2/index.html:3030-3041）；后端 facade 只映射 `skills/bonds/attributes/merchant/treasure`（dashboard_facade.py:896-906），`cards` 走顶层字段。

| 字段/语义 | 旧 Qt 写入 | ui-v2 现状（user_settings.json） | 局内影响 | 等级 |
|---|---|---|---|---|
| `skill_archive_levels` | `archive_grid.get_levels()`（16 系存档等级） | 无控件，存为 `{}` | **只影响排序，不影响合法性**：①`waived_prereq_names`（skill_catalog.py:445）存档豁免前置→`priority_rank`（choice_policy.py:900-915）；②`skill_role_rank` 按最高存档定 CARRY（choice_policy.py:918-928，用户恰好 4 系所以生效）；③`grant_on_learn_card` 赠卡不记入已学（mediator.py:3233-3238）→“缺主技能优先键”可能重复追已赠送的主技能；④`skill_chain_rank` 只在 fill 模式（关闭）。存档解锁卡不会被拒点（`is_skill_choice_legal` 不看存档） | P2 |
| `smart_route_disabled_amplifiers` | smart_route_panel | 存 `[]`，无控件 | 仅角色排序 | P2 |
| advanced pack `exclude_ex` | 过滤 `ADVANCED_PACKS[*].cards` 中的 EX 名 + 固定禁 {解放的圣剑,帝炎,法天象地} | ui-v2 `ADV_PACK_CARDS` 不含 EX 名，无过滤 | **旧逻辑本就是空操作**（official_strategy_defaults.json 各包 cards 均不含 exclude_ex 名）；hard 白名单外 EX 不会被点 → 无损失。**风险**：solo-fixes 分支 B4 计划“按 catalog group 自动补全成员”，若补全不走 exclude_ex（混元金斗/飞升/冰封王座…）会把 EX 带进白名单 | 当前无影响；B4 需带上 exclude_ex |
| 基础卡 提速/体术 | `BASIC_PACK_NAMES`=祝福 成长 经济 贪婪 挑战 提速 体术 固守 陷阵 急速；官方流派 arcane_open 带 `tishu` | ui-v2 `BASIC` 无 提速/体术；GROWTH 只有 5 张 | **体术（破甲10%，KB round3 “优先级极高”）和提速无法勾选**；08-14 lab 体术拿了 9 次，09-14 为 0 | P1 |
| 祝福 | `BOND_ALWAYS_CODES=["zhufu"]` 组装永远带上 | ui-v2 DEFAULT_PRESETS 的 growth 不含 祝福；3434f0a 又删了策略层必拿 | 用户没手勾就永远不拿（当前存档有勾，暂无影响） | P1（默认值） |
| 官方流派属性/UR 卡 | `apply_official_build` 写 `zhili/yanmiezhe/fs` 到 cards | ui-v2 流派只带 `attr:["intelligence"]`，后端今日按链展开 | 等价（今日补） | 已补 |
| 属性线 support | chain+support 一起展开 | 后端只展 chain；support 放 BASIC（魔法师/元素师），力量 support 血誓 无处勾 | 小 | P2 |
| 白名单顺序 | lab/bond_priority：round1→整条属性链→生存(提速/体术/固守/陷阵)→急速→round4→support | bonds→属性链→高级包→basic（choice_policy.py:428-460 + main.ts:259-268） | `_match_bond_preset` 按名单位次排序；80% 后高级包排在 法术/急速 前 | P2 |
| `bond_inverted` / `bond_scheme`（_shell） | 反选基础卡 → 从 cards 剔除 | 残留 `["提速","tishu","gushou","xianzhen","jisu"]`，但 cards 里却有 急速；运行时不读 `_shell` | 无运行影响，只是脏数据易误导 | P2 清理 |
| `panel_episode_limit_per_kind` | 旧默认 5（08-11~08-25），deepcopy 持久化 | 仍是 **5**（默认已是 24） | 叠加 59563fd 的空开计数 → 5 次空开就冷却 | **P0** |
| `ocr_timeout_ms` | 1200 | 1200（运行时抬到 2500） | 无 | — |
| 其余（stage/cycle/房间/boss/秘境/主线/考古/声望/路线/优先级） | 有 | 有 | 等价 | — |

---

## 6. 恢复清单（按优先级）

### P0（直接造成单人停滞/饿死）
1. **空开不计数 + solo 上限不惩罚**（59563fd）  
   恢复方式：**直接恢复旧语义**——`WAIT_VISIBLE` 超时（mediator.py:14701-14703）在 solo 下只做 `ui_action_interval_s` 冷却、不加 `_panel_episode_count`（蹭车 treasure 分支 14692-14700 已是这个思路）；episode 计数只留给 hard-deadline 超时/CLOSING 失败。同时做一次**设置迁移**：`panel_episode_limit_per_kind<24` 的旧存档抬到 24（或 facade 加载时忽略低于默认值的旧值）。
2. **F 锁只约束“F 里拿什么”，不劫持环**（f1b4bc4/17c52d9）  
   恢复方式：**按新架构重写**——删掉 4176-4177 的 `target="bond"` 覆写，80% 门槛只留在 `choice_policy._decide_collectible`（1263-1281）里决定可选卡；环内 bond 连续两格（`_L1_CYCLE_ORDER` 已是 bond,skill,bond,skill）足以保证羁绊优先。与 solo-fixes 分支 B1“有上限抽干 3 次/30s”合并做。
3. **技能步有上限抽干**：同 B1；并以 08-22 为验收基线（19 分钟内 V≥20 次、进化/装备/Z/神器均>0）。
4. **单帧直点快路径**（e2a2714 的代价）：  
   恢复方式：**重写**——白名单全名/族模板一致且 conf≥0.95 免二帧（B2 已列）；3 槽补扫恢复 `named_4<2`（撤 99e6c37 的放宽，或按布局检测只扫一种）。目标 open→pick ≤2s（08-22 为 1.4s）。

### P1（资源/收益被误伤）
5. **F4 自动清怪只在 KB 规则下触发**（8262ad8）：先改为默认关闭（`auto_pressure` 进 Settings、默认 False），待 Owner 定“打不过”判定；或恢复原版语义“5-5 后清一次”。**需 Owner 确认 F4 是否会清掉四挑战怪导致丢木材**。
6. **单人黑商恢复 木材礼包 + 2折/5折**（d7d6dc2）：**直接恢复旧 `rank_purchases` 三优先级**，按 `mode_id` 隔离（蹭车保持只买吞噬丹）；杀敌数 OCR 读不到时单人按旧行为（刷新钮存在即可刷新），不要无限等 OCR（d0087e3）。
7. **ui-v2 补 提速/体术 基础卡、流派预设默认带 祝福**：改 index.html `BASIC`/`DEFAULT_PRESETS` 与 main.ts `basicNames`（main.ts:651）。
8. **Z 拾取频率**（d0087e3）：单人恢复“到期即捡”（10s 节流）或满 4 格即捡，蹭车保持满栏才捡。需 Owner 定。
9. **测试壳去 PNG 同步写**：harness 改异步队列或只在失败/书签时落帧，否则实机测速不可信。

### P2（排序/体验/清理）
10. `skill_archive_levels`：**按新架构重写**——ui-v2 加 16 格存档等级（或接 `player_profile.py` 的存档页 OCR 采集），写回 `skill_archive_levels`；在此之前可在 policy 里对 `{}` 记一次告警。
11. `smart_route_disabled_amplifiers`、属性线 support（血誓）、白名单顺序（按 bond_priority 分层）补到 ui-v2 或后端组装。
12. `_shell.bond_inverted/bond_scheme` 迁移清理，避免与 cards 冲突。
13. 无进展监督软复位不要把 `_l1_cycle_step` 硬拉回 bond（11274），改为保持当前步或只清面板态。
14. 传家宝 225835 “打开即 Dismiss” 查帧确认是否挑战次数不足。
15. d4aa92c 宝物纯品质序：请 Owner 确认 EX 四宝（ONEPIECE/至高进化/一身神装/满级大佬）是否要跨品质必拿。
16. solo-fixes B4 自动补全 catalog group 时必须应用 `exclude_ex`。

### 不建议恢复
- d919544 的 3s 品质盲选 / 固定坐标点击推进（已证实会乱拿，08-22 删除）。
- 模板模式下羁绊按品质色选（违背白名单）。
- runtime 看门狗盲按 Esc（无前台校验，09-08 去掉有理由）；若要恢复，只允许在“两帧确认局内 HUD + 已知遮挡面板锚点”时点已验证关闭按钮。
- `order.index()` 相关无需再动：LIVE 早已位置推进，core 今日已对齐。

---

## 7. 对“已查实退化”的补充更正
- `_L1_CYCLE_ORDER order.index()`：缺陷真实，但 **LIVE（RuntimeMediator）自 01163b1 起覆写为位置推进**（runtime_mediator.py:227-251，`git log -S "not tuple.index()"` 仅 01163b1），所以它不是 09-14/15 实机支线为 0 的原因；真正原因是 F 锁 + 技能抽不干 + 慢。
- 0f6cfc9 的 60s COOLDOWN 不是“为蹭车新加的限制”，而是把 59563fd(08-29) 的 `float("inf")` 永久隔离改成 60s；solo 在它之前就会被永久隔离，09-09 后仍因每 tick 重置而等同永久。
- `skill_archive_levels={}`：只降排序质量，不会让技能停拿。
