# -*- coding: utf-8 -*-
"""Skill KB 60-Level Expansion Updater.

Reads material from user screenshots (2026-09-02) and updates:
- config/skill_card_catalog.json
- config/skill_archive_unlocks.json
- config/skill_card_rarity.json
- config/skill_card_knowledge.json
- config/choice_lexicon.json
- dist/ShuaBao/_internal/config/...

Also exports documentation and JSON directly to:
C:/Users/10639/Desktop/存档挑战素材/技能更新/
"""

import json
import os
import shutil
from pathlib import Path

CONFIG_DIR = Path("G:/刷刷宝/GameScript-Local/config")
DIST_CONFIG_DIR = Path("G:/刷刷宝/GameScript-Local/dist/ShuaBao/_internal/config")
DESKTOP_DIR = Path(r"C:\Users\10639\Desktop\存档挑战素材\技能更新")

# 20 cards defined from screenshots
CARDS_UPDATE = [
    # 1. 普攻
    {
        "name": "箭神",
        "family": "普攻",
        "family_code": "pg",
        "set_membership": "普攻",
        "effect": "基础普攻伤害+100%，普攻额外附加300%攻击的自适应伤害",
        "prereq": "强化箭矢x2",
        "exclude": "",
        "aliases": [],
        "unlock": "56级",
        "rarity": "橙",
        "source": "user_screenshot_20260902",
    },
    # 2. 天雷
    {
        "name": "紫极天雷",
        "family": "天雷",
        "family_code": "tl",
        "set_membership": "天雷",
        "effect": "天雷命中目标后，对目标周围600范围内的随机敌人施放2次造成100%天雷伤害的紫极天雷",
        "prereq": "审判之雷",
        "exclude": "",
        "aliases": [],
        "unlock": "60级",
        "rarity": "橙",
        "source": "user_screenshot_20260902",
    },
    # 3. 闪电链
    {
        "name": "无限电流",
        "family": "闪电链",
        "family_code": "sdl",
        "set_membership": "闪电链",
        "effect": "闪电链弹射时不再忽视已命中单位(可以在两个怪之间来回弹射)",
        "prereq": "永动电流",
        "exclude": "",
        "aliases": [],
        "unlock": "60级",
        "rarity": "橙",
        "source": "user_screenshot_20260902",
    },
    # 4. 陨石
    {
        "name": "地爆天星",
        "family": "陨石",
        "family_code": "ys",
        "set_membership": "陨石",
        "effect": "每释放3次陨石，释放1次地爆天星，地爆天星会缓慢落下，下降过程中造成3次500%陨石的伤害，落地后发生爆炸，造成2000%陨石的伤害",
        "prereq": "陨石碎片,星落,毁灭陨石",
        "exclude": "",
        "aliases": [],
        "unlock": "56级",
        "rarity": "橙",
        "source": "user_screenshot_20260902",
    },
    # 5. 奥数激光
    {
        "name": "高频脉冲",
        "family": "奥数激光",
        "family_code": "asjg",
        "set_membership": "奥术激光",
        "effect": "激光闪射伤害频率翻倍，伤害翻倍，范围翻倍",
        "prereq": "激光闪射",
        "exclude": "",
        "aliases": [],
        "unlock": "56级",
        "rarity": "橙",
        "source": "user_screenshot_20260902",
    },
    # 6. 飓风
    {
        "name": "风力回旋",
        "family": "飓风",
        "family_code": "jf",
        "set_membership": "飓风",
        "effect": "飓风消失时往回再次释放1个保留所有强化的飓风",
        "prereq": "多重风暴",
        "exclude": "",
        "aliases": [],
        "unlock": "40级",
        "rarity": "绿",
        "source": "user_screenshot_20260902",
    },
    {
        "name": "强化飓风",
        "family": "飓风",
        "family_code": "jf",
        "set_membership": "飓风",
        "effect": "飓风伤害+20%",
        "prereq": "飓风增幅x3",
        "exclude": "",
        "aliases": [],
        "unlock": "43级",
        "rarity": "绿",
        "source": "user_screenshot_20260902",
    },
    {
        "name": "风暴狂潮",
        "family": "飓风",
        "family_code": "jf",
        "set_membership": "飓风",
        "effect": "飓风齐射+2",
        "prereq": "贯通之风,强袭飓风,多重风暴",
        "exclude": "",
        "aliases": [],
        "unlock": "60级",
        "rarity": "橙",
        "source": "user_screenshot_20260902",
    },
    # 7. 地震
    {
        "name": "余震",
        "family": "地震",
        "family_code": "dz",
        "set_membership": "地震",
        "effect": "地震结束后会在周围触发2次小范围造成50%地震伤害的余震",
        "prereq": "强震,地震速击,地震增幅",
        "exclude": "",
        "aliases": [],
        "unlock": "56级",
        "rarity": "橙",
        "source": "user_screenshot_20260902",
    },
    # 8. 奥数箭
    {
        "name": "次级箭",
        "family": "奥数箭",
        "family_code": "asj",
        "set_membership": "奥术箭",
        "effect": "奥术箭首次命中后，分裂出1个可以造成150%攻击[能量]魔法伤害的次级箭",
        "prereq": "箭矢增幅",
        "exclude": "",
        "aliases": [],
        "unlock": None,
        "rarity": "蓝",
        "source": "user_screenshot_20260902",
    },
    {
        "name": "强力箭矢",
        "family": "奥数箭",
        "family_code": "asj",
        "set_membership": "奥术箭",
        "effect": "奥术箭伤害+80%",
        "prereq": "箭矢增幅x2",
        "exclude": "",
        "aliases": [],
        "unlock": None,
        "rarity": "蓝",
        "source": "user_screenshot_20260902",
    },
    {
        "name": "急速抽箭",
        "family": "奥数箭",
        "family_code": "asj",
        "set_membership": "奥术箭",
        "effect": "奥术箭冷却缩减+30%",
        "prereq": "箭矢增幅,强化箭矢",
        "exclude": "爆炸箭矢",
        "aliases": [],
        "unlock": None,
        "rarity": "紫",
        "source": "user_screenshot_20260902",
    },
    {
        "name": "强化飞箭",
        "family": "奥数箭",
        "family_code": "asj",
        "set_membership": "奥术箭",
        "effect": "奥术箭伤害+20%",
        "prereq": "箭矢增幅x3",
        "exclude": "",
        "aliases": [],
        "unlock": None,
        "rarity": "白",
        "source": "user_screenshot_20260902",
    },
    {
        "name": "集束箭矢",
        "family": "奥数箭",
        "family_code": "asj",
        "set_membership": "奥术箭",
        "effect": "奥术箭发射的箭矢更加集中，奥术箭数量+1",
        "prereq": "箭矢齐射x2",
        "exclude": "",
        "aliases": [],
        "unlock": "50级",
        "rarity": "橙",
        "source": "user_screenshot_20260902",
    },
    {
        "name": "散射箭矢",
        "family": "奥数箭",
        "family_code": "asj",
        "set_membership": "奥术箭",
        "effect": "次级箭会对原本的主目标造成1次伤害再释放，次级箭数量+1",
        "prereq": "次级扩散",
        "exclude": "",
        "aliases": [],
        "unlock": "56级",
        "rarity": "橙",
        "source": "user_screenshot_20260902",
    },
    {
        "name": "奥术狂潮",
        "family": "奥数箭",
        "family_code": "asj",
        "set_membership": "奥术箭",
        "effect": "奥术箭额外释放1次，数量+2，穿透+3",
        "prereq": "箭矢齐射,箭矢连发,强力箭矢",
        "exclude": "",
        "aliases": [],
        "unlock": "60级",
        "rarity": "橙",
        "source": "user_screenshot_20260902",
    },
    # 9. 寒冰箭
    {
        "name": "冰晶爆裂",
        "family": "寒冰箭",
        "family_code": "hbj",
        "set_membership": "寒冰箭",
        "effect": "小冰箭会对原本的主目标造成1次伤害再释放，小冰箭数量+1",
        "prereq": "蚀骨冰棱",
        "exclude": "",
        "aliases": [],
        "unlock": "36级",
        "rarity": "蓝",
        "source": "user_screenshot_20260902",
    },
    {
        "name": "强化冰箭",
        "family": "寒冰箭",
        "family_code": "hbj",
        "set_membership": "寒冰箭",
        "effect": "寒冰箭伤害+20%",
        "prereq": "冰箭增幅x3",
        "exclude": "",
        "aliases": [],
        "unlock": "43级",
        "rarity": "蓝",
        "source": "user_screenshot_20260902",
    },
    {
        "name": "永冻天球",
        "family": "寒冰箭",
        "family_code": "hbj",
        "set_membership": "寒冰箭",
        "effect": "每释放5次寒冰箭，生成一个持续3秒的永冻天球，每0.5秒造成100%寒冰箭的范围伤害，并附加1层冻伤。如果目标已有5层冻伤，则清空目标冻伤层数，造成500%寒冰箭的伤害并附加0.3秒的深度冻结",
        "prereq": "",
        "exclude": "",
        "aliases": [],
        "unlock": "50级",
        "rarity": "橙",
        "source": "user_screenshot_20260902",
    },
    {
        "name": "究极冰箭",
        "family": "寒冰箭",
        "family_code": "hbj",
        "set_membership": "寒冰箭",
        "effect": "三棱冰箭造成的伤害提高50%",
        "prereq": "三棱冰箭",
        "exclude": "",
        "aliases": [],
        "unlock": "60级",
        "rarity": "橙",
        "source": "user_screenshot_20260902",
    },
]

