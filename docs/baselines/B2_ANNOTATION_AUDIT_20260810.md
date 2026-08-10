# B2 数据集标注质量审计（B2-1 抽查）

> 日期：2026-08-10
> 分支：`codex/ocr-hybrid`（基线 HEAD=`473b568`）
> 范围：`fixtures/ocr_choices/manifest.json`（85 条目：skill 16 / bond 14 / treasure 18 / negative 37）
> 方法：分层抽样 12 面板（每类 4）+ 系统性问题扩审 8 面板 = **20 面板实机视觉复核**（designer 子代理读全帧 + 裁剪图双重确认，与 manifest `slots`/`has_*` 字段逐项比对）
> 蓝图依据：§18 验收项 5（抽查错例而非只看平均数）——本报告为"继续收集 shadow 数据"路线下的数据质量保证（B2-1 部分）

## 1. 抽样清单（12 面板，每类 4）

| # | entry id | 类别 | 会话 | 抽样理由 | 槽位核验 |
|---|---|---|---|---|---|
| 1 | rec7_short2_20260808_f_022_skill | skill | rec7（新会话，frame-ID swap 前科） | 天雷/焦点/次级增伤 | ✅ 一致 |
| 2 | rec3_260810_f_008_skill_corrected | skill | rec3（新会话） | 箭矢连发/电磁网/冰霜新星 | ✅ 一致 |
| 3 | rec5_260808_f_083_skill_corrected | skill | rec5 | 闪电链/飓风/地震 | ✅ 一致（按钮区"刷新次数不足"=禁用态，`has_refresh` 仍真） |
| 4 | rec1_ingame_boss_20260809_t_063s_技能面板 | skill | rec1 | 2 槽面板变体 + 品质 R/SR | ✅ 一致（光法 R / 潮汐猎人 SR） |
| 5 | rec7_short2_20260808_f_027_bond | bond | rec7 | 含 set_progress（3×0/3） | ✅ 一致（无放弃按钮标注也正确） |
| 6 | rec3_260810_f_015_bond_corrected | bond | rec3 | 含 set_progress（3×0/3） | ⚠️ `has_giveup` 错（见 §3） |
| 7 | rec5_260808_f_030_bond_corrected | bond | rec5 | 含 set_progress（1/3,1/3,None） | ⚠️ `has_giveup` 错（见 §3） |
| 8 | rec1_ingame_boss_20260809_t_417s_转折点 | bond | rec1 | 含 set_progress（0/2）+ SR/R/SR | ✅ 一致（无放弃按钮标注正确） |
| 9 | rec7_short2_20260808_f_033_treasure_3star | treasure | rec7 | 含 is_dragon_ball（三星球 0/7） | ✅ 一致 |
| 10 | dragonball_webp_20260807_image-ef3f2be8fc5d1103 | treasure | dragonball_webp | 含 is_dragon_ball（四星球 1/7） | ✅ 一致 |
| 11 | rec5_260808_f_112_treasure_corrected | treasure | rec5 | 含 is_dragon_ball（六星球 0/7） | ✅ 一致 |
| 12 | rec1_ingame_boss_20260809_t_393s_技能面板_龙珠首现 | treasure | rec1 | 龙珠首现帧（六星球 0/7） | ✅ 一致 |

### 1.1 扩审清单（系统性问题触发，8 面板）

| # | entry id | 类别 | 会话 | 结果 |
|---|---|---|---|---|
| 13 | rec5_260808_f_031_bond_corrected | bond | rec5 | ⚠️ `has_giveup` 错；槽位一致 |
| 14 | rec5_260808_f_033_bond_corrected | bond | rec5 | ⚠️ `has_giveup` 错；槽位一致 |
| 15 | rec5_260808_f_034_bond_corrected | bond | rec5 | ⚠️ `has_giveup` 错；槽位一致 |
| 16 | rec5_260808_f_035_bond_corrected | bond | rec5 | ⚠️ `has_giveup` 错；槽位一致 |
| 17 | rec5_260808_f_039_bond_corrected | bond | rec5 | ⚠️ `has_giveup` 错；槽位一致 |
| 18 | rec5_260808_f_041_bond_corrected | bond | rec5 | ⚠️ `has_giveup` 错；槽位一致 |
| 19 | rec5_260808_f_050_bond_corrected | bond | rec5 | ⚠️ `has_giveup` 错；槽位一致 |
| 20 | rec5_260808_f_051_bond_corrected | bond | rec5 | ⚠️ `has_giveup` 错；槽位一致 |

## 2. 不一致计数

