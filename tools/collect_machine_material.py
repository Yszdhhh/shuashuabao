#!/usr/bin/env python3
"""R0 实机素材采集工具（dry-run：只打印指引 + 目录检查，零输入动作）。

对应蓝图 §15 R0.1（960×540 与断线素材缺口）与 O3 门禁 BLOCKED 项：
  - 每类（技能 skill / 羁绊 bond / 宝物 treasure）≥10 张真实 960×540 选择面板帧
    （游戏窗口以 960×540 运行采集；禁止把 1600×900 缩放成"真实 960×540"）；
  - ≥1 帧真实断线弹窗帧（命名素材 gameDisconnect / retryConnect）。

本工具永不发送输入：不 import 生产运行时，不点击、不按键、不写任何文件。

用法：
  .venv\\Scripts\\python.exe tools/collect_machine_material.py            # 指引 + 素材到位检查表（exit 0）
  .venv\\Scripts\\python.exe tools/collect_machine_material.py --check    # exit 0=素材齐 / 1=缺素材
  .venv\\Scripts\\python.exe tools/collect_machine_material.py --json     # 检查表以 JSON 输出（便于 R0 报告引用）
  .venv\\Scripts\\python.exe tools/collect_machine_material.py --root <dir> --panels-days 30

素材目录约定（本工具文档化，配合 D0_SESSION_MAP_20260811.md / incidents.py）：
  素材根目录  GSL_MATERIAL_ROOT 或 --root，默认 C:\\Users\\<user>\\Desktop\\录屏素材
  960×540 面板帧  <root>\\960x540\\skill|bond|treasure\\panel_<YYYYMMDD_HHMMSS>_<fp8>.png
                   （每类一目录；每 panel episode 一帧主样本；分辨率必须恰为 960×540）
  断线弹窗帧  <root>\\disconnect\\gameDisconnect_<ts>.png / retryConnect_<ts>.png
               （文件名必须含 gameDisconnect / retryConnect 标识，与 SCENES.md 模板名一致）
               （也可用 tools/net_block.py 自动阻断+抓屏：默认输出 C:\\tmp\\disconnect_captures）
  panel episodes（自动收集）  %LocalAppData%\\GameScript-Local\\YYYYMMDD\\panels\\
               panel_<HHMMSS_mmm>_<fp8>.jpg + <同名>.json（kind=panel_sample，
               300s 内容指纹去重；Mediator 旁路归档，无输入动作权 —— src/gamescript/incidents.py）
  incidents（异常归档）       %LocalAppData%\\GameScript-Local\\incidents\\YYYYMMDD\\incidents\\
  录屏/索引  C:\\tmp\\recordings\\（rec1-rec8 既有；idx_a/idx_b 为 1fps 索引帧目录，
               video_index_meta.json 记录 probe/sha256/frames）
  会话映射   视频 → rec<seq>_<内容>_<YYYYMMDD>（参照 D0_SESSION_MAP：idx_a→rec9_mijing_20260810、
              idx_b→rec10_3normal_20260810）；面板帧 → 960x540_<YYYYMMDD>；
              panels 日目录 → panel_sample_<YYYYMMDD>；断线帧 → disconnect_<YYYYMMDD>。
  每条素材记录 SHA256（前 16 位）/时间戳/分辨率/会话映射，与 D0 治理口径一致。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

IMAGE_EXTS = (".png", ".jpg", ".jpeg")
VIDEO_EXTS = (".mp4", ".avi", ".mkv", ".mov", ".flv", ".wmv")
PANEL_CLASSES = ("skill", "bond", "treasure")
DISCONNECT_TOKENS = ("gameDisconnect", "retryConnect")
# net_block.py 的默认输出目录（用户可能没指定 --out 而使用默认值）
NETBLOCK_DEFAULT_OUT = Path(r"C:\tmp\disconnect_captures")

# ---------------------------------------------------------------------------
# 素材探针（SHA256 / 分辨率 / 时间戳）
# ---------------------------------------------------------------------------


def sha256_hex(path: Path, prefix: int = 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:prefix]


def _png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """SOF 段扫描：返回 (width, height)；找不到 SOF 返回 None。"""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return struct.unpack(">HH", data[i + 5:i + 9])
        i += 2 + seg_len
    return None


def _probe_cv2(path: Path) -> tuple[int, int] | None:
    """用 cv2 读尺寸（仓库 .venv 自带；失败返回 None 走 stdlib 兜底）。"""
    try:
        import cv2  # type: ignore

        img = cv2.imread(str(path))
        if img is None:
            return None
        h, w = img.shape[:2]
        return w, h
    except Exception:
        return None


def image_size(path: Path) -> tuple[int, int] | None:
    """返回 (width, height)；任何解析失败返回 None（不抛异常）。"""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    for sniff in (_png_size, _jpeg_size):
        size = sniff(data)
        if size is not None:
            return size
    return _probe_cv2(path)


@dataclass
class ImageItem:
    path: str
    width: int
    height: int
    sha256: str
    mtime: str  # ISO
    session: str
    note: str = ""


def _session_from_mtime(mtime: float, prefix: str) -> str:
    return f"{prefix}_{datetime.fromtimestamp(mtime).strftime('%Y%m%d')}"


def scan_frame_dir(directory: Path, session_prefix: str, want: tuple[int, int] | None = None) -> tuple[list[ImageItem], list[ImageItem]]:
    """扫描目录下所有图片：SHA/尺寸/时间戳/会话映射。

    返回 (accepted, skipped)：want=(960,540) 时 accepted 仅含分辨率恰为
    960×540 的帧（真实 960×540 素材口径，不缩放伪造）；skipped 记录
    非目标分辨率/不可读项（仅提示，不计入门禁计数）。
    """
    accepted: list[ImageItem] = []
    skipped: list[ImageItem] = []
    if not directory.is_dir():
        return accepted, skipped
    for p in sorted(directory.iterdir()):
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        mtime = datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
        session = _session_from_mtime(p.stat().st_mtime, session_prefix)
        size = image_size(p)
        if size is None:
            skipped.append(ImageItem(str(p), 0, 0, sha256_hex(p), mtime, session, "note=unreadable"))
            continue
        w, h = size
        if want is not None and (w, h) != want:
            skipped.append(ImageItem(str(p), w, h, sha256_hex(p), mtime, session, "note=skipped_not_target_res"))
            continue
        accepted.append(ImageItem(str(p), w, h, sha256_hex(p), mtime, session))
    return accepted, skipped


def scan_videos(directory: Path) -> list[dict]:
    """视频清单：SHA/时长/分辨率/fps/总帧数/时间戳/会话映射建议。

    用 cv2 探测（无 cv2 时仅记录 SHA 与文件信息）。"""
    out: list[dict] = []
    if not directory.is_dir():
        return out
    for p in sorted(directory.iterdir()):
        if p.suffix.lower() not in VIDEO_EXTS or not p.is_file():
            continue
        row: dict = {
            "path": str(p),
            "size_bytes": p.stat().st_size,
            "sha256": sha256_hex(p),
            "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
            "session_suggestion": f"recX_{p.stem}_{datetime.fromtimestamp(p.stat().st_mtime):%Y%m%d}",  # X=下一序号，参照 D0 会话命名
        }
        try:
            import cv2  # type: ignore

            cap = cv2.VideoCapture(str(p))
            if cap.isOpened():
                row["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                row["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                row["fps"] = round(float(cap.get(cv2.CAP_PROP_FPS)), 3)
                row["frames"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                cap.release()
        except Exception:
            row["note"] = "cv2 unavailable; resolution/frames not probed"
        out.append(row)
    return out


def scan_panel_days(localappdata: Path, days: int) -> list[dict]:
    """panel_sample 自动收集目录：%LocalAppData%\\GameScript-Local\\YYYYMMDD\\panels\\。

    每个日目录 = 一个采集 session（panel_sample_<YYYYMMDD>）；记录 jpg 数、
    960×540 帧数（真实窗口证据）、SHA 样例与时间范围。"""
    base = localappdata / "GameScript-Local"
    out: list[dict] = []
    if not base.is_dir():
        return out
    cutoff = datetime.now().timestamp() - days * 86400
    for day_dir in sorted(base.iterdir()):
        if not day_dir.is_dir() or not re.fullmatch(r"\d{8}", day_dir.name):
            continue
        panels = day_dir / "panels"
        if not panels.is_dir():
            continue
        jpgs = sorted(p for p in panels.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        if not jpgs:
            continue
        jpgs = [p for p in jpgs if p.stat().st_mtime >= cutoff]
        if not jpgs:
            continue
        total = len(jpgs)
        n960 = 0
        sha_samples: list[str] = []
        for p in jpgs:
            size = image_size(p)
            if size == (960, 540):
                n960 += 1
            if len(sha_samples) < 3:
                sha_samples.append(f"{p.name}:{sha256_hex(p)}")
        out.append({
            "session": f"panel_sample_{day_dir.name}",
            "day": day_dir.name,
            "dir": str(panels),
            "frames": total,
            "frames_960x540": n960,
            "first": jpgs[0].stat().st_mtime,
            "last": jpgs[-1].stat().st_mtime,
            "sha_samples": sha_samples,
        })
    return out


def scan_disconnect(root: Path) -> dict:
    """断线弹窗帧：<root>\\disconnect\\ + net_block 默认输出目录。

    命名素材（文件名含 gameDisconnect / retryConnect）单独计数；
    未命名帧单独列出（提示按命名规范重命名）。"""
    dirs = [root / "disconnect", NETBLOCK_DEFAULT_OUT]
    named: list[ImageItem] = []
    unnamed: list[ImageItem] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.suffix.lower() not in IMAGE_EXTS:
                continue
            name = p.name.lower()
            if any(t.lower() in name for t in DISCONNECT_TOKENS):
                named.append(ImageItem(str(p), *(image_size(p) or (0, 0)), sha256_hex(p),
                                       datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                                       _session_from_mtime(p.stat().st_mtime, "disconnect")))
            else:
                unnamed.append(ImageItem(str(p), *(image_size(p) or (0, 0)), sha256_hex(p),
                                         datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
                                         _session_from_mtime(p.stat().st_mtime, "disconnect"),
                                         "note=unnamed_missing_token"))
    return {"named": named, "unnamed": unnamed}


# ---------------------------------------------------------------------------
# 指引文本
# ---------------------------------------------------------------------------

GUIDE = """\
============================================================
 R0 实机素材采集指引（dry-run：零输入动作，本工具只打印+检查）
 对照门禁：O3 BLOCKED（docs/baselines/O3_GATE_CORRECTION_20260811.md）
