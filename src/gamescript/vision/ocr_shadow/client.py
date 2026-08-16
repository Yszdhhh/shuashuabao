"""Parent-side process manager and cache for OCR shadow predictions."""

from __future__ import annotations

import base64
import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .protocol import (
    ShadowCandidate,
    ShadowResponse,
    decode_response,
    encode_request,
    panel_fingerprint,
)


class ShadowClient:
    """One persistent, sequential JSONL sidecar for a process/session."""

    def __init__(
        self,
        *,
        repo_root: str | Path | None = None,
        python_executable: str | Path | None = None,
        model_dir: str | Path | None = None,
        timeout_ms: int = 400,
        startup_timeout_ms: int = 6000,
        max_restarts: int = 3,
        restart_cooldown_s: float = 2.0,
        trace_path: str | Path | None = None,
        worker_command: Iterable[str] | None = None,
    ) -> None:
        self.repo_root = Path(
            repo_root
            or os.environ.get("GAMESCRIPT_OCR_REPO_ROOT", "")
            or Path(__file__).resolve().parents[4]
        )
        self.model_dir = Path(
            model_dir
            or os.environ.get("GAMESCRIPT_OCR_MODEL_DIR", "")
            or self.repo_root / "models" / "ocr"
        )
        self.python_executable = _resolve_ocr_python(
            self.repo_root, python_executable
        )
        self.timeout_ms = max(1, int(timeout_ms))
        self.startup_timeout_ms = max(self.timeout_ms, int(startup_timeout_ms))
        self.max_restarts = max(0, int(max_restarts))
        self.restart_cooldown_s = max(0.0, float(restart_cooldown_s))
        self.trace_path = Path(trace_path) if trace_path else None
        self.worker_command = list(worker_command) if worker_command else None
        self._proc: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str] = queue.Queue()
        self._stderr_chunks: list[str] = []
        self._reader: threading.Thread | None = None
        self._err_reader: threading.Thread | None = None
        self._lock = threading.RLock()
        self._seq = 0
        self._crashes = 0
        self._disabled = False
        self._cooldown_until = 0.0
        self._ready = False
        self._ready_reason: str | None = None
        self._load_ms = 0.0
        self._model_validated = False
        self._announced = False
        self._cache: dict[str, tuple[str, dict[str, ShadowResponse]]] = {}
        self._max_cache_panels = 256
        self._trace_lock = threading.Lock()
        print(
            f"[ocr] configured worker={' '.join(self._command())} "
            f"model_dir={self.model_dir} python={self.python_executable} "
            f"python_exists={Path(self.python_executable).is_file()}",
            flush=True,
        )

    @property
    def disabled(self) -> bool:
        return self._disabled and time.monotonic() < self._cooldown_until

    @property
    def process(self) -> subprocess.Popen[str] | None:
        return self._proc

    def _command(self) -> list[str]:
        if self.worker_command is not None:
            return list(self.worker_command)
        return [self.python_executable, "-m", "gamescript.vision.ocr_shadow.worker"]

    def _spawn(self) -> bool:
        self._maybe_rearm()
        if self._disabled and time.monotonic() < self._cooldown_until:
            return False
        command = self._command()
        env = os.environ.copy()
        src = str(self.repo_root / "src")
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        env["GAMESCRIPT_OCR_MODEL_DIR"] = str(self.model_dir)
        env["GAMESCRIPT_OCR_REPO_ROOT"] = str(self.repo_root)
        exe = command[0] if command else ""
        if exe and not Path(exe).is_file() and self.worker_command is None:
            self._note_spawn_failure(
                "spawn",
                command,
                detail=f"python missing: {exe}",
            )
            self._record_crash("spawn")
            return False
        self._stderr_chunks = []
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(self.repo_root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
            )
        except (OSError, ValueError) as exc:
            self._note_spawn_failure("spawn", command, detail=str(exc))
            self._record_crash("spawn")
            return False
        self._proc = proc
        self._lines = queue.Queue()
        self._ready = False
        self._reader = threading.Thread(target=self._read_lines, args=(proc,), daemon=True)
        self._reader.start()
        self._err_reader = threading.Thread(
            target=self._read_stderr, args=(proc,), daemon=True
        )
        self._err_reader.start()
        self._await_ready(self.startup_timeout_ms / 1000)
        if not self._ready:
            err = self._stderr_text()
            reason = "ready_timeout"
            if proc.poll() not in (None, 0):
                reason = "spawn"
            self._ready_reason = reason
            self._note_spawn_failure(reason, command, detail=err or "worker produced no ready line")
            self._record_crash(reason)
            self._terminate()
            return False
        self._announce(ready=True, command=command)
        return True

    def _await_ready(self, timeout_s: float) -> bool:
        if self._ready:
            return True
        try:
            raw = self._lines.get(timeout=max(0.0, timeout_s))
            ready = decode_response(raw)
            if ready.get("seq") != 0 or ready.get("type") not in {"ready", None}:
                raise ValueError("invalid worker ready response")
            self._ready_reason = ready.get("reason")
            self._load_ms = float(ready.get("load_ms", 0.0) or 0.0)
            self._model_validated = bool(ready.get("model_validated", False))
            self._ready = True
            return True
        except (queue.Empty, ValueError, json.JSONDecodeError):
            return False

    def _read_lines(self, proc: subprocess.Popen[str]) -> None:
        stream = proc.stdout
        if stream is None:
            return
        try:
            for line in stream:
                self._lines.put(line.rstrip("\r\n"))
        finally:
            self._lines.put("")

    def _read_stderr(self, proc: subprocess.Popen[str]) -> None:
        stream = proc.stderr
        if stream is None:
            return
        try:
            for line in stream:
                text = line.rstrip("\r\n")
                if text:
                    self._stderr_chunks.append(text)
                    if len(self._stderr_chunks) > 40:
                        del self._stderr_chunks[:-40]
        except OSError:
            return

    def _stderr_text(self) -> str:
        return "\n".join(self._stderr_chunks[-20:])

    def _maybe_rearm(self) -> None:
        if not self._disabled:
            return
        if time.monotonic() < self._cooldown_until:
            return
        self._disabled = False
        self._crashes = 0
        if self._ready_reason in {"spawn", "ready_timeout", "disabled"}:
            self._ready_reason = None

    def _record_crash(self, reason: str) -> None:
        self._ready_reason = reason
        self._crashes += 1
        if self._crashes >= self.max_restarts:
            # Skip this frame / a short cooldown, then allow another spawn wave.
            self._disabled = True
            self._cooldown_until = time.monotonic() + self.restart_cooldown_s

    def _announce(self, *, ready: bool, command: list[str], detail: str = "") -> None:
        if self._announced:
            return
        self._announced = True
        reason = self._ready_reason or ("ok" if ready else "unknown")
        line = (
            f"[ocr] worker={' '.join(command)} model_dir={self.model_dir} "
            f"ready={ready} reason={reason}"
        )
        if detail:
            line = f"{line} detail={detail[:400]}"
        print(line, flush=True)
        self._write_lifecycle(
            {
                "event": "ocr_worker",
                "command": command,
                "python_executable": self.python_executable,
                "model_dir": str(self.model_dir),
                "repo_root": str(self.repo_root),
                "ready": ready,
                "reason": reason,
                "detail": detail[:800],
            }
        )

    def _note_spawn_failure(self, reason: str, command: list[str], *, detail: str) -> None:
        self._ready_reason = reason
        self._announce(ready=False, command=command, detail=detail)
        print(f"[ocr] spawn failed reason={reason} {detail[:400]}", flush=True)
        self._write_lifecycle(
            {
                "event": "ocr_spawn_failure",
                "command": command,
                "python_executable": self.python_executable,
                "model_dir": str(self.model_dir),
                "repo_root": str(self.repo_root),
                "ready": False,
                "reason": reason,
                "detail": detail[:800],
                "stderr": self._stderr_text()[:800],
            }
        )

    def _terminate(self) -> None:
        proc, self._proc = self._proc, None
        self._ready = False
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass

    def close(self) -> None:
        with self._lock:
            self._terminate()

    def reset(self) -> None:
        with self._lock:
            self._terminate()
            self._disabled = False
            self._cooldown_until = 0.0
            self._crashes = 0
            self._ready_reason = None
            self._load_ms = 0.0
            self._model_validated = False
            self._announced = False
            self._cache.clear()

    def _ensure_process(self) -> bool:
        self._maybe_rearm()
        if self._disabled and time.monotonic() < self._cooldown_until:
            return False
        if self._proc is not None and self._proc.poll() is None:
            if self._ready or self._await_ready(0.0):
                return True
            self._terminate()
            self._record_crash("ready_timeout")
            self._maybe_rearm()
            if self._disabled and time.monotonic() < self._cooldown_until:
                return False
        else:
            self._terminate()
        return self._spawn()

    def ping(self, timeout_ms: int | None = None) -> bool:
        with self._lock:
            if not self._ensure_process() or self._proc is None or self._proc.stdin is None:
                return False
            seq = self._next_seq()
            request = {"type": "ping", "seq": seq, "sent_at": time.time()}
            try:
                self._proc.stdin.write(encode_request(request) + "\n")
                self._proc.stdin.flush()
                response = self._read_response(seq, timeout_ms)
                if response is not None and response.status == "ok":
                    self._crashes = 0
                return response is not None and response.status == "ok"
            except (OSError, ValueError):
                self._terminate()
                self._record_crash("ping")
                return False

    def shadow_predict(
        self,
        frame: Any,
        panel_id: str,
        slot: Any,
        *,
        session: str | None = None,
        fingerprint: str | None = None,
        panel_bbox: tuple[int, int, int, int] | list[int] | None = None,
    ) -> ShadowResponse:
        """Return candidates only; this method never performs an input action."""
        started = time.perf_counter()
        slot_id, bbox, kind = _slot_fields(slot)
        seq = self._next_seq()
        fp = fingerprint or panel_fingerprint(frame, panel_bbox)
        cache_key = _cache_key(slot_id, bbox, kind)
        with self._lock:
            panel_cache = self._cache.get(panel_id)
            if panel_cache is None or panel_cache[0] != fp:
                if panel_cache is None and len(self._cache) >= self._max_cache_panels:
                    self._cache.pop(next(iter(self._cache)))
                panel_cache = (fp, {})
                self._cache[panel_id] = panel_cache
            cached = panel_cache[1].get(cache_key)
            if cached is not None:
                response = ShadowResponse(
                    seq=seq, status=cached.status, candidates=cached.candidates,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    reason=cached.reason, cache_hit=True,
                    raw_text=cached.raw_text, rec_score=cached.rec_score,
                )
                self._write_trace(response, session, panel_id, slot_id, bbox, fp, True)
                return response
            self._maybe_rearm()
            if self._disabled and time.monotonic() < self._cooldown_until:
                response = ShadowResponse.unavailable(seq, "disabled", (time.perf_counter() - started) * 1000)
                self._write_trace(response, session, panel_id, slot_id, bbox, fp, False)
                return response
            image_b64 = _frame_crop_b64(frame, bbox)
            if image_b64 is None:
                response = ShadowResponse.unavailable(seq, "bad_frame", (time.perf_counter() - started) * 1000)
                self._write_trace(response, session, panel_id, slot_id, bbox, fp, False)
                return response
            if not self._ensure_process() or self._proc is None or self._proc.stdin is None:
                response = ShadowResponse.unavailable(seq, self._ready_reason or "crash", (time.perf_counter() - started) * 1000)
                self._write_trace(response, session, panel_id, slot_id, bbox, fp, False)
                return response
            request = {
                "type": "predict",
                "seq": seq,
                "frame_ref": fp,
                "session": session or "",
                "panel_id": panel_id,
                "slot_id": slot_id,
                "id": f"{panel_id}:{slot_id}",
                "bbox": list(bbox),
                "kind": kind,
                "image_b64": image_b64,
                "sent_at": time.time(),
            }
            try:
                self._proc.stdin.write(encode_request(request) + "\n")
                self._proc.stdin.flush()
                response = self._read_response(seq, self.timeout_ms)
            except (OSError, ValueError):
                response = None
            if response is None:
                # Kill on timeout/protocol failure so a late line cannot shift the
                # next request.  The next call performs a bounded fresh restart.
                self._terminate()
                self._record_crash("timeout_or_protocol")
                reason = "timeout" if (time.perf_counter() - started) * 1000 >= self.timeout_ms else "protocol"
                response = ShadowResponse.unavailable(seq, reason, (time.perf_counter() - started) * 1000)
            else:
                elapsed = (time.perf_counter() - started) * 1000
                response = ShadowResponse(
                    seq=seq, status=response.status, candidates=response.candidates,
                    elapsed_ms=elapsed, reason=response.reason,
                    raw_text=response.raw_text, rec_score=response.rec_score,
                )
                if response.status == "ok":
                    self._crashes = 0
                    panel_cache[1][cache_key] = response
            self._write_trace(response, session, panel_id, slot_id, bbox, fp, False)
            return response

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _read_response(self, seq: int, timeout_ms: int | None) -> ShadowResponse | None:
        deadline = time.monotonic() + (max(1, timeout_ms or self.timeout_ms) / 1000)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                raw = self._lines.get(timeout=remaining)
            except queue.Empty:
                return None
            if raw == "":
                return None
            try:
                data = decode_response(raw)
            except (ValueError, json.JSONDecodeError):
                return None
            if data.get("seq") != seq:
                continue
            candidates = tuple(
                ShadowCandidate(str(c["name"]), float(c["confidence"]))
                for c in data.get("candidates", [])
            )
            return ShadowResponse(
                seq=seq,
                status=str(data["status"]),
                candidates=candidates,
                elapsed_ms=float(data.get("elapsed_ms", 0.0)),
                reason=data.get("reason"),
                raw_text=data.get("raw_text"),
                rec_score=(
                    float(data["rec_score"])
                    if isinstance(data.get("rec_score"), (int, float))
                    else None
                ),
            )

    def _write_trace(
        self,
        response: ShadowResponse,
        session: str | None,
        panel_id: str,
        slot_id: int,
        bbox: tuple[int, int, int, int],
        fingerprint: str,
        cache_hit: bool,
    ) -> None:
        if self.trace_path is None:
            return
        event = {
            "ts": time.time(),
            "session": session or "",
            "panel_id": panel_id,
            "slot_id": slot_id,
            "bbox": list(bbox),
            "panel_fingerprint": fingerprint,
            "status": response.status,
            "candidates": [c.as_dict() for c in response.candidates],
            "raw_text": response.raw_text,
            "rec_score": response.rec_score,
            "elapsed_ms": round(response.elapsed_ms, 3),
            "cache_hit": cache_hit,
        }
        if response.reason:
            event["reason"] = response.reason
        try:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self._trace_lock, self.trace_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def _write_lifecycle(self, event: dict[str, Any]) -> None:
        if self.trace_path is None:
            return
        payload = {"ts": time.time(), **event}
        try:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self._trace_lock, self.trace_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            pass


