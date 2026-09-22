# Boss unconfirmed 修复集成记录

## 身份

- 执行 agent 行为提交：e35ffc36271b00b74f6f3328bc9d80e265a00a68。
- 注释/文档补充：dc0ceb243201a7c821d7c5aae555d12c8f4c252e。
- 主目录合并提交：5b23f9c710b609cb072cf7b62b2eb65ed7660be2（双父 merge commit）。
- identity 提交/当前测试源码：afc3443f2a7862c2fb2e2f68692f203fa7a25d02。
- candidate_sha：5b23f9c710b609cb072cf7b62b2eb65ed7660be2。
- 主目录：G:\刷刷宝\GameScript-Local；分支 fix/hitch-goal-archaeology-20260920。

## 已验收

两条生产路径的双帧无卡分支均为 done=True / result_confirmed=False / confirm_unconfirmed=True / clicked_at=None；不新增识别器或 FSM，保留有界等待与禁止空滚。

dc0ceb2 末尾报告的替换失败没有留下那两条旧验收条件：最终 diff 已更正。主架构合并时另补正文档遗留的“低成功率1/10”“输入成功即可否定游戏未受理”，并将10局改称10个战后事件段。这些为文档改动，不改业务代码。

合并后的 mediator.py 及两份回归测试与 dc0ceb2 相同。源快速测试、UI 与本次合并前一致。两个未跟踪脚本仍留在外部 Boss worktree，不纳入主目录。

identity 实测 ready_for_gt=true、production_code_diff=CLEAN、runtime_source_verified=true；这不是全量门禁或真机成功证明。

## 全量门禁

状态：**PASS**（2026-09-22 19:20，exit 0，耗时 19m14s）。首次运行（18:37）因会话中断未产出日志，作废；本次为独占重跑。

- pytest 2490 passed / 2 xfailed / 2 skipped，无 deviation
- frozen_replay PASS（disconnect_modal_missing=BLOCKED，属既有缺素材项，不计失败）
- scene_templates PASS（148 ok / 0 missing，asset 401/401）
- contract PASS（58 passed）
- 日志：G:\刷刷宝\Artifacts\internal-pilot\gate-afc3443-20260922-rerun.stdout.log

实机测试台 lnk 已更新 ProductionSourceSha 9ed8b52 → afc3443 并读回一致（管理员标志保留）；旧 lnk 备份到 G:\刷刷宝\Archive\Shortcuts\刷刷宝 实机测试台.9ed8b52.20260922.lnk。

主目录独占运行现有 tools/release_gate.py --json；解释器 .venv\Scripts\python.exe；进程内 OCR_PYTHON 指向主目录 .venv-ocr\Scripts\python.exe，OCR_MODEL_DIR 指向主目录 models\ocr。未修改用户级环境变量。

- G:\刷刷宝\Artifacts\internal-pilot\gate-afc3443-20260922.stdout.log
- G:\刷刷宝\Artifacts\internal-pilot\gate-afc3443-20260922.stderr.log

## 发布边界

当前9ed8b529签名候选包不包含本次修正。现有包保留，禁止用源码文件热补签名包。
正式 current.json、刷刷宝.lnk、Grok 登记不在本次变更范围。实机输入未授权，不启动游戏。
实机测试台 SHA 待门禁通过后更新并读回；快速测试入口沿用主目录，不改授权行为。

Boss 游戏受理/成功、tick4081、game_count映射和六次兜底解锁状态仍 UNKNOWN；不阻止本次“不虚报受理”离线验收，但不得描述为 Boss 真机成功。
