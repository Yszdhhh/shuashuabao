"""Window capture for the KK platform (L0) and game (L1) stages with health checks and verifiable identity."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
import time

import numpy as np

try:
    import mss
except ImportError:  # pragma: no cover
    mss = None  # type: ignore


@dataclass
class Frame:
    bgr: np.ndarray
    left: int = 0  # Client area screen X position
    top: int = 0   # Client area screen Y position
    window_title: str = ""
    hwnd: int | None = None
    timestamp: float = field(default_factory=time.time)
    is_valid: bool = True
    error: str | None = None
    role: str | None = None

    @property
    def width(self) -> int:
        if self.bgr is None or self.bgr.ndim < 2:
            return 0
        return int(self.bgr.shape[1])

    @property
    def height(self) -> int:
        if self.bgr is None or self.bgr.ndim < 2:
            return 0
        return int(self.bgr.shape[0])


class FrameHealthIssue(Enum):
    CAPTURE_FAILED = "capture_failed"
    MINIMIZED = "minimized"
    BLACK_FRAME = "black_frame"
    LOW_ENTROPY = "low_entropy"
    FROZEN = "frozen"
    OLD_FRAME = "old_frame"


@dataclass
class FrameHealthResult:
    is_healthy: bool
    issues: list[FrameHealthIssue] = field(default_factory=list)
    details: str = ""


# L0: KK platform/lobby/room. L1: the game window.
L0_WINDOW_KEYWORDS = ["KK官方", "KK对战", "KK竞技", "对战平台", "竞技平台", "KK"]
L1_WINDOW_KEYWORDS = ["英雄三国", "魔兽世界", "warcraft", "魔兽争霸", "single player", "single", "troubl", "KK"]
DEFAULT_WINDOW_FALLBACKS = L0_WINDOW_KEYWORDS + L1_WINDOW_KEYWORDS
# The local control panel contains the game name in its own title. It must
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
    pid: int = 0
    exe: str = ""
    class_name: str = ""
    role: str = ""
    client_left: int = 0
    client_top: int = 0
    client_width: int = 0
    client_height: int = 0


# ---------- Win32 API Helpers (Mockable) ----------

def get_window_class_name(hwnd: int) -> str:
    """Return window class name using Win32 API."""
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        return buf.value.strip()
    except Exception:
        return ""


def get_window_process_info(hwnd: int) -> tuple[int, str]:
    """Return (PID, EXE_Name) for a window handle."""
    try:
        import ctypes
        from ctypes import wintypes

        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pid_val = int(pid.value)
        exe_name = ""
        if pid_val > 0:
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h_proc = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid_val)
            if h_proc:
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if ctypes.windll.kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
                        exe_path = buf.value
                        exe_name = exe_path.split("\\")[-1]
                finally:
                    ctypes.windll.kernel32.CloseHandle(h_proc)
        return pid_val, exe_name
    except Exception:
        return 0, ""


def get_client_rect_info(hwnd: int, window_left: int, window_top: int, window_width: int, window_height: int) -> tuple[int, int, int, int]:
    """Return (client_left, client_top, client_width, client_height) in screen coordinates."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        pt = POINT(0, 0)
        if user32.ClientToScreen(hwnd, ctypes.byref(pt)):
            c_left = int(pt.x)
            c_top = int(pt.y)
        else:
            c_left, c_top = window_left, window_top

        rect = wintypes.RECT()
        if user32.GetClientRect(hwnd, ctypes.byref(rect)):
            c_width = int(rect.right - rect.left)
            c_height = int(rect.bottom - rect.top)
        else:
            c_width, c_height = window_width, window_height

        return c_left, c_top, c_width, c_height
    except Exception:
        return window_left, window_top, window_width, window_height


def client_to_screen(hwnd: int | None, client_x: int, client_y: int, client_origin: tuple[int, int] | None = None) -> tuple[int, int]:
    """Convert client-relative coordinate (x, y) to screen coordinate."""
    if client_origin is not None:
        return client_origin[0] + client_x, client_origin[1] + client_y
    if hwnd:
        try:
            import ctypes
            from ctypes import wintypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            pt = POINT(client_x, client_y)
            if ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt)):
                return int(pt.x), int(pt.y)
        except Exception:
            pass
    return client_x, client_y