def _resolve_ocr_python(
    repo_root: Path, python_executable: str | Path | None
) -> str:
    """Pick a real python.exe. InfraB often has no .venv-ocr; don't silently FileNotFound."""
    candidates: list[Path] = []
    if python_executable:
        candidates.append(Path(python_executable))
    env_py = os.environ.get("GAMESCRIPT_OCR_PYTHON", "").strip()
    if env_py:
        candidates.append(Path(env_py))
    candidates.append(repo_root / ".venv-ocr" / "Scripts" / "python.exe")
    for parent in (repo_root.parent, repo_root.parent.parent):
        candidates.append(parent / "GameScript-Local" / ".venv-ocr" / "Scripts" / "python.exe")
        candidates.append(
            parent / "🎮 影音游戏" / "GameScript-Local" / ".venv-ocr" / "Scripts" / "python.exe"
        )
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if path.is_file():
                return str(path)
        except OSError:
            continue
    return str(candidates[0] if candidates else repo_root / ".venv-ocr" / "Scripts" / "python.exe")


def _slot_fields(slot: Any) -> tuple[int, tuple[int, int, int, int], str | None]:
    if isinstance(slot, dict):
        slot_id = slot.get("slot_id", slot.get("id", slot.get("index", 0)))
        bbox = slot.get("bbox")
        kind = slot.get("kind")
    else:
        slot_id = getattr(slot, "slot_id", getattr(slot, "id", getattr(slot, "index", 0)))
        bbox = getattr(slot, "bbox", None)
        kind = getattr(slot, "kind", None)
    if bbox is None or len(bbox) != 4:
        raise ValueError("slot requires bbox=(x0,y0,x1,y1)")
    x0, y0, x1, y1 = (int(v) for v in bbox)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("slot bbox must have positive area")
    return int(slot_id), (x0, y0, x1, y1), str(kind) if kind else None