- **抽查 12 面板**：不一致 **2** 条目（均 `has_giveup` 字段；槽位/品质/套装进度/龙珠标记 0 错）
- **扩审 8 面板**：不一致 **8** 条目（均 `has_giveup` 字段；槽位 0 错）
- **合计**：**10/20 面板有标注不一致，全部集中在同一字段 `has_giveup`，无任何槽位内容错误**
- 修正后：`has_giveup` 应为 `false` 的 bond 面板 = rec1(2) + reborn(1) + rec7(1) + rec3(1) + rec5(9) = **14/14 bond 全部无放弃按钮**

## 3. 修正明细

**字段：`has_giveup`（true → false）**，共 10 条目，`manifest.json` + `sources.json` 同步（+20/-20，仅此字段）：

| entry id | 旧值 | 新值 | 画面证据 |
|---|---|---|---|
| rec3_260810_f_015_bond_corrected | true | **false** | 按钮区仅"暂时隐藏 + 刷新"，无"放弃" |
| rec5_260808_f_030_bond_corrected | true | **false** | 同上 |
| rec5_260808_f_031_bond_corrected | true | **false** | 同上 |
| rec5_260808_f_033_bond_corrected | true | **false** | 同上 |
| rec5_260808_f_034_bond_corrected | true | **false** | 同上 |
| rec5_260808_f_035_bond_corrected | true | **false** | 同上 |
| rec5_260808_f_039_bond_corrected | true | **false** | 同上 |
| rec5_260808_f_041_bond_corrected | true | **false** | 同上 |
| rec5_260808_f_050_bond_corrected | true | **false** | 同上 |
| rec5_260808_f_051_bond_corrected | true | **false** | 同上 |

**佐证（非画面，结构性证据）**：
- `assets/Images/` 中只有 `skill_giveup_btn.png`，**不存在 `bond_giveup_btn.png`**（运行时 `mediator.py:546-550` `_selection_anchor` 对 bond 只查 `bond_hide_btn`/`bond_refresh_btn`）→ bond 面板结构上无"放弃"按钮，rec3/rec5 标注为同一批次系统性误标
- 其余 4 个 bond 面板（rec1 t_036s / rec1 t_417s / reborn bond_choice_3 / rec7 f_027）本就标注 `has_giveup=false`，与画面一致 → 佐证 rec3/rec5 的 10 个 `true` 为错

## 4. 未修正的观察项（证据不足，保持现状）

- rec5/rec3 bond 帧刷新按钮显示"刷新 40"（疑为刷新消耗货币而非次数），manifest `refresh_count=1` 语义为剩余次数——**字段口径未确认，不猜不改**
- rec5 f_083 刷新按钮为禁用态"刷新次数不足"——`has_refresh=true` 语义为按钮存在性，仍成立
- 全数据集 `is_valid=false` 槽位为 0（负样本无槽位），本次抽样未发现任何需降级为 UNKNOWN 的槽位

## 5. 抽查结论（标注总体可信度评估）

1. **槽位内容标注可信度高**：20 面板 × 3 槽 = 60 槽位逐一复核，卡名/品质/套装进度/龙珠标记 **0 错误**；含全部 4 类高危槽（is_dragon_ball、set_progress、2 槽变体、龙珠首现帧）与 rec1/rec3/rec5/rec7/dragonball_webp 5 个会话（含 frame-ID swap 前科的 rec7/rec3 会话）
2. **按钮存在性标注有系统性缺陷**：`has_giveup` 在 rec3/rec5 的 10 个 bond 面板上全部误标 true（占全数据集 85 条目的 11.8%）。根因：rec3/rec5 批注时未按面板类别区分按钮模板集合
3. **修复后数据一致性**：14/14 bond 面板 `has_giveup=false`，与资产模板清单、运行时分类逻辑完全对齐；修正后 manifest/sources JSON 合法，85 条目的 frame + crop 路径全部存在（缺失=0）
4. **对 B2-2 评测的影响**：`has_giveup` 不参与 OCR 槽位准确率评测（仅按钮存在性元数据），本次修正**不改变** 143 valid 槽位、top-1 1.46% 等既有指标；但修正了后续 shadow 收集/B3 运行时对 bond 面板"放弃"按钮的误预期风险（giveUp 模板 0.945 误检教训相关）

## 6. 交付信息

- 基线 commit：`473b568`（docs(ocr): B2 status refresh (85 panels, 143 slots, top1 1.46%)）
- 本次 commit：见 git log（`docs(ocr): B2 annotation audit fix has_giveup on 10 rec3/rec5 bond panels`）
- 改动文件（2）：`fixtures/ocr_choices/manifest.json`、`fixtures/ocr_choices/sources.json`（各 10 处 `has_giveup` true→false，diff +20/-20 仅此字段）
- 未实机验证项：`refresh_count` 语义（"刷新 40" 为消耗货币还是次数）、负样本 37 条目不在此次抽查范围
- 回滚方式：`git revert <本次 commit hash>`（纯数据文件，无迁移成本；或 `git checkout 473b568 -- fixtures/ocr_choices/` 单文件还原）
