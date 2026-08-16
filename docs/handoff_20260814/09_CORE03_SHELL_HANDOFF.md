# CORE-03 Shell 交接（2026-08-16）

## 看板入口

- 首屏是「单人刷图」与「蹭车 / 跟车」两种主入口；后者仅在二级选择「大厅找房蹭车」或「已在房间跟车」。
- 赌木、站团本和实验室放进「更多模式」。所有 `live_enabled=false` 模式仍由 `RunnerService` 拒绝，按钮显示「待验证 · 不可启动」，不会创建 Runner/Mediator。

## 单人与测试配置

- 单人页面持久化自动创房、房名、密码（掩码输入）、每局新建/复用、关卡、局数、英雄阵营/难度、秘境与学习模式。
- `config/dashboard_test_profiles.json` 提供 V0 单局、V1 两局和秘境一局。导入仅允许 `normal_farm` 的看板白名单字段；未知版本、未知字段和路径/命令/密码字段一律拒绝。
- 测试配置不含也不改 `dry_run`，导出不含 `room_password`。应用前显示差异确认，应用后仅更新表单，绝不启动运行。

## 运行边界

- 本轮不创建桌面快捷方式、不运行真机。看板入口仍为仓库根目录 `desktop_app.py`。
- 用户设置继续写入 `%LOCALAPPDATA%\ShuaBao\user_settings.json`，使用同目录 `.tmp` 后 replace 的原子写入。
