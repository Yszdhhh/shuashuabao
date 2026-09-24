# 卡牌与道具视觉资料索引（2026-09-24）

供云端机制研究直接查阅的轻量资料包。竞品模板只表示竞品包实际使用的识别样本；机制和名称仍以我方实机证据、游戏卡面和来源明确的研究文档裁决。

## 本次新增的竞品参考图

源文件来自 `C:\Users\10639\Desktop\竞品`。这里只收录与卡牌/消耗品识别直接相关的小图，不包含竞品程序、反编译源码、支付码或无关资源。

| 类别 | 仓库文件 | 本地来源（相对 `竞品`） | 用途/边界 |
|---|---|---|---|
| 吞噬丹 | `script3_1366x768/pill_bag.bmp`、`pill_bag_2.bmp`、`pill_bag_3.bmp`、`pill_bag_4.bmp` | `参考脚本3/resolution_assets/1366x768/base_assets/` 同名文件 | 脚本3用于背包吞噬丹识别的 4 个模板变体 |
| 吞噬丹 | `script3_1366x768/pill_market.bmp` | 同上 | 脚本3用于黑市商品区吞噬丹识别的模板 |
| 英雄卡 | `script3_1366x768/yingxiongka.bmp`、`yingxiongka_2.bmp`、`yingxiongka_3.bmp`、`yingxiongka_4.bmp`、`yingxiongka_5.bmp` | 同上 | 脚本3用于背包英雄卡识别的 5 个模板变体；不代表 5 种不同英雄 |
| 海贼王 | `script1_1.6.3/haizeiwang.png`、`haizeiwangEx.png` | `脚本1更新/1.6.3/Images/` 同名文件 | 竞品 1.6.3 的普通态与 Ex 标记样本；`Ex` 文件名本身不能替代游戏卡面/机制证据 |
| 顶级属性卡 | `script1_1.6.3/lizhiji.png`、`minzhiji.png`、`zhizhiji.png` | 同上 | 力之极、敏之极、智之极的竞品图标 |
| 英雄卡礼包 | `script1_1.6.3/yingxiongkalibao.png` | 同上 | 英雄抽卡礼包道具图标，不是单张英雄卡面 |

## 脚本1 1.6.3 全量 `Images` 对照

已将本地 `脚本1更新/1.6.3/Images` 的 338 张 PNG 与 GitHub `main` 的 `assets/Images` 按相对路径和 SHA-256 对照：

| 对照结果 | 数量 | 处理 |
|---|---:|---|
| 路径相同且内容相同 | 186 | 已在云端，无需重复归档 |
| 路径相同但内容不同 | 75 | 作为竞品 1.6.3 版本样本归档 |
| 云端没有同路径文件 | 77 | 补入资料包；其中 6 张此前已在上表单独收录，不重复存放 |

本次新增归档 146 张，保留 `Images` 下的相对目录结构，放在 [`script1_1.6.3/Images/`](script1_1.6.3/Images/)；另外 6 张已收录于上表的独立参考图中。内容相同的 186 张没有复制进研究目录。

- `Images/cards/` 的 36 张卡族图全部已在 `assets/Images/cards/` 且 SHA-256 完全一致，因此不重复上传。
- `Images/skills/` 的 16 张中有 15 张与云端相同；`byj.png` 内容不同，已归档竞品版本。
- `boss/` 的 57 张和 `chuanjiaobao/` 的 21 张都已纳入资料包，覆盖云端缺失项和竞品版本不同项。
- 根目录的新增项包括大厅/房间按钮、英雄卡与技能/属性相关图标、状态提示等；`numbers/` 的 11 张声望等级数字图也已纳入。

本节只记录图像是否存在及字节内容是否相同，不据文件名推断卡牌机制。资料包仍是研究参考，不用于我方运行时模板。

## GitHub `main` 已有的我方证据

- [EX/最终形态卡面](../../../fixtures/ex_finals_20260814/README.md)：11 张用户提供的卡面截图，其中 10 张为 EX，海盗“毁灭战舰”为 UR。卡面词条索引在 `config/choice_lexicon.json`，机制备注在 `config/game_mechanics_kb.json`。
- “神赐吞噬丹”实机画面：[`fixtures/lobby_hitch_detail_20260814/t0282.00.png`](../../../fixtures/lobby_hitch_detail_20260814/t0282.00.png)，索引见同目录 `README.md`。这是地面道具的实机截图。
- 通用英雄卡道具图标：`assets/Images/hero_card_item.png`。英雄卡刷新来源和巫妖卡的区分备注在 `config/game_mechanics_kb.json` 与 `config/choice_lexicon.json`。
- 竞品能力与研究入口：[竞品知识索引](../../handoff_20260923/COMPETITOR_KNOWLEDGE_INDEX.md)。

本次搜索没有找到单独命名为“神赐英雄卡”的卡面文件。现有实机证据写的是“神赐吞噬丹”；本资料包把吞噬丹模板与英雄卡模板分开归档，避免把两个物品混为一谈。

## 使用范围

这些竞品小图是静态参考样本，不是我方运行时资源，也不能单独证明我方识别阈值、消费条件或吞噬目标。涉及吞噬丹的触发、购买、使用和背包空位规则，请对照我方实机记录、代码与机制 KB；竞品脚本行为只作为参考。
