"""B1-2 未知页面/未知选择自动归档（蓝图 §7 B1-2）。

IncidentArchiver 把"未知/异常"事件证据落到本地目录，供离线回放复现：

    <root>/YYYYMMDD/incidents/incident_<时间戳>_<指纹前8位>/
        metadata.json       事件元数据（phase/hwnd/尺寸/分数/候选动作/最终处理）
        frame_before.jpg    触发前一帧全帧
        frame_now.jpg       触发帧全帧
        frame_after.jpg     触发后第一健康帧（由 attach_frame_after 补齐）
        roi_<label>.png     相关 ROI 裁剪（调用方在 metadata["rois"] 给出，可选）

安全约束（蓝图 §3）：
- 本模块不产生任何输入动作、不参与决策，只是旁路证据。
- 黑帧/错误窗口由调用方传 healthy=False；此类 incident 统一记为
  health_error，绝不标成 unknown_page（黑帧不是"游戏未知页"）。
- 帧指纹：全帧 BGR → 32x18 缩略 → aHash 位串 → MD5；同指纹静态页面
  dedup_seconds（默认 60s）内最多保存一组。
- 容量上限 max_bytes（默认 2GB）、保留期 retention_days（默认 7 天）；
  清理只删除本模块创建的 incident_* 目录，不触碰官方日志/用户录像。
- 线程安全：Mediator 在 worker 线程调用，内部用 RLock 保护共享状态。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

_THUMB_W = 32
_THUMB_H = 18

_DEFAULT_MAX_BYTES = 2 * 1024 ** 3
_DEFAULT_RETENTION_DAYS = 7
_DEFAULT_DEDUP_SECONDS = 60.0
_INCIDENT_PREFIX = "incident_"


def default_incident_dir() -> Path:
    """生产入口（桌面/API/CLI）构造 Mediator 时使用的默认 incident 目录。

    S0.5：`%LocalAppData%/ShuaBao/incidents`；测试必须传临时目录，
    生产入口一律经本函数，避免三处入口各自硬编码路径漂移。
    `SHUABAO_APP_DATA` 与 Desktop MainWindow / HeadlessRunner 共用同一根。

    2026-08-12 改名（GameScript-Local → ShuaBao）：旧目录里的历史 incident
    不会自动迁移，需要考古时去 `%LocalAppData%/GameScript-Local` 找。
    2026-08-25 起路径统一由 shuabao.paths 提供（唯一规范路径源）。
    """
    from shuabao.paths import incidents_dir

    return incidents_dir()


class IncidentArchiver:
    """未知页面/未知选择事件证据归档器（线程安全）。"""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        retention_days: int = _DEFAULT_RETENTION_DAYS,
        dedup_seconds: float = _DEFAULT_DEDUP_SECONDS,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        """root 为可注入的基目录（测试用临时目录）；默认 %LocalAppData%/ShuaBao。

        incident 落在 <root>/YYYYMMDD/incidents/ 下，按天分目录。
        """
        if root is None:
            root = default_incident_dir()
        self.root = Path(root)
        self.max_bytes = int(max_bytes)
        self.retention_days = int(retention_days)
        self.dedup_seconds = float(dedup_seconds)
        self._now = now_fn or time.time
        self._lock = threading.RLock()
        # 指纹 → 最近保存时间（去重窗口）
        self._last_saved: dict[str, float] = {}
        # 指纹 → (incident 目录, 创建时间)；等待 attach_frame_after 补齐
        self._pending_after: dict[str, tuple[Path, float]] = {}

    # ------------------------------------------------------------------
    # 帧指纹
    # ------------------------------------------------------------------

    @staticmethod
    def _thumb_hash(bgr: np.ndarray | None) -> str | None:
        """全帧 BGR → 32x18 缩略（INTER_AREA）→ 灰度 aHash 位串 → MD5 hex。

        相同静态页面（含不同分辨率缩放后内容一致）得到同一指纹；
        用于 60 秒去重与 metadata 回溯。
        """
        if bgr is None or bgr.ndim != 3 or bgr.size == 0:
            return None
        try:
            small = cv2.resize(bgr, (_THUMB_W, _THUMB_H), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        except cv2.error:
            return None
        bits = (gray > float(gray.mean())).astype(np.uint8).tobytes()
        return hashlib.md5(bits).hexdigest()

    def fingerprint(self, frame) -> str | None:
        """对外暴露的帧指纹；None 表示帧无效（无可归档内容）。"""
        if frame is None:
            return None
        return self._thumb_hash(getattr(frame, "bgr", None))

    # ------------------------------------------------------------------
    # 事件记录
    # ------------------------------------------------------------------

    def maybe_record(
        self,
        *,
        frame_before=None,
        frame_now=None,
        frame_after=None,
        metadata: dict | None = None,
        healthy: bool = True,
        health_issues: list[str] | None = None,
        health_details: str = "",
    ) -> str | None:
        """尝试归档一组 incident；返回帧指纹（新建）或 None（去重/无有效帧）。

        metadata 由调用方提供（至少）：kind / phase / hwnd / size / score /
        candidate_actions / final_action / reason；rois（帧内坐标，可选）为
        [{"label", "x", "y", "w", "h"}]。frame_after 触发瞬间不存在时传 None，
        之后用 attach_frame_after() 补齐。
        """
        if frame_now is None:
            return None
        fp = self._thumb_hash(getattr(frame_now, "bgr", None))
        if fp is None:
            return None
        meta = dict(metadata or {})
        kind = str(meta.get("kind") or "unknown")
        if not healthy and kind == "unknown_page":
            # 黑帧/错误窗口不是"游戏未知页"：保留调用方原意，统一记成 health_error
            meta["reported_kind"] = kind
            kind = "health_error"
        meta["kind"] = kind
        with self._lock:
            now = self._now()
            last = self._last_saved.get(fp)
            if last is not None and now - last < self.dedup_seconds:
                return None
            incident_dir = self._new_incident_dir(now, fp)
            self._write_group(
                incident_dir, fp, frame_before, frame_now, frame_after,
                meta, healthy, list(health_issues or []), health_details, now,
            )
            self._last_saved[fp] = now
            self._prune_dedup(now)
            if frame_after is None:
                self._pending_after[fp] = (incident_dir, now)
            self._enforce_limits(now, keep=incident_dir)
        return fp

    def attach_frame_after(self, fingerprint: str | None, frame) -> bool:
        """把触发后的下一帧画面补进 incident 组（frame_after 补齐）。

        返回 True 表示已补齐（调用方应清除待补状态）；False 表示没有
        待补的组或帧无效。
        """
        if not fingerprint or frame is None:
            return False
        bgr = getattr(frame, "bgr", None)
        if bgr is None or bgr.size == 0:
            return False
        with self._lock:
            pending = self._pending_after.pop(fingerprint, None)
            if pending is None:
                return False
            incident_dir, _ = pending
            img_name = "frame_after.jpg"
            self._save_jpg(incident_dir / img_name, bgr)
            meta_path = incident_dir / "metadata.json"
            if meta_path.is_file():
                try:
                    row = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    row = {}
                row["frame_after"] = img_name
                row["frame_after_info"] = {
                    "hwnd": getattr(frame, "hwnd", None),
                    "window_title": getattr(frame, "window_title", ""),
                    "size": [getattr(frame, "width", 0), getattr(frame, "height", 0)],
                    "fingerprint": self._thumb_hash(bgr),
                }
                meta_path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def sample_panel(
        self,
        frame,
        metadata: dict | None = None,
        *,
        dedup_seconds: float = 300.0,
    ) -> str | None:
        """轻量"正常选择面板"抽样归档（B2 数据集收集用，非异常 incident）。

        与 maybe_record 的区别：只在面板正常出现时记录全帧 + 少量元数据，
        不存 before/after/ROI；独立去重窗口（默认 300 秒，按内容指纹），
        同一静态面板不会反复落盘。kind 强制为 "panel_sample"。
        无任何输入动作权，只是旁路证据（蓝图 §3）。
        """
        if frame is None:
            return None
        bgr = getattr(frame, "bgr", None)
        fp = self._thumb_hash(bgr)
        if fp is None:
            return None
        with self._lock:
            now = self._now()
            last = self._last_saved.get(fp)
            if last is not None and now - last < dedup_seconds:
                return None
            day = datetime.fromtimestamp(now).strftime("%Y%m%d")
            stamp = datetime.fromtimestamp(now).strftime("%H%M%S_%f")[:-3]
            out_dir = self.root / day / "panels"
            out_dir.mkdir(parents=True, exist_ok=True)
            img_name = f"panel_{stamp}_{fp[:8]}.jpg"
            self._save_jpg(out_dir / img_name, bgr)
            meta = dict(metadata or {})
            meta.update({
                "kind": "panel_sample",
                "fingerprint": fp,
                "saved_at": datetime.fromtimestamp(now).isoformat(timespec="milliseconds"),
                "frame": img_name,
                "hwnd": getattr(frame, "hwnd", None),
                "window_title": getattr(frame, "window_title", ""),
                "size": [getattr(frame, "width", 0), getattr(frame, "height", 0)],
            })
            (out_dir / f"{Path(img_name).stem}.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            self._last_saved[fp] = now
            self._prune_dedup(now)
            self._enforce_limits(now, keep=None)
        return fp

    def cleanup(self) -> None:
        """按保留期/容量上限清理过期 incident（幂等，随时可调）。"""
        with self._lock:
            self._enforce_limits(self._now())

    # ------------------------------------------------------------------
    # 落盘
    # ------------------------------------------------------------------

    def _new_incident_dir(self, now: float, fp: str) -> Path:
        day = datetime.fromtimestamp(now).strftime("%Y%m%d")
        stamp = datetime.fromtimestamp(now).strftime("%H%M%S_%f")[:-3]
        base = self.root / day / "incidents"
        path = base / f"{_INCIDENT_PREFIX}{stamp}_{fp[:8]}"
        if path.exists():
            for i in range(2, 100):
                candidate = base / f"{_INCIDENT_PREFIX}{stamp}_{fp[:8]}_{i}"
                if not candidate.exists():
                    path = candidate
                    break
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_group(
        self,
        incident_dir: Path,
        fp: str,
        frame_before,
        frame_now,
        frame_after,
        meta: dict,
        healthy: bool,
        health_issues: list[str],
        health_details: str,
        now: float,
    ) -> None:
        bgr_now = getattr(frame_now, "bgr", None)
        before_name = None
        bgr_before = getattr(frame_before, "bgr", None) if frame_before is not None else None
        if bgr_before is not None and bgr_before.size > 0:
            before_name = "frame_before.jpg"
            self._save_jpg(incident_dir / before_name, bgr_before)
        now_name = None
        if bgr_now is not None and bgr_now.size > 0:
            now_name = "frame_now.jpg"
            self._save_jpg(incident_dir / now_name, bgr_now)
        after_name = None
        bgr_after = getattr(frame_after, "bgr", None) if frame_after is not None else None
        if bgr_after is not None and bgr_after.size > 0:
            after_name = "frame_after.jpg"
            self._save_jpg(incident_dir / after_name, bgr_after)
        roi_entries = self._write_rois(incident_dir, bgr_now, meta.get("rois") or [])
        row: dict = {
            "schema": "incident/v1",
            "incident_id": incident_dir.name,
            "kind": meta.get("kind"),
            "phase": meta.get("phase"),
            "hwnd": meta.get("hwnd"),
            "window_title": meta.get("window_title"),
            "size": meta.get("size")
            or (
                [getattr(frame_now, "width", 0), getattr(frame_now, "height", 0)]
                if frame_now is not None
                else None
            ),
            "score": meta.get("score"),
            "candidate_actions": meta.get("candidate_actions"),
            "final_action": meta.get("final_action"),
            "reason": meta.get("reason"),
            "frame_fingerprint": fp,
            "health": {"healthy": bool(healthy), "issues": health_issues, "details": health_details},
            "frame_before": before_name,
            "frame_now": now_name,
            "frame_after": after_name,
            "rois": roi_entries,
            "created_at": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
            "created_epoch": now,
        }
        for key, value in meta.items():
            if key not in row or row[key] is None:
                row[key] = value
        (incident_dir / "metadata.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_rois(self, incident_dir: Path, bgr_now: np.ndarray | None, rois: list) -> list[dict]:
        """裁剪相关 ROI 为 png；坐标按帧内（client）坐标，越界自动裁剪。"""
        entries: list[dict] = []
        if bgr_now is None or bgr_now.size == 0:
            return entries
        frame_h, frame_w = bgr_now.shape[:2]
        for roi in rois:
            label = "".join(c for c in str(roi.get("label") or "roi") if c.isalnum() or c in "-_") or "roi"
            x, y = int(roi.get("x", 0)), int(roi.get("y", 0))
            w, h = int(roi.get("w", 0)), int(roi.get("h", 0))
            if w <= 0 or h <= 0:
                continue
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(frame_w, x + w), min(frame_h, y + h)
            if x1 <= x0 or y1 <= y0:
                continue
            ok, buf = cv2.imencode(".png", bgr_now[y0:y1, x0:x1])
            if not ok:
                continue
            roi_name = f"roi_{label}.png"
            (incident_dir / roi_name).write_bytes(buf.tobytes())
            entries.append({"label": label, "file": roi_name, "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
        return entries

    @staticmethod
    def _save_jpg(path: Path, bgr: np.ndarray) -> None:
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if ok:
            path.write_bytes(buf.tobytes())

    # ------------------------------------------------------------------
    # 去重 / 容量 / 保留期
    # ------------------------------------------------------------------

    def _prune_dedup(self, now: float) -> None:
        cutoff = now - max(self.dedup_seconds * 2, 120.0)
        self._last_saved = {fp: t for fp, t in self._last_saved.items() if t >= cutoff}
        self._pending_after = {fp: v for fp, v in self._pending_after.items() if v[1] >= cutoff}

    def _enforce_limits(self, now: float, keep: Path | None = None) -> None:
        """保留期 + 容量上限。

        只扫描 <root>/YYYYMMDD/incidents/ 下的 incident_* 目录（本模块唯一
        创建路径）并删除过期/最旧目录；绝不触碰官方日志、用户录像等其它文件。
        keep 为刚写入的 incident 目录（容量超标时也不删当次证据）。
        """
        retention_sec = self.retention_days * 86400
        dirs: list[tuple[float, Path]] = []
        total = 0
        if self.root.is_dir():
            for day in sorted(self.root.iterdir()):
                if not day.is_dir() or len(day.name) != 8 or not day.name.isdigit():
                    continue
                incidents_dir = day / "incidents"
                if not incidents_dir.is_dir():
                    continue
                for entry in incidents_dir.iterdir():
                    if not entry.is_dir() or not entry.name.startswith(_INCIDENT_PREFIX):
                        continue
                    if keep is not None and entry == keep:
                        continue
                    try:
                        mtime = entry.stat().st_mtime
                    except OSError:
                        continue
                    if mtime < now - retention_sec:
                        self._rmtree(entry)
                        continue
                    size = self._dir_size(entry)
                    total += size
                    dirs.append((mtime, entry))
        if total > self.max_bytes:
            for _, entry in sorted(dirs):  # 最旧先删
                if total <= self.max_bytes:
                    break
                size = self._dir_size(entry)
                self._rmtree(entry)
                total -= size

    @staticmethod
    def _dir_size(entry: Path) -> int:
        return sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())

    @staticmethod
    def _rmtree(entry: Path) -> None:
        """删除 incident_* 目录；名称不符（非本模块创建）则不删。"""
        if entry.is_dir() and entry.name.startswith(_INCIDENT_PREFIX):
            shutil.rmtree(entry, ignore_errors=True)
