# Boss 挑战更新（战后层）— 2026-09-22

## 结论一句话

**点击输入成功，但双帧未再识别到 Boss 卡（f0310 上未见掉落弹窗或「击杀BOSS」）**；原逻辑 1 秒盲等后清标记继续「重新定位卡位」，在无卡区域滚动，最终误判 anomaly 跳过。双帧无卡只支持停止重复定位，**不证明挑战受理/成功**。

---

## 1. 根因还原（实机 GT）

### 1.1 现场

| 项 | 值 |
|---|---|
| Bundle | `C:\tmp\shuabao-captures\hitch_lobby_chain_20260922_002105_993691` |
| 时间 | tick 320–351（00:34:35–00:36:11） |
| 设置 | cjb_boss=17年兽、sgzx_boss=18瑟莱德丝公主 |
| 生产源 | `production_source_sha=ca84a28eef93bdd26335591fcccaacee822b11ed` |

### 1.2 动作序列（trace.jsonl + manifest.events）

| tick | event | 动作 | 帧 | 含义 |
|---|---|---|---|---|
| 320–327 | e0186–e0193 | ArchiveChallenge ×8 | f0287–f0302 | 先点一轮存档挑战（正常） |
| 328 | e0194 | BossConfigured-scroll −5 | f0303→f0304 | 时光之穴列表滚动定位 |
| 329–330 | e0195–e0196 | BossConfigured-scroll-up +5 ×2 | f0305–f0308 | 回滚校准 |
| **331** | **e0197** | **click:18瑟莱德丝公主 @ [1313,389] ok=true** | **f0309→f0310** | **点击生效** |
| 332–335 | e0198–e0201 | BossConfigured-scroll −5 ×4 | f0311–f0318 | **故障：列表已关仍空滚 4 次** |
| 338/340/342 | — | BossAnomalyParkPointer ×3 | — | 一张卡都认不出 |
| **343** | — | **boss_challenge_skipped reason=anomaly page=ARCHIVE_PANEL** | — | **误判跳过** |
| 344 | e0203 | CloseArchivePanel | f0320→f0321 | 关面板 |
| 345 | e0204 | OpenHeirloomChallenges | f0322→f0323 | 转传家宝 |
| 346–347 | e0205–e0206 | scroll → click:17年兽 ok=true | f0324–f0327 | **传家宝正常** |

### 1.3 帧证据（决定性）

| 帧文件 | 观察 |
|---|---|
| `frames/f0309_action_before.png` | 右侧「时光之穴」Boss 列表打开，可见 阿扎达斯 / **瑟莱德丝公主** / 加兹瑞拉 …（点击前） |
| `frames/f0310_action_after.png` | 右侧 Boss 卡片不再命中；左侧存档挑战八卡仍在。**未见**掉落弹窗或「击杀BOSS」文本（旧描述已撤回，SHA256 `48edd941…0c2c7`） |
| `frames/f0311_action_before.png` | 右侧无 Boss 卡；代码开始 scroll @ [1360,480]（无卡区域） |
| `frames/f0318_action_after.png` | 4 次滚动后仍无时光之穴列表，画面右侧是地图/法术特效 |
| `frames/f0326_action_before.png` | 传家宝列表打开，可见「17年兽」 |
| `frames/f0327_action_after.png` | 17年兽 点击后正常进入挑战 |

**n=1 局（tick 320–351）**；帧文件名见上表，均在 bundle `frames/` 下。

### 1.4 三选一定性

| 假设 | 判定 | 依据 |
|---|---|---|
| 滚动定位失败 | **否** | f0309 列表打开且 18瑟莱德丝公主 可见，e0197 点击 ok=true |
| 点击没生效 | **否** | input_success=true（仅表示输入被接受，不等于业务受理） |
| **后置语义过强** | **是** | 双帧无卡只支持停止重复定位；旧逻辑却置 `result_confirmed=True` 并称「挑战受理」，随后仍滚动 4 次 + 3 次 ParkPointer + skip |

### 1.5 代码缺陷（仓库代码，worktree file:line）

| 位置 | 问题 |
|---|---|
| `src/shuabao/mediator.py:17268`（修前） | `now - clicked_at < 1.0` 盲等后清标记，**没有任何成功后置检查** |
| `src/shuabao/mediator.py:8276`（修前） | `can_scroll=not _post_game_boss_has_no_scrollbar(...)`：列表被替换后滑块消失，`has_no_scrollbar` 因 ROI 取不到内容返回 False，于是 `can_scroll=True`，在空列表上滚动 |
| `src/shuabao/mediator.py:8050` 附近 | 传家宝有 `_heirloom_boss_result_visible` / `_heirloom_boss_confirm_expired` one-shot；**时光之穴没有对称后置**（仅 `_time_cave_boss_clicked_at` 时间戳） |

对照：传家宝同一条链（tick 345–347）正常，因为 `HEIRLOOM_DIALOG` 有 one-shot 确认；时光之穴缺失。

---

## 2. 10 局 Boss 结果统计（实机 GT）