# Archive unlocks by skill_id
ARCHIVE_UNLOCK_ITEMS = {
    "pg": [
        {
            "level": 56,
            "level_status": "verified",
            "kind": "unlock_card",
            "payload": {"card": "箭神"},
            "text": "解锁卡牌：箭神",
            "source": {"screenshot": "user_20260902_skill_update"},
        }
    ],
    "tl": [
        {
            "level": 60,
            "level_status": "verified",
            "kind": "unlock_card",
            "payload": {"card": "紫极天雷"},
            "text": "解锁卡牌：紫极天雷",
            "source": {"screenshot": "user_20260902_skill_update"},
        }
    ],
    "sdl": [
        {
            "level": 60,
            "level_status": "verified",
            "kind": "unlock_card",
            "payload": {"card": "无限电流"},
            "text": "解锁卡牌：无限电流",
            "source": {"screenshot": "user_20260902_skill_update"},
        }
    ],
    "ys": [
        {
            "level": 56,
            "level_status": "verified",
            "kind": "unlock_card",
            "payload": {"card": "地爆天星"},
            "text": "解锁卡牌：地爆天星",
            "source": {"screenshot": "user_20260902_skill_update"},
        }
    ],
    "asjg": [
        {
            "level": 56,
            "level_status": "verified",
            "kind": "unlock_card",
            "payload": {"card": "高频脉冲"},
            "text": "解锁卡牌：高频脉冲",
            "source": {"screenshot": "user_20260902_skill_update"},
        }
    ],
    "jf": [
        {
            "level": 60,
            "level_status": "verified",
            "kind": "unlock_card",
            "payload": {"card": "风暴狂潮"},
            "text": "解锁卡牌：风暴狂潮",
            "source": {"screenshot": "user_20260902_skill_update"},
        }
    ],
    "dz": [
        {
            "level": 56,
            "level_status": "verified",
            "kind": "unlock_card",
            "payload": {"card": "余震"},
            "text": "解锁卡牌：余震",
            "source": {"screenshot": "user_20260902_skill_update"},
        }
    ],
    "asj": [
        {
            "level": 56,
            "level_status": "verified",
            "kind": "unlock_card",
            "payload": {"card": "散射箭矢"},
            "text": "解锁卡牌：散射箭矢",
            "source": {"screenshot": "user_20260902_skill_update"},
        },
        {
            "level": 60,
            "level_status": "verified",
            "kind": "unlock_card",
            "payload": {"card": "奥术狂潮"},
            "text": "解锁卡牌：奥术狂潮",
            "source": {"screenshot": "user_20260902_skill_update"},
        },
    ],
    "hbj": [
        {
            "level": 50,
            "level_status": "verified",
            "kind": "unlock_card",
            "payload": {"card": "永冻天球"},
            "text": "解锁卡牌：永冻天球",
            "source": {"screenshot": "user_20260902_skill_update"},
        },
        {
            "level": 60,
            "level_status": "verified",
            "kind": "unlock_card",
            "payload": {"card": "究极冰箭"},
            "text": "解锁卡牌：究极冰箭",
            "source": {"screenshot": "user_20260902_skill_update"},
        },
    ],
}


