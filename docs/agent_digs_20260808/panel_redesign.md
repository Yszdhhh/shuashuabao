# 英雄三国挂机助手 (GameScript-Local) 控制面板简化重构方案设计书

## 1. 重构背景与核心目标

### 1.1 当前 GUI 面板 (desktop_app.py) 痛点分析
1. **界面过载与垂直滚动 (UI Overload & Scrolling)**：当前控制面板堆砌了大量低频/调试参数（如龙珠数 7、等待 UI 超时 120s、发想/超时设置、建房左右侧等），垂直高度超 880px，导致在低于 1080p 分辨率或标准笔记本屏幕上需要频繁滚动。
2. **技能项使用拼音短码 (Unfriendly Skill Shortcodes)**：技能配置区仅提供 4 个包含 `asj`、`jq`、`assx` 等拼音短码的下拉框，玩家无法直观识别（玩家只熟悉游戏内中文名，如"集火"、"剑气"、"奥数箭"、"奥数激光"）。
3. **声望模式逻辑与顺序混乱 (Confusing Reputation Flow)**：声望设置分散且缺乏引导，缺少与游戏内 6 大阵营（黑锋骑士团、肯瑞托等）和 1-10 级强度的直观对应关系。
4. **Boss / 传家宝配置过于复杂 (Over-engineered Boss Selectors)**：主线 Boss 与传家宝 Boss 常年占据主界面下拉框，而 95% 以上的挂机刷图场景玩家只需"自动挑战当前解锁的最后一个 Boss"。
5. **缺少分层信息架构 (Lack of Information Hierarchy)**：核心常用功能（选关/开始）与高级运维微调混在一起，缺乏合理的「核心-常用-高级隐藏」三级分区。

### 1.2 重构原则与交付目标
- **一屏无滚动 (Single-Screen Ergonomics)**：主界面高度严格控制在 680px – 720px，核心刷图操作一目了然，不需要滚动。
- **中文直观可视化 (Chinese-First Skill Card System)**：技能/羁绊卡片采用全中文显示 + 拼音短码自动映射；面板内部存取短码对 `Settings` 和 Mediator 完全兼容。
- **符合官方游戏直觉的流程 (Intuitive Game Workflow)**：声望模式按「先选阵营 -> 再选难度 -> 开启挑战」3 步进行；Boss/传家宝选择默认缺省为「最后一个 Boss」。
- **三层信息架构 (3-Tier Information Architecture)**：
  - **顶部核心区**：房间/密码/关卡范围/模式/一键主开始按钮
  - **折叠/常用配置区**：中文技能卡片网格、英雄模式/声望挑战、Boss/传家宝指定
  - **隐藏抽屉/高级设置**：龙珠数、等待超时、匹配阈值、游戏内优化微调开关

---

## 2. 三层 UI 信息架构 (IA) 与区域划分

### 2.1 整体界面结构
```
+-----------------------------------------------------------------------------------+
| 顶部核心区 (Top Core Zone) - 占高 ~35% (常驻可见，核心主控)                        |
| - 状态徽章 | 免证书标识 | 已刷局数 | Dry-run 模式测试高亮开关                     |
| - 目标关卡范围 (Stage1 — Stage2) | 固定模式标识: 独狼刷图 (GameMode=0)            |
| - 极简房间配置 (房间名 / 密码，留空即自动/随机)                                   |
| - 核心一键主按钮 [   开   始   游   戏   ] (带管理员 UIPI 提权拦截提醒)            |
+-----------------------------------------------------------------------------------+
| 中部折叠/常用配置区 (Config Accordion Zone) - 占高 ~50% (按需展开)                 |
| ├─ [折叠 Card 1] 🎯 技能选择 (中文卡片网格 + 流派快捷预设) - 默认展开              |
| ├─ [折叠 Card 2] 🏆 英雄模式与声望挑战 (6大阵营卡片 -> 1-10级难度 -> 开启开关)       |
| └─ [折叠 Card 3] 👹 Boss 与传家宝设置 (默认挑战最后一个，勾选"指定"才展开下拉)    |
+-----------------------------------------------------------------------------------+
| 底部日志与高级抽屉 (Log & Advanced Zone) - 占高 ~15% (收尾与运维)                 |
| - 辅助按钮: [ 从官方同步配置 ]  [ 保存本地配置 ]  [ ⚙️ 高级/局内优化设置... ]       |
| - 精简日志控制台 (固定 3-4 行展示最新日志，支持双击/滚动查看)                       |
+-----------------------------------------------------------------------------------+
```

