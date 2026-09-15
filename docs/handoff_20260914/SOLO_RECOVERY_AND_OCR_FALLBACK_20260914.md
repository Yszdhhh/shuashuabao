# 单人无人值守恢复 + 传家宝 OCR 兜底（2026-09-14 下午）

依据：云端审计 `review/audit-20260914:docs/reviews/CLOUD_AUDIT_20260914.md`（结论：单人长程 NO-GO，外发 NO-GO）。
分支：`feat/unattended-recovery-20260914`（基于 main@b348da7）。流程钩子在另一个 PR #22（`chore/main-guard-hooks-20260914`）。

## Owner 决策（2026-09-14）

1. **单人传家宝后的收口**：和蹭车同一套逻辑，窗口放长到 120 秒——出现已获取装备，或在广场满 120 秒。
   - 没开自动秘境：退出本局（装备 → VICTORY，超时 → TIMEOUT）。
   - 开了自动秘境：触发后标记"进秘境"，等传家宝 Boss 的胜利页 → 继续游戏 → 右键大秘境 NPC；传家宝后 240 秒内还没出胜利页 → 退出本局。
2. **0.4 external-beta 范围**：normal_farm + lobby_hitch；follow_team 推到 0.5（`mode_specs` 还没收窄，属于后续的发布 PR）。
3. **GitHub**：已关闭 squash / rebase 合并，只留 merge commit。
4. **CI**：GitHub Actions 因账号付款/额度问题，job 起不来（"recent account payments have failed or your spending limit needs to be increased"），需要 Owner 处理 Billing。main@b348da7 的 push run #190 就是因为这个失败的，不是测试失败。

## 本分支改了什么

### b7e636c 恢复与战后层
- 新增 `_unattended_recovery_enabled()`（normal_farm / lobby_hitch / follow_team）：只管"停局还是停整个运行"。动作授权仍是 fail-closed（未知页面零输入）；乘客业务规则仍用 `_passenger_mode()`。
- 单人不再停整个运行、改为重新武装的点：暂停恢复、胜利页不消失 / 继续游戏重试耗尽、未经胜利页进入存档面板或挑战广场（接管战后链）、存档面板 / 传家宝弹窗关闭重试、未实现的战后页、未验证的 archive 入口、继续游戏后转场、QUIT/NEXT 退出链、秘境确认框取消重试。
- 秘境各步超时 → `_abandon_secret_realm`：放弃本局秘境，按 VICTORY 退出本局。
- 战后总预算 300 秒、战后背包遮挡先关背包：扩大到所有无人值守模式；传家宝 Boss 自己的胜利页重新开始计时（修掉了"第二个胜利页时总预算早已超时 → 进不了秘境"的问题）。
- 无输入监督器：非蹭车模式只监督局内阶段（MAIN_LINE / RECOVER_FAILURE / QUIT / NEXT），升级顺序为软复位 → 退出本局 → BLOCKED；单人的大厅/房间流程不受影响。
- 所有外层上限仍在：整局截止 `round_timeout_s`（默认 3600 秒）、连续 3 局不成功熔断停机、各阶段停留上限。
- 7 条原有的 fail-closed 测试改为在 `mode_id="lab"` 下跑（lab 仍停机，机制保留）；`tests/test_unattended_recovery_20260914.py` 25 条钉住单人的新行为（其中 22 条在 main 上失败）。

### 04cc18a 感知层
- 传家宝入口阈值 0.58 → 0.70。
- `vision/label_boxes.py`：白色文字连通域切词框（纯函数，不做 OCR，也不授权点击）。
- `_heirloom_label_ocr_fallback`：只在所有模板都没命中、战后链进行中、顶栏是"存档"广场时启用；只在传家宝 ROI 内切词框 → 现有的框内 OCR → 读到"传家宝"（≥ 0.80）且第二帧同位置（±8 px）才返回标签；限流 1 秒一次，最多 4 个框。
- 真实 OCR：f0707 细体"传家宝挑战" 0.996、f0346 粗体 0.955；兜底点击 (1072,271)/(1079,277)，模板路径是 (1073,274)/(1081,279)。

## 暂缓（记账，没做）

- 云端 A2：顶栏否决从"绝对否决"降为"否决弱证据"——要防的场景（广场/团本里真的打开选关层）没有实机样本。
- 云端 A3：蹭车宝物末段兜底要"确认刷新耗尽后才盲选"——只影响蹭车。
- 云端 A4：聊天条和频繁开 V 的因果——先加观测，不改逻辑。
- 云端 A6：`GATE_BASELINE.json` 需要在资源稳定的机器上按正规流程 `--update-baseline` 重新生成。
- follow_team 从 0.4 外发范围收窄（`mode_specs` + 桌面入口），属于发布 PR。

## 需要实机验证（单人，正式版）

1. 正常一局：胜利 → 继续游戏 → 存档 8 卡 → 时光之穴 Boss → 关闭 → 广场 → 传家宝 → 装备 / 120 秒 →（开秘境）胜利页 → 秘境，或（没开）退出 → 回房间 → 下一局。
2. 至少遇到一次可恢复异常（例如手动按暂停、手动关掉存档面板），确认**只结束本局、不停整个运行**。
3. 传家宝入口：鼠标停在"存档挑战"上时，传家宝还能点到（细体模板 / OCR 兜底，看日志 `OCR 兜底两帧确认`）。
4. 长程：多局连跑，出问题时保留 bundle。
