from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_choice_policy() -> None:
    path = ROOT / "src/shuabao/choice_policy.py"

    replace_once(
        path,
        '''# 羁绊/卡牌白名单语义：
#   "hard" —— 未勾选（不在 presets 内）一律不可选；三槽全未勾选 → 刷新/放弃/隐藏，
#             宁可不拿也不乱拿。用户 2026-08-12 明确要求（"海盗都明确 ban 了还是每次拿"）。
#   "soft" —— 旧行为：预设未命中时仍按套装进度/品质兜底挑一张。
WHITELIST_HARD = "hard"
WHITELIST_SOFT = "soft"
VALID_WHITELIST_MODES = frozenset({WHITELIST_HARD, WHITELIST_SOFT})

# 技能面板恒定严格：只允许已配置焦点系/卡（skill_focus_families 展开 ∪
# skill_presets），未配置一律不可选；宁可不拿也不乱拿（用户 2026-08-17 确认：
# 技能至多 4 个、无 all_round 全能档）。两字段均空 = 显式零勾选 → CLOSE；
# 非空 → 只过滤焦点集再按 skill_catalog 排序（前置/链条/存档/稀有度）。

# 必拿宝物缺省名单 = 旧版硬编码的「全能宝物」子串特权（2026-08-13 前行为：
''',
        '''# 羁绊/卡牌白名单语义：
#   "hard" —— 用户显式要求时仍可禁止预设外羁绊；系统必拿特权不受其影响。
#   "soft" —— 长程默认：预设未命中时按套装进度/品质兜底，避免三张都隐藏空手而归。
WHITELIST_HARD = "hard"
WHITELIST_SOFT = "soft"
VALID_WHITELIST_MODES = frozenset({WHITELIST_HARD, WHITELIST_SOFT})

# 真机 2026-08-16 长程证据：祝福即使没有在前端单独勾选也应直接拿。
# 子串匹配覆盖「祝福」「祝福1级/2级/3级」等规范化结果；运行时装配会把
# 这条系统特权与配置合并，因此即使旧配置缺字段也不会丢失。
DEFAULT_BOND_MUST_TAKE = ("祝福",)

# 前四个独立技能系尚未占满时允许从“已入库且 legal”的通用技能池补位；
# 四系已满后恢复严格焦点/预设升级，避免前期因神技未刷出而长期空技能槽。
DEFAULT_SKILL_SLOT_CAP = 4

# 必拿宝物缺省名单 = 旧版硬编码的「全能宝物」子串特权（2026-08-13 前行为：
''',
        "choice constants",
    )

    replace_once(
        path,
        '''    # 羁绊/卡牌白名单语义（默认硬禁用：未勾选一律不选）。
    bond_whitelist_mode: str = WHITELIST_HARD
    # 宝物负面描述模式；命中即视为负面。
''',
        '''    # 羁绊/卡牌白名单语义：长程默认 soft，预设 miss 仍可安全降级。
    bond_whitelist_mode: str = WHITELIST_SOFT
    # 系统必拿羁绊；默认祝福，运行时会与配置做不可删除的并集。
    bond_must_take: tuple[str, ...] = DEFAULT_BOND_MUST_TAKE
    # 宝物负面描述模式；命中即视为负面。
''',
        "policy bond defaults",
    )

    replace_once(
        path,
        '''    # 焦点技能系（原始勾选的主技能中文名，配置顺序即用户意图）。
    skill_focus_families: tuple[str, ...] = ()
    # 各系存档等级（不可变 (名称, 等级) 对；由 skill_catalog 消费，用于
''',
        '''    # 焦点技能系（原始勾选的主技能中文名，配置顺序即用户意图）。
    skill_focus_families: tuple[str, ...] = ()
    # 前四个独立技能系未占满时，允许目录内合法的新技能系做通用补位。
    # 直接构造默认 False 以保持纯函数旧调用兼容；运行时配置默认开启。
    skill_fill_empty_slots: bool = False
    # 各系存档等级（不可变 (名称, 等级) 对；由 skill_catalog 消费，用于
''',
        "skill fill setting",
    )

    replace_once(
        path,
        '''        must_take = raw.get("treasure_must_take")
        habit_raw = raw.get("habit_name_scores") or {}
''',
        '''        must_take = raw.get("treasure_must_take")
        bond_must_take = raw.get("bond_must_take")
        habit_raw = raw.get("habit_name_scores") or {}
''',
        "from mapping bond must take raw",
    )

    replace_once(
        path,
        '''            bond_whitelist_mode=WHITELIST_HARD if bond_mode is None else str(bond_mode),
            treasure_negative_patterns=(
''',
        '''            bond_whitelist_mode=WHITELIST_SOFT if bond_mode is None else str(bond_mode),
            bond_must_take=tuple(dict.fromkeys(
                DEFAULT_BOND_MUST_TAKE
                + tuple(str(s) for s in (bond_must_take or ()))
            )),
            treasure_negative_patterns=(
''',
        "from mapping soft and must take",
    )

    replace_once(
        path,
        '''            skill_focus_families=tuple(
                str(s) for s in (raw.get("skill_focus_families") or ())
            ),
            skill_archive_levels=normalize_archive_levels(
''',
        '''            skill_focus_families=tuple(
                str(s) for s in (raw.get("skill_focus_families") or ())
            ),
            skill_fill_empty_slots=bool(raw.get("skill_fill_empty_slots", False)),
            skill_archive_levels=normalize_archive_levels(
''',
        "from mapping skill fill",
    )

    replace_once(
        path,
        '''    raw = dict(policy_doc or {})
    bond_cfg = raw.get("bond") if isinstance(raw.get("bond"), Mapping) else {}
    treasure_cfg = raw.get("treasure") if isinstance(raw.get("treasure"), Mapping) else {}
''',
        '''    raw = dict(policy_doc or {})
    skill_cfg = raw.get("skill") if isinstance(raw.get("skill"), Mapping) else {}
    bond_cfg = raw.get("bond") if isinstance(raw.get("bond"), Mapping) else {}
    treasure_cfg = raw.get("treasure") if isinstance(raw.get("treasure"), Mapping) else {}
''',
        "assemble skill cfg",
    )

    replace_once(
        path,
        '''            "skill_focus_families": tuple(skill_families),
            "skill_archive_levels": getattr(settings, "skill_archive_levels", None),
            "bond_presets": tuple(bond_presets),
            "treasure_presets": (),
            "quality_order": raw.get("quality_order"),
            "min_confidence": 0.60 if min_conf is None else min_conf,
            "bond_whitelist_mode": bond_cfg.get("whitelist_mode", WHITELIST_HARD),
            "treasure_negative_patterns": treasure_cfg.get("negative_patterns"),
''',
        '''            "skill_focus_families": tuple(skill_families),
            "skill_fill_empty_slots": bool(skill_cfg.get("fill_empty_slots", True)),
            "skill_archive_levels": getattr(settings, "skill_archive_levels", None),
            "bond_presets": tuple(bond_presets),
            "treasure_presets": (),
            "quality_order": raw.get("quality_order"),
            "min_confidence": 0.60 if min_conf is None else min_conf,
            "bond_whitelist_mode": (
                getattr(settings, "bond_whitelist_mode", None)
                or bond_cfg.get("whitelist_mode", WHITELIST_SOFT)
            ),
            "bond_must_take": tuple(dict.fromkeys(
                DEFAULT_BOND_MUST_TAKE
                + tuple(str(s) for s in (getattr(settings, "bond_must_take", None) or ()))
                + tuple(str(s) for s in (bond_cfg.get("must_take_names") or ()))
            )),
            "treasure_negative_patterns": treasure_cfg.get("negative_patterns"),
''',
        "assemble runtime liveness settings",
    )

    replace_once(
        path,
        '''    ranked.sort()
    return [int(entry[5]) for entry in ranked]


def _decide_skill(
''',
        '''    ranked.sort()
    return [int(entry[5]) for entry in ranked]


def _rank_skill_fill_candidates(
    slots: tuple[SlotCandidate, ...],
    settings: PolicySettings,
    owned: tuple[str, ...],
) -> list[int]:
    """Rank safe *new-family* skills used only while fewer than four families exist.

    This fallback is deliberately narrower than "click any readable text": a card must
    exist in the verified skill catalog, pass the normal legality checks, and belong
    to a family not already confirmed in this round.  It therefore fills empty skill
    slots without turning OCR uncertainty into click authority.
    """
    owned_set = owned_families(owned)
    if len(owned_set) >= DEFAULT_SKILL_SLOT_CAP:
        return []
    ranked: list[tuple[int, int, int, int, int]] = []
    for slot in slots:
        if not slot.name or slot.confidence < settings.min_confidence:
            continue
        card = lookup_card(slot.name)
        if card is None:
            continue
        fam = canonical_family(str(card.get("family") or "")) or family_of(slot.name)
        if not fam or fam in owned_set:
            continue
        if not is_skill_choice_legal(slot.name, owned):
            continue
        level = slot.skill_level
        if level is None and slot.card_fact is not None:
            level = getattr(slot.card_fact, "skill_level", None)
        new_flag = bool(slot.is_new or (slot.card_fact and getattr(slot.card_fact, "is_new", False)))
        ranked.append(
            (
                _skill_effective_rarity_rank(slot, settings),
                skill_chain_rank(slot.name, owned, settings.skill_archive_levels),
                0 if new_flag else 1,
                -int(level or 0),
                int(slot.index),
            )
        )
    ranked.sort()
    return [entry[4] for entry in ranked]


def _decide_skill(
''',
        "insert skill fill ranking",
    )

    replace_once(
        path,
        '''    if ranked:
        index = ranked[0]
        name = _slot_name(cands.slots, index)
        rarity = _slot_rarity(cands.slots, index) or "未知品质"
        return PolicyDecision.select(
            index,
            f"技能严格命中（前置/存档/稀有度优先）：{name}/{rarity} @ slot {index}",
        )
    unread = _all_skill_names_missing(cands.slots)
''',
        '''    if ranked:
        index = ranked[0]
        name = _slot_name(cands.slots, index)
        rarity = _slot_rarity(cands.slots, index) or "未知品质"
        return PolicyDecision.select(
            index,
            f"技能严格命中（前置/存档/稀有度优先）：{name}/{rarity} @ slot {index}",
        )
    owned_family_count = len(owned_families(cands.owned_skill_cards))
    if settings.skill_fill_empty_slots and owned_family_count < DEFAULT_SKILL_SLOT_CAP:
        fill_ranked = _rank_skill_fill_candidates(
            cands.slots, settings, cands.owned_skill_cards
        )
        if fill_ranked:
            index = fill_ranked[0]
            name = _slot_name(cands.slots, index)
            rarity = _slot_rarity(cands.slots, index) or "未知品质"
            return PolicyDecision.select(
                index,
                f"技能槽未满（{owned_family_count}/{DEFAULT_SKILL_SLOT_CAP}），"
                f"通用安全补位：{name}/{rarity} @ slot {index}",
            )
    unread = _all_skill_names_missing(cands.slots)
''',
        "skill fill decision",
    )

    replace_once(
        path,
        '''    else:
        eligible = cands.slots
    preset_hit = _match_preset(
''',
        '''    else:
        eligible = cands.slots
        if kind == PANEL_BOND:
            # 系统必拿优先于 whitelist；"祝福" 子串覆盖祝福1/2/3级。
            for slot in eligible:
                if (
                    slot.confidence >= settings.min_confidence
                    and _is_must_take(slot.name, settings.bond_must_take)
                ):
                    return PolicyDecision.select(
                        slot.index,
                        f"羁绊系统必拿【{slot.name}】 @ slot {slot.index}",
                    )
    preset_hit = _match_preset(
''',
        "bond must take before whitelist",
    )


