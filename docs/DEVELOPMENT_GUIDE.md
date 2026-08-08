# GameScript-Local 开发与调试指南

> **生成日期**：2026-08-08  
> **生成模型**：gemini-3.6-flash  
> **项目版本**：GameScript-Local 2.0 (重构版)  
> **适用范围**：开发人员、测试人员及贡献者

---

## 1. 开发环境搭建

本项目推荐使用 Windows 10/11 64 位环境，并使用 Python 3.11 搭配 `uv`（极速 Python 包管理器）进行依赖管理。

### 1.1 前置要求
- **操作系统**：Windows 10 / 11 64-bit
- **Python**：Python 3.11 (64-bit)
- **包管理器**：`uv` (推荐) 或 `pip`

### 1.2 快速搭建步骤

1. **克隆仓库并进入根目录**：
   ```powershell
   cd "C:\Users\10639\Desktop\🎮 影音游戏\GameScript-Local"
   ```

2. **创建虚拟环境**：
   使用 `uv` 创建 Python 3.11 隔离虚拟环境：
   ```powershell
   uv venv --python 3.11 .venv
   ```

3. **激活虚拟环境**：
   ```powershell
   # PowerShell
   .\.venv\Scripts\Activate.ps1
   ```

4. **安装依赖**：
   分别安装运行依赖与打包构建依赖：
   ```powershell
   # 使用 uv 安装
   uv pip install -r requirements-desktop.txt -r requirements-build.txt
   ```

5. **配置 Python Path**：
   源码存放在 `src/` 目录下，在终端中直接运行 python 命令前需指定环境变量 `PYTHONPATH=src`：
   ```powershell
   # PowerShell 临时设置
   $env:PYTHONPATH="src"
   ```

---

## 2. 项目打包与构建 (Build Release)

项目使用 PyInstaller 打包成单文件/单文件夹的 EXE 可执行程序。打包关键在于**强制设置 UAC 管理员提权**（`uac_admin=True`），以满足 Windows UIPI 防作弊隔离机制。

### 2.1 一键打包脚本
项目根目录提供了 PowerShell 构建脚本 `build_release.ps1`：

```powershell
.\build_release.ps1
```

**脚本内部执行流程**：
1. 自动检测系统中的 `uv` 命令。
2. 自动检查 `.venv` 虚拟环境，若不存在则调用 `uv venv` 自动创建。
3. 调用 `uv pip install` 自动同步 `requirements-desktop.txt` 与 `requirements-build.txt`。
4. 调用 PyInstaller 清理并重新编译 `GameScript.spec`。
5. 验证是否成功生成 `dist\GameScript\GameScript.exe`。

### 2.2 打包配置 (`GameScript.spec`) 注意事项
- **UAC 提权配置**：`exe = EXE(..., uac_admin=True)`。**切勿修改为 False**，否则打包出来的 EXE 将无法通过 Windows SendInput 向游戏或 KK 平台发送点击事件（UIPI 会静默丢弃）。
- **控制台窗口**：`console=False`（隐藏黑框控制台，完全通过 PySide6 面板展示日志）。
- **资源嵌入**：`assets/Images`、`config/scenes.json` 及 `default_settings.json` 已自动打包入可执行文件资源路径。

---

## 3. 测试运行指南 (Test Suite)

项目包含 76+ 个单元测试与实机回放夹具测试，涵盖 P0 安全拦截链、P1 主线控制、战后多锚点判别、英雄模式时序与实机截图全回放。

### 3.1 运行完整测试套件
在项目根目录运行 `unittest`（务必携带 `PYTHONPATH=src`）：

