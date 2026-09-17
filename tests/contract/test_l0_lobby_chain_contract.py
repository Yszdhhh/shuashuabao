"""L0 大厅链契约测试。

与 `tests/test_*` 的"事后回归"不同，本套件描述的是**必须永远成立的层间契约**：
改局内（L1）代码时若无意触碰大厅判定、共享阈值或红线配置，这里立刻红。

立此套件的直接动因：commit e997b39（局内三录屏修复）在同一提交里顺手改了
`room_start.fallback`、建房弹窗断言与 `_adapt_scales` 排序，导致 8-12 上午
连发 r10（de77a19）/ r11（42f3e95）两次紧急修复大厅建房链路。当时没有任何
测试能在提交前拦住它。

四条契约：
  C1 相位链只能被自己的锚点推进（fail-closed，不得"猜"着往前跳）
  C2 局内状态污染不得改变大厅决策（层间隔离，本文件核心）
  C3 大厅锚点模板资产必须真实存在（防 config/asset 漂移）
  C4 进房/建房入口禁止颜色兜底（用户红线：不得复活"快速加入"/蓝按钮）
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from shuabao.mediator import Mediator, Phase  # noqa: E402
from shuabao.settings import Settings  # noqa: E402
from shuabao.vision.capture import Frame  # noqa: E402
from shuabao.vision.matcher import MatchResult  # noqa: E402

SCENES = json.loads((ROOT / "config" / "scenes.json").read_text(encoding="utf-8"))


def _frame(width: int = 1600, height: int = 900, hwnd: int = 10001) -> Frame:
    return Frame(np.zeros((height, width, 3), dtype=np.uint8), window_title="KK", hwnd=hwnd)


def _hit(name: str, x: int = 700, y: int = 800) -> MatchResult:
    return MatchResult(name, 0.93, x, y, 120, 40, x + 60, y + 20)


def _new_mediator() -> Mediator:
    return Mediator(Settings(auto_create_room=True, dry_run=True), ROOT)


class _L0Probe:
    """把一次 L0 tick 的可观测结果收敛成可比对的元组。"""

    def __init__(self, mediator: Mediator):
        self.mediator = mediator
        self.clicks: list[tuple[str, str]] = []

    def record_click(self, hit, reason, *args, **kwargs):  # noqa: ANN001
        name = getattr(hit, "name", str(hit))
        self.clicks.append((name, reason))
        return True

    def run(self, frame: Frame, **anchors) -> tuple[str, tuple[tuple[str, str], ...]]:
        """跑一次 `_tick_l0`，返回 (相位, 本次点击序列)。"""
        before = len(self.clicks)
        with patch.object(self.mediator, "_detect_context", return_value=anchors["context"]), \
                patch.object(self.mediator, "_find_room_start", return_value=anchors.get("room_start")), \
                patch.object(self.mediator, "_find_create_confirm", return_value=anchors.get("create_confirm")), \
                patch.object(self.mediator, "_find_map_create_room", return_value=anchors.get("map_create")), \
                patch.object(self.mediator, "_find_stage_page", return_value=anchors.get("stage_page")), \
                patch.object(self.mediator, "act_click", side_effect=self.record_click):
            self.mediator._tick_l0(frame)
        return self.mediator.phase.name, tuple(self.clicks[before:])


class C1PhaseChainAnchorGated(unittest.TestCase):
    """C1：每个 L0 相位跃迁都必须由它自己的锚点触发。"""

    def test_platform_map_without_create_anchor_does_not_advance_or_click(self):
        med = _new_mediator()
        med.set_phase(Phase.PLATFORM_MAP, "contract")
        probe = _L0Probe(med)

        phase, clicks = probe.run(_frame(), context="PLATFORM_MAP")

        self.assertEqual(phase, "PLATFORM_MAP", "无建房锚点时不得离开 PLATFORM_MAP")
        self.assertEqual(clicks, (), "无锚点必须零输入（fail-closed）")

    def test_create_room_click_is_request_only_and_waits_for_dialog_anchor(self):
        """点了"创建房间"不等于进 CREATE_ROOM——必须等专用弹窗锚点。"""
        med = _new_mediator()
        med.set_phase(Phase.PLATFORM_MAP, "contract")
        probe = _L0Probe(med)

        phase, clicks = probe.run(_frame(), context="PLATFORM_MAP", map_create=_hit("create_room"))

        self.assertEqual(phase, "PLATFORM_MAP", "仅发出创建请求，尚未确认弹窗")
        self.assertEqual([reason for _, reason in clicks], ["CreateRoom-open"])

    def test_room_waiting_requires_room_start_anchor_before_starting(self):
        med = _new_mediator()
        med.set_phase(Phase.ROOM_WAITING, "contract")
        probe = _L0Probe(med)

        no_anchor_phase, no_anchor_clicks = probe.run(_frame(), context="ROOM_WAITING")
        self.assertEqual(no_anchor_phase, "ROOM_WAITING")
        self.assertEqual(no_anchor_clicks, (), "看不到开始按钮时不得盲点")

        phase, clicks = probe.run(_frame(), context="ROOM_WAITING", room_start=_hit("kk_start"))
        self.assertEqual(phase, "ROOM_STARTING", "拿到 room_start 锚点才能进 ROOM_STARTING")
        self.assertEqual([reason for _, reason in clicks], ["RoomStart"])

    def test_unknown_context_never_produces_input(self):
        """UNKNOWN 屏态是"零动作"，强行操作正是实跑卡死的来源。"""
        for phase in (Phase.PLATFORM_MAP, Phase.ROOM_WAITING, Phase.CREATE_ROOM):
            with self.subTest(phase=phase.name):
                med = _new_mediator()
                med.set_phase(phase, "contract")
                probe = _L0Probe(med)
                _, clicks = probe.run(_frame(), context="UNKNOWN")
                self.assertEqual(clicks, (), f"{phase.name} 在 UNKNOWN 下必须零输入")


class C2InGameStateIsolation(unittest.TestCase):
    """C2：局内（L1）状态不得泄漏进大厅（L0）决策——本仓库最易踩的回归。

    做法：同一段 L0 输入序列跑两个 Mediator，其中一个把局内状态全部污染成
    "跑了半局"的样子。两者的 (相位, 点击) 序列必须逐步一致。
    """

    # 明确属于局内的可变状态；若新增局内字段，建议一并加进来。
    INGAME_POLLUTION = {
        "_hub_label_ocr_next_at": 9e18,
        "_l1_cycle_step": "equipment",
        "_l1_cycle_owned_panel": True,
        "_l1_cycle_selected": True,
        "_l1_cycle_last_advance_at": 1.0e9,
        "_l1_cycle_step_successes": 3,
        "_panel_visit_force_advance": True,
        "_evolve_ok_this_cycle": True,
        "_evolve_fail_count": 7,
        "_evolve_feedback_pending": True,
        "_inventory_clicks_this_visit": 2,
        "_inventory_same_pt_hits": 5,
        "_inventory_next_at": 1.0e9,
        "_skill_refresh_attempts": 3,
        "_choice_session": __import__(
            "shuabao.choice_policy", fromlist=["SessionState"]
        ).SessionState(attempts=9, refreshes=3, waits=4),
        "_choice_fp_before_refresh": "0:污染|1:污染|2:污染",
        "_choice_policy_idle": True,
        "_panel_fingerprint_attempts": 4,
        "_f_draw_fingerprint": "polluted-draw",
        "_f_draw_reopen_count": 11,
        "_f_draw_backoff_until": 1.0e9,
        "_exit_rearm_attempts": 2,
        "_panel_f1_used_this_episode": True,
        "_merchant_next_at": 1.0e9,
        "_merchant_budget_retry_at": 1.0e9,
        "_merchant_kill_balance_fingerprint": "polluted",
        "_merchant_kill_balance_value": 999,
        "_pickup_next_at": 1.0e9,
        "_post_game_hud_confirmations": 7,
        "_hitch_postgame_started_at": 1.0e9,
        "_pending_archive_panel_frames": 7,
        "_post_game_archive_pending_only": True,
        "_secret_realm_hud_confirmations": 2,
        "_secret_realm_last_hud_frame_id": 12345,
        "_passenger_heirloom_for_secret": True,
        "_public_bag_fsm": __import__(
            "shuabao.policy.public_bag", fromlist=["PublicBagFSM", "PublicBagPhase"]
        ).PublicBagFSM(
            phase=__import__(
                "shuabao.policy.public_bag", fromlist=["PublicBagPhase"]
            ).PublicBagPhase.SOURCE_SELECTED,
            source_id="swallow_pill",
            source_slot=1,
            deadline=1.0e9,
            opened_by_us=True,
        ),
        "_public_bag_next_at": 1.0e9,
        "_hitch_opening_pressure_armed": True,
        "_tick_post_confirm": False,
        "_boss_challenge_scroll_signature": "polluted",
        "_boss_challenge_scroll_stable_frames": 7,
    }

    def _pollute(self, med: Mediator) -> None:
        for field, value in self.INGAME_POLLUTION.items():
            self.assertTrue(
                hasattr(med, field),
                f"{field} 不存在——局内状态被改名后请同步本契约",
            )
            setattr(med, field, value)

    def _walk_lobby_chain(self, med: Mediator) -> list[tuple[str, tuple[tuple[str, str], ...]]]:
        """走一遍 地图→建房请求→弹窗确认→房间→开始 的最短完整链。"""
        probe = _L0Probe(med)
        med.set_phase(Phase.PLATFORM_MAP, "contract")
        steps = [
            dict(context="PLATFORM_MAP"),
            dict(context="PLATFORM_MAP", map_create=_hit("create_room")),
            dict(context="ROOM_WAITING", room_start=_hit("kk_start")),
            dict(context="STAGE_SELECT", stage_page=1),
        ]
        return [probe.run(_frame(), **step) for step in steps]

    def test_lobby_chain_identical_with_and_without_ingame_pollution(self):
        clean = _new_mediator()
        polluted = _new_mediator()
        self._pollute(polluted)

        self.assertEqual(
            self._walk_lobby_chain(clean),
            self._walk_lobby_chain(polluted),
            "局内状态改变了大厅决策序列——层间隔离被破坏",
        )

    def test_ingame_pollution_does_not_unlock_create_room_gate(self):
        """已发出的建房请求门闩不得被局内计数器/时间戳绕过。"""
        med = _new_mediator()
        med.set_phase(Phase.PLATFORM_MAP, "contract")
        probe = _L0Probe(med)
        probe.run(_frame(), context="PLATFORM_MAP", map_create=_hit("create_room"))
        attempts_after_request = med._create_room_attempts

        self._pollute(med)
        _, clicks = probe.run(_frame(), context="PLATFORM_MAP", map_create=_hit("create_room"))

        self.assertEqual(clicks, (), "门闩期内不得再次点击创建")
        self.assertEqual(med._create_room_attempts, attempts_after_request)


class C3LobbyAnchorAssets(unittest.TestCase):
    """C3：大厅锚点依赖的模板必须真实存在（防"改配置忘了放图"）。"""

    REQUIRED_SCENES = ("map_create_room", "create_room_confirm", "room_start", "stage_page")
    IMAGES = ROOT / "assets" / "Images"

    def _resolve(self, template: str) -> Path | None:
        name = template if template.lower().endswith(".png") else f"{template}.png"
        direct = self.IMAGES / name
        if direct.is_file():
            return direct
        stem = Path(name).stem
        return next((p for p in self.IMAGES.rglob("*.png") if p.stem == stem), None)

    def test_required_lobby_scenes_declared(self):
        for scene in self.REQUIRED_SCENES:
            with self.subTest(scene=scene):
                self.assertIn(scene, SCENES["scenes"], f"scenes.json 缺少大厅锚点 {scene}")

    def test_required_lobby_templates_exist_on_disk(self):
        for scene in self.REQUIRED_SCENES:
            for template in SCENES["scenes"][scene].get("templates") or []:
                with self.subTest(scene=scene, template=template):
                    self.assertIsNotNone(
                        self._resolve(template),
                        f"{scene} 引用的模板 {template} 在 assets/Images 下找不到",
                    )


class C4EntryScenesForbidColorFallback(unittest.TestCase):
    """C4：进房/建房入口禁止颜色兜底（用户红线：不得复活"快速加入"蓝按钮）。"""

    NO_FALLBACK_SCENES = ("room_start", "map_create_room")

    def test_entry_scenes_have_null_fallback(self):
        for scene in self.NO_FALLBACK_SCENES:
            with self.subTest(scene=scene):
                self.assertIsNone(
                    SCENES["scenes"][scene].get("fallback"),
                    f"{scene}.fallback 必须为 null，禁止颜色兜底进房/建房",
                )

    def test_room_start_aliases_inherit_the_ban(self):
        for name, scene in SCENES["scenes"].items():
            if scene.get("alias_of") == "room_start":
                with self.subTest(alias=name):
                    self.assertIsNone(
                        scene.get("fallback"),
                        f"{name} 是 room_start 别名，同样禁止颜色兜底",
                    )

    def test_large_window_create_dialog_never_uses_blue_fallback(self):
        """大窗（含 1600×900 / 1328×945）即便有蓝色按钮也不得判为建房弹窗。"""
        import cv2

        med = _new_mediator()
        for width, height in ((1600, 900), (1328, 945)):
            with self.subTest(size=f"{width}x{height}"):
                image = np.zeros((height, width, 3), dtype=np.uint8)
                cv2.rectangle(
                    image,
                    (int(width * 0.45), int(height * 0.80)),
                    (int(width * 0.55), int(height * 0.86)),
                    (230, 150, 20),
                    -1,
                )
                with patch.object(med, "find_scene", return_value=None):
                    self.assertIsNone(med._find_create_confirm(Frame(image)))


if __name__ == "__main__":
    unittest.main()