---

## 3. 各功能区块详细设计方案

### 3.1 顶部核心区 (Top Core Zone)
**定位**：90% 的日常挂机操作无需展开下方配置，仅在此区域调整关卡并点击开始即可。

1. **状态与标题栏 (Header Bar)**：
   - 软件标题: `英雄三国挂机助手 (GameScript-Local) · 本地独狼版`
   - 运行状态徽章: `[● 空闲]` (灰色 `#94a3b8`) / `[● 运行中 (MAIN_LINE)]` (绿字高亮 `#34d399`)
   - 局数统计: `已完成: 0 局` (`#60a5fa`)
   - 免证书标识: `<span style="color:#34d399">1.3.3.3 免证书</span>`
   - Dry-run 开关: `[✓] Dry-run (测试不点击)` (黄字醒目提醒)
2. **关卡与模式行 (Stage & Mode Bar)**：
   - 目标关卡范围: `目标关卡: [ 1 ] — [ 10 ] 关` (QSpinBox, 范围 1-50)
   - 模式标识: `[ 独狼模式 (GameMode=0) ]` (固定只读 Badge)
3. **房间配置行 (Room Info Bar)**：
   - 房间名: `QLineEdit` (占位符: `留空按默认大厅`)
   - 密码: `QLineEdit` (Password 模式，占位符: `留空无密码`)
4. **一键主按钮 (Hero Action Button)**：
   - 占据独行超高视觉焦点按钮: `[   开   始   游   戏   ]` (渐变蓝色 `#2563eb` -> `#4f46e5`, 14px 加粗)
   - 运行态时自动变为: `[   停   止   游   戏   ]` (渐变红色 `#dc2626` -> `#be123c`)
   - **UIPI 权限硬门禁**：若 `dry_run == False` 且控制面板未以管理员身份运行，点击时弹窗阻断并提醒通过 `启动面板.bat` 提权运行。

---

### 3.2 技能中文标签卡片方案 (Skill Chinese Label Card System)

#### (1) 映射机制 (`skill_labels.json`)
读取 `config/skill_labels.json` 的中文映射关系：
```json
{
  "asj": "奥数箭",
  "asjg": "奥数激光",
  "assx": "奥数射线",
  "bsxx": "冰霜新星",
  "byj": "爆炎箭",
  "dcw": "电磁网",
  "dz": "地震",
  "hbj": "寒冰箭",
  "hq": "火球",
  "jf": "飓风",
  "jq": "剑气",
  "ljf": "龙卷风",
  "pg": "普攻",
  "sdl": "闪电链",
  "tl": "天雷",
  "ys": "陨石"
}
```
- **UI 面板**：显示中文名字 `奥数箭`，并在下方以小号浅灰色标记短码 `asj`。
- **后端存取**：多选选中的卡片列表在保存/运行输入时自动转换为 `["asj", "asjg", "assx", "jq"]`，直接对接 `Settings.skills`。

#### (2) 卡片组件布局与流派预设 (SkillCardGrid)
- **快捷流派一键预设按钮组**：
  - `[ 🎯 奥术箭流 ]` -> 一键自动勾选: `奥数箭 (asj)`, `奥数激光 (asjg)`, `奥数射线 (assx)`, `剑气 (jq)`
  - `[ ❄️ 冰法控场 ]` -> 一键自动勾选: `寒冰箭 (hbj)`, `冰霜新星 (bsxx)`, `剑气 (jq)`, `普攻 (pg)`
  - `[ ⚡ 天雷狂轰 ]` -> 一键自动勾选: `天雷 (tl)`, `闪电链 (sdl)`, `电磁网 (dcw)`, `剑气 (jq)`
  - `[ 🧹 清空选择 ]` -> 取消所有选择
- **多选卡片网格 (4 x 4 Card Grid)**：
  - 未选中态：深色卡片背景 `#0a101c`、灰色边框 `#243044`、文字 `#cbd5e1`。
  - 选中态：蓝框高亮 `#2563eb`、勾选徽章 `[✓]`、亮白中文文字 `#ffffff`。
