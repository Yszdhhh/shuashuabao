# N0 热路径基准报告

> 生成时间：2026-08-11T09:27:37（耗时 19.4s）
> repo HEAD：8facf06b04ad25b851ed65eac4b6164b31ff4836（branch=codex/ocr-hybrid，dirty=True）
> 环境：Python 3.11.15 / OpenCV 4.14.0 / numpy 2.4.6 / CPU Intel64 Family 6 Model 183 Stepping 1, GenuineIntel
> 模板聚合 SHA256：`9060a146c803eae50409dbd03b8ec5659e3c8f0bf680304dd9dc7750d6523ff8`（316 个文件，assets/Images）
> 每模式迭代数：3

## 逐 fixture 结果（P50 ms / P95 ms）

| fixture | mode | total P50/P95 | capture | health | context | decision | action | matches P50 | pixels P50 |
|---|---|---|---|---|---|---|---|---|---|
| idle_hud | cold | 184.8/216.6 | 26.6 | 22.7 | 73.2 | 63.6 | 0.0 | 39 | 8944285 |
| idle_hud | warm_changed | 209.5/210.6 | 21.3 | 26.3 | 83.4 | 76.1 | 0.0 | 39 | 8944285 |
| idle_hud | exact_static | 22.4/25.0 | 0.0 | 22.2 | 0.0 | 0.3 | 0.0 | 0 | 0 |
| skill_panel | cold | 87.5/98.6 | 23.2 | 23.1 | 3.4 | 37.1 | 0.0 | 14 | 5259232 |
| skill_panel | warm_changed | 85.8/87.7 | 25.0 | 22.0 | 3.4 | 36.5 | 0.0 | 14 | 5259232 |
| skill_panel | exact_static | 25.1/26.3 | 0.0 | 24.9 | 0.0 | 0.1 | 0.0 | 0 | 0 |
| bond_panel | cold | 84.1/93.2 | 22.4 | 32.4 | 12.4 | 16.8 | 0.0 | 10 | 3946956 |
| bond_panel | warm_changed | 77.2/77.4 | 21.8 | 31.0 | 13.6 | 12.6 | 0.0 | 10 | 3946956 |
| bond_panel | exact_static | 22.4/25.9 | 0.0 | 22.1 | 0.0 | 0.4 | 0.0 | 0 | 0 |
| treasure_panel | cold | 74.7/87.4 | 25.4 | 25.2 | 8.2 | 18.0 | 0.0 | 11 | 4229216 |
| treasure_panel | warm_changed | 66.2/68.3 | 22.3 | 20.0 | 7.4 | 16.7 | 0.0 | 11 | 4229216 |
| treasure_panel | exact_static | 23.1/23.4 | 0.0 | 22.6 | 0.0 | 0.5 | 0.0 | 0 | 0 |
| victory | cold | 203.4/215.7 | 22.7 | 25.3 | 151.7 | 6.7 | 0.0 | 25 | 9360734 |
| victory | warm_changed | 198.7/253.4 | 25.0 | 28.6 | 146.7 | 5.6 | 0.0 | 25 | 9360734 |
| victory | exact_static | 33.1/41.9 | 0.0 | 33.0 | 0.0 | 0.1 | 0.0 | 0 | 0 |
| fail_panel | cold | 234.9/235.4 | 8.8 | 30.7 | 10.9 | 176.6 | 0.0 | 26 | 13254192 |
| fail_panel | warm_changed | 285.7/285.9 | 6.9 | 37.7 | 15.5 | 206.7 | 0.0 | 26 | 13254192 |
| fail_panel | exact_static | 45.3/50.2 | 0.0 | 45.1 | 0.0 | 0.1 | 0.0 | 0 | 0 |
| giveup_panel | cold | 67.8/68.2 | 7.9 | 28.6 | 11.8 | 15.0 | 0.0 | 9 | 5225472 |
| giveup_panel | warm_changed | 65.8/71.1 | 6.3 | 30.4 | 11.7 | 16.2 | 0.0 | 9 | 5225472 |
| giveup_panel | exact_static | 34.0/34.9 | 0.0 | 33.6 | 0.0 | 0.4 | 0.0 | 0 | 0 |
| stage_select | cold | 300.7/315.7 | 17.5 | 20.7 | 252.5 | 9.4 | 0.0 | 51 | 17264560 |
| stage_select | warm_changed | 333.2/375.0 | 20.6 | 27.1 | 274.7 | 13.5 | 0.0 | 51 | 17264560 |
| stage_select | exact_static | 33.1/34.4 | 0.0 | 22.4 | 0.0 | 10.7 | 0.0 | 4 | 2128 |
| room_waiting | cold | 373.4/421.3 | 4.1 | 11.7 | 357.6 | 0.1 | 0.0 | 130 | 24872886 |
| room_waiting | warm_changed | 407.4/432.2 | 4.3 | 11.4 | 391.6 | 0.1 | 0.0 | 130 | 24872886 |
| room_waiting | exact_static | 11.5/12.2 | 0.0 | 11.4 | 0.0 | 0.0 | 0.0 | 0 | 0 |
| unknown_page | cold | 460.8/467.8 | 13.8 | 22.2 | 408.0 | 16.9 | 0.0 | 79 | 25414992 |
| unknown_page | warm_changed | 408.3/445.7 | 8.6 | 23.7 | 360.6 | 15.5 | 0.0 | 79 | 25414992 |
| unknown_page | exact_static | 19.0/22.2 | 0.0 | 19.0 | 0.0 | 0.0 | 0.0 | 0 | 0 |
| black_frame | cold | 25.1/26.4 | 6.1 | 19.1 | 0.0 | 0.0 | 0.0 | 0 | 0 |
| black_frame | warm_changed | 24.9/25.3 | 5.0 | 19.9 | 0.0 | 0.0 | 0.0 | 0 | 0 |
| black_frame | exact_static | 20.5/21.4 | 0.0 | 20.5 | 0.0 | 0.0 | 0.0 | 0 | 0 |

## 实时捕获参考（本机）

- skipped
