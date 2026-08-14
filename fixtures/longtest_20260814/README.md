# longtest_20260814 — 录屏拆解索引

- **视频**: `c:\Users\10639\Desktop\录屏素材\长测试.mp4`（约 50.2 min / 3011s / 1920x1080）
- **对齐**: `video_t=0` ≈ 墙钟 **12:37:17** = `trace_lab_20260814_123717_intelligence.jsonl`
  - `video_t≈1522` ≈ **13:02:40** = `trace_lab_20260814_130240_strength.jsonl`
  - 两段 trace 合计 ~2996s，与视频时长差约 15s（切模式/丢窗等待）
- **产物**
  - `长测试/frames/` — scene-diff 关键帧（36 张，早期跑）
  - `interval/frames/` — 每 12s 固定抽帧（全片）
  - `focus/` — 问题时间点定向抽帧（分析用）
  - `choice_decisions.json` / `trace_deep.json` / `trace_aligned.json` — trace 对齐产物
- **临时脚本**: `tools/_tmp_longtest_*.py`（勿当生产逻辑）

详见父 agent 最终回复中的问题时间线。
