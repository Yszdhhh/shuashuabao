# 竞品1 (GameScript 1.6.3) 静态观察与增量情报

> **样本路径**：`C:\Users\10639\Desktop\竞品\脚本1更新\1.6.3\`  
> **对比基准**：`1.6.2` 版本目录（2026-09-22 归档）  
> **分析日期**：2026-09-23  
> **核心发现**：海贼王≠海盗体系辨析、不归秘境独立落点、三极卡面入库、工程 PDB 符号及 FlaUI XML 泄露。

---

## 一、 文件系统增量 Diff (1.6.2 vs 1.6.3)

对比两个版本的文件与目录结构：
1. **新增二进制伴随文件**：
   * `GameScript.pdb` (74,240 字节, 2026-09-22 17:09) —— 关键未剥离符号表！
   * `Lan.UIAutomation.xml` (53,889 字节) —— FlaUI UIAutomation 封装层 API 接口文档
   * `Lan.UIAutomationCore.xml` (203,788 字节) —— 底层 UIA Core 转换器与互操作文档
2. **`Images/` 图像资源目录净增 9 个模板文件**：

| 文件名 | 体积 (Bytes) | 视觉内容 | 机制定位与权威解读 |
| :--- | :--- | :--- | :--- |
| **`haizeiwang.png`** | 2,506 | “海贼王”卡面图标 | 核心跨品质宝物/专精卡，**绝非普通海盗羁绊** |
| **`haizeiwangEx.png`** | 6,133 | “海贼王Ex”进阶图标 | 海贼王升星或觉醒后的进阶卡面，带金色粒子/Ex 标识 |
| **`buguimijing.png`** | 4,154 | “不归秘境”文字与按钮 | 战后高阶挑战“不归秘境”独立落点，有别于普通大秘境 |
| **`damingjiText.png`** | 2,812 | “大秘境”弹窗标题文本 | 验证大秘境 NPC 对话框已处于打开状态的 PAGE_IDENTITY 锚点 |
| **`lizhiji.png`** | 3,100 | “力之极”卡面 | 力量体系后期顶级质变卡（力量大幅增幅） |
| **`minzhiji.png`** | 3,510 | “敏之极”卡面 | 敏捷体系后期顶级质变卡（敏捷大幅增幅） |
| **`zhizhiji.png`** | 2,986 | “智之极”卡面 | 智力体系后期顶级质变卡（智力大幅增幅） |
| **`chooseHeroBtn.png`** | 3,880 | “选择英雄”金色按钮 | 局内开局阶段点击进入英雄池挑选界面的 ACTION_LOCATOR |
| **`yingxiongkalibao.png`**| 5,665 | “英雄卡礼包”包裹图标 | 物品栏中存放的英雄抽卡礼包，开局或任务奖励道具 |

---

## 二、 核心机制深拆 1：海贼王 ≠ 海盗体系辨析

### 2.1 混淆根源与实机真相
在历史脚本和老攻略中，许多开发者常将“海贼王”与“海盗”混为一谈：
* **普通海盗 (Pirate Bond)**：属于羁绊 F 中的门卡进阶组（4 张常规海盗卡），消耗木材抽取，提供基础暴击与金币收益；
* **海贼王 (ONEPIECE)**：是游戏近期版本推出的**跨品质超级专属核心卡**，拥有独立的触发条件与质变收益。
  * `haizeiwang.png` 为初始形态；
  * `haizeiwangEx.png` 为进阶觉醒形态。

### 2.2 架构裁决
* **应用 (ADAPT)**：在 `choice_lexicon.json` 中区分 `haizeiwang` 与普通海盗卡，将 `haizeiwang` 作为宝物/高级卡池中的 `must_take` 候选入库；
* **参考 (REFERENCE)**：观察竞品在出海贼王时是否重置木材预算；
* **REJECT**：严禁在策略层将“海盗门卡”的进度计数累加给“海贼王”，二者生命周期完全解耦。

---

## 三、 核心机制深拆 2：不归秘境 (Secret Realm of No Return)

### 3.1 战后分支演进
战后挑战原先仅有：
$$\text{POST\_VICTORY} \longrightarrow \text{存档 8 卡} \longrightarrow \text{时光之穴} \longrightarrow \text{传家宝} \longrightarrow \text{常规大秘境 / 退出}$$

1.6.3 新增的 `buguimijing.png` 证实游戏引入了第二种秘境终点：
* **常规大秘境 (`damingjiText.png`)**：标准层级递增秘境；
* **不归秘境 (`buguimijing.png`)**：高难度特殊挑战，进入条件和门票扣除逻辑不同，战败或通关结算提示不同。

### 3.2 架构裁决
* **应用 (ADAPT)**：在战后判页状态机中增加 `SUB_REALM_NO_RETURN` 分支，提取 `buguimijing.png` 作为锚点，防止识别为未知弹窗触发 Fail-Closed 误退；
* **REJECT**：竞品在秘境超时后直接盲点屏幕右侧返回，刷刷宝坚守严格凭退出按钮与结算状态确认后才离场。

---

## 四、 核心机制深拆 3：三极卡面与英雄开局

1. **三极卡面 (力之极/敏之极/智之极)**：
   * 属于单属性纯数值放大卡，适合在对应主属性链（法神/战神/弓神）成型后作为终极倍率卡；
   * 纳入 `choice_policy` 的属性强化高权保底序列。
2. **`chooseHeroBtn.png` 与 `yingxiongkalibao.png`**：
   * 揭示了开局自动选英雄的完整链路：检测开局礼包 $\to$ 右键开包 $\to$ 弹出面板 $\to$ 点击“选择英雄” $\to$ 挑取指定英雄。

---

## 五、 工程泄露挖掘：PDB 符号与 FlaUI 架构价值

1. **`GameScript.pdb` (Program Database)**：
   * 包含未混淆的完整调试符号，包含 `GameScript.Jobs.AutoJob`、`LongzhuJob`、`PowerHelper` 等全部方法名与局部变量名；
   * 确认了其核心调度采用多线程 + UI 线程调度模式，利用 `Dispatcher.Invoke` 与 WPF 前端绑定。
2. **`Lan.UIAutomation.xml` (FlaUI)**：
   * 竞品并不是使用单纯的 Win32 API 找窗，而是借由开源框架 **FlaUI**（包装 Windows UIA 2/3）遍历 KK 平台的大厅控件树；
   * 竞品在找房、输入密码、点击开始游戏等环节，利用 AutomationId 与 Name 双重选择器。这与我方原生 UIA 设计思路完全一致，进一步印证了“弃用找图兜底大厅，全走 UIA”技术路线的正确性。
