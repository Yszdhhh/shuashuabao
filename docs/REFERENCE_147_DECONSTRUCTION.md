# 1.4.7 原版参考脚本解构与底层运行机理 (Reference Deconstruction)

## 一、原版架构概览
- **程序类型**：.NET Framework 4.8 + Win32 GDI / OpenCV C# 原生程序 (`GameScript.exe`)
- **配置文件**：`GameScript.exe.config`
- **核心依赖**：
  - `System.Drawing.Common` (GDI 屏幕抓取与坐标换算)
  - `Emgu.CV` / `OpenCV` (模板匹配)
  - `UIAutomationCore` (Win32 物理输入模拟)

---

## 二、原版 1.4.7 的核心实现方式（状态自愈推进）

### 1. 选关机制（Stage Selection）
- **配置结构**：`Stage1` (大关卡，如 3) 与 `Stage2` (小关卡，如 2)
- **底层逻辑**：
  ```csharp
  // 简化的 C# 状态机推进逻辑
  while (IsInStageSelectPage()) {
      var target = FindTemplate($"stage_{Stage1}_{Stage2}.png");
      if (target != null) {
          Click(target.Center);
          Click(FindTemplate("startChallenge.png"));
          break;
      }
      // 没有找到目标，就执行一次滚轮并短暂 sleep 200ms
      ScrollDown(-120); // 负值向下滚
      Sleep(200);
      // 只有在全局超时 (QueryTimeOut = 60s) 时才跳出报错，绝无中途 8 次自杀
  }
  ```

### 2. 选卡与羁绊（Cards & Bonds）
- **选卡逻辑**：
  ```csharp
  // 弹出选择面板
  if (IsPanelOpen("skill_hide.png") || IsPanelOpen("card_hide.png")) {
      foreach (var skill in ConfiguredSkills) {
          var hit = FindTemplate(skill.Template);
          if (hit != null) {
              Click(hit.Center);
              return;
          }
      }
      // 无命中：直接点击右上角或右下角的关闭/隐藏按钮 (skill_hide / card_hide)
      // 绝不在没有刷新按钮时循环点击刷新
      Click(FindTemplate("skill_hide.png") ?? FindTemplate("card_hide.png"));
  }
  ```

### 3. 建房与进房（Lobby & Room）
- **状态流转**：
  ```text
  识别 createRoomBtn.png -> 点击
  等待 sureBtn.png (建房确定) -> 点击
  进入房间 roomStart.png (开始游戏) -> 点击
  等待游戏窗口拉起 -> 切换上下文
  ```
  - 中间如果因为平台延迟没弹出，只要还在大厅界面，它就会自然进入下一轮循环重新检测并补点，绝不把标志位永久锁死。

---

## 三、给云端 AI 的去僵化重构指导建议
1. **废除 `attempts < N` 微观计数器**：
   - 将 `mediator.py` 的 L0 选关与创房改回像 1.4.7 一样：只要 `_detect_context == STAGE_SELECT`，就持续滚动寻找直到找到或触发全局 60s 超时；
2. **选卡关闭对齐 1.4.7**：
   - 技能/宝物/羁绊未命中时，统一调用 `skill_hide` 或 `card_hide` 物理模板关闭，绝不尝试执行不存在的刷新。
