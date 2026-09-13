# GAP_REBASE_MATRIX_20260909.md

| ITEM | OLD_REPORT | CURRENT_REF | CURRENT_FILE | CURRENT_STATUS | OWNER | NEXT_ACTION |
|---|---|---|---|---|---|---|
| GAP A: Refresh mutation dead evidence | 10046-10051 清基线, 2918 指纹死变量 | d9148c8 | src/shuabao/mediator.py:878, 2913, 3086, 10538, 10559 | CONFIRMED_CURRENT_PRODUCTION | TEST_LAB | 在 GT Lab 建立 Merchant/Treasure refresh 真实突变基线，不直接盲改 formal |
| GAP B: Quarantine liveness starvation | 10951-10953 检疫不断刷新主线时钟导致15s看门狗饿死 | d9148c8 | src/shuabao/mediator.py:10757, 10769, 10953, 11001 | HISTORICAL_OR_WRONG_REF | NO_ACTION | 经全生命周期审查，检疫配额耗尽后推进至 PanelState.COOLDOWN，该状态不刷新主线时钟，看门狗正常运转 |
| GAP C: Merchant purchases==0 fail-open | merchant_fsm.py:44-46 注释导致循环烧满 20 rerolls | d9148c8 | src/shuabao/policy/merchant_fsm.py:44-46 | CONFIRMED_CURRENT_PRODUCTION | TEST_LAB | 代码含明确注释证明为有意设计，先在 GT Lab 评估 N 次相同指纹作为 BOUNDED STOP EVIDENCE |
| GAP D: Pressure transfer never appears | 蹭车压力转移按钮从未出现导致无界等待 | d9148c8 | src/shuabao/mediator.py:821, 5635 | ALREADY_FIXED | NO_ACTION | d9148c8 已落地 40-tick fresh reobserve 有界预算，超界转 PRESSURE_CORE_FAILURE，0 盲点 |
| GAP E: Archaeology blind coordinate | stage_archaeology_btn 缺失退回固定 0.86W/0.903H 盲点 | d9148c8 | src/shuabao/mediator.py:865, 6237 | ALREADY_FIXED | NO_ACTION | d9148c8 彻底移除伪造坐标，改用 40-tick reobserve 有界预算，耗尽 Fail-Closed 停机 |
| GAP F: Lobby low-information assets | 5 个大厅纯色模板（std 1.09）持有动作权且无 GT | d9148c8 vs 53afb43 | src/shuabao/mediator.py:9312 | CONFIRMED_CURRENT_PRODUCTION | TEST_LAB | Formal 仍留 1 处 room_exit_btn 点击；53afb43 已完全剥离该控件动作权，需待 53afb43 进入正式验证链 |
| GAP G: Battle GT coverage | 战斗侧场景除部分宝物 OCR 外几无正向/困难负向 GT | d9148c8 | fixtures/**, tests/** | NEEDS_GT | TEST_LAB | 盘点表明 talisman/devour_pill/public_bag/wood/disconnect 为 0 GT，需建立真实截图库 |
| GAP H: Asset hygiene | test_patch.png 混入, kk_start 四重复, dead fallback keys | d9148c8 | assets/Images/**, config/scenes.json | CONFIRMED_CURRENT_PRODUCTION | ASSET_HYGIENE | test_patch.png 仍存在，kk_start 4-way 重复存在，scenes.json 存在 2 处死 fallback 键，等待清洗 |
