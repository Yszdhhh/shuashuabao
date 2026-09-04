# 发布 Harness · 反复失败后的硬规则

这份记录不是背景介绍，而是后续 Agent 执行发布、桌面同步和订阅排查时的
**可执行约束**。它把 2026-09-03 之前几轮“源码看起来已修、用户桌面仍失败”的
经验固化为门禁；如果本文件与旧交接文档冲突，以本文件和当前 `HEAD` 为准。

## 1. 已确认的事故链

### 1.1 源码 Python 通过，不代表桌面 EXE 通过

曾经出现过下面的假象：

```text
仓库 Python 调 activate_device()       PASS
桌面 ShuaBao.exe 点击激活               SSLError
```

原因是两者不是同一个运行时。PyInstaller onedir 包有自己的 `_internal` 目录，
它实际加载的 DLL 可能与开发环境不同。后续 Agent 不得用源码 CLI 的成功替代最终
桌面 EXE 的验证。

### 1.2 这次的主因是 OpenSSL DLL 同名错配，不是 VPS 卡库

`_ssl.pyd` 需要 Python 配套的 `libssl-3-x64.dll` / `libcrypto-3-x64.dll`，但
PyInstaller 汇总 Qt/Poppler 依赖时曾把另一套同名 DLL 放进包里。加载顺序导致
TLS 在真正联网前就失败，并被上层显示成笼统的 `SSLError`/`TLS 连接失败`。

因此，看到 SSL 错误时必须先核对：

1. 包内 `_ssl.pyd` 是否存在且只有一个；
2. 包内两枚 TLS DLL 是否各只有一个；
3. 两枚 DLL 的 SHA-256 是否与**打包该 EXE 的 Python** 的 `DLLs` 目录一致；
4. 最终 EXE 的 `--tls-check-report` 是否为 `verified_tls=true` 且 CA 数量大于零。

只换 CA bundle、只改 `certifi` 或只验证 `urllib`，不能证明 DLL 没有错配。

### 1.3 Cloudflare Tunnel 还有独立的冷启动超时问题

修好 DLL 后，首次请求仍可能因 Tunnel 冷启动超过 3 秒超时。HTTPS 远端发布配置
的超时不得回退到 3 秒；当前构建脚本固定写入 10 秒。超时问题和 TLS 初始化问题
必须分开记录，不能看到一次超时就继续改证书，也不能把一次源码网络成功当成两者
都已验证。

### 1.4 改完源码但没有同步桌面，用户仍在运行旧版本

“构建成功”不等于“用户快捷方式已更新”。曾经发生过源码、`ui-v2/dist`、EXE、
桌面快捷方式四者不同步。后续交付必须满足：

```text
source SHA
  = ui-v2/dist/build_manifest.source_sha
  = build_identity.source_sha
  = 桌面目录 EXE 对应的 build_identity.source_sha
快捷方式 TargetPath -> 该桌面目录的 ShuaBao.exe
快捷方式 WorkingDirectory -> 该桌面目录
```

只看到日志里的“已部署”或只看到快捷方式对象被赋值，不算同步成功；必须 Save 后
重新读取 `.lnk` 再比对。

另外，重建前如果旧的 `ShuaBao.exe` 仍在运行，Windows 会锁住目标 EXE，
`robocopy /MIR` 可能长时间重试，留下“新 identity + 旧 EXE”的半同步状态。当前
`build_release.ps1` 会在复制前列出占用 PID 并直接失败；先正常关闭旧看板，再重试，
不要在锁等待期间手工覆盖单个文件。

### 1.5 点击成功不是业务成功

订阅里的 `SendInput/click` 成功、搜索框写入成功、页面发生变化，都只是步骤证据。
业务成功必须有正式后置条件（例如真实挑战 HUD、房间等待锚点、按钮状态变化、
订阅接口返回有效 permit）。离线 replay/harness 不得把点击成功升级成真机业务 PASS。

### 1.6 密钥只走 UI/DPAPI，不进命令行和日志

