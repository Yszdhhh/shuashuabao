# Fixtures: lab13_200601_stage_card

本目录为录屏 `C:\Users\10639\Desktop\录屏素材\20260814_195647.mp4` 与对应 trace（`195653` / `195723` / `200601`）的实机抽帧拆解夹具。

## 证据文件列表

- `INDEX.json`: 全量证据帧元数据与时间戳对应表
- `01_q1_stage_select_click1_t1563.3s.jpg`: 选关第1轮t1312点击[1237,841]，高亮格子为1-10，同屏可见1-10到1-12
- `02_q2_stage_select_click2_t1567.0s.jpg`: 同轮第二次点击[1237,802]后高亮切换为1-12
- `03_q2_stagestart_loading_t1568.8s.jpg`: StageStart点击后进入场景加载19%，证实点中开始游戏
- `04_q3_round1_hud_t1572.0s.jpg`: 第1轮进局后实际关卡为1-12
- `05_q3_round2_hud_t2545.0s.jpg`: 第2轮进局后实际关卡为1-12
- `06_q3_round3_hud_t3518.0s.jpg`: 第3轮进局后实际关卡为1-12
- `07_q4_game0_hud_start_t0555.0s.jpg`: 第1局开场tick1在局内没走选关，顶部HUD显示当前正在打1-12
- `08_q6_t9_g_panel_misclassified_t0559.9s.jpg`: tick9实际弹出的是G技能三选面板，非宝物锁/V面板；trace误报treasure_lock
- `09_q5_skill_choice_t0561.1s.jpg`: 技能三选为爆炸箭矢(金)、攻速提升(绿)、闪电链(金/NEW)；拥有1点技能点；刷新未换牌；OCR认错面板
- `10_q7_bond_t1726_t1866.5s.jpg`: t1726点击底栏祝福/宝物进化，无居中三选一弹窗
- `11_q7_bond_t3665_t2803.9s.jpg`: t3665点击底栏祝福/宝物进化，无居中三选一弹窗
- `12_q7_bond_t5696_t3751.7s.jpg`: t5696点击底栏祝福/宝物进化，无居中三选一弹窗
- `13_q8_195723_cmd_window_t0053.5s.jpg`: 195723建房后hwnd=None期间画面为桌面CMD黑框窗口，游戏窗口无前台焦点
- `14_q8_200601_room_starting_explorer_t1465.0s.jpg`: ROOM_STARTING t1064期间切到了资源管理器/测试夹，游戏被遮挡致丢窗