============================================================

【素材目标】两条硬门禁缺口：
  1) 每类 ≥10 张真实 960×540 选择面板帧
     （技能 skill / 羁绊 bond / 宝物 treasure；游戏窗口 960×540 运行采集，
       禁止把 1600×900 缩放成"真实 960×540"）
  2) ≥1 帧真实断线弹窗（命名素材 gameDisconnect / retryConnect）

【目录约定】
  素材根目录      GSL_MATERIAL_ROOT 或 --root（默认 <桌面>\\录屏素材）
  960×540 帧      <root>\\960x540\\skill|bond|treasure\\panel_<日期_时间>_<fp8>.png
  断线弹窗帧      <root>\\disconnect\\gameDisconnect_<时间戳>.png / retryConnect_<时间戳>.png
  panel episodes  %LocalAppData%\\GameScript-Local\\YYYYMMDD\\panels\\（panel_sample 自动收集）
  incidents       %LocalAppData%\\GameScript-Local\\incidents\\YYYYMMDD\\incidents\\
  每条素材记录 SHA256(16)/时间戳/分辨率/会话映射（会话 id 形如
  rec<seq>_<内容>_<YYYYMMDD>、960x540_<YYYYMMDD>、panel_sample_<YYYYMMDD>、
  disconnect_<YYYYMMDD>；参照 docs/baselines/D0_SESSION_MAP_20260811.md）

