"""LIVE 日志事件总线。替代对 builtins.print 的全局覆盖。"""

from __future__ import annotations

import builtins
import logging
import threading
from collections.abc import Callable
from pathlib import Path

LOGGER = logging.getLogger("ShuaBao")

KindFn = Callable[[str, str], None]


class LogEventSink(logging.Handler):
    """stdlib Handler + 订阅列表。emit 时先拷贝订阅者再回调，避免持锁重入死锁。"""

    def __init__(self) -> None:
        super().__init__()
        self._sub_lock = threading.Lock()
        self._subs: list[KindFn] = []
        self.setFormatter(logging.Formatter("%(message)s"))

    def subscribe(self, fn: KindFn) -> None:
        with self._sub_lock:
            self._subs.append(fn)

    def unsubscribe(self, fn: KindFn) -> None:
        with self._sub_lock:
            try:
                self._subs.remove(fn)
            except ValueError:
                return

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self, "_emitting", False):
            return
        self._emitting = True
        try:
            try:
                text = self.format(record)
            except Exception:
                text = record.getMessage()
            if record.levelno >= logging.ERROR:
                kind = "error"
            elif record.levelno >= logging.WARNING:
                kind = "warn"
            else:
                kind = "info"
            with self._sub_lock:
                subs = list(self._subs)
            for fn in subs:
                try:
                    fn(text, kind)
                except Exception:
                    continue
        finally:
            self._emitting = False

    def publish(self, text: str, kind: str = "info") -> None:
        level = {
            "error": logging.ERROR,
            "warn": logging.WARNING,
            "warning": logging.WARNING,
        }.get(kind, logging.INFO)
        LOGGER.log(level, text)


def emit_print(*args: object, **kwargs: object) -> None:
    """Mediator 模块级 print：先打到 ShuaBao logger，再走真正的 builtins.print。"""
    text = " ".join(str(x) for x in args)
    if text:
        lowered = text.lower()
        if (
            "失败" in text
            or "中断" in text
            or "错误" in text
            or "timeout" in lowered
            or "fatal" in lowered
        ):
            LOGGER.error(text)
        elif "警告" in text or "miss" in lowered:
            LOGGER.warning(text)
        else:
            LOGGER.info(text)
    builtins.print(*args, **kwargs)


def install_live_logging(
    *,
    log: KindFn | None,
    log_file: Path | None,
) -> tuple[LogEventSink, logging.Handler | None]:
    for existing in list(LOGGER.handlers):
        if isinstance(existing, LogEventSink):
            LOGGER.removeHandler(existing)
    sink = LogEventSink()
    if log is not None:
        sink.subscribe(log)
    LOGGER.setLevel(logging.INFO)
    LOGGER.addHandler(sink)
    file_handler: logging.Handler | None = None
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        LOGGER.addHandler(file_handler)
    return sink, file_handler


def uninstall_live_logging(
    sink: LogEventSink,
    file_handler: logging.Handler | None,
) -> None:
    LOGGER.removeHandler(sink)
    if file_handler is not None:
        LOGGER.removeHandler(file_handler)
        try:
            file_handler.close()
        except Exception:
            pass
