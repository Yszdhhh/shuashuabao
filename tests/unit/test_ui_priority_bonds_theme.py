"""技能优先级拖拽条 / 路线下拉 v2 / 预设羁绊预选 / 自定义羁绊 的最小 UI 契约。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QComboBox

from shuabao.shell.main_window import (
    OFFICIAL_BUILDS,
    MainWindow,
    SkillCardGrid,
    SkillPriorityBar,
    code_for_bond_name,
)


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(qapp, tmp_path):
    win = MainWindow(app_data=tmp_path)
    win.grp_skill.setChecked(True)
    yield win
    win.close()


def _pump(qapp=None):
    loop = QEventLoop()
    QTimer.singleShot(60, loop.quit)
    loop.exec()


def test_priority_drag_round_trips_to_settings(window):
    window.skill_grid.set_skills(["asj", "jq"])
    assert window.skill_priority_bar.order() == ["asj", "jq"]

    lst = window.skill_priority_bar.chip_list
    item = lst.takeItem(1)  # 模拟拖拽：jq 移到最前（索引 0 最高优先级）
    lst.insertItem(0, item)
    _pump()

    assert window.skill_priority_bar.order() == ["jq", "asj"]
    assert window.skill_grid.get_skills() == ["jq", "asj"]
    assert list(getattr(window.settings, "skill_priority", [])) == ["jq", "asj"]
    collected = window.collect_settings_from_ui()
    assert list(collected.skill_priority) == ["jq", "asj"]


def test_new_selection_appends_after_existing_priority(window):
    window.settings.skill_priority = ["asj"]
    window.skill_grid.set_skills(["jq", "asj"])
    assert window.skill_priority_bar.order() == ["asj", "jq"]
    assert window.skill_grid.get_skills() == ["asj", "jq"]


def test_route_combo_filled_from_v2_families_and_persisted(window):
    window.skill_grid.set_skills(["asj"])
    combo = window.skill_priority_bar.chip_list.itemWidget(
        window.skill_priority_bar.chip_list.item(0)
    ).findChild(QComboBox)
    assert combo is not None and combo.count() >= 2
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert all(labels), "路线 label 必须来自 families[].routes"

    rid = str(combo.currentData())
    window._on_priority_route_changed("asj", rid)
    routes = getattr(window.settings, "skill_custom_routes", {})
    assert routes.get("asj") == rid
    collected = window.collect_settings_from_ui()
    assert collected.skill_custom_routes.get("asj") == rid


def test_route_combo_hidden_when_families_missing(qapp):
    bar = SkillPriorityBar()
    try:
        bar._families = {}
        bar.rebuild(["asj"])
        combo = bar.chip_list.itemWidget(bar.chip_list.item(0)).findChild(QComboBox)
        assert combo is not None
        assert combo.count() == 0 and not combo.isVisibleTo(combo.parentWidget())
    finally:
        bar.close()


def test_official_build_prechecks_recommended_bonds_and_stays_editable(window):
    window.grp_bond_basic.setChecked(True)  # 展开基础卡组后必须可自由增删
    build = next(b for b in OFFICIAL_BUILDS if b.get("skills") and b.get("cards"))
    assert window.apply_official_build(str(build["id"]), confirm=False)

    recommended = {code_for_bond_name(n) or n for n in build["cards"]}
    checked = {c for c, box in window._bond_plan_boxes.items() if box.isChecked()}
    overlap = checked & recommended
    assert overlap, f"预设羁绊未预勾选进复选组: {sorted(recommended)} vs {sorted(checked)}"
    for code in overlap:
        box = window._bond_plan_boxes[code]
        assert box.isEnabled(), "预勾选绝不允许锁定禁用"
        box.setChecked(False)  # 全部可自由增删
        assert code not in window.effective_bond_codes()


def test_custom_bond_append_dedupe_and_free_edit(window):
    window.grp_bond_basic.setChecked(True)  # 展开后勾选框可用
    window.txt_custom_bond.setText("测试羁绊甲")
    window._add_custom_bond()
    window.txt_custom_bond.setText("测试羁绊甲")  # 去重
    window._add_custom_bond()
    window.txt_custom_bond.setText("")  # 非空校验
    window._add_custom_bond()

    matches = [(c, b) for c, b in window._bond_plan_boxes.items() if "测试羁绊甲" in c]
    assert len(matches) == 1, matches
    code, box = matches[0]
    assert box.isChecked() and box.isEnabled()
    assert "测试羁绊甲" in (getattr(window.settings, "cards", None) or [])
    box.setChecked(False)  # 可自由取消
    assert box.isEnabled()


def test_skill_priority_cap_four_via_bar(window):
    codes = list(window.skill_grid.cards.keys())
    window.skill_grid.set_skills(codes)
    assert len(window.skill_priority_bar.order()) <= SkillCardGrid.MAX_SKILLS
