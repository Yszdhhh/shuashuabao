#!/usr/bin/env python3
"""R0 实机素材采集工具（dry-run：只打印指引 + 目录检查，零输入动作）。

对应蓝图 §15 R0.1（1600×900 首发口径 + 断线素材缺口）与
docs/SCOPE_OVERRIDE_1600X900_20260811.md：
  - 每类（技能 skill / 羁绊 bond / 宝物 treasure）≥10 个独立面板 episode
    （游戏窗口 1600×900 采集；禁止把其他分辨率缩放成"真实 1600×900"）；
  - ≥1 帧真实断线弹窗帧（命名素材 gameDisconnect / retryConnect）；
  - 960×540 = NOT_APPLICABLE（游戏无该分辨率），不入计数、不采集、不缩放伪造。

去重与内容验证（SCOPE_OVERRIDE 即时指令第 4 条修复项）：
  - SHA256 去重：同内容帧（字节级相同）只计 1 次；
  - 感知哈希（pHash 64bit，DCT 低频）相邻去重：同一面板静止持续期的近重复
    帧合并为 1 个 episode；jitter 帧不单独计数；
  - 独立 episode 判定：同源目录内按文件名序 phash 聚类，记录每 episode 的
    start/end 帧与持续时长（idx 帧名 1fps 时 duration = 帧跨度秒数）；
  - 内容验证：面板 crop 区非空（灰度 std ≥ --content-std）＋ 文字/边缘像素
    （Canny ≥ --text-pixels），面板锚点区非纯背景 —— 不凭文件名解锁；
  - 非 1600×900 游戏窗帧明确排除（NOT_APPLICABLE 分辨率不入计数）。

本工具永不发送输入：不 import 生产运行时，不点击、不按键、不写任何文件。

用法：
  .venv\\Scripts\\python.exe tools/collect_machine_material.py            # 指引 + 素材到位检查表（exit 0）
  .venv\\Scripts\\python.exe tools/collect_machine_material.py --check    # exit 0=素材齐 / 1=缺素材
  .venv\\Scripts\\python.exe tools/collect_machine_material.py --json     # 检查表以 JSON 输出（含 episode 明细）
  .venv\\Scripts\\python.exe tools/collect_machine_material.py --root <dir> --panels-days 30
  .venv\\Scripts\\python.exe tools/collect_machine_material.py --want 1600x900 --tol-w 20 --tol-h 40 \\
      --phash-hd 10 --content-std 18.0 --text-pixels 500

素材目录约定（本工具文档化，配合 D0_SESSION_MAP_20260811.md / incidents.py）：
  素材根目录  GSL_MATERIAL_ROOT 或 --root，默认 C:\\Users\\<user>\\Desktop\\录屏素材
  1600×900 面板帧  <root>\\1600x900\\skill|bond|treasure\\panel_<YYYYMMDD_HHMMSS>_<fp8>.png
                   （每类一目录；每 panel episode 一帧主样本；窗口捕获分辨率须落在
                     want±--res-tolerance 内，默认 1600×900±20×40；1920×1080 全桌面
                     /960×540 等一律 NOT_APPLICABLE，不入计数）
  断线弹窗帧  <root>\\disconnect\\gameDisconnect_<ts>.png / retryConnect_<ts>.png
               （文件名必须含 gameDisconnect / retryConnect 标识，与 SCENES.md 模板名一致）
               （也可用 tools/net_block.py 自动阻断+抓屏：默认输出 C:\\tmp\\disconnect_captures）
  panel episodes（自动收集）  %LocalAppData%\\ShuaBao\\YYYYMMDD\\panels\\
               panel_<HHMMSS_mmm>_<fp8>.jpg + <同名>.json（kind=panel_sample，
               300s 内容指纹去重；Mediator 旁路归档，无输入动作权 —— src/gamescript/incidents.py）
  incidents（异常归档）       %LocalAppData%\\ShuaBao\\incidents\\YYYYMMDD\\incidents\\
  录屏/索引  C:\\tmp\\recordings\\（rec1-rec8 既有；idx_a/idx_b 为 1fps 索引帧目录，
               video_index_meta.json 记录 probe/sha256/frames）
  会话映射   视频 → rec<seq>_<内容>_<YYYYMMDD>（参照 D0_SESSION_MAP：idx_a→rec9_mijing_20260810、
              idx_b→rec10_3normal_20260810）；面板帧 → 1600x900_<YYYYMMDD>；
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

# 默认门禁参数（可 CLI 覆盖）
DEFAULT_WANT = (1600, 900)
DEFAULT_TOL_W = 20
DEFAULT_TOL_H = 40
DEFAULT_PHASH_HD = 10
DEFAULT_CONTENT_STD = 18.0
DEFAULT_TEXT_PIXELS = 500

# 960×540 明确 NOT_APPLICABLE（SCOPE_OVERRIDE_20260811：游戏无此分辨率）
NOT_APPLICABLE_960X540 = (960, 540)


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


def load_bgr(path: Path):
    """cv2 读图（BGR）；失败返回 None。仅用于 phash/内容验证。"""
    try:
        import cv2  # type: ignore

        data = path.read_bytes()
        return cv2.imdecode(np_frombuffer(data), cv2.IMREAD_COLOR)
    except Exception:
        return None


def np_frombuffer(data: bytes):
    import numpy as np  # type: ignore

    return np.frombuffer(data, dtype=np.uint8)


# ---------------------------------------------------------------------------
# 感知哈希（pHash 64bit，DCT 低频）＋ 内容验证
# ---------------------------------------------------------------------------


def phash_bits(bgr) -> int | None:
    """pHash 64bit：32x32 灰度 → DCT → 8x8 低频 vs 中位数 → 64 位。"""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        if bgr is None or bgr.size == 0:
            return None
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
        dct = cv2.dct(small)
        top = dct[:8, :8]
        med = float(np.median(top))
        bits = (top > med).astype(np.uint8).flatten()
        val = 0
        for b in bits:
            val = (val << 1) | int(b)
        return val
    except Exception:
        return None


def phash_hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def validate_panel_content(bgr, content_std: float, text_pixels: int) -> dict:
    """面板内容验证：crop 区非空（灰度 std）+ 文字/边缘像素（Canny）。

    面板锚点区 = 中央三选区域（x 0.24-0.76, y 0.16-0.66，与生产 _panel_roi_region
    同框）；纯背景/空 crop（std≈0、边缘≈0）判 invalid。不凭文件名解锁。
    返回 {valid, crop_std, edge_pixels, note}。"""
    try:
        import cv2  # type: ignore

        if bgr is None or bgr.size == 0:
            return {"valid": False, "crop_std": 0.0, "edge_pixels": 0, "note": "unreadable"}
        h, w = bgr.shape[:2]
        if w < 100 or h < 100:
            return {"valid": False, "crop_std": 0.0, "edge_pixels": 0, "note": "frame_too_small"}
        x1, y1 = int(w * 0.24), int(h * 0.16)
        x2, y2 = int(w * 0.76), int(h * 0.66)
        if x2 <= x1 or y2 <= y1:
            return {"valid": False, "crop_std": 0.0, "edge_pixels": 0, "note": "bad_crop_box"}
        crop = bgr[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        crop_std = float(gray.std())
        edges = cv2.Canny(gray, 50, 150)
        edge_pixels = int(cv2.countNonZero(edges))
        ok = crop_std >= content_std and edge_pixels >= text_pixels
        note = "valid" if ok else f"content_check_failed(std={crop_std:.1f}<{content_std} or edges={edge_pixels}<{text_pixels})"
        return {"valid": ok, "crop_std": round(crop_std, 2), "edge_pixels": edge_pixels, "note": note}
    except Exception:
        return {"valid": False, "crop_std": 0.0, "edge_pixels": 0, "note": "validate_error"}


def _natural_key(name: str):
    """文件名自然排序：数字段按数值比较（idx 帧名 000001 等）。"""
    parts = re.split(r"(\d+)", name)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


@dataclass
class ImageItem:
    path: str
    width: int
    height: int
    sha256: str
    mtime: str  # ISO
    session: str
    note: str = ""


@dataclass
class Episode:
    """独立面板 episode：同一面板静止持续期的 phash 聚类（SHA/pHash 去重后）。"""
    session: str
    kind: str
    source: str
    resolution: tuple[int, int]
    frames: list[ImageItem]
    start_frame: str
    end_frame: str
    frame_count: int
    n_distinct_sha: int
    duplicate_count: int
    duration_s: float | None
    phash: int | None
    content_valid: bool
    crop_std: float
    edge_pixels: int
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "session": self.session,
            "kind": self.kind,
            "source": self.source,
            "source_session": self.session,
            "resolution": [self.resolution[0], self.resolution[1]],
            "frame_range": [self.start_frame, self.end_frame],
            "frames": [f.path for f in self.frames],
            "sha256": self.frames[0].sha256,
            "sha_distinct": sorted({f.sha256 for f in self.frames}),
            "frame_count": self.frame_count,
            "n_distinct_sha": self.n_distinct_sha,
            "duplicate_count": self.duplicate_count,
            "duration_s": self.duration_s,
            "phash": hex(self.phash) if self.phash is not None else None,
            "content_valid": self.content_valid,
            "crop_std": self.crop_std,
            "edge_pixels": self.edge_pixels,
            "note": self.note,
        }


def _session_from_mtime(mtime: float, prefix: str) -> str:
    return f"{prefix}_{datetime.fromtimestamp(mtime).strftime('%Y%m%d')}"


def _duration_of(frames: list[ImageItem]) -> float | None:
    """episode 持续时长：idx 帧名（纯数字）时 = 末帧序号 - 首帧序号 + 1（1fps 即秒数）；
    非数字命名时按帧数（未知 fps）返回 None。"""
    nums = []
    for f in frames:
        m = re.fullmatch(r"(\d+)", Path(f.path).stem)
        if m:
            nums.append(int(m.group(1)))
    if len(nums) >= 2:
        return float(max(nums) - min(nums) + 1)
    return None


def scan_frame_dir(directory: Path, session_prefix: str, want: tuple[int, int],
                   tol_w: int, tol_h: int, phash_hd: int, content_std: float,
                   text_pixels: int) -> dict:
    """扫描一类目录：分辨率门禁 → SHA 去重 → phash 相邻聚类（episode）→ 内容验证。

    返回：
      {
        "accepted": [...ImageItem],          # 窗口分辨率（want±tol_w×tol_h）非重复帧
        "not_applicable": [...ImageItem],    # 非目标分辨率（含 960×540），明确不入计数
        "duplicates": [...ImageItem],        # SHA 相同（同内容）帧，折叠入其 episode
        "episodes": [...Episode],            # 去重后独立 episode（含内容验证）
        "validated_episode_count": int,      # 门禁计数 = 内容验证通过的 episode 数
      }
    """
    out: dict = {"accepted": [], "not_applicable": [], "duplicates": [], "episodes": [], "validated_episode_count": 0}
    if not directory.is_dir():
        return out
    items: list[ImageItem] = []
    for p in sorted(directory.iterdir(), key=lambda p: _natural_key(p.name)):
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        mtime = datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
        session = _session_from_mtime(p.stat().st_mtime, session_prefix)
        sha = sha256_hex(p)
        size = image_size(p)
        if size is None:
            out["not_applicable"].append(ImageItem(str(p), 0, 0, sha, mtime, session, "note=unreadable"))
            continue
        w, h = size
        in_window = abs(w - want[0]) <= tol_w and abs(h - want[1]) <= tol_h
        if not in_window:
            na_note = "note=not_applicable"
            if (w, h) == NOT_APPLICABLE_960X540:
                na_note = "note=not_applicable_960x540"
            out["not_applicable"].append(ImageItem(str(p), w, h, sha, mtime, session, na_note))
            continue
        items.append(ImageItem(str(p), w, h, sha, mtime, session))

    # SHA 去重：同内容（字节级）只保留一个；重复帧折叠计数
    unique: list[ImageItem] = []
    seen_sha: dict[str, int] = {}
    for it in items:
        if it.sha256 in seen_sha:
            seen_sha[it.sha256] += 1
            out["duplicates"].append(it)
        else:
            seen_sha[it.sha256] = 0
            unique.append(it)
    out["accepted"] = unique

    # phash 相邻聚类：同一面板静止持续期（含 jitter 近重复）合并为 1 episode
    episodes: list[Episode] = []
    for it in unique:
        bgr = load_bgr(Path(it.path))
        ph = phash_bits(bgr)
        if episodes and episodes[-1].phash is not None and ph is not None \
                and phash_hamming(episodes[-1].phash, ph) <= phash_hd:
            ep = episodes[-1]
            ep.frames.append(it)
            ep.n_distinct_sha = len({f.sha256 for f in ep.frames})
            ep.start_frame = Path(ep.frames[0].path).name
            ep.end_frame = Path(ep.frames[-1].path).name
            ep.frame_count = len(ep.frames)
            ep.duration_s = _duration_of(ep.frames)
            continue
        cv_ = validate_panel_content(bgr, content_std, text_pixels)
        episodes.append(Episode(
            session=it.session,
            kind=directory.name,
            source=str(directory),
            resolution=(it.width, it.height),
            frames=[it],
            start_frame=Path(it.path).name,
            end_frame=Path(it.path).name,
            frame_count=1,
            n_distinct_sha=1,
            duplicate_count=0,
            duration_s=_duration_of([it]),
            phash=ph,
            content_valid=bool(cv_["valid"]),
            crop_std=float(cv_["crop_std"]),
            edge_pixels=int(cv_["edge_pixels"]),
            note=str(cv_["note"]),
        ))

    # 折叠 SHA 重复帧计数到其所属 episode（同内容帧只计 1 的直接证据）
    for ep in episodes:
        ep.duplicate_count = sum(1 for d in out["duplicates"] if d.sha256 == ep.frames[0].sha256)

    out["episodes"] = episodes
    out["validated_episode_count"] = sum(1 for e in episodes if e.content_valid)
    return out


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


def scan_panel_days(localappdata: Path, days: int, want: tuple[int, int], tol_w: int, tol_h: int) -> list[dict]:
    """panel_sample 自动收集目录：%LocalAppData%\\ShuaBao\\YYYYMMDD\\panels\\。

    每个日目录 = 一个采集 session（panel_sample_<YYYYMMDD>）；记录 jpg 数、
    1600×900 窗口分辨率帧数（真实窗口证据，want±tol_w×tol_h）、SHA 样例与时间范围。"""
    base = localappdata / "ShuaBao"
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
        n_window = 0
        sha_samples: list[str] = []
        for p in jpgs:
            size = image_size(p)
            if size is not None and abs(size[0] - want[0]) <= tol_w and abs(size[1] - want[1]) <= tol_h:
                n_window += 1
            if len(sha_samples) < 3:
                sha_samples.append(f"{p.name}:{sha256_hex(p)}")
        out.append({
            "session": f"panel_sample_{day_dir.name}",
            "day": day_dir.name,
            "dir": str(panels),
            "frames": total,
            f"frames_{want[0]}x{want[1]}_tol{tol_w}x{tol_h}": n_window,
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
 对照门禁：docs/SCOPE_OVERRIDE_1600X900_20260811.md（1600×900 唯一首发分辨率）
============================================================

【素材目标】两条硬门禁缺口：
  1) 每类 ≥10 个独立面板 episode（真实 1600×900 游戏窗采集）
     （技能 skill / 羁绊 bond / 宝物 treasure；窗口捕获分辨率须落在
       1600×900±20×40 内，1920×1080 全桌面/960×540 等一律 NOT_APPLICABLE，
       禁止把其他分辨率缩放成"真实 1600×900"）
  2) ≥1 帧真实断线弹窗（命名素材 gameDisconnect / retryConnect）

【去重与内容验证（自动执行）】
  - SHA256 去重：字节级相同帧只计 1；
  - pHash 相邻去重：同一面板静止持续期（含 jitter 近重复）只计 1 个 episode；
  - 内容验证：面板 crop 区非空（灰度 std）+ 文字/边缘像素 ≥ 阈值；
    纯背景/空 crop 帧判 invalid，不凭文件名解锁计数。

【目录约定】
  素材根目录      GSL_MATERIAL_ROOT 或 --root（默认 <桌面>\\录屏素材）
  1600×900 帧     <root>\\1600x900\\skill|bond|treasure\\panel_<日期_时间>_<fp8>.png
  断线弹窗帧      <root>\\disconnect\\gameDisconnect_<时间戳>.png / retryConnect_<时间戳>.png
  panel episodes  %LocalAppData%\\ShuaBao\\YYYYMMDD\\panels\\（panel_sample 自动收集）
  incidents       %LocalAppData%\\ShuaBao\\incidents\\YYYYMMDD\\incidents\\
  每条素材记录 SHA256(16)/时间戳/分辨率/会话映射（会话 id 形如
  rec<seq>_<内容>_<YYYYMMDD>、1600x900_<YYYYMMDD>、panel_sample_<YYYYMMDD>、
  disconnect_<YYYYMMDD>；参照 docs/baselines/D0_SESSION_MAP_20260811.md）

────────────────────────────────────────────
步骤 A：1600×900 面板采集（对照门禁 1）
────────────────────────────────────────────
  A1 启动 KK 平台进入游戏，把游戏窗口调整为 1600×900（窗口模式）。
     注意：不要用 1920×1080/1366×768 等窗口缩放冒充；本工具会校验帧分辨率
     落在 1600×900±20×40 内。960×540 为 NOT_APPLICABLE（游戏无此分辨率），
     不采集、不缩放、不伪造。
  A2 打开录屏软件（OBS / Win+G 录制），或直接使用带 panel_sample 的构建
     （dist\\ShuaBao\\ShuaBao.exe 或后续 release）自动收集（见步骤 C）。
  A3 实机打局，确保每局至少出现 技能/羁绊/宝物 三类选择面板；
     每个面板停留 ≥2 秒（保证静止帧可用，参照 D0 的 panel episode 采样纪律）。
     目标：每类 ≥10 个独立面板 episode（不是 10 帧连拍，是 10 个独立面板）。
  A4 录制结束，把视频文件放入素材根目录（本工具会列出并记录 SHA/时长/分辨率）。
  A5 每类面板每 episode 抽取 1 帧主样本，保存到
       <root>\\1600x900\\skill\\panel_<YYYYMMDD_HHMMSS>_<fp8>.png
       <root>\\1600x900\\bond\\panel_...
       <root>\\1600x900\\treasure\\panel_...
     （<fp8> 为内容指纹前 8 位；同一面板静止期的相邻帧不要重复入库，
      重复帧会被 SHA/pHash 去重折叠，但仍建议每 episode 只放 1 帧主样本）
  A6 不想手动抽帧时：把视频交给 D0 流程（panel episode 提取 + 分类标注，
     见 docs/baselines/D0_STATUS_20260811.md），分类结果同样落入上述 1600x900\\<class>\\。

────────────────────────────────────────────
步骤 B：断线弹窗采集（对照门禁 2）
────────────────────────────────────────────
  B1 进入一局游戏（任意窗口分辨率均可，建议顺带用 1600×900 窗口一石二鸟）。
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
       %LocalAppData%\\ShuaBao\\YYYYMMDD\\panels\\
       panel_<HHMMSS_mmm>_<fp8>.jpg  +  <同名>.json（kind=panel_sample，300s 指纹去重）
  C2 若以 1600×900 窗口跑局，panels 帧即为真实 1600×900 正样本；
     注意 panels 帧未分类（json 不含面板类型），计入门禁前需按类标注
     （抽取主样本落入 1600x900\\<class>\\ 或走 D0 标注流程）。
  C3 本工具会按日目录统计：帧数 / 1600×900 窗口帧数 / SHA 样例 / 时间范围，
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
    want: tuple[int, int]
    tol_w: int
    tol_h: int
    phash_hd: int
    content_std: float
    text_pixels: int
    videos: list[dict] = field(default_factory=list)
    class_dirs: dict[str, dict] = field(default_factory=dict)  # 每类 scan_frame_dir 结果
    unknown_class: list[ImageItem] = field(default_factory=list)
    disconnect: dict = field(default_factory=dict)
    panel_days: list[dict] = field(default_factory=list)

    def per_class_episodes(self) -> dict[str, int]:
        return {c: self.class_dirs.get(c, {}).get("validated_episode_count", 0) for c in PANEL_CLASSES}

    def gate_ready(self) -> bool:
        counts = self.per_class_episodes()
        return all(counts[c] >= 10 for c in PANEL_CLASSES) and len(self.disconnect.get("named", [])) >= 1

    def to_dict(self) -> dict:
        def _img(i: ImageItem) -> dict:
            return {"path": i.path, "width": i.width, "height": i.height,
                    "sha256": i.sha256, "mtime": i.mtime, "session": i.session, "note": i.note}

        class_out: dict[str, dict] = {}
        for c in PANEL_CLASSES:
            d = self.class_dirs.get(c, {})
            class_out[c] = {
                "want_resolution": [self.want[0], self.want[1]],
                "res_tolerance": [self.tol_w, self.tol_h],
                "accepted_frames": [_img(i) for i in d.get("accepted", [])],
                "duplicate_frames": [_img(i) for i in d.get("duplicates", [])],
                "not_applicable_frames": [_img(i) for i in d.get("not_applicable", [])],
                "episodes": [e.to_dict() for e in d.get("episodes", [])],
                "validated_episode_count": d.get("validated_episode_count", 0),
            }
        return {
            "root": str(self.root),
            "want_resolution": [self.want[0], self.want[1]],
            "res_tolerance": [self.tol_w, self.tol_h],
            "phash_hamming_threshold": self.phash_hd,
            "content_std_threshold": self.content_std,
            "text_pixels_threshold": self.text_pixels,
            "videos": self.videos,
            "class_dirs": class_out,
            "unknown_class_frames": [_img(i) for i in self.unknown_class],
            "disconnect_named": [_img(i) for i in self.disconnect.get("named", [])],
            "disconnect_unnamed": [_img(i) for i in self.disconnect.get("unnamed", [])],
            "panel_sample_days": self.panel_days,
            "gates": {
                "per_class_1600x900_episodes_ge10": self.per_class_episodes(),
                "disconnect_frames_ge1": len(self.disconnect.get("named", [])),
                "ready": self.gate_ready(),
            },
        }


def run_checks(root: Path, localappdata: Path, panels_days: int,
               want: tuple[int, int], tol_w: int, tol_h: int, phash_hd: int,
               content_std: float, text_pixels: int) -> CheckResult:
    res = CheckResult(root=root, want=want, tol_w=tol_w, tol_h=tol_h, phash_hd=phash_hd,
                      content_std=content_std, text_pixels=text_pixels)
    res.videos = scan_videos(root)

    for cls in PANEL_CLASSES:
        res.class_dirs[cls] = scan_frame_dir(root / "1600x900" / cls, f"1600x900_{cls}",
                                             want, tol_w, tol_h, phash_hd, content_std, text_pixels)
    res.unknown_class = scan_frame_dir(root / "1600x900", "1600x900_unknown",
                                       want, tol_w, tol_h, phash_hd, content_std, text_pixels).get("accepted", [])
    res.disconnect = scan_disconnect(root)
    res.panel_days = scan_panel_days(localappdata, panels_days, want, tol_w, tol_h)
    return res


def _fmt_frame(i: ImageItem) -> str:
    return (f"      {i.path}\n"
            f"        res={i.width}x{i.height} sha={i.sha256} mtime={i.mtime} session={i.session}"
            + (f" {i.note}" if i.note else ""))


def render_checklist(res: CheckResult, panels_days: int) -> str:
    lines: list[str] = []
    counts = res.per_class_episodes()
    disconnect_named = res.disconnect.get("named", [])
    want = res.want
    lines.append(f"素材根目录: {res.root}   (--panels-days {panels_days})")
    lines.append(f"目标分辨率: {want[0]}x{want[1]} ±{res.tol_w}x{res.tol_h}px  "
                 f"(pHash hd≤{res.phash_hd} 合并 episode；内容验证 std≥{res.content_std} 且 "
                 f"边缘≥{res.text_pixels}px)")
    lines.append("")
    lines.append("— 视频素材（录制会话；含分辨率）—")
    if res.videos:
        for v in res.videos:
            extra = f" {v['width']}x{v['height']} fps={v['fps']} frames={v['frames']}" if "width" in v else ""
            lines.append(f"  {v['path']}  [{v['size_bytes']}B] sha={v['sha256']} mtime={v['mtime']}{extra}")
            lines.append(f"    session 建议: {v['session_suggestion']}")
    else:
        lines.append("  （无视频。步骤 A4：把 1600×900 录制放入素材根目录）")
    lines.append("")
    lines.append(f"— {want[0]}x{want[1]} 分类面板 episode（门禁 1：每类 ≥10；窗口捕获须在 ±{res.tol_w}x{res.tol_h}px 内）—")
    for cls in PANEL_CLASSES:
        d = res.class_dirs.get(cls, {})
        eps = d.get("episodes", [])
        ok = counts[cls] >= 10
        lines.append(f"  [{cls}] 有效 episode={counts[cls]}/10  {'达标' if ok else '缺口'}"
                     f"（SHA/重复帧折叠 {len(d.get('duplicates', []))}，总 episode {len(eps)}）")
        for e in eps:
            dur = f"dur={e.duration_s:.0f}s" if e.duration_s is not None else "dur=n/a"
            lines.append(f"      episode[{e.start_frame}..{e.end_frame}] res={e.resolution[0]}x{e.resolution[1]} "
                         f"frames={e.frame_count} sha={e.frames[0].sha256} {dur} "
                         f"valid={'YES' if e.content_valid else 'NO'} "
                         f"(std={e.crop_std:.1f} edges={e.edge_pixels}) {e.note}")
        na = d.get("not_applicable", [])
        if na:
            lines.append(f"    NOT_APPLICABLE 分辨率（不入计数）{len(na)} 张: "
                         + ", ".join(f"{Path(i.path).name}({i.width}x{i.height})" for i in na[:6])
                         + (f" …另 {len(na) - 6} 张" if len(na) > 6 else ""))
    if res.unknown_class:
        lines.append(f"  1600x900/ 下未分类帧（不计入门禁；需按类移入子目录）: {len(res.unknown_class)}")
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
            key = f"frames_{want[0]}x{want[1]}_tol{res.tol_w}x{res.tol_h}"
            lines.append(f"  {d['session']}  {d['dir']}")
            lines.append(f"    帧数={d['frames']}  窗口分辨率帧={d.get(key, 0)}  "
                         f"范围={d['first']:%Y%m%d_%H%M%S}~{d['last']:%Y%m%d_%H%M%S}")
            for s in d["sha_samples"]:
                lines.append(f"    样例 {s}")
    else:
        lines.append(f"  （无。步骤 C1：用带 panel_sample 的构建实机跑局；"
                     f"检查 %LocalAppData%\\ShuaBao\\YYYYMMDD\\panels\\）")
    lines.append("")
    lines.append("— 素材到位检查表（对照 SCOPE_OVERRIDE 1600×900 门禁）—")
    lines.append("| 门禁 | 目标 | 当前 | 状态 |")
    lines.append("|---|---|---|---|")
    for cls in PANEL_CLASSES:
        lines.append(f"| 1600×900 {cls} 面板 episode | ≥10 | {counts[cls]} | {'PASS' if counts[cls] >= 10 else 'GAP'} |")
    lines.append(f"| 断线弹窗命名帧 | ≥1 | {len(disconnect_named)} | "
                 f"{'PASS' if disconnect_named else 'GAP'} |")
    lines.append("")
    lines.append("结论: " + ("素材齐备，可解锁后续实机/离线评测。"
                            if res.gate_ready() else "素材未齐，保持 BLOCKED（与 SCOPE_OVERRIDE 门禁一致）。"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def default_root() -> Path:
    env = os.environ.get("GSL_MATERIAL_ROOT")
    if env:
        return Path(env)
    return Path.home() / "Desktop" / "录屏素材"


def parse_want(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d+)x(\d+)", text.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError(f"非法分辨率 '{text}'（应为 WxH，如 1600x900）")
    return (int(m.group(1)), int(m.group(2)))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true",
                   help="仅输出检查表并以退出码反映素材是否到位（0=齐，1=缺）")
    p.add_argument("--json", action="store_true", help="检查表以 JSON 输出")
    p.add_argument("--root", type=Path, default=None,
                   help="素材根目录（默认 GSL_MATERIAL_ROOT 或 <桌面>\\录屏素材）")
    p.add_argument("--panels-days", type=int, default=30,
                   help="panel_sample 自动收集目录回溯天数（默认 30）")
    p.add_argument("--want", type=parse_want, default=DEFAULT_WANT,
                   help="目标窗口分辨率 WxH（默认 1600x900）")
    p.add_argument("--tol-w", type=int, default=DEFAULT_TOL_W,
                   help="宽度容差 px（默认 20；窗口捕获边框差异）")
    p.add_argument("--tol-h", type=int, default=DEFAULT_TOL_H,
                   help="高度容差 px（默认 40；窗口捕获边框差异）")
    p.add_argument("--phash-hd", type=int, default=DEFAULT_PHASH_HD,
                   help="pHash 海明距离阈值（默认 10；≤阈值并入同一 episode）")
    p.add_argument("--content-std", type=float, default=DEFAULT_CONTENT_STD,
                   help="面板 crop 灰度 std 下限（默认 18.0；纯背景判 invalid）")
    p.add_argument("--text-pixels", type=int, default=DEFAULT_TEXT_PIXELS,
                   help="面板 crop Canny 边缘像素下限（默认 500；文字/图形证据）")
    args = p.parse_args(argv)

    root = args.root or default_root()
    localappdata = Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local"))

    if args.json:
        res = run_checks(root, localappdata, args.panels_days, args.want, args.tol_w, args.tol_h,
                         args.phash_hd, args.content_std, args.text_pixels)
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
        if args.check:
            return 0 if res.gate_ready() else 1
        return 0

    print(GUIDE)
    res = run_checks(root, localappdata, args.panels_days, args.want, args.tol_w, args.tol_h,
                     args.phash_hd, args.content_std, args.text_pixels)
    print(render_checklist(res, args.panels_days))
    if args.check:
        return 0 if res.gate_ready() else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