────────────────────────────────────────────
步骤 A：960×540 面板采集（对照门禁 1）
────────────────────────────────────────────
  A1 启动 KK 平台进入游戏，把游戏窗口调整为 960×540（窗口模式）。
     注意：不要用 1600×900 或 1920×1080 窗口缩放冒充；本工具会校验帧分辨率恰为 960×540。
  A2 打开录屏软件（OBS / Win+G 录制），或直接使用带 panel_sample 的构建
     （dist_release2\\GameScript\\*.exe 或后续 release）自动收集（见步骤 C）。
  A3 实机打局，确保每局至少出现 技能/羁绊/宝物 三类选择面板；
     每个面板停留 ≥2 秒（保证静止帧可用，参照 D0 的 panel episode 采样纪律）。
     目标：每类 ≥10 个面板 episode（不是 10 帧连拍，是 10 个独立面板）。
  A4 录制结束，把视频文件放入素材根目录（本工具会列出并记录 SHA/时长/分辨率）。
  A5 每类面板每 episode 抽取 1 帧主样本，保存到
       <root>\\960x540\\skill\\panel_<YYYYMMDD_HHMMSS>_<fp8>.png
       <root>\\960x540\\bond\\panel_...
       <root>\\960x540\\treasure\\panel_...
     （<fp8> 为内容指纹前 8 位；同一面板静止期的相邻帧不要重复入库）
  A6 不想手动抽帧时：把视频交给 D0 流程（panel episode 提取 + 分类标注，
     见 docs/baselines/D0_STATUS_20260811.md），分类结果同样落入上述 960x540\\<class>\\。

