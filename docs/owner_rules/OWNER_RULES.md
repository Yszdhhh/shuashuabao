# Owner 局内规则（唯一文档）

> 交接提示词只写一句：**读 `docs/owner_rules/OWNER_RULES.md` 和 PR 51。**
> 审查、实现、GPT、云端都以本文件为准；旧蓝图、记忆、交接文档与本文件冲突时以本文件为准。

## 怎么用

- 每条规则 = Owner 原话时间 + 代码位置 + 锁定测试。锁定测试登记在
  `tests/test_owner_ingame_rules_lock_20260924.py` 的 `OWNER_RULES`；删规则或删测试都会变红。
- **改规则**：必须有 Owner 原话和日期，同一个 PR 里同时改本文件、代码、`OWNER_RULES`。
- **新规则**：先写进本文件（状态标 ❌ 或 ❓），再改代码、补锁，最后把状态改成 ✅。
- 拿不准的口径写进文末「待 Owner 确认」，不要猜。
- 状态：✅ 已实现且有锁 · ⚠️ 被削弱或扩大（写明谁在修）· ❌ 没实现 · ❓ 待确认

对账基准：PR 51 头 06f5c9d（2026-09-26）。

## 1. 调度与拿卡顺序

| # | 规则 | Owner 原话时间 | 代码 | 锁定测试 | 状态 |
|---|---|---|---|---|---|
| 1.1 | 羁绊主路径（含吞噬丹）> 技能 > 宝物、黑商、其它；开局先花木材点羁绊 | 09-15 / 09-20 / 09-24 | `mediator._L1_CYCLE_ORDER`、`_l1_step_visit_exhausted` | 锁表「木材 <500 先技能」「木材 ≥500 先羁绊」「≥1000 羁绊压技能」 | ✅ |
| 1.2 | 前期先把祝福拿完，再做点击进化、英雄选择、神器 | 09-26 04:59 | `mediator._blessing_set_pending`、HUD「OpenBondPanel-BlessingPriority」、`_direct_template_bond_pick` | `test_direct_family_pick_20260926` 祝福相关三条 | ⚠️ OCR 路径必拿分支只看"一张祝福都没有"，第 2、3 张会被成长/经济抢。omp 分支 fix/restore-owner-rules-20260926 在修 |
| 1.3 | 有标签模板的卡族匹配到就直接拿，不做 OCR；全没命中才走 OCR | 09-26 04:59 / 05:09 | `mediator._direct_template_bond_pick` | `test_direct_family_pick_obeys_owner_priority_and_skips_rarity_reads` | ✅ |
| 1.4 | 祝福不看等级不看内容直接拿；从看板移除勾选项，每局默认必拿、最高 | 09-26 02:16 / 04:59 | ui-v2 `pushBondsAndAttributes` 总附祝福；`DEFAULT_BOND_MUST_TAKE` | 锁表「同页优先级」 | ✅ |
| 1.5 | 羁绊同页：祝福 > 成长/经济 > 当前高级卡组 > 其它白名单；贪婪、固守等其余基础卡与普通卡组同级 | 09-26 02:16 | `choice_policy.choose_action` 羁绊分支 | 锁表「同页优先级」「基础羁绊同页顺序」 | ✅ |
| 1.6 | 高级卡组之间的先后由看板优先级设置决定 | 09-26 03:10 | `assemble_policy_settings` 按 `cards` 顺序选组 | `test_advanced_pack_order_follows_dashboard_priority` | ✅ |
| 1.7 | 同一时刻只推进一组高级卡组，羁绊栏出现蓝色 EX（海盗为 UR）才解锁下一组 | 09-24 | `_active_advanced_presets` | 锁表 | ✅ |
| 1.8 | 高级卡组不设硬门槛（不等基础 80%、不等 480 秒） | 09-23 / 09-24 | 同上 | 锁表 | ✅ |
| 1.9 | EX 靠合成得到，不从面板拿（海贼王例外：卡族名与 EX 同名，看到就拿） | 09-24 / 09-26 | `ex_final_names` | 锁表「EX 靠合成链」 | ✅ |
| 1.10 | 同一卡族优先拿高等级卡（N<R<SR<SSR<UR，用徽标读） | 09-26 | `_direct_template_bond_pick` 同族读徽标 | `test_direct_family_pick_uses_rarity_only_for_same_priority_ties` | ✅ |
| 1.11 | 开局四挑战固定位置一次连点再核对，漏了补点（木材漏点要补） | 09-26 04:59 / 05:09 | `_ensure_four_challenges_fast` | `test_four_challenge_batch_retries_still_off_wood_immediately` | ✅ |
| 1.12 | 亡灵默认不勾 | 09-26 | `config/default_settings.json` cards=[]；看板标实验 | 无 | ✅（无锁） |

