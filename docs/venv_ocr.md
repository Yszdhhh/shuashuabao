# .venv-ocr 隔离环境说明（B2-2）

> 创建：2026-08-10（分支 codex/ocr-hybrid，B2-2 任务）

## 目的

蓝图 B2-2 要求 OCR 试验使用独立环境，不得破坏现有 `.venv`（B0 基线运行环境，无 pip）。

## 创建命令

```powershell
# 用 uv 管理的 Python 3.11.15 base 创建（与 .venv 同版本）
python -m venv .venv-ocr
.\.venv-ocr\Scripts\python.exe -m pip --version   # 确认 pip 可用
```

## 已安装依赖（清华镜像）

```powershell
.\.venv-ocr\Scripts\python.exe -m pip install paddlepaddle -i https://pypi.tuna.tsinghua.edu.cn/simple
.\.venv-ocr\Scripts\python.exe -m pip install paddleocr -i https://pypi.tuna.tsinghua.edu.cn/simple
```

- paddlepaddle 3.3.1（CPU）
- paddleocr 3.7.0
- paddlex 3.7.2

## 关键坑（Windows + 非 ASCII 路径）

Paddle C++ 加载器无法读取含非 ASCII 字符的 Windows 路径（本仓库路径含 `🎮`）。
实测：模型从仓库路径加载失败，复制到 ASCII 路径（`%LOCALAPPDATA%\Temp\gamescript_ocr_stage`）后加载/推理正常。
`tools/evaluate_choice_ocr.py` 内置 staging 逻辑（`--staging-dir` 可覆盖默认暂存目录）。

## 隔离验证

- 删除 `.venv-ocr` 后，B0 基线（`.venv`）原样可运行：compileall / unittest / run_replay 不受影响（B0_BASELINE.md 有基线数值可对照）。
- 现有 `.venv` 的 pip list 在创建前后无变化（快照存于任务期临时目录）。

## 模型

- 模型文件：`models/ocr/PP-OCRv5_mobile_rec_infer/`（不入库）
- 清单与校验：`models/ocr/MODEL_MANIFEST.json`
- 推理全程 `download_enable=False`，已断网验证。
