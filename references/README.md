# Open-source reference snapshots

这些目录是为了让云端 AI 能在**同一个公开仓库**里审查相关实现而保留的精简上游快照，不是本项目的运行时依赖，也没有被 `src/gamescript` 导入。每个目录只保留与窗口捕获、图像匹配、Windows GUI 控制有关的代码，以及上游 README/许可证文件。

锁定的来源与 commit 见 [`SOURCES.lock.json`](SOURCES.lock.json)。如果需要完整历史、完整测试或最新版本，应以表中的上游仓库为准。

## 快速审查顺序

1. 先读 [`../docs/REMOTE_REVIEW.md`](../docs/REMOTE_REVIEW.md) 和 [`../src/gamescript/mediator.py`](../src/gamescript/mediator.py)。
2. 对比 [`python-mss/src/mss/windows/gdi.py`](python-mss/src/mss/windows/gdi.py) 与本项目 `capture.py`：MSS 是屏幕像素捕获，不等于被遮挡窗口的内容捕获。
3. 对比 [`airtest/airtest/core/cv.py`](airtest/airtest/core/cv.py)、[`airtest/airtest/core/win/`](airtest/airtest/core/win/)：图像模板匹配、Windows 窗口/输入边界。
4. 对比 [`pywinauto/pywinauto/`](pywinauto/pywinauto/)：Win32/UIA 控件树是否可用，以及后台输入的限制。
5. 看 [`ComputerVision_bot/Test.py`](ComputerVision_bot/Test.py)：最小的“枚举窗口→截窗口→模板定位”游戏脚本样例。

## 来源与用途

| 目录 | 上游仓库 | 许可证 | 本项目借鉴点 |
|---|---|---|---|
| `airtest/` | [AirtestProject/Airtest](https://github.com/AirtestProject/Airtest) | Apache-2.0 | 游戏/App 的图像识别自动化、Windows 设备/输入抽象 |
| `pywinauto/` | [pywinauto/pywinauto](https://github.com/pywinauto/pywinauto) | BSD-3-Clause | Win32/UIA 窗口和控件发现、文本属性和输入边界 |
| `python-mss/` | [BoboTiG/python-mss](https://github.com/BoboTiG/python-mss) | MIT | 快速屏幕/区域截图、NumPy/OpenCV 对接 |
| `ComputerVision_bot/` | [edd-ie/ComputerVision_bot](https://github.com/edd-ie/ComputerVision_bot) | 上游 README 声明 BSD-3-Clause | 最小化游戏窗口枚举、窗口截图和模板定位流程 |

## 许可证边界

- Airtest、pywinauto、python-mss 的上游许可证文件已分别放在对应目录。
- `ComputerVision_bot` 的上游仓库快照中没有单独的 LICENSE 文件；其原始 README 声明 BSD-3-Clause，原始 README 已保留，复用前应以作者仓库当前许可为准。
- 这些快照没有包含官方游戏二进制、官方 `LicenseTxt`、房间密码或本机运行配置。
- 不要把 `references/` 加入运行时 `PYTHONPATH`；它们只用于代码审查、对比和定位问题。

## 给云端 AI 的一句话任务

> 请先阅读 `docs/REMOTE_REVIEW.md`，再对比 `src/gamescript/vision/capture.py`、`src/gamescript/mediator.py` 与 `references/` 中的窗口捕获/模板匹配实现；重点判断 L0 建房、房间开始、L1 选关分别在哪个 HWND、哪个截图后端和哪个状态转换上可能失败，并给出可复现的日志字段，而不是只建议“提高阈值”。