def patch_settings() -> None:
    path = ROOT / "src/shuabao/settings.py"
    replace_once(
        path,
        '''    skills: list[str] = field(default_factory=lambda: ["jq", "pg"])
    cards: list[str] = field(default_factory=list)
    # 负面宝物放行名单（拿了会断资源/断成长的卡，默认一张都不选）。
''',
        '''    skills: list[str] = field(default_factory=lambda: ["jq", "pg"])
    cards: list[str] = field(default_factory=list)
    # 羁绊长程默认 soft；祝福为系统必拿，即使旧 UI/旧配置没有单独勾选。
    bond_whitelist_mode: str = "soft"
    bond_must_take: list[str] = field(default_factory=lambda: ["祝福"])
    # 负面宝物放行名单（拿了会断资源/断成长的卡，默认一张都不选）。
''',
        "settings bond fields",
    )
    replace_once(
        path,
        '''    panel_visible_timeout_s: float = 2.0    # 主动打开面板的可见确认窗
    ui_action_interval_s: float = 1.5       # UI-changing 输入最小间隔
    challenge_recheck_interval_s: float = 30.0  # 四挑战 ON 的周期复查间隔（钳制 5..300s）
''',
        '''    panel_visible_timeout_s: float = 2.0    # 主动打开面板的可见确认窗
    ui_action_interval_s: float = 1.5       # UI-changing 输入最小间隔
    panel_reopen_cooldown_s: float = 12.0   # 物理隐藏确认后，同类 G/F/V 主动重开冷却（10..15s）
    challenge_recheck_interval_s: float = 30.0  # 四挑战 ON 的周期复查间隔（钳制 5..300s）
''',
        "settings panel cooldown field",
    )
    replace_once(
        path,
        '''                    elif k in ("skills", "cards", "stage_targets", "treasure_allow_negative"):
                        clean[k] = []
''',
        '''                    elif k in ("skills", "cards", "stage_targets", "treasure_allow_negative", "bond_must_take"):
                        clean[k] = []
''',
        "settings None list cleanup",
    )
    replace_once(
        path,
        '''            "cjb_boss", "sgzx_boss", "window_title_contains",
            "ocr_repo_root", "images_dir",
''',
        '''            "cjb_boss", "sgzx_boss", "window_title_contains",
            "ocr_repo_root", "images_dir", "bond_whitelist_mode",
''',
        "settings string fields",
    )
    replace_once(
        path,
        '''            "recovery_retry_interval_s", "panel_visible_timeout_s",
            "ui_action_interval_s", "incident_sample_rate",
            "challenge_recheck_interval_s",
''',
        '''            "recovery_retry_interval_s", "panel_visible_timeout_s",
            "ui_action_interval_s", "panel_reopen_cooldown_s", "incident_sample_rate",
            "challenge_recheck_interval_s",
''',
        "settings float fields",
    )
    replace_once(
        path,
        '''            "panel_visible_timeout_s": (0.5, 10.0),
            "ui_action_interval_s": (0.5, 10.0),
            "incident_sample_rate": (0.0, 1.0),
''',
        '''            "panel_visible_timeout_s": (0.5, 10.0),
            "ui_action_interval_s": (0.5, 10.0),
            "panel_reopen_cooldown_s": (10.0, 15.0),
            "incident_sample_rate": (0.0, 1.0),
''',
        "settings cooldown range",
    )
    replace_once(
        path,
        '''        # 负面宝物放行名单：只接受字符串列表；类型不对一律回落为空（不放行任何负面卡）。
        if "treasure_allow_negative" in clean:
''',
        '''        # 羁绊系统必拿扩展：用户列表只能追加，不能移除系统默认“祝福”。
        if "bond_must_take" in clean:
            raw_bond_must = clean["bond_must_take"]
            if isinstance(raw_bond_must, (list, tuple)):
                items = [str(v).strip() for v in raw_bond_must if str(v).strip()]
                clean["bond_must_take"] = list(dict.fromkeys(["祝福", *items]))
            elif fallback is not None:
                clean.pop("bond_must_take")
            else:
                clean["bond_must_take"] = ["祝福"]
        if "bond_whitelist_mode" in clean:
            mode = str(clean["bond_whitelist_mode"]).strip().lower()
            if mode in {"soft", "hard"}:
                clean["bond_whitelist_mode"] = mode
            else:
                clean.pop("bond_whitelist_mode")
        # 负面宝物放行名单：只接受字符串列表；类型不对一律回落为空（不放行任何负面卡）。
        if "treasure_allow_negative" in clean:
''',
        "settings bond validation",
    )