卡密不允许放进脚本参数、构建日志、测试输出、manifest、截图文件名或回传文本。
桌面自检只能从正常环境/DPAPI 读取，并输出脱敏状态；诊断失败也不得回显请求体、
卡密或设备标识。

## 2. 唯一推荐执行顺序

在修改打包、桌面 UI、订阅配置或发布脚本后，按下面顺序执行：

```powershell
cd "G:\刷刷宝\GameScript-Local"
git status --short
git branch --show-current
git rev-parse HEAD
git diff --check

python tools/release_gate.py
python -m pytest tests -q --tb=short

powershell -ExecutionPolicy Bypass -File .\build_release.ps1 `
  -ReleaseChannel dev -AllowDirty `
  -SubscriptionBaseUrl "https://<approved-endpoint>" `
  -SubscriptionMode enforce `
  -ManifestSigningKeyPath "<仓外 operator manifest private key>" `
  -ManifestSigningKeyId "<operator key id>" `
  -ManifestPublicKeysPath "<仓外 operator public-key registry>"
```

`build_release.ps1` 会自动调用 `tools/release_harness.py` 两次：一次检查 `dist`，
一次检查最终桌面目录；任一失败都必须停止，不得手工复制某几个 DLL 或只替换
`ui-v2/dist`。

需要单独复核最终目录时使用：

```powershell
python tools/release_harness.py `
  --source-root "G:\刷刷宝\GameScript-Local" `
  --bundle "C:\Users\10639\Desktop\ShuaBao" `
  --python-root "<build Python sys.base_prefix>" `
  --manifest-public-keys "<仓外 operator manifest public-key registry>" `
  --require-clean
```

然后再用**最终桌面 EXE**执行不发游戏输入的诊断：

```powershell
ShuaBao.exe --tls-check-report <脱敏报告路径>
ShuaBao.exe --subscription-check-report <脱敏报告路径>
```

报告中的 `ActivationOK` 只表示订阅激活接口成功；真正的游戏链路仍须按
`tools/live_scenario_capture.py` 的自然 E2E 规则和用户真机清单单独验证。

## 3. 失败时的归因表

| 现象 | 首先检查 | 不要做的事 |
|------|----------|------------|
| 桌面 EXE `SSLError`，源码 CLI 正常 | 包内 `_ssl.pyd`、两枚 TLS DLL 的路径/哈希、最终 EXE TLS report | 继续只换 CA、反复改 VPS 卡密 |
| 桌面 EXE `TLS 连接失败` 但 TLS report PASS | HTTPS timeout 是否至少 10 秒、Tunnel 冷启动、接口响应 | 把超时误判成证书问题 |
| 用户看不到刚改的 UI/设置 | `build_identity.json`、`ui-v2/dist/build_manifest.json`、`.lnk` 目标和工作目录 | 只说“已构建/已部署” |
| click success 但业务未继续 | 正式视觉/业务后置条件和当前 phase | 把点击结果、frame change、bookmark 当 PASS |
| 测试变绿但行为没证据 | 是否只跑了源码/模拟 fixture；是否绕过 gate | 删除失败、skip/xfail、改 baseline 数字 |
| 需要卡密做诊断 | 用已保存 DPAPI 或桌面 UI 输入 | 把卡密写入命令、脚本、日志、报告 |

## 4. 给后续 Agent 的停止条件

遇到以下任一项，状态写 `BLOCKED`/`FAIL`，不要继续扩展业务功能：

- 最终桌面 EXE 的 `build_identity.source_sha` 与当前源码不一致；
- `.lnk` 目标不是当前桌面目录的 `ShuaBao.exe`；
- `release_harness.py` 任一检查失败；
- 包内 TLS DLL 缺失、重复或哈希与打包 Python 不一致；
- 只有源码网络测试成功，没有最终冻结 EXE 的 TLS/激活报告；
- 只有离线 replay 或日志，没有真实业务后置证据；
- 发现用户未跟踪 captures/docs，尚未记录就准备清理或加入 commit。

这份 harness 只证明发布工件和订阅启动边界一致；它不授予真实 KK 输入权限，
也不把离线结果升级为 `RELEASE READY`。
