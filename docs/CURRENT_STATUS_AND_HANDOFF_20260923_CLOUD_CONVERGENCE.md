# 2026-09-23 云端三线整合：本地唯一施工入口

状态：**DRAFT / NOT_RELEASE_APPROVED**。适用范围为三份交付的整合执行；不覆盖未上传现场、Owner 新裁定或设备真实状态。

先读 `docs/reviews/CLOUD_CONVERGENCE_AUDIT_20260923.md`，其中已完成基线对齐、16 提交静态处置、机制纠偏、跨文件接口、W0–W5 分工。`docs/handoff_20260923/` 与新增 `docs/research/COMPETITOR_*` 为原始来源，**不能跳过纠偏报告直接按原施工提示执行**。

## 固定来源

- 架构：PR #33，`94f502335dd3575926fc78e853f992edbb401fab`，相对 `da566dd8d2320d55df0211a4b6f43d0e671789e5` 共 16 提交。
- 机制+竞品：PR #32，`14d5575fa7c2c9c1951c6c368bf175819ada68cb`，16 个 docs 文件；代码基线是旧 main `7ebf4b205a1fd3acd8d9d64fd84d184db6447ebc`。
- 整合分支：`integrate/cloud-convergence-20260923`，从 #33 起点建立。#33 相对上述 main 实际领先 125 提交，不能绕过既有候选历史直接合 main。

## 第一个动作：保护现场，不是在脏 root 上 pull

权威目录仍为 AGENTS 指定的 `G:\刷刷宝\GameScript-Local`。在原工作区记录 `git status --short`、`git diff --stat`、完整 tracked diff、untracked 清单、`git rev-parse HEAD`；保护未提交文件，清单/备份不要把授权数据、密钥、Token 放进 Git。

`config/choice_lexicon.json` 缺失属于本地现场。核对 HEAD blob 与实际备份 bytes，确认缺失是否为并行 agent 正在进行的重命名/生成流程；不得由同步脚本自动 `git restore` 覆盖。存在分歧时隔离为独立增量，不能把删除混入正式候选。

拉取后核验远端来源仍是以上 SHA。新建干净整合 worktree，避免触碰正在写入的 root。例如在确认目录/分支不存在后：

```powershell
git fetch origin
# 先保存上述现场记录，再创建独立审查/整合 worktree。
git worktree add -b integrate/local-convergence-20260923 G:/ShuaBao-Integration-20260923 origin/integrate/cloud-convergence-20260923
```

该 worktree 只用于隔离整合和验证，不自动替换正式桌面入口。若来源 ref 已前移，记录真实 SHA 并做增量对照；不得 force/reset 回本文件的旧值。完成现场收敛后，按权威 root 的正式候选流程接入已经审查的提交。

## 执行方向（已定，不再另起总重构）

1. W0 后冻结共同基线。主 agent 独占 runtime；资料 agent 仅 registry/证据；UI agent 限 main.ts/bridge/test。不得多人同写 mediator 或同一工作区。
2. W1 先验蹭车 end/solo/arch、离房后置确认、计数一次性、C2/C4、UNKNOWN。L0 与恢复/战后改动分提交，5-5 OFF 确认及失败终态归 L1。
3. W2 按审查报告 §5 收敛观察→计划→动作回执→业务确认，复用已存在的 solo_scheduler，不新增执行器。shadow 不主动 OCR、不改感知节流、不替执行器推进账本；不配对就 UNPAIRED。真实主线入口测试必须比较 shadow on/off 的输入、感知、状态迁移，而不只是 pytest 数量。
4. W3 复用现有夹具/测试建立来源与 Owner 状态表。保留当前 9 名/18 pattern 的已批准配置；不把 19+2、440、999、300s 单 ESC 或固定网格坐标直接施工。
5. W4 修复技能保存 key 先确认再去重，覆盖拒绝/失败/同值重试/快照 revision。`ui-v2/index.html`、签名订阅链另列，不混进此次修复。
6. W5 定向验证通过后，只跑一份受控的完整 gate，保留每阶段原始结果。失败先定位，不跳过/放宽/刷新 baseline。再做 Windows 与真实业务后置验证；源码、打包、桌面入口三个 verdict 分开。

Owner-held 项见审查报告 §6。可并行推进非争议的结构修复；不要代替 Owner 静默改变消费豁免、宝物默认选择、技能抢占阈值或新高级组阈值。

## 本轮工具变更的使用边界

`tools/summarize_solo_shadow.py` 的新输出仅比较已记录的计划家族。`report_schema=2`；按 source file + log schema + round_id 分组。旧 `recommend_vs_actual_*` 保留为兼容别名，真实含义为 `recommend_vs_plan_target_*`，**不是动作一致率**。当前 schema 没有足够动作回执，报告会明确 NOT_BEHAVIOR_PROOF / NOT_AVAILABLE。

损坏 JSON、非对象、重复 JSON key、未知 schema、非法 seq、同文件 seq 重置/重复、缺少明确输入等将返回错误，不再静默删坏行。请在一次记录关闭并完成 flush 后做正式汇总；对正在追加、尾行尚未完成的文件不要将失败当成可忽略。

定向测试：

```powershell
python -m pytest tests/test_solo_shadow_summary_integrity_20260923.py -q
```

云端仅在隔离目录运行标量工具测试与语法编译；完整 repo conftest、Qt、模板、replay、Windows 和真实输入均未在云端运行。详见 `docs/reviews/evidence_20260923/cloud_convergence/ISOLATED_VALIDATION.md`。

## Git 交付要求（必须执行）

- 本地每包明确 commit，完成定向验证后 push 自己的 topic branch，并创建/更新 Draft PR；一层一提交，可回滚。未提交现场不得顺手混入。
- 整合 PR 的 base 是 `review/current-architecture-20260923`，不是 main。后续本地 PR 优先以本整合分支为 base，保持堆叠依赖清楚。
- 禁止 force-push、squash merge、rebase merge、自动 merge。#32/#33 维持原状态；导入文档不代表其 PR 已 merge。
- 只有完整 gate 有可复核 verdict、Owner-held 处置明确、保护路径获准且 reviewer 同意后，才可按仓库规则使用 merge commit；不得由本任务自动发布/替换桌面。
- 每次回传必须包括：starting/final branch 与完整 SHA、parent/base、changed files、commit/push/PR/merge 状态、各测试命令/退出码/日志、未提交剩余、阻塞归属。实际包变化时另带 UI dist/EXE/manifest/shortcut/harness 身份与真机证据。

**本轮不允许把“代码可同步”“29 项离线测试通过”“研究资料完整”写成正式包/业务链通过。**
