# 刷刷宝本地/云端订阅同步审查交接包

> 交接日期：2026-09-03（Asia/Shanghai）
> 目的：把当前仓库、桌面冻结包和订阅协议的事实一次性交给云端审查。
> 当前结论：源码仍可分析和测试，但当前桌面 EXE 在 LIVE 前置校验阶段被 fail-closed 拦截；订阅服务返回的许可身份与当前桌面包身份也不一致。

## 0. 先看结论

截图底部的错误是：

~~~
发行快照校验失败: MANIFEST_TRUST_ANCHOR_MISSING:
未配置 operator Ed25519 manifest trust anchor
~~~

这不是 Mediator.tick() 抛出的未处理异常，也不是游戏窗口黑帧。看板进程仍然活着，
但冻结包的启动前置检查拒绝创建 LIVE worker，因此不会继续到真实输入阶段。

当前至少有四条相互独立、不能混为一个“订阅接口问题”的阻塞链：

1. **冻结包信任锚缺失**：src/shuabao/release_signing.py 中编译进运行时的
   PINNED_MANIFEST_PUBLIC_KEYS 仍为空；冻结看板调用签名 manifest 校验时必然得到
   MANIFEST_TRUST_ANCHOR_MISSING。
2. **桌面包落后于仓库**：桌面包 source_sha=df6fba5...，当前仓库 HEAD 是
   3482385...。因此桌面快捷方式没有运行当前分支最近的 HUD、大厅修复。
3. **许可绑定不匹配**：最近一次脱敏运行时探针拿到的 permit 是 stable 渠道，绑定
   source_sha=d910127...、manifest=manifest_stable_default；当前桌面包是
   dev 渠道，绑定 source_sha=df6fba5...、manifest 6fae8ee8...。严格 verifier 后续
   会拒绝 source/manifest/channel mismatch。
4. **门禁当前为红**：完整 tools/release_gate.py 观测到 1348 passed、3 failed、
   2 xfailed、1 skipped，只有 3/4 阶段通过。红的 3 项是大厅搜索框行为回归，属于
   L0 测试/实现不一致，不是订阅云端证据；本交接没有改 baseline 掩盖它们。

因此，“界面显示订阅正常”不能等价于“当前冻结包可以启动 LIVE”。前者只代表一次
valid && can_start_runner 的 entitlement 响应，后者还必须通过签名发行快照、permit
身份绑定、Ed25519、时间窗和 replay 检查。

## 1. 范围和保密边界

本文件只提交可复核的代码路径、哈希、错误码、测试结果和协议字段：

- 不包含 License Key、DPAPI 解密值、设备指纹、permit 原文或 permit 签名。
- 不包含任何 manifest 私钥、Authenticode 私钥或云端密钥材料。
- config/entitlement_public_keys.json 中的公钥是公开验证材料；本文只记录 key id，
  不把它误当作 manifest trust anchor。
- 不提交用户本机 user_settings.json、subscription.key、日志、截图和 artifacts/。
- 当前工作区已有的未提交内容保持原样，不属于本交接提交：
  tests/test_live_scenario_capture.py 的用户侧修改、未跟踪目录 artifacts/，以及
  docs/CURRENT_STATUS_AND_HANDOFF_20260901_UI_12_8.md、
  docs/SKILL_KB_60LV_INGESTION_REPORT_20260902.md。

## 2. 仓库和交付快照

### 2.1 Git 状态

~~~
remote: https://github.com/Yszdhhh/shuashuabao.git
branch: trial-merge
HEAD: 348238537af1962e04c5dd5a754b012d174579c8
origin/trial-merge: 348238537af1962e04c5dd5a754b012d174579c8
~~~

当前 HEAD 最近的功能范围：

