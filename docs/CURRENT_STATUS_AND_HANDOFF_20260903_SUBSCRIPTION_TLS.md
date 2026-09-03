# 2026-09-03：桌面订阅 TLS 打包故障

TLS 修复范围为 Shell/订阅传输与打包，不执行 KK 输入。

后续部署补记：`4320201` 在 TLS 提交后新增了压力转移功能，同时误删原 F4 helper 的
`LoopAction.Continue` 返回值和新局 `_auto_task_recheck_at` 重置。
两处均已由离线测试复现；为解除当前分支构建阻塞，单独补回原有语句，保留新增功能。
该补记不代表压力转移已通过真机业务验证。

补记验证：focused + contract 为 117 passed；完整门禁为 1342 passed / 2 xfailed /
1 skipped，Standard 四阶段 4/4 PASS。执行期间另有操作修改
`tools/live_scenario_capture.py`，不属于本次修复，不能将其擅自提交/覆盖。

## 已确认的故障证据

- 排查基线：`trial-merge@603fecaefd535f95720662ea3794109e29fc5671`。
- 故障桌面 EXE SHA-256：`a22f21a10a5311474c3725ec38b8a6a0627290b119c7e02b80e7f5f21c624e2f`。
- `build/ShuaBao/Analysis-00.toc` / `COLLECT-00.toc` 中 `_ssl.pyd` 来自 Python，
  `libssl-3-x64.dll` / `libcrypto-3-x64.dll` 却来自宿主 Poppler 的 Library/bin。
- 故障桌面 DLL 的哈希与 Poppler 相同。将这对 DLL 载入独立 Python 进程后，
  `ssl.create_default_context()` 在尚未请求 VPS 时抛出
  `[ASN1: NOT_ENOUGH_DATA] not enough data (_ssl.c:4057)`。
- 错误组合报告 OpenSSL 3.6.3；Python 原配为 OpenSSL 3.5.6。
  因此此处 SSL 失败不能归因为卡密错误或云端接口字段不匹配。
- 先前 `603feca` 的延迟 permit 导入不解决整套 GUI 的加载链：其他 Shell 模块仍会导入它。
  本轮撤回该无效绕行，将导入顺序测试替换为实际 DLL 来源、TLS 初始化失败回归。

## 最小修复与验证边界

- `ShuaBao.spec` 显式收集当前 Python 安装的 TLS 库，并在 Analysis 后约束同名库来源；
  缺少原配库立即阻断构建。不新增依赖，不关闭证书/主机名校验。
- TLS 错误仅展示类型和 OpenSSL 符号码，不输出完整异常、卡密或请求。
- 正式 `ShuaBao.exe --tls-check-report <绝对报告路径>`：离线证书上下文自检。
- 正式 `ShuaBao.exe --subscription-check-report <绝对报告路径>`：构造实际 Web 看板，
  调用同一 `DashboardFacade.activate_subscription`，不调用启动运行。
  此项会真实绑定并通过现有 DPAPI 保存卡密，只能在用户明确授权后使用。
  卡密只从进程环境/正常 DPAPI 加载读取，不放命令行参数或报告。
- 源码单测、独立小型 probe 均不等于正式 EXE 激活成功。
  最终必须检查实际桌面 EXE 生成的报告 `frozen=true`、`verified_tls=true`、
  `ok=true`、订阅状态及到期时间。UI 手工点击验收与该接口自检应分别说明。

## 交付身份与剩余验证

本轮源码 focused：109 passed。项目实际 `tools/release_gate.py` 退出码 0：
全量 pytest 1341 passed / 2 xfailed / 1 skipped，四阶段 4/4 PASS；
契约 56 passed，模板 147/147，素材 386/386，缺失/陈旧/hash mismatch 均为 0。
冻结回放的 `disconnect_modal_missing` 仍为已有 BLOCKED，Standard PASS 不等于零缺陷或真机 PASS。

修复源码身份是包含本文件的提交；实际构建后必须读取
`C:\Users\10639\Desktop\ShuaBao\build_identity.json` 的 `source_sha` / `exe_sha256`，
和仓库 HEAD / EXE 实际哈希逐项一致后才可交付。构建前不预测产物哈希；
构建与真实激活结果在当轮工具证据及最终交付中报告。

正式入口：`C:\Users\10639\Desktop\刷刷宝.lnk` →
`C:\Users\10639\Desktop\ShuaBao\ShuaBao.exe`。

订阅修复不是游戏链路验收。本轮没有执行大厅 4→3、四种组队、Boss/传家宝、
队友退出等待、遮挡/黑帧的真实游戏验证；不得据此宣称 RELEASE READY。
用户原有 untracked artifacts/captures/docs 不清理、不提交。