def patch_configs() -> None:
    default_path = ROOT / "config/default_settings.json"
    data = json.loads(default_path.read_text(encoding="utf-8"))
    data["bond_whitelist_mode"] = "soft"
    data["bond_must_take"] = ["祝福"]
    data["panel_reopen_cooldown_s"] = 12.0
    default_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    policy_path = ROOT / "config/choice_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy.setdefault("skill", {})["fill_empty_slots"] = True
    policy["skill"]["fill_slot_cap"] = 4
    policy.setdefault("bond", {})["whitelist_mode"] = "soft"
    policy["bond"]["must_take_names"] = ["祝福"]
    policy["bond"]["_note"] = (
        "长程默认 soft：预设优先；预设 miss 按套装/品质安全降级。祝福为系统必拿，"
        "不依赖前端勾选；显式 hard 仍不得拦截系统必拿。"
    )
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch_mediator() -> None:
    path = ROOT / "src/shuabao/mediator.py"
    replace_once(
        path,
        '''        self._panel_fingerprint: tuple | None = None
        self._panel_fingerprint_attempts = 0
        self._panel_f1_used_this_episode = False
''',
        '''        self._panel_fingerprint: tuple | None = None
        self._panel_fingerprint_attempts = 0
        # SendInput accepted != card consumed.  Track the semantic action until
        # WAIT_MUTATION proves a panel mutation/disappearance.
        self._panel_pending_choice_action: str | None = None  # select/close/refresh
        self._panel_pending_choice_fingerprint: tuple | None = None
        self._panel_f1_used_this_episode = False
''',
        "mediator pending choice fields",
    )

    replace_once(
        path,
        '''        target = getattr(self, "_choice_target", None)
        target = target or self._l1_cycle_step

        # 技能 G：核心，持续到无可选项后才进入羁绊。
''',
        '''        target = getattr(self, "_choice_target", None)
        target = target or self._l1_cycle_step
        if target in ("skill", "bond", "treasure"):
            reopen_at = self._panel_cooldown_until.get(target, 0.0)
            if now < reopen_at:
                remaining = reopen_at - now
                print(f"[L1] {target} 物理隐藏后主动重开冷却中（剩余 {remaining:.1f}s）")
                if target == self._l1_cycle_step:
                    self._advance_l1_cycle(target)
                return LoopAction.Continue

        # 技能 G：核心，持续到无可选项后才进入羁绊。
''',
        "proactive panel reopen cooldown",
    )

    replace_once(
        path,
        '''    def _enter_panel_episode(self, frame: Frame, anchor: MatchResult, kind: str, opened: bool) -> None:
        """进入 ACTIVE 会话：记录 kind/指纹起点；主动打开的面板计 episode 数。"""
        self._panel_state = PanelState.ACTIVE
        self._panel_kind = kind
        self._panel_episode_started = time.time()
        self._panel_mutation_baseline = None
        self._panel_f1_used_this_episode = False
        self._clear_pending_skill_cards()
''',
        '''    @staticmethod
    def _panel_choice_action_kind(hit_name: str | None) -> str:
        text = str(hit_name or "").lower()
        if "refresh" in text:
            return "refresh"
        if any(token in text for token in ("hide", "close", "giveup")):
            return "close"
        return "select"

    def _arm_panel_reopen_cooldown(self, kind: str | None, now: float) -> None:
        if kind not in ("skill", "bond", "treasure"):
            return
        delay = max(10.0, min(15.0, float(getattr(self.settings, "panel_reopen_cooldown_s", 12.0))))
        self._panel_cooldown_until[kind] = max(
            self._panel_cooldown_until.get(kind, 0.0), now + delay
        )

    def _stage_panel_choice_action(self, action: str, fingerprint: tuple | None) -> None:
        self._panel_pending_choice_action = action
        self._panel_pending_choice_fingerprint = fingerprint

    def _confirm_panel_choice_action(self, now: float) -> None:
        action = self._panel_pending_choice_action
        if action == "select":
            if (
                self._l1_cycle_owned_panel
                and self._panel_kind == self._l1_cycle_step
                and self._panel_kind in ("skill", "bond", "treasure")
            ):
                self._l1_cycle_selected = True
            if self._panel_kind == "skill":
                # Only a *confirmed* skill selection may bypass normal reopen cadence.
                self._last_skill_panel = 0.0
        elif action == "close":
            self._arm_panel_reopen_cooldown(self._panel_kind, now)
        self._panel_pending_choice_action = None
        self._panel_pending_choice_fingerprint = None

    def _expire_panel_choice_action(self) -> str | None:
        action = self._panel_pending_choice_action
        self._panel_pending_choice_action = None
        self._panel_pending_choice_fingerprint = None
        return action

    def _enter_panel_episode(self, frame: Frame, anchor: MatchResult, kind: str, opened: bool) -> None:
        """进入 ACTIVE 会话：记录 kind/指纹起点；主动打开的面板计 episode 数。"""
        self._panel_state = PanelState.ACTIVE
        self._panel_kind = kind
        self._panel_episode_started = time.time()
        self._panel_mutation_baseline = None
        self._panel_pending_choice_action = None
        self._panel_pending_choice_fingerprint = None
        self._panel_f1_used_this_episode = False
        self._clear_pending_skill_cards()
''',
        "panel semantic action helpers",
    )

    replace_once(
        path,
        '''        self._panel_fingerprint = None
        self._panel_fingerprint_attempts = 0
        self._panel_opened_by_us = None
''',
        '''        self._panel_fingerprint = None
        self._panel_fingerprint_attempts = 0
        self._panel_pending_choice_action = None
        self._panel_pending_choice_fingerprint = None
        self._panel_opened_by_us = None
''',
        "finish clears pending choice",
    )

    replace_once(
        path,
        '''                    # 技能选卡点击成功 → 暂存卡名，等 WAIT_MUTATION 确认后才计入已学
                    # （刷新/放弃/关闭/隐藏不算选卡；未确认点击超时只清暂存不记账）。
                    if kind == "技能" and self._is_skill_card_click(hit.name):
                        self._stage_skill_card(hit.name)
                    if (
                        self._l1_cycle_owned_panel
                        and self._panel_kind == self._l1_cycle_step
                        and "refresh" not in hit.name.lower()
                            and "giveup" not in hit.name.lower()
                            and "close" not in hit.name.lower()
                            and "hide" not in hit.name.lower()
                        and (
                            self._panel_kind != "skill"
                            or Path(hit.name).stem
                            in {Path(name).stem for name in self.settings.skills}
                        )
                    ):
                        self._l1_cycle_selected = True
                    self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
''',
        '''                    action_kind = self._panel_choice_action_kind(hit.name)
                    self._stage_panel_choice_action(action_kind, fingerprint)
                    # 技能选卡点击成功只暂存；必须等 mutation/面板消失后才记为已学。
                    if action_kind == "select" and kind == "技能" and self._is_skill_card_click(hit.name):
                        self._stage_skill_card(hit.name)
                    self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
''',
        "do not confirm selection on SendInput",
    )

    replace_once(
        path,
        '''                    else:
                        if kind == "技能":
                            # 配置技能成功后立即再开 G，直到没有可学点数。
                            self._last_skill_panel = 0.0
                        self._panel_opened_by_us = None
''',
        '''                    else:
                        # Selection success is not known yet; WAIT_MUTATION owns
                        # both cycle success and the fast skill reopen permission.
                        self._panel_opened_by_us = None
''',
        "remove premature skill reopen success",
    )

    replace_once(
        path,
        '''                if self.act_click(close_hit, close_reason):
                    self._bump_choice_attempts()
                    self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
                    self._panel_state = PanelState.WAIT_MUTATION
                    self._panel_mutation_baseline = self._panel_roi_region(frame)
                    self._panel_last_input_at = now
''',
        '''                if self.act_click(close_hit, close_reason):
                    self._bump_choice_attempts()
                    self._stage_panel_choice_action("close", (self._panel_kind, close_hit.name))
                    self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
                    self._panel_state = PanelState.WAIT_MUTATION
                    self._panel_mutation_baseline = self._panel_roi_region(frame)
                    self._panel_last_input_at = now
''',
        "unknown close stages semantic action",
    )

    replace_once(
        path,
        '''        if st == PanelState.WAIT_MUTATION:
            if anchor is None:
                # 面板已关闭：episode 完成；已点技能卡视为确认学得。
                self._commit_pending_skill_cards()
                self._finish_panel_episode()
                return LoopAction.Continue
            if self._panel_mutation_confirmed(frame):
                # 内容变化（刷新/新候选/选卡生效）：确认学得，回到 ACTIVE 继续
                self._commit_pending_skill_cards()
                self._panel_state = PanelState.ACTIVE
                self._panel_mutation_baseline = None
                return LoopAction.Continue
            if now - self._panel_last_input_at >= self._panel_confirm_window:
                # 确认窗超时：未观察到变化 → 未确认点击不记账（回 ACTIVE，
                # 同 fingerprint 重试计数将捕获无变化点击）。
                print("[L1] 面板 mutation 确认窗超时，回到 ACTIVE（零输入）")
                self._clear_pending_skill_cards()
                self._panel_state = PanelState.ACTIVE
            return LoopAction.Continue
''',
        '''        if st == PanelState.WAIT_MUTATION:
            if anchor is None:
                # 面板消失是最强消费/关闭证据；此时才确认 semantic action。
                self._confirm_panel_choice_action(now)
                self._commit_pending_skill_cards()
                self._finish_panel_episode()
                return LoopAction.Continue
            if self._panel_mutation_confirmed(frame):
                # 内容变化（新候选/选卡消费/关闭过渡）后才确认成功。
                self._confirm_panel_choice_action(now)
                self._commit_pending_skill_cards()
                self._panel_state = PanelState.ACTIVE
                self._panel_mutation_baseline = None
                return LoopAction.Continue
            if now - self._panel_last_input_at >= self._panel_confirm_window:
                failed_action = self._expire_panel_choice_action()
                self._clear_pending_skill_cards()
                self._panel_mutation_baseline = None
                if failed_action == "select":
                    # Real-machine 2026-08-16: SendInput returned success while
                    # bond card stayed visible. Never hammer the same slot again;
                    # close this stale episode physically, then the reopen cooldown
                    # gives the UI/resource state time to settle.
                    print("[L1] 选卡点击未观察到 mutation；禁止重复同槽，转物理关闭")
                    self._panel_state = PanelState.CLOSING
                else:
                    print("[L1] 面板 mutation 确认窗超时，回到 ACTIVE（零输入）")
                    self._panel_state = PanelState.ACTIVE
            return LoopAction.Continue
''',
        "mutation confirmation semantics",
    )

    replace_once(
        path,
        '''            if self.act_click(close_hit, "PanelClose"):
                self._panel_state = PanelState.WAIT_MUTATION
                self._panel_last_input_at = now
                self._panel_mutation_baseline = self._panel_roi_region(frame)
                self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
''',
        '''            if self.act_click(close_hit, "PanelClose"):
                self._stage_panel_choice_action("close", (self._panel_kind, close_hit.name))
                self._panel_state = PanelState.WAIT_MUTATION
                self._panel_last_input_at = now
                self._panel_mutation_baseline = self._panel_roi_region(frame)
                self._selection_click_cooldown_until = now + self.settings.ui_action_interval_s
''',
        "closing stages close confirmation",
    )


