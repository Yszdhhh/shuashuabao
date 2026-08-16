# 板块 1 工单 · 测试脚本读控制室保存项

> 把下面整段复制给**看板 / 外壳**执行 agent。层归属：**外壳**（`src/gamescript/shell/` + `tools/lab_run.py` + 测试夹 bat）。
> 本单只做「看板保存 ↔ 实验室启动」接线。不改选关/选卡判定，不改 `choice_policy`，不碰 `mediator` 面板定类。

```text
你是板块 1（看板/外壳）。工作目录：G:\刷刷宝\GameScript-Local
先读 AGENTS.md 红线，再读本文，做完回写 docs/CURRENT_STATUS_AND_HANDOFF_20260812.md。

【用户原话】
「是否可以在看板控制室里面我先加入技能/关卡/英雄模式相关的设置，我在面板里保存设置，测试的脚本就是读取面板的设置，我就不用针对每一局去改针对脚本，很容易出BUG」

【为什么要做】
13 号长测为了换关卡/卡组，另写了 测试夹\lab_dasheng_probe.json，bat 再传 --stage 1-12。
tools/lab_run.py 的 apply_lab_preset 还会强制 auto_reputation=False。
每换一局实验就改一份 probe/bat，和看板勾选脱节，容易出 BUG。
用户要：控制室勾好 → 保存 → 双击测试 bat → 读同一份设置。

【现状（2026-08-14 23:30 已核对，不要重探）】
1. 看板保存路径已经定了：%LOCALAPPDATA%\ShuaBao\user_settings.json
   - 写入：main_window._write_user_bundle → collect_persistable_settings
   - lab_focus 在 PERSIST_DENYLIST，不会写进用户默认（对，保持）
   - 这台机器此刻还没有这份文件（用户还没在本机看板里保存过）。缺文件必须 fail-closed 提示，禁止默默落到 default_settings.json 假装读了看板。
2. collect_settings_from_ui 已经收集：stage_targets、skills、cards、auto_reputation、reputation_type/level、cycle_num。
   「1-10」→ stage1/stage2 的既有 quirk 不要顺手改。
3. 13 号实际跑的是 InfraB：G:\刷刷宝\Worktrees\GameScript-InfraB
   Local 的 SlotCandidate 没有 set_name，硬白名单对套装件会狂刷。lab_run 接线要 Local + InfraB 各改一份，行为一致。
4. 13 号那一局用的卡组（对照用，不是本单要写死进代码的）：
   - 技能：奥术箭流 asj / asjg / assx / jq
   - 羁绊白名单：刀刀链（刀刀/幽灵系带/护腕/空灵挂坠/刀刀萌新/刀刀大成）+ 齐天大圣 + 封神散件（封神/姜子牙/吕岳）+ 木头（祝福/成长/经济/挑战）
   - 关卡 1-12，英雄模式关
   - 游戏左上角禁用卡组（海盗/亡灵/三国）是游戏里禁的，不是脚本白名单
   - EX 名只作「点到就退本局」，不进猎取白名单

【契约：谁说了算】

看板说了算（user_settings.json）：
  技能 skills、羁绊 cards、关卡 stage_targets、英雄模式 auto_reputation、
  声望类型/等级、局数 cycle_num（仅当 bat 没传 --games 时）

bat / CLI 说了算（实验怎么跑，不是玩什么）：
  --preset / --focus   开哪些面板环（catalogs = G+F+V+回房）
  --hours / --games    这次实验时长和局数
  --route / --build / --skill-family / --stage   仅当显式传入才覆盖看板
  实验室专用：lab_exit_on_bond（catalogs 点到已知 EX 就退）。看板没有这个控件，
  空着时由 lab_run 给 catalogs 默认 EX 列表，不要为此改看板 UI。

禁止：
  apply_lab_preset 再强制 auto_reputation=False
  没传 --stage 却用 bat 写死 1-12
  没传 --config 却要求旁边再放一份 probe.json
  看板 LIVE 与 lab CLI 同时开（live.lock 已有，保住）

【你要改的文件】
外壳一层，可以同一个 commit（不要和 mediator / 选关定类混提）：

1. tools/lab_run.py（Local 与 InfraB 各一份，逻辑相同）
   - resolve_lab_config(explicit)：
       有 --config 且文件存在 → 用它（旧 probe 仍能跑）
       否则若 %LOCALAPPDATA%\ShuaBao\user_settings.json 存在 → 用看板
       否则打印中文错误并退出码 2：先打开刷刷宝控制室，勾好技能/关卡/英雄模式，等自动保存（或点保存），再跑测试。
   - apply_lab_preset：删掉「实验室一律非英雄」。只在 CLI 显式给了 --stage / --route / --build / --skill-family 时覆盖对应字段。
   - catalogs 且 lab_exit_on_bond 为空：填默认 EX 名列表（解放的圣剑,圣人,祖龙,世界末日迦拉克隆,世界末日,吞食天地,帝炎,陀舍古帝,帝炎陀舍古帝,萨格拉斯,兵主,大乘期,法天象地），count=1。Local 若 Settings 没有该字段就跳过。
   - 启动必须打印：config 路径（看板 / 显式文件）、关卡、英雄模式开/关、skills、cards。用户对照看板一眼能看出读没读对。

2. 测试夹\13-长测-大圣刀刀封神-技能黑商进化.bat
   - 去掉 --config "%PROBE%" 和 --stage 1-12，以及 PROBE 文件必须存在的检查。
   - 改为：--preset catalogs --hours 2 --games 4
   - 开跑前检查 user_settings.json，没有就 echo 中文说明并 pause/exit 2。
   - echo 写成「关卡/技能/英雄模式/羁绊 = 看板 user_settings.json」，不要再写死 1-12 非英雄。
   - 仍跑 InfraB（REPO=GameScript-InfraB）。live.lock 检查保留。

3. 测试（Local 即可，InfraB 能对称加最好）
   - 有看板文件：resolve 指向它
   - 无看板且无 --config：退出/抛错，不静默 default_settings
   - apply_lab_preset 不把 auto_reputation True 改成 False
   - 不传 --stage 时保留 settings.stage_targets
   - 传 --stage 1-8 时才覆盖

4. 看板侧只需确认，不必大改 UI：
   - 保存后文件确实落在 %LOCALAPPDATA%\ShuaBao\user_settings.json
   - 技能/关卡/英雄模式（运行板块里叫「关卡难度」，不要改名成「模式」）写入上述字段
   - 控制室给一句可见提示：「测试夹 bat 会读这份保存。改完等自动保存（约 1 秒）再双击 bat。不要同时开 LIVE。」
   - 本机现在没有该文件：用户第一次打开看板改完必须能自动写出。若自动保存没触发，补一个明确的「保存设置」按钮（现在只有 debounce timer）。

【不要做】
- 不要把 EX 最终形态写进羁绊白名单。
- 不要为了接线改 mediator / 选关 / 抽卡策略。
- 不要改任何 live_enabled。
- 不要让看板 LIVE 和 lab 抢同一把锁之外再发明第二套互斥。
- 不要把 13 号的刀刀/大圣名单写死进 lab_run 默认 cards——那必须来自看板勾选。

【验收】
- 看板勾 1-12 + 奥术箭流 + 非英雄 + 若干羁绊 → 保存 → 不传 --stage/--config 跑 lab_run --preset catalogs --games 1 --dry-run（或只打印不点），stdout 里 skills/cards/stage/英雄模式与文件一致。
- 删掉/改名 user_settings.json 再跑，必须失败并说明去看板保存，不能偷偷用出厂默认。
- pytest 新增用例绿；python tools/release_gate.py 退出码 0。
- 回写交接文档：改了什么、13 号以后怎么开（先看板保存，再双击 bat）。
```