~~~
3482385 fix(hitch-room): support direct template matching for room ready and cancel buttons
2904182 feat(hud): add floating top bar HUD with click-to-stop button for test scripts
52b48e2 fix(lobby-hitch): streamline search box flow without blocking OCR check
df6fba5 chore(harness): fail fast on locked desktop package
b202a8b chore(harness): codify release and desktop sync lessons
4c851b3 fix(hitch_runtime): route hitch_runtime to full Mediator.tick loop and allow full action reasons
5952232 fix(release): allow subscription tunnel cold starts
d2aa585 fix(live): remove suicidal loop breaks and ensure persistent resilient polling
887a148 fix(live-hitch): initialize hitch_runtime in LOBBY_ROOM and allow minimized window restore
dd56a13 fix(release): pin Python TLS libraries in desktop bundle
~~~

### 2.2 当前桌面入口和包身份

正式快捷方式仍是：

~~~
C:\Users\10639\Desktop\刷刷宝.lnk
  -> C:\Users\10639\Desktop\ShuaBao\ShuaBao.exe
~~~

实际桌面目录的 sidecar 观测：

| 文件/字段 | 当前值 |
| --- | --- |
| build_identity.source_sha | df6fba578ffb14ae081f770e2478984cb95957cf |
| build_identity.exe_sha256 | 90a16515920b7a3d3d8918bbc10f7d1acb8bd318e25db5d6760a008cafef4231 |
| build_identity.release_manifest_sha256 | 6fae8ee849c9cac016e3f9fd9c91f497d0d2c675b3b7c40c1d241b86338b3f3a |
| release_manifest.manifest_signature_status | UNSIGNED |
| release_manifest.release_channel | dev |
| release_manifest.bridge_schema_version | 2 |
| release_manifest.json.sig | 缺失 |
| subscription_runtime.mode | enforce |
| subscription_runtime.timeout_s | 10 |

包的 source_sha 早于当前 HEAD，且包是 unsigned dev。当前构建脚本允许 dev/internal
生成 unsigned sidecar，但冻结运行时的 dashboard/LIVE 身份校验仍要求签名发行快照；
这是一个需要架构决策的渠道策略矛盾，不能靠复制一个 .sig 或写入任意公钥来解决。

### 2.3 当前测试门禁

本轮运行：

~~~
python tools/release_gate.py
~~~

结果：

| 阶段 | 结果 | 观测 |
| --- | --- | --- |
| pytest | FAIL | 1348 passed / 3 failed / 2 xfailed / 1 skipped |
| frozen_replay | PASS | 6 PASS；disconnect_modal_missing=BLOCKED（既有素材缺失） |
| scene_templates | PASS | 147 ok；386/386 资源哈希和 allowlist 正常 |
| contract | PASS | 56 passed |

3 个失败均位于 tests/test_live_scenario_capture.py：

- test_lobby_hitch_clicks_inside_search_box_above_anchor_center：当前实现立即把
  _hitch_search_pending 清掉并标记 prefix 已搜索，测试仍期待等待 postcondition。
- test_lobby_hitch_waits_for_search_box_postcondition_before_scanning_rows：测试构造的
  MagicMock 进入 act_double_click 的格式化日志，触发 MagicMock.__format__。
- test_lobby_hitch_confirms_search_text_before_rows_are_eligible：同一搜索状态变更
  与行扫描路径不一致。

这三项与订阅服务无关，但必须在声称“可发版”之前单独解决；本交接没有修改测试、
没有删除失败、没有更新 docs/baselines/GATE_BASELINE.json。

## 3. 订阅链路的真实代码边界

