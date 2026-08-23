#!/usr/bin/env python3
"""Isolated live probe for the post-game challenge chain.

Run this only while Heroes of the Three Kingdoms is already on a verified
archive/heirloom/rift/NPC-hub page.  It never enters the KK lobby, never
creates a room, and never calls the normal round exit path.  Observation is
the default; ``--execute`` opts into the anchored clicks.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator, Phase
from shuabao.settings import Settings
from shuabao.input.keyboard_mouse import is_current_process_elevated

POST_GAME_PAGES = {
    "ARCHIVE_PANEL",
    "HEIRLOOM_DIALOG",
    "GREAT_RIFT_CONFIRM",
    "NPC_HUB",
}


def load_dashboard_settings() -> Settings:
    """Use the same saved configuration as the desktop dashboard when present."""
    user_path = Path(os.environ.get("LOCALAPPDATA", "")) / "ShuaBao" / "user_settings.json"
    if user_path.is_file():
        return Settings.load(user_path)
    return Settings.load(ROOT / "config" / "default_settings.json")


def relaunch_elevated() -> int:
    """Real input needs the same integrity level as the elevated game client."""
    params = subprocess.list2cmdline([str(Path(__file__).resolve()), *sys.argv[1:]])
    result = int(ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, str(ROOT), 1))
    if result <= 32:
        print(f"[postgame-probe] 请求管理员权限失败（ShellExecute={result}）。")
        return 2
    print("[postgame-probe] 已请求管理员权限；请在新打开的窗口继续观察结果。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="只测试赛后挑战链；默认只观察，不会点击。")
    parser.add_argument("--execute", action="store_true", help="确认执行受锚定的赛后点击")
    parser.add_argument("--seconds", type=float, default=90.0, help="最长观察时长（默认 90 秒）")
    args = parser.parse_args()
    if args.execute and not is_current_process_elevated():
        return relaunch_elevated()

    settings = load_dashboard_settings()
    settings.dry_run = not args.execute
    # This probe is specifically for the archive → boss → hub → secret-realm
    # path.  Keeping it on also prevents NPC_HUB from taking the normal QUIT
    # branch when the dashboard's ordinary setting is disabled.
    settings.auto_secret_realm = True
    settings.auto_create_room = False

    med = Mediator(settings, ROOT)
    med.set_phase(Phase.MAIN_LINE, "isolated post-game probe")
    med._post_game_pending = True
    med._victory_continue_since = time.time()

    mode = "执行" if args.execute else "观察"
    print(f"[postgame-probe] {mode}模式：只处理赛后挑战，不会建房或退出游戏。")
    if not args.execute:
        print("[postgame-probe] 需要实际测试时重新运行并添加 --execute。")

    deadline = time.monotonic() + max(5.0, args.seconds)
    while time.monotonic() < deadline:
        frame = med.see("postgame-probe")
        if not frame.is_valid:
            print(f"[postgame-probe] 抓图无效：{frame.error or 'unknown'}；继续等待")
            time.sleep(0.8)
            continue
        page = med._post_game_state(frame)
        print(f"[postgame-probe] page={page or 'NONE'} hwnd={frame.hwnd}")
        if page == "PAUSED":
            print("[postgame-probe] 检测到暂停层；此工具不会恢复暂停，请先手动回到赛后页。")
        elif page in POST_GAME_PAGES:
            # _tick_main_line is deliberately bounded here to the dedicated
            # post-game branches.  We do not call run(), so L0 and QUIT cannot
            # be reached by this probe.
            med._post_game_pending = True
            if page == "ARCHIVE_PANEL":
                med._post_game_route = "archive_active"
            elif page == "HEIRLOOM_DIALOG":
                med._post_game_route = "heirloom_active"
            elif page == "GREAT_RIFT_CONFIRM":
                med._post_game_route = "secret"
                med._secret_realm_request_pending = True
                med._secret_realm_request_since = time.time()
            med._tick_main_line(frame)
        elif med._secret_realm_active:
            print("[postgame-probe] 已确认进入大秘境局内 HUD；测试链路完成，工具退出。")
            return 0
        else:
            print("[postgame-probe] 未识别到赛后锚点，零输入等待。")
        time.sleep(0.6)

    print("[postgame-probe] 到达观察时限；未调用退出游戏。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
