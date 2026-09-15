# -*- coding: utf-8 -*-
"""B6：pytest 不得写真实日志。

`shuabao.shell.main_window` 在模块加载时给共享的 "ShuaBao" logger 挂一个真实
`RotatingFileHandler`（指向 `%LOCALAPPDATA%\\ShuaBao\\logs\\ShuaBao.log`）。任何
后续经 `shuabao.log_sink` 打的印都会经同名 logger 落进这个真实文件——某些用
例 `patch("time.time", ...)` 冻结全局时钟到极小 epoch，写出的就是 1970 年
时间戳，污染了实机日志。

`tests/conftest.py` 必须在任何 `shuabao.*` 模块被导入前把 `SHUABAO_APP_DATA`
重定向到 tmp 目录；本测试证明：即便触发一次会打印的调用（且时钟被冻结到
1970 附近），真实 AppData 日志文件也不会被创建/修改。
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _real_appdata_log_path() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "ShuaBao" / "logs" / "ShuaBao.log"


def test_printing_through_the_shared_logger_never_touches_the_real_appdata_log() -> None:
    real_log = _real_appdata_log_path()
    before_exists = real_log.is_file()
    before_mtime = real_log.stat().st_mtime if before_exists else None

    # Importing main_window is what originally attached the real-file handler
    # to the shared "ShuaBao" logger at module load time.
    from shuabao.shell import main_window  # noqa: F401
    from shuabao.log_sink import emit_print

    with patch("time.time", return_value=100.0):
        emit_print("b6 regression: this print must never reach the real AppData log")
    after_exists = real_log.is_file()
    after_mtime = real_log.stat().st_mtime if after_exists else None
    assert after_exists == before_exists, "真实 AppData 日志文件被测试进程创建（B6 回归）"
    assert after_mtime == before_mtime, "真实 AppData 日志文件 mtime 被测试进程改动（B6 回归）"


def test_main_window_log_file_resolves_under_the_redirected_tmp_app_data() -> None:
    from shuabao.shell import main_window

    app_data = os.environ.get("SHUABAO_APP_DATA", "")
    assert app_data, "conftest 必须已设置 SHUABAO_APP_DATA"
    assert str(main_window.LOG_FILE).startswith(str(Path(app_data).resolve())), (
        f"main_window.LOG_FILE={main_window.LOG_FILE} 未落在重定向的 SHUABAO_APP_DATA={app_data} 下"
    )