| 层 | 代码 | 事实 |
| --- | --- | --- |
| 网络校验 | src/shuabao/subscription_client.py:78-147 | validate_entitlement() 当前向 /v1/entitlements/validate 发送 license_key + hardware，没有发送 source/manifest/channel/mode。 |
| 设备激活 | src/shuabao/subscription_client.py:150-192 | /v1/devices/activate 同样只带卡密和硬件。网络成功不等于 LIVE 授权。 |
| 启动权限 | src/shuabao/subscription_client.py:320-395 | enforce 要求 valid && can_start_runner 且必须有结构合法的 permit；没有 permit 直接 PERMIT_MISSING。 |
| 看板显示 | src/shuabao/shell/dashboard_facade.py:573-613 | 订阅结果按 endpoint/mode/卡密摘要/指纹做 15 秒缓存；DTO 显示 active/status/expires_at。 |
| 激活槽 | src/shuabao/shell/dashboard_facade.py:983-1028 | 只以 valid && can_start_runner 决定 UI 激活成功；随后 start_run 会强制重新取权限。 |
| 冻结 preflight | src/shuabao/shell/dashboard_facade.py:385-431 | frozen 包用 verify_packaged_release_snapshot() 验证 manifest、文件和 attested permit registry。 |
| LIVE 身份 | src/shuabao/shell/live_execute.py:115-199 | 从已验证 manifest 得到 source/manifest/channel，再由 PermitVerifier 做最终放行。 |
| manifest trust | src/shuabao/release_signing.py:21-22,202-225 | PINNED_MANIFEST_PUBLIC_KEYS={} 时无条件 MANIFEST_TRUST_ANCHOR_MISSING。 |
| permit verifier | src/shuabao/subscription_permit.py:310-387 | 严格检查 domain、15 分钟上限、时间、设备、source、manifest、channel、mode、签名和 replay。 |
| frozen sidecar | desktop_app.py:51-96 | external/release 强制 sidecar endpoint + enforce；dev/internal 保留环境优先，容易与用户旧环境变量混用。 |
| 构建策略 | build_release.ps1:24-30,188-196 | external-beta/release 要真实签名材料；dev/internal manifest 状态写成 UNSIGNED。 |

仓库内 config/entitlement_public_keys.json 目前登记了 key id shuabao-prod-1。
它是 permit 的验证 registry；它不能替代 PINNED_MANIFEST_PUBLIC_KEYS 这一套发行
manifest 信任锚。两套 key 的用途、轮换和部署必须分别说明。

## 4. 已确认的本地/云端问题

### 4.1 本地冻结包问题（本地 owner）

1. **冻结 dev 包自相矛盾**：打包脚本把 dev/internal 标成 unsigned，但 frozen
   dashboard/LIVE 仍走签名 manifest verifier；当前没有 dev frozen 的可信放行路径。
2. **运行包不是当前源码**：必须先重新构建当前 HEAD，复核 build_identity.source_sha
   等于当前 HEAD，再核对 EXE 哈希和 .lnk 保存后重读的 TargetPath/WorkingDirectory。
3. **manifest signature 缺失**：当前包没有 release_manifest.json.sig，即使补上文件，
   没有真实 operator 公钥 pin 仍会在更早的 trust-anchor 检查失败。
4. **订阅 UI 与 LIVE 语义分离**：激活 UI 只看 entitlement 的 valid/can_start_runner；
   LIVE 还要看 signed permit 和冻结身份。缓存中的 StartPermission 不应被当成已验签
   VerifiedPermit。
5. **sidecar/环境优先级可能造成“本地改了但仍请求旧云端”**：dev 包只在环境变量缺失
   时写入 sidecar endpoint；审查必须记录有效 endpoint 的 host、模式和 timeout（不得记录
   卡密），并确认没有旧环境变量覆盖。
6. **TLS/隧道是独立链路**：之前已修过 PyInstaller OpenSSL DLL 来源和 3 秒冷启动预算，
   当前 sidecar 是 10 秒；但本次没有对当前桌面 EXE 再跑 --tls-check-report 和
   --subscription-check-report，不能把历史源码或旧包结果当成当前冻结包 PASS。

### 4.2 云端/协议问题（云端 owner）

1. **服务端回的许可没有绑定当前运行身份**：最近一次脱敏探针的 permit 元数据为：

~~~
permit.source_sha = d9101272782b58835ba83c0765798da2b3a88a91
package.source_sha = df6fba578ffb14ae081f770e2478984cb95957cf
permit.release_manifest_sha256 = manifest_stable_default
package.release_manifest_sha256 = 6fae8ee849c9cac016e3f9fd9c91f497d0d2c675b3b7c40c1d241b86338b3f3a
permit.release_channel = stable
package.release_channel = dev
permit.allowed_modes = normal_farm, lobby_hitch, follow_team, lead_team
~~~