- **已选数量与规则约束**：
  - 上限约束: 建议最多选择 4 个（超过 4 个时阻止勾选并黄色 Toast 提示）。
  - 底栏选中摘要: `当前已选 4/4 项: 奥数箭、奥数激光、奥数射线、剑气`。

---

### 3.3 声望与英雄模式：先阵营，后难度，开启挑战 (Reputation Flow)

根据游戏内英雄声望模式的选盘逻辑，重构为 **3 步引导式交互**：

#### (1) 交互三步法
1. **第一步：选择声望阵营 (Reputation Faction)**
   - 6 大阵营单选卡片网格 (2 行 3 列)，直观呈现中文阵营名称与代码编号：
     - `[ ⚔️ 黑锋骑士团 ]` (`reputation_type: 1`)
     - `[ 🛡️ 银色北伐军 ]` (`reputation_type: 2`)
     - `[ 🔮 肯瑞托     ]` (`reputation_type: 3`)
     - `[ 🧭 探险者协会 ]` (`reputation_type: 4`)
     - `[ 🌋 元素领主   ]` (`reputation_type: 5`)
     - `[ 🐲 守护巨龙   ]` (`reputation_type: 6`)
   - 鼠标点击即切换选中状态，选中的阵营呈现蓝色外发光边框。
2. **第二步：选择挑战难度 (Difficulty Level 1-10)**
   - 10 级快捷按键条 / 水平滑块 Slider (`1 级 — 10 级`)。
   - 对应后端的 `reputation_level` (默认 1)。
3. **第三步：开启挑战开关 (Enable Challenge Switch)**
   - 总开关 Checkbox: `[✓] 开启英雄声望模式` (`auto_reputation = True`)。
   - 动态更新提示文案: `当前已启用: 英雄模式 —【肯瑞托】难度 5 级`。

---

### 3.4 Boss 与传家宝选择：默认最后一个，指定才展开

#### (1) 交互逻辑与设计
- **单选项模式 (Radio / Checkbox Group)**：
  - `(●) 默认挑战最新 Boss (自动匹配关卡/地图最后一个 Boss)` [系统默认选项]
  - `( ) 指定特定 Boss`
- **动态展开 (Collapsible Dropdowns)**：
  - 选择 `默认挑战最新 Boss` 时：隐藏特定下拉框。
    - 后端自动赋值: `sgzx_boss = BOSS_MAIN[-1]` (如 `08巨形缝合怪`), `cjb_boss = BOSS_CJB[-1]` (如 `01暴掠龙`)。
  - 勾选 `指定特定 Boss` 时：平滑展开下拉选择框：
    - 主线 Boss: `[ 08巨形缝合怪  ▼ ]` (扫描 `assets/Images/boss/*.png`)
    - 传家宝 Boss: `[ 01暴掠龙        ▼ ]` (扫描 `assets/Images/chuanjiaobao/*.png`)

---

### 3.5 明确删除与隐藏项清单 (Deletion & Hidden Items List)

| 控件 / 参数字段 | 当前面板位置 | 处理方案 | 详细理由与设计目的 |
|---|---|---|---|
| `dragon_ball_count` (龙珠数) | 主面板常规区 | **隐藏** (移至高级抽屉) | 默认值为 7（对应"我打不过呀"成就与通关逻辑），99% 用户无需干预，放主界面增加认知负担。 |
| `query_timeout` (等待UI超时) | 主面板常规区 | **隐藏** (移至高级抽屉) | 默认 120 秒是系统级防御超时，属于内部稳定性参数，非日常配置。 |
| `develop_time` (发育时间) | 主面板常规区 | **隐藏** (移至高级抽屉) | 独狼快刷默认 0 秒，非赌木/特殊策略无需修改。 |
| `auto_close_main_line` / `close_main_line_time` | 主面板 | **隐藏** (移至高级抽屉) | 自动关闭主线为高级防御设置，日常挂机保持默认即可。 |
| 游戏内优化设置 (屏蔽特效/禁用击退等) | 散落各处 | **整合隐藏** (高级抽屉) | 属于一键开关后的细粒度优化，日常界面不显示。 |
| `room_create_side` (建房左右位) | 主面板 L0 区 | **隐藏** (移至高级抽屉) | 官方默认左侧，极少变动。 |
| `new_room_every_times` (每局重建) | 主面板 L0 区 | **隐藏** (移至高级抽屉) | 独狼连刷无需每局退房重建，属于高级排错选项。 |
| `match_threshold` (找图阈值) | 主面板环境区 | **隐藏** (移至高级抽屉) | 默认 0.85 已经经过大量真机验证，暴露给普通用户容易引发误操作导致找图失败。 |
| `window_title_contains` (窗口标题) | 主面板环境区 | **精简隐藏** (高级抽屉) | 默认「英雄三国」已覆盖 99% 情况，高级抽屉提供修改即可。 |
| 4个短码技能下拉框 | 主面板技能区 | **彻底删除重构** | 拼音短码无法直观识别，下拉框形式限制了多选体验且排版拥挤。重构为中文卡片网格。 |
| 声望区重复 Boss 下拉框 | 声望区 | **隐藏/移除** | 与主 Boss 选项重复，直接共享 Boss 策略，避免多处设置引发冲突。 |