def write_tests() -> None:
    path = ROOT / "tests/test_choice_liveness_20260818.py"
    path.write_text(r'''from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from shuabao.choice_policy import (
    PANEL_BOND,
    PANEL_SKILL,
    WHITELIST_HARD,
    WHITELIST_SOFT,
    PanelCandidates,
    PolicyAction,
    PolicySettings,
    SlotCandidate,
    assemble_policy_settings,
    choose_action,
)
from shuabao.mediator import Mediator, PanelState
from shuabao.settings import Settings
from shuabao.vision import Frame

ROOT = Path(__file__).resolve().parents[1]


def slot(index: int, name: str, *, rarity: str = "white", confidence: float = 0.99):
    return SlotCandidate(index=index, name=name, rarity=rarity, confidence=confidence)


def test_blessing_is_system_must_take_even_in_explicit_hard_mode():
    cands = PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(slot(0, "普通羁绊"), slot(1, "祝福3级", rarity="green"), slot(2, "另一羁绊")),
        settings=PolicySettings(
            bond_presets=(),
            bond_whitelist_mode=WHITELIST_HARD,
            min_confidence=0.60,
        ),
    )
    decision = choose_action(cands)
    assert decision.action == PolicyAction.SELECT_SLOT
    assert decision.index == 1
    assert "系统必拿" in decision.reason


def test_runtime_bond_default_is_soft_and_quality_falls_back():
    runtime = SimpleNamespace(
        skills=[], cards=[], skill_archive_levels={}, treasure_allow_negative=[],
        bond_whitelist_mode="soft", bond_must_take=["祝福"],
    )
    settings = assemble_policy_settings(
        settings=runtime,
        skill_labels={},
        fetter_labels={},
        policy_doc={"bond": {"whitelist_mode": "soft"}, "min_confidence": 0.60},
    )
    assert settings.bond_whitelist_mode == WHITELIST_SOFT
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_BOND,
        slots=(slot(0, "甲", rarity="blue"), slot(1, "乙", rarity="orange"), slot(2, "丙", rarity="white")),
        settings=settings,
    ))
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 1)
    assert "品质降级" in decision.reason


def test_skill_safe_fill_uses_new_catalog_family_before_four_slots():
    ps = PolicySettings(
        skill_presets=("寒冰箭",),
        skill_focus_families=("寒冰箭",),
        skill_fill_empty_slots=True,
        min_confidence=0.60,
    )
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_SKILL,
        slots=(slot(0, "奥术箭矢", rarity="blue"),),
        owned_skill_cards=("剑气", "地震", "火球"),
        settings=ps,
    ))
    assert (decision.action, decision.index) == (PolicyAction.SELECT_SLOT, 0)
    assert "技能槽未满" in decision.reason


def test_skill_safe_fill_turns_strict_after_four_families():
    ps = PolicySettings(
        skill_presets=("寒冰箭",),
        skill_focus_families=("寒冰箭",),
        skill_fill_empty_slots=True,
        min_confidence=0.60,
    )
    decision = choose_action(PanelCandidates(
        panel_kind=PANEL_SKILL,
        slots=(slot(0, "奥术箭矢", rarity="red"),),
        owned_skill_cards=("剑气", "地震", "火球", "奥数激光"),
        settings=ps,
    ))
    assert decision.action == PolicyAction.CLOSE


def test_bond_slot0_logged_screen_coordinate_matches_window_offset():
    med = object.__new__(Mediator)
    frame = Frame(np.zeros((900, 1600, 3), dtype=np.uint8), left=160, top=102)
    hit = med._choice_slot_hit(frame, "bond", 0, "ocr_bond:祝福")
    # 0.331 * 1600 -> local x=529; 0.44 * 900 -> local y=396.
    # The real-machine log (689, 498) is exactly local + HWND origin (160, 102).
    assert (hit.x, hit.y) == (529, 396)
    assert (hit.screen_x, hit.screen_y) == (689, 498)


def _semantic_mediator(action: str):
    med = object.__new__(Mediator)
    med.settings = SimpleNamespace(panel_reopen_cooldown_s=12.0)
    med._panel_cooldown_until = {}
    med._panel_pending_choice_action = action
    med._panel_pending_choice_fingerprint = ("bond", "ocr_bond:祝福", 86, 62)
    med._l1_cycle_owned_panel = True
    med._l1_cycle_step = "bond"
    med._l1_cycle_selected = False
    med._panel_kind = "bond"
    med._last_skill_panel = 30.0
    return med


def test_selection_is_not_success_until_mutation_confirmation():
    med = _semantic_mediator("select")
    assert med._l1_cycle_selected is False
    med._confirm_panel_choice_action(100.0)
    assert med._l1_cycle_selected is True
    assert med._panel_pending_choice_action is None


def test_unconfirmed_select_expires_without_becoming_success():
    med = _semantic_mediator("select")
    action = med._expire_panel_choice_action()
    assert action == "select"
    assert med._l1_cycle_selected is False
    assert med._panel_pending_choice_action is None


def test_confirmed_physical_close_arms_twelve_second_reopen_cooldown():
    med = _semantic_mediator("close")
    med._confirm_panel_choice_action(100.0)
    assert med._panel_cooldown_until["bond"] == 112.0
    assert med._l1_cycle_selected is False


def test_default_settings_persist_soft_bond_and_panel_cooldown():
    raw = json.loads((ROOT / "config/default_settings.json").read_text(encoding="utf-8"))
    assert raw["bond_whitelist_mode"] == "soft"
    assert "祝福" in raw["bond_must_take"]
    assert raw["panel_reopen_cooldown_s"] == 12.0
    loaded = Settings.load(ROOT / "config/default_settings.json")
    assert loaded.bond_whitelist_mode == "soft"
    assert loaded.bond_must_take[0] == "祝福"
    assert loaded.panel_reopen_cooldown_s == 12.0
''', encoding="utf-8")


def main() -> None:
    patch_choice_policy()
    patch_settings()
    patch_configs()
    patch_mediator()
    write_tests()
    print("choice liveness refactor applied")


if __name__ == "__main__":
    main()
