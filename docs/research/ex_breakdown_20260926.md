# 10EX / 11EX 卡组拆解总览（2026-09-26）

> 来源：`G:\刷刷宝\nightwatch\` 下 ex11_video_analysis.md、macro_10ex_a.md、
> macro_10ex_b_guide.md、macro_strategy.md、ex10_gap_audit.md、
> video_haizeiwang_wangling_haidao.md、deck_feasibility.md、
> attribute_lines_ur_check.md，以及 `G:\刷刷宝\素材\系列标签\README_Owner口径.md`
> （Owner 口径最高优先）。
> 可信度：macro_10ex_b_guide.md 只收卡面机制文字，不收其中木材/时刻读数
> （逐行时间线可信度低）；11EX 逐分钟时刻表本轮未复核，只用机制方向。
> 全部事实已合并进 KB（`config/game_mechanics_kb.json`），每条带 source_level
> 与出处；与旧条目冲突的一律写进该条目 `conflicts`，不覆盖原文。
> 本次只动 KB 与本文档：`wired_to_decision` 未改，不接决策，不改 choice_policy / 代码。

## 大圣 / 神通

怎么启动：拿散件合大圣套装；怎么进阶：大圣套装合成后自动进化出 UR
齐天大圣（标签<大圣再临>，效果4开启神通卡组），再走神通进阶；
EX 是什么：青色 EX 法天象地（set_membership=神通），移池型；
脚本注意：大圣再临不是面板可选卡，不要进白名单、不要切标签模板。
KB：`card_pool_rules.dasheng_chain.owner_20260926` /
`card_pool_rules.dasheng_chain.ex_breakdown_20260926`。

## 刀刀

怎么启动：幽灵系带+护腕+空灵挂坠（need=3）→刀刀萌新；怎么进阶：
每击杀 200 自动发图纸，刀刀大成卡面"吞噬外刀刀卡并将 UR 图纸放入卡池"，
点金手自吞；EX 是什么：解放的圣剑（移除刀刀池+掷骰吞，掷骰吞几张未定）；
脚本注意：Owner 纠正"西瓦的守护"是错名，以游戏内"希瓦的守护"为准；
刀刀进行中看到刀刀装备系列（旋涡/风之杖/纷争面纱/风神杖/灵匣/绝刃/
雷神之锤/希瓦的守护）就拿；UR 实写"暗海猎手"非"暗夜猎手"。
KB：`card_pool_rules.daodao_chain.owner_20260926` /
`card_pool_rules.daodao_chain.ex_breakdown_20260926`（conflicts 记错名）。

## 异火

怎么启动：焚诀·黄阶（只开 N 池）；怎么进阶：杀敌吞噬自进阶
（黄→玄=3 为 live，其余阶段数未上帧），不靠店里丹；EX 是什么：帝炎；
脚本注意：旧 `yihuo_chain` 的火种/佛怒火莲口径已被
`yihuo_fenjue_pool` live 取代（conflicts 已记）；11EX"200 杀"说法与
"黄→玄=3"阶段口径不同，不可混为同一阈值。
KB：`card_pool_rules.yihuo_chain.ex_breakdown_20260926`（+conflicts）/
`card_pool_rules.yihuo_fenjue_pool`。

## 海盗

怎么启动：藏宝图(三) need=3 等散件；怎么进阶：掘金者产悬赏令，
悬赏令定向吞海盗杂卡换金币木材（不消耗通用吞噬丹）；
终局：UR 毁灭战舰（非 EX），开池 N 三张+SSR 重拳先生；
脚本注意：宝藏归海盗链（Owner）；悬赏令须在海贼王卡在场时用，
无海贼卡用则毫无收益（11EX 卡面）；吞 12 vs 橙悬赏出战舰未决。
KB：`card_pool_rules.haidao_chain.owner_20260926` /
`card_pool_rules.haidao_chain.ex_breakdown_20260926`。

## 海贼王（11EX 新增）

怎么启动：海盗 UR 毁灭战舰（技能劫掠）杀敌触发，或打破礼盒掉各阶悬赏令；
怎么进阶：R 普通海贼 3（恶龙/猫爪船长/东海霸主）→SR 超新星 3
（怪僧/少将/打碟人）→SSR 七武海 5（沙鳄鱼/海侠/女帝/大剑豪/多弗朗明哥）
→UR 四皇（红发/凯多），全阶"通过海贼王成长卡的效果吞噬"；
EX 是什么：EX 海贼王（品级 EX，不可吞噬；卡面已由 Owner 截图
`素材/机制抽帧/owner_screens/haizeiwang_EX_owner_20260926.webp`
逐字确认，见 KB `ex_card`）；11EX 录屏只看到深红 UR 顶阶
（Slot3 栏名"海贼王"，红发头像，数字 7→501），说明该局未到 EX（推断）；
脚本注意：Owner 口径无 (x/y) 进度、单卡杀敌吞噬、标签只写"海贼王"、
见快拿、同族高等级优先；阶段数 4/9/14/4 仍是攻略不可硬编码；
海贼王排海盗之后；与普通海盗链分开建模。
KB：`card_pool_rules.haizeiwang_chain_11ex`（新条目，EX 卡面见
`ex_card`；旧 `card_pool_rules.haizeiwang_chain_guide` 攻略桩不动）。

## 封神

怎么启动：姜子牙（卡面：累积 6 张封神卡→SSR 封神榜入栏）；
怎么进阶：法宝"通过炼化效果吞噬"（火尖枪/黄金棍/乾坤尺/落宝金钱卡面），
榜吞→天仙/天庭→三连跳各吞 5 法宝；EX 是什么：圣人（移除法宝池）；
脚本注意：张数全 guide；封神榜自动吞噬 70s vs 90s 未决（conflicts），
代码未接计时器。
KB：`card_pool_rules.fengshen_chain.ex_breakdown_20260926`（+conflicts）。

## 修仙

怎么启动：神秘戒指+流星泪+小绿瓶（need=3）置入练气期；
怎么进阶：木灵根→SSR 化神期，六九天劫 50% 进 UR 合体期，
其余境界配方全空（stage_need=null）；EX 是什么：大乘期（移除修仙卡组，
"元神出窍"彻底证伪）；脚本注意：首个 live 成员练气期当时不在推进组，
进组与否等 Owner 定；不要为对称复制亡灵 hold；五极山归修仙卡组，
拿满 5 个增大乘概率。
KB：`card_pool_rules.xiuxian_chain.owner_20260926` /
`card_pool_rules.xiuxian_chain.ex_breakdown_20260926`（+conflicts）/
`card_pool_rules.wujishan_20260926`（新条目）。

## 三国

怎么启动：乱世三国开池；怎么进阶：Owner 三国规则——魏/蜀/吴/群雄
最多拿 3 国，先出先得，第 4 国不再拿，已选 3 国有啥拿啥、
同族高等级优先、杀敌吞噬、3 国可同时拿；
EX 是什么：凑满 3 张 UR 武将后自动吞噬全三国、移池、置入 EX 吞食天地
（移池型；之后每吞 1 张全属性+1%，每击杀 400 随机吞 1 张）；
脚本注意：11EX 全拿四国做法与 Owner"最多 3 国"冲突时以 Owner 为准；
旧名天下归心/三国争霸存档备查；神兽须先于三国（吞食天地会吞神兽）。
KB：`card_pool_rules.sanguo_chain.owner_20260926` /
`card_pool_rules.sanguo_chain.ex_breakdown_20260926`（+conflicts）。

## 神兽

怎么启动：异兽蛋（60 秒自吞开神兽池，全属性+20）；怎么进阶：
同名互吞（guide：16 绿→1UR、4UR→祖龙，未上帧不写 need）；
EX 是什么：祖龙（移除神兽池）；脚本注意：机制存在≠初版做
（初版不上神兽/三国/龙族/军团）；蛋 60 秒是 live OCR，
丹跳过 60 秒未上帧。
KB：`card_pool_rules.shenshou_chain.ex_breakdown_20260926`。

## 龙族

怎么启动：巨龙军团（开龙族卡组，全属性+20）；怎么进阶：
五色龙 300 杀进巨龙之魂，瑞亚丝塔萨+纯净龙巢进迦拉克隆，
祈求 5/10 次上行（guide）；EX 是什么：世界末日迦拉克隆；
脚本注意：持续成长型——EX 后绝不停池（终局计数 16），
必须与移池型区分，只降权不停池；雏龙须杀敌进化，丹/三国吞不算。
KB：`card_pool_rules.longzu_chain.ex_breakdown_20260926`。

## 军团

怎么启动：燃烧的远征；怎么进阶：累吞 27 军团卡+栏内 3 张扭曲虚空点爆
（guide，未上帧不写 need，第三张是不可逆截止）；
EX 是什么：萨格拉斯（不拆池）；脚本注意：EX 后只降权；
后期廉价军团杂卡是吞食天地的饲料；初版不上军团。
KB：`card_pool_rules.juntuan_chain.ex_breakdown_20260926`。

## 亡灵

怎么启动：亡灵天灾 need=3；怎么进阶：亡者大厅回魂攒残骸，
符文/残骸路线（100 残骸+三符文各≥10 为 guide）；
EX 是什么：兵主（冰霜符文技能伤害×1.25 live）；
脚本注意：11EX t=160s 抓亡灵天灾；b 报告兵主 06:45 动机仅存档。
KB：`card_pool_rules.wangling_chain.ex_breakdown_20260926`。

## 祝福 / 基础属性线

祝福：每局默认必拿（Owner：看板移除，优先级祝福>成长经济>
当前高级卡组>其它；11EX t=15s 激活并吞噬祝福套装）。
基础/属性：力量线收束于 UR 屠戮者（杀敌力量+0.2，结算×1.05）；
魔法师/元素师是基础卡组（只加智力），不是属性线；
高级卡组间优先级由看板设置，不写进代码；同族按 N<R<SR<SSR<UR 拿高等级。
KB：`card_pool_rules.zhufu_blessing_20260926`（新条目）/
`card_pool_rules.attribute_lines_basic_20260926`（新条目）。

## 冲突清单（KB `conflicts` 汇总）

1. 刀刀"西瓦的守护"错名 → canonical 希瓦的守护（Owner 优先）。
2. `yihuo_chain` 火种/佛怒火莲旧口径 → 以 `yihuo_fenjue_pool` live 为准。
3. `xiuxian_chain` name/guide.ex 元神出窍 → 以 11EX 大乘期为准；练气期进组待 Owner 定。
4. `sanguo_chain` 11EX 全拿四国 → 以 Owner 最多 3 国为准；旧名天下归心/三国争霸存档。
5. 海贼王青色 EX 已解决：EX 卡面由 Owner 截图确认存在
（旧"青色 EX 未验证"表述作废，见 KB conflicts）；
4/9/14/4 仍是攻略；
   圣剑掷骰数、海盗吞 12 vs 橙悬赏均未决（见各条目）。
6. `ex_capstones` 吞食天地条目缺 remove_pool 字段待补（只补 KB，不涉接线）。
