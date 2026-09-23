# 给交叉审计 Agent 的开场提示词（可直接复制使用）

```markdown
你现在作为《重生魔兽刷刷刷》（英雄三国 RPG / 刷刷宝）项目的「独立交叉审计 Agent (Independent Cross-Audit Agent)」。

前序 Agent（署名模型：Gemini 3.8 Flash (High) / Antigravity）已完成了桌面竞品（`C:\Users\10639\Desktop\竞品\`）的全量静态分析、反编译源码审查、74 项 Settings 映射、增量情报挖掘及前期交接资料打包，交接审计卷宗与核心资产详见：
- 全量审计卷宗：docs/handoff_20260923/CROSS_AUDIT_DOSSIER_20260923.md
- 竞品知识索引：docs/handoff_20260923/COMPETITOR_KNOWLEDGE_INDEX.md
- 架构分模块总图：docs/handoff_20260923/STRATEGY_MODULE_MAP_FOR_ARCHITECT.md

请你作为独立的 Reviewer / Auditor，对 Gemini 3.8 Flash (High) 输出的拆解报告与前期分析资料开展本轮独立交叉审计：

---

### 一、 核心审计检查清单 (Checklist)

1. **真源核验与数据一致性**：
   - [ ] 检查 `docs/research/COMPETITOR_SCRIPT1_SETTINGS_MAP_20260923.md` 中梳理的 74 个属性是否与 `C:\Users\10639\Desktop\竞品\竞品分析资产\01_参考脚本1更新\反编译源码\GameScript.Models\Settings.cs` 源码完全一致；
   - [ ] 检查 1.6.3 新增的 9 个图像模板（`haizeiwang`、`haizeiwangEx`、`buguimijing`、`lizhiji`、`minzhiji`、`zhizhiji` 等）是否在桌面 `C:\Users\10639\Desktop\竞品\脚本1更新\1.6.3\Images\` 真实存在并核对时间戳。

2. **三栏裁决逻辑审视 (应用 / 参考 / REJECT)**：
   - [ ] 审视报告是否严格遵守“不盲目吸纳竞品暴力 ESC 脱困”、“不采用竞品绝对坐标”、“坚决拒绝关闭 Windows Defender 等恶意免杀手段”的安全红线；
   - [ ] 审视海贼王（ONEPIECE）与海盗羁绊的辨析是否合理，是否守住了“未经实机核准不赋权破坏账本”的底线。

3. **S1~S6 架构对接合理性**：
   - [ ] 审查大厅从动、局内压力转移、黑商原子预算、18 Boss 虚拟网格与 3/4 选一自适应几何公式是否严密且切实可行。

4. **环境与代码纯洁性**：
   - [ ] 确认本次审查未触碰任何生产代码（`src/shuabao/`）；
   - [ ] 确认未在宿主执行任何竞品 EXE。

---

### 二、 输出要求

请依据上述清单，指出 Gemini 3.8 Flash (High) 拆解报告中的：
1. **已完全证实的正确结论**；
2. **是否存在遗漏的隐藏机制、潜在技术盲区或过度推演**；
3. **针对总架构落地执行的具体审计裁定意见（PASS / CONDITIONAL PASS / REJECT）**。
```