def update_catalog():
    path = CONFIG_DIR / "skill_card_catalog.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    existing_map = {c["name"]: c for c in data["cards"]}
    for card_info in CARDS_UPDATE:
        name = card_info["name"]
        entry = {
            "name": name,
            "family": card_info["family"],
            "effect": card_info["effect"],
            "prereq": card_info["prereq"],
            "exclude": card_info["exclude"],
            "aliases": card_info["aliases"],
            "source": card_info["source"],
        }
        if card_info.get("unlock"):
            entry["unlock"] = card_info["unlock"]
        existing_map[name] = entry

    # Preserve deterministic sorting or insertion order
    final_cards = []
    seen = set()
    for c in data["cards"]:
        name = c["name"]
        if name in existing_map:
            final_cards.append(existing_map[name])
            seen.add(name)
    for card_info in CARDS_UPDATE:
        name = card_info["name"]
        if name not in seen:
            final_cards.append(existing_map[name])
            seen.add(name)

    data["cards"] = final_cards
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Updated {path}: total cards = {len(final_cards)}")
    return final_cards


def update_archive_unlocks():
    path = CONFIG_DIR / "skill_archive_unlocks.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for sk in data.get("skills", []):
        sid = sk.get("skill_id")
        if sid in ARCHIVE_UNLOCK_ITEMS:
            new_items = ARCHIVE_UNLOCK_ITEMS[sid]
            existing_unlocks = sk.get("unlocks", [])
            for item in new_items:
                replaced = False
                for i, ex in enumerate(existing_unlocks):
                    if ex.get("level") == item["level"] and ex.get("kind") == item["kind"]:
                        existing_unlocks[i] = item
                        replaced = True
                        break
                if not replaced:
                    existing_unlocks.append(item)
            existing_unlocks.sort(key=lambda u: (u.get("level") is None, u.get("level") or 999))
            sk["unlocks"] = existing_unlocks

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Updated {path}")
    return data


