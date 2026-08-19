import sys
from shuabao.choice_policy import choose_action, PanelCandidates, SlotCandidate, PolicySettings

# 用户配置了奥术箭为焦点技能
settings = PolicySettings(
    skill_presets=("奥术箭",),
    skill_focus_families=("奥术箭",),
    quality_order=("red", "orange", "purple", "blue", "white", "green")
)

# 场景：屏幕上同时出现 爆炸箭矢 (橙), 火焰射击 (蓝/紫), 箭矢连发 (蓝)
# 只要游戏刷出来了，说明前置必然达成，直接按品质：橙 > 紫 > 蓝 抢选！
slots = [
    SlotCandidate(index=1, name="火焰射击", confidence=0.95),
    SlotCandidate(index=2, name="爆炸箭矢", confidence=0.95),
    SlotCandidate(index=3, name="箭矢连发", confidence=0.95),
]

p = PanelCandidates(panel_kind="skill", slots=slots, owned_skill_cards=["奥术箭"], settings=settings)
d = choose_action(p)
chosen = next(s for s in slots if s.index == d.target_slot)
print(f"极简直选结果 -> 槽位 {d.target_slot}: 【{chosen.name}】 | 原因: {d.reason}")
