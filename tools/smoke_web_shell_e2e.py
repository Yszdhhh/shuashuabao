"""Task 8 端到端真机验收：WebConfigShell（SHUABAO_SHELL=web）。

独立临时 SHUABAO_APP_DATA，绝不触碰用户真实 AppData。覆盖：
1. 设置读取 → 修改 → 重启（新建 Facade）后持久化保留；
2. preflight 判定（normal_farm 通过；未开放模式被拦截）；
3. 学习模式（dry_run）安全启动：RunnerService RUNNING、收到 log/state 信号、
   停止后恢复 IDLE 且 live.lock 释放；
4. 100%/125%/150% DPI 缩放截图到 docs/screenshots/（每档独立子进程，QT_SCALE_FACTOR
   必须在 Qt 初始化前设置）。

用法：
    python tools/smoke_web_shell_e2e.py              # 全量验收
    python tools/smoke_web_shell_e2e.py --screenshot --scale 125 --app-data <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(ok), detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    if not ok:
        raise AssertionError(f"{name}: {detail}")


# ------------------------------------------------------------------ 截图子进程


def run_screenshot(scale_pct: int, app_data: Path) -> None:
    """在独立进程中按 QT_SCALE_FACTOR 渲染并截图。"""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from shuabao.shell.web_config_shell import WebConfigShell

    factor = scale_pct / 100.0
    os.environ["QT_SCALE_FACTOR"] = str(factor)

    app = QApplication.instance() or QApplication(sys.argv)
    shell = WebConfigShell(app_data, root=ROOT)
    shell.show()
    out_dir = ROOT / "docs" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"web_shell_{scale_pct}pct.png"
    done: dict = {}

    def grab_and_exit() -> None:
        pix = shell.grab()
        ok = pix.save(str(out_path))
        done["ok"] = ok and pix.width() > 0
        done["w"], done["h"] = pix.width(), pix.height()
        image = pix.toImage()
        colors = {
            image.pixelColor(x, y).rgba()
            for x in range(0, image.width(), max(1, image.width() // 20))
            for y in range(0, image.height(), max(1, image.height() // 20))
        }
        done["colors"] = len(colors)
        app.quit()

    def on_loaded(ok: bool) -> None:
        # 渲染稳定后再抓帧；QTimer 回到事件循环确保首帧 paint 完成。
        QTimer.singleShot(1200, grab_and_exit)

    shell.view.loadFinished.connect(on_loaded)
    QTimer.singleShot(15000, app.quit)  # 兜底超时
    app.exec()

    check(
        f"screenshot_{scale_pct}pct",
        bool(done.get("ok")) and out_path.exists() and int(done.get("colors", 0)) >= 8,
        f"{out_path.name} {done.get('w')}x{done.get('h')} colors={done.get('colors')}",
    )


# ------------------------------------------------------------------ 主流程


def wait_until(app, cond, timeout_ms: int, what: str) -> bool:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    result = {"ok": False}

    def poll() -> None:
        if cond():
            result["ok"] = True
            loop.quit()

    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(poll)
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(loop.quit)
    timer.start()
    watchdog.start(timeout_ms)
    poll()
    if not result["ok"]:
        loop.exec()
    timer.stop()
    if not result["ok"]:
        print(f"[TIMEOUT] 等待超时（{timeout_ms}ms）：{what}", flush=True)
    return result["ok"]


def main_e2e(app_data: Path) -> int:
    from PySide6.QtWidgets import QApplication

    from shuabao.paths import user_settings_path
    from shuabao.shell.dashboard_facade import DashboardFacade
    from shuabao.shell.runner_service import live_lock_busy

    QApplication.instance() or QApplication(sys.argv)  # noqa: B015 信号需主循环

    print(f"# 临时 AppData: {app_data}")

    # ---- 1. 设置读写 + 重启持久化 ------------------------------------------
    facade = DashboardFacade(app_data, root=ROOT)
    snap0 = json.loads(facade.get_snapshot())
    check("settings_read", "settings" in snap0 and isinstance(snap0.get("modes"), list),
          f"cycle_num={snap0['settings'].get('cycle_num')}")

    patch = {"cycle_num": 7, "dry_run": True}
    upd = json.loads(facade.update_config(json.dumps(patch)))
    check("settings_update_ok", upd.get("ok") is True,
          str(upd.get("errors") or ""))
    check("settings_update_applied",
          upd.get("settings", {}).get("cycle_num") == 7
          and upd.get("settings", {}).get("dry_run") is True)

    settings_file = user_settings_path(app_data)
    check("settings_file_written", settings_file.exists(), str(settings_file))

    del facade  # 模拟重启：全新 Facade 从磁盘读回
    facade = DashboardFacade(app_data, root=ROOT)
    snap1 = json.loads(facade.get_snapshot())
    check("settings_persist_after_restart",
          snap1["settings"].get("cycle_num") == 7
          and snap1["settings"].get("dry_run") is True,
          f"cycle_num={snap1['settings'].get('cycle_num')}, "
          f"dry_run={snap1['settings'].get('dry_run')}")

    # ---- 2. preflight 判定 -------------------------------------------------
    pre = json.loads(facade.validate_preflight(json.dumps({"mode_id": "normal_farm"})))
    check("preflight_normal_farm_pass", pre.get("ok") is True,
          json.dumps(pre.get("checks"), ensure_ascii=False))
    pre_bad = json.loads(facade.validate_preflight(json.dumps({"mode_id": "gambling_wood"})))
    check("preflight_blocked_mode_rejected", pre_bad.get("ok") is False,
          pre_bad.get("blocked_reason", ""))
    pre_empty = json.loads(facade.validate_preflight('{"mode_id": ""}'))
    check("preflight_unknown_mode_rejected", pre_empty.get("ok") is False)

    # ---- 3. 学习模式启动/停止与 live.lock ----------------------------------
    logs: list[str] = []
    states: list[dict] = []
    facade.log_appended.connect(lambda text, kind: logs.append(f"[{kind}] {text}"))
    facade.run_status_changed.connect(
        lambda payload: states.append(json.loads(payload)))

    start = json.loads(facade.start_run(json.dumps({"mode_id": "normal_farm"})))
    check("start_run_accepted", start.get("ok") is True, str(start.get("error") or ""))

    runner = facade._ensure_runner()
    proc = QApplication.instance()
    got_running = wait_until(
        proc,
        lambda: bool(logs) or runner.worker is None or not runner.worker.isRunning(),
        15000, "RunnerService RUNNING 与日志信号")
    wait_until(proc, lambda: bool(states) or runner.runner_state != "RUNNING",
               5000, "state 信号")
    check("runner_state_running_observed",
          any(s.get("state") in ("RUNNING", "STOPPING") for s in states)
          or (got_running and runner.runner_state == "RUNNING"),
          f"states={ [s.get('state') for s in states] }, runner={runner.runner_state}")
    check("log_signals_received", len(logs) > 0,
          f"{len(logs)} 条日志: {logs[:2]}")

    stop = json.loads(facade.stop_run())
    check("stop_run_accepted", stop.get("ok") is True)

    worker = runner.worker
    if worker is not None:
        finished = worker.wait(60000)
        check("worker_thread_finished", finished)
    wait_until(proc, lambda: runner.runner_state == "IDLE", 10000,
               "runner 回到 IDLE")
    check("runner_back_to_idle", runner.runner_state == "IDLE", runner.runner_state)
    lock_free = wait_until(proc, lambda: not live_lock_busy(app_data), 5000,
                           "live.lock 释放")
    check("live_lock_released", lock_free and not live_lock_busy(app_data))

    # ---- 4. 多缩放截图（独立子进程） ---------------------------------------
    env = {k: v for k, v in os.environ.items()}
    for pct in (100, 125, 150):
        cmd = [sys.executable, str(Path(__file__).resolve()),
               "--screenshot", "--scale", str(pct), "--app-data", str(app_data)]
        r = subprocess.run(cmd, cwd=str(ROOT), env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
        check(f"screenshot_subprocess_{pct}pct", r.returncode == 0,
              (r.stdout + r.stderr).strip().splitlines()[-1] if r.returncode else "")
        env.pop("QT_SCALE_FACTOR", None)

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--screenshot", action="store_true")
    ap.add_argument("--scale", type=int, default=100)
    ap.add_argument("--app-data", default=None)
    args = ap.parse_args()

    if args.screenshot:
        assert args.app_data, "--screenshot 需要 --app-data"
        run_screenshot(args.scale, Path(args.app_data))
        return 0

    tmp = tempfile.mkdtemp(prefix="shuabao_e2e_appdata_")
    os.environ["SHUABAO_APP_DATA"] = tmp
    code = 1
    try:
        main_e2e(Path(tmp))
        code = 0
    except AssertionError as exc:
        print(f"[ABORT] {exc}", flush=True)
    finally:
        passed = sum(1 for _, ok, _ in CHECKS if ok)
        print(f"\n===== E2E 验收结果: {passed}/{len(CHECKS)} PASS =====")
        for name, ok, detail in CHECKS:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}"
                  + (f" — {detail}" if detail else ""))
        if code == 0:
            print(f"[cleanup] 临时 AppData 保留供检查: {tmp}")
    return code


if __name__ == "__main__":
    sys.exit(main())
