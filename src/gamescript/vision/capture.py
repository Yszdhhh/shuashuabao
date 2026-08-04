"""截屏。支持双窗口策略：L0（KK对战平台房间）与 L1（英雄三国游戏窗口）。"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np

try:
    import mss
except ImportError:  # pragma: no cover
    mss = None  # type: ignore


@dataclass
class Frame:
    bgr: np.ndarray
    left: int = 0
    top: int = 0

    @property
    def width(self) -> int:
        return int(self.bgr.shape[1])

    @property
    def height(self) -> int:
        return int(self.bgr.shape[0])


# L0 大厅/房间阶段 — 窗口在 KK 对战平台
L0_WINDOW_KEYWORDS = ["kk官方", "kk对战", "kk竞技", "对战平台", "竞技平台", "kk", "魔兽", "warcraft", "英雄三国"]
# L1 局内阶段 — 窗口是英雄三国游戏进程
L1_WINDOW_KEYWORDS = ["英雄三国", "魔兽世界", "warcraft", "魔兽争霸", "kk"]
# 合并后的全量降级关键字（当用户未配置时使用）
DEFAULT_WINDOW_FALLBACKS = L0_WINDOW_KEYWORDS + L1_WINDOW_KEYWORDS


def list_active_window_titles() -> list[str]:
    """获取所有当前可见的独立窗口标题列表。仅 Windows。"""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        titles: list[str] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if title and len(title) > 1:
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 300 and h > 200:
                    titles.append(title)
            return True

        user32.EnumWindows(enum_proc, 0)
        return sorted(list(set(titles)))
    except Exception:
        return []


def _find_window_rect(title_contains: str) -> tuple[int, int, int, int] | None:
    """返回 (left, top, width, height)。仅 Windows。支持多关键字与模糊退让算法。"""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found: list[tuple[wintypes.HWND, int, int, int, int]] = []

        # 整理搜索关键字
        keywords = [k.strip().lower() for k in title_contains.replace("|", ",").replace("/", ",").split(",") if k.strip()]
        if not keywords:
            keywords = [k.lower() for k in DEFAULT_WINDOW_FALLBACKS]

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            win_title = buf.value.lower()
            if any(k in win_title for k in keywords):
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 200 and h > 200:
                    found.append((hwnd, rect.left, rect.top, w, h))
            return True

        user32.EnumWindows(enum_proc, 0)

        # 1. 尝试用户/多关键字匹配
        if found:
            hwnd, l, t, w, h = found[0]
            try:
                user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
            return (l, t, w, h)

        # 2. 匹配失败时，自动匹配常见平台降级关键字
        fallbacks = [k.lower() for k in DEFAULT_WINDOW_FALLBACKS]
        if keywords != fallbacks:
            keywords = fallbacks
            found.clear()
            user32.EnumWindows(enum_proc, 0)
            if found:
                hwnd, l, t, w, h = found[0]
                try:
                    user32.SetForegroundWindow(hwnd)
                except Exception:
                    pass
                return (l, t, w, h)

        return None
    except Exception:
        return None


def capture(title_contains: str = "") -> Frame:
    if mss is None:
        raise RuntimeError("mss not installed")
    rect = _find_window_rect(title_contains)
    left, top = 0, 0
    try:
        with mss.mss() as sct:
            if rect:
                left, top, w, h = rect
                mon = {"left": left, "top": top, "width": w, "height": h}
            else:
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                left, top = mon["left"], mon["top"]
            raw = np.array(sct.grab(mon))
            # BGRA -> BGR
            bgr = raw[:, :, :3].copy()
            return Frame(bgr=bgr, left=left, top=top)
    except Exception as e:
        print(f"[capture] screenshot exception fallback: {e}")
        # 返回默认 1600x900 黑色 Frame 作为安全退让，不造成崩溃
        dummy_bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
        return Frame(bgr=dummy_bgr, left=left, top=top)


