# Signed Entitlement Permit 协议（Ed25519）

状态：**客户端验证已落地，Subscription Server 尚不存在**。本文档描述目标协议与
服务器契约；在服务器与生产公钥出现之前，本机验证一律 fail-closed（空公钥注册表
即全部拒绝）。

## 角色

- **Subscription Server（未建成）**：持有 Ed25519 私钥，唯一签发方。验证 license
  状态后签发 permit；永不向客户端发送私钥或签发接口。
- **客户端 `src/shuabao/subscription_permit.py`**：只做验证。`PermitVerifier`
  消费公钥注册表 + `EntitlementPermit` + `PermitVerificationContext`，产出
  `VerifiedPermit` 或抛 `PermitVerificationError`。
- **私钥纪律**：私钥只存在于服务器；本仓库、测试、构建产物中禁止出现任何私钥
  材料。测试使用进程内存中即时生成的密钥对。

## Permit 结构（schema_version = 1）

JSON object，字段全集（严格模式：缺失、多余、形状错误一律 `PERMIT_MALFORMED`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| schema_version | int | 恒为 1；其他值 `PERMIT_SCHEMA_UNKNOWN` |
| permit_id / jti | str | 服务器生成的唯一 ID，两者必须一致 |
| license_id | str | 订阅 license 标识 |
| device_id / device_fingerprint | str | 绑定设备指纹，两者必须一致 |
| release_channel | str | stable/beta 等发布渠道 |
| source_sha | str | 绑定的源码 commit SHA |
| release_manifest_sha256 | str | 绑定的发布 manifest 哈希 |
| allowed_modes | list[str] | 允许的启动模式（如 ["live"]） |
| features | list[str] | 授权特性集合 |
| issued_at / expires_at | str | UTC ISO-8601（`YYYY-MM-DDTHH:MM:SSZ`） |
| nonce | str | 一次性随机值（重放防护） |
| signature_algorithm | str | 恒为 `Ed25519`，其他值 `PERMIT_MALFORMED` |
| key_id | str | 公钥注册表中的密钥标识 |
| signature | str | Ed25519 签名，base64url 无 padding |

### Canonical payload

被签名字节串 = 对上述 JSON（**不含 signature 字段**）做
`json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`
的 UTF-8 编码。服务器与客户端必须产出完全一致的字节串。

## 客户端验证顺序（全部 fail-closed）

1. 结构解析（`EntitlementPermit.from_mapping`）：字段全集、类型、恒等对
   （permit_id==jti、device_id==device_fingerprint）、时间形状、算法名、
   base64url 无 padding → `PERMIT_MALFORMED` / `PERMIT_SCHEMA_UNKNOWN`。
2. key_id 解析 → 公钥注册表无此 key → `PERMIT_KEY_UNKNOWN`（空注册表同样）。
3. 时间窗：`issued_at > expires_at` → `PERMIT_MALFORMED`；`now > expires_at` →
   `PERMIT_EXPIRED`；`issued_at - 300s > now` → `PERMIT_NOT_YET_VALID`
   （容许 5 分钟时钟偏差）。
4. 绑定核对：device_id / source_sha / release_manifest_sha256 / release_channel
   / mode_id ∈ allowed_modes → 各自 `PERMIT_DEVICE_MISMATCH`、
   `PERMIT_SOURCE_MISMATCH`、`PERMIT_MANIFEST_MISMATCH`、
   `PERMIT_CHANNEL_MISMATCH`、`PERMIT_MODE_NOT_ALLOWED`。
5. Ed25519 验签失败 → `PERMIT_SIGNATURE_INVALID`。
6. 重放（如提供 replay store）：`claim(permit_id, nonce)` 原子性返回 False →
   `PERMIT_REPLAY`。`InMemoryReplayStore` 为进程内参考实现；服务器化时按同一
   接口替换。claim 仅在签名与上述全部检查通过后执行：任何验证失败的 permit
   都不占用 permit_id/nonce 重放额度。

任何错误码都不得降级为放行；`StartPermission(allowed=True)`（shadow/off 或
服务端 can_start_runner）本身不构成 LIVE 授权。显式 dev/off 路径使用独立的
`DevStartCapability`（仅 mode="off" 可构造），它与 permit 验证互不替代。

## 服务器响应契约（未来实现）

`POST /v1/permits`（HTTPS；本机 Bridge 允许 loopback HTTP），请求携带 license
凭据 + 本机绑定事实（device_id、source_sha、release_manifest_sha256、
release_channel、请求 modes/features）。成功响应体即 permit JSON（上表全集，
含 signature）；拒绝时返回：

```json
{"ok": false, "code": "<STABLE_ERROR_CODE>", "message": "<人类可读>"}
```

错误码约定沿用现有 Subscription 客户端风格（`ENTITLEMENT_*`、`CONFIG_*`）。
时钟偏差容忍 ±300 秒；permit 有效期建议 ≤ license 剩余有效期，且不超过 24 小时。

## 公钥轮换

- `config/entitlement_public_keys.json`：`{"keys": {"<key_id>": "<base64 SPKI DER>"}}`。
- 轮换 = 注册表加入新 key_id（双活窗口）→ 服务器切换签发 → 窗口结束后移除旧
  key_id。客户端永不缓存跨版本注册表之外的 key。
- 文件缺失/损坏/结构错误（含根非 JSON object、密钥解码失败或非 Ed25519 公钥）
  → `PERMIT_KEY_REGISTRY_INVALID`，验证 fail-closed。
- **当前生产注册表为空**：无服务器、无生产公钥，任何 permit 都会被拒绝，这是
  预期行为，不得伪造或预置密钥。

## 撤销与网络失败语义

- **撤销**：服务器在有效期内的 permit 可通过短有效期（≤24h）+ 启动时重新签发
  实现事实撤销；后续可增加服务器端撤销列表查询（nonce/permit_id 维度），客户端
- **网络失败**：无法取得新 permit 时 LIVE 不启动（enforce 模式）。
- **shadow 模式**：只记录权威决策，不产生 LIVE 授权；LIVE 仍必须经过
  `resolve_live_permission` 的 signed permit 或显式、受信任的 dev/off capability。
- **重放存储丢失**（进程重启）：进程内 store 清空即允许同一 permit 在新进程再次
  使用一次；这是已知边界，服务器侧 nonce 唯一性约束是最终防线。
