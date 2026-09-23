# 云端离线工具验证记录（2026-09-23）

## 范围

只验证 `tools/summarize_solo_shadow.py` 的日志完整性与计划比较语义，不导入/启动生产 Mediator，不执行游戏输入、OCR、Qt、Windows API 或竞品 EXE。

源码通过 GitHub connector 读取。容器 DNS 检查 `socket.getaddrinfo('raw.githubusercontent.com',443)` 返回 `gaierror: [Errno -3] Temporary failure in name resolution`，未取得完整仓库 checkout；使用 connector 返回的固定版本内容在隔离目录建立工具和测试副本。本轮没有运行完整仓库 conftest、release_gate、C2/C4、frozen replay、templates、UI build 或实机测试。PR 必须保持 Draft；隔离通过不可替代完整发布门禁。

## 来源与字节核验

原工具来自 #33 固定 HEAD `94f502335dd3575926fc78e853f992edbb401fab`。经 connector base64 内容还原，字节长度 6021；计算 Git blob SHA-1（含 blob header）为 `ff6e1359c44191548fc4add46d61a50133bbdb14`，与 GitHub 返回的原 blob 一致。

修复后工具：10883 bytes，blob `83df18e1f47231d3bfb0ca3c8e83171195542ff5`。

新增测试：5880 bytes，blob `8070bae70a5873030e027ce2d34d96471cab25dc`。

三项 hash 均由本轮容器读取实际文件字节计算，修复和测试副本与提交对象对应 blob 一致。

## 执行结果

环境：Linux 容器，Python 3.13.5，pytest 9.0.2。独立目录仅含该工具和新增测试，没有原仓库 conftest。

命令：

```text
python -m pytest tests/test_solo_shadow_summary_integrity_20260923.py -q
```

同一份新测试针对原实现：退出码 1，**27 failed, 2 passed in 0.17s**。

修复后：退出码 0，**29 passed in 0.05s**。

```text
.............................                                            [100%]
29 passed in 0.05s
```

语法检查：

```text
python -m py_compile tools/summarize_solo_shadow.py tests/test_solo_shadow_summary_integrity_20260923.py
```

退出码 0。未设置 skip/xfail，未修改门禁、fixtures 或资产 baseline。

## 反例与兼容性

原实现对“一个合法记录 + 一个损坏 JSON 尾行”返回 CLI 0 并输出剩余记录汇总；`kill` / `open_skill_panel` 等子串误配计一致；不同文件的同名 round_id 合并。这些反例由上述标量测试直接复现，不依赖游戏机制假设。27 个失败同时包含行为反例和新增输出字段合同，不等于 27 个独立生产缺陷。

修复使用显式 skill/bond/treasure 家族映射，只在记录声明 `plan_in_window` 时比较；未知映射单列 uncomparable。`bond_draw` 和 `bond_refresh` 都可能与 bond 计划家族一致，但这不是两个动作等价的证据。

所有报告标 `PLAN_TARGET_ONLY`、`behavior_proof=false`、`actual_action_evidence=NOT_AVAILABLE`；旧 `recommend_vs_actual_*` 仅保留为弃用兼容别名。`report_schema=2`，rounds key 按 source file/log schema/round_id 隔离；旧 JSON 消费脚本需按 schema 迁移。

损坏/非对象/重复 key/未知 schema/非法 seq 被拒绝；同文件 seq 重置须调查会话身份。明确输入缺失不得忽略；重复传入同一 resolved path 不重复计数。本工具检查其消费字段，不是快照内所有事实的完整 schema/合法性验证器。

默认只做完整日志汇总，不支持跳过坏行继续。对仍在追加、尾行未 flush 的日志，应在记录关闭后汇总；不能把本次报错当成已通过。

## 尚未证明

没有证明 runtime shadow on/off 行为等价；没有修复 runtime 的提前 OCR、真实动作回执配对、事实有效期、跨局清理和服务时钟。这些实现合同已在架构报告 §5 明确，交给本地按真实入口接线和验证。合成标量日志只测试工具，不是合成游戏帧，也不是游戏 Ground Truth。
