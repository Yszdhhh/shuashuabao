# VISION DATA BOUNDARY — 视觉资产边界与隐私防护规范
# Gemini Stage 1 — 研发与生产资产严格解耦
# 权威基准: G:\刷刷宝\GameScript-Local | 发布门禁: tools/release_gate.py

---

## 1. 资产三级边界体系定义

为了彻底终结“开发抓一张图就塞进生产 assets 一起打包”的乱象，项目确立以下三级资产边界：

```
[ DEV_ONLY 研发物料 ] (15.9万张, 27.2GB)
        │ (离线清洗 / 聚类蒸馏 / 提取 ROI / 调优词典)
        ▼
[ TEST_ONLY 回归夹具 ] (155个金标准槽位, 约 5MB)
        │ (只用于 pytest / evaluate_choice_ocr.py 质量把关，不打入发布包)
        ▼
[ RUNTIME_REQUIRED 生产必需品 ] (仅结构化配置 + 极少量字形图标, < 500KB)
        └─► 真正跟随发布 EXE / Installer 分发给用户
```

---

## 2. 详细资产清单与归属表

### 2.1 DEV_ONLY (仅限研发与离线分析)
**绝对禁止打入生产安装包、禁止提交进 Git 主分支代码库：**
1. `G:\下载\1.5.1.zip\Images` (293 张历史参考小图)；
2. `%LOCALAPPDATA%\ShuaBao\incidents\**\*.jpg` (11,305 张实机故障截图快照)；
3. `G:\刷刷宝\测试夹` 中的全部未裁剪大图及录屏切片 (5,333 张图片)；
4. `G:\测试视频+抽帧` 中的全量连续帧 (142,075 张图片)；
5. `G:\刷刷宝\_codex_skill_video_evidence` 与 `video_frames`；
6. 任何中间生成的 `.temp_crop.png` 或调试用分析图像。

### 2.2 TEST_ONLY (仅限测试与 CI 回归)
**存放于 `fixtures/ocr_choices/`，受 `tools/evaluate_choice_ocr.py` 严格校验，仅在测试环境中运行：**
1. `fixtures/ocr_choices/skill/` (47 个经人工复核的技能紧凑裁剪槽)；
2. `fixtures/ocr_choices/bond/` (53 个经人工复核的羁绊紧凑裁剪槽)；
3. `fixtures/ocr_choices/treasure/` (54 个用于负例测试的宝物裁剪槽)；
4. `fixtures/ocr_choices/manifest.json` 与 `VISION_EVAL_MANIFEST.jsonl`；
5. 负面板触发与分类验证夹具 (`fixtures/ocr_choices/negatives/`)。

### 2.3 RUNTIME_REQUIRED (真正随生产包分发)
**只有以下经过严格审批的轻量资产才允许进入发布包：**
1. **结构化参数配置**：
   - `config/scenes.json` (ROI 矩形、阈值、检测器绑定)；
   - `config/choice_lexicon.json` (规范名、别名、混淆词典，~25KB)；
   - `config/skill_labels.json` / `config/fetter_labels.json`；
   - `config/vision_profiles.proposed.yaml` (蒸馏后的新版视觉配置)；
2. **合法 UI / Logo 素材**：
   - `assets/branding/app_logo.png`
   - `assets/branding/pet_mode_1.png`, `pet_mode_2.png`
3. **极少量不可替代的紧凑字形与核心图标** (`assets/Images/` 保持在 300KB 以内)：
   - 36 张 `cards/*.png` (标题艺术字字形，平均仅 2KB/张)；
   - 54 张 `boss/*.png` (Boss 头像缩略图，平均 3KB/张)；
   - 16 张 `skills/*.png` (基础技能图标)；
   - 必要的 L0 大厅定位锚点 (如 `create_room.png`, `startGameBtn.png`)；
4. **轻量 OCR 推理引擎与权重**：
   - `models/ocr/PP-OCRv5_mobile_rec_infer/` (经过 SHA256 校验的官方 Mobile 识别模型，约 12MB)。

---

## 3. 隐私保护与零截图泄漏铁律

1. **普通运行日志零截图原则**：
   - 生产环境下的常规日志（`logs/ShuaBao.log`）严禁以任何理由自动保存全屏截图；
2. **Debug 故障快照隔离与自动清理**：
   - 仅在用户显式开启“调试日志”且发生严重异常时，才允许在 `%LOCALAPPDATA%\ShuaBao\incidents\` 保存低压缩比故障帧；
   - 必须配置 Retention 策略：单日最多保留 20 宗 incident，超过 7 天的旧数据自动轮转清理，总容量上限锁定为 500MB；
3. **发布门禁（Release Gate）路径白名单校验**：
   - `tools/release_gate.py` 在打包前执行静态资产扫描，严禁 `*.jpg`、`fixtures/`、`testjia`、`tmp`、`incidents` 等非白名单路径进入构建产物。
