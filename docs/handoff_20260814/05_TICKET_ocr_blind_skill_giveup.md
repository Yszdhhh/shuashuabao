# 板块 5 工单 · OCR 致盲后技能全放弃（20260814_234206）

> 把下面整段复制给 **Infra / 板块 5** 执行 agent。一层一 commit。做完回写交接文档。

```text
你是板块 5（Infra）。工作目录先用：
  G:\刷刷宝\Worktrees\GameScript-InfraB
13 号 bat 跑的是 InfraB。行为改完后把同一套修同步到
  G:\刷刷宝\GameScript-Local
先读 AGENTS.md 红线（fail-closed、一层一 commit、C2、进房禁颜色兜底、合成帧不当实机）。
本单只修两件事：OCR 起不来/熔断致盲，以及读不到技能名时禁止放弃技能点。
不要改看板、不要改选关、不要改词典/KB、不要把 EX 塞进白名单。

【用户原话】
「怎么技能现在全部点放弃？不是说了不到万不得已不会放弃吗？技能点是很难得的？
明明有预设卡的选项为什么一直点放弃？刷新就在边上初始还有四次为什么一次都不点？」
录屏：C:\Users\10639\Desktop\录屏素材\20260814_234206.mp4
trace：C:\Users\10639\AppData\Local\ShuaBao\20260814\trace_lab_20260814_234214.jsonl

【已核对事实（不要重探成「没预设」）】
1. 面板定类已经是 skill（上一刀 _panel_kind_of 修过）。不是宝物误认。
2. OCR 槽位 147 次：先 3 次 reason=spawn，之后全是 reason=disabled / status=unavailable。
   零卡名。策略看不见 asj 预设，等于没接上。
3. 动作：技能选中 0；click:skill_refresh_btn 16 次（每轮 3 次）；放弃 5 次
   （giveUp / skill_giveup_btn）。用户以为没刷新，是因为刷完卡面常没换，然后点了放弃。
4. 策略路径（choice_policy._decide_skill）：名字空 → WAIT 最多 5 帧 → REFRESH 最多 3 次
   → _giveup_or_close。DEFAULT_MAX_REFRESHES=3，DEFAULT_MAX_WAITS=5。
5. 对照：同晚 23:14 的 trace_lab_20260814_231455.jsonl OCR 是活的，会选
   箭矢齐射/奥术箭矢/剑气/爆炸箭矢。词典和预设能用，不是 KB 缺卡。

【根因】
ShadowClient 拉不起 worker（_spawn 失败记 crash），max_restarts 用尽后 _disabled=True，
整局 shadow_predict 直接返回 unavailable(reason=disabled)。
live 模式同样走 ShadowClient（mediator._ocr_roi）。
读不到名字后策略仍当「刷新耗尽、可以放弃」，把技能点点掉。这不是万不得已。

【你要修的两刀，分开 commit】

第 1 刀 · 感知层（ocr_shadow）
- 文件：src/gamescript/vision/ocr_shadow/client.py（及 worker 启动失败的日志）
- 查清 spawn 失败原因：python 路径、PYTHONPATH、模型目录 GAMESCRIPT_OCR_MODEL_DIR、
  stderr 被 DEVNULL 吃掉（先把启动失败打到 trace/日志，禁止再静默）。
- 熔断后不得整局致盲：允许后续 tick 再拉起 worker；或 live 模式下熔断只跳过本帧、下一帧重试。
- 启动时打印一次：worker 命令、model_dir、ready/reason。用户/下一场一眼能看出 OCR 死了。
- 单测：worker 起不来时不得永久 disabled；重试后能恢复。不要用合成帧冒充实机 OCR。

第 2 刀 · L1（choice_policy + mediator 选卡收口）
- 技能点珍贵。下列情况禁止 GIVEUP / 禁止点 skill_giveup_btn / giveUp：
  a) 本面板槽位全部 name=None（OCR 空/disabled/spawn）
  b) 刷新点击后三张卡指纹没变（刷新没换牌）
- 以上只允许 WAIT 或暂时隐藏（skill_hide / 关闭），耗尽则零输入等，不要把技能点点掉。
- 有可读卡名且不在预设、刷新次数还在：继续 REFRESH（这场其实点了刷新，保留）。
- 真万不得已才放弃：卡名已读出、确认不是预设系、免费刷新用尽、且用户/配置允许放弃。
  实验室 catalogs 默认：宁可隐藏也不放弃。
- 单测钉住：
  1) 三槽 name=None + has_giveup → 不得 GIVEUP
  2) 预设在、名字是爆炸箭矢/闪电链/箭矢齐射 → SELECT（对照 231455）
  3) 刷新后槽位指纹不变 → 不得再 REFRESH 死循环，也不得 GIVEUP

【不要做】
- 不要改 choice_lexicon / skill_meta / KB「补预设」——预设已经在（asj/asjg/assx/jq）。
- 不要回退 _panel_kind_of 的「按了 G 就认 skill」。
- 不要和看板 user_settings 接线混一个 commit。
- 不要用合成帧声称「实机 OCR 已通」。

【验收】
- 复现 234214 的空槽输入：策略不再输出 GIVEUP。
- 有名字的 231455 类输入：仍会选预设系，不回归成只刷新。
- InfraB 与 Local 行为一致。
- python -m pytest tests/test_choice_policy.py tests/test_live_run_205044_regressions.py -q
  以及你新增的 OCR client 测试要绿。
- 回写 docs/CURRENT_STATUS_AND_HANDOFF_20260812.md：OCR 怎么修的、技能放弃门闩改了什么、
  哪场需要板块 7 再真机验（建议再跑 13 号，盯启动日志 OCR ready + 技能选中>0 + 零放弃）。
```