def screen_to_client(hwnd: int | None, screen_x: int, screen_y: int, client_origin: tuple[int, int] | None = None) -> tuple[int, int]:
    """Convert screen coordinate (x, y) to client-relative coordinate."""
    if client_origin is not None:
        return screen_x - client_origin[0], screen_y - client_origin[1]
    if hwnd:
        try:
            import ctypes
            from ctypes import wintypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            pt = POINT(screen_x, screen_y)
            if ctypes.windll.user32.ScreenToClient(hwnd, ctypes.byref(pt)):
                return int(pt.x), int(pt.y)
        except Exception:
            pass
    return screen_x, screen_y


def is_window_minimized(hwnd: int | None) -> bool:
    """Return whether window is iconic / minimized."""
    if not hwnd:
        return False
    try:
        import ctypes

        return bool(ctypes.windll.user32.IsIconic(hwnd))
    except Exception:
        return False


def is_window_valid(hwnd: int | None) -> bool:
    """Return whether HWND is a valid visible window."""
    if not hwnd:
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return bool(user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd))
    except Exception:
        return False


def check_frame_health(
    frame: Frame,
    prev_frame: Frame | None = None,
    max_age_sec: float = 5.0,
    frozen_threshold_sec: float = 5.0,
) -> FrameHealthResult:
    """Perform health checks on a Frame: capture failure, minimized, black, low entropy, frozen, old."""
    issues: list[FrameHealthIssue] = []

    # 1. Capture failure
    if not frame.is_valid or frame.bgr is None or frame.bgr.size == 0 or frame.width <= 0 or frame.height <= 0:
        issues.append(FrameHealthIssue.CAPTURE_FAILED)
        return FrameHealthResult(is_healthy=False, issues=issues, details=frame.error or "Capture failed or invalid frame")

    # 2. Minimized window
    if frame.hwnd and is_window_minimized(frame.hwnd):
        issues.append(FrameHealthIssue.MINIMIZED)

    # 3. Old frame
    now = time.time()
    if frame.timestamp > 0 and (now - frame.timestamp) > max_age_sec:
        issues.append(FrameHealthIssue.OLD_FRAME)

    # 4. Black frame (all black or average pixel intensity near zero)
    mean_val = float(np.mean(frame.bgr))
    max_val = float(np.max(frame.bgr))
    if mean_val < 2.0 or max_val <= 1.0:
        issues.append(FrameHealthIssue.BLACK_FRAME)

    # 5. Low entropy / single color frame
    std_val = float(np.std(frame.bgr))
    if std_val < 1.0:
        issues.append(FrameHealthIssue.LOW_ENTROPY)

    # 6. Frozen frame (identical content across captures over frozen_threshold_sec)
    if prev_frame is not None and prev_frame.is_valid and prev_frame.bgr is not None:
        if prev_frame.bgr.shape == frame.bgr.shape:
            time_diff = abs(frame.timestamp - prev_frame.timestamp)
            if time_diff >= frozen_threshold_sec and np.array_equal(frame.bgr, prev_frame.bgr):
                issues.append(FrameHealthIssue.FROZEN)

    is_healthy = len(issues) == 0
    details = f"Issues: {[i.value for i in issues]}" if issues else "Healthy"
    return FrameHealthResult(is_healthy=is_healthy, issues=issues, details=details)


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


