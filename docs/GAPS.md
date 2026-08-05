# 缺口清单

## 已从现包拆出（无需新材料）

- 方法链闭包：`EntryF1` / `SelectStage` / `CloseCardPanel` / `CloseSkillPanel` /
  `ChangeMainLineStatus` / `ClickOKBtn` / `CreateRoom` / `QuitGame` /
  `FindAllMatchImages` / `FindCardImages` / `FindNodeWithTimeOut` / `MonitorGameOver` 等  
  → 见 `docs/SCENES.md`、`docs/closure_hints.txt`
- 场景优先级 + 模板分组 → `config/scenes.json`（已校验模板文件存在）
- 战斗内未归类根图列表 → `scenes.json` 的 `combat_templates_root_unclassified`

## 授权后已补上

- 完整 Settings 实参路径：`%AppData%\GameScript\Settings\Settings.json`
- 运行日志 + CaptureWin 落盘规则
- Boss 名 = 模板文件名；`GameMode=3`（你当前取值，枚举表仍未完整）
- `QueryTimeOut=120` 与「等待进入 UI」超时同量级

## 仍缺

1. **窗口标题** → `window_title_contains`（样例截屏是 1920×1080 全屏）
2. **GameMode 0/1/2/3 完整对照**（你当前是 3）
3. **mainIdentifier 是否与当前客户端一致**（本次失败点）
4. **阈值 / Stage1Rec ROI / ZS 重开**
5. **奥数四卡** → cards 文件名
6. 证书 Hub URL（本地不做）

## 实现状态

| 模块 | 状态 |
|------|------|
| scenes.json 驱动 AutoJob | 已接 |
| 找图 / 截屏 / dry-run | 已有 |
| CreateRoom 真建房 | 已接入场景化状态链；无真实弹窗模板时仅使用严格 ROI，输入框不安全则停住 |
| Shift+F12 全局热键 | 未接 |
| 防息屏 / NTP / 证书 | 不做或后补 |