Bundle：`G:\刷刷宝\captures\hitch_lobby_chain_20260922_004851_422384`（trace.jsonl，n=10 局战后链）

设置同为 cjb_boss=17年兽、sgzx_boss=18瑟莱德丝公主。

| 局 | game_count | 时光之穴（18瑟莱德丝公主） | 传家宝（17年兽） | 备注 |
|---|---|---|---|---|
| 1 | 0 | 点击 ok → 异常跳过 | **异常兜底** BossNotUnlockedLast → 12战争之王 | 传家宝 17 未解锁 |
| 2 | 1 | 点击 ok → 异常跳过 | **成功** click 17年兽 | 唯一传家宝成功 |
| 3 | 3 | 点击 ok → 异常跳过 | **异常兜底** BossNotUnlockedLast → 13蛇王纳什 | game_count 0→1→3，缺 2 |
| 4 | 4 | 点击 ok → 异常跳过 | **异常兜底** BossNotUnlockedLast → 13蛇王纳什 | |
| 5 | 5 | 点击 ok → 异常跳过 | **异常兜底** BossNotUnlockedLast → 13蛇王纳什 | |
| 6 | 6 | 点击 ok → 异常跳过 | **异常兜底** BossNotUnlockedLast → 13蛇王纳什 | 局 TIMEOUT |
| 7 | 7 | 点击 ok → 空滚 13 次 → 兜底误点 52库林纳克斯 | **跳过**（scroll-bottom 后 Dismiss，未点 17） | 空滚变体 |
| 8 | 8 | 点击 ok → 异常跳过 | **异常兜底** BossNotUnlockedLast → 13蛇王纳什 | 局 TIMEOUT |
| 9 | 9 | 点击 ok → 空滚 13 次 → 兜底误点 52库林纳克斯 | **跳过**（scroll-bottom 后 Dismiss，未点 17） | 空滚变体 |
| 10 | 10 | 点击 ok → 空滚 13 次 → 兜底误点 52库林纳克斯 | **失败** click 17年兽 ok=false | 局 TIMEOUT |

### 汇总（每列 n=10）

| 页面 | 成功 | 跳过 | 异常 | 空滚/兜底误点 |
|---|---|---|---|---|
| 时光之穴 18瑟莱德丝公主 | 0 | 7（anomaly skip） | 0 | 3（13 次空滚 + 误点 52库林纳克斯） |
| 传家宝 17年兽 | 1 | 2 | 7（6 兜底非目标 + 1 点击失败） | 0 |

**证据类型**：以上全部为实机 GT（bundle trace + 动作 reason），n=10。  
**推断（标注）**：004851 各局「异常跳过 / 空滚」与本样本同属「点击后无卡 + 旧链继续滚动」；**不得**再外推为「成功被误判」或「掉落弹窗=受理」。业务受理/成功均为 UNKNOWN。

---

## 3. 竞品线索（仅线索，不抄默认值）

`docs/research/COMPETITOR_STATIC_OBSERVATIONS_1_6_2_20260922.md` 中 Boss 相关静态观察仅作行为线索（例如「挑战成功后列表关闭」的 UI 形态），**不引用其阈值/坐标/默认配置**。修复所用后置判据全部来自本仓库真机帧（f0310 列表关闭 + 卡片模板空）。

---

## 4. 修复（仅恢复与战后层）

改动文件：`src/shuabao/mediator.py`、`tests/contract/test_l0_lobby_chain_contract.py`、`tests/test_boss_challenge_20260922.py`。  
**未碰** L0 大厅 / L1 局内选卡 / `config/scenes.json` / 感知模板。

### 4.1 有界滚动 + 看不到锚点零输入

- 新增 `_post_game_boss_list_alive()`：**仅卡片命中**才算列表还活着（滚动条滑块在 f0318 上被法术特效污染，已去掉）。
- `decide_boss_order_action(..., can_scroll=can_scroll)`，其中  
  `can_scroll = list_alive and not _post_game_boss_has_no_scrollbar(...)`。  
  双帧无卡后两者皆无 → 零输入，绝不滚动。

### 4.2 点击后 one-shot 后置（对齐传家宝）

- 新增 `_time_cave_boss_result_visible()`：时光之穴双帧未识别到卡片 = 停止重复定位的收敛信号（**不**证明列表关闭，**不**证明挑战受理）。真机依据 f0310（未见掉落/击杀文本）。
- 新增 `_time_cave_boss_confirm_expired()` + `_TIME_CAVE_BOSS_CONFIRM_TIMEOUT_S = 6.0`（与传家宝同量级；原 1.0s 在 ~2.2s/tick 节拍下只够 0.5 tick）。
- `_maybe_challenge_configured_boss` 与 `_tick_impl` 的 ARCHIVE_PANEL 分支共用同一后置：  
  收敛 → `_time_cave_boss_done=True` / `_time_cave_boss_result_confirmed=False` / `_time_cave_boss_confirm_unconfirmed=True`；  
  超时 → 记 unconfirmed 事件并安全跳过。

### 4.3 找不到就安全跳过并留证据

