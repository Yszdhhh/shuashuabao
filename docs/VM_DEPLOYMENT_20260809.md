# GameScript-Local VM 部署文档（持久 Windows 虚拟机）

> **生成日期**：2026-08-09
> **适用范围**：KK 对战平台《重生魔兽刷刷刷》纯视觉 + SendInput 自动化挂机系统
> **素材来源**：deep-research-report「后台运行、分辨率与隔离方案」章节、`docs/AI_REVIEW_CONTEXT.md`、`docs/ARCHITECTURE_20260808.md`
> **状态说明**：本文档中的「待验证」项表示素材未给出确定答案，需实机验证后回填。

---

## 1. 为什么需要 VM

### 1.1 问题：真实输入不是后台输入

项目当前已具备一部分"后台抓图"能力：`capture_target()` 发现目标不是 foreground 时会先尝试 `ImageGrab.grab(window=HWND)`，成功即可不依赖被其他窗口覆盖后的桌面像素；失败才走 MSS。

但**真实输入仍然不是后台输入**。`InputExecutor.check_can_execute()` 若发现当前前台不是目标 HWND，会主动 `activate_window(target_hwnd)`；因此每次进行真实点击/按键时，脚本仍会**抢宿主 Windows 的前台焦点**——这是 SendInput 的本质特性：它是 **guest/host 桌面级输入**，不是窗口级后台消息。

### 1.2 结论：虚拟机/沙盒隔离是当前技术路线下最合理的方案

不是为了逃避反自动化，而是因为 SendInput 本质上就是桌面级输入。把游戏与脚本**一起放在 guest 里**，可以让：

- 前台切换
- 鼠标移动
- 按键注入

全部**局限在 guest 内部**，host 继续办公，互不打扰。host 不运行任何游戏输入逻辑。

### 1.3 推荐方案：持久 Windows VM（而非 Windows Sandbox）

| 方案 | 是否推荐长期挂机 | 原因 |
|---|---|---|
| **持久 Windows VM（Hyper-V）** | ✅ 推荐 | 可长期保留 KK 安装、资源、调试截图与模板；状态可持久化 |
| Windows Sandbox | ❌ 不推荐 | 默认是一次性环境，**关闭后状态被销毁**；更适合短期依赖验证、打包、安全实验 |

微软说明 Sandbox 默认一次性销毁；虽然支持 vGPU、网络、剪贴板、映射目录等配置，但对于需要长期保留 KK 安装、资源、调试截图和模板的挂机项目，不如持久 VM 方便。

---

## 2. 前置条件

### 2.1 宿主系统要求

- **操作系统**：Windows 10 / 11 **Pro**（Hyper-V 为 Pro/Enterprise/Education 及以上版本功能，家庭版不包含 Hyper-V 组件）
- **CPU**：支持并已开启虚拟化（Intel VT-x / AMD-V）；建议 ≥ 8 逻辑核，与脚本同机运行更佳
- **内存**：建议 16 GB 起步（guest 分配见 §3.3，需为 host 日常办公留足余量）
- **磁盘**：建议 256 GB 以上可用空间（guest 虚拟磁盘 + host 自身占用）

### 2.2 开启 Hyper-V（管理员 PowerShell）

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All
```

执行后**需重启**宿主。重启后可在「开始菜单 → Windows 管理工具 → Hyper-V 管理器」中确认功能已启用。

> 若宿主为 Windows 10 Home（或 Hyper-V 不可用的环境），见 §7「已知风险与回退」——退回 VMware Workstation 等其他虚拟化方案（待验证）。

---

## 3. 创建持久 VM 步骤

### 3.1 方式一：Hyper-V 管理器（图形界面）

1. 打开 **Hyper-V 管理器**，右键宿主节点 → **新建 → 虚拟机**。
2. **代数（Generation）**：选择 **Generation 2**（UEFI 引导，支持更大磁盘与更新虚拟硬件）。
3. **内存**：见 §3.3 建议值。
4. **网络**：连接 Hyper-V 默认交换机（Default Switch，提供 NAT 上网）；如需固定 IP 或与宿主网络直连，再按需配置（待验证）。
5. **虚拟硬盘**：新建虚拟磁盘，大小见 §3.3 建议值。
6. 完成向导后，在 VM 设置中挂载 Windows 10/11 Pro 安装镜像（.iso），启动并从镜像安装 guest 系统。

### 3.2 方式二：PowerShell（New-VM）

以下为参考命令骨架，**具体参数以微软官方文档为准（待验证）**：

```powershell
New-VM -Name "GameScript-VM" `
       -MemoryStartupBytes 8GB `
       -BootDevice VHD `
       -VHDPath "D:\Hyper-V\GameScript-VM\GameScript-VM.vhdx" `
       -Generation 2
