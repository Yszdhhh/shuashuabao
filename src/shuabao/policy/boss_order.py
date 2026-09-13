"""Pure decision policy for post-game Boss selection with unlock order fallback.

Rules:
设目标 Boss 的序号为 T，已确认到底后物理末卡的序号为 L（从末卡模板名解析得到）：
1. T <= L（目标排在末卡前面，理应已经解锁）：没找到大概率是识别失败，不能直接选末卡。
   按顺序定位：用当前能识别出的卡片序号，判断目标在上方还是下方、离得多远，朝那个方向滚动，
   并在预测位置附近重新确认后再点。若尝试耗尽，按具名常量 LOCATE_FAILURE_FALLBACK_DEFAULT
   收口（默认点末卡，并单独打日志 BossOrderLocateFailed、记录 incident）。
2. T > L（目标还没解锁出来）：选末卡（兜底，BossNotUnlockedLast）。
3. 没配置目标：保持现状，探底后选末卡（BossBottomFallback）。
4. 识别不出末卡序号时（L 未知）：有界等待，不套用规则 1 或 2。
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, Sequence

# 定位失败时的收口默认行为：默认点末卡；可选 "fail_closed"
LOCATE_FAILURE_FALLBACK_DEFAULT: str = "last_card"


def is_slot_empty(crop: Any) -> bool:
    """Determine if a slot bounding box contains an empty slot background (no card).

    Measured on fixtures (heirloom_challenge_bosses.png, archive_challenge_panel.png):
    - Real card slots: std in [58.2, 75.7] (>= 50.0), max >= 240, canny edge ratio in [0.19, 0.36] (>= 0.15)
    - Empty background slots: std in [2.0, 8.3] (<= 12.0), max in [37, 44] (<= 50), mean ~ 27, canny edge ratio in [0.00, 0.04] (<= 0.05)
    - Separation criteria: (max <= 60.0 and std <= 12.0) or (edge_ratio <= 0.05 and std <= 15.0)
    """
    if crop is None:
        return True
    try:
        import cv2
        import numpy as np

        if not isinstance(crop, np.ndarray) or crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
            return True
        if len(crop.shape) == 3:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        else:
            gray = crop
        std_val = float(np.std(gray))
        max_val = float(np.max(gray))
        if max_val <= 60.0 and std_val <= 12.0:
            return True
        edges = cv2.Canny(gray, 50, 150)
        edge_ratio = float(np.count_nonzero(edges)) / float(edges.size)
        if edge_ratio <= 0.05 and std_val <= 15.0:
            return True
        return False
    except Exception:
        return False


class BossOrderAction(str, Enum):
    CLICK_TARGET = "CLICK_TARGET"
    SCROLL_UP = "SCROLL_UP"
    SCROLL_DOWN = "SCROLL_DOWN"
    CONFIRM_PREDICTED = "CONFIRM_PREDICTED"
    CLICK_LAST_NOT_UNLOCKED = "CLICK_LAST_NOT_UNLOCKED"
    CLICK_LAST_LOCATE_FAILED = "CLICK_LAST_LOCATE_FAILED"
    WAIT = "WAIT"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class VisibleCard:
    no: int
    name: str
    x: int
    y: int
    w: int
    h: int
    score: float

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


@dataclass(frozen=True)
class BossOrderDecision:
    action: BossOrderAction
    target_card: Optional[VisibleCard] = None
    predicted_box: Optional[tuple[int, int, int, int]] = None  # (x, y, w, h)
    predicted_center: Optional[tuple[int, int]] = None
    reason: str = ""
    stage: Optional[str] = None


def get_catalog_max_order(
    page_type: str = "ARCHIVE_PANEL",
    catalog: dict | None = None,
) -> int:
    """Read max unlock order per section from challenge_boss_catalog."""
    if catalog:
        section = "boss" if page_type == "ARCHIVE_PANEL" else "chuanjiaobao"
        items = catalog.get(section, [])
        if isinstance(items, list) and items:
            valid_nos = []
            for item in items:
                if isinstance(item, dict) and "no" in item:
                    try:
                        no_val = int(item["no"])
                        if page_type == "HEIRLOOM_DIALOG" and no_val == 54:
                            # 54莫阿姆 is known competitor-sync anomaly excluded from heirloom ordering
                            continue
                        valid_nos.append(no_val)
                    except (ValueError, TypeError):
                        pass
            if valid_nos:
                return max(valid_nos)
    return 54 if page_type == "ARCHIVE_PANEL" else 20


def parse_boss_order_number(
    boss_identifier: str | int | None,
    catalog: dict | None = None,
) -> int | None:
    """Extract numeric unlock order from boss name, template stem, or catalog."""
    if boss_identifier is None:
        return None
    if isinstance(boss_identifier, int):
        return boss_identifier

    raw = str(boss_identifier).strip()
    if not raw:
        return None

    # Remove optional folder prefix like "boss/" or "chuanjiaobao/"
    name = raw.split("/")[-1]

    # 1. Match leading digits (e.g. "01霍格" -> 1, "18乌索克" -> 18)
    match = re.match(r"^(\d+)", name)
    if match:
        return int(match.group(1))

    # 2. Look up in challenge_boss_catalog if provided
    if catalog:
        for section in ("chuanjiaobao", "boss"):
            items = catalog.get(section, [])
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if (
                        item.get("label") == name
                        or item.get("template_stem") == name
                        or str(item.get("no")) == name
                    ):
                        try:
                            return int(item["no"])
                        except (ValueError, TypeError, KeyError):
                            pass

    return None


def measure_grid_pitch(
    visible_cards: Sequence[VisibleCard],
    cols_per_row: int,
    default_pitch: tuple[float, float] = (78.0, 76.0),
) -> tuple[float, float, int, int]:
    """Measure empirical horizontal (dx) and vertical (dy) pitch and card size."""
    if not visible_cards:
        return default_pitch[0], default_pitch[1], 58, 58

    widths = [c.w for c in visible_cards if c.w > 0]
    heights = [c.h for c in visible_cards if c.h > 0]
    med_w = int(statistics.median(widths)) if widths else 58
    med_h = int(statistics.median(heights)) if heights else 58

    dx_samples: list[float] = []
    dy_samples: list[float] = []

    cards_list = list(visible_cards)
    for i in range(len(cards_list)):
        for j in range(i + 1, len(cards_list)):
            c1, c2 = cards_list[i], cards_list[j]
            # If on roughly the same row
            if abs(c1.y - c2.y) <= med_h * 0.4:
                # Column difference based on numbering
                col1 = (c1.no - 1) % cols_per_row
                col2 = (c2.no - 1) % cols_per_row
                d_col = abs(col1 - col2)
                if d_col > 0:
                    pitch = abs(c1.x - c2.x) / d_col
                    if 40 <= pitch <= 140:
                        dx_samples.append(pitch)
            # If on roughly the same column
            if abs(c1.x - c2.x) <= med_w * 0.4:
                row1 = (c1.no - 1) // cols_per_row
                row2 = (c2.no - 1) // cols_per_row
                d_row = abs(row1 - row2)
                if d_row > 0:
                    pitch = abs(c1.y - c2.y) / d_row
                    if 40 <= pitch <= 140:
                        dy_samples.append(pitch)

    dx = float(statistics.median(dx_samples)) if dx_samples else default_pitch[0]
    dy = float(statistics.median(dy_samples)) if dy_samples else default_pitch[1]
    return dx, dy, med_w, med_h


def predict_card_slot(
    target_no: int,
    visible_cards: Sequence[VisibleCard],
    cols_per_row: int = 4,
    default_pitch: tuple[float, float] = (78.0, 76.0),
) -> tuple[int, int, int, int] | None:
    """Predict bounding box (x, y, w, h) for target_no using visible neighbor anchors."""
    if not visible_cards or target_no <= 0:
        return None

    dx, dy, med_w, med_h = measure_grid_pitch(visible_cards, cols_per_row, default_pitch)

    target_col = (target_no - 1) % cols_per_row
    target_row = (target_no - 1) // cols_per_row

    # Check for bilateral interpolation (e.g. left anchor target_no - 1 and right anchor target_no + 1 on same row)
    left_anchor = next(
        (c for c in visible_cards if c.no == target_no - 1 and (c.no - 1) // cols_per_row == target_row),
        None,
    )
    right_anchor = next(
        (c for c in visible_cards if c.no == target_no + 1 and (c.no - 1) // cols_per_row == target_row),
        None,
    )

    if left_anchor is not None and right_anchor is not None:
        px = int((left_anchor.x + right_anchor.x) / 2)
        py = int((left_anchor.y + right_anchor.y) / 2)
        return (px, py, med_w, med_h)

    # Otherwise choose anchor with smallest grid distance
    def grid_dist(c: VisibleCard) -> float:
        c_col = (c.no - 1) % cols_per_row
        c_row = (c.no - 1) // cols_per_row
        return abs(target_col - c_col) + abs(target_row - c_row) * 1.5

    best_anchor = min(visible_cards, key=grid_dist)
    anchor_col = (best_anchor.no - 1) % cols_per_row
    anchor_row = (best_anchor.no - 1) // cols_per_row

    px = int(best_anchor.x + (target_col - anchor_col) * dx)
    py = int(best_anchor.y + (target_row - anchor_row) * dy)
    return (px, py, med_w, med_h)


def decide_boss_order_action(
    target_no: int | None,
    visible_cards: Sequence[VisibleCard],
    *,
    at_bottom: bool = False,
    at_top: bool = False,
    scroll_attempts: int = 0,
    scroll_limit: int = 16,
    locate_attempts: int = 0,
    locate_limit: int = 3,
    locate_exhausted: bool = False,
    bottom_scroll_attempts: int = 0,
    bottom_scroll_limit: int = 16,
    page_type: str = "ARCHIVE_PANEL",
    can_scroll: bool | None = None,
    viewport_box: tuple[int, int, int, int] | None = None,
    slot_empty_checker: Callable[[tuple[int, int, int, int]], bool] | None = None,
    frame_bgr: Any = None,
    catalog: dict | None = None,
    max_catalog_no: int | None = None,
) -> BossOrderDecision:
    """Pure decision function for post-game boss selection with unlock order fallback."""
    if can_scroll is None:
        can_scroll = True

    cols = 4 if page_type == "ARCHIVE_PANEL" else 5
    default_pitch = (78.0, 76.0) if page_type == "ARCHIVE_PANEL" else (79.2, 79.5)
    if max_catalog_no is None:
        max_catalog_no = get_catalog_max_order(page_type, catalog)

    if slot_empty_checker is None and frame_bgr is not None:
        def _check_empty(b: tuple[int, int, int, int]) -> bool:
            x0, y0 = max(0, b[0]), max(0, b[1])
            x1 = min(frame_bgr.shape[1], b[0] + b[2])
            y1 = min(frame_bgr.shape[0], b[1] + b[3])
            return is_slot_empty(frame_bgr[y0:y1, x0:x1])
        slot_empty_checker = _check_empty

    # 1. 没配置目标：保持现状，探底后选末卡
    if target_no is None:
        if at_bottom:
            if visible_cards:
                last_card = max(visible_cards, key=lambda c: (c.y + c.h, c.x + c.w))
                return BossOrderDecision(
                    action=BossOrderAction.CLICK_LAST_NOT_UNLOCKED,
                    target_card=last_card,
                    reason="未配置目标 Boss，列表已确认到底，选择物理最后一张卡",
                )
            return BossOrderDecision(
                action=BossOrderAction.WAIT,
                reason="未配置目标 Boss，列表已到底但未识别出末卡，等待证据",
            )
        if can_scroll and scroll_attempts < scroll_limit:
            return BossOrderDecision(
                action=BossOrderAction.SCROLL_DOWN,
                reason=f"未配置目标 Boss，向下探底 ({scroll_attempts + 1}/{scroll_limit})",
            )
        return BossOrderDecision(
            action=BossOrderAction.WAIT,
            reason="未配置目标 Boss，滚动到安全上限但未证明到底，等待未决观察收敛",
        )

    # 2. 目标已直接识别在当前视野中
    for card in visible_cards:
        if card.no == target_no:
            return BossOrderDecision(
                action=BossOrderAction.CLICK_TARGET,
                target_card=card,
                reason=f"目标 Boss {target_no} 直接匹配命中: {card.name}",
            )

    # 3. 目标未直接匹配：检查视野内可见卡片
    if not visible_cards:
        # L 未知：识别不出任何卡片
        if at_bottom:
            return BossOrderDecision(
                action=BossOrderAction.WAIT,
                reason="列表已到底但未能识别出任何卡片（末卡未知），等待证据",
            )
        if can_scroll and scroll_attempts < scroll_limit:
            return BossOrderDecision(
                action=BossOrderAction.SCROLL_DOWN,
                reason=f"当前帧未识别出卡片，向下滚动寻找 ({scroll_attempts + 1}/{scroll_limit})",
            )
        return BossOrderDecision(
            action=BossOrderAction.WAIT,
            reason="未识别出卡片且滚动达到安全上限，等待未决观察收敛",
        )

    min_no = min(c.no for c in visible_cards)
    max_no = max(c.no for c in visible_cards)
    phys_last_card = max(visible_cards, key=lambda c: (c.y + c.h, c.x + c.w))
    L = phys_last_card.no

    def _locate_failed_fallback(reason_prefix: str) -> BossOrderDecision:
        if at_bottom:
            # P2-D: 复用规则 2 的 L+1 空格校验；只有证明为物理末卡才点末卡，L+1 有卡时 WAIT
            if target_no > max_catalog_no or L >= max_catalog_no:
                return BossOrderDecision(
                    action=BossOrderAction.CLICK_LAST_LOCATE_FAILED,
                    target_card=phys_last_card,
                    reason=f"{reason_prefix}且列表已确认到底（已达目录上限），兜底选择末卡",
                )
            next_slot = predict_card_slot(L + 1, visible_cards, cols_per_row=cols, default_pitch=default_pitch)
            if next_slot is None:
                return BossOrderDecision(
                    action=BossOrderAction.WAIT,
                    reason=f"{reason_prefix}且列表已确认到底，但无法推算后续格位 L+1={L+1}，等待证据",
                )
            nx, ny, nw, nh = next_slot
            ncx, ncy = nx + nw // 2, ny + nh // 2
            in_viewport = True
            if viewport_box is not None:
                vx0, vy0, vx1, vy1 = viewport_box
                in_viewport = (vx0 <= ncx <= vx1) and (vy0 <= ncy <= vy1)
            if in_viewport:
                slot_is_empty = slot_empty_checker(next_slot) if slot_empty_checker is not None else False
                if slot_is_empty:
                    return BossOrderDecision(
                        action=BossOrderAction.CLICK_LAST_LOCATE_FAILED,
                        target_card=phys_last_card,
                        reason=f"{reason_prefix}且列表已确认到底，后续格位 L+1={L+1} 经像素校验为空格（末卡已证明），兜底选择末卡",
                    )
                else:
                    return BossOrderDecision(
                        action=BossOrderAction.WAIT,
                        reason=f"{reason_prefix}且列表已确认到底，但末卡 L={L} 后续格位存在未识别卡片（真实末卡未知），等待证据",
                    )
            else:
                return BossOrderDecision(
                    action=BossOrderAction.WAIT,
                    reason=f"{reason_prefix}且列表已确认到底，但推算格位 L+1={L+1} 超出视野边界，无法证明末卡，等待证据",
                )
        if can_scroll and bottom_scroll_attempts < bottom_scroll_limit:
            return BossOrderDecision(
                action=BossOrderAction.SCROLL_DOWN,
                reason=f"定位失败，回到底部取末卡 ({bottom_scroll_attempts + 1}/{bottom_scroll_limit})",
                stage="return_to_bottom",
            )
        return BossOrderDecision(
            action=BossOrderAction.WAIT,
            reason=f"{reason_prefix}回底滚动已到安全上限但未证明到底，禁止任意卡兜底，等待未决收敛",
            stage="return_to_bottom",
        )

    # 若已处于定位尝试耗尽状态，直接走回底兜底
    if locate_exhausted:
        return _locate_failed_fallback("目标定位尝试已耗尽")

    # 规则 2: T > L 且已确认到底（目标还没解锁出来）
    if at_bottom and target_no > max_no:
        # P0-3: 必须证明已识别出的末卡就是物理末卡，不能把仅识别出的卡片当成物理末卡
        if target_no > max_catalog_no or L >= max_catalog_no:
            return BossOrderDecision(
                action=BossOrderAction.CLICK_LAST_NOT_UNLOCKED,
                target_card=phys_last_card,
                reason=f"目标序号 {target_no} > 末卡序号 {L}（已达目录上限或到底确认未解锁），兜底选择末卡",
            )
        next_slot = predict_card_slot(L + 1, visible_cards, cols_per_row=cols, default_pitch=default_pitch)
        if next_slot is None:
            return BossOrderDecision(
                action=BossOrderAction.WAIT,
                reason=f"目标序号 {target_no} > 可见最大 {L}，但无法推算后续格位，等待证据",
            )
        nx, ny, nw, nh = next_slot
        ncx, ncy = nx + nw // 2, ny + nh // 2
        in_viewport = True
        if viewport_box is not None:
            vx0, vy0, vx1, vy1 = viewport_box
            in_viewport = (vx0 <= ncx <= vx1) and (vy0 <= ncy <= vy1)

        if in_viewport:
            slot_is_empty = slot_empty_checker(next_slot) if slot_empty_checker is not None else False
            if slot_is_empty:
                return BossOrderDecision(
                    action=BossOrderAction.CLICK_LAST_NOT_UNLOCKED,
                    target_card=phys_last_card,
                    reason=f"目标序号 {target_no} > 末卡序号 {L}，后续格位 L+1={L+1} 经像素校验为空格（末卡已证明），兜底选择末卡",
                )
            else:
                # L+1 格位存在未识别卡片，L 不是末卡，禁止误点倒数第二张
                if target_no == L + 1:
                    return BossOrderDecision(
                        action=BossOrderAction.CONFIRM_PREDICTED,
                        predicted_box=next_slot,
                        predicted_center=(ncx, ncy),
                        reason=f"末卡 L={L} 后续格位存在未识别卡片，目标正是 L+1={target_no}，在预测格位做二次证据确认",
                    )
                return BossOrderDecision(
                    action=BossOrderAction.WAIT,
                    reason=f"末卡 L={L} 后续格位存在未识别卡片（真实末卡未知），目标序号 {target_no} > {L}，禁止点击倒数第二张，等待证据",
                )
        else:
            # L+1 格位超出视口
            return BossOrderDecision(
                action=BossOrderAction.WAIT,
                reason=f"目标序号 {target_no} > 可见最大 {L}，推算格位 L+1={L+1} 超出列表视野边界，无法证明末卡，等待证据",
            )

    # 规则 1: 目标排在末卡前面或当前视野附近 (T <= L 或当前可见区)
    # 3A: 目标在当前可见区上方 (T < min_no)
    if target_no < min_no:
        if can_scroll and not at_top and scroll_attempts < scroll_limit:
            return BossOrderDecision(
                action=BossOrderAction.SCROLL_UP,
                reason=f"目标序号 {target_no} < 可见最小序号 {min_no}，向上滚动寻找 ({scroll_attempts + 1}/{scroll_limit})",
            )
        # 无法继续上滚或已到顶：在视野内预测格位尝试二次确认，用完 locate_limit 次后才兜底
        if locate_attempts >= locate_limit:
            return _locate_failed_fallback(
                f"目标序号 {target_no} < {min_no} 向上定位尝试已耗尽 ({locate_attempts}/{locate_limit})（at_top={at_top}）"
            )
        box = predict_card_slot(target_no, visible_cards, cols_per_row=cols, default_pitch=default_pitch)
        if box:
            cx, cy = box[0] + box[2] // 2, box[1] + box[3] // 2
            if viewport_box is not None:
                vx0, vy0, vx1, vy1 = viewport_box
                if cy < vy0:
                    if can_scroll and not at_top and scroll_attempts < scroll_limit:
                        return BossOrderDecision(
                            action=BossOrderAction.SCROLL_UP,
                            reason=f"目标序号 {target_no} 预测格位在视野上方 (y={box[1]} < {vy0})，向上滚动寻找 ({scroll_attempts + 1}/{scroll_limit})",
                        )
                    return _locate_failed_fallback(f"目标序号 {target_no} 预测格位在视野上方但无法上滚")
                elif cy > vy1:
                    if can_scroll and not at_bottom and scroll_attempts < scroll_limit:
                        return BossOrderDecision(
                            action=BossOrderAction.SCROLL_DOWN,
                            reason=f"目标序号 {target_no} 预测格位在视野下方 (y={box[1] + box[3]} > {vy1})，向下滚动寻找 ({scroll_attempts + 1}/{scroll_limit})",
                        )
                    return _locate_failed_fallback(f"目标序号 {target_no} 预测格位在视野下方但无法下滚")
            return BossOrderDecision(
                action=BossOrderAction.CONFIRM_PREDICTED,
                predicted_box=box,
                predicted_center=(cx, cy),
                reason=f"目标序号 {target_no} < {min_no} 已到顶或无法上滚，在预测格位做二次证据确认 ({locate_attempts + 1}/{locate_limit})",
            )
        return _locate_failed_fallback(f"目标序号 {target_no} 无法推算预测格位")

    # 3B: 目标在当前可见区下方 (T > max_no 且未到底)
    if target_no > max_no and not at_bottom:
        if can_scroll and scroll_attempts < scroll_limit:
            return BossOrderDecision(
                action=BossOrderAction.SCROLL_DOWN,
                reason=f"目标序号 {target_no} > 可见最大序号 {max_no}，向下滚动寻找 ({scroll_attempts + 1}/{scroll_limit})",
            )
        return BossOrderDecision(
            action=BossOrderAction.WAIT,
            reason=f"目标序号 {target_no} > {max_no} 向下滚动已到安全上限 ({scroll_attempts}/{scroll_limit}) 但未证明到底，禁止任意卡兜底，等待收敛",
        )

    # 3C: 目标理应在当前可见区内 (min_no <= target_no <= max_no)
    if locate_attempts >= locate_limit:
        return _locate_failed_fallback(
            f"目标序号 {target_no} 在可见区 [{min_no}, {max_no}] 内但预测确认尝试耗尽 ({locate_attempts}/{locate_limit})"
        )

    box = predict_card_slot(target_no, visible_cards, cols_per_row=cols, default_pitch=default_pitch)
    if box:
        cx, cy = box[0] + box[2] // 2, box[1] + box[3] // 2
        if viewport_box is not None:
            vx0, vy0, vx1, vy1 = viewport_box
            if cy < vy0:
                if can_scroll and not at_top and scroll_attempts < scroll_limit:
                    return BossOrderDecision(
                        action=BossOrderAction.SCROLL_UP,
                        reason=f"目标序号 {target_no} 预测格位在视野上方 (y={box[1]} < {vy0})，向上滚动寻找 ({scroll_attempts + 1}/{scroll_limit})",
                    )
                return _locate_failed_fallback(f"目标序号 {target_no} 预测格位在视野上方但无法上滚")
            elif cy > vy1:
                if can_scroll and not at_bottom and scroll_attempts < scroll_limit:
                    return BossOrderDecision(
                        action=BossOrderAction.SCROLL_DOWN,
                        reason=f"目标序号 {target_no} 预测格位在视野下方 (y={box[1] + box[3]} > {vy1})，向下滚动寻找 ({scroll_attempts + 1}/{scroll_limit})",
                    )
                return _locate_failed_fallback(f"目标序号 {target_no} 预测格位在视野下方但无法下滚")
        return BossOrderDecision(
            action=BossOrderAction.CONFIRM_PREDICTED,
            predicted_box=box,
            predicted_center=(cx, cy),
            reason=f"目标序号 {target_no} 理应在可见区 [{min_no}, {max_no}] 内，在预测格位做二次证据确认 ({locate_attempts + 1}/{locate_limit})",
        )
    return _locate_failed_fallback(f"目标序号 {target_no} 无法推算预测格位")