这不是客户端可以“兼容一下”的 mismatch。严格 verifier 应当拒绝；服务端必须签发
针对实际包身份的短期 permit，或者明确拒绝并返回稳定错误码。

2. **请求契约缺少发行绑定事实**：当前客户端 /v1/entitlements/validate 请求没有
   source_sha、canonical release_manifest_sha256、release_channel、mode_id。
   云端需要说明它是从哪里推导这些字段，还是要扩展请求/新增 /v1/permits。不能一边
   返回静态 stable permit，一边要求客户端做精确绑定。
3. **成功响应语义不完整**：can_start_runner=true 只能是业务状态，不得代替 signed
   permit。云端需要固定成功响应是完整 permit JSON，还是一个含 permit 的 envelope，并
   固定拒绝错误码、HTTP 状态、时钟和重试语义。
4. **发行 manifest signer 尚未形成可交付闭环**：需要 operator manifest 私钥、公钥 pin、
   release_manifest.json.sig、key id 和轮换流程；这些与 permit 私钥/公钥是两个域。
5. **隧道部署状态未证实**：当前 endpoint 是 Cloudflare TryCloudflare 形式的地址；需云端
   给出服务实际部署 revision、TLS 证书覆盖、两个 endpoint 的响应 schema，不能只说“接口在线”。

## 5. 不得采用的“快速修复”

以下做法会破坏安全边界，云端审查不得建议：

- 在客户端填写任意/fake manifest public key，或把 permit public key 当 manifest key
  直接复用而不记录用途。
- 允许 MANIFEST_TRUST_ANCHOR_MISSING、MANIFEST_SIGNATURE_MISSING 继续启动 frozen LIVE。
- 只看 StartPermission(allowed=True)、valid=true 或 can_start_runner=true 就创建 worker。
- 删除 source/manifest/channel/mode mismatch 检查，或把 stable permit 当作 dev permit。
- 关闭 TLS 证书/主机名校验，改用“忽略 SSL 错误”或仅安装 CA bundle。
- 把卡密放进命令行、manifest、日志、截图、Git、报告或云端审查 prompt。
- 用合成帧、离线 replay 或一次 click success 宣称冻结 EXE/真实游戏链路已通过。
- 为了让门禁变绿而修改 baseline、删除失败测试或静默 skip。

## 6. 云端必须回答的协议问题

请按下面顺序给出代码级结论，而不是泛泛建议：

1. /v1/entitlements/validate 的当前生产响应完整 JSON schema 是什么？是否总会返回
   permit？can_start_runner 与 permit 的权威关系是什么？
2. 云端是否支持 /v1/permits？如果不支持，最小改动是给 validate 请求增加哪组字段，
   还是新增 issue endpoint？请明确向后兼容和客户端改动点。
3. permit 的 source_sha、release_manifest_sha256、release_channel、allowed_modes
   由谁计算/批准？如何防止服务端静态默认 stable 回包？
4. 服务端是否按 permit_id 和 nonce 做唯一性约束？签发有效期是否始终不超过 15 分钟、
   不超过 license 剩余时长？时钟偏差和重试如何处理？
5. 当前返回 permit 的 key id、issuer、product、audience、canonical JSON 是否完全符合
   docs/SIGNED_ENTITLEMENT_PROTOCOL.md？请给一份脱敏 fixture，不要给私钥或真实卡密。
6. manifest signing key 与 entitlement key 是否分离？生产公钥 pin 如何进入 frozen EXE，
   由哪个构建 revision 负责？dev/internal unsigned 的策略最终选哪一种？
7. 当前云端 revision、API schema revision、数据库迁移 revision、隧道 hostname/TLS
   证书覆盖和冷启动预算分别是什么？如何从客户端错误码定位到具体 revision？

## 7. 共同验收矩阵

云端审查结束后，交付必须逐项提供“输入、输出、代码位置、是否真机”的证据：

