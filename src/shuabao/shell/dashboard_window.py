"""刷刷宝控制中心面板（别名模块，保持与 main_window 兼容并导出核心组件）。"""

from __future__ import annotations

from shuabao.shell.main_window import (
    MainWindow as DashboardWindow,
    MainWindow,
    SkillCardGrid,
    SkillArchiveLevelGrid,
    NegativeTreasureGroup,
    ATTR_LINE_OPTIONS,
    ATTR_ROUTES,
    BASIC_PACK_NAMES,
    DEFAULT_BOND_CODES,
    SKILL_STEMS,
    SKILL_LABELS,
    FETTER_LABELS,
)

__all__ = [
    "DashboardWindow",
    "MainWindow",
    "SkillCardGrid",
    "SkillArchiveLevelGrid",
    "NegativeTreasureGroup",
    "ATTR_LINE_OPTIONS",
    "ATTR_ROUTES",
    "BASIC_PACK_NAMES",
    "DEFAULT_BOND_CODES",
    "SKILL_STEMS",
    "SKILL_LABELS",
    "FETTER_LABELS",
]
