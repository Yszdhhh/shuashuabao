"""黑市商人固定五槽扫描与决策器 (Merchant 5-slot scanner & decision logic).

规则体系:
1. 固定 5 槽 ROI 扫描。
2. 实际会买的只有三种，没有其它拿取:
   - Priority 1: OCR 明确识别的 2折/5折（不含 8折）
   - Priority 2: 吞噬丹 icon 小模板 (danGif)
   - Priority 3: 木材礼包完整商品模板 (merchant_wood)
   - 8折/普通宝石/属性卡/技能卡一律不买；买完这三类就刷新。
3. 商店指纹用槽位占用 + 已识别目标，不用整条商品 ROI 逐像素哈希。
   倒计时、图标动画和局部 HUD 变化不得打断 CONFIRMING→READY。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Sequence

import cv2
import numpy as np

# 1600x900 基准下黑商 5 槽 ROI 定义
# 整体黑商商品区域大约在 x: 0.70..0.90, y: 0.67..0.79
# 5 个槽位水平等分
MERCHANT_STRIP_ROI = (0.70, 0.67, 0.90, 0.79)
MERCHANT_SLOT_COUNT = 5
MERCHANT_SLOT_CENTER_X0 = 1172 / 1600
MERCHANT_SLOT_STEP_X = 55 / 1600
MERCHANT_SLOT_CENTER_Y = 640 / 900

DISCOUNT_KEYWORDS = ("2折", "5折", "二折", "五折")
NEGATIVE_ITEM_NAMES = ("贪欲之刃", "贪婪献祭", "杀敌流失", "扣除金币", "生命削减")


@dataclass(frozen=True)
class MerchantSlotItem:
    slot_index: int
    center_ratio: tuple[float, float]
    item_type: str  # "discount", "devour_pill", "wood", "attribute", "focus_card", "unknown"
    label: str = ""
    score: float = 1.0
    is_negative: bool = False


@dataclass
class MerchantScanResult:
    is_present: bool
    slots: list[MerchantSlotItem] = field(default_factory=list)
    refresh_available: bool = False
    refresh_ratio: tuple[float, float] = (0.911, 0.702)
    fingerprint: str = ""


class MerchantScanner:
    """黑市商人 5 槽分析与决策引擎。"""

    def __init__(
        self,
        attr_routes: Sequence[str] | None = None,
        focus_skills: Sequence[str] | None = None,
        focus_bonds: Sequence[str] | None = None,
        auto_refresh: bool = False,
    ):
        self.attr_routes = list(attr_routes or [])
        self.focus_skills = [s.strip() for s in (focus_skills or []) if s.strip()]
        self.focus_bonds = [b.strip() for b in (focus_bonds or []) if b.strip()]
        self.auto_refresh = auto_refresh

    @staticmethod
    def get_slot_center_ratio(slot_idx: int) -> tuple[float, float]:
        """获取 5 槽中第 slot_idx 槽 (0..4) 的归一化中心坐标。"""
        return (
            MERCHANT_SLOT_CENTER_X0 + slot_idx * MERCHANT_SLOT_STEP_X,
            MERCHANT_SLOT_CENTER_Y,
        )

    @staticmethod
    def slot_occupancy_bits(roi_bgr: np.ndarray | None) -> tuple[int, ...]:
        """Per-slot filled/empty bits from the icon region, ignoring price text."""
        if roi_bgr is None or roi_bgr.size == 0:
            return (0,) * MERCHANT_SLOT_COUNT
        width = int(roi_bgr.shape[1])
        slot_w = width / float(MERCHANT_SLOT_COUNT)
        bits: list[int] = []
        for index in range(MERCHANT_SLOT_COUNT):
            x0 = int(index * slot_w)
            x1 = int((index + 1) * slot_w)
            slot = roi_bgr[:, x0:x1]
            if slot.size == 0:
                bits.append(0)
                continue
            slot_h, slot_w_px = slot.shape[:2]
            icon = slot[
                : max(1, int(slot_h * 0.70)),
                max(0, int(slot_w_px * 0.10)) : max(1, int(slot_w_px * 0.90)),
            ]
            if icon.size == 0:
                bits.append(0)
                continue
            hsv = cv2.cvtColor(icon, cv2.COLOR_BGR2HSV)
            occupied = (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 70)
            bits.append(1 if float(occupied.mean()) >= 0.12 else 0)
        return tuple(bits)

    @staticmethod
    def compute_merchant_fingerprint(
        roi_bgr: np.ndarray | None,
        slot_items: Sequence[MerchantSlotItem] | None = None,
    ) -> str:
        """Hash slot occupancy plus recognized targets, not whole-strip pixels."""
        if roi_bgr is None or roi_bgr.size == 0:
            return ""
        occupancy = MerchantScanner.slot_occupancy_bits(roi_bgr)
        targets = tuple(
            sorted(
                (int(item.slot_index), str(item.item_type))
                for item in (slot_items or ())
            )
        )
        return hashlib.md5(f"{occupancy}|{targets}".encode("utf-8")).hexdigest()

    def rank_purchases(
        self,
        slots: Sequence[MerchantSlotItem],
        bond_bar_nonempty: bool = True,
    ) -> list[MerchantSlotItem]:
        """根据优先级为可购买的槽位排序。

        过滤负面物品。
        """
        candidates: list[tuple[int, MerchantSlotItem]] = []

        for item in slots:
            if item.is_negative:
                continue
            if item.label in NEGATIVE_ITEM_NAMES:
                continue

            # Priority 1: 5折 / 2折 折扣商品
            if item.item_type == "discount" or any(kw in item.label for kw in DISCOUNT_KEYWORDS):
                candidates.append((1, item))
                continue

            # Priority 2: 吞噬丹。merchant purchase itself does not consume it.
            if item.item_type == "devour_pill" or "danGif" in item.label or "吞噬" in item.label:
                if bond_bar_nonempty:
                    candidates.append((2, item))
                continue

            # Priority 3: 木材礼包
            if item.item_type == "wood" or "wood" in item.label or "木材" in item.label:
                candidates.append((3, item))
                continue
        # 按 priority 从小到大，再按 slot_index 确定性排序
        candidates.sort(key=lambda pair: (pair[0], pair[1].slot_index))
        return [item for _, item in candidates]
