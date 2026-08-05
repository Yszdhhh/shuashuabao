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
    window_title: str = ""
    hwnd: int | None = None

    @property
    def width(self) -> int:
        return int(self.bgr.shape[1])

    @property
    def height(self) -> int:
        return int(self.bgr.shape[0])


# L0 大厅/房间阶段 — 窗口在 KK 对战平台
L0_WINDOW_KEYWORDS = ["kk官方", "kk对战", "kk竞技", "对战平台", "竞技平台", "kk"]
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


@dataclass(frozen=True)
class WindowTarget:
    hwnd: int
    title: str
    left: int
    top: int
    width: int
    height: int


def _window_title_score(title: str, role: str | None = None) -> int:
    """Score a title for the phase that requested the capture.

    Both the platform and the game can contain ``KK`` in their title.  A
    plain substring match therefore cannot choose a window safely.  Keep the
    role preference here, next to the Win32 enumeration, so callers never
    have to guess from the first matching HWND.
    """
    title = title.lower()
    role = (role or "").lower()
    platform = any(k in title for k in ("kk官方", "kk对战", "kk竞技", "对战平台", "竞技平台"))
    game = any(k in title for k in ("英雄三国", "魔兽世界", "魔兽争霸", "warcraft"))
    if role == "l0":
        return (80 if platform else 0) - (80 if game else 0)
    if role == "l1":
        return (80 if game else 0) - (80 if platform else 0)
    return 0


def _find_window_rect(title_contains: str, role: str | None = None) -> WindowTarget | None:
    """Return the scored window target for the requested title keywords."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found: list[tuple[wintypes.HWND, str, int, int, int, int]] = []

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
                    found.append((hwnd, win_title, rect.left, rect.top, w, h))
            return True

        user32.EnumWindows(enum_proc, 0)

        # 1. 尝试用户/多关键字匹配
        def choose(items: list[tuple[wintypes.HWND, str, int, int, int, int]]) -> WindowTarget:
            foreground = user32.GetForegroundWindow()
            if role in ("l0", "l1"):
                preferred = [item for item in items if _window_title_score(item[1], role) > 0]
                if preferred:
                    items = preferred
                else:
                    # Keep neutral custom titles usable, but never fall back
                    # from an L0 request to a known game window (or vice
                    # versa) just because it also contains "KK".
                    neutral = [item for item in items if _window_title_score(item[1], role) == 0]
                    items = neutral
                    if not items:
                        raise LookupError(f"no {role} window in matching titles")

            def rank(item):
                hwnd, title, _l, _t, w, h = item
                score = _window_title_score(title, role)
                if hwnd == foreground:
                    score += 20
                if "英雄三国kk" in title:
                    score += 40
                elif "kk" in title:
                    score += 10
                if "挂机助手" in title or "懒人系列" in title:
                    score -= 60
                score += min(15, (w * h) / 300000)
                return score

            hwnd, title, left, top, width, height = max(items, key=rank)
            return WindowTarget(int(hwnd), title, left, top, width, height)

        if found:
            target = choose(found)
            try:
                user32.SetForegroundWindow(target.hwnd)
            except Exception:
                pass
            return target

        # 2. 匹配失败时，自动匹配常见平台降级关键字
        fallbacks = [k.lower() for k in DEFAULT_WINDOW_FALLBACKS]
        if keywords != fallbacks:
            keywords = fallbacks
            found.clear()
            user32.EnumWindows(enum_proc, 0)
            if found:
                target = choose(found)
                try:
                    user32.SetForegroundWindow(target.hwnd)
                except Exception:
                    pass
                return target

        return None
    except Exception:
        return None


def capture(title_contains: str = "", role: str | None = None) -> Frame:
    if mss is None:
        raise RuntimeError("mss not installed")
    rect = _find_window_rect(title_contains, role=role)
    left, top = 0, 0
    if rect is None:
        # Strict L0/L1 safety rule: never fall back to a desktop screenshot.
        # A full-screen frame can match an unrelated blue button and cause an
        # absolute-coordinate click outside the game window.
        print(f"[capture] target window not found: {title_contains!r}")
        return Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))
    try:
        with mss.mss() as sct:
            left, top, w, h = rect.left, rect.top, rect.width, rect.height
            mon = {"left": left, "top": top, "width": w, "height": h}
            raw = np.array(sct.grab(mon))
            # BGRA -> BGR
            bgr = raw[:, :, :3].copy()
            return Frame(
                bgr=bgr,
                left=left,
                top=top,
                window_title=rect.title,
                hwnd=rect.hwnd,
            )
    except Exception as e:
        print(f"[capture] screenshot exception fallback: {e}")
        # 返回默认 1600x900 黑色 Frame 作为安全退让，不造成崩溃
        dummy_bgr = np.zeros((900, 1600, 3), dtype=np.uint8)
        return Frame(
            bgr=dummy_bgr,
            left=left,
            top=top,
            window_title=rect.title,
            hwnd=rect.hwnd,
        )


