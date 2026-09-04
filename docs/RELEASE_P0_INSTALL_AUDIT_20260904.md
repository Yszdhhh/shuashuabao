# Release P0 安装模型审计（2026-09-04）

基线：`origin/trial-merge` `bea21e509c5b175042e092af6199ac49c3b0d7f4`  
分支：`release/versioned-install-p0-20260904`  
范围：发行安装拓扑。不改订阅/permit/channel/manifest 信任边界，不改 mediator / FSM / OCR。

---

## 1. 当前 install / deploy topology

构建产物与桌面落地由 `build_release.ps1` 串起来，`sync_to_desktop.ps1` 只是它的薄封装。

```
源码 worktree
  → dist\ShuaBao\                 # PyInstaller onedir（主程序 + OCR worker + sidecars）
  → robocopy /MIR
  → %USERPROFILE%\Desktop\ShuaBao\   # 可变安装目录，每次覆盖
  → 刷刷宝.lnk → Desktop\ShuaBao\ShuaBao.exe
```

关键事实：

| 步骤 | 位置 | 行为 |
| --- | --- | --- |
| 冻结打包 | `dist\ShuaBao\` | onedir：`ShuaBao.exe`、`vision\ShuaBaoOCR.exe`、`build_identity.json`、`release_manifest.json` + `.sig`、`subscription_runtime.json` |
| 部署 | `Desktop\ShuaBao` | `robocopy /MIR` **覆盖**同一目录 |
| 快捷方式 | `Desktop\刷刷宝.lnk` | `TargetPath = Desktop\ShuaBao\ShuaBao.exe`，Save 后重读验证 |
| 用户数据 | `%LOCALAPPDATA%\ShuaBao\` | 已与桌面目录分离（`src/shuabao/paths.py`） |
| 旧版处理 | `Desktop\刷刷宝-旧版归档\` | 归档 `ShuaBao-*` / `GameScript-*` 目录和旧 `.lnk`；**不能**按已验证版本回滚 |

历史故障模式（已发生多次）：源码 / `ui-v2/dist` 已更新，桌面用户仍运行旧 frozen package。根因不是缺少 SHA sidecar，而是 **mutable install dir + 快捷方式直指该目录的 EXE**。`/MIR` 遇到锁定 EXE 还会长时间重试，留下“新 identity + 旧 EXE”的半同步状态。

`NoDeploy` 只构建 `dist\ShuaBao`，不改桌面。本轮最小实现应把“部署”从桌面覆盖改成 `%LOCALAPPDATA%\ShuaBao\app-<id>\` 版本目录 + 稳定 launcher。

---

## 2. Immutable app files（冻结包内、不得被用户设置覆盖）

以 `dist\ShuaBao\`（部署后即 `Desktop\ShuaBao\`）为包根：

| 路径 | 角色 |
| --- | --- |
| `ShuaBao.exe` | 主程序；Authenticode（外发渠道）；hash 写入 `build_identity.exe_sha256` |
| `vision\ShuaBaoOCR.exe` + `vision\_internal\` | OCR sidecar 进程与模型 |
| `_internal\` | PyInstaller runtime / Qt / TLS DLL |
| `web\dist\`（在 `_internal` 下） | 已构建 Web 壳；`build_manifest.json` 绑定 `source_sha` |
| `config\*.json`（spec 白名单） | 打包进包的只读配置，含 `entitlement_public_keys.json` |
| `assets\` | 运行时素材（manifest 白名单） |
| `release_manifest.json` | 签名对象：`source_sha`、`release_channel`、文件 hash 列表 |
| `release_manifest.json.sig` | Ed25519 envelope；**不**进入 manifest `files` |
| `build_identity.json` | 旁路身份：source SHA、channel、exe/manifest/OCR hash；**不**进入 manifest `files` |
| `subscription_runtime.json` | 非秘密部署配置：`base_url` / `mode=enforce` / `release_channel` / `timeout_s`；在 manifest 内 |

`METADATA_FILE_EXCEPTIONS` = `{release_manifest.json, release_manifest.json.sig, build_identity.json}`。其余 regular file 必须在清单中且 hash 一致。

这些文件今天被 `/MIR` 当成可变目录反复覆盖。P0 要把它们放进 **只写一次的 `app-<id>\`**，禁止覆盖另一个版本目录里的文件。

---

## 3. User mutable data（必须与 app version directory 分离）

Canonical provider：`src/shuabao/paths.py`  
根：`$SHUABAO_APP_DATA` 或 `%LOCALAPPDATA%\ShuaBao`

| 路径 | 用途 |
| --- | --- |
| `user_settings.json` | 用户设置（原子 tmp+replace） |
| `habit_preference.json` | 习惯偏好 |
| `profiles\` | 玩家档案 |
| `learning\` | 学习数据 |
| `incidents\` | 异常归档 |
| `logs\ShuaBao.log` | 控制中心滚动日志 |
| `live.log` | LIVE 日志 |
| `ShuaBao.lock` / `ShuaBao.live.lock` | 单实例 / LIVE 锁 |
| 许可相关 DPAPI 文件 | 卡密；不进包 |

本轮 **不** 把 `user_settings.json` 搬进 `config\`，**不** 重构 logging。目标拓扑里的 `config\` / `logs\` / `incidents\` 含义：

- `logs\` / `incidents\`：已经在 canonical app data 下，保持不动。
- `config\`：包内只读配置继续留在 `app-<id>\`（frozen）；用户可写配置继续是根上的 `user_settings.json`。不新造第二套 settings。

安装根与 app data 默认都是 `%LOCALAPPDATA%\ShuaBao`，版本目录是该根下的 `app-*` 兄弟，而不是嵌进用户设置文件里。

---

## 4. Launcher：现有入口不可直接复用

| 现有入口 | 为什么不够 |
| --- | --- |
| `刷刷宝.lnk` → `Desktop\ShuaBao\ShuaBao.exe` | 直指可变目录，正是本任务要拆掉的 |
| `tools/launch_packaged_web_shell.vbs` | 必须和 `ShuaBao.exe` 同目录；还改 `SHUABAO_APP_DATA` 到 `ShuaBaoWeb` |
| `tools/launch_web_shell.vbs` / `DEPRECATED_launch_dashboard.vbs` | 源码开发入口 |
| `live_scenario_launcher.ps1` | 实机采集；会在 Desktop / dist 里找 EXE |
| `desktop_app.py` | 应用本体，不是稳定启动器 |

结论：没有“读 current pointer → 校验 identity → 启动目标 EXE”的稳定入口。需要新增 **thin launcher**（无订阅、无 FSM、无更新器、无远程控制）。

建议契约：

- 桌面唯一快捷方式 `刷刷宝.lnk` → `%LOCALAPPDATA%\ShuaBao\launcher\ShuaBaoLauncher.vbs`
- launcher 只读 `current.json`，校验目标目录基本 identity，启动该目录 `ShuaBao.exe`
- 失败用明确对话框，非零退出

---

## 5. 当前 rollback 能力

**没有**已验证版本的本地回滚。

今天所谓“旧版”：

1. `robocopy /MIR` 覆盖 `Desktop\ShuaBao` 之后，上一份冻结包不再作为可启动目录保留。
2. 桌面上历史 `ShuaBao-*` 目录被搬进 `刷刷宝-旧版归档`，无 `current`/`previous` 指针，无 identity 校验，快捷方式不会指向归档。
3. 回滚实际操作是重新跑 `build_release.ps1`（重新构建），或手工改 `.lnk`。

P0 需要：current N → 切回已验证 N-1 → launcher 启动 N-1，且 **不得重新构建**。

---

## 6. 修改 `build_release.ps1` 的最小方案

**不改**（必须原样保留，见第 7 节）：

- dirty / channel / SkipGate 门禁
- 订阅 URL 解析与 loopback 规则
- manifest 私钥仓外检查、`prepare_manifest_trust`、Ed25519 签名
- 外发 Authenticode + RFC3161
- `subscription_runtime.json` 字段白名单
- `release_manifest.json` 生成与签名
- `build_identity.json` 字段（可 **追加** `version`，不删不改现有键）
- dist 上的 `tools/release_harness.py`（构建后、部署前）
- shortcut Save 后重读验证

**只改部署段（`if ($NoDeploy) { return }` 之后）**：

1. 冻结包仍先写到 `dist\ShuaBao\`，并对该目录跑现有 harness。
2. 调用 `python -m shuabao.versioned_install`：
   - 把 bundle **copytree 到新目录** `%LOCALAPPDATA%\ShuaBao\app-<version>-<channel>-<source12>\`
   - 禁止 copy 进已存在且 identity 不同的目录
   - 先放到 `*.staging`，校验 identity + manifest 文件 hash，再 rename 成最终目录
   - **先不切换 current**；build 脚本对 **新目录** 再跑一次同一 harness
   - harness 通过后 `promote`：原子写 `current.json`（tmp + `os.replace`）
   - 保留 previous（N-1）；其余 `app-*` 可删，不做复杂 GC
3. 把 `tools/launcher\` 同步到 `%LOCALAPPDATA%\ShuaBao\launcher\`
4. `刷刷宝.lnk` 改为指向稳定 launcher，Save 后重读
5. 若桌面仍有旧 `Desktop\ShuaBao`，归档到 `刷刷宝-旧版归档`，避免用户继续双击旧目录

`sync_to_desktop.ps1` 只更新成功文案。不改 PyInstaller spec、不改签名、不加 auto-updater。

---

## 7. 必须原样保留的安全检查

| 检查 | 位置 | 本轮 |
| --- | --- | --- |
| 工作区 dirty 拒绝（外发禁止 `-AllowDirty`） | `build_release.ps1` | 保留 |
| `external-beta`/`release` 禁止 `-SkipGate` | 同上 | 保留 |
| frozen 全渠道 `-SubscriptionMode enforce` | 同上 | 保留 |
| 外发 HTTPS 订阅地址、loopback 整段拒绝、FQDN 尾点 | 同上 | 保留 |
| Ed25519 私钥仓外 + key id + 公钥 registry | 同上 + `prepare_manifest_trust.py` | 保留 |
| manifest 与 permit 公钥分离 | harness + prepare | 保留 |
| `sign_release_manifest.py`；失败删除清单/签名 | `build_release.ps1` | 保留 |
| 编译进 EXE 的 operator pin hook | spec + harness | 保留 |
| 外发 Authenticode Valid + RFC3161 | `Assert-AuthenticodeValid` | 保留 |
| 外发 `mode_evidence` 绑定当前 `source_sha` | `Assert-ExternalModeEvidence` | 保留 |
| canonical manifest SHA256（非原始字节）写入 identity | `Get-CanonicalManifestSha256` | 保留 |
| dist harness + 部署后 harness | `tools/release_harness.py` | 保留；部署后目标改为 `app-<id>` |
| shortcut Save 后重读 TargetPath / WorkingDirectory / 空 Arguments | 部署段 | 保留；期望值改为 launcher |
| `subscription_runtime.json` 无密钥字段、mode=enforce、channel 与 manifest 一致 | harness + `desktop_app.py` | 保留 |
| 运行时 `verify_packaged_release_snapshot` | `release_signing.py` / facade / desktop_app | 保留 |
| permit：`source_sha` / `release_manifest_sha256` / `release_channel` binding、TTL、entitlement | subscription_* | **禁止改** |

明确 **不接受** 本轮施工：把 channel 移出 signed manifest、manifest expiry、session grace、TUF、auto updater、delta patch、resource hot update、Nuitka/Cython/PyArmor、active-active VPS。

---

## 目标拓扑（R1）

```
%LOCALAPPDATA%\ShuaBao\
    launcher\                  # 稳定入口（VBS trampoline + PS1）
    app-<version>-<channel>-<source12>\
    app-<previous>\
    current.json               # atomic pointer
    user_settings.json         # 现有 canonical user data（不搬迁）
    logs\
    incidents\
    ...

Desktop\刷刷宝.lnk  →  launcher\ShuaBaoLauncher.vbs
                     →  读 current.json → 启动 app-*\ShuaBao.exe
```

`current.json`（拟）：

```json
{
  "schema_version": 1,
  "current": "app-0.3-dev-bea21e509c5b",
  "previous": "app-0.3-dev-aaaaaaaaaaaa",
  "updated_at_utc": "2026-09-04T00:00:00Z",
  "current_version": "0.3",
  "current_release_channel": "dev",
  "current_source_sha": "<40 hex>",
  "current_release_manifest_sha256": "<64 hex>"
}
```

回滚：`python -m shuabao.versioned_install rollback` 校验 previous 目录 identity 后对调 current/previous。不重建。

---

## R0 结论

无架构阻塞。canonical app data、signed manifest、harness、identity sidecar 都已存在；缺的是版本目录、稳定入口、原子 current pointer、以及不重建的 N-1 回滚。R1 只改部署/启动层。
