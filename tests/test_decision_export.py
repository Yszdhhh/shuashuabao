"""live_scenario_capture export：按 elapsed 秒导出时刻切片（离线，不启动游戏）。

夹具策略：实机帧单张约 2-3MB，不能进仓库。trace 用真实结果包
（solo_ingame_chain_20260925_190942_836832）的前 6 行做解析兼容夹具
（tests/fixtures/decision_export/trace_excerpt.jsonl，约 8KB）；
帧用运行时生成的十几 KB 小 PNG，验证复制与汇总逻辑。
时间基线是采集 elapsed 秒，不是游戏顶栏时钟（尚无逐帧顶栏时钟识别函数）。
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

import tools.live_scenario_capture as live_capture

ROOT = Path(__file__).resolve().parents[1]
EXCERPT = ROOT / "tests" / "fixtures" / "decision_export" / "trace_excerpt.jsonl"


def _tiny_png(path: Path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 255, size=(12, 16, 3), dtype=np.uint8)
    assert cv2.imwrite(str(path), image)


def _make_bundle(bundle: Path) -> dict:
    """5 个 trace tick（elapsed 0/5/10/15/20s）+ 2 帧 + 2 事件。"""
    frames_dir = bundle / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    _tiny_png(frames_dir / "f0000_state_change.png", 1)
    _tiny_png(frames_dir / "f0001_action_after.png", 2)
    base_ts = 1790334613.0
    rows = []
    for tick, elapsed in enumerate([0.0, 5.0, 10.0, 15.0, 20.0], start=1):
        row: dict = {
            "tick": tick,
            "ts": base_ts + elapsed,
            "phase_before": "MAIN_LINE",
            "phase_after": "MAIN_LINE",
            "actions": [],
            "decision": None,
        }
        if tick == 3:
            row["actions"] = [{
                "intent": "key:h", "reason": "OpenBlackMerchantForWood",
                "ok": True, "action_ms": 12.0,
            }]
            row["decision"] = "act:OpenBlackMerchantForWood"
            row["decision_reasons"] = [{
                "kind": "merchant", "rule": "按H打开黑商",
                "inputs": {"want": "wood", "wood": 320, "bond_occ": 3},
            }]
        rows.append(row)
    (bundle / "trace.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "bundle_id": bundle.name,
        "target": "solo_ingame_chain",
        "frames": [
            {"id": "f0000_state_change", "at_s": 8.0, "file": "frames/f0000_state_change.png"},
            {"id": "f0001_action_after", "at_s": 12.0, "file": "frames/f0001_action_after.png"},
        ],
        "events": [
            {"event_id": "e0000", "at_s": 8.0, "frame_before": "f0000_state_change",
             "frame_after": None, "action": None},
            {"event_id": "e0001", "at_s": 12.0, "frame_before": "f0000_state_change",
             "frame_after": "f0001_action_after",
             "action": {"reason": "OpenBlackMerchantForWood"}},
        ],
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return manifest


def test_export_selects_window_by_elapsed_seconds(tmp_path: Path) -> None:
    bundle = tmp_path / "solo_run"
    _make_bundle(bundle)

    out = live_capture.export_moment_bundle(bundle, "10s", window_s=6.0)

    assert out == bundle / "exports" / "10s"
    sliced = [json.loads(line) for line in (out / "trace_slice.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["tick"] for row in sliced] == [2, 3, 4]
    # 含 decision_reasons 的行原样保留
    assert sliced[1]["decision_reasons"] == [{
        "kind": "merchant", "rule": "按H打开黑商",
        "inputs": {"want": "wood", "wood": 320, "bond_occ": 3},
    }]
    assert {path.name for path in (out / "frames").iterdir()} == {
        "f0000_state_change.png", "f0001_action_after.png",
    }
    events = json.loads((out / "events_slice.json").read_text(encoding="utf-8"))
    assert [event["event_id"] for event in events] == ["e0000", "e0001"]
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "按H打开黑商" in summary
    assert "采集 elapsed 秒" in summary
    assert "| 10.0s | 3 " in summary


def test_export_accepts_mm_ss_and_cli(tmp_path: Path) -> None:
    bundle = tmp_path / "solo_run"
    _make_bundle(bundle)

    out = live_capture.export_moment_bundle(bundle, "00:10", window_s=6.0)
    assert out == bundle / "exports" / "00_10"

    assert live_capture.main([
        "export", "--run", str(bundle), "--at", "10s", "--window", "6",
    ]) == 0


def test_export_parses_real_trace_excerpt_without_decision_reasons(tmp_path: Path) -> None:
    """真实包的前 6 行（尚无 decision_reasons 字段）也能导出，原因列写"无"。"""
    assert EXCERPT.exists()
    bundle = tmp_path / "real_excerpt"
    frames_dir = bundle / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    _tiny_png(frames_dir / "f0000_state_change.png", 7)
    (bundle / "trace.jsonl").write_text(EXCERPT.read_text(encoding="utf-8"), encoding="utf-8")
    rows = [json.loads(line) for line in EXCERPT.read_text(encoding="utf-8").splitlines()]
    base_elapsed = 2.0
    (bundle / "manifest.json").write_text(json.dumps({
        "bundle_id": bundle.name,
        "target": "solo_ingame_chain",
        "frames": [{"id": "f0000_state_change", "at_s": base_elapsed,
                    "file": "frames/f0000_state_change.png"}],
        "events": [{"event_id": "e0000", "at_s": base_elapsed,
                    "frame_before": "f0000_state_change",
                    "frame_after": None, "action": None}],
    }, ensure_ascii=False), encoding="utf-8")

    out = live_capture.export_moment_bundle(bundle, f"{base_elapsed}s", window_s=30.0)

    sliced = [json.loads(line) for line in (out / "trace_slice.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(sliced) == len(rows)
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "无" in summary


def test_export_rejects_bad_input(tmp_path: Path) -> None:
    bundle = tmp_path / "solo_run"
    _make_bundle(bundle)

    with pytest.raises(ValueError):
        live_capture.export_moment_bundle(bundle, "not-a-time")
    with pytest.raises(ValueError):
        live_capture.export_moment_bundle(bundle, "100s", window_s=0.001)
    with pytest.raises(ValueError):
        live_capture.export_moment_bundle(tmp_path / "no_such_bundle", "10s")
