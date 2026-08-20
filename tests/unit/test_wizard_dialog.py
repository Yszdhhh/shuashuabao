import os

import pytest
from PySide6.QtWidgets import QApplication

from shuabao.settings import Settings
from shuabao.shell.main_window import MainWindow
from shuabao.shell.wizard_dialog import (
    SKILL_PRESETS,
    GameStyleWizardDialog,
    QuickStartSelection,
    apply_quick_start_to_settings,
    catalog_preset_by_index,
    selection_from_payload,
)


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_wizard_dialog_instantiation_and_dto(qapp):
    settings = Settings()
    dialog = GameStyleWizardDialog(settings=settings)
    assert dialog is not None
    assert dialog.page_mode is not None
    assert dialog.page_stage is not None
    assert dialog.page_build is not None
    assert dialog.width() <= 520

    dto = dialog.get_selection()
    assert isinstance(dto, QuickStartSelection)
    assert dto.mode in {"solo", "lobby_hitch"}
    assert isinstance(dto.skills, list)
    assert isinstance(dto.bonds, list)
    assert dto.skills
    assert all(len(code) <= 8 and code.isascii() for code in dto.skills)


def test_wizard_custom_build_switch(qapp):
    settings = Settings()
    dialog = GameStyleWizardDialog(settings=settings)
    dialog.skill_boxes[0].setCurrentIndex(min(1, dialog.skill_boxes[0].count() - 1))
    dialog._on_custom_changed()
    assert dialog.is_custom is True
    assert "自定义" in dialog.lbl_status.text()


def test_advanced_requested_signal_connects(qapp):
    dialog = GameStyleWizardDialog(settings=Settings())
    assert hasattr(dialog, "advanced_requested")
    seen = []
    dialog.advanced_requested.connect(lambda payload: seen.append(payload))
    dialog.rb_ride.setChecked(True)
    dialog._on_advanced()
    assert seen and seen[0]["mode"] == "lobby_hitch"


def test_chapter_change_retargets_stage_labels(qapp):
    dialog = GameStyleWizardDialog(settings=Settings())
    texts_ch1 = [dialog.cb_stage.itemText(i) for i in range(dialog.cb_stage.count())]
    assert dialog.cb_stage.count() == 23
    assert any(t.endswith("1-1") or t == "1-1" for t in texts_ch1)
    assert any("1-23" in t for t in texts_ch1)
    dialog.cb_chapter.setCurrentIndex(1)
    texts_ch2 = [dialog.cb_stage.itemText(i) for i in range(dialog.cb_stage.count())]
    assert dialog.cb_stage.count() == 7
    assert any("2-1" in t for t in texts_ch2)
    assert not any("1-1" in t for t in texts_ch2)
    assert not any("1-6" in t for t in texts_ch2)


def test_apply_quick_start_to_settings_maps_catalog_preset():
    preset = catalog_preset_by_index(0)
    assert preset and preset.get("codes")
    sel = QuickStartSelection(
        mode="lobby_hitch",
        stage1=2,
        stage2=3,
        preset_name=str(preset.get("name") or ""),
        skills=list(preset["codes"]),
    )
    out = apply_quick_start_to_settings(Settings(skills=["pg"], mode_id="normal_farm"), sel)
    assert out.mode_id == "lobby_hitch"
    assert out.stage_targets == ["2-3"]
    assert out.skills == list(preset["codes"])
    assert "闪电链" not in out.skills


def test_direct_start_and_advanced_apply_payload(qapp, tmp_path):
    preset = catalog_preset_by_index(0)
    assert preset and SKILL_PRESETS
    window = MainWindow(app_data=tmp_path)
    wizard = GameStyleWizardDialog(settings=window.settings)
    wizard.rb_ride.setChecked(True)
    wizard.cb_chapter.setCurrentIndex(1)
    wizard._retarget_stage_combo(1)
    wizard.cb_stage.setCurrentIndex(2)
    wizard.cb_preset.setCurrentIndex(0)
    wizard._apply_preset_index(0)

    seen = []

    def _on_run(payload):
        window.apply_quick_start_selection(payload)
        seen.append(("run", payload))

    def _on_advanced(payload):
        window.apply_quick_start_selection(payload)
        seen.append(("adv", payload))

    wizard.run_requested.connect(_on_run)
    wizard.advanced_requested.connect(_on_advanced)

    wizard._on_advanced()
    assert seen[0][0] == "adv"
    assert window.selected_mode_id() == "lobby_hitch"
    collected = window.collect_settings_from_ui()
    assert collected.mode_id == "lobby_hitch"
    assert collected.stage_targets == ["2-3"]
    assert collected.skills == list(preset["codes"])
    assert "闪电链" not in collected.skills

    wizard2 = GameStyleWizardDialog(settings=Settings())
    wizard2.rb_ride.setChecked(True)
    wizard2.cb_chapter.setCurrentIndex(1)
    wizard2._retarget_stage_combo(1)
    wizard2.cb_stage.setCurrentIndex(2)
    wizard2.cb_preset.setCurrentIndex(0)
    wizard2._apply_preset_index(0)
    wizard2.run_requested.connect(_on_run)
    wizard2.advanced_requested.connect(_on_advanced)
    wizard2._on_run()
    assert seen[-1][0] == "run"
    collected2 = window.collect_settings_from_ui()
    assert collected2.mode_id == "lobby_hitch"
    assert collected2.stage_targets == ["2-3"]
    assert collected2.skills == list(preset["codes"])
    window.close()


def test_wizard_mode_page_then_preset_popup_size(qapp):
    dialog = GameStyleWizardDialog(settings=Settings())
    assert dialog.stack.currentIndex() == 0
    assert dialog.width() <= 520
    dialog._on_next()
    assert dialog.stack.currentIndex() == 1
    assert dialog.width() >= 700
    assert dialog.preset_cards


def test_selection_from_payload_roundtrip():
    raw = {"mode": "lobby_hitch", "stage1": 2, "stage2": 3, "skills": ["tl", "sdl"]}
    sel = selection_from_payload(raw)
    assert sel.mode == "lobby_hitch"
    assert sel.stage1 == 2
    assert sel.skills == ["tl", "sdl"]