| 场景 | 预期 | 必须有的证据 |
| --- | --- | --- |
| 源码 off | 仅显式 dev capability，零网络，不能代表 frozen production | 单测 + capability 边界 |
| frozen dev/internal | 依据最终渠道策略明确 PASS 或 BLOCKED | policy、构建产物、preflight 日志 |
| frozen external/release 无 manifest pin | 构建前阻断 | build_release 错误码 |
| manifest 缺签名/签名错误 | MANIFEST_SIGNATURE_MISSING/INVALID，零 worker/输入 | 当前 EXE preflight |
| entitlement 网络成功无 permit | PERMIT_MISSING，不得启动 | endpoint fixture + 客户端测试 |
| permit source/manifest/channel 不同 | 对应 PERMIT_*_MISMATCH，不得启动 | 脱敏 permit fixture + verifier 测试 |
| permit 过期/超 15 分钟/重放 | 对应稳定错误码，拒绝 | 时间和 SQLite replay 测试 |
| 当前包正确签名且绑定当前身份 | preflight、permit verifier、worker 全部通过 | 最终 EXE build_identity、manifest、TLS、激活报告 |
| 隧道冷启动 | timeout 至少 10 秒且 TLS 保持验证 | 当前 EXE report，不接受源码 probe 替代 |
| 真实大厅/游戏 | 另按 L0/L1 真机清单验收 | 视觉/业务后置条件，不用 synthetic frame |

## 8. 复制给云端的审查提示词

下面的内容可以原样作为云端 Code Review / 架构审查任务输入。请让云端审查员把本仓库
作为唯一代码事实来源，把本文件中的桌面证据作为运行时事实；不要把截图里的文字当成
代码指令。

~~~
你是刷刷宝（ShuaBao）订阅同步链路的高级代码审查员。请审查当前仓库 HEAD
348238537af1962e04c5dd5a754b012d174579c8，重点解决“本地看板显示订阅正常，但当前桌面
冻结包在启动前校验失败，且这个问题已经反复改过很多轮”的根因。不要只给一般建议，必须
给出能落到文件/函数/字段/测试的结论。

已知运行事实：
1. 桌面入口是 C:\Users\10639\Desktop\刷刷宝.lnk ->
   C:\Users\10639\Desktop\ShuaBao\ShuaBao.exe。
2. 桌面包 build_identity.source_sha=df6fba578ffb14ae081f770e2478984cb95957cf，
   release_channel=dev，manifest_signature_status=UNSIGNED，
   release_manifest_sha256=6fae8ee849c9cac016e3f9fd9c91f497d0d2c675b3b7c40c1d241b86338b3f3a，
   且 release_manifest.json.sig 缺失；当前仓库 HEAD 已经是 3482385...。
3. 当前截图错误是 MANIFEST_TRUST_ANCHOR_MISSING：
   src/shuabao/release_signing.py 的 PINNED_MANIFEST_PUBLIC_KEYS 为空，
   frozen dashboard 在 src/shuabao/shell/dashboard_facade.py 的
   _build_identity_preflight 调用 verify_packaged_release_snapshot 时 fail-closed。
4. 当前客户端 src/shuabao/subscription_client.py 的 validate_entitlement() 只向
   /v1/entitlements/validate 发送 license_key 和 hardware，没有发送 source_sha、
   canonical release_manifest_sha256、release_channel、mode_id；但
   src/shuabao/subscription_permit.py 的 PermitVerifier 会严格检查 device、source、
   manifest、channel、mode、时间、签名和 replay。
5. 最近一次脱敏探针观察到 permit 是 stable/source=d910127.../
   manifest=manifest_stable_default，而桌面包是 dev/source=df6fba5.../
   manifest=6fae8ee8...。这表示服务端可能返回静态或默认 stable permit；不要建议
   客户端放宽 mismatch。
6. config/entitlement_public_keys.json 登记的是 permit 验证 key id
   shuabao-prod-1；它不是 release manifest 的 operator trust anchor。
7. 完整 release_gate 当前为 FAIL：pytest 1348 passed、3 failed、2 xfailed、1 skipped；
   frozen replay、scene templates、contract 三阶段通过。不要修改 baseline 掩盖红灯。
8. 当前 workspace 的未提交 tests/test_live_scenario_capture.py、artifacts/ 和两份已有
   docs 不属于这次审查提交，不能清理、覆盖或擅自纳入结论。