────────────────────────────────────────────
步骤 B：断线弹窗采集（对照门禁 2）
────────────────────────────────────────────
  B1 进入一局游戏（任意窗口分辨率均可，建议顺带用 960×540 窗口一石二鸟）。
  B2 制造断线（三选一）：
     - 直接拔网线 / 关闭 WiFi；
     - 关闭服务端 / 代理进程；
     - 推荐：用现成工具阻断游戏进程出站并自动抓屏检测
         .venv\\Scripts\\python.exe tools\\net_block.py watch --seconds 120 --out <root>\\disconnect
       需要管理员权限（防火墙规则）；结束后规则自动解除。
  B3 在断线弹窗完整出现时录制 / 截图 ≥1 帧（包含整窗，勿裁切按钮区）。
  B4 保存命名（必须含标识，与 SCENES.md 模板名 gameDisconnect / retryConnect 对应）：
       <root>\\disconnect\\gameDisconnect_<YYYYMMDD_HHMMSS>.png
       <root>\\disconnect\\retryConnect_<YYYYMMDD_HHMMSS>.png
  B5 恢复网络并确认弹窗可重连（retryConnect 帧记录重连按钮形态）。

────────────────────────────────────────────
步骤 C：panel episodes 自动收集（panel_sample）
────────────────────────────────────────────
  C1 使用带 panel_sample 的构建实机跑局；Mediator 在面板正常出现时旁路归档
     （无任何输入动作权，见 src/gamescript/incidents.py sample_panel）：
       %LocalAppData%\\GameScript-Local\\YYYYMMDD\\panels\\
       panel_<HHMMSS_mmm>_<fp8>.jpg  +  <同名>.json（kind=panel_sample，300s 指纹去重）
  C2 若以 960×540 窗口跑局，panels 帧即为真实 960×540 正样本；
     注意 panels 帧未分类（json 不含面板类型），计入门禁前需按类标注
     （抽取主样本落入 960x540\\<class>\\ 或走 D0 标注流程）。
  C3 本工具会按日目录统计：帧数 / 960×540 帧数 / SHA 样例 / 时间范围，
     session id = panel_sample_<YYYYMMDD>。

