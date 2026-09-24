# 9ed8b529 internal-pilot 候选包验收

结论：候选构建/工件一致性 PASS；正式桌面切换与业务验收 HOLD。

## 已核对身份

- 产物：G:\刷刷宝\Artifacts\internal-pilot\9ed8b529-internal-pilot
- source_sha：9ed8b52979f4192de9b3a3ac90e3974a9ae3eeec
- canonical release_manifest_sha256：1bb270b5b78a2088b102b2eb977bcf498aab2e2e49c1182f035aa5128811ac99（identity 与冻结核验记录一致；非 JSON 原始文件哈希）
- EXE SHA256：ccfd8ee8bdaf3fe7e7f22923f9ec76131d82b37107e297c0a6bab80808f758a2（主架构直接对产物重算一致）
- 包内 UI index SHA256：da35a4a730aba2a2f88dbe9118e9f8403a5f802bfa15b216092944275f0851b5（主架构重算，与包内 web manifest 一致）
- channel internal-pilot；enforce；HTTPS endpoint entitlement.shuashuabao.xyz；harness 记录 timeout 10s、SIGNED、生产验签通过。

## 门禁与冻结证据

日志根：G:\刷刷宝\Artifacts\internal-pilot

- build-9ed8b52-20260922.continue.meta.txt：17:50:11–18:13:43，EXIT=0，NO_DEPLOY=1、SKIP_GATE=0、ALLOW_DIRTY=0。
- build-9ed8b52-20260922.continue.stdout.log：pytest 2490 passed / 2 xfailed / 2 skipped；frozen replay PASS（disconnect_modal_missing 仍 BLOCKED）；templates 148、asset files 401；contract 58 passed；4/4 PASS。
- harness-1-9ed8b529.txt：PASS。
- harness-2-9ed8b529.json：PASS，errors=[]；记录生产签名/完整性核验通过。本轮读取核验记录，不另跑一遍完整冻结检查。
- tls-9ed8b529-20260922.json：frozen=true、ok=true、verified_tls=true、ca_count=201；executable 指向本候选产物。
- stderr 文件非空（93631 字节），末尾为 PyInstaller 构建完成；不能描述为 stderr 为空。
- 本轮检查 PID44300、41080 均不存在；未启动新的测试、构建或 EXE。

## 入口与边界

读取 C:\Users\10639\AppData\Local\ShuaBao\current.json：current_source_sha 仍为 bc228bafa05caab43351b4207b3512d97bac462b。

三枚桌面快捷方式已只读解析：

- C:\Users\10639\Desktop\刷刷宝.lnk → LocalAppData\ShuaBao\launcher\ShuaBaoLauncher.vbs（正式路由未切候选）。
- C:\Users\10639\Desktop\刷刷宝-快速测试.lnk → 主目录 tools\quick_test.ps1。
- C:\Users\10639\Desktop\刷刷宝 实机测试台.lnk → 主目录 live_scenario_launcher.ps1，source SHA9ed8b529，ROUNDS30、DURATION36000。

本轮无写入入口、current.json 或登记服务；未对“TLS 检查前后快捷方式哈希未变”另作历史快照比对，只确认当前目标。主目录 git status --short 为空。

## 尚未放行

1. 本包是9ed8b529，未包含尚未交付的 Boss unconfirmed 最小修正。停止空滚与业务受理分开；当前包不可宣传该后置问题已解决。
2. 真实桌面 UI 交互、正常 UAC 快速测试路径、真实游戏链路尚未据本包验收。
3. “降低Y级”仍是前端本地值，后端不支持；正式外发前需处理误导展示，不在打包阶段偷偷加后端字段。
4. stdout 第8行 npm audit 摘要：4 vulnerabilities（2 moderate / 1 high / 1 critical）。仅有总数，缺依赖链与生产影响分诊，不判断可利用性；不执行 npm audit fix --force，不借机升级依赖。
5. meta 的 UI_MARK“UI 最终参考未对齐，禁止正式切换”为启动时旧备注。UI 内容差异已由 UI22_REFERENCE_ACCEPTANCE_20260922.md 收口，原始 meta 保留，不回改历史日志；正式 HOLD 仍有以上独立原因。

后续：等待原 Boss agent 最小补丁；主架构审查后 merge→identity→独占门禁。确认最终源码身份后再安排签名重打包，不补丁覆盖现有签名工件、不提前反复重建。当前9ed8b529包保留为可追溯候选，不删除。
