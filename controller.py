#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地控制台 — UI 对齐官方「懒人系列之魔兽世界刷刷刷」截图字段。
自己刷图；无证书联网。可从官方 Settings.json 同步。
"""

from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

# ---- 尽早失败可见 ----
def _fatal(msg: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("GameScript-Local 启动失败", msg)
        r.destroy()
    except Exception:
        print(msg)
        try:
            input("按回车退出…")
        except Exception:
            pass
    sys.exit(1)


try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except Exception as e:
    print("tkinter 不可用:", e)
    input("按回车退出…")
    sys.exit(1)

try:
    from shuabao.settings import OFFICIAL_SETTINGS, Settings
except Exception as e:
    _fatal(f"导入 settings 失败:\n{e}")

# Mediator 依赖 opencv，延迟导入，保证界面先能打开
Mediator = None  # type: ignore


def _stems(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.png"))


BOSS_MAIN = _stems(ROOT / "assets" / "Images" / "boss")
BOSS_CJB = _stems(ROOT / "assets" / "Images" / "chuanjiaobao")
ALL_SKILLS = _stems(ROOT / "assets" / "Images" / "skills") or [
    "asj", "asjg", "assx", "bsxx", "byj", "dcw", "dz", "hbj",
    "hq", "jf", "jq", "ljf", "pg", "sdl", "tl", "ys",
]

# 官方截图色
BG = "#0b1220"
CARD = "#151c2c"
FG = "#e8eef8"
MUTED = "#8b9bb4"
LINE = "#243044"
BLUE = "#2563eb"
GREEN = "#22c55e"
RED = "#ef4444"


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("懒人系列之魔兽世界刷刷刷 · 本地版")
        self.root.geometry("420x780")
        self.root.minsize(400, 700)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.settings = Settings()
        self._med = None
        self._worker: threading.Thread | None = None

        self._style()
        self._build()
        self.sync_official(silent=True)

    def _style(self) -> None:
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure(".", background=BG, foreground=FG)
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=BG, foreground=FG, font=("Microsoft YaHei UI", 9))
        s.configure("Card.TLabel", background=CARD, foreground=FG, font=("Microsoft YaHei UI", 9))
        s.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=("Microsoft YaHei UI", 8))
        s.configure("Title.TLabel", background=BG, foreground="#60a5fa", font=("Microsoft YaHei UI", 13, "bold"))
        s.configure("Run.TLabel", background=CARD, foreground=GREEN, font=("Microsoft YaHei UI", 11, "bold"))
        s.configure("Idle.TLabel", background=CARD, foreground=MUTED, font=("Microsoft YaHei UI", 11, "bold"))
        s.configure("TLabelframe", background=CARD, foreground=MUTED, bordercolor=LINE)
        s.configure("TLabelframe.Label", background=CARD, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        s.configure("TCheckbutton", background=CARD, foreground=FG, font=("Microsoft YaHei UI", 9))
        s.configure("TButton", font=("Microsoft YaHei UI", 9), padding=5)
        s.configure("Start.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=10)
        s.configure("TEntry", fieldbackground="#0a101c", foreground=FG)
        s.configure("TSpinbox", fieldbackground="#0a101c", foreground=FG)
        s.configure("TCombobox", fieldbackground="#0a101c", foreground=FG)

    def _card(self, parent, title: str) -> ttk.LabelFrame:
        lf = ttk.LabelFrame(parent, text=f"  {title}  ", padding=10, style="TLabelframe")
        lf.pack(fill=tk.X, pady=5, padx=2)
        return lf

    def _build(self) -> None:
        wrap = ttk.Frame(self.root, padding=12)
        wrap.pack(fill=tk.BOTH, expand=True)

        # 标题
        ttk.Label(wrap, text="懒人系列之魔兽世界刷刷刷", style="Title.TLabel").pack()
        ttk.Label(wrap, text="本地版 1.3.3.3-local · 自己刷图（无证书联网）", style="Muted.TLabel").pack(
            pady=(0, 8)
        )

        # 状态（对齐官方：认证/运行/局数）
        c0 = self._card(wrap, "状态")
        r = ttk.Frame(c0, style="Card.TFrame")
        r.pack(fill=tk.X)
        ttk.Label(r, text="认证状态: 本地免证书", style="Muted.TLabel").pack(side=tk.LEFT)
        self.lbl_run = ttk.Label(r, text="空闲", style="Idle.TLabel")
        self.lbl_run.pack(side=tk.RIGHT)
        r2 = ttk.Frame(c0, style="Card.TFrame")
        r2.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(r2, text="当前局数:", style="Card.TLabel").pack(side=tk.LEFT)
        self.var_games = tk.IntVar(value=0)
        ttk.Label(r2, textvariable=self.var_game, style="Card.TLabel", font=("Microsoft YaHei UI", 12, "bold")).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Label(r2, text="Shift+F12 停官方脚本 | 本窗点停止", style="Muted.TLabel").pack(side=tk.RIGHT)

        # 常规运行配置（对齐官方截图字段）
        c1 = self._card(wrap, "常规运行配置")
        r = ttk.Frame(c1, style="Card.TFrame")
        r.pack(fill=tk.X)
        ttk.Label(r, text="目标关卡", style="Card.TLabel").pack(side=tk.LEFT)
        self.var_s1 = tk.IntVar(value=1)
        self.var_s2 = tk.IntVar(value=10)
        ttk.Spinbox(r, from_=1, to=50, width=4, textvariable=self.var_s1).pack(side=tk.LEFT, padx=3)
        ttk.Label(r, text="—", style="Card.TLabel").pack(side=tk.LEFT)
        ttk.Spinbox(r, from_=1, to=50, width=4, textvariable=self.var_s2).pack(side=tk.LEFT, padx=3)

        r = ttk.Frame(c1, style="Card.TFrame")
        r.pack(fill=tk.X, pady=6)
        ttk.Label(r, text="地图/Boss", style="Card.TLabel").pack(side=tk.LEFT)
        self.var_sgzx = tk.StringVar(value=BOSS_MAIN[0] if BOSS_MAIN else "")
        cb1 = ttk.Combobox(r, textvariable=self.var_sgzx, values=BOSS_MAIN, width=16, state="readonly")
        cb1.pack(side=tk.LEFT, padx=3)
        ttk.Label(r, text="传家宝", style="Card.TLabel").pack(side=tk.LEFT, padx=(8, 0))
        self.var_cjb = tk.StringVar(value=BOSS_CJB[0] if BOSS_CJB else "")
        cb2 = ttk.Combobox(r, textvariable=self.var_cjb, values=BOSS_CJB, width=14, state="readonly")
        cb2.pack(side=tk.LEFT, padx=3)

        r = ttk.Frame(c1, style="Card.TFrame")
        r.pack(fill=tk.X)
        ttk.Label(r, text="龙珠数", style="Card.TLabel").pack(side=tk.LEFT)
        self.var_db = tk.IntVar(value=7)
        ttk.Spinbox(r, from_=1, to=10, width=4, textvariable=self.var_db).pack(side=tk.LEFT, padx=3)
        ttk.Label(r, text="等待UI(秒)", style="Card.TLabel").pack(side=tk.LEFT, padx=(10, 0))
        self.var_qto = tk.IntVar(value=120)
        ttk.Spinbox(r, from_=30, to=600, width=5, textvariable=self.var_qto).pack(side=tk.LEFT, padx=3)
        ttk.Label(r, text="发育时间", style="Card.TLabel").pack(side=tk.LEFT, padx=(10, 0))
        self.var_dev = tk.IntVar(value=0)
        ttk.Spinbox(r, from_=0, to=2000, width=5, textvariable=self.var_dev).pack(side=tk.LEFT, padx=3)

        r = ttk.Frame(c1, style="Card.TFrame")
        r.pack(fill=tk.X, pady=4)
        self.var_card = tk.BooleanVar(value=True)
        self.var_weapon = tk.BooleanVar(value=True)
        self.var_dmg = tk.BooleanVar(value=True)
        self.var_secret = tk.BooleanVar(value=False)
        self.var_devpri = tk.BooleanVar(value=True)
        for text, var in [
            ("自动卡组", self.var_card),
            ("自动武器", self.var_weapon),
            ("奥数增伤", self.var_dmg),
            ("发育优先", self.var_devpri),
            ("自动秘境", self.var_secret),
        ]:
            ttk.Checkbutton(r, text=text, variable=var).pack(side=tk.LEFT, padx=4)

        # 声望（对齐官方区块，自己刷图可用）
        c2 = self._card(wrap, "声望运行配置")
        r = ttk.Frame(c2, style="Card.TFrame")
        r.pack(fill=tk.X)
        self.var_rep = tk.BooleanVar(value=False)
        ttk.Checkbutton(r, text="开启自动声望", variable=self.var_rep).pack(side=tk.LEFT)
        ttk.Label(r, text="目标关卡", style="Card.TLabel").pack(side=tk.LEFT, padx=(12, 0))
        self.var_rs1 = tk.IntVar(value=1)
        self.var_rs2 = tk.IntVar(value=10)
        ttk.Spinbox(r, from_=1, to=50, width=4, textvariable=self.var_rs1).pack(side=tk.LEFT, padx=2)
        ttk.Label(r, text="—", style="Card.TLabel").pack(side=tk.LEFT)
        ttk.Spinbox(r, from_=1, to=50, width=4, textvariable=self.var_rs2).pack(side=tk.LEFT, padx=2)
        r = ttk.Frame(c2, style="Card.TFrame")
        r.pack(fill=tk.X, pady=4)
        ttk.Label(r, text="声望Boss", style="Card.TLabel").pack(side=tk.LEFT)
        self.var_rcjb = tk.StringVar(value=BOSS_CJB[0] if BOSS_CJB else "")
        ttk.Combobox(r, textvariable=self.var_rcjb, values=BOSS_CJB, width=14, state="readonly").pack(
            side=tk.LEFT, padx=3
        )
        self.var_rsgzx = tk.StringVar(value=BOSS_MAIN[0] if BOSS_MAIN else "")
        ttk.Combobox(r, textvariable=self.var_rsgzx, values=BOSS_MAIN, width=16, state="readonly").pack(
            side=tk.LEFT, padx=3
        )

        # 技能
        c3 = self._card(wrap, "技能设置（官方 Skills）")
        self.skill_vars: dict[str, tk.BooleanVar] = {}
        grid = ttk.Frame(c3, style="Card.TFrame")
        grid.pack(fill=tk.X)
        for i, code in enumerate(ALL_SKILLS):
            v = tk.BooleanVar(value=False)
            self.skill_vars[code] = v
            ttk.Checkbutton(grid, text=code, variable=v).grid(
                row=i // 4, column=i % 4, sticky="w", padx=4, pady=1
            )

        # 窗口
        c4 = self._card(wrap, "环境")
        r = ttk.Frame(c4, style="Card.TFrame")
        r.pack(fill=tk.X)
        ttk.Label(r, text="游戏窗口标题包含", style="Card.TLabel").pack(side=tk.LEFT)
        self.var_title = tk.StringVar(value="英雄三国")
        ttk.Entry(r, textvariable=self.var_title, width=22).pack(side=tk.LEFT, padx=6)
        self.var_dry = tk.BooleanVar(value=True)
        ttk.Checkbutton(r, text="Dry-run(不真点)", variable=self.var_dry).pack(side=tk.LEFT, padx=6)

        # 按钮区 — 对齐官方大按钮「开始游戏」
        btns = ttk.Frame(wrap)
        btns.pack(fill=tk.X, pady=8)
        ttk.Button(btns, text="从官方同步设置", command=lambda: self.sync_official(False)).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btns, text="保存本地", command=self.save_local).pack(side=tk.LEFT, padx=2)
        ttk.Label(btns, text="步数", style="Muted.TLabel").pack(side=tk.LEFT, padx=(10, 2))
        self.var_steps = tk.IntVar(value=0)  # 0=不限制
        ttk.Spinbox(btns, from_=0, to=99999, width=6, textvariable=self.var_steps).pack(side=tk.LEFT)

        self.btn_start = ttk.Button(wrap, text="开  始  游  戏", style="Start.TButton", command=self.start)
        self.btn_start.pack(fill=tk.X, ipady=6, pady=4)
        self.btn_stop = ttk.Button(wrap, text="停  止", command=self.stop)
        self.btn_stop.pack(fill=tk.X, pady=2)

        warn = (
            "【大厅/房间】独狼模式会尝试在游戏窗口内识别并点击「开始游戏」。\n"
            "脚本随后继续识别选关/主线 UI；若日志提示 miss lobby start，请确认窗口标题、1600×900/100% 缩放并更新模板。\n"
            "自动建房/密码请在 Web 控制面板的 L0 配置中开启；此旧版 Tk 面板仅保留已有配置，不提供建房字段编辑。\n"
            "完整官方：..\\1.3.3.3\\GameScript.exe"
        )
        tk.Label(
            wrap,
            text=warn,
            bg="#3b1d1d",
            fg="#fecaca",
            font=("Microsoft YaHei UI", 8),
            justify=tk.LEFT,
            wraplength=380,
            padx=8,
            pady=6,
        ).pack(fill=tk.X, pady=4)

        # 日志
        logf = self._card(wrap, "运行日志")
        self.log = tk.Text(
            logf, height=8, bg="#080d16", fg=FG, insertbackground=FG,
            font=("Consolas", 9), relief="flat", wrap="word",
        )
        self.log.pack(fill=tk.BOTH, expand=True)

    def _log(self, msg: str) -> None:
        def go() -> None:
            self.log.insert(tk.END, msg + "\n")
            self.log.see(tk.END)

        try:
            self.root.after(0, go)
        except Exception:
            print(msg)

    def _set_run(self, on: bool) -> None:
        self.lbl_run.configure(text="运行中" if on else "空闲", style="Run.TLabel" if on else "Idle.TLabel")

    def sync_official(self, silent: bool = False) -> None:
        try:
            s = Settings.load_official()
        except Exception as e:
            self._log(f"[同步失败] {e}")
            if not silent:
                messagebox.showwarning("同步失败", str(e))
            return
        self.settings = s
        self.var_s1.set(s.stage1)
        self.var_s2.set(s.stage2)
        self.var_db.set(s.dragon_ball_count)
        self.var_qto.set(s.query_timeout)
        self.var_dev.set(s.develop_time)
        self.var_secret.set(s.auto_secret_realm)
        self.var_rep.set(s.auto_reputation)
        self.var_card.set(s.auto_card)
        self.var_weapon.set(s.auto_weapon)
        self.var_dmg.set(s.damage_increase_card)
        self.var_devpri.set(s.develop_priority)
        self.var_rs1.set(s.reputation_stage1 or 1)
        self.var_rs2.set(s.reputation_stage2 or 10)
        if s.sgzx_boss:
            self.var_sgzx.set(s.sgzx_boss)
        if s.cjb_boss:
            self.var_cjb.set(s.cjb_boss)
        if s.reputation_cjb_boss:
            self.var_rcjb.set(s.reputation_cjb_boss)
        if s.reputation_sgzx_boss:
            self.var_rsgzx.set(s.reputation_sgzx_boss)
        if s.window_title_contains:
            self.var_title.set(s.window_title_contains)
        for code, var in self.skill_vars.items():
            var.set(code in (s.skills or []))
        self._log(f"[同步] Skills={s.skills}")
        self._log(f"[同步] 关卡 {s.stage1}—{s.stage2}  Boss {s.sgzx_boss} / 传家宝 {s.cjb_boss}")
        self._log(f"[同步] 来源 {OFFICIAL_SETTINGS}")

    def _collect(self) -> Settings:
        s = self.settings
        s.game_mode = 0
        s.stage1 = int(self.var_s1.get())
        s.stage2 = int(self.var_s2.get())
        s.dragon_ball_count = int(self.var_db.get())
        s.query_timeout = int(self.var_qto.get())
        s.develop_time = int(self.var_dev.get())
        s.sgzx_boss = self.var_sgzx.get().strip()
        s.cjb_boss = self.var_cjb.get().strip()
        s.auto_secret_realm = bool(self.var_secret.get())
        s.auto_reputation = bool(self.var_rep.get())
        s.auto_card = bool(self.var_card.get())
        s.auto_weapon = bool(self.var_weapon.get())
        s.damage_increase_card = bool(self.var_dmg.get())
        s.develop_priority = bool(self.var_devpri.get())
        s.reputation_stage1 = int(self.var_rs1.get())
        s.reputation_stage2 = int(self.var_rs2.get())
        s.reputation_cjb_boss = self.var_rcjb.get().strip()
        s.reputation_sgzx_boss = self.var_rsgzx.get().strip()
        s.window_title_contains = self.var_title.get().strip()
        s.skills = [c for c, v in self.skill_vars.items() if v.get()]
        s.dry_run = bool(self.var_dry.get())
        return s

    def save_local(self) -> None:
        p = ROOT / "config" / "default_settings.json"
        self._collect().save(p)
        self._log(f"[保存] {p}")
        messagebox.showinfo("保存", f"已保存到\n{p}")

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("提示", "已在运行中")
            return
        try:
            from shuabao.mediator import Mediator as _Med
        except Exception as e:
            messagebox.showerror(
                "缺少依赖",
                f"无法加载自动化引擎（需要 OpenCV 等）:\n{e}\n\n"
                f"请在黑窗执行:\n"
                f"python -m pip install -r requirements.txt",
            )
            self._log(f"[依赖] {e}")
            return
        s = self._collect()
        steps = int(self.var_steps.get())
        max_steps = None if steps <= 0 else steps
        self._log(f"[开始] dry_run={s.dry_run} 关卡={s.stage1}-{s.stage2} 技能={s.skills}")
        self._set_run(True)

        def work() -> None:
            import builtins

            med = _Med(s, ROOT)
            self._med = med
            real = builtins.print

            def hook(*a, **k):
                self._log(" ".join(str(x) for x in a))
                real(*a, **k)

            builtins.print = hook  # type: ignore
            try:
                med.run(max_steps=max_steps)
            except Exception:
                self._log(traceback.format_exc())
            finally:
                builtins.print = real  # type: ignore
                self.root.after(0, lambda: self._set_run(False))
                self.root.after(0, lambda: self.var_game.set(med.game_count))
                self._log("[结束]")

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        if self._med:
            self._med.stop()
            self._log("[停止] 已请求")
        self._set_run(False)

    def _on_close(self) -> None:
        self.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    try:
        App().run()
    except Exception:
        _fatal(traceback.format_exc())


if __name__ == "__main__":
    main()
