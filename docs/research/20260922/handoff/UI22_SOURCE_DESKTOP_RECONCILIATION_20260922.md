# UI-22 源码、交接与桌面核对

日期：2026-09-22。只读核对；未修改源码、dist、签名、版本指针或快捷方式。

## 结论

桌面仍是 bc228b 旧包，确实没有 UI-22。当前主目录 UI-22 已被提交并进入候选包，交接词中“尚未 commit”的描述已不符合实物。UI-22 完整交互验收仍待完成；标题标识不是全部验收。

主目录 HEAD：9ed8b52979f4192de9b3a3ac90e3974a9ae3eeec，status 干净。
`ui-v2/index.html` 的工作文件 Git blob 与 HEAD blob 均为 `1bbad769baf09d8f37e199659a11ae9b84925b27`。
源文件 SHA-256：`d7f49253ab9fcfedc19302c8b91231abc29e7e90df184659a8f0d0d91ef67881`。

实际入库 commit：6a4bba469f609a2a1352c1f12e10df8b8809a5ec，提交名为 `feat(shell): restore ui-21 dashboard in source`，但该提交中的 UI_BUILD 已经是 UI-22。此前主架构按提交名沿用 UI-21 称呼不准确。

## 三处实物

| 位置 | UI-22 | index.html SHA-256 |
|---|---|---|
| 正式安装 app-0.3-internal-pilot-bc228bafa05c/_internal/web/dist | 否 | d49fcccc9ebf4dc0bc93bd5a60296f5370ceb7b828919f92a9c6a478998472f2 |
| Artifacts/internal-pilot/8880e483-internal-pilot/_internal/web/dist | 是 | da35a4a730aba2a2f88dbe9118e9f8403a5f802bfa15b216092944275f0851b5 |
| Worktrees/ui21-hitch-internal-pilot-20260922/ui-v2/dist（manifest source=9ed8b52） | 是 | da35a4a730aba2a2f88dbe9118e9f8403a5f802bfa15b216092944275f0851b5 |

源码与构建后 HTML 的哈希不应直接要求相等；分别核对源文件身份和同次构建/包内文件身份。
打包 worktree 的源码 index.html 与主目录源文件 SHA-256 相同。

桌面 `C:\Users\10639\Desktop\刷刷宝.lnk` → LocalAppData/ShuaBao/launcher/ShuaBaoLauncher.vbs → 同目录 ps1 → LocalAppData/ShuaBao/current.json。
current.json 的 current_source_sha 仍是 bc228bafa05caab43351b4207b3512d97bac462b，指向旧 app 目录；因此启动旧 UI 是当前指针的直接结果。

## 交接词逐项核对

- “UI-22 未 commit”：已过时，无需重复 commit 或还原源码。
- “main.ts 被关闭”：当前源文件末尾保留 type=module 的 ./src/main.ts；静态接线存在，运行时交互还需验证。
- “胶囊、玻璃工具栏、雅黑不在源码”：当前源码有相关样式和文字；仅此不能证明所有历史小窗修复完整。
- “6a906709 非祖先说明 UI 丢失”：该 SHA 对当前 HEAD 和 bc228baf 的 ancestor 检查均为 1，但提交自身只改 config/entitlement_public_keys.json；祖先检查不能代替按文件/行为对比，不能据此整段合回旧分支。
- “结束脚本不得开放”：新增 after-goal stop 控件受 __SB_ALLOW_STOP_AFTER__ 条件保护，搜索当前 index/main 源码未见启用赋值。它与现有紧急停止按钮不是同一控件。
- 现有 ui-v2/docs 两份迁移文档确实是 09-12 文档，不能代表本次设计交接。
- 用户贴出的交接摘要未含设计参考的完整 SHA-256、备份路径或逐项验收原文；本次查到的项目交接目录未发现该完整交接。不能仅凭 UI-22 标签认定与设计 agent 最终参考完全相同。

## 当前执行安排

1. 保留正在运行的 9ed8b52 打包线；它已包含上述 UI-22 源码。继续完成门禁、签名与 frozen harness，不再重复迁移。
2. 对照设计 agent 完整交接哈希；若等于本记录的源文件 SHA，进入 UI 验收；若不同，先保护差异并审查，不覆盖当前源码。
3. 验收真实 main.ts/宿主运行下的标题 UI-22、过场、预检、完成、激活、小窗；静态哈希或预览不能替代这些结果。
4. 包和 UI 验收通过后，按 Owner 已定发布边界执行版本登记与正式切换。current.json、目标 app identity 和桌面入口必须 read-after-write 复核。
5. 最终与代码同目录的 UI 交接文档应在 UI 收口分支中提交；本记录暂存仓外，保持当前主目录干净并避免干扰打包。

不热改安装 dist，不手工篡改签名清单哈希，不因提交名/UI 标签混淆创建重复业务提交。

## 后续补充：设计参考身份不同，正式 UI 验收 HOLD

Owner 随后提供设计 agent 的参考信息（尚未取得文件本体核验）：
- UI22_index.reference.html：438182 字节、LF。
- SHA256：5a7824ab275ea313686ecaa40a979f5668d802978286e51192402e7a97ee6f63。
- Git blob：0d285578ad537058cbb0a0f283232684892bd867。

它与当前已提交源文件 blob 1bbad769baf09d8f37e199659a11ae9b84925b27 不同。因此上文“含 UI-22”只说明含构建号及该实现，不证明与设计最终参考相同。正式 UI 验收暂停在内容差异审查，当前 9ed8b52 包不能据此宣称最终设计已落地。

本轮检索未在 handoff_prompts、Downloads、Desktop 顶层、Documents/Codex、项目事实目录找到参考附件；当前任务附件列表为空；仓库也没有参考 blob 对象。没有内容就不能生成 diff 或按哈希恢复文件。

另有基线疑点：当前仓库 `bc228baf:ui-v2/index.html` 的真实 blob 为 e974ddffa40945562c697d5ce8d35dda699cf10f，与回传所称基线 blob 前缀 ab335c9d 不同。需取得 baseline 附件后核实它是源码、构建产物还是另一个副本，不能预设祖先关系做覆盖。

Git blob 也不是天然无视换行：它标识实际存储字节。core.autocrlf=true 时应按 ui-v2/index.html 的 clean 规则计算待提交 blob，并独立校验原始参考 SHA256；最终用语义 diff 判定差异。

参考文件取得后的顺序：核验原始 SHA/长度 → 明确基线来源 → 参考与当前的归一化差异审查 → 保留有效增量并在独立 UI 分支处理 → 测试与真实主脚本联调 → 重新确定发布候选。差异大也不能不经审查整文件替换。
