# 改动纪律与发版门禁

> 立此规矩的代价已经付过了：commit `e997b39`（局内三录屏修复）在同一提交里顺手改了大厅侧
> `room_start.fallback`、建房弹窗断言与 `_adapt_scales` 排序，8-12 上午被迫连发
> r10（`de77a19`）、r11（`42f3e95`）两次紧急修复。同期 `fixtures/baselines/replay_frozen`
> 已红 3 个场景却无人发现——资产齐全，但没有闸门。

## 一、改动纪律（三条硬规矩）

### 1. 一个 commit 只动一层

| 层 | 范围 |
|----|------|
| **L0 大厅** | 平台地图 / 建房弹窗 / 房间等待 / 房间开始 / 选关 / 英雄模式弹窗 |
| **L1 局内** | 主线循环（技能/羁绊/宝物/进化/装备/拾取/黑商/神器）、面板 FSM、挑战开关 |
| **恢复与战后** | 失败/断线恢复、胜利/存档/秘境、退出回房 |
| **感知** | `vision/`（matcher / capture / OCR）、模板资产、`scenes.json` |
| **外壳** | `desktop_app.py` / `api_server.py` / `main.py` / 打包 |

跨层改动请拆成多个 commit。**理由**：`mediator.py` 目前约 5900 行、159 个方法、约 161 个共享
可变状态，跨层混提交会让二分定位失效——上次就是因此只能整包回滚再打补丁。

### 2. 发版前必须 gate 通过

```powershell
python tools/release_gate.py
```

退出码 0 才允许打包。**不要**用 `--skip` 蒙混过关（被跳过的阶段会标记 SKIPPED 并直接判 FAIL）。

### 3. 版本用 git tag，不用目录名

根目录下 20 多个 `build_*/dist_*` 目录不是版本管理，是回归温床。发版流程：

```powershell
python tools/release_gate.py          # 必须 PASS
git tag -a v2026.08.12-r12 -m "..."   # 版本以 tag 为准
# 然后打包，产物目录随时可删
```

---

## 二、门禁四阶段

`tools/release_gate.py` 串联仓库既有离线资产，全部零输入、不需要游戏在运行：

| 阶段 | 内容 | 判定 |
|------|------|------|
| `pytest` | `tests/` 全量 | 不得有 failed/error；通过数不得低于快照 |
| `frozen_replay` | `tools/run_frozen_replay.py` 冻结端到端回放 | 每个场景状态必须与快照一致 |
| `scene_templates` | `tools/validate_scenes.py` | `missing=0` |
| `contract` | `tests/contract/` 层间契约 | 全绿 |

### 为什么是"快照比对"而不是"要求全绿"

冻结回放当前有 3 个场景 FAIL、1 个 BLOCKED（详见 `docs/baselines/GATE_BASELINE.json`
的 `known_failures`，每项都写明了根因）。若门禁要求全绿，它会永久红、然后被所有人忽略——
这正是它此前失效的方式。

改为快照比对后：

- **新破坏** → 某个 PASS 场景变 FAIL → 门禁立刻红。
- **已修好** → 某个 FAIL 场景变 PASS → 门禁也红，提示更新快照（避免悄悄回退）。
- **已知过期** → 与快照一致 → 放行，但原因写在案上，不会被遗忘。

### 更新快照的唯一正当方式

```powershell
python tools/release_gate.py --update-baseline --reason "说明为什么快照变了"
```

`--reason` 是必填的。**禁止**为了让门禁变绿而更新快照——那就是项目自己
（`docs/AGENT_CORRECTION_GATES_20260811.md`）明令禁止的 `FAIL + waiver = PASS`。
正当顺序永远是：**先修夹具期望或代码，再更新快照**。

---

## 三、契约测试（`tests/contract/`）

与 `tests/test_*`（事后回归，记录"某次真机为什么坏了"）不同，契约测试描述
**必须永远成立的层间约束**。当前四条：

| 契约 | 内容 | 拦什么 |
|------|------|--------|
| **C1** 相位链锚点门控 | 每个 L0 相位跃迁必须由自己的锚点触发；`UNKNOWN` 屏态零输入 | 盲点、猜着往前跳、无锚点乱按 |
| **C2** 局内状态隔离 | 污染全部 L1 状态后，L0 决策序列必须逐步一致 | **改局内弄坏大厅**（本仓库最易踩） |
| **C3** 大厅锚点资产 | 大厅锚点引用的模板必须在 `assets/Images` 下真实存在 | 改配置忘了放图 |
| **C4** 入口禁止颜色兜底 | `room_start` / `map_create_room` 及其别名 `fallback` 必须为 `null`；大窗不得走蓝色兜底 | 复活"快速加入"/蓝按钮红线 |

契约测试已做突变验证（人为注入耦合与红线破坏，确认会红）——**能通过一切的测试等于没有测试**。
新增契约时请同样验证它会咬人。

### 改了局内状态字段名怎么办

C2 用显式字段清单做污染（`C2InGameStateIsolation.INGAME_POLLUTION`）。若重命名或新增
局内状态字段，请同步该清单；字段不存在时契约会直接报错提示，不会静默失效。

---

## 四、实机检查（不在离线门禁内）

门禁只保证"离线行为没退化"，不能替代真机验证。真机链路检查：

```powershell
python tools/diagnose_lobby.py          # 只读快照：窗口候选 / context / 各锚点命中
python tools/diagnose_lobby.py --save-dir agent_out/lobby_probe   # 需要留证时
```

真机跑完后，若出现 TIMEOUT / CANCELLED / 循环点击，请把对应帧固化成夹具
（`tools/video_breakdown.py` 抽帧），让这次事故变成永久回归资产——
而不是下次再从录屏重新考古。
