import sys
from pathlib import Path
from shuabao.choice_policy import choose_action, PanelCandidates, SlotCandidate, PolicySettings

# 用户配置了奥术箭为焦点技能
settings = PolicySettings(
    skill_presets=("奥术箭",),
    skill_focus_families=("奥术箭",),
    quality_order=("red", "orange", "purple", "blue", "white", "green")
)

# 场景 A: 只有 爆炸箭矢, 火焰射击, 箭矢连发；此时未拥有爆炸箭矢，但已有 奥术箭 + 爆炎箭 (爆炸箭矢前置满足)
slots_1 = [
    SlotCandidate(index=1, name="爆炸箭矢", confidence=0.95),
    SlotCandidate(index=2, name="火焰射击", confidence=0.95),
    SlotCandidate(index=3, name="箭矢连发", confidence=0.95),
]
p1 = PanelCandidates(panel_kind="skill", slots=slots_1, owned_skill_cards=["奥术箭", "爆炎箭", "箭矢增幅"], settings=settings)
d1 = choose_action(p1)
chosen_1 = next(s for s in slots_1 if s.index == d1.target_slot)
print("=== 场景 A: 未拥有爆炸箭矢，爆炸箭矢 vs 火焰射击 vs 箭矢连发 ===")
print(f"-> 选中: {chosen_1.name} (槽位 {d1.target_slot}) | 原因: {d1.reason}")

# 场景 B: 已拥有爆炸箭矢 + 箭矢增幅，未拥有火箭增幅 (火焰射击前置未满足，箭矢连发前置满足)
slots_2 = [
    SlotCandidate(index=1, name="火焰射击", confidence=0.95),
    SlotCandidate(index=2, name="箭矢连发", confidence=0.95),
]
p2 = PanelCandidates(panel_kind="skill", slots=slots_2, owned_skill_cards=["奥术箭", "爆炸箭矢", "箭矢增幅"], settings=settings)
d2 = choose_action(p2)
chosen_2 = next(s for s in slots_2 if s.index == d2.target_slot)
print("\n=== 场景 B: 已有爆炸箭矢但无火箭增幅 (火焰射击未达标，箭矢连发达标) ===")
print(f"-> 选中: {chosen_2.name} (槽位 {d2.target_slot}) | 原因: {d2.reason}")

# 场景 C: 已拥有爆炸箭矢 + 火箭增幅 + 箭矢增幅 (火焰射击与箭矢连发均满足)
slots_3 = [
    SlotCandidate(index=1, name="火焰射击", confidence=0.95),
    SlotCandidate(index=2, name="箭矢连发", confidence=0.95),
]
p3 = PanelCandidates(panel_kind="skill", slots=slots_3, owned_skill_cards=["奥术箭", "爆炸箭矢", "火箭增幅", "箭矢增幅"], settings=settings)
d3 = choose_action(p3)
chosen_3 = next(s for s in slots_3 if s.index == d3.target_slot)
print("\n=== 场景 C: 已有爆炸箭矢+火箭增幅+箭矢增幅 (火焰射击与箭矢连发均达标) ===")
print(f"-> 选中: {chosen_3.name} (槽位 {d3.target_slot}) | 原因: {d3.reason}")
