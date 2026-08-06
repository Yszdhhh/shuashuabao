"""Window capture for the KK platform (L0) and game (L1) stages."""

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


# L0: KK platform/lobby/room. L1: the game window.
L0_WINDOW_KEYWORDS = ["KK官方", "KK对战", "KK竞技", "对战平台", "竞技平台", "KK"]
L1_WINDOW_KEYWORDS = ["英雄三国", "魔兽世界", "warcraft", "魔兽争霸", "KK"]
DEFAULT_WINDOW_FALLBACKS = L0_WINDOW_KEYWORDS + L1_WINDOW_KEYWORDS
# The local control panel contains the game name in its own title.  It must
# never be selected as the L1 game window, otherwise its blue controls can be
# mistaken for the in-game stage UI.
LOCAL_HELPER_WINDOW_KEYWORDS = ("挂机助手", "GameScript-Local", "本地版")


@dataclass(frozen=True)
class WindowTarget:
    hwnd: int
    title: str
    left: int
    top: int
    width: int
    height: int


def list_active_window_titles() -> list[str]:
    """Return visible, non-minimized top-level window titles on Windows."""
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
                if rect.right - rect.left > 300 and rect.bottom - rect.top > 200:
                    titles.append(title)
            return True

        user32.EnumWindows(enum_proc, 0)
        return sorted(set(titles))
    except Exception:
        return []


def _window_title_score(title: str, role: str | None = None) -> int:
    """Score a title for the requested platform/game role."""
    title = title.lower()
    role = (role or "").lower()
    platform = any(k.lower() in title for k in ("KK官方", "KK对战", "KK竞技", "对战平台", "竞技平台"))
    game = any(k.lower() in title for k in ("英雄三国", "魔兽世界", "魔兽争霸", "warcraft"))
    if role == "l0":
        return (80 if platform else 0) - (80 if game else 0)
    if role == "l1":
        return (80 if game else 0) - (80 if platform else 0)
    return 0


def is_local_helper_title(title: str) -> bool:
    """Return whether a title belongs to this project's control panel."""
    lowered = title.lower()
    return any(keyword.lower() in lowered for keyword in LOCAL_HELPER_WINDOW_KEYWORDS)


def _parse_window_keywords(title_contains: str) -> list[str]:
    keywords = [
        k.strip().lower()
        for k in title_contains.replace("|", ",").replace("/", ",").split(",")
        if k.strip()
    ]
    return keywords or [k.lower() for k in DEFAULT_WINDOW_FALLBACKS]


