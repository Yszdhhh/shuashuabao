"""P0 确定性选择策略（蓝图 §12，纯函数）。

本模块只做一件事：把识别层输出的结构化候选，映射为有限动作枚举 + 槽位编号。

规则（与蓝图 §12 一致）：

- 技能：仅选用户预设（skill_presets）；预设未命中 → REFRESH；刷新耗尽
  （session.refreshes >= max_refreshes）→ GIVEUP / CLOSE；永不返回非预设技能槽；
- 羁绊：预设优先 → 接近合成者（set_progress 可验证字段，含 owned 成员清单）
  → 品质降级（quality_order 确定性规则）；unknown 名称绝不冒充词典内羁绊
  （只能 WAIT/REFRESH）；
- 宝物：预设 + 套装进度优先（龙珠进度必须来自可验证字段
  set_progress.members/owned）→ 品质序降级；无安全候选 → WAIT（有上限）
  → REFRESH → GIVEUP / CLOSE；
- 技能学习优先于羁绊/宝物循环（同帧多面板时由 :func:`panel_priority` 排序）。

安全不变量：

- 不读屏、不点击、无隐式全局状态、无时钟依赖——所有输入显式传入；
- 同一输入恒返回同一 :class:`PolicyDecision`（纯函数；并列优先级用固定
  tie-break：配置顺序 → 槽位 index 升序 → set 名字典序）；
- 返回值仅 :class:`PolicyAction` 枚举 + slot index（:class:`PolicyDecision`），
  绝无坐标/像素/原始文本；
- 技能 SELECT 仅当 ``slot.name in skill_presets``；羁绊/宝物 SELECT 仅当
  ``slot.name`` 非空（词典规范名）且 ``confidence >= min_confidence``——
  unknown 槽位永不直接点击；
- WAIT 有总次数上限（``max_waits``），无安全候选且 WAIT/REFRESH 均耗尽时
  必然落 GIVEUP / CLOSE，禁止无限等待；
- 总期限（时钟）在外部由执行层判定并置 ``session.deadline_exceeded``，
  本模块只做纯布尔判断。

接线（集成波）：识别层输出 PanelCandidates → ``choose_action(candidates, session)``
→ PolicyDecision；执行层只消费 ``decision.action`` + ``decision.index``，
后置确认后更新 ``SessionState`` 记账（attempts/refreshes/waits）。
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Mapping

PANEL_SKILL = "skill"
PANEL_BOND = "bond"
PANEL_TREASURE = "treasure"
VALID_PANEL_KINDS = frozenset({PANEL_SKILL, PANEL_BOND, PANEL_TREASURE})

# 合成接近度上限：need - have 落在 [1, MAX_SYNTHESIS_GAP] 才视为“接近合成”。
# 1 格之差的套装严格优先于 2 格；超过该上限不进入合成优先（避免把一个刚起步
# 的套装当作合成候选）。
MAX_SYNTHESIS_GAP = 2

# 默认品质序（与 mediator.RARITY_BANDS 对齐：红 > 橙 > 紫 > 蓝 > 白）。
# 品质带不在序中或缺失的槽位一律排最末（最差），保证确定性。
DEFAULT_QUALITY_ORDER = ("red", "orange", "purple", "blue", "white")

# 会话/动作上限默认值（蓝图 §12：技能 3 次免费刷新后放弃；WAIT 有总次数上限；
# 每个 panel episode 有尝试上限）。集成波可用配置覆盖。
DEFAULT_MAX_ATTEMPTS = 12
DEFAULT_MAX_REFRESHES = 3
DEFAULT_MAX_WAITS = 5


class PolicyAction(str, Enum):
    """有限动作枚举。执行层只接受该枚举 + 槽位编号。"""

    SELECT_SLOT = "SELECT_SLOT"  # 点击槽位（index 见 PolicyDecision.index）
    REFRESH = "REFRESH"          # 刷新面板
    GIVEUP = "GIVEUP"            # 放弃面板（面板存在放弃按钮）
    CLOSE = "CLOSE"              # 关闭面板（无放弃按钮 / 必须退出）
    WAIT = "WAIT"                # 本 tick 不输入，下一 tick 重观察（有上限）
    NONE = "NONE"                # 无面板/无候选：什么都不做


@dataclass(frozen=True)
class PolicyDecision:
    """策略输出：动作 + 槽位编号 + trace 理由。"""

    action: PolicyAction
    index: int | None = None
    reason: str = ""

    @classmethod
    def select(cls, index: int, reason: str = "") -> "PolicyDecision":
        return cls(PolicyAction.SELECT_SLOT, int(index), reason)


@dataclass(frozen=True)
class SlotCandidate:
    """识别层输出的单个候选槽位（结构化；绝不含像素坐标）。"""

    index: int
    name: str | None = None       # 词典规范名；None 表示 unknown（绝不可点击）
    confidence: float = 0.0
    evidence: str = ""            # trace：证据说明（ROI/锚点/帧号等）
    rarity: str | None = None     # 品质带（red/orange/purple/blue/white 或 SSR/SR/R/N…）


@dataclass(frozen=True)
class PolicySettings:
    """策略配置（预设/品质序）。所有字段显式传入，缺省用保守默认。"""

    skill_presets: tuple[str, ...] = ()
    bond_presets: tuple[str, ...] = ()
    treasure_presets: tuple[str, ...] = ()
    quality_order: tuple[str, ...] = DEFAULT_QUALITY_ORDER
    min_confidence: float = 0.0   # 可点击下限；低于该置信度的槽位不可选

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "PolicySettings":
        """从任意映射（如 settings 配置对象/JSON）确定性构造。

        未知键忽略；缺失键取默认；列表顺序即用户配置顺序（有意义，不排序）。
        """
        if raw is None:
            return cls()
        if isinstance(raw, PolicySettings):
            return raw
        qo = raw.get("quality_order")
        return cls(
            skill_presets=tuple(str(s) for s in raw.get("skill_presets", ())),
            bond_presets=tuple(str(s) for s in raw.get("bond_presets", ())),
            treasure_presets=tuple(str(s) for s in raw.get("treasure_presets", ())),
            quality_order=(
                tuple(str(s) for s in qo) if qo is not None else DEFAULT_QUALITY_ORDER
            ),
            min_confidence=float(raw.get("min_confidence", 0.0)),
        )


@dataclass(frozen=True)
class SessionState:
    """本次 panel episode 会话记账（由执行层维护并传入；本模块只读）。

    attempts = 已执行的 UI 动作数（SELECT/REFRESH/GIVEUP/CLOSE）；WAIT 不计入
    （不改变 UI）。总期限（时钟）由执行层判定后置 ``deadline_exceeded``。
    """

    attempts: int = 0
    refreshes: int = 0
    waits: int = 0
    deadline_exceeded: bool = False
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    max_refreshes: int = DEFAULT_MAX_REFRESHES
    max_waits: int = DEFAULT_MAX_WAITS

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "SessionState":
        if raw is None:
            return cls()
        if isinstance(raw, SessionState):
            return raw
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})


@dataclass(frozen=True)
class PanelCandidates:
    """识别层输出的单面板候选。逐面板调用；同帧多面板排序见 :func:`panel_priority`。

    ``refresh_count``：识别层可验证的“本面板已刷新次数”（可为 0）；
    与 ``SessionState.refreshes`` 的关系见 :func:`choose_action`。
    """

    panel_kind: str | None = None  # "skill" | "bond" | "treasure"；None → NONE
    slots: tuple[SlotCandidate, ...] = ()
    set_progress: Mapping[str, Mapping[str, Any]] | None = None
    refresh_count: int = 0
    has_giveup: bool = False
    settings: PolicySettings | Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.panel_kind is not None and self.panel_kind not in VALID_PANEL_KINDS:
            raise ValueError(
                f"panel_kind={self.panel_kind!r} not in {sorted(VALID_PANEL_KINDS)}"
            )
        # 槽位既接受 SlotCandidate 也接受字典形态 {index, name, confidence,
        # evidence, rarity}（契约文档形态）；确定性：按 index 升序归一。
        object.__setattr__(
            self,
            "slots",
            tuple(
                sorted(
                    (_coerce_slot(s) for s in self.slots),
                    key=lambda s: int(s.index),
                )
            ),
        )
        # 确定性：配置归一为不可变 PolicySettings。
        if not isinstance(self.settings, PolicySettings):
            object.__setattr__(
                self, "settings", PolicySettings.from_mapping(self.settings)
            )


def _coerce_slot(raw: Any) -> SlotCandidate:
    """SlotCandidate 或字典形态 → SlotCandidate；其它类型直接报错（fail-fast）。"""
    if isinstance(raw, SlotCandidate):
        return raw
    if isinstance(raw, Mapping):
        known = {"index", "name", "confidence", "evidence", "rarity"}
        return SlotCandidate(**{k: v for k, v in raw.items() if k in known})
    raise TypeError(
        f"slot must be SlotCandidate or mapping, got {type(raw).__name__}"
    )


def panel_priority(kinds: Any) -> str | None:
    """同帧多面板时技能优先：skill > bond > treasure（确定性固定序）。

    输入为面板种类可迭代（如 ["treasure", "skill"]）；返回应最先处理的面板
    种类；无任何面板返回 None。集成波按该顺序逐面板调用 :func:`choose_action`，
    技能面板永远先于羁绊/宝物执行。
    """
    present = set(kinds or ())
    for kind in (PANEL_SKILL, PANEL_BOND, PANEL_TREASURE):
        if kind in present:
            return kind
    return None


def choose_action(
    candidates: PanelCandidates | Mapping[str, Any],
    session: SessionState | Mapping[str, Any] | None = None,
) -> PolicyDecision:
    """把结构化候选映射为有限动作。纯函数：同输入恒同输出。

    ``session`` 缺省时以 ``candidates.refresh_count`` 作为已刷新次数
    （其余上限取默认）；显式传入 session 时以 session 记账为准
    （执行层权威计数）。返回 :class:`PolicyDecision`。
    """
    cands = (
        candidates
        if isinstance(candidates, PanelCandidates)
        else PanelCandidates(**dict(candidates))
    )
    state = (
        session
        if isinstance(session, SessionState)
        else SessionState.from_mapping(session)
    )
    if session is None:
        state = SessionState(
            refreshes=int(cands.refresh_count or 0),
            attempts=state.attempts,
            waits=state.waits,
            deadline_exceeded=state.deadline_exceeded,
            max_attempts=state.max_attempts,
            max_refreshes=state.max_refreshes,
            max_waits=state.max_waits,
        )
    settings = cands.settings
    assert isinstance(settings, PolicySettings)

    # 无面板 / 无候选 → 什么都不做。
    if cands.panel_kind is None:
        return PolicyDecision(PolicyAction.NONE, None, "无面板")

    # 全局抢占：总期限过期 / 尝试上限耗尽 → 放弃或关闭（不再做任何动作）。
    if state.deadline_exceeded or state.attempts >= state.max_attempts:
        return _giveup_or_close(
            cands,
            "总期限过期或尝试上限耗尽" if state.deadline_exceeded
            else f"尝试次数达上限 {state.max_attempts}",
        )

    if cands.panel_kind == PANEL_SKILL:
        return _decide_skill(cands, state, settings)
    return _decide_collectible(cands, state, settings)


# ---------------------------------------------------------------------------
# 技能面板：仅预设；预设未命中 → 刷新；刷新耗尽 → 放弃/关闭。
# ---------------------------------------------------------------------------
def _decide_skill(
    cands: PanelCandidates, state: SessionState, settings: PolicySettings
) -> PolicyDecision:
    preset_hit = _match_preset(cands.slots, settings.skill_presets, settings.min_confidence)
    if preset_hit is not None:
        name = _slot_name(cands.slots, preset_hit)
        return PolicyDecision.select(
            preset_hit, f"技能预设命中：{name} @ slot {preset_hit}"
        )
    # 预设不存在（含全部槽位 unknown）→ 刷新；非预设技能槽绝不返回 SELECT。
    if state.refreshes < state.max_refreshes:
        return PolicyDecision(
            PolicyAction.REFRESH,
            None,
            f"技能预设未命中（已刷新 {state.refreshes}/{state.max_refreshes}），刷新",
        )
    return _giveup_or_close(cands, "刷新耗尽仍无预设技能")


# ---------------------------------------------------------------------------
# 羁绊/宝物面板：预设 → 接近合成 → 品质降级；无安全候选 → WAIT→REFRESH→退出。
# ---------------------------------------------------------------------------
def _decide_collectible(
    cands: PanelCandidates, state: SessionState, settings: PolicySettings
) -> PolicyDecision:
    kind = cands.panel_kind
    presets = (
        settings.bond_presets if kind == PANEL_BOND else settings.treasure_presets
    )
    preset_hit = _match_preset(cands.slots, presets, settings.min_confidence)
    if preset_hit is not None:
        name = _slot_name(cands.slots, preset_hit)
        return PolicyDecision.select(
            preset_hit, f"{kind} 预设命中：{name} @ slot {preset_hit}"
        )

    synth_hit = _match_synthesis(cands, settings.min_confidence)
    if synth_hit is not None:
        name = _slot_name(cands.slots, synth_hit)
        return PolicyDecision.select(
            synth_hit, f"{kind} 套装进度优先：{name} @ slot {synth_hit}"
        )

    quality_hit = _match_quality(cands, settings)
    if quality_hit is not None:
        name = _slot_name(cands.slots, quality_hit)
        return PolicyDecision.select(
            quality_hit, f"{kind} 品质降级：{name} @ slot {quality_hit}"
        )

    # 无安全候选（全部 unknown / 置信度不足）：
    # WAIT（有上限）→ REFRESH → GIVEUP / CLOSE；禁止无限等待。
    if state.waits < state.max_waits and state.refreshes < state.max_refreshes:
        return PolicyDecision(
            PolicyAction.WAIT,
            None,
            f"{kind} 无安全候选，等待重观察（{state.waits + 1}/{state.max_waits}）",
        )
    if state.refreshes < state.max_refreshes:
        return PolicyDecision(
            PolicyAction.REFRESH,
            None,
            f"{kind} 无安全候选且 WAIT 耗尽，刷新（{state.refreshes + 1}/{state.max_refreshes}）",
        )
    return _giveup_or_close(cands, f"{kind} 无安全候选且刷新耗尽")


# ---------------------------------------------------------------------------
# 匹配原语（全部确定性；并列用固定 tie-break）。
# ---------------------------------------------------------------------------
def _match_preset(
    slots: tuple[SlotCandidate, ...], presets: tuple[str, ...], min_confidence: float
) -> int | None:
    """配置顺序优先（用户顺序有意义），同预设多槽位取最小 index。

    仅匹配名称与预设完全一致的槽位；unknown（name 为 None）永不命中。
    """
    for preset in presets:
        for slot in slots:
            if slot.name == preset and slot.confidence >= min_confidence:
                return slot.index
    return None


def _match_synthesis(cands: PanelCandidates, min_confidence: float) -> int | None:
    """接近合成者：need - have 最小（1 格优先）且不超过 MAX_SYNTHESIS_GAP。

    套装进度必须来自可验证字段
    ``set_progress[set] = {have, need, members, owned}``：
    ``owned`` 列出已拥有的成员名，缺失成员 = members - owned；
    没有 ``owned`` 就无法证明“缺哪张”→ 该套装不参与合成优先（绝不猜测，
    与龙珠进度“必须来自可验证字段”一致）。字段缺失/不可解析一律跳过。
    并列按 (gap 升序, set 名字典序, 槽位 index 升序)——与 dict 插入顺序无关。
    """
    prog = cands.set_progress
    if not prog:
        return None
    hits: list[tuple[int, str, int]] = []
    for set_name, info in prog.items():
        if not isinstance(info, Mapping):
            continue
        try:
            have = int(info.get("have", 0))
            need = int(info.get("need", 0))
        except (TypeError, ValueError):
            continue  # 字段不可验证 → 跳过
        gap = need - have
        members_raw = info.get("members")
        owned_raw = info.get("owned")
        # 成员/已拥有清单必须是名称列表（字符串会被拒绝，防字符级误拆）。
        if not isinstance(members_raw, (list, tuple, set, frozenset)) or not members_raw:
            continue
        if owned_raw is None or isinstance(owned_raw, (str, bytes)):
            continue
        if not isinstance(owned_raw, (list, tuple, set, frozenset)):
            continue
        if gap <= 0 or gap > MAX_SYNTHESIS_GAP:
            continue  # 已完成 / 差距过大 → 跳过
        members = tuple(members_raw)
        owned_set = {str(o) for o in owned_raw}
        for slot in cands.slots:
            if (
                slot.name is not None
                and slot.name in members
                and slot.name not in owned_set  # 只选缺失成员，绝不点已拥有
                and slot.confidence >= min_confidence
            ):
                hits.append((gap, str(set_name), slot.index))
    if not hits:
        return None
    hits.sort()  # (gap 升序, set 名字典序, index 升序)
    return hits[0][2]


def _match_quality(cands: PanelCandidates, settings: PolicySettings) -> int | None:
    """品质降级：quality_order 中 rank 最小者胜；未知/缺失品质带排最末。

    仅词典内规范名（name 非空）且置信度达标者可入选——unknown 绝不点击；
    并列取最小槽位 index。
    """
    order = settings.quality_order
    best: tuple[int, int] | None = None
    for slot in cands.slots:
        if not slot.name or slot.confidence < settings.min_confidence:
            continue  # unknown / 低置信不可选
        if slot.rarity and slot.rarity in order:
            rank = order.index(slot.rarity)
        else:
            rank = len(order)  # 未知品质带 → 最差
        key = (rank, slot.index)
        if best is None or key < best:
            best = key
    return best[1] if best is not None else None


def _slot_name(slots: tuple[SlotCandidate, ...], index: int) -> str:
    for slot in slots:
        if slot.index == index and slot.name:
            return slot.name
    return f"slot{index}"


def _giveup_or_close(cands: PanelCandidates, why: str) -> PolicyDecision:
    if cands.has_giveup:
        return PolicyDecision(PolicyAction.GIVEUP, None, f"{why}，放弃")
    return PolicyDecision(PolicyAction.CLOSE, None, f"{why}，关闭面板")
