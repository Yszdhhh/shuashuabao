# 给云端 AI 的审查入口

这份文件把“脚本一直运行但不开始/不能选关”的现场证据、当前状态机契约和参考项目入口集中起来。它不包含官方 `LicenseTxt`、密码或完整机器配置。

## 2026-08-06 现场结论

在本机复现时同时发现了三个会让现象看起来像“脚本卡住”的问题：

1. `config/default_settings.json` 原来是 `auto_create_room=false`、`dry_run=true`。前者只等待手动房间，后者只找图不点击；脚本有输出不代表发生了真实点击。Solo 本地默认现已改为自动建房，但仍保留 `dry_run=true` 的安全默认值。
2. 旧的 MSS 桌面截屏会把浏览器覆盖在 KK 窗口上的画面当成 KK 内容，进而误判选关页或找不到开始按钮。现在对被遮挡的非前台窗口优先使用 Pillow/Win32 `PrintWindow` 捕获；不支持该路径的 GPU 窗口仍会安全地无匹配，不会把前台浏览器当成游戏。
3. 本地控制面板自己的标题包含“英雄三国”，旧窗口筛选会把控制面板当成 L1 游戏窗口。现在 L1 排除 `挂机助手`、`GameScript-Local`、`本地版` 标题，只接受真实游戏窗口。

此外，KK 地图页的“创建房间”按钮以前没有项目模板，底部宣传图又会和蓝色按钮连成一个轮廓，颜色兜底容易漏检。当前加入了：

- `assets/Images/lobby/create_room.png`
- `assets/Images/lobby/create_room_confirm.png`

并把颜色兜底限制在底部操作带内。当前实机回放可以稳定识别 `PLATFORM_MAP` 与 `create_room`，已有房间的 `kk_start` 和游戏选关页也有离线回放覆盖。

## 状态机应该满足的链路

```text
BOOT
  ├─ 已在局内（卡牌/技能面板） → MAIN_LINE
  ├─ 已在房间（kk_start）       → ROOM_WAITING → ROOM_STARTING
  ├─ 已在建房弹窗              → CREATE_ROOM
  └─ 否                       → PLATFORM_MAP → CREATE_ROOM → ROOM_WAITING

ROOM_STARTING → STAGE_SELECT → 识别配置的编号关卡 → 点击棕色开始 → MAIN_LINE
```

每个真实动作前都必须先确认场景、目标模板和 HWND；无法确认时保持当前阶段或进入 `ERROR`，不能用全屏蓝色按钮猜测。

## 现场诊断命令

在游戏与 KK 平台打开后，先用只读诊断，不会移动鼠标：

```powershell
python tools\diagnose_lobby.py --config config\default_settings.json
```

需要把截图交给云端 AI 时才增加 `--save-dir`；截图可能包含游戏画面和桌面信息，请先检查并脱敏：

```powershell
python tools\diagnose_lobby.py --save-dir "$env:TEMP\gamescript-lobby-diagnose"
```

重点看：

- `role=l0 context=PLATFORM_MAP` 且 `map_create=True`
- `role=l0 context=ROOM_WAITING` 且 `room_start=True`
- `role=l1 context=STAGE_SELECT` 且 `stage_page=True stage_start=True`
- 是否出现真实 `英雄三国KK`，而不是本地控制面板标题

第一次真机验证建议在 UI 中勾选“大厅自动建房 (L0)”、取消 Dry-run，并把“测试步数”设为 10—20；确认日志出现 `CreateRoom-open`、`CreateRoom-confirm`、`RoomStart`、`SelectStage` 后再长跑。

## 参考项目

完整的来源、许可证、锁定 commit 和本项目对应的审查点见 [`references/README.md`](../references/README.md)。这些参考代码只用于审查和对比，不会被运行时自动导入，也没有修改 `requirements.txt`。
