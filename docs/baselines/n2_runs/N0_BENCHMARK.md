# N0 热路径基准报告

> 生成时间：2026-08-11T07:48:21（耗时 140.6s）
> repo HEAD：0f8681e153583abb2537f81cfa98c62f312474bb（branch=codex/ocr-hybrid，dirty=True）
> 环境：Python 3.11.15 / OpenCV 4.14.0 / numpy 2.4.6 / CPU Intel64 Family 6 Model 183 Stepping 1, GenuineIntel
> 模板聚合 SHA256：`9060a146c803eae50409dbd03b8ec5659e3c8f0bf680304dd9dc7750d6523ff8`（316 个文件，assets/Images）
> 每模式迭代数：3

## 逐 fixture 结果（P50 ms / P95 ms）

| fixture | mode | total P50/P95 | capture | health | context | decision | action | matches P50 | pixels P50 |
|---|---|---|---|---|---|---|---|---|---|
| idle_hud | cold | 2087.8/2140.7 | 20.2 | 17.7 | 601.5 | 1437.0 | 0.0 | 58 | 52307393 |
| idle_hud | warm_changed | 2059.0/2078.9 | 21.4 | 17.8 | 594.2 | 1419.2 | 0.0 | 58 | 52307393 |
| idle_hud | exact_static | 18.3/19.1 | 0.0 | 18.1 | 0.0 | 0.3 | 0.0 | 0 | 0 |
| skill_panel | cold | 497.5/501.5 | 20.2 | 18.0 | 30.3 | 429.4 | 0.0 | 20 | 18589110 |
| skill_panel | warm_changed | 491.9/499.2 | 19.7 | 18.1 | 30.1 | 424.5 | 0.0 | 20 | 18589110 |
| skill_panel | exact_static | 50.9/51.2 | 0.0 | 17.7 | 0.0 | 33.1 | 0.0 | 2 | 783432 |
| bond_panel | cold | 238.5/243.1 | 20.1 | 24.2 | 47.4 | 147.2 | 0.0 | 15 | 11882533 |
| bond_panel | warm_changed | 233.6/237.6 | 18.8 | 18.2 | 45.3 | 151.4 | 0.0 | 15 | 11882533 |
| bond_panel | exact_static | 17.9/18.6 | 0.0 | 17.5 | 0.0 | 0.4 | 0.0 | 0 | 0 |
| treasure_panel | cold | 346.9/359.7 | 21.1 | 18.7 | 32.7 | 274.3 | 0.0 | 16 | 14722369 |
| treasure_panel | warm_changed | 331.3/339.1 | 20.1 | 18.0 | 29.5 | 264.4 | 0.0 | 16 | 14722369 |
| treasure_panel | exact_static | 18.7/18.9 | 0.0 | 18.3 | 0.0 | 0.4 | 0.0 | 0 | 0 |
| victory | cold | 1131.8/1137.3 | 19.4 | 17.3 | 1082.1 | 13.3 | 0.0 | 28 | 27310223 |
| victory | warm_changed | 1149.5/1161.5 | 19.7 | 19.5 | 1096.7 | 13.2 | 0.0 | 28 | 27310223 |
| victory | exact_static | 22.3/22.7 | 0.0 | 22.2 | 0.0 | 0.1 | 0.0 | 0 | 0 |
| fail_panel | cold | 985.5/989.2 | 6.1 | 24.6 | 39.8 | 914.6 | 0.0 | 31 | 33072624 |
| fail_panel | warm_changed | 983.0/1002.0 | 6.1 | 24.7 | 39.4 | 912.8 | 0.0 | 31 | 33072624 |
| fail_panel | exact_static | 308.8/309.3 | 0.0 | 24.5 | 0.0 | 284.3 | 0.0 | 12 | 6473520 |
| giveup_panel | cold | 292.2/298.7 | 6.2 | 27.4 | 40.7 | 213.8 | 0.0 | 14 | 16231104 |
| giveup_panel | warm_changed | 291.6/301.2 | 5.6 | 26.8 | 40.2 | 223.2 | 0.0 | 14 | 16231104 |
| giveup_panel | exact_static | 25.3/32.1 | 0.0 | 24.9 | 0.0 | 0.4 | 0.0 | 0 | 0 |
| stage_select | cold | 2344.2/2352.7 | 16.7 | 18.4 | 2299.7 | 9.4 | 0.0 | 54 | 60626128 |
| stage_select | warm_changed | 2352.6/2361.6 | 17.5 | 18.1 | 2308.2 | 9.6 | 0.0 | 54 | 60626128 |
| stage_select | exact_static | 26.7/27.0 | 0.0 | 17.3 | 0.0 | 9.5 | 0.0 | 4 | 2128 |
| room_waiting | cold | 3333.1/3357.4 | 3.4 | 8.9 | 3320.1 | 0.1 | 0.0 | 139 | 86223280 |
| room_waiting | warm_changed | 3335.0/3347.2 | 3.4 | 9.2 | 3323.2 | 0.1 | 0.0 | 139 | 86223280 |
| room_waiting | exact_static | 8.4/9.6 | 0.0 | 8.3 | 0.0 | 0.0 | 0.0 | 0 | 0 |
| unknown_page | cold | 4784.8/4789.0 | 8.2 | 19.2 | 4067.0 | 691.0 | 0.0 | 109 | 123669360 |
| unknown_page | warm_changed | 4723.1/4740.0 | 6.0 | 17.2 | 4013.4 | 677.2 | 0.0 | 109 | 123669360 |
| unknown_page | exact_static | 17.5/18.2 | 0.0 | 17.5 | 0.0 | 0.1 | 0.0 | 0 | 0 |
| black_frame | cold | 22.6/22.7 | 5.1 | 17.4 | 0.0 | 0.0 | 0.0 | 0 | 0 |
| black_frame | warm_changed | 22.7/22.8 | 5.1 | 17.6 | 0.0 | 0.0 | 0.0 | 0 | 0 |
| black_frame | exact_static | 18.2/18.3 | 0.0 | 18.2 | 0.0 | 0.0 | 0.0 | 0 | 0 |

## 实时捕获参考（本机）

- skipped
