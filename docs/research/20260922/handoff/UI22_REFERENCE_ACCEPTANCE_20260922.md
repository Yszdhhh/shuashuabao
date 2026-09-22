# UI-22 参考文件验收与差异结论

状态：文件交付 PASS；源码设计内容一致性 PASS；本机前端测试 PASS；桌面真实交互/正式部署 HOLD。
核对基线：GameScript-Local @9ed8b52979f4192de9b3a3ac90e3974a9ae3eeec，主目录干净，未修改源码/安装dist/版本指针。

## 1. 三份文件核验

完整读取 UI22_DESIGN_HANDOFF_FINAL.md。以下均为实际读回 SHA256，与设计 agent 回传一致：
- UI22_index.reference.html：5a7824ab275ea313686ecaa40a979f5668d802978286e51192402e7a97ee6f63。
- UI22_index.baseline-bc228baf.html：d29b572c5fd1d8d5a3029c8c0333f17ae8b63f601a4eeaaa1550d36d2e096f2c。
- UI22_DESIGN_HANDOFF_FINAL.md：3fbc553c6c626625492b09a360f11d471cdc54fcaaa93d59e4a25473686ff88f。

路径均在 G:\刷刷宝\handoff_prompts\。
基线按 ui-v2/index.html clean 规则计算 blob 得 e974ddffa40945562c697d5ce8d35dda699cf10f，与 bc228baf 源码一致。

## 2. 内容差异最终结论

参考与当前源码都是6978行。参考438182字节/LF；当前445150字节/CRLF；当前去CR后438172字节。
对比全部行，只有第3737行不同：参考有10个普通空格，当前为空行。位置在目标局数行与声望挑战控件之间，不在脚本、样式、属性或文本内容中。

因此“不是仅换行差异”在字节层面正确，但不能据此推断设计不同。实际差异=CRLF/LF转换+删除空白行中的10个空格。没有视觉/交互/业务接线差异。
参考 blob 0d285578… 与当前 1bbad769… 不同是合理的；不应为哈希相等把尾随空格加回源码。

复现：
git -c core.autocrlf=false diff --no-index --ignore-cr-at-eol --unified=3 G:\刷刷宝\handoff_prompts\UI22_index.reference.html G:\刷刷宝\GameScript-Local\ui-v2\index.html

不需要重新移植UI、覆盖源码或为UI换新SHA。当前6a4bba4虽名为restore ui-21，实际已入库这份UI-22设计（仅清掉上述空格）。

## 3. 正式本机验证

2026-09-22 17:48，在主目录ui-v2运行真实npm/vitest：
- npm test：8个测试文件、42个测试PASS，exit=0，Vitest v1.6.1。
- kanban_contract.spec.ts：7个测试PASS（不是交接宣称的8个）。
- npm run check：tsc --noEmit，exit=0。
- 正式Vite构建：当前打包树相同源码已有17:05构建日志，496ms完成，index SHA256 da35a4a730aba2a2f88dbe9118e9f8403a5f802bfa15b216092944275f0851b5；该项引用打包日志，不冒充本轮重新构建。

6a4bba4移除的是一个读取历史桌面绝对路径的附加测试，故7/8数量差异已解释，不以替身测试作为证据。当前测试通过不等于桌面全部交互通过。

## 4. 仍需收口

- 真实宿主的过场、预检、完成、激活、小窗；_verify/verify_vite_dev.py尚未在本轮运行。
- #downgradeSteps目前是可编辑的本地值，main.ts只下发downgrade_after_failures；不能按“降低Y级已实现”交付。外发前应明确未生效或禁用这个控件；不在本次设计一致性审查中擅自增加后端降级行为。
- after-goal stop开关仍关闭；原生overlay_hud不属于本次UI设计。
- current.json仍指bc228b，正式桌面没有更新。

本文件更正此前UI参考不一致导致的“必须重新迁移/重包”假设。打包agent可继续固定9ed8b52包；不因这10个空格重启构建。包仍需完整门禁与桌面验收，不能直接发布。
