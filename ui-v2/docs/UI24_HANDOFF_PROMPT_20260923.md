# UI-24 看板升级 · 交接提示词（2026-09-23）

> 用法：把下面「给下一位 agent 的提示词」整段复制给接手的 agent。其余章节是它需要的事实与验收口径。
> 本文件位于 UI 分支 `G:\刷刷宝\Worktrees\ui-run-summary-20260923\ui-v2\docs\`，与改动放在同一分支里。

---

## 给下一位 agent 的提示词

```text
你接手「刷刷宝」看板 UI-24 升级。先读仓库根 AGENTS.md、docs/agent_shared_logs/RELEASE_HARNESS_LESSONS.md，
再读 ui-v2/docs/UI24_HANDOFF_PROMPT_20260923.md（本文件）全文。

工作目录：G:\刷刷宝\Worktrees\ui-run-summary-20260923（分支 feat/ui-run-summary-20260923，基于 7070c097）。
不要在主目录 G:\刷刷宝\GameScript-Local 直接改 ui-v2；那里有别人的未提交改动。

目标（按顺序）：
1. 在本机复现预览沙盒效果：
   a) 双击桌面「刷刷宝 UI预览（不连接游戏）」：应出现 960×820 的看板窗口，右侧贴一个「场景」面板；
      点「蹭车 · 小窗」窗口缩成 360 宽、高度按内容；点「单刷」恢复 960×820。
   b) 或在 ui-v2 下 npm run dev 后浏览器打开 http://127.0.0.1:5187/_verify/preview_sandbox.html
      （外框 + 底部场景条 + 960/1080 宽度对比 + 深浅主题）。
   两者的场景动作都来自 ui-v2/src/dev/previewScenes.ts（window.__sbPreview），不要各写一套。
2. 按「验收清单」逐项在 960×820 下看一遍，深色、浅色都要看。发现问题先截图再修，修完重跑对应场景。
3. 跑测试：ui-v2 下 npm run check、npm test；仓库根 python -m pytest tests/test_web_config_shell.py -q；
   再跑 python tools/release_gate.py（四阶段，退出码必须为 0，门禁红了不许改快照变绿）。
4. 通过后提交（外壳层一个 commit 即可：ui-v2 + web_config_shell.py + 对应测试），走 PR merge commit。
5. 按 AGENTS.md §6 在主目录构建正式包：powershell -ExecutionPolicy Bypass -File .\build_release.ps1，
   核对 build_identity.json 的 source_sha 与 HEAD 一致、桌面快捷方式指向新目录，再跑 release_harness。
6. 实机验收只认正式 EXE：重点确认标题栏按钮可点（见「已知风险 1」）、960 窗口、蹭车小窗、过场是否还卡。
7. 回写 docs/CURRENT_STATUS_AND_HANDOFF_*.md：commit、产物 hash、正式入口、仍需真机验证的项。

