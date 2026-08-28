# B2-2 补项：PyInstaller 打包可行性评测（2026-08-10）

> 蓝图 B2-2 要求"PyInstaller 冷启动和离线运行可行性"；本项为补测。
> 分支：`codex/ocr-hybrid` | 环境：`.venv-ocr`（paddlepaddle 3.3.1 / paddleocr 3.7.0 / PyInstaller 6.22.0）

## 尝试记录

| # | 方案 | 结果 |
|---|---|---|
| 1 | 默认 onedir 打包（隐式收集） | 运行失败：`mklml.dll` 未正确配置（error 126），537MB |
| 2 | spec 显式收集 `paddle/libs/*.dll` | 运行失败：predictor 创建依赖错误（DLL 链仍缺），635MB |
| 3 | 方案 2 + DLL 复制到 exe 根目录（PATH 兜底） | 运行失败：同 error（paddle 3.x 动态加载链与 PyInstaller onedir 布局不兼容） |

## 实测数值

- 打包体积：537-635MB（**> 蓝图 B10-1 单进程门禁 350MB**）
- 冷启动（至失败点）：3.1-3.3s（含模型加载；失败于 predictor 创建）
- 源码模式对照：模型加载 2.34s + 单槽推理 18.8ms P50（B2-2 已测）
- 干净机器离线运行：**未达**（打包产物无法运行）

## 结论（B10 决策输入）

1. **paddlepaddle 3.x + PyInstaller 单进程打包在本机不可行**（3 种方案均失败；DLL 依赖链/动态加载路径问题是 paddle 3.x 已知难点）
2. **支持蓝图 B10-1 的备选路径：sidecar 方案**——OCR 做成同目录独立进程（JSONL stdin/stdout，只处理裁剪 ROI，不接触输入），主程序 `ocr_mode=off` 时不启动 sidecar
3. 若未来仍想单进程：需降 paddle 版本（2.x 打包资料较多）或引入额外 DLL 收集链（如 pefile 全依赖收集），成本高，B10 再评估
4. 运行期性能不受影响（源码模式 P95 达标）；本结论只影响 B10 打包策略

## 证据文件

- `tools/ocr_cli_min.py`（最小评测 CLI，已入库）
- 打包产物在 `C:/tmp/ocr_build/`（不入库）
