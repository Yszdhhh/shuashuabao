# 背包自动清理真机夹具 (2026-09-25)

## 来源与背景
- **采样时间**：2026-09-25
- **原始源路径**：`G:\刷刷宝\captures\backpack_clean_gt_20260925\`（只读实机截屏）
- **客户端规格**：1600x900 客户区
- **用途**：蹭车乘客模式局内自动清理背包完整事务单测与真机回归资产

## 文件对应关系
- `01_hud.png`：来自 `g0001_102114.png`，局内正常 HUD 画面，底部信息栏有「存档」按钮（`assets/Images/backpack/hud_cundang.png` 命中 @ (392, 712)）。
- `02_page_items_tab.png`：来自 `g0002_102119.png`，点存档后打开的存档页，默认停留在「物品」页签（底部为一键回收，不能点；左侧为装备页签）。
- `03_page_equip_tab.png`：来自 `g0003_102122.png`，切到「装备」页签，底部出现「一键分解」按钮（`assets/Images/decompose.png` 命中 @ (404, 853)）。
- `04_quality_dialog.png`：来自 `g0004_102127.png`，点一键分解后弹出的"请选择品质："弹窗（精良及以下✓、史诗✓、传说☐，按钮「是」/「否」）。
- `05_dialog_closed.png`：来自 `g0005_102130.png`，点「是」后弹窗关闭，停留在装备存档页，右上角有「返回游戏」按钮。
- `06_hud_returned.png`：来自 `g0006_102134.png`，点右上角「返回游戏」后回到局内 HUD，存档按钮重新可见。

单人入口回放复用已有的真实选关帧 `fixtures/stage_select_20260814/highlight_on_1_1_client_1600x900.png`，以及本目录的存档页和弹窗帧。选关页用 `backpack/tab_cundang.png` 进入；返回时用 `backpack/tab_lobby.png` 点击「游戏大厅」页签。异常品质弹窗的「否」按钮模板 `backpack/quality_no.png` 直接从 `g0004_102127.png` 裁出。