```powershell
# PowerShell 环境
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

### 3.2 运行特定模块测试

- **运行 P0 安全拦截链测试**（验证急停/遮挡/提权/前台门禁）：
  ```powershell
  python -m unittest tests/test_p0_security.py
  ```

- **运行 P0-B 实机截图全回放测试**（针对 32 个实机场景夹具进行识别校验）：
  ```powershell
  python -m unittest tests/test_p0b_replay.py
  ```

- **运行 P1 战后多锚点判别测试**：
  ```powershell
  python -m unittest tests/test_p1b0_post_game.py
  ```

- **运行英雄模式 (肯瑞托 1-5 级) 时序测试**：
  ```powershell
  python -m unittest tests/test_hero_mode_temporal.py
  ```

- **运行关卡选择器测试**：
  ```powershell
  python -m unittest tests/test_stage_selector.py
  ```

- **使用 pytest 运行**：
  ```powershell
  pytest tests/
  ```

---

## 4. 新增场景与功能开发步骤 (Step-by-step Guide)

当游戏更新或需要支持新玩法（如新阵营挑战、新三选一面板、新 Boss 入口）时，请按照以下 6 步标准流程开发：

### Step 1: 图像模板采集与规范
1. 在游戏 1600×900 窗口模式下截取清晰目标 UI 图像。
2. 裁剪边缘，保留核心特征像素（避免包含背景动态特效）。
3. 保存为 24 位 PNG 格式到 `assets/Images/` 对应子目录（如 `assets/Images/lobby/` 或 `assets/Images/skills/`）。

### Step 2: 配置 `config/scenes.json`
在 `config/scenes.json` 的 `scenes` 字典中添加或更新场景定义：
```json
"new_feature_panel": {
  "templates": ["lobby/new_feature_btn"],
  "threshold": 0.80,
  "roi": [0.30, 0.40, 0.70, 0.80],
  "comment": "新增玩法功能按钮描述"
}
```

### Step 3: 扩展视觉检测接口 (`matcher.py` / `capture.py`)
若新场景包含特殊颜色、数字或几何排列，在 `src/gamescript/vision/matcher.py` 中添加识别 helper。例如品质色分阶、蓝色按钮轮廓等。

### Step 4: 扩展 Mediator 状态机 Hook (`mediator.py`)
1. 若涉及新阶段，在 `Phase` 枚举中添加新项：
   ```python
   class Phase(Enum):
       ...
       NEW_FEATURE = auto()
   ```
2. 在 `Mediator._detect_context()` 中添加场景分类规则。
3. 在 `Mediator.tick()` 的状态分流中挂载新的 `_tick_new_feature(frame)` 处理函数。
4. 在 `set_phase()` 中添加跨局/跨阶段状态清理逻辑。

### Step 5: 接入 `InputExecutor` 与 Fail-Closed 机制
所有点击/按键操作必须调用 `self.act_click()` 或 `self.executor` 提供的接口，**绝对不可绕过 InputExecutor 直接调用底层 SendInput**。必须显式处理超时与重试上限：
```python
if self._new_feature_attempts >= 3:
    print("[NewFeature] 重试次数已达上限，Fail-Closed 停止")
    self.set_phase(Phase.ERROR, "new feature timeout")
    self.stop()
    return LoopAction.Break
```

### Step 6: 编写单元测试与实机夹具
在 `tests/` 中编写对应的测试用例（使用 Mock `Frame` 或真实的 screenshot fixture），验证各种成功、失败、遮挡及超时分支。

---

## 5. 常见调试方法与诊断技巧

### 5.1 CLI Dry-Run 模式 (零输入安全调试)
在无需真实点击游戏的情况下，可以使用 CLI 启动 Dry-Run 模式。脚本会捕获画面、进行识别并打印坐标及状态机转换日志，但**不会触发任何鼠标键盘注入**：

```powershell
# 使用默认配置运行 Dry-Run
python main.py --dry-run

# 使用特定配置文件运行
python main.py --dry-run --config config/default_settings.json
```

### 5.2 图像匹配诊断工具 (`cmd_match`)
在添加新模板后，可以使用内置的 CLI 工具单图验证匹配度与屏幕坐标：

```powershell
python main.py match assets/Images/lobby/stage_begin_btn.png
```
**输出示例**：
```
[match] template=stage_begin_btn.png score=0.985 @ (897, 742) screen=(1057, 892)
```

### 5.3 日志与 Frame Health 诊断
在观察终端日志时，注意以下关键标识：
- `[med] capture ... context=...`：当前捕获窗口尺寸、坐标、状态机阶段及分类器上下文。
- `[med] 静态/陈旧帧 (frozen/old_frame)`：画面没有变化，坐标仍然可信，继续识别。
- `[med] Frame health check failed (black_frame / low_entropy)`：截屏为全黑或纯色低熵帧（可能正在切屏或加载），系统暂停动作并等待。
- `[input] click (x, y) CANCELLED: CANCELLED_WINDOW_OBSCURED`：坐标点被其他窗口遮挡，安全拦截成功。
- `[input] click (x, y) CANCELLED: CANCELLED_NOT_ELEVATED`：进程未提权，已被安全拦截。

### 5.4 急停测试 (Emergency Stop)
在脚本运行期间，随时按下全局热键 **`Shift + F12`**：
- `EmergencyStopListener` 会瞬间触发 `StopSignal`。
- 所有后续的鼠标点击、按键发送与主循环迭代将立即中止（`Action cancelled by stop signal`）。

---

## 6. 代码提交规范与 Checkpoints

为了维持架构的稳定性与安全性，提交代码前必须确认以下 5 条硬性 Guardrails：

1. **测试全通**：运行 `python -m unittest discover -s tests`，确保 76+ 个测试用例（包括 `test_p0_security` 与 `test_p0b_replay`）全部为 `PASS`。
2. **安全链不破坏**：所有新增输入必须带上 `target_hwnd` 并通过 `InputExecutor` 校验，绝对不能绕过前台/遮挡/提权检查。
3. **Fail-Closed 零盲点**：新增场景或识别分支在未能确认页面时，必须默认保持**零输入等待**或超时切 `ERROR` 停机，严禁盲点或强行兜底点击。
4. **窗口坐标对齐**：所有逻辑坐标均以 **1600×900 客户区**为基准，屏幕坐标换算必须通过 `frame.left + x` / `frame.top + y` 或 Win32 API 换算，不得硬编码绝对屏幕坐标。
5. **文档与注释同步**：新增 Phase 或场景映射后，需同步更新 `scenes.json` 与相关架构文档。