def find_window_targets(title_contains: str = "", role: str | None = None) -> list[WindowTarget]:
    """List all visible targets, ranked by role and foreground status.

    The platform shell and its room window can have the same title.  Returning
    all candidates lets the state machine inspect their pixels and select the
    one that actually contains the current scene anchor.
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        requested = _parse_window_keywords(title_contains)
        fallbacks = [k.lower() for k in DEFAULT_WINDOW_FALLBACKS]

        def collect(keywords: list[str]) -> list[WindowTarget]:
            found: list[WindowTarget] = []

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
                if not title or not any(k in title.lower() for k in keywords):
                    return True
                if role == "l1" and is_local_helper_title(title):
                    return True
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if width > 200 and height > 200:
                    found.append(WindowTarget(int(hwnd), title, rect.left, rect.top, width, height))
                return True

            user32.EnumWindows(enum_proc, 0)
            return found

        found = collect(requested)
        if not found and requested != fallbacks:
            found = collect(fallbacks)

        if role in ("l0", "l1"):
            preferred = [target for target in found if _window_title_score(target.title, role) > 0]
            if preferred:
                found = preferred
            else:
                # Never use a known opposite-role window just because it also
                # contains the broad "KK" fallback keyword.
                found = [target for target in found if _window_title_score(target.title, role) == 0]

        foreground = int(user32.GetForegroundWindow())

        def rank(target: WindowTarget) -> float:
            score = _window_title_score(target.title, role)
            if target.hwnd == foreground:
                score += 20
            title = target.title.lower()
            if "英雄三国kk" in title:
                score += 40
            elif "kk" in title:
                score += 10
            if "挂机助手" in title or "懒人系列" in title:
                score -= 60
            return score + min(15, (target.width * target.height) / 300000)

        return sorted(found, key=rank, reverse=True)
    except Exception:
        return []


def activate_window(hwnd: int | None) -> bool:
    """Bring a target forward only immediately before a real input action."""
    if not hwnd:
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:
        return False


def _foreground_window() -> int | None:
    try:
        import ctypes

        hwnd = int(ctypes.windll.user32.GetForegroundWindow())
        return hwnd or None
    except Exception:
        return None


def _capture_print_window(target: WindowTarget) -> Frame | None:
    """Capture a covered Win32 window without reading the desktop behind it.

    MSS reads visible screen pixels, so a browser covering KK would otherwise
    be returned as if it were the game.  Pillow's Windows ImageGrab uses the
    window capture path (PrintWindow) and works for the KK Chromium window.
    If a renderer does not implement that path, callers can safely fall back
    to MSS or to a no-match frame.
    """
    try:
        from PIL import ImageGrab

        try:
            image = ImageGrab.grab(window=target.hwnd, include_layered_windows=True)
        except TypeError:  # Pillow versions without the optional keyword.
            image = ImageGrab.grab(window=target.hwnd)
        rgb = np.asarray(image)
        if rgb.ndim != 3 or rgb.shape[0] < 4 or rgb.shape[1] < 4:
            return None
        if rgb.shape[2] >= 4:
            rgb = rgb[:, :, :3]
        bgr = rgb[:, :, ::-1].copy()
        # ImageGrab may omit a 1px non-client border.  Keep click coordinates
        # aligned with the captured pixels rather than the larger window rect.
        left = target.left + max(0, (target.width - bgr.shape[1]) // 2)
        top = target.top + max(0, (target.height - bgr.shape[0]) // 2)
        return Frame(
            bgr=bgr,
            left=left,
            top=top,
            window_title=target.title,
            hwnd=target.hwnd,
        )
    except Exception:
        return None


def _find_window_rect(
    title_contains: str,
    role: str | None = None,
    activate: bool = True,
) -> WindowTarget | None:
    """Return the highest-ranked target, optionally activating it."""
    targets = find_window_targets(title_contains, role=role)
    if not targets:
        return None
    target = targets[0]
    if activate:
        activate_window(target.hwnd)
    return target


def capture_target(target: WindowTarget, activate: bool = False) -> Frame:
    """Capture one visible target without falling back to the desktop."""
    if mss is None:
        raise RuntimeError("mss not installed")
    if activate:
        activate_window(target.hwnd)
    elif _foreground_window() != target.hwnd:
        # Prefer an off-screen window capture.  Falling straight back to MSS
        # here can read Chrome/ChatGPT and create false scene matches.
        offscreen = _capture_print_window(target)
        if offscreen is not None:
            return offscreen
    try:
        with mss.mss() as sct:
            mon = {
                "left": target.left,
                "top": target.top,
                "width": target.width,
                "height": target.height,
            }
            raw = np.array(sct.grab(mon))
            return Frame(
                bgr=raw[:, :, :3].copy(),  # BGRA -> BGR
                left=target.left,
                top=target.top,
                window_title=target.title,
                hwnd=target.hwnd,
            )
    except Exception as e:
        print(f"[capture] screenshot exception fallback: {e}")
        return Frame(
            bgr=np.zeros((900, 1600, 3), dtype=np.uint8),
            left=target.left,
            top=target.top,
            window_title=target.title,
            hwnd=target.hwnd,
        )


def capture(title_contains: str = "", role: str | None = None, activate: bool = True) -> Frame:
    if mss is None:
        raise RuntimeError("mss not installed")
    target = _find_window_rect(title_contains, role=role, activate=False)
    if target is None:
        # A desktop screenshot is unsafe: it can match an unrelated button and
        # produce an absolute-coordinate click outside the game window.
        print(f"[capture] target window not found: {title_contains!r}")
        return Frame(bgr=np.zeros((900, 1600, 3), dtype=np.uint8))
    return capture_target(target, activate=activate)