def _cache_key(slot_id: int, bbox: tuple[int, int, int, int], kind: str | None) -> str:
    return json.dumps([slot_id, *bbox, kind], separators=(",", ":"))


def _frame_crop_b64(frame: Any, bbox: tuple[int, int, int, int]) -> str | None:
    value = getattr(frame, "bgr", frame)
    try:
        if hasattr(value, "shape"):
            h, w = int(value.shape[0]), int(value.shape[1])
            x0, y0, x1, y1 = bbox
            if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
                return None
            crop = value[y0:y1, x0:x1]
            import cv2
            ok, encoded = cv2.imencode(".png", crop)
            return base64.b64encode(encoded.tobytes()).decode("ascii") if ok else None
        if isinstance(value, (str, Path)):
            data = Path(value).read_bytes()
        elif isinstance(value, (bytes, bytearray, memoryview)):
            data = bytes(value)
        else:
            # PIL-like objects are encoded without importing PIL in the parent.
            if hasattr(value, "save"):
                buf = io.BytesIO()
                value.save(buf, format="PNG")
                data = buf.getvalue()
            else:
                return None
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return None
        x0, y0, x1, y1 = bbox
        if not (0 <= x0 < x1 <= image.shape[1] and 0 <= y0 < y1 <= image.shape[0]):
            return None
        ok, encoded = cv2.imencode(".png", image[y0:y1, x0:x1])
        return base64.b64encode(encoded.tobytes()).decode("ascii") if ok else None
    except (OSError, ValueError, TypeError, ImportError):
        return None


_default_client: ShadowClient | None = None
_default_lock = threading.Lock()


def shadow_predict(frame: Any, panel_id: str, slot: Any, **kwargs: Any) -> ShadowResponse:
    """Convenience facade used by the integration wave.

    A single lazy client keeps the sidecar persistent.  Pass ``client=`` in
    kwargs for tests or explicit lifecycle ownership.
    """
    client = kwargs.pop("client", None)
    global _default_client
    if client is None:
        with _default_lock:
            if _default_client is None:
                _default_client = ShadowClient()
            client = _default_client
    return client.shadow_predict(frame, panel_id, slot, **kwargs)