## 2. 木材两种模式（09-26 03:43，"溢出"沿用 500）

| # | 规则 | 代码 | 锁定测试 | 状态 |
|---|---|---|---|---|
| 2.1 | 木材持续溢出（≥500）：核心是快速合成 EX，不管黑商（缺吞噬丹例外） | `mediator._solo_wants_merchant` | `test_solo_does_not_want_merchant_when_pill_and_wood_are_available` | ✅ |
| 2.2 | 木材不溢出：从技能、进化、黑商等支线补战力；F 每轮最多 1 张（500–1000 两张，≥1000 十五张） | `_l1_step_visit_exhausted` | 锁表「木材 <500 以支线循环为主」 | ✅ |

## 3. 羁绊刷新、兜底、禁拿（09-26 03:33）

| # | 规则 | 代码 | 锁定测试 | 状态 |
|---|---|---|---|---|
| 3.1 | 羁绊没有放弃，必须拿一张；100 木材刷新最多 3 次，还没目标就按优先级拿一张（白名单优先、再按稀有度） | `DEFAULT_MAX_REFRESHES=3`、`_best_available_bond_pick` | `test_refresh_exhaustion_selects_best_readable_card_even_outside_whitelist` | ✅ |
| 3.2 | 兜底不拿未勾选高级卡组的卡 | `_best_available_bond_pick` | `test_refresh_fallback_never_takes_an_unticked_advanced_pack` | ✅ |
| 3.3 | 禁拿名单默认空、看板可配，禁拿卡永远不拿 | `bond_candidate_allowed`（现只剩禁字法/安身法） | 无 | ⚠️ `bond_negative_names` 被删；"PR 51 云端审查与 debug"线程在恢复 |
| 3.4 | 满槽顶替只点 OCR 认出的非目标卡，认不出零输入 | `_bond_capacity_candidates` | 锁表 | ✅ |

## 4. 吞噬丹与亡灵

| # | 规则 | Owner 原话时间 | 代码 | 锁定测试 | 状态 |
|---|---|---|---|---|---|
| 4.1 | 羁绊栏 ≥8/10 才吃，每吃一颗重读，降下来就停；单人默认吃（看板不加开关） | 09-24 / 09-25 | `_DEVOUR_BOND_OCCUPANCY` | 锁表 | ✅ |
| 4.2 | 只有专心做亡灵时停吃丹；其它卡组（含属性链）照常吃 | 09-26 06:57 | `_devour_hold_reason` | 锁表「亡灵卡组进行中不吃」 | ⚠️ 被扩到属性链，#57 在修 |
| 4.3 | 亡灵进行中也不为丹去黑商 | 09-26 | `_solo_wants_merchant`、`_urgent_merchant_reason` 都没看 `_devour_hold_reason` | 无 | ⚠️ omp 在修 |
| 4.4 | 羁绊栏空位 ≤2 没丹、木材 <500：插队去黑商，回到被打断的步骤；黑商一步按 H | 09-24 / 09-25 | `_urgent_merchant_reason`、merchant 步 | 锁表两条 | ✅ |
| 4.5 | 亡灵：三种碎片各 10 再拿亡者大厅；邪爆初版不上 | 09-26 | 无 | 无 | ❌ Owner 已延后（看板标实验） |

## 5. 卡族（白名单必须含卡族名本身）

白名单来源：`config/choice_policy.json` `bond.advanced_groups`（`DEFAULT_ADVANCED_GROUPS` 同步）。
看板 `ui-v2/src/main.ts` `ADV_PACK_CARDS` 只负责选中哪一组，组里多出的卡同样生效。
锁：`tests/test_owner_pack_whitelist_lock_20260926.py`、`tests/test_slow_pack_pickup_lock_20260924.py`。