- 后置超时：`_record_boss_challenge_skipped_incident(..., reason="post_click_unconfirmed")`（与 anomaly 区分）。
- 无锚点未点击：走既有未决收敛 → `boss_challenge_skipped` + incident 归档（f0311/f0318 可复现）。

### 4.4 新增状态（已同步 C2 INGAME_POLLUTION）

`_time_cave_boss_result_confirmed` / `_time_cave_boss_confirm_unconfirmed` / `_time_cave_boss_clear_frames` / `_time_cave_boss_clear_last_frame`（后两者已入 `INGAME_POLLUTION`）。

---

## 5. 回归测试（真实 bundle 帧）

夹具：`fixtures/boss_challenge_20260922/`（自 bundle `frames/` 复制，非合成）：

- `f0309_before_click_18.png` / `f0310_after_click_18.png` / `f0311_before_scroll1.png`
- `f0317_before_scroll4.png` / `f0318_after_scroll4.png` / `f0319_anomaly_state.png`
- `f0326_before_click_17.png` / `f0327_after_click_17.png` / `f0303_before_first_scroll.png`

测试文件：`tests/test_boss_challenge_20260922.py`

| 用例 | 断言 |
|---|---|
| `test_time_cave_list_alive_on_open_panel` | f0309 列表活着 |
| `test_time_cave_list_not_alive_after_click` | f0310/f0311/f0318 无锚点 |
| `test_time_cave_result_visible_after_click` | 双帧稳定后后置成立 |
| `test_time_cave_clear_frames_reset_when_cards_return` | **卡片重现必须重置双帧计数**（Review M1） |
| `test_no_scroll_after_click_on_replaced_list` | **点击后 0 scroll / 0 click / done + confirmed=False + unconfirmed=True** |
| `test_no_scroll_when_no_anchor_without_click` | 无锚点 0 scroll |
| `test_unconfirmed_timeout_skips_with_evidence` | 超时记 `post_click_unconfirmed`、不滚动 |
| `test_post_click_wait_is_zero_action` | 后置窗口内零动作 |
| `test_click_target_on_open_list_still_works` | f0309 仍点 18瑟莱德丝公主 |
| `test_heirloom_click_on_real_frame` | f0326 仍点 17年兽 |

### 测试结果

见本文档末尾「验证记录」。

---

## 6. 仍需实机验证 / 补采

1. **补采确认（高优）**：004851 bundle 中时光之穴 7 次 anomaly skip + 3 次空滚局，是否同样出现掉落弹窗（= 成功被误判）。需要逐局战后 tick 的 frames 或录屏。  
2. **修复后真机跑一次 hitch_lobby_chain**：确认 18瑟莱德丝公主 点击后不再出现 `BossConfigured-scroll` / `BossAnomalyParkPointer` / `boss_challenge_skipped`，且 `_time_cave_boss_result_confirmed=True`。  
3. **传家宝 17年兽 低成功率**（1/10）：6 次 `BossNotUnlockedLast` 兜底到 12/13、2 次未点、1 次 ok=false。属**账号解锁进度**还是**列表定位失败**需补采：战后传家宝列表整帧 + 账号已解锁 Boss 截图。  
4. **空滚变体（3/10）**：为何部分局列表关闭后走了 13 次 scroll + 误点 52库林纳克斯，而不是 anomaly skip。可能与 `has_no_scrollbar` ROI 被地图/特效污染有关；修复的 `list_alive` 门应消除该路径，需真机确认。  
5. **game_count 0→1→3**：缺一局战后链，需确认是否该局未进战后（如断线/强失败）。
6. **Review 补充**：非连续空帧误确认（已用单测钉住重置语义，仍需真机闪断样本）；主路径 `_tick_impl` 与 `_maybe_challenge_configured_boss` 双份后置逻辑是否同刻一致（M2，未抽公共 helper）；无锚点未点击是否留下 `boss_challenge_skipped` incident。

---

## 验证记录

- `tests/test_boss_challenge_20260922.py`：**10 passed**（2026-09-22，worktree，`GameScript-Local/.venv`）
- 防回归（同批）：`tests/test_boss_order_integration.py` + `tests/test_hitch_heirloom_scroll_20260914.py` + `tests/test_hitch_bag_panel_20260912.py` + `tests/test_hitch_l0_and_hud_fixes.py` + `tests/contract/test_l0_lobby_chain_contract.py`：**72 passed, 25 subtests passed**
- 未跑全量 `release_gate`（按任务纪律只跑针对性测试）。
- Review 跟进（M1/M3/m1）：`_time_cave_boss_result_visible` 在卡片重现时重置双帧计数；`_time_cave_boss_clear_last_frame` 入 `INGAME_POLLUTION`；`list_alive` 文档改为「仅卡片」。新增 `test_time_cave_clear_frames_reset_when_cards_return`。
- `list_alive` 最终判据：**仅卡片命中**。真机 f0318 上法术特效在滚动条 ROI 留亮斑，「滑块在=列表在」会把已关闭列表误判为可滚，故去掉滑块分支（见 `_post_game_boss_list_alive` docstring）。
