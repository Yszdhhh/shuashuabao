#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷刷宝 桌面测试看板 (Test Dashboard)。

用于在桌面直接打开测试看板，核验运行身份与测试方案，执行 ZERO-INPUT 预检及启动实机测试。
复用现有链路：Dashboard / shell -> test profile -> one-click test -> live_scenario_capture -> RuntimeMediator。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

# 确保导入当前 worktree 的 shuabao 源码
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 连接 Default 交互桌面以支持窗口枚举
if sys.platform == "win32":
    try:
        _u = ctypes.windll.user32
        _h = _u.OpenDesktopW("Default", 0, False, 0x01FF)
        if _h:
            _u.SetThreadDesktop(_h)
    except Exception:
        pass

import shuabao
from shuabao.vision import capture
from shuabao.shell.test_profiles import load_test_profiles

from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QIcon, QFont, QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def get_git_output(args: list[str]) -> str:
    try:
        p = subprocess.run(
            ["git", "-C", str(ROOT)] + args,
            capture_output=True,
            text=True,
            check=True,
        )
        return p.stdout.strip()
    except Exception:
        return ""


def get_identity_info() -> dict[str, str]:
    test_head = get_git_output(["rev-parse", "HEAD"])
    prod_base = get_git_output(["merge-base", "origin/fix/solo-live-regression-20260915", "HEAD"])
    if not prod_base:
        prod_base = get_git_output(["rev-parse", "origin/fix/solo-live-regression-20260915"])
    shuabao_pkg = getattr(shuabao, "__file__", "")
    return {
        "root": str(ROOT),
        "test_head": test_head,
        "prod_base": prod_base,
        "python": sys.executable,
        "imported_shuabao": shuabao_pkg,
        "package_valid": str(ROOT / "src") in shuabao_pkg,
    }


class PreflightChecker:
    @staticmethod
    def check() -> dict[str, any]:
        result = {
            "ready": False,
            "status": "BLOCKED_PRECONDITION",
            "reasons": [],
            "game_hwnd": None,
            "game_title": "",
            "kk_hwnd": None,
            "kk_minimized": False,
            "ocr_ready": False,
        }

        # 检查 Default 桌面连接
        if sys.platform == "win32":
            try:
                _u = ctypes.windll.user32
                _h = _u.OpenDesktopW("Default", 0, False, 0x01FF)
                if _h:
                    _u.SetThreadDesktop(_h)
            except Exception:
                pass

        # 1. 检查 KK 平台
        kk_targets = capture.find_window_targets("KK", allow_minimized=True)
        if kk_targets:
            target = kk_targets[0]
            result["kk_hwnd"] = target.hwnd
            result["kk_minimized"] = (target.left <= -30000 or target.top <= -30000)
            if result["kk_minimized"]:
                result["reasons"].append("KK 官方对战平台当前处于【最小化】状态")
        else:
            result["reasons"].append("未发现 KK 官方对战平台窗口")

        # 2. 检查游戏窗口
        game_targets = capture.find_window_targets("英雄三国", allow_minimized=True)
        if game_targets:
            g = game_targets[0]
            result["game_hwnd"] = g.hwnd
            result["game_title"] = g.title
            if g.left <= -30000 or g.top <= -30000:
                result["reasons"].append("英雄三国游戏窗口处于【最小化】状态")
        else:
            result["reasons"].append("未检测到【英雄三国】游戏窗口（Game_x64h.exe 未运行）")

        # 3. 检查 OCR 解释器与模型
        ocr_python = ROOT.parent.parent / "GameScript-Local" / ".venv-ocr" / "Scripts" / "python.exe"
        ocr_model = ROOT.parent.parent / "GameScript-Local" / "models" / "ocr"
        if ocr_python.exists() and ocr_model.exists():
            result["ocr_ready"] = True
        else:
            result["reasons"].append("OCR 环境或模型文件缺失")

        if not result["reasons"]:
            result["ready"] = True
            result["status"] = "READY"

        return result


class TestDashboardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("刷刷宝 测试看板 · 海盗+亡灵机制GT")
        self.resize(780, 720)
        self._init_ui()
        self.refresh_identity()
        self.do_preflight(silent=True)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QFrame()
        header.setStyleSheet("background: #2b303c; border-radius: 8px; padding: 12px;")
        h_lay = QVBoxLayout(header)
        h_title = QLabel("刷刷宝 实机测试看板 (Test Dashboard)")
        h_title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        h_sub = QLabel("对齐测试分支: test/pirate-necromancy-gt-20260917 | 生产基线: origin/fix/solo-live-regression-20260915")
        h_sub.setStyleSheet("color: #9aa0a6; font-size: 12px;")
        h_lay.addWidget(h_title)
        h_lay.addWidget(h_sub)
        layout.addWidget(header)

        # 1. 身份核验
        grp_id = QGroupBox("运行身份与环境核验 (Identity & Environment Verification)")
        grp_id.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #dcdfe6; border-radius: 6px; margin-top: 6px; padding-top: 10px; }")
        grid_id = QGridLayout(grp_id)
        grid_id.setSpacing(8)

        self.lbl_root = QLabel("正在读取...")
        self.lbl_head = QLabel("正在读取...")
        self.lbl_base = QLabel("正在读取...")
        self.lbl_import = QLabel("正在读取...")
        self.lbl_python = QLabel("正在读取...")

        grid_id.addWidget(QLabel("测试 Worktree:"), 0, 0)
        grid_id.addWidget(self.lbl_root, 0, 1)
        grid_id.addWidget(QLabel("测试 HEAD SHA:"), 1, 0)
        grid_id.addWidget(self.lbl_head, 1, 1)
        grid_id.addWidget(QLabel("生产 Base SHA:"), 2, 0)
        grid_id.addWidget(self.lbl_base, 2, 1)
        grid_id.addWidget(QLabel("导入 shuabao 路径:"), 3, 0)
        grid_id.addWidget(self.lbl_import, 3, 1)
        grid_id.addWidget(QLabel("Python 解释器:"), 4, 0)
        grid_id.addWidget(self.lbl_python, 4, 1)

        layout.addWidget(grp_id)

        # 2. 测试方案
        grp_profile = QGroupBox("当前加载测试方案 (Active Test Profile)")
        grp_profile.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #dcdfe6; border-radius: 6px; margin-top: 6px; padding-top: 10px; }")
        v_prof = QVBoxLayout(grp_profile)
        self.lbl_prof_name = QLabel("【海盗+亡灵机制GT】 (内置测试方案)")
        self.lbl_prof_name.setStyleSheet("font-size: 14px; font-weight: bold; color: #1a73e8;")
        self.lbl_prof_desc = QLabel(
            "• 关卡目标: 1-12 | 循环局数: 1 局\n"
            "• 自动秘境: True (战后进入秘境) | 自动吞丹: False (MANUAL_GT 保护，严禁自动吞丹)\n"
            "• 初始羁绊: 经济 | 必拿卡牌: 藏宝图(三) | 进阶解锁: 60.0s\n"
            "• 构筑卡包: ['zhufu', 'jj', '藏宝图(三)', '海盗', '亡灵']"
        )
        self.lbl_prof_desc.setStyleSheet("color: #3c4043; line-height: 1.4;")
        v_prof.addWidget(self.lbl_prof_name)
        v_prof.addWidget(self.lbl_prof_desc)
        layout.addWidget(grp_profile)

        # 3. 预检状态
        grp_pre = QGroupBox("窗口与实机预检状态 (Preflight Status)")
        grp_pre.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #dcdfe6; border-radius: 6px; margin-top: 6px; padding-top: 10px; }")
        v_pre = QVBoxLayout(grp_pre)
        self.lbl_pre_status = QLabel("预检状态: 检测中...")
        self.lbl_pre_status.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.lbl_pre_detail = QLabel("")
        self.lbl_pre_detail.setStyleSheet("color: #d93025;")
        v_pre.addWidget(self.lbl_pre_status)
        v_pre.addWidget(self.lbl_pre_detail)
        layout.addWidget(grp_pre)

        # 4. 操作按钮栏
        btn_box = QHBoxLayout()
        btn_box.setSpacing(12)

        self.btn_preflight = QPushButton("一键预检 (ZERO-INPUT)")
        self.btn_preflight.setStyleSheet("padding: 10px 16px; font-size: 13px;")
        self.btn_preflight.clicked.connect(lambda: self.do_preflight(silent=False))
        btn_box.addWidget(self.btn_preflight)

        self.btn_start = QPushButton("开始测试 (Live GT)")
        self.btn_start.setStyleSheet(
            "background-color: #1a73e8; color: white; padding: 10px 24px; "
            "font-size: 14px; font-weight: bold; border-radius: 4px;"
        )
        self.btn_start.clicked.connect(self.on_start_test_clicked)
        btn_box.addWidget(self.btn_start, 1)

        self.btn_open_native = QPushButton("打开完整配置看板")
        self.btn_open_native.setStyleSheet("padding: 10px 16px; font-size: 13px;")
        self.btn_open_native.clicked.connect(self.on_open_native_dashboard)
        btn_box.addWidget(self.btn_open_native)

        layout.addLayout(btn_box)

        # 5. 日志与指引
        layout.addWidget(QLabel("执行日志与实机指引 (Shift+F12 紧急停止 | p=PASS f=FAIL m=MANUAL_INTERVENTION):"))
        self.log_txt = QPlainTextEdit()
        self.log_txt.setReadOnly(True)
        self.log_txt.setStyleSheet("background: #f8f9fa; font-family: Consolas, monospace; font-size: 12px;")
        layout.addWidget(self.log_txt, 1)

    def log(self, msg: str):
        self.log_txt.appendPlainText(msg)

    def refresh_identity(self):
        info = get_identity_info()
        self.lbl_root.setText(info["root"])
        self.lbl_head.setText(f"{info['test_head'][:12]} (HEAD)")
        self.lbl_base.setText(f"{info['prod_base'][:12]} (origin/fix/solo-live-regression-20260915)")
        status_txt = " [通过]" if info["package_valid"] else " [错误: 未从当前worktree导入]"
        self.lbl_import.setText(info["imported_shuabao"] + status_txt)
        self.lbl_python.setText(info["python"])
        self.log(f"[identity] Worktree: {info['root']}")
        self.log(f"[identity] Test HEAD: {info['test_head']}")
        self.log(f"[identity] Production Base: {info['prod_base']}")
        self.log(f"[identity] shuabao: {info['imported_shuabao']}")

    def do_preflight(self, silent=False):
        res = PreflightChecker.check()
        if res["ready"]:
            self.lbl_pre_status.setText("预检状态: ● READY (窗口与环境就绪)")
            self.lbl_pre_status.setStyleSheet("color: #188038; font-weight: bold; font-size: 13px;")
            self.lbl_pre_detail.setText(f"游戏 HWND: {res['game_hwnd']} | 标题: {res['game_title']} | OCR: 就绪")
            self.lbl_pre_detail.setStyleSheet("color: #188038;")
            self.log("[preflight] 预检结果: READY。游戏窗口已确认。")
        else:
            self.lbl_pre_status.setText("预检状态: ● BLOCKED_PRECONDITION (条件不满足)")
            self.lbl_pre_status.setStyleSheet("color: #d93025; font-weight: bold; font-size: 13px;")
            detail_msg = "\n".join(f"• {r}" for r in res["reasons"])
            self.lbl_pre_detail.setText(detail_msg)
            self.lbl_pre_detail.setStyleSheet("color: #d93025;")
            self.log("[preflight] 预检结果: BLOCKED_PRECONDITION。")
            for r in res["reasons"]:
                self.log(f"  -> {r}")
            if not silent:
                QMessageBox.warning(
                    self,
                    "实机预检未就绪 (ZERO INPUT)",
                    f"当前无法启动实机测试（已执行 ZERO INPUT 拦截）：\n\n{detail_msg}\n\n"
                    "处理建议：\n1. 打开或恢复 KK 官方对战平台与英雄三国游戏窗口；\n"
                    "2. 停在地图页、建房弹窗、房间或选关页；\n"
                    "3. 保持游戏窗口可见（不要最小化）；\n4. 再次点击【开始测试】。",
                )
        return res

    def on_start_test_clicked(self):
        self.log("[action] 用户点击【开始测试】。正在执行安全前置预检...")
        res = self.do_preflight(silent=False)
        if not res["ready"]:
            self.log("[安全拦截] 预检未通过，坚决执行 ZERO INPUT，未发出任何键盘鼠标指令。")
            return

        # 启动 one_click_test.cmd
        self.log("[点火] 预检全部通过！正在调用 one_click_test.cmd 启动实机链路...")
        cmd_path = str(ROOT / "one_click_test.cmd")
        try:
            subprocess.Popen(["cmd.exe", "/c", cmd_path], cwd=str(ROOT))
            self.log("[点火] 已拉起实机测试会话进程。请不要触碰键盘鼠标。紧急停止请按 Shift+F12。")
        except Exception as exc:
            self.log(f"[错误] 拉起测试失败: {exc}")
            QMessageBox.critical(self, "启动失败", f"无法拉起测试: {exc}")

    def on_open_native_dashboard(self):
        self.log("[action] 正在打开原生配置面板...")
        from shuabao.shell.main_window import MainWindow, APP_DATA
        self._native_window = MainWindow(app_data=APP_DATA)
        self._native_window.show()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("ShuaBao-Test-Dashboard")
    logo_ico = ROOT / "assets" / "branding" / "app_logo.ico"
    if logo_ico.exists():
        app.setWindowIcon(QIcon(str(logo_ico)))
    win = TestDashboardWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
