"""黑市商人固定五槽扫描与决策器 (Merchant 5-slot scanner & decision logic).

规则体系:
1. 固定 5 槽 ROI 扫描。
2. 购买优先级:
   - Priority 1: OCR 明确识别的 2折/5折
   - Priority 2: 吞噬丹 icon 小模板 (danGif) -> 商店获取；背包使用另有前置
   - Priority 3: 木材礼包 icon 小模板 (merchant_wood / woodgift)
   - Priority 4: 属性线/主属性关键词匹配 (智力 / 力量 / 敏捷)
   - Priority 5: 技能 / 羁绊偏好卡片 (技能 focus / 偏好羁绊)
   - Priority 6: 免费刷新 (仅在开启刷新且满足条件时)
   - 负面宝物 / 负收益物品严格过滤与跳过。
3. 商店指纹排除倒计时秒数，避免缓存频繁击穿。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Sequence
import numpy as np

# 1600x900 基准下黑商 5 槽 ROI 定义
# 整体黑商商品区域大约在 x: 0.70..0.90, y: 0.67..0.79
# 5 个槽位水平等分
MERCHANT_STRIP_ROI = (0.70, 0.67, 0.90, 0.79)
MERCHANT_SLOT_COUNT = 5

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
    refresh_ratio: tuple[float, float] = (0.91, 0.72)
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
        x_min, y_min, x_max, y_max = MERCHANT_STRIP_ROI
        slot_w = (x_max - x_min) / MERCHANT_SLOT_COUNT
        cx = x_min + (slot_idx + 0.5) * slot_w
        cy = (y_min + y_max) / 2.0
        return (cx, cy)

    @staticmethod
    def compute_merchant_fingerprint(roi_bgr: np.ndarray | None) -> str:
        """排除易变的倒计时文本区域，计算商品图标区域的稳定哈希。"""
        if roi_bgr is None or roi_bgr.size == 0:
            return ""
        # 裁剪掉底部可能包含秒数/金币文本的 20% 高度区域，只保留图标特征
        h, w = roi_bgr.shape[:2]
        crop_h = max(1, int(h * 0.80))
        stable_region = roi_bgr[:crop_h, :]
        # 缩放至小图做轻量 dhash / sha256
        small = stable_region[::4, ::4]
        return hashlib.md5(small.tobytes()).hexdigest()

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