---

### 3.6 隐藏区 / 高级与局内优化设置抽屉 (Advanced Settings Drawer)

面板底部点击 `[ ⚙️ 高级与局内优化设置... ]` 按钮，弹出 Modal 对话框，集中存放以下低频/调试参数：

1. **局内辅助开关 (In-Game Toggles)**：
   - `[✓] 自动卡组 (auto_card)`
   - `[✓] 自动武器 (auto_weapon)`
   - `[✓] 奥数增伤优先 (damage_increase_card)`
   - `[✓] 发育优先 (develop_priority)`
   - `[  ] 局末自动秘境 (auto_secret_realm)`
2. **高级防御与超时 (Timeouts & Safeguards)**：
   - 龙珠收集数量: `[ 7 ] 颗` (`dragon_ball_count`)
   - 等待 UI 超时: `[ 120 ] 秒` (`query_timeout`)
   - 局内单局超时: `[ 15 ] 秒` (`game_timeout`)
   - 自动清理间隔: `[ 5 ] 局` (`auto_clean_interval`)
   - 模板匹配阈值: `[ 0.85 ]` (`match_threshold`)
3. **环境锁窗高级关键字**：
   - 窗口标题包含: `[ 英雄三国,Single Player,魔兽世界,KK ]`

---

## 4. 新控件布局草图 (ASCII Sketch)

```
+-----------------------------------------------------------------------------------+
| 英雄三国挂机助手 (GameScript-Local) 1.3.3.3 本地版           [● 空闲] [已刷: 0局]  |
+-----------------------------------------------------------------------------------+
| 运行模式: [ 独狼刷图 (GameMode=0) ]         认证状态: <1.3.3.3 本地免证书>        |
| 目标关卡: [ 1 ] — [ 10 ] 关                  [✓] Dry-run (测试只找图不点击)        |
| 房间配置: 房间名 [            ]  密码 [            ] (留空默认随机大厅)           |
| +-------------------------------------------------------------------------------+ |
| |                         [   开   始   游   戏   ]                            | |
| +-------------------------------------------------------------------------------+ |
+-----------------------------------------------------------------------------------+
| [▼] 🎯 技能配置 (中文多选, 已选 4/4)                                              |
| 流派预设: [ 🎯 奥术箭流 ]  [ ❄️ 冰法控场 ]  [ ⚡ 天雷狂轰 ]  [ 🧹 清空 ]            |
| +-------------------+ +-------------------+ +-------------------+ +-------------------+ |
| | [✓] 奥数箭 (asj)  | | [✓] 奥数激光(asjg)| | [✓] 奥数射线(assx)| | [✓] 剑  气 (jq)   | |
| +-------------------+ +-------------------+ +-------------------+ +-------------------+ |
| | [ ] 冰霜新星(bsxx)| | [ ] 爆炎箭 (byj)  | | [ ] 电磁网 (dcw)  | | [ ] 地  震 (dz)   | |
| +-------------------+ +-------------------+ +-------------------+ +-------------------+ |
| | [ ] 寒冰箭 (hbj)  | | [ ] 火  球 (hq)   | | [ ] 飓  风 (jf)   | | [ ] 龙卷风 (ljf)  | |
| +-------------------+ +-------------------+ +-------------------+ +-------------------+ |
| | [ ] 普  攻 (pg)   | | [ ] 闪电链 (sdl)  | | [ ] 天  雷 (tl)   | | [ ] 陨  石 (ys)   | |
| +-------------------+ +-------------------+ +-------------------+ +-------------------+ |
| 当前选定技能: 奥数箭、奥数激光、奥数射线、剑气                                    |
+-----------------------------------------------------------------------------------+
| [▶] 🏆 英雄模式 & 声望挑战                                                       |
| [✓] 开启英雄声望模式                                                              |
| 选阵营: [⚔️黑锋骑士团] [🛡️银色北伐军] [🔮肯瑞托] [🧭探险者协会] [🌋元素领主] [🐲守护巨龙] |
| 选难度: 1级 [======|-------------------] 10级  (当前选定: 难度 5 级)             |
+-----------------------------------------------------------------------------------+
| [▶] 👹 Boss & 传家宝设置                                                          |
| (●) 默认挑战最新 Boss (自动匹配关卡/地图最后一个 Boss)                           |
| ( ) 指定特定 Boss -> [ 展开下拉 ]                                                  |
+-----------------------------------------------------------------------------------+
| [ 从官方同步配置 ]   [ 保存本地配置 ]   [ ⚙️ 高级与局内优化设置... ]                |
| 日志控制台 (显示最新 3-4 行):                                                     |
| [15:30:00] [信息] 配置载入成功: default_settings.json                             |
| [15:30:01] [就绪] 点击【开始游戏】后脚本将自动识别窗口并运行                        |
+-----------------------------------------------------------------------------------+
```

