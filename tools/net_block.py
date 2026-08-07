#!/usr/bin/env python3
"""断线弹窗抓取工具（P1-B0 素材缺口：missing_disconnect_modal）。

原理：
  1. 用 Windows 防火墙按【进程】阻断游戏进程（KK 平台 Platform.exe，
     游戏在其进程内 CEF 渲染）的全部出站连接 —— 只断游戏，不断整机；
  2. 游戏断线后应弹出断线确认弹窗（gameDisconnect / retryConnect 模板）；
  3. 连续抓屏并用项目模板匹配断线弹窗，命中即保存截图并停止。

用法（需要管理员权限运行）：
  python tools/net_block.py on     # 阻断游戏出站并开始抓屏（默认 120s）
  python tools/net_block.py off    # 解除阻断
  python tools/net_block.py watch  # 仅抓屏（不阻断），观察断线弹窗

产物：断线弹窗截图保存到 --out（默认 C:\\tmp\\disconnect_captures\\）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gamescript.mediator import Mediator
from gamescript.settings import Settings
from gamescript.vision.capture import Frame, capture

RULE_NAME = "GS_DisconnectCapture_BlockOut"
PROCESS_NAMES = ["Platform", "PlatformWebBrowser"]
DISCONNECT_TEMPLATES = ["gameDisconnect", "retryConnect"]


def is_admin() -> bool:
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def game_process_path() -> str | None:
    """Locate the KK platform executable path (game runs in-process CEF).

    The platform runs elevated, so its path is only readable from an elevated
    process; falls back to CIM, then to the process command line.
    """
    names = ",".join(f"'{n}'" for n in PROCESS_NAMES)
    ps = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-Process {PROCESS_NAMES[0]},{PROCESS_NAMES[1]} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Path"],
        capture_output=True, text=True, timeout=30,
    )
    for line in (ps.stdout or "").splitlines():
        line = line.strip()
        if line.lower().endswith(".exe"):
            return line
    # CIM fallback (path may be blanked for elevated processes; try ExecutablePath)
    ps = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-CimInstance Win32_Process -Filter \"Name='{PROCESS_NAMES[0]}' or Name='{PROCESS_NAMES[1]}'\" | Select-Object -First 1 -ExpandProperty ExecutablePath"],
        capture_output=True, text=True, timeout=30,
    )
    for line in (ps.stdout or "").splitlines():
        line = line.strip()
        if line.lower().endswith(".exe"):
            return line
    # command-line fallback (ExtractPathFromCommandLine)
    ps = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-CimInstance Win32_Process -Filter \"Name='{PROCESS_NAMES[0]}'\" | Select-Object -First 1).CommandLine"],
        capture_output=True, text=True, timeout=30,
    )
    for line in (ps.stdout or "").splitlines():
        line = line.strip().strip('"')
        if line.lower().endswith(".exe"):
            return line
    return None


def firewall(cmd: str, program: str | None = None) -> subprocess.CompletedProcess:
    if cmd == "add":
        args = [
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name={RULE_NAME}", "dir=out", f"program={program}", "action=block",
            "enable=yes",
        ]
    else:
        args = ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE_NAME}"]
    return subprocess.run(args, capture_output=True, text=True, timeout=60)


def block_game() -> bool:
    path = game_process_path()
    if not path:
        print("[net_block] 未找到游戏进程（Platform.exe），请先打开 KK 平台并进入游戏")
        return False
    print(f"[net_block] 阻断 {path} 出站…")
    res = firewall("add", path)
    if res.returncode != 0:
        print(f"[net_block] 防火墙规则失败: {res.stdout} {res.stderr}")
        return False
    print("[net_block] 已阻断（规则名 %s）。出现断线弹窗后会自动抓屏。" % RULE_NAME)
    return True


def unblock() -> None:
    res = firewall("delete")
    print(f"[net_block] 解除阻断: rc={res.returncode} {res.stdout.strip() or res.stderr.strip()}")


def watch(duration: int, out_dir: Path, require_disconnect: bool) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    med = Mediator(Settings(), ROOT)
    start = time.time()
    shot = 0
    while time.time() - start < duration:
        try:
            frame = capture("英雄三国,KK官方,KK对战,KK竞技,对战平台,竞技平台,KK", activate=False)
            if frame is not None and frame.bgr is not None and frame.bgr.size > 0:
                ts = time.strftime("%Y%m%d_%H%M%S")
                path = out_dir / f"{ts}_h{frame.hwnd}.png"
                cv2.imwrite(str(path), frame.bgr)
                shot += 1
                # check for the disconnect modal
                hit = med.find(frame, DISCONNECT_TEMPLATES, threshold=0.60, scales=(0.9, 1.0, 1.1))
                if hit:
                    print(f"[net_block] 命中断线弹窗模板 {hit.name} score={hit.score:.3f} -> {path}")
                    if require_disconnect:
                        return 0
        except Exception as e:
            print(f"[net_block] 抓屏异常: {e}")
        time.sleep(2.0)
    print(f"[net_block] 观察结束（{duration}s，{shot} 帧），未命中断线弹窗模板")
    return 1 if require_disconnect else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["on", "off", "watch"])
    p.add_argument("--seconds", type=int, default=120)
    p.add_argument("--out", default=r"C:\tmp\disconnect_captures")
    args = p.parse_args()

    out_dir = Path(args.out)

    if args.mode == "off":
        unblock()
        return 0

    if args.mode == "watch":
        return watch(args.seconds, out_dir, require_disconnect=False)

    # mode == on: block + watch
    if not is_admin():
        print("[net_block] 需要管理员权限（防火墙规则）。请用管理员终端运行，或使用启动面板的提权方式。")
        return 2
    if not block_game():
        return 1
    try:
        return watch(args.seconds, out_dir, require_disconnect=True)
    finally:
        unblock()


if __name__ == "__main__":
    sys.exit(main())