```

创建后需进一步设置 vCPU、挂载安装镜像、启动安装 guest 系统（详细参数待验证）。

### 3.3 资源建议（参考值，可按需调整）

| 资源 | 建议值 | 说明 |
|---|---|---|
| vCPU | 4 | 游戏 + CEF 渲染 + 脚本识别共用，建议 ≥ 4（待验证） |
| 内存 | 8 GB 起 | KK 平台（Qt + CEF）+ 魔兽争霸 3 地图 + 脚本，建议 8 GB 起（待验证） |
| 虚拟磁盘 | 128 GB 起（动态扩展） | 需容纳 Windows 系统、KK 平台、游戏资源、调试截图与模板（待验证） |
| 网络 | 默认交换机（Default Switch） | 提供 NAT 上网即可；具体网络需求待验证 |

> 以上数值为部署建议，非素材结论；实机挂机后按 guest 内实际占用回填调整。

---

## 4. guest 系统配置清单

guest 系统（Windows 10/11 Pro）安装完成后，按以下清单逐项配置：

### 4.1 显示与分辨率

- [ ] 分辨率固定为 **1600×900**
- [ ] DPI 缩放固定为 **100%**，关闭自动缩放 / 缩放建议
- [ ] 关闭显示器休眠/关闭显示器策略（挂机期间画面需持续可捕获）
- [ ] 坐标基准为 1600×900 窗口（含标题栏偏移 ~30px），与项目现有基准保持一致

### 4.2 权限与 UAC（关键）

- [ ] **KK 与 GameScript 在 guest 内保持相同管理员级别**（与 host 环境一致，双方均以管理员运行）
- [ ] 保持 guest 内 UAC 提权机制有效（GameScript 打包 `uac_admin=True`，非提权进程的 SendInput 会被 UIPI 静默丢弃）
- [ ] 切勿将 GameScript 或 KK 降权运行（会导致输入完全失效）

### 4.3 软件安装

- [ ] 安装 **KK 对战平台**（Qt 5.15 + CEF 内嵌渲染）
- [ ] 安装 **魔兽争霸 3** 与《重生魔兽刷刷刷》自定义地图
- [ ] 部署 **GameScript-Local**（源码或打包 EXE，管理员权限）
- [ ] （可选）安装 Python 环境用于 `main.py` CLI / dry-run / 校验工具

### 4.4 其他

- [ ] guest 内关闭不必要的后台更新/通知，避免干扰画面识别（待验证）
- [ ] 为 guest 创建还原点或定期快照（Hyper-V 检查点），便于挂机环境出问题后回滚

---

## 5. 输入链说明

### 5.1 guest 内保持现有安全 SendInput 链

脚本**继续使用当前安全 SendInput 链，不做任何改动**。guest 内 `InputExecutor` 的安全门禁全部保留：

| 门禁 | 作用 |
|---|---|
| 提权门禁（UIPI Elevate） | 非管理员进程拒绝注入（UIPI 会静默丢弃低权限 SendInput） |
| HWND 校验 | 目标窗口存在且未最小化 |
| 前台校验 | 目标 HWND 是否在最前台，否则 `activate_window()` |
| WindowFromPoint 遮挡拒绝 | 目标坐标点被其他窗口覆盖时取消点击 |

这些校验在 guest 内**继续生效且同样有价值**（guest 桌面内仍有其他窗口可能遮挡游戏窗口）。

### 5.2 输入边界收窄到 guest

- SendInput 是桌面级输入：**在 guest 内执行时，前台切换、鼠标移动、按键都局限在 guest 桌面**
- **host 不运行任何游戏输入逻辑**，宿主前台焦点不再被脚本抢占，可继续办公

### 5.3 明确不做的事：改后台窗口消息

**不建议为了"后台点击"把核心改成 `PostMessage/SendMessage`**：

- KK/CEF/游戏是否接受这类后台窗口消息是 **UNKNOWN**
- 会**破坏**现在已很有价值的 HWND / foreground / WindowFromPoint 安全模型

结论：保持 SendInput + 现有安全链，用 VM 隔离解决抢焦点问题，而不是换输入机制。

---

## 6. 验证清单

按以下顺序逐项验证，每项给出**通过/失败**判定标准。全部通过方可进入长期挂机。

### 6.1 步骤 1：Basic Session / VM console 截图基准

- **操作**：以 **VM console / Basic Session** 启动 guest，运行 KK + 游戏 + GameScript，捕获关键场景截图（建房页、选关页、主线战斗页等），保存为**截图基准**。
- **通过**：guest 内画面正常渲染，脚本 `dry-run` / 抓图识别正常，坐标命中（1600×900 基准）。
- **失败**：画面异常 / 识别错位 → 先排查 guest 显示栈与分辨率/DPI 配置（回到 §4），修复后重测。

### 6.2 步骤 2：Enhanced Session 对比

Hyper-V **Enhanced Session 使用 RDP 技术**，支持可调整分辨率和设备共享。对普通应用是优势，但**游戏视觉自动化依赖具体显示栈**，必须验证：

- **操作**：开启 Enhanced Session，在**同一场景**下重新截图，与步骤 1 的 Basic 基准逐项对比（KK / CEF / 魔兽画面）。
- **通过（一致）**：Enhanced Session 未改变画面 → 可选用 Enhanced Session 挂机（便于分辨率/设备管理）。
- **失败（不一致）**：截图表现不同 → **挂机坚持 Basic / console 会话**，不使用 Enhanced Session。

### 6.3 步骤 3：SendInput 实测

- **操作**：guest 内以管理员运行 GameScript，触发一次真实点击（如 KK「创建房间」），观察是否生效；同时观察**宿主前台焦点是否被抢占**。
- **通过**：guest 内输入生效（弹窗出现等预期结果），且 host 焦点不被抢，host 可继续办公。
- **失败**：
  - guest 内无响应 → 检查 UIPI 提权（GameScript/KK 是否同为管理员），回到 §4.2。
  - host 仍被抢焦点 → 检查输入是否真的发生在 guest 会话内（Basic/Enhanced 会话模式），重新验证 §6.2。

### 6.4 步骤 4：识别验证（validate_scenes + 场景测试）

- **操作**：在 guest 环境内运行场景校验与回放测试：

```powershell
$env:PYTHONPATH="src"
python tools/validate_scenes.py        # 场景模板静态校验
python -m unittest tests/test_p0b_replay.py   # 实机截图全回放
```

- **通过**：`validate_scenes` 无 missing（近期基线 `ok=99 missing=0 root_unreferenced=0`，具体数以当前代码为准）；回放测试通过；dry-run 实测关键场景识别正常。
- **失败**：存在 missing 模板或回放失败 → 说明 guest 画面与模板基线不一致（可能由虚拟 GPU 渲染差异引起），回到 §6.2 / §7 排查。

### 6.5 汇总判定

| 步骤 | 判定 | 结论 |
|---|---|---|
| 1. Basic 截图基准 | 通过 / 失败 | 失败 → 修 guest 显示配置 |
| 2. Enhanced Session 对比 | 一致 / 不一致 | 不一致 → 挂机用 Basic/console |
| 3. SendInput 实测 | 通过 / 失败 | 失败 → 查 UIPI 提权 |
| 4. validate_scenes + 回放 | 通过 / 失败 | 失败 → 排查虚拟 GPU 渲染差异 |

全部通过 → 进入长期挂机；任一步失败 → 按对应结论处理（含 §7 回退方案）。

---

## 7. 已知风险与回退

### 7.1 核心未知项：虚拟 GPU 兼容性（UNKNOWN）

> **KK/魔兽在具体虚拟 GPU 下能否稳定运行：UNKNOWN。**
> 这一点**必须实机测试**后才能决定 Hyper-V、VMware 等哪一个最合适。

这是本方案最大的不确定性：CEF 渲染（KK 平台）与魔兽争霸 3 的画面在具体虚拟 GPU（Hyper-V 默认 vGPU / Enhanced Session RDP 显示栈等）下可能表现不一致，直接影响视觉识别。

### 7.2 风险清单

| 风险 | 等级 | 处置 |
|---|---|---|
| 虚拟 GPU 下 KK/CEF/魔兽画面异常 | 高（UNKNOWN） | 实机测试后决定 Hyper-V / VMware 等方案（§7.3） |
| Enhanced Session 改变画面 | 中 | 挂机坚持 Basic/console（§6.2） |
| 后台窗口消息兼容性 | 未知 | **不采用** PostMessage/SendMessage 方案（§5.3） |
| guest 内识别与模板基线不一致 | 中 | 用 §6.4 校验暴露，回 §7.3 |

### 7.3 回退路径

1. **优先**：确认 Hyper-V 下 KK/魔兽可稳定运行（§6 全部通过）→ 采用 Hyper-V 持久 VM。
2. **回退 A**：Hyper-V 下游戏画面/性能不达标 → **退回 VMware Workstation**（或其他虚拟化方案）重新走 §3–§6（待验证）。
3. **回退 B**：所有 VM 方案均不满足 → 维持真机运行（接受宿主抢焦点行为），或等待后续输入方案研究（不推荐改后台消息）。
4. **排除项**：**Windows Sandbox 不适用**于长期挂机（一次性环境，关闭即销毁；仅适合短期依赖/打包/安全实验）。

---

## 8. 分辨率策略

### 8.1 guest 固定 1600×900 为稳定基线

- guest 固定 **1600×900、100% DPI**，与项目坐标基准（1600×900 窗口，含标题栏偏移 ~30px）一致。
- **不**建议继续靠"所有 detector 各自多尺度"硬兜底——项目文档已明确：**1600×900 是基准，其他分辨率并未全面验证**。

### 8.2 其余分辨率：先校准、后开放

如需支持其他分辨率，采用**会话级 UI 校准**（轻量方案）而非扩大 scale 列表：

1. 启动时读取真实客户区 `W×H` 与 DPI；
2. 检查宽高比；
3. 识别 1~2 个稳定的 L0/L1 anchor；
4. 由 anchor 与客户区尺寸求统一 `ui_scale`；
5. 所有固定坐标转为 client-normalized 比例；
6. 模板只围绕该 scale 搜索一个很小范围。

**校准不成立时直接 Fail-Closed**（零输入停机），并保存诊断帧，而不是继续用越来越宽的 scale 列表猜。

### 8.3 实施顺序建议

1. 先以 guest 固定 1600×900 跑通全链路（§6 全通过）；
2. 再实现 §8.2 会话级校准，作为后续分辨率开放的唯一入口；
3. 每开放一个新分辨率，按 §6.4 重新做识别验证。

---

## 附：素材依据对照

| 本文档结论 | 素材出处 |
|---|---|
| SendInput 是桌面级输入、会抢宿主前台焦点 | deep-research-report「后台运行、分辨率与隔离方案」 |
| 持久 Windows VM 优于 Windows Sandbox（Sandbox 一次性销毁） | 同上 |
| guest 固定 1600×900 + 100% DPI | 同上 |
| KK 与 GameScript 保持相同管理员级别 | 同上 |
| Enhanced Session（RDP）需 Basic 基准对比 | 同上 |
| KK/魔兽虚拟 GPU 兼容性 UNKNOWN | 同上 |
| 不建议 PostMessage/SendMessage | 同上 |
| InputExecutor 安全链（提权/HWND/前台/遮挡） | `docs/AI_REVIEW_CONTEXT.md`、`docs/ARCHITECTURE_20260808.md` |
| 1600×900 坐标基准、其他分辨率未全面验证 | `docs/AI_REVIEW_CONTEXT.md` |
| validate_scenes / 回放测试 | `docs/PROJECT_HANDOFF_NEXT_AGENT.md` 等（近期基线 `ok=99 missing=0`） |