---

## 5. PySide6 代码重构实现方案

### 5.1 核心组件封装结构

#### 1. `SkillCardGrid` (中文技能卡片网格 Widget)
```python
class SkillCardGrid(QWidget):
    skills_changed = Signal(list)  # 发送选中的短码列表

    def __init__(self, skill_stems: list[str], skill_labels: dict[str, str]):
        super().__init__()
        self.skill_stems = skill_stems
        self.skill_labels = skill_labels
        self.cards: dict[str, QPushButton] = {}
        self._selected: set[str] = set()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 快捷预设行
        preset_lay = QHBoxLayout()
        preset_lay.addWidget(QLabel("流派预设:"))
        
        btn_asj = QPushButton("🎯 奥术箭流")
        btn_asj.clicked.connect(lambda: self.set_selected_skills(["asj", "asjg", "assx", "jq"]))
        preset_lay.addWidget(btn_asj)

        btn_ice = QPushButton("❄️ 冰法控场")
        btn_ice.clicked.connect(lambda: self.set_selected_skills(["hbj", "bsxx", "jq", "pg"]))
        preset_lay.addWidget(btn_ice)

        btn_thunder = QPushButton("⚡ 天雷狂轰")
        btn_thunder.clicked.connect(lambda: self.set_selected_skills(["tl", "sdl", "dcw", "jq"]))
        preset_lay.addWidget(btn_thunder)

        btn_clear = QPushButton("🧹 清空")
        btn_clear.clicked.connect(lambda: self.set_selected_skills([]))
        preset_lay.addWidget(btn_clear)
        preset_lay.addStretch()
        layout.addLayout(preset_lay)

        # 4x4 卡片网格
        grid = QGridLayout()
        for idx, code in enumerate(self.skill_stems):
            cn_name = self.skill_labels.get(code, code)
            btn = QPushButton(f"{cn_name}\n({code})")
            btn.setCheckable(True)
            btn.setMinimumHeight(44)
            btn.clicked.connect(lambda checked, c=code: self._on_card_toggled(c, checked))
            self.cards[code] = btn
            grid.addWidget(btn, idx // 4, idx % 4)
        
        layout.addLayout(grid)

        # 已选文本摘要
        self.lbl_summary = QLabel("当前已选技能: 无")
        self.lbl_summary.setStyleSheet("color: #60a5fa; font-size: 11px;")
        layout.addWidget(self.lbl_summary)

    def _on_card_toggled(self, code: str, checked: bool):
        if checked:
            if len(self._selected) >= 4:
                self.cards[code].setChecked(False)
                QMessageBox.warning(self, "技能限制", "主刷图技能最多只能选择 4 个！")
                return
            self._selected.add(code)
        else:
            self._selected.discard(code)
        self._update_summary()
        self.skills_changed.emit(self.get_selected_skills())

    def set_selected_skills(self, skills: list[str]):
        self._selected = set(skills[:4])
        for code, btn in self.cards.items():
            btn.setChecked(code in self._selected)
        self._update_summary()
        self.skills_changed.emit(self.get_selected_skills())

    def get_selected_skills(self) -> list[str]:
        return [c for c in self.skill_stems if c in self._selected]

    def _update_summary(self):
        names = [self.skill_labels.get(c, c) for c in self.get_selected_skills()]
        txt = "、".join(names) if names else "无"
        self.lbl_summary.setText(f"当前已选技能 ({len(names)}/4): {txt}")
```