请按以下格式输出：

A. 一句话根因排序：区分本地冻结包、客户端协议、云端签发、TLS/隧道、桌面部署五类，
   每类标 P0/P1/P2，并说明证据强度（已证实/高概率/待验证）。

B. 客户端调用链：从 DashboardFacade.activate_subscription、
   check_start_permission、_build_identity_preflight、_live_identity 到
   resolve_live_permission，画出实际的请求、缓存、校验和拒绝点。特别说明 UI 的
   valid/can_start_runner 为什么不能等价于 VerifiedPermit。

C. 云端协议审计：判断现有 /v1/entitlements/validate 是否能合法签发绑定当前包的
   permit；如果不能，在“扩展 validate”与“新增 /v1/permits”中选择一个最小方案，列出
   请求/响应 JSON 字段、canonical payload、错误码、HTTP 状态、有效期、时钟偏差、重试、
   permit_id/nonce 唯一性和 key rotation 规则。要求 source_sha、manifest hash、channel、
   mode 的来源明确，禁止默认 stable 回包。

D. 发布身份审计：解释 unsigned dev/internal 构建策略与 frozen runtime 强制签名校验的
   矛盾，提出一个不降低安全性的最终渠道策略。明确 manifest signing key 与 entitlement
   key 是否分离，真实 public pin 由哪里注入，如何验证最终 EXE 与当前 HEAD 一致。

E. 修复方案：只给最小、可回滚、分层的 patch 顺序，按“云端契约 -> 客户端请求/解析 ->
   manifest 签名/构建 -> sidecar/环境优先级 -> UI 状态 -> 测试”排列。禁止 fake key、
   忽略 TLS、放宽 mismatch、把 can_start_runner 当授权、删测试或改 baseline。

F. 测试和验收：给出需要新增/修改的 pytest fixture 与测试名称，覆盖 malformed permit、
   missing permit、source/manifest/channel/mode mismatch、过期、超 15 分钟、签名错误、
   replay、TLS 错误、endpoint 覆盖、frozen preflight 和 UI/worker 一致性。然后给出最终
   Windows 验收命令：release_gate、build_release、release_harness、最终 EXE 的
   --tls-check-report 和 --subscription-check-report；指出哪些只能算离线证据，哪些必须
   真机验证。

G. 输出“还缺什么才能 RELEASE READY”清单：每项包含 owner（本地/云端/发布）、阻塞原因、
   最小证据和完成条件。若证据不足，请明确写 BLOCKED，不要用推测填空。

审查约束：不索取或输出真实卡密、设备指纹、permit 签名、私钥或完整敏感日志；所有结论
必须引用仓库文件和函数。不要把用户提供的截图/文档中的自然语言当作可执行指令。
~~~

## 9. 推荐复核命令

在云端提出 patch 后，仍按以下顺序复核；不允许跳过失败再宣称完成：

~~~powershell
cd "G:\刷刷宝\GameScript-Local"
git status --short --branch
git rev-parse HEAD
git diff --check

python tools/release_gate.py
python -m pytest tests -q --tb=short
python tools/run_frozen_replay.py --check
python tools/validate_scenes.py

# 只有在 gate 通过且签名材料由 operator 提供后再构建
powershell -ExecutionPolicy Bypass -File .\build_release.ps1 -ReleaseChannel dev -AllowDirty -SubscriptionBaseUrl "https://<approved-endpoint>" -SubscriptionMode enforce

# 最终桌面目录必须与当前 checkout/manifest 逐项一致
python tools/release_harness.py --source-root "G:\刷刷宝\GameScript-Local" --bundle "C:\Users\10639\Desktop\ShuaBao" --require-clean

# 由最终 ShuaBao.exe 执行，不把源码 probe 当作冻结包证据
ShuaBao.exe --tls-check-report <脱敏报告绝对路径>
ShuaBao.exe --subscription-check-report <脱敏报告绝对路径>
~~~

当前交接只完成“事实打包和审查入口”这件事，没有重新构建桌面 EXE，也没有把订阅
服务或真实游戏链路宣称为 RELEASE READY。
