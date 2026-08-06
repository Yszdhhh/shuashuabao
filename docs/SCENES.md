# 场景 · 方法 · 模板对照表

从 `1.3.3.3` 元数据闭包名 + 帮助文档 + `Images/` 文件名交叉还原。  
机器可读表：`config/scenes.json`。

---

## 1. 原 AutoJob 方法链（闭包名，可信）

```
Start / LaunchGame / BeginGame
  → CreateRoom                 # 带队：建房
  → EntryF1                    # 进房/点开始
  → SelectStage                # 选关
  → FindAllMatchImages         # 视觉原语：全图匹配
  → FindCardImages             # 卡牌区匹配
  → FindNodeWithTimeOut        # 单节点+超时
  → FindNodesWithTimeOut       # 多节点+超时
  → CloseCardPanel             # 关卡牌面板
  → CloseSkillPanel            # 关技能面板
  → ChangeMainLineStatus       # 主线开/关（含 F4 5-5）
  → ClickOKBtn                 # 通用确认
  → MonitorGameOver            # 监听结束
  → QuitGame                   # 退出/结算后处理
  → Run                        # 总循环
```

辅助：

| 方法 | 层 |
|------|-----|
| CaptureWin | 截窗 |
| PressKey | 按键（F4 等） |
| GetBoss / GetAllSkill / GetAllCardGroups | 模板库枚举 |
| SaveSettings | 存配置 |
| Valida* | 环境校验（名称截断为 Valida） |

---

## 2. 一局主循环

### 2.A 文档语义（帮助）

```
环境检测 → [带队] CreateRoom → Entry → SelectStage → 主线循环
→ 卡/技能面板 → 龙珠/宝物 → [可选]F4 → 结束 → 秘境/清理 → 下一局
```

### 2.B 授权后真实日志语义（2026-08-03 样例）

```
验证环境成功，准备开始游戏
  → 等待所有人退出游戏状态！
  → 开始游戏或开始准备游戏
  → 已经准备游戏了
  → 等待进入游戏UI          # FindNodeWithTimeOut，时限≈QueryTimeOut
  → [失败] 没找到游戏进入标识！  # mainIdentifier
  → 开始主线！ / 自动主线失败！
  → CaptureWin → Local\GameScript\{date}\CaptureScreen_*.png
```

Boss 配置值 = 模板 stem，例如 `CJBBoss=10马格纳斯` → `chuanjiaobao/10马格纳斯.png`。

---

## 3. 模板分类（根目录 + 子目录）

### 3.1 流程控制

| 逻辑键 | 模板文件 |
|--------|----------|
| start | startGameBtn, continueGame, jihuo |
| ok | ok, yes |
| close | close, failGiftClose, quit |
| fail | fail, gameFail, giveUp |
| disconnect | gameDisconnect, retryConnect |
| pause | pauseGame |
| auto_flag | zidong |
| env_anchor | mainIdentifier, shortKey |

### 3.2 选关 / 挑战

| 逻辑键 | 模板 |
|--------|------|
| stage | stage, stage1, stage2, stage3, stage4 |
| hero | toHero, HeroChallenge |
| archive | archiveChallenge, cundang, cundangInfo |
| skill_challenge | skillchallenge |
| tuanben | tuanben |
| boss_entry | boosIcon, cjbBoss, cjbBossbak, sgzxBoss, cjbtiaozhan |

### 3.3 卡牌 / 技能面板

| 逻辑键 | 模板 |
|--------|------|
| card_panel | card_hide, hide, cardRefresh, heroRefresh |
| skill_panel | skill_hide, noSkillNum, skillRefreshGift |
| cards/* | 36 张属性/职业卡（FindCardImages） |
| skills/* | 16 个技能短码（Settings.skills 默认 jq,pg） |

`skill_choice` / `fetter_choice` 使用中央三选一 ROI；若设置项可见，优先点击
`Settings.skills` / `Settings.cards` 中的图标。`treasure_choice` 在缺少宝物图集
时只在已确认的选择面板内点第一张卡，不会点击右下角刷新计数。

### 3.4 龙珠 / 宝物 / 赌木

| 逻辑键 | 模板 |
|--------|------|
| longzhu | longzhu, longzhu2, closeLongzhu |
| treasure | treasurechest, treasureRefreshGift, baowushuaxin, bwRefresh, 2000baowu |
| wood | woodgift, woodSuccess |
| refresh | refresh, shuaxinquan, shuaxinquan3 |
| coin_challenge | challenges/coin_challenge |
| wood_challenge | challenges/wood_challenge |
| experience_challenge | challenges/experience_challenge |
| treasure_challenge | challenges/treasure_challenge |

挑战按钮先匹配底部标签，再把点击点上移到图标中心；若按钮上方已经是绿色
“自动”，只记录为已开启，不重复点击切换状态。

### 3.5 秘境 / 考古

| 逻辑键 | 模板 |
|--------|------|
| secret | damijing, mijingOk, kaogu, kaoguMode |

### 3.6 清理 / 品质

| 逻辑键 | 模板 |
|--------|------|
| clean | decompose, zhuangbei, baoshi, cibao |
| rarity | r, sr, ssr, ur, ex, hc |
| quality | pinfu, pingfu1–4, pingfu6 |

### 3.7 职业/技能表现图（战斗内识别或点选）

根目录大量中文拼音图，例如：

- 兵种/技能：`bingjianguanchuang`, `bolidapao`, `duochongjian`, `laser`, `ray`…
- 角色：`mofashi`, `fengwuzhe`, `manwuzhe`, `yinwuzhe`…
- 关卡标记：`5-6` … `5-10`, `1-23`

→ 归属 **战斗中识别 / 选卡优先级**（奥数增伤等），不是主流程门闩。

### 3.8 Boss 图库

| 目录 | 用途 |
|------|------|
| boss/01–51 | 主线/声望 Boss 点选（Settings CJB/SGZX 名） |
| chuanjiaobao/01–17 | 传家宝 Boss |

---

## 4. 模式差分

| 模式 | 行为差 |
|------|--------|
| 独狼 | Entry 主动点开始 |
| 带队 | CreateRoom；不主动开始，等自动开 |
| 赌木 | 只主线 + 第一宝物；刷新耗尽 ZS 重开；找到 wood → pauseGame + 通知 |
| 邪修秘境 | 其它功能关；只打已选 Boss |
| 自动秘境 | 局末进 damijing，直到失败 |
| 自动声望 | Reputation* 关卡/Boss；赌木下不触发 |
| 自动清理 | 每 auto_clean_interval 局 decompose 链 |

---

## 5. 视觉原语（重建接口）

```
FindAllMatchImages(names, timeout?) -> list[Match]
FindCardImages() -> list[Match]          # cards/*
FindNodeWithTimeOut(name, timeout) -> Match | None
FindNodesWithTimeOut(names, timeout) -> list
ClickOKBtn()  ~= click ok/yes
```

超时默认对齐 `query_timeout`（秒，实机标定）。

---

## 6. 仍未知（无新材料暂挂）

- GameMode 整型枚举表  
- SelectStage 的 Stage1Rec 屏幕矩形  
- Find* 的匹配阈值与多尺度  
- 「ZS 重开」具体按键/点击目标  
- 奥数四卡对应的 cards 文件名精确映射  
- MonitorGameOver 判定优先级细节  

有实机截图后优先补这几项。
