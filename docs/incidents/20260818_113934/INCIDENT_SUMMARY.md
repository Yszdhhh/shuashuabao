# 事故排查与现场复盘记录 (Incident 20260818_113934)

## 1. 事故概况
- **录屏文件**：`G:\测试视频+抽帧\录屏素材\20260818_113934.mp4` (721 MB)
- **运行日志**：本目录下的 `ShuaBao.log` (2.7 MB)
- **关键帧快照**：本目录下的 `frame_20s.jpg` ~ `frame_900s.jpg`

## 2. 现场故障现象与时间线
- **00:20 (frame_20s.jpg)**：成功进入 `1-20` 关卡主线（选关滚动优化已生效）；
- **00:25 (frame_25s.jpg)**：局内首次弹出三选一面板（宝物/藏宝面板，带祝福词条与橙色技能卡）；
- **00:25 ~ 15:03 (frame_30s ~ frame_900s)**：
  - 脚本每 tick 尝试处理该面板，由于 `choice_policy.py` 判定未命中白名单返回了 `REFRESH`，但游戏该面板无刷新按钮；
  - 脚本每 tick 寻找刷新按钮落空，陷入零输入等待；
  - 持续卡死 900 秒，直至 15:03 触发 `round hard deadline expired (900s)` 安全退出。

## 3. 根因与修复要求 (05 Infra)
1. **OCR 子进程找不到模块**：
   - 日志报错：`ModuleNotFoundError: No module named 'shuabao'`
   - 修复：在 `src/shuabao/vision/ocr_shadow/client.py` 中向 `env["PYTHONPATH"]` 注入绝对 `src` 路径。
2. **Treasure 宝物面板无候选死锁**：
   - 修复：在 `src/shuabao/choice_policy.py` 的 `_decide_collectible` 中，当面板为 `treasure` 且无安全候选时，若无可用刷新，必须强制返回 `PolicyAction.CLOSE`（或进入品质保底），严禁返回无效的 `REFRESH`。
