#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GameScript-Local FastAPI 后端服务
提供配置管理、官方同步、选项动态扫描与 Mediator 运行控制接口。
"""

from __future__ import annotations

import builtins
import datetime
import os
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 确保 src 包含在 PATH 中
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from gamescript.settings import OFFICIAL_SETTINGS, Settings

# Mediator 在运行阶段延迟载入（以防部分开发环境缺少 opencv 时接口基础功能依然可用）
Mediator = None
Phase = None


def get_mediator_cls():
    global Mediator, Phase
    if Mediator is None:
        from gamescript.mediator import Mediator as _Med, Phase as _Ph
        Mediator = _Med
        Phase = _Ph
    return Mediator, Phase


PHASE_NAME_MAP = {
    "BOOT": "就绪",
    "WAIT_EXIT": "等待退出",
    "LOBBY_ROOM": "房间大厅",
    "PREPARE": "准备游戏",
    "WAIT_UI": "等待进入UI",
    "PLATFORM_MAP": "地图页",
    "CREATE_ROOM": "创建房间",
    "ROOM_WAITING": "等待房间开始",
    "ROOM_STARTING": "进入游戏",
    "STAGE_SELECT": "选择关卡",
    "STAGE_STARTING": "启动关卡",
    "ERROR": "目标窗口不可用",
    "MAIN_LINE": "主线选卡",
    "EARLY_CHALLENGE": "提前挑战",
    "ANCHOR_BOSS": "锚点Boss",
    "LONGZHU": "查找龙珠",
    "QUIT": "退出本局",
    "NEXT": "下一局",
}


def _stems(folder: Path) -> List[str]:
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.png"))


# 全局运行状态与日志缓冲
class RunnerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None
        self.mediator: Any = None
        self.running: bool = False
        self.phase: str = "BOOT"
        self.phase_name: str = "就绪"
        self.game_count: int = 0
        self.last_error: Optional[str] = None
        self.logs: List[Dict[str, Any]] = []
        self._log_id: int = 0

    def add_log(self, text: str, log_type: str = "info"):
        with self.lock:
            self._log_id += 1
            now_str = datetime.datetime.now().strftime("%H:%M:%S")
            log_item = {
                "id": self._log_id,
                "time": now_str,
                "text": text,
                "type": log_type,
            }
            self.logs.append(log_item)
            # 维持日志容量 2000 行
            if len(self.logs) > 2000:
                self.logs = self.logs[-1500:]

    def get_logs(self, since: int = 0) -> List[Dict[str, Any]]:
        with self.lock:
            return [item for item in self.logs if item["id"] > since]

    def reset_status(self):
        with self.lock:
            self.running = False
            self.phase = "BOOT"
            self.phase_name = "就绪"
            self.game_count = 0
            self.last_error = None


runner = RunnerState()

app = FastAPI(title="GameScript-Local API", version="1.3.3.3-local")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态图片资源
images_path = ROOT / "assets" / "Images"
if images_path.exists():
    app.mount("/assets/Images", StaticFiles(directory=str(images_path)), name="images")


class StartRunRequest(BaseModel):
    dry_run: Optional[bool] = None
    max_steps: Optional[int] = None


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "app": "GameScript-Local",
        "official_settings_exists": OFFICIAL_SETTINGS.is_file(),
    }


@app.get("/api/settings")
def get_settings():
    config_file = ROOT / "config" / "default_settings.json"
    if not config_file.is_file():
        s = Settings()
        s.save(config_file)
    try:
        s = Settings.load(config_file)
        return s.__dict__
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load settings: {e}")


@app.put("/api/settings")
def update_settings(payload: Dict[str, Any]):
    config_file = ROOT / "config" / "default_settings.json"
    try:
        s = Settings._from_dict(payload)
        s.save(config_file)
        runner.add_log(f"[配置] 配置已更新并保存到 {config_file.name}", "info")
        return s.__dict__
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {e}")


@app.post("/api/settings/sync-official")
def sync_official_settings():
    config_file = ROOT / "config" / "default_settings.json"
    try:
        s = Settings.load_official()
        s.save(config_file)
        runner.add_log(f"[同步] 已成功从官方 Settings.json 同步配置: Skills={s.skills}", "info")
        return s.__dict__
    except Exception as e:
        runner.add_log(f"[同步错误] 无法读取官方配置: {e}", "error")
        raise HTTPException(status_code=400, detail=f"官方配置同步失败: {e}")


@app.get("/api/windows")
def get_windows():
    try:
        from gamescript.vision.capture import list_active_window_titles
        return {"windows": list_active_window_titles()}
    except Exception:
        return {"windows": []}


@app.get("/api/options/skills")
def list_skills():
    skills_dir = ROOT / "assets" / "Images" / "skills"
    stems = _stems(skills_dir)
    return [
        {
            "code": stem,
            "image_url": f"/assets/Images/skills/{stem}.png"
            if (skills_dir / f"{stem}.png").exists()
            else None,
        }
        for stem in stems
    ]


@app.get("/api/options/bosses")
def list_bosses():
    boss_dir = ROOT / "assets" / "Images" / "boss"
    cjb_dir = ROOT / "assets" / "Images" / "chuanjiaobao"
    return {
        "main": [
            {
                "name": stem,
                "image_url": f"/assets/Images/boss/{stem}.png",
            }
            for stem in _stems(boss_dir)
        ],
        "cjb": [
            {
                "name": stem,
                "image_url": f"/assets/Images/chuanjiaobao/{stem}.png",
            }
            for stem in _stems(cjb_dir)
        ],
    }


@app.get("/api/options/cards")
def list_cards():
    cards_dir = ROOT / "assets" / "Images" / "cards"
    return [
        {
            "name": stem,
            "image_url": f"/assets/Images/cards/{stem}.png",
        }
        for stem in _stems(cards_dir)
    ]


@app.post("/api/run/start")
def start_run(req: StartRunRequest = StartRunRequest()):
    with runner.lock:
        if runner.running and runner.thread and runner.thread.is_alive():
            return {"status": "already_running", "message": "任务已经在运行中"}

    config_file = ROOT / "config" / "default_settings.json"
    try:
        s = Settings.load(config_file)
    except Exception as e:
        s = Settings()

    if req.dry_run is not None:
        s.dry_run = req.dry_run

    try:
        MedCls, PhEnum = get_mediator_cls()
    except Exception as e:
        runner.add_log(f"[错误] 依赖加载失败: {e}", "error")
        raise HTTPException(
            status_code=500, detail=f"无法加载 Mediator 自动化模块（缺乏 OpenCV 等）：{e}"
        )

    runner.running = True
    runner.last_error = None
    runner.phase = "BOOT"
    runner.phase_name = "就绪"

    max_steps = req.max_steps if (req.max_steps and req.max_steps > 0) else None

    runner.add_log(
        f"[启动] 刷图任务启动 | Dry-run={s.dry_run} | 关卡={s.stage1}-{s.stage2} "
        f"| 精确目标={s.stage_targets or '-'} | 技能={s.skills}",
        "info",
    )

    def worker():
        real_print = builtins.print

        def hook_print(*args, **kwargs):
            text = " ".join(str(arg) for arg in args)
            real_print(*args, **kwargs)

            # 解析关键日志并推送至 runner
            log_type = "info"
            if "失败" in text or "错误" in text or "中断" in text or "timeout" in text:
                log_type = "error"
            elif "警告" in text or "warn" in text.lower() or "miss" in text:
                log_type = "warn"
            runner.add_log(text, log_type)

            # 抓取 Mediator 阶段状态变化
            if "phase " in text:
                try:
                    parts = text.split("phase ")
                    if len(parts) > 1:
                        p_str = parts[1].split()[0]
                        p_name = p_str.split("→")[-1].strip()
                        runner.phase = p_name
                        runner.phase_name = PHASE_NAME_MAP.get(p_name, p_name)
                except Exception:
                    pass

        builtins.print = hook_print

        try:
            med = MedCls(s, ROOT)
            runner.mediator = med
            med.run(max_steps=max_steps)
            runner.game_count = med.game_count
        except Exception as e:
            err_str = f"运行过程中抛出异常: {e}\n{traceback.format_exc()}"
            runner.last_error = str(e)
            runner.add_log(f"[异常] 游戏中断: {e}", "error")
        finally:
            builtins.print = real_print
            with runner.lock:
                runner.running = False
                if runner.mediator:
                    runner.game_count = runner.mediator.game_count
            runner.add_log("[停止] 任务运行结束", "info")

    t = threading.Thread(target=worker, daemon=True)
    runner.thread = t
    t.start()

    return {"status": "started", "dry_run": s.dry_run, "max_steps": max_steps}


@app.post("/api/run/stop")
def stop_run():
    if runner.mediator:
        runner.mediator.stop()
        runner.add_log("[操作] 用户请求停止任务...", "warn")
    with runner.lock:
        runner.running = False
    return {"status": "stopping"}


@app.get("/api/run/status")
def get_run_status():
    if runner.mediator:
        runner.game_count = runner.mediator.game_count
        p_name = runner.mediator.phase.name
        runner.phase = p_name
        runner.phase_name = PHASE_NAME_MAP.get(p_name, p_name)

    return {
        "running": runner.running,
        "phase": runner.phase,
        "phase_name": runner.phase_name,
        "game_count": runner.game_count,
        "last_error": runner.last_error,
        "log_count": len(runner.logs),
    }


@app.get("/api/run/logs")
def get_run_logs(since: int = 0):
    items = runner.get_logs(since=since)
    next_since = items[-1]["id"] if items else since
    return {"logs": items, "next_since": next_since}


# 如果 ui/dist 存在，挂载单页应用
dist_path = ROOT / "ui" / "dist"
if dist_path.exists():
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="ui")

if __name__ == "__main__":
    import uvicorn

    print("==================================================")
    print(" GameScript-Local Web 控制台后端已启动")
    print(" 访问地址: http://localhost:17880")
    print("==================================================")
    uvicorn.run(app, host="127.0.0.1", port=17880, log_level="info")