#### 2. `ReputationSelector` (声望阵营与难度 Widget)
```python
class ReputationSelector(QWidget):
    FACTIONS = [
        (1, "黑锋骑士团", "⚔️"),
        (2, "银色北伐军", "🛡️"),
        (3, "肯瑞托", "🔮"),
        (4, "探险者协会", "🧭"),
        (5, "元素领主", "🌋"),
        (6, "守护巨龙", "🐲"),
    ]

    def __init__(self):
        super().__init__()
        self.selected_type = 1
        self.selected_level = 1
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        # 1. 开启总开关
        self.chk_enable = QCheckBox("开启英雄声望模式")
        self.chk_enable.setStyleSheet("font-weight: bold; color: #60a5fa;")
        layout.addWidget(self.chk_enable)

        # 2. 阵营单选网格 (2x3)
        grid_factions = QGridLayout()
        self.faction_btns = {}
        for idx, (ftype, fname, icon) in enumerate(self.FACTIONS):
            btn = QPushButton(f"{icon} {fname}")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, t=ftype: self._select_faction(t))
            self.faction_btns[ftype] = btn
            grid_factions.addWidget(btn, idx // 3, idx % 3)
        layout.addLayout(grid_factions)

        # 3. 难度选择器 (Slider + SpinBox)
        lay_lvl = QHBoxLayout()
        lay_lvl.addWidget(QLabel("挑战难度 (1-10级):"))
        self.slider_lvl = QSlider(Qt.Horizontal)
        self.slider_lvl.setRange(1, 10)
        self.spn_lvl = QSpinBox()
        self.spn_lvl.setRange(1, 10)

        self.slider_lvl.valueChanged.connect(self.spn_lvl.setValue)
        self.spn_lvl.valueChanged.connect(self.slider_lvl.setValue)
        self.spn_lvl.valueChanged.connect(self._on_level_changed)

        lay_lvl.addWidget(self.slider_lvl)
        lay_lvl.addWidget(self.spn_lvl)
        layout.addLayout(lay_lvl)

        self._select_faction(1)

    def _select_faction(self, ftype: int):
        self.selected_type = ftype
        for t, btn in self.faction_btns.items():
            btn.setChecked(t == ftype)

    def _on_level_changed(self, val: int):
        self.selected_level = val

    def get_config((tuple[int, int, bool]):
        return (self.selected_type, self.selected_level, self.chk_enable.isChecked())

    def set_config(self, ftype: int, level: int, enabled: bool):
        self.chk_enable.setChecked(enabled)
        self.spn_lvl.setValue(max(1, min(10, level)))
        self._select_faction(max(1, min(6, ftype)))
```

#### 3. `BossSelector` (Boss 智能缺省 Widget)
```python
class BossSelector(QWidget):
    def __init__(self, main_bosses: list[str], cjb_bosses: list[str]):
        super().__init__()
        self.main_bosses = main_bosses
        self.cjb_bosses = cjb_bosses
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        self.rad_default = QRadioButton("默认挑战最新 Boss (自动选择地图/传家宝最后一个 Boss)")
        self.rad_specify = QRadioButton("指定特定 Boss")
        self.rad_default.setChecked(True)

        layout.addWidget(self.rad_default)
        layout.addWidget(self.rad_specify)

        # 折叠下拉框容器
        self.w_dropdowns = QWidget()
        lay_drop = QGridLayout(self.w_dropdowns)
        lay_drop.setContentsMargins(20, 0, 0, 0)

        lay_drop.addWidget(QLabel("地图/主线 Boss:"), 0, 0)
        self.cmb_sgzx = QComboBox()
        self.cmb_sgzx.addItems(self.main_bosses)
        lay_drop.addWidget(self.cmb_sgzx, 0, 1)

        lay_drop.addWidget(QLabel("传家宝 Boss:"), 0, 2)
        self.cmb_cjb = QComboBox()
        self.cmb_cjb.addItems(self.cjb_bosses)
        lay_drop.addWidget(self.cmb_cjb, 0, 3)

        layout.addWidget(self.w_dropdowns)
        self.w_dropdowns.setVisible(False)

        self.rad_specify.toggled.connect(self.w_dropdowns.setVisible)

    def get_bosses() -> tuple[str, str]:
        if self.rad_default.isChecked():
            sgzx = self.main_bosses[-1] if self.main_bosses else ""
            cjb = self.cjb_bosses[-1] if self.cjb_bosses else ""
            return (sgzx, cjb)
        return (self.cmb_sgzx.currentText().strip(), self.cmb_cjb.currentText().strip())

    def set_bosses(self, sgzx: str, cjb: str):
        is_last_sgzx = (not sgzx) or (self.main_bosses and sgzx == self.main_bosses[-1])
        is_last_cjb = (not cjb) or (self.cjb_bosses and cjb == self.cjb_bosses[-1])

        if is_last_sgzx and is_last_cjb:
            self.rad_default.setChecked(True)
        else:
            self.rad_specify.setChecked(True)
            if sgzx in self.main_bosses:
                self.cmb_sgzx.setCurrentText(sgzx)
            if cjb in self.cjb_bosses:
                self.cmb_cjb.setCurrentText(cjb)
```

