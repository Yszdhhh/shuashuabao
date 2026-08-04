# 成功跑通流水（实机 2026-08-03）

来源：`%LocalAppData%\GameScript\20260803\log.log`  
对照失败轮次与 14:38 起成功轮次。

## 1. 失败 vs 成功

| | 失败（多轮） | 成功（14:38 起） |
|--|-------------|------------------|
| 卡点 | `等待进入游戏UI` → `未找到关卡/主线UI` | 同句之后出现 **`开始主线！`** |
| 主因 | 窗分辨率/界面未对齐（曾 1936×1066）+ Stage 可能无效 | 环境对齐后通过进入判定 |
| 超时 | ≈ QueryTimeOut 120s | 约 1 分钟内进入主线 |

## 2. 成功状态机（日志原文顺序）

```
保存配置成功
验证环境成功，准备开始游戏
等待所有人退出游戏状态！
开始游戏或开始准备游戏
已经准备游戏了
等待进入游戏UI
开始主线！                    ← 进入局内
卡都找完了！                   ← FindCardImages 循环（多次）
未找到集火，点击F1            ← 技能回退 PressKey("f1")
卡都找完了！…（持续）
```

## 3. 可恢复到本地工程的行为规则

1. **进房门闩**：等所有人退出 → 开始/准备 → 已准备  
2. **进入判定**：等「游戏 UI / 关卡主线」；超时用 `query_timeout`  
3. **主线**：`开始主线` 后进入选卡循环  
4. **选卡**：`卡都找完了` = 本轮 `CloseCardPanel` / `FindCardImages` 结束  
5. **技能**：优先找「集火」类模板/节点；失败 → **F1**  
6. **截图落盘**（失败时）：  
   - `CaptureScreen_*` 全屏  
   - `CaptureWindow_*` 游戏窗（成功诊断用）

## 4. 运维注意

- 游戏建议 **1600×900 窗口化**、缩放 100%  
- Stage 配置需对应界面真实关卡按钮  
- 脚本窗勿遮挡游戏  
- 急停：Shift+F12；暂停/恢复：F10/F11（UI 红字提示）

## 5. 本地 AutoJob 对齐建议

| 日志 | 本地步骤 |
|------|----------|
| 验证环境成功 | env check / mainIdentifier |
| 等待所有人退出 | gate before Entry |
| 开始游戏或准备 | EntryF1 / BeginGame |
| 已经准备游戏了 | ready flag |
| 等待进入游戏UI | FindNodeWithTimeOut(stage/main) |
| 开始主线 | SelectStage done → main loop |
| 卡都找完了 | CloseCardPanel / FindCardImages |
| 未找到集火，点击F1 | skill match miss → press_key f1 |
| 自动主线失败！,等下轮继续 | **软失败**：不退出进程，主循环 Continue 进下一轮（14:58 实机，约 30s 一次） |
| 游戏被中断了！ | **硬中断**：找图/节点链抛错；栈含 `AutoJob.jJplMSwIPy(Rectangle&)`、`AutoJob.WWMlr11etO`；会 `CaptureScreen`；进程可仍「运行中」 |
| UI 目标关卡 1 -- 15 | 脚本界面两框 Stage1/Stage2，右侧可配 Boss 名（非单纯 1-15 单关按钮） |
| 出现了提前挑战按钮，不需要发育时间！ | 命中提前挑战 → 跳过 DevelopTime 等待 |
| 锚点BOSS名称为07大法师阿鲁高 | 运行时解析锚点 Boss，名=模板 stem（`boss/07大法师阿鲁高.png`） |
| 找到锚点Boss了！ | 锚点匹配成功 |
| 开始查找龙珠7 | LongzhuJob：目标数量=DragonBallCount（配置 7） |
| 退出游戏时间还剩下N秒 | 局内倒计时（与 ArchiveBossTime/BoosLiveTime≈200 同量级） |
| 找龙珠，需要判断是否有战斗画面 | 龙珠查找前先判战斗场景，避免大厅误点 |
| QuitGame_*.png | 退出时截窗（样例 1616×939≈1600×900） |
| 大秘境失败 / 本局大秘境成绩 | AutoSecretRealm 开启时局末进秘境；失败后仍 QuitGame 并开下一轮 |