| 卡族 | 规则 | 标签模板 | 状态 |
|---|---|---|---|
| 大圣 | 子卡族多；「大圣再临」是套装合成后自动进化出的 UR，不在面板出现，不需要模板 | dasheng / 残躯 / 套装 | ✅ |
| 海贼王 | 全是单卡，杀敌吞噬，没有进度；看到就拿；有 EX | 仓库暂无（本机待合入） | ✅ 目前走 OCR |
| 异火 | 同上，看到就拿 | yihuo | ✅ |
| 刀刀 | 旋涡、风之杖、纷争面纱、风神杖、灵匣、绝刃、雷神之锤、希瓦的守护都是刀刀装备，和起手三件（幽灵系带/护腕/空灵挂坠）、萌新、大成一起进刀刀组，按游戏实际名字 | daodao | ✅（#59 补 8 件装备）。**完整逻辑待 Owner 补充，见 §5.1** |
| 修仙 | 五极山属修仙，拿满 5 个提高出大乘概率；终卡大乘期 | 仓库暂无（本机待合入） | ✅（#59 补五极山） |
| 三国 | 魏蜀吴群雄四选三：哪国先出先拿该国启动卡，拿满 3 国不拿第四国；已选 3 国有啥拿啥、高等级优先 | sanguo | ❌ #55 在做 |
| 海盗 | 藏宝图(三)开池；终形态 UR 毁灭战舰 | cangbaotu | ✅（#59 补藏宝图） |
| 亡灵 | 见 §4 | wangling | 只到拿卡 |
| 封神 | — | fengshen | ✅ |
| 属性线 | 魔法师、元素师是基础卡（只加智力，不在智力链）；屠戮者是力量线 UR 终点 | — | ✅ `_ATTRIBUTE_CHAINS` |

### 5.1 刀刀（待 Owner 补充）

> Owner 在线程里写刀刀逻辑，先落这里，再改代码、补锁。

（空）

## 6. 英雄卡与进化

| # | 规则 | 代码 | 锁定测试 | 状态 |
|---|---|---|---|---|
| 6.1 | 点击进化没点完前不用英雄卡（金条亮着物品栏零点击） | `_maybe_use_inventory_slot` | 锁表首两条 | ✅ |
| 6.2 | 英雄卡 EX > UR > SSR > 未知进化 > SR > R | 进化二选一 `rarity_rank` | 无 | ❓ EX 没有单独色带 |

## 7. 其它

| # | 规则 | Owner 原话时间 | 锁定测试 | 状态 |
|---|---|---|---|---|
| 7.1 | 装备词条按颜色 橙>紫>蓝>绿>白 | 09-25 | `test_equipment_affix_color_hierarchy` | ✅ |
| 7.2 | 画面飞离战后大厅 → F2；看板丢失 → F1；弹窗先 Esc 再点叉 | 09-24 | 锁表三条 | ✅ |
| 7.3 | 急停 Shift+F12；F9 标记 | — | 外壳层 | ✅（无局内锁） |
| 7.4 | 背包清理：看板开关默认关，每 10 局一次；蹭车走局内「存档→装备→一键分解」（精良、史诗勾，传说不勾）；单人走选关页「存档」；认不出退出不重试，45 秒未确认即停 | 09-25 | `test_backpack_clean_disabled_zero_input`、`test_backpack_clean_45s_hard_cap_converges_and_no_retry` | ✅ |
| 7.5 | 负面宝物默认不拿；EX 宝物出现就拿 | 09-15 / 09-22 | 锁表 | ✅ |
| 7.6 | 单人物品栏满时 2–6 格左键试用；蹭车不动物品栏 | 09-23 | 锁表 | ✅ |
| 7.7 | 打不过自动降级 | 09-15 | 锁表 | ✅ |

## 待 Owner 确认

1. 祝福几张算"拿完"？代码按"持有 3 张名字带祝福的卡"。刷不出第 3 张时会一直优先开羁绊面板、F 次数上限也被关掉，可能饿住进化和技能。要不要设上限？
2. 刀刀"风神杖"和词库里的"封神杖"是不是同一张？若是"封神杖"，会和封神卡组名字冲突。
3. 刀刀图纸（点金手、深渊之刃、随缘之刃、龙心、三元重戟、阿哈利姆神杖等）要不要拿？
4. 英雄卡 EX 边框是什么颜色？
5. 修仙、海盗的中间卡（练气期、四九天劫、悬赏令、开进码头、剑柄/剑刃等）要不要全拿？
6. 木材溢出时技能要不要也让路？现在只停了黑商。