禁止：用 Qt mock 预览或浏览器截图冒充正式包验收；把 mock 数据写进正式构建；绕过 release_gate。
```

---

## 现状（2026-09-23 交接时）

- 分支 `feat/ui-run-summary-20260923` HEAD `7070c097`，以下改动**均未提交、未构建、未发布**。
- 主目录 `GameScript-Local` 的 `ui-v2` 仍是 `7070c097` + 旧布局修复，**没有同步本轮改动**；发布前以 UI 分支为准合并。
- 在线预览沙盒（claude.ai，私有）：https://claude.ai/artifact/6sz4fkc3s6SJkmrwe4MSxP ——与上面 1b 同一套页面，只是用 bun 打包后托管。

## 改动文件

| 文件 | 改了什么 |
|---|---|
| `ui-v2/index.html` | 新增「补丁 UI-24」CSS/JS 块（在最后一个 `</style>` 前、`sb-ux-layer` 脚本末尾），以及少量源码改动：宝物手风琴、篇章名/阶段分列、高级卡组空态与拖动排序、订阅胶囊文案与配色、带车房间两行、流光性能、策略列表对齐、≤1000px 适配、宝物效果浮层、激活动画 `reduce()` 作用域修复、布局脚本测量时恢复自然高度（`sb-measuring`）、仅 http 页暴露 `window.__sbPreviewState` |
| `ui-v2/src/main.ts` | 非 production 分支动态导入 `./dev/previewScenes` 并安装（正式构建不打包） |
| `ui-v2/src/dev/previewScenes.ts` | **新增**：场景动作表 `window.__sbPreview = { scenes, run(id) }`；把 `sb:window-layout` 转成控制台行 `[sb-preview-layout] {...}` |
| `ui-v2/src/bridge/mockBridge.ts` | mock 的 `set_window_layout` 广播 `sb:window-layout` 事件（仅 mock） |
| `ui-v2/_verify/preview_window.py` | **新增**：桌面预览窗口唯一实现（960×820、按事件切小窗、右侧场景面板、`--snapshot`/`--scene`） |
| `ui-v2/_verify/preview_sandbox.html` | **新增**：浏览器预览外框（场景条、宽度对比、主题），dev server 下打开 |
| `ui-v2/tests/ui23_regression.spec.ts` | 宝物分组摘要断言改为新行为（不再写「默认不拿」，同时只展开一组） |
| `src/shuabao/shell/web_config_shell.py` | `_DASHBOARD_SIZE = (960, 820)`；看板标题栏拖动区改为左侧 360px |
| `tests/test_web_config_shell.py` | 尺寸断言 1080→960，拖动区 850/690→360 |
| `G:\刷刷宝\Preview\固定窗口预览.py`（仓外） | 改成薄入口：转调 `ui-v2/_verify/preview_window.py`，启动失败弹窗说明原因 |

## 各项设计决定（验收时对照）

1. **看板 960×820**：技能卡按面板宽度排布（策略下拉 124px，不压 ▲▼）；高级卡组在窄宽度隐藏拖柄；羁绊两列 `1.05fr / 1fr`。
2. **同层面板底对齐**：上排技能/宝物等高；下排羁绊铺到底与左栏底边齐平；单刷时左栏开关组贴底，带车时最后一块「带车房间」铺到底。
3. **宝物设置**：标题后小字「默认不拿 · 勾选放行」；分组行只在有勾选时显示「已选 N」；**同一时间只展开一组**；选项两列；效果说明悬停/聚焦时以浮层显示在宝物面板左侧（`.sb-tip`，挂在 `#scene-app` 下，不会被裁切）。
4. **龙珠图标**：`dragonIconSvg()` 改为线性圆珠 + 四角星，跟随文字色。
5. **篇章**：`renderDD` 支持 `htmlOf`，篇章显示「名称 + 右侧阶段小标签」。
6. **羁绊**：无高级卡组时显示三个虚线槽位 + 「选择高级卡组」（直接进入编辑）；有高级卡组时为紧凑行，拖动或 ▲▼ 排序，超过 3 个按列分两栏；去掉了每行的「选槽位」下拉（`assignAdvSlot` 与 `data-adv-pick` 点击处理保留未删）。
7. **订阅胶囊**：有效态只写「卡密有效 · MM-DD 到期」，LIVE 状态放 title；配色改为中性胶囊 + 绿色状态点（原浅绿在浅色主题对比度 1.9:1）。未激活/异常仍为警示色。
8. **过场卡顿**：主因是彩色边框流光（两张 1600² 锥形渐变 + 全窗 inset 阴影，出现时现场栅格化约 500 万像素）。改为 400² 渐变放大 3.3 倍旋转、内晕改线性渐变、流光层启动时预插入；同时关闭 `#scene-app` 内 30 余处无视觉作用的 `backdrop-filter`。Chromium 追踪下完成过场栅格耗时约减半；**Windows QtWebEngine 实际手感需实机确认**。
9. **激活成功动画**：「补丁 F–I」里 `reduce()` 未定义导致激活后报错不播放，已在该作用域补定义。
10. **带车左栏**：房间名称/密码并排（标签改占位文字，读屏仍可读），「每局新建」开关放标题行，说明进 title；解决原来左栏被挤出窗口约 180px。
11. **声望任务列表**加宽到 216px，长任务不再单独折出「-25%」。

## 验收清单（960×820，深色 + 浅色）

用场景面板/场景条逐个点：单刷、蹭车·小窗（360 宽）、带车、跟车·小窗、启动过场、预检中、预检失败、运行中、完成·蹭车统计、完成·单刷、中断、订阅激活、激活成功（应播放动画且无控制台报错）、声望挑战、传家宝、Boss、高级设置、运行日志、编辑羁绊、高级卡组 0/2/5 个。
每个场景确认：无重叠、无被裁切、无异常换行；三栏标题同一水平线；同层面板底边对齐；宝物悬停说明完整显示。

## 已知风险 / 仍需实机确认

1. **标题栏拖动区可能吞点击（旧包也可能受影响）**：Qt 外壳在网页标题栏上盖了一个透明拖动层。旧规则是看板宽 − 230（1080 时 850px），而网页标题栏右侧控件从约 x=371（960 宽、订阅已激活）开始，旧值会盖住订阅胶囊、方案下拉、保存方案等按钮。本轮改为只盖左侧 360px。请在正式 EXE 上逐个点击标题栏按钮确认。
2. 本轮前端测试是在云端用 bun 代跑的：61 个里 60 过，1 个失败是 bun 的 `vi` 缺 `advanceTimersByTimeAsync`（与改动无关），**必须在本机 `npm test` 复核**。`tsc --noEmit` 通过。Python 测试未跑。
3. 预览窗口 `preview_window.py` 在云端只做过语法检查（云端装不了 PySide6），首次在本机打开时请确认场景面板与小窗缩放正常。
4. 版本标识仍为 `UI-23`（测试里有断言）；是否升到 UI-24 由 Owner 决定。
