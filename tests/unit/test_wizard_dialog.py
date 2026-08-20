import pytest
from PySide6.QtWidgets import QApplication
from shuabao.shell.wizard_dialog import GameStyleWizardDialog, QuickStartSelection
from shuabao.settings import Settings

@pytest.fixture(scope="session")
def qapp():
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
    
    dto = dialog.get_selection()
    assert isinstance(dto, QuickStartSelection)
    assert dto.mode in {"solo", "lobby_hitch"}
    assert isinstance(dto.skills, list)
    assert isinstance(dto.bonds, list)

def test_wizard_custom_build_switch(qapp):
    settings = Settings()
    dialog = GameStyleWizardDialog(settings=settings)
    dialog.skill_boxes[0].setCurrentText("电磁场")
    dialog._on_custom_changed()
    assert dialog.is_custom is True
    assert "自定义" in dialog.lbl_status.text()