---

### 5.2 Settings 数据读写与转换对接

重构 `MainWindow` 中 `apply_settings_to_ui` 与 `collect_settings_from_ui` 方法：

```python
def apply_settings_to_ui(self, s: Settings):
    self.settings = s
    
    # 1. 顶部核心区
    self.spn_s1.setValue(s.stage1)
    self.spn_s2.setValue(s.stage2)
    self.txt_room_name.setText(s.room_name or "")
    self.txt_room_password.setText(s.room_password or "")
    self.chk_dry.setChecked(s.dry_run)
    
    # 2. 技能选择区 (中文卡片网格)
    self.skill_grid.set_selected_skills(s.skills or [])
    
    # 3. 声望选择区 (阵营+难度)
    self.rep_selector.set_config(
        ftype=getattr(s, "reputation_type", 1),
        level=getattr(s, "reputation_level", 1),
        enabled=s.auto_reputation
    )
    
    # 4. Boss 选择区
    self.boss_selector.set_bosses(s.sgzx_boss, s.cjb_boss)

def collect_settings_from_ui(self) -> Settings:
    s = self.settings
    s.game_mode = 0  # 独狼刷图固定为 0
    s.stage1 = self.spn_s1.value()
    s.stage2 = self.spn_s2.value()
    s.room_name = self.txt_room_name.text().strip()
    s.room_password = self.txt_room_password.text()
    s.dry_run = self.chk_dry.isChecked()
    
    # 收集技能 (短码列表)
    s.skills = self.skill_grid.get_selected_skills()
    
    # 收集声望
    rep_type, rep_level, rep_enabled = self.rep_selector.get_config()
    s.reputation_type = rep_type
    s.reputation_level = rep_level
    s.auto_reputation = rep_enabled
    
    # 收集 Boss
    s.sgzx_boss, s.cjb_boss = self.boss_selector.get_bosses()
    
    return s
```

---

## 6. 重构实施 CheckList (步骤与验收指南)

- [x] 1. 读 `desktop_app.py` 现状与全配置字段映射。
- [x] 2. 对照 `config/default_settings.json` 确认所有底层 JSON 字段完整保留与对接。
- [x] 3. 对照 `docs/HANDOFF_FRONTEND_CONTROL_PANEL.md` 确认无证书逻辑与独狼约束。
- [ ] 4. 在 `desktop_app.py` 中编写 `SkillCardGrid` 控件，引入 `skill_labels.json` 中文映射。
- [ ] 5. 编写 `ReputationSelector` 控件，实现 6 大阵营按钮网格 + 难度 1-10 Slider。
- [ ] 6. 编写 `BossSelector` 控件，实现默认「最后一个 Boss」与勾选展开逻辑。
- [ ] 7. 创建 `AdvancedSettingsDialog` 弹窗，收纳 `dragon_ball_count`、`query_timeout`、`match_threshold` 等高级运维设置。
- [ ] 8. 优化 GUI CSS 样式，控制垂直 Padding/Margin，确保 700px 窗口下完全无滚动条。
- [ ] 9. 运行 `python desktop_app.py`，测试并验证本地配置保存/加载无损。
