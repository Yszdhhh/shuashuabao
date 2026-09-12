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
from typing import Optional, Sequence

# 定位失败时的收口默认行为：默认点末卡；可选 "fail_closed"
LOCATE_FAILURE_FALLBACK_DEFAULT: str = "last_card"


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
    page_type: str = "ARCHIVE_PANEL",
    can_scroll: bool | None = None,
) -> BossOrderDecision:
    """Pure decision function for post-game boss selection with unlock order fallback."""
    if can_scroll is None:
        can_scroll = True

    cols = 4 if page_type == "ARCHIVE_PANEL" else 5
    default_pitch = (78.0, 76.0) if page_type == "ARCHIVE_PANEL" else (79.2, 79.5)

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

    # 规则 2: T > L 且已确认到底（目标还没解锁出来）
    if at_bottom and target_no > max_no:
        return BossOrderDecision(
            action=BossOrderAction.CLICK_LAST_NOT_UNLOCKED,
            target_card=phys_last_card,
            reason=f"目标序号 {target_no} > 末卡序号 {L}（列表已到底，目标未解锁），兜底选择末卡",
        )

    # 规则 1: 目标排在末卡前面或当前视野附近 (T <= L 或当前可见区)
    # 3A: 目标在当前可见区上方 (T < min_no)
    if target_no < min_no:
        if can_scroll and not at_top and scroll_attempts < scroll_limit:
            return BossOrderDecision(
                action=BossOrderAction.SCROLL_UP,
                reason=f"目标序号 {target_no} < 可见最小序号 {min_no}，向上滚动寻找 ({scroll_attempts + 1}/{scroll_limit})",
            )
        # 无法继续上滚或已到顶
        if locate_attempts >= locate_limit or scroll_attempts >= scroll_limit or not can_scroll:
            return BossOrderDecision(
                action=BossOrderAction.CLICK_LAST_LOCATE_FAILED,
                target_card=phys_last_card,
                reason=f"目标序号 {target_no} < {min_no} 向上定位尝试已耗尽（at_top={at_top}），定位失败兜底",
            )
        box = predict_card_slot(target_no, visible_cards, cols_per_row=cols, default_pitch=default_pitch)
        center = (box[0] + box[2] // 2, box[1] + box[3] // 2) if box else None
        return BossOrderDecision(
            action=BossOrderAction.CONFIRM_PREDICTED,
            predicted_box=box,
            predicted_center=center,
            reason=f"目标序号 {target_no} 在顶部边缘附近，在预测格位做确认 ({locate_attempts + 1}/{locate_limit})",
        )

    # 3B: 目标在当前可见区下方 (T > max_no 且未到底)
    if target_no > max_no and not at_bottom:
        if can_scroll and scroll_attempts < scroll_limit:
            return BossOrderDecision(
                action=BossOrderAction.SCROLL_DOWN,
                reason=f"目标序号 {target_no} > 可见最大序号 {max_no}，向下滚动寻找 ({scroll_attempts + 1}/{scroll_limit})",
            )
        return BossOrderDecision(
            action=BossOrderAction.CLICK_LAST_LOCATE_FAILED,
            target_card=phys_last_card,
            reason=f"目标序号 {target_no} > {max_no} 向下滚动已到上限且未到底，定位失败兜底",
        )

    # 3C: 目标理应在当前可见区内 (min_no <= target_no <= max_no)
    if locate_attempts >= locate_limit:
        return BossOrderDecision(
            action=BossOrderAction.CLICK_LAST_LOCATE_FAILED,
            target_card=phys_last_card,
            reason=f"目标序号 {target_no} 在可见区 [{min_no}, {max_no}] 内但预测确认尝试耗尽 ({locate_attempts}/{locate_limit})，定位失败兜底",
        )

    box = predict_card_slot(target_no, visible_cards, cols_per_row=cols, default_pitch=default_pitch)
    center = (box[0] + box[2] // 2, box[1] + box[3] // 2) if box else None
    return BossOrderDecision(
        action=BossOrderAction.CONFIRM_PREDICTED,
        predicted_box=box,
        predicted_center=center,
        reason=f"目标序号 {target_no} 理应在可见区 [{min_no}, {max_no}] 内，在预测格位做二次证据确认 ({locate_attempts + 1}/{locate_limit})",
    )
