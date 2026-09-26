from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_12_launcher_exposes_temporary_advanced_cards_override() -> None:
    script = (ROOT / "live_scenario_launcher.ps1").read_text(encoding="utf-8")
    panel = script.split("function Show-HarnessSettingsPanel {", 1)[1].split("\nfunction ", 1)[0]
    assert 'Name = "cards"; Value = (Csv-Value "cards")' in panel
    assert "高级卡组成员（cards，逗号分隔）" in panel
    assert 'card_packs.advanced.dasheng.cards' in panel
    assert 'card_packs.advanced.haizeiwang.cards' in panel
    assert "填入 大圣+海贼王" in panel
    assert '$raw.cards = @($controls["cards"].Text -split' in panel
    assert "WriteAllText($path" in script