def find_window_targets(
    title_contains: str = "",
    role: str | None = None,
    allow_fallback: bool = False,
) -> list[WindowTarget]:
    """List all visible targets, ranked by role and foreground status."""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        has_user_keywords = bool(title_contains and title_contains.strip())
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
                    hwnd_val = int(hwnd)
                    class_name = get_window_class_name(hwnd_val)
                    pid, exe = get_window_process_info(hwnd_val)
                    c_left, c_top, c_width, c_height = get_client_rect_info(
                        hwnd_val, rect.left, rect.top, width, height
                    )
                    found.append(
                        WindowTarget(
                            hwnd=hwnd_val,
                            title=title,
                            left=rect.left,
                            top=rect.top,
                            width=width,
                            height=height,
                            pid=pid,
                            exe=exe,
                            class_name=class_name,
                            role=role or "",
                            client_left=c_left,
                            client_top=c_top,
                            client_width=c_width,
                            client_height=c_height,
                        )
                    )
                return True

            user32.EnumWindows(enum_proc, 0)
            return found

        found = collect(requested)
        # Fail-closed: only fallback if explicitly requested or if title_contains was omitted/empty.
        if not found and (allow_fallback or not has_user_keywords):
            found = collect(fallbacks)

        if role in ("l0", "l1"):
            preferred = [target for target in found if _window_title_score(target.title, role) > 0]
            if preferred:
                found = preferred
            else:
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
        user32.BringWindowToTop(hwnd)
        user32.keybd_event(0x12, 0, 0, 0)
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x12, 0, 2, 0)
        return int(user32.GetForegroundWindow()) == hwnd
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
    """Capture a covered Win32 window without reading the desktop behind it."""
    try:
        from PIL import ImageGrab

        try:
            image = ImageGrab.grab(window=target.hwnd, include_layered_windows=True)
        except TypeError:
            image = ImageGrab.grab(window=target.hwnd)
        rgb = np.asarray(image)
        if rgb.ndim != 3 or rgb.shape[0] < 4 or rgb.shape[1] < 4:
            return None
        if rgb.shape[2] >= 4:
            rgb = rgb[:, :, :3]
        bgr = rgb[:, :, ::-1].copy()
        left = target.client_left if target.client_left > 0 else target.left + max(0, (target.width - bgr.shape[1]) // 2)
        top = target.client_top if target.client_top > 0 else target.top + max(0, (target.height - bgr.shape[0]) // 2)
        return Frame(
            bgr=bgr,
            left=left,
            top=top,
            window_title=target.title,
            hwnd=target.hwnd,
            role=target.role,
            is_valid=True,
        )
    except Exception:
        return None


def _find_window_rect(
    title_contains: str,
    role: str | None = None,
    activate: bool = True,
    allow_fallback: bool = False,
) -> WindowTarget | None:
    """Return the highest-ranked target, optionally activating it."""
    targets = find_window_targets(title_contains, role=role, allow_fallback=allow_fallback)
    if not targets:
        return None
    target = targets[0]
    if activate:
        activate_window(target.hwnd)
    return target


def capture_target(target: WindowTarget, activate: bool = False) -> Frame:
    """Capture one visible target aligned to client area coordinates."""
    if mss is None:
        return Frame(
            bgr=np.zeros((0, 0, 3), dtype=np.uint8),
            left=target.client_left or target.left,
            top=target.client_top or target.top,
            window_title=target.title,
            hwnd=target.hwnd,
            role=target.role,
            is_valid=False,
            error="mss not installed",
        )

    if is_window_minimized(target.hwnd):
        return Frame(
            bgr=np.zeros((0, 0, 3), dtype=np.uint8),
            left=target.client_left or target.left,
            top=target.client_top or target.top,
            window_title=target.title,
            hwnd=target.hwnd,
            role=target.role,
            is_valid=False,
            error="Window is minimized",
        )

    if activate:
        activate_window(target.hwnd)
    elif _foreground_window() != target.hwnd:
        offscreen = _capture_print_window(target)
        if offscreen is not None:
            return offscreen

    c_left = target.client_left if (target.client_width > 0 and target.client_height > 0) else target.left
    c_top = target.client_top if (target.client_width > 0 and target.client_height > 0) else target.top
    c_width = target.client_width if target.client_width > 0 else target.width
    c_height = target.client_height if target.client_height > 0 else target.height

    try:
        with mss.mss() as sct:
            mon = {
                "left": c_left,
                "top": c_top,
                "width": c_width,
                "height": c_height,
            }
            raw = np.array(sct.grab(mon))
            return Frame(
                bgr=raw[:, :, :3].copy(),
                left=c_left,
                top=c_top,
                window_title=target.title,
                hwnd=target.hwnd,
                role=target.role,
                is_valid=True,
            )
    except Exception as e:
        print(f"[capture] screenshot exception: {e}")
        return Frame(
            bgr=np.zeros((0, 0, 3), dtype=np.uint8),
            left=c_left,
            top=c_top,
            window_title=target.title,
            hwnd=target.hwnd,
            role=target.role,
            is_valid=False,
            error=f"Screenshot exception: {e}",
        )


def capture(title_contains: str = "", role: str | None = None, activate: bool = True, allow_fallback: bool = False) -> Frame:
    if mss is None:
        return Frame(
            bgr=np.zeros((0, 0, 3), dtype=np.uint8),
            is_valid=False,
            error="mss not installed",
        )
    target = _find_window_rect(title_contains, role=role, activate=False, allow_fallback=allow_fallback)
    if target is None:
        print(f"[capture] target window not found: {title_contains!r}")
        return Frame(
            bgr=np.zeros((0, 0, 3), dtype=np.uint8),
            role=role,
            is_valid=False,
            error=f"Target window not found: {title_contains!r}",
        )
    return capture_target(target, activate=activate)