def update_rarity():
    path = CONFIG_DIR / "skill_card_rarity.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    existing_map = {c["name"]: c for c in data["cards"]}
    for card_info in CARDS_UPDATE:
        name = card_info["name"]
        entry = {
            "name": name,
            "rarity": card_info["rarity"],
            "family": card_info["family"].replace("奥数", "奥术"),
            "face": "card_grid",
            "rarity_status": "real_machine_screenshot",
            "source": "user_screenshot_20260902",
        }
        existing_map[name] = entry

    final_cards = []
    seen = set()
    for c in data["cards"]:
        name = c["name"]
        if name in existing_map:
            final_cards.append(existing_map[name])
            seen.add(name)
    for card_info in CARDS_UPDATE:
        name = card_info["name"]
        if name not in seen:
            final_cards.append(existing_map[name])
            seen.add(name)

    data["cards"] = final_cards
    data["total_cards"] = len(final_cards)
    data["version"] = "2026-09-02"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Updated {path}: total cards = {len(final_cards)}")
    return final_cards


def update_knowledge(catalog_cards, archive_data, rarity_cards):
    path = CONFIG_DIR / "skill_card_knowledge.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rarity_map = {c["name"]: c for c in rarity_cards}

    knowledge_cards = []
    for c in catalog_cards:
        name = c["name"]
        k_card = dict(c)
        r_entry = rarity_map.get(name)
        if r_entry:
            k_card["rarity"] = {
                "value": r_entry.get("rarity", ""),
                "confirmed": True,
                "source": r_entry.get("source", "user_screenshot_20260902"),
            }
        else:
            k_card["rarity"] = {"value": "", "confirmed": False, "source": ""}
        knowledge_cards.append(k_card)

    data["cards"] = knowledge_cards
    data["card_count"] = len(knowledge_cards)
    data["archive_unlocks"] = archive_data
    data["rarity"] = {
        "version": "2026-09-02",
        "total_cards": len(rarity_cards),
        "cards": rarity_cards,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Updated {path}: card_count = {len(knowledge_cards)}")


def update_choice_lexicon():
    path = CONFIG_DIR / "choice_lexicon.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data.get("entries", {})
    for card_info in CARDS_UPDATE:
        name = card_info["name"]
        if name not in entries:
            entries[name] = {
                "aliases": card_info["aliases"],
                "kind": "skill",
                "version_seen": "1.3.x",
                "confusions": [],
                "set_membership": card_info["set_membership"],
            }
        else:
            entries[name]["set_membership"] = card_info["set_membership"]

    data["entries"] = entries
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Updated {path}: total entries = {len(entries)}")


def sync_dist():
    if DIST_CONFIG_DIR.exists():
        for filename in [
            "skill_card_catalog.json",
            "skill_archive_unlocks.json",
            "skill_card_rarity.json",
            "skill_card_knowledge.json",
            "choice_lexicon.json",
        ]:
            src = CONFIG_DIR / filename
            dst = DIST_CONFIG_DIR / filename
            if src.exists():
                shutil.copy2(src, dst)
                print(f"Synced {src.name} to dist.")


def export_desktop_summary():
    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DESKTOP_DIR / "skill_updates_60lv.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(CARDS_UPDATE, f, ensure_ascii=False, indent=2)

    md_content = """# 刷刷宝技能库 60级版本扩展汇总（2026-09-02）

## 一、本次更新概览

游戏版本更新后，技能满级由原先的 46~50 级拓展至 **60 级**。
本次从实机截图素材中核验并入库了 **10 个全新高阶技能**（含 56 级、60 级质变核心卡），并对 10 个已有技能的描述、前置条件与解锁等级进行了全量实机校正。

---

## 二、新增与校正技能详细清单

| 技能名称 | 技能族系 | 解锁等级 | 前置条件 | 排斥卡牌 | 品质 | 技能效果描述 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **箭神** | 普攻 | 56级 | `[强化箭矢x2]` | 无 | 橙 | 基础普攻伤害+100%，普攻额外附加300%攻击的自适应伤害 |
| **紫极天雷** | 天雷 | 60级 | `[审判之雷]` | 无 | 橙 | 天雷命中目标后，对目标周围600范围内的随机敌人施放2次造成100%天雷伤害的紫极天雷 |
| **无限电流** | 闪电链 | 60级 | `[永动电流]` | 无 | 橙 | 闪电链弹射时不再忽视已命中单位(可以在两个怪之间来回弹射) |
| **地爆天星** | 陨石 | 56级 | `[陨石碎片]、[星落]、[毁灭陨石]` | 无 | 橙 | 每释放3次陨石，释放1次地爆天星，地爆天星会缓慢落下，下降过程中造成3次500%陨石的伤害，落地后发生爆炸，造成2000%陨石的伤害 |
| **高频脉冲** | 奥术激光 | 56级 | `[激光闪射]` | 无 | 橙 | 激光闪射伤害频率翻倍，伤害翻倍，范围翻倍 |
| **风暴狂潮** | 飓风 | 60级 | `[贯通之风]、[强袭飓风]、[多重风暴]` | 无 | 橙 | 飓风齐射+2 |
| **余震** | 地震 | 56级 | `[强震]、[地震速击]、[地震增幅]` | 无 | 橙 | 地震结束后会在周围触发2次小范围造成50%地震伤害的余震 |
| **散射箭矢** | 奥术箭 | 56级 | `[次级扩散]` | 无 | 橙 | 次级箭会对原本的主目标造成1次伤害再释放，次级箭数量+1 |
| **奥术狂潮** | 奥术箭 | 60级 | `[箭矢齐射]、[箭矢连发]、[强力箭矢]` | 无 | 橙 | 奥术箭额外释放1次，数量+2，穿透+3 |
| **究极冰箭** | 寒冰箭 | 60级 | `[三棱冰箭]` | 无 | 橙 | 三棱冰箭造成的伤害提高50% |
| **永冻天球** | 寒冰箭 | 50级 | 无 | 无 | 橙 | 每释放5次寒冰箭，生成一个持续3秒的永冻天球，每0.5秒造成100%寒冰箭的范围伤害，并附加1层冻伤。如果目标已有5层冻伤，则清空目标冻伤层数，造成500%寒冰箭的伤害并附加0.3秒的深度冻结 |
| **集束箭矢** | 奥术箭 | 50级 | `[箭矢齐射x2]` | 无 | 橙 | 奥术箭发射的箭矢更加集中，奥术箭数量+1 |
| **强化飓风** | 飓风 | 43级 | `[飓风增幅x3]` | 无 | 绿 | 飓风伤害+20% |
| **强化冰箭** | 寒冰箭 | 43级 | `[冰箭增幅x3]` | 无 | 蓝 | 寒冰箭伤害+20% |
| **风力回旋** | 飓风 | 40级 | `[多重风暴]` | 无 | 绿 | 飓风消失时往回再次释放1个保留所有强化的飓风 |
| **冰晶爆裂** | 寒冰箭 | 36级 | `[蚀骨冰棱]` | 无 | 蓝 | 小冰箭会对原本的主目标造成1次伤害再释放，小冰箭数量+1 |
| **次级箭** | 奥术箭 | 基础 | `[箭矢增幅]` | 无 | 蓝 | 奥术箭首次命中后，分裂出1个可以造成150%攻击[能量]魔法伤害的次级箭 |
| **强力箭矢** | 奥术箭 | 基础 | `[箭矢增幅x2]` | 无 | 蓝 | 奥术箭伤害+80% |
| **急速抽箭** | 奥术箭 | 基础 | `[箭矢增幅]、[强化箭矢]` | `[爆炸箭矢]` | 紫 | 奥术箭冷却缩减+30% |
| **强化飞箭** | 奥术箭 | 基础 | `[箭矢增幅x3]` | 无 | 白 | 奥术箭伤害+20% |

---

## 三、知识库与引擎同步状态

本次更新已同步至 G 盘刷刷宝主仓库与运行时环境：
1. `config/skill_card_catalog.json`：全量卡牌目录扩充并完成字段校正。
2. `config/skill_archive_unlocks.json`：补充 50/56/60 级实机解锁里程碑。
3. `config/skill_card_rarity.json`：更新卡牌品质与全量计数。
4. `config/skill_card_knowledge.json`：重新聚合卡牌-前置-品质-解锁全量知识图谱。
5. `config/choice_lexicon.json`：添加 OCR 识别词条及所属流派映射。
"""
    md_path = DESKTOP_DIR / "技能更新_60级全量解析.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"Exported markdown to {md_path}")
    print(f"Exported json to {json_path}")


def main():
    catalog_cards = update_catalog()
    archive_data = update_archive_unlocks()
    rarity_cards = update_rarity()
    update_knowledge(catalog_cards, archive_data, rarity_cards)
    update_choice_lexicon()
    sync_dist()
    export_desktop_summary()
    print("All skill updates completed successfully!")


if __name__ == "__main__":
    main()
