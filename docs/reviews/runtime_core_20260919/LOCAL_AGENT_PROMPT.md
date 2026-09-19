# 本地主集成 Agent 接收提示词

接手 ShuaBao Runtime Core 整合。用户已授权接收云端核心代码并推进本地整合；禁止直接发布生产。

我同时给你 `ShuaBao_RuntimeCore_20260919.zip`。注意：云端 GitHub 文件写入被工具安全检查阻断，远端预留分支 `arch/runtime-core-handoff-20260919` 仍停在旧基线，不包含新源码。不得只 fetch 该分支就说接收完成。

审查基线：6d55cecb50ab38675db420ccc950fd30c232ef08
生产锚点：b52c69e2aa1f74b59506439cceba06535bc6234c
现有工作树：G:\刷刷宝\Worktrees\pirate-necromancy-gt-20260917
建议新工作树：G:\刷刷宝\Worktrees\runtime-core-integration-20260919
新分支：integration/runtime-core-20260919

任务顺序：
1. 先读现有仓库 AGENTS.md。核验现有工作树 root、HEAD、status、remote refs。保留所有 captures、截图、scratch 和未提交内容；禁止 stash、reset --hard、git clean。不要切走其他 Agent 正在用的工作树。
2. 创建全新的 integration worktree，起点必须核验为上述基线；发现分支／目录已存在或远端漂移时停止自动覆盖并报告。
3. 解压交付包到仓库外，读取 DELIVERY_MANIFEST.json 并校验每个文件 hash。先读 repo/docs/reviews/runtime_core_20260919/ARCHITECTURE_AND_LOCAL_HANDOFF.md。
4. 在新 worktree 执行 `git apply --check <包路径>\core_foundation.patch`，检查通过后应用；补丁只新增内核、测试、工具和交接文档，不应覆盖旧源码。
5. 用 G:\刷刷宝\GameScript-Local\.venv\Scripts\python.exe 执行 tools/run_runtime_core_checks.py。期望78项通过；这是 OFFLINE_UNIT，不是实机。
6. 执行 tools/prepare_runtime_core_integration.py 的只读检查。它核验四个旧文件 blob；发生 SOURCE_DRIFT 禁止改 hash 绕过，回传差异。
7. 生成并审查 legacy-seams.patch，再 git apply --check / git apply。这批仅修 Runtime/Core/Harness 方法一致性、黑商关键字参数、测试高级组旁路，并暂时关闭缺少目标证据的破坏性消费与无效帧成功判定。
8. 你唯一负责旧主循环薄适配器：将现有感知转成 Demand/Proof，复用现有 act_* 和 postcondition，所有任务共用 Coordinator。先shadow再受控接管；不能让旧循环和新仲裁器同时拥有输入权。新增局内字段同步 C2 INGAME_POLLUTION。
9. 云端交付的 src/shuabao/runtime_core/ 与 tests/runtime_core/ 是核心协议，不要另建 scheduler 或无界 watchdog。发现问题先给最小失败测试与单独补丁，不混入机制参数调整。
10. 本轮先完成接收、P0接线、真实Core/Runtime/factory集成测试；然后推进适配器。未完成普通丹/悬赏令/神赐丹目标身份与后置证据前不得重新开放。不要顺手开放通用技能、0.90首帧直击或改3000/1000阈值。
11. 重跑原有目标回归、C2和完整release_gate；旧失败单列归因，不修改snapshot制造绿色。固定新的candidate SHA后再做受控LIVE；旧日志不能验收新候选。
12. 按层分提交并push独立integration分支、创建Draft PR。禁止合并main或生产、禁止force push和自动merge；合并待独立验收，且只允许merge commit。满足仓库提交门禁或获得明确例外前，不绕过hooks。

最终回传：
branch、起点/终点完整SHA、PR/base、修改文件、测试命令/退出码、78项结果、旧/新增失败、frozen/LIVE分别状态、manifest与配置/规则/资产/实际绑定hash、captures保留情况、是否改snapshot、merge=NOT_DONE。

不要再只输出架构建议；从核验与新worktree接收开始执行。未验证的机制可以保持BLOCKED，但要交付可复现失败、最小补丁与下一步证据需求。