────────────────────────────────────────────
检查结果（素材到位检查表）
────────────────────────────────────────────
"""


# ---------------------------------------------------------------------------
# 检查表
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    root: Path
    videos: list[dict] = field(default_factory=list)
    classified: dict[str, list[ImageItem]] = field(default_factory=dict)
    skipped: dict[str, list[ImageItem]] = field(default_factory=dict)
    unknown_class: list[ImageItem] = field(default_factory=list)
    disconnect: dict = field(default_factory=dict)
    panel_days: list[dict] = field(default_factory=list)

    def per_class_counts(self) -> dict[str, int]:
        return {c: len(self.classified.get(c, [])) for c in PANEL_CLASSES}

    def gate_ready(self) -> bool:
        counts = self.per_class_counts()
        return all(counts[c] >= 10 for c in PANEL_CLASSES) and len(self.disconnect.get("named", [])) >= 1

    def to_dict(self) -> dict:
        def _img(i: ImageItem) -> dict:
            return {"path": i.path, "width": i.width, "height": i.height,
                    "sha256": i.sha256, "mtime": i.mtime, "session": i.session, "note": i.note}

        return {
            "root": str(self.root),
            "videos": self.videos,
            "classified_960x540": {c: [_img(i) for i in self.classified.get(c, [])] for c in PANEL_CLASSES},
            "skipped_frames": {c: [_img(i) for i in self.skipped.get(c, [])] for c in PANEL_CLASSES},
            "unknown_class_frames": [_img(i) for i in self.unknown_class],
            "disconnect_named": [_img(i) for i in self.disconnect.get("named", [])],
            "disconnect_unnamed": [_img(i) for i in self.disconnect.get("unnamed", [])],
            "panel_sample_days": self.panel_days,
            "gates": {
                "per_class_960x540_ge10": self.per_class_counts(),
                "disconnect_frames_ge1": len(self.disconnect.get("named", [])),
                "ready": self.gate_ready(),
            },
        }


def run_checks(root: Path, localappdata: Path, panels_days: int) -> CheckResult:
    res = CheckResult(root=root)
    res.videos = scan_videos(root)

    for cls in PANEL_CLASSES:
        accepted, skipped = scan_frame_dir(root / "960x540" / cls, f"960x540_{cls}", want=(960, 540))
        res.classified[cls] = accepted
        res.skipped[cls] = skipped
    res.unknown_class = scan_frame_dir(root / "960x540", "960x540_unknown")[0]
    res.disconnect = scan_disconnect(root)
    res.panel_days = scan_panel_days(localappdata, panels_days)
    return res


def _fmt_frame(i: ImageItem) -> str:
    return (f"      {i.path}\n"
            f"        res={i.width}x{i.height} sha={i.sha256} mtime={i.mtime} session={i.session}"
            + (f" {i.note}" if i.note else ""))


def render_checklist(res: CheckResult, panels_days: int) -> str:
    lines: list[str] = []
    counts = res.per_class_counts()
    disconnect_named = res.disconnect.get("named", [])
    lines.append(f"素材根目录: {res.root}   (--panels-days {panels_days})")
    lines.append("")
    lines.append("— 视频素材（录制会话；含分辨率，960×540 视频为有效采集会话）—")
    if res.videos:
        for v in res.videos:
            extra = f" {v['width']}x{v['height']} fps={v['fps']} frames={v['frames']}" if "width" in v else ""
            lines.append(f"  {v['path']}  [{v['size_bytes']}B] sha={v['sha256']} mtime={v['mtime']}{extra}")
            lines.append(f"    session 建议: {v['session_suggestion']}")
    else:
        lines.append("  （无视频。步骤 A4：把 960×540 录制放入素材根目录）")
    lines.append("")
    lines.append("— 960×540 分类面板帧（门禁 1：每类 ≥10；分辨率必须恰为 960×540）—")
    for cls in PANEL_CLASSES:
        items = res.classified[cls]
        ok = len(items) >= 10
        lines.append(f"  [{cls}] 帧数={len(items)}/10  {'达标' if ok else '缺口'}")
        for i in items:
            lines.append(_fmt_frame(i))
        skipped = res.skipped.get(cls, [])
        if skipped:
            lines.append(f"    非目标分辨率/不可读 {len(skipped)} 张（不计入门禁）: "
                         + ", ".join(f"{Path(i.path).name}({i.width}x{i.height})" for i in skipped[:5])
                         + (f" …另 {len(skipped) - 5} 张" if len(skipped) > 5 else ""))
    if res.unknown_class:
        lines.append(f"  960x540/ 下未分类帧（不计入门禁；需按类移入子目录）: {len(res.unknown_class)}")
    lines.append("")
    lines.append("— 断线弹窗帧（门禁 2：≥1 帧命名素材 gameDisconnect/retryConnect）—")
    if disconnect_named:
        for i in disconnect_named:
            lines.append(_fmt_frame(i))
    else:
        lines.append("  （缺。步骤 B：制造断线并保存命名帧）")
    unnamed = res.disconnect.get("unnamed", [])
    if unnamed:
        lines.append(f"  未命名帧 {len(unnamed)} 张（文件名缺 gameDisconnect/retryConnect 标识，需重命名）:")
        for i in unnamed[:5]:
            lines.append(_fmt_frame(i))
        if len(unnamed) > 5:
            lines.append(f"    …另 {len(unnamed) - 5} 张")
    lines.append("")
    lines.append("— panel episodes 自动收集（panel_sample）—")
    if res.panel_days:
        for d in res.panel_days:
            lines.append(f"  {d['session']}  {d['dir']}")
            lines.append(f"    帧数={d['frames']}  960×540帧={d['frames_960x540']}  "
                         f"范围={d['first']:%Y%m%d_%H%M%S}~{d['last']:%Y%m%d_%H%M%S}")
            for s in d["sha_samples"]:
                lines.append(f"    样例 {s}")
    else:
        lines.append(f"  （无。步骤 C1：用带 panel_sample 的构建实机跑局；"
                     f"检查 %LocalAppData%\\GameScript-Local\\YYYYMMDD\\panels\\）")
    lines.append("")
    lines.append("— 素材到位检查表（对照 O3 BLOCKED 项）—")
    lines.append("| 门禁 | 目标 | 当前 | 状态 |")
    lines.append("|---|---|---|---|")
    for cls in PANEL_CLASSES:
        lines.append(f"| 960×540 {cls} 面板 | ≥10 | {counts[cls]} | {'PASS' if counts[cls] >= 10 else 'GAP'} |")
    lines.append(f"| 断线弹窗命名帧 | ≥1 | {len(disconnect_named)} | "
                 f"{'PASS' if disconnect_named else 'GAP'} |")
    lines.append("")
    lines.append("结论: " + ("素材齐备，可解锁后续实机/离线评测。"
                            if res.gate_ready() else "素材未齐，保持 BLOCKED（与 O3 门禁一致）。"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def default_root() -> Path:
    env = os.environ.get("GSL_MATERIAL_ROOT")
    if env:
        return Path(env)
    return Path.home() / "Desktop" / "录屏素材"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true",
                   help="仅输出检查表并以退出码反映素材是否到位（0=齐，1=缺）")
    p.add_argument("--json", action="store_true", help="检查表以 JSON 输出")
    p.add_argument("--root", type=Path, default=None,
                   help="素材根目录（默认 GSL_MATERIAL_ROOT 或 <桌面>\\录屏素材）")
    p.add_argument("--panels-days", type=int, default=30,
                   help="panel_sample 自动收集目录回溯天数（默认 30）")
    args = p.parse_args(argv)

    root = args.root or default_root()
    localappdata = Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local"))

    if args.json:
        res = run_checks(root, localappdata, args.panels_days)
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
        if args.check:
            return 0 if res.gate_ready() else 1
        return 0

    print(GUIDE)
    res = run_checks(root, localappdata, args.panels_days)
    print(render_checklist(res, args.panels_days))
    if args.check:
        return 0 if res.gate_ready() else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
