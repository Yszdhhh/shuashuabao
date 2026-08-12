#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刷刷宝 本地桌面控制台启动器 (Native Desktop GUI)
使用 pywebview 挂载高保真 Web 控制面板，双击直接打开独立桌面窗口。
"""

from __future__ import annotations

import sys
import time
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))


def start_server():
    import uvicorn
    from api_server import app
    uvicorn.run(app, host="127.0.0.1", port=17880, log_level="warning")


def main():
    # 启动后台 FastAPI 服务
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # 简单等待服务初始化
    time.sleep(1)

    try:
        import webview
    except ImportError:
        print("未检测到 pywebview，请先运行: pip install pywebview")
        print("临时在浏览器打开: http://localhost:17880")
        import webbrowser
        webbrowser.open("http://localhost:17880")
        server_thread.join()
        return

    # 创建桌面 GUI 窗口（对齐 HANDOFF 文档推荐的 450x820 独立客户端视图）
    window = webview.create_window(
        title="懒人系列之魔兽世界刷刷刷 · 本地控制台",
        url="http://127.0.0.1:17880",
        width=460,
        height=820,
        resizable=True,
        min_size=(420, 700),
        text_select=True,
        confirm_close=True,
    )

    webview.start()


if __name__ == "__main__":
    main()
