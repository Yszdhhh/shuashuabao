# Release Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task with review checkpoints.

**Goal:** 将 LIVE 启动从可构造的 `StartPermission(allowed=True)` 提升为服务端 Ed25519 Permit 能力，并建立 release manifest/AuthentiCode 外发签名边界；同时只登记未完成看板和大厅蹭车的回归/真机阻断测试，不改游戏自动化逻辑。

**Architecture:** `subscription_client.py` 只负责请求并解析服务端 Permit；新增集中 verifier 负责 canonical payload、Ed25519 签名、设备/source/manifest/channel/mode/时间/重放校验。RunnerService、HeadlessRunner、`execute_runtime_mediator()` 共享同一 verifier，且最后一层仍在创建 Mediator/OCR/live.lock/真实输入之前拒绝。release manifest 使用相同的 canonical Ed25519 机制生成 `.sig`，公开 key registry 进入 runtime 包，私钥仅由外部签名输入提供。

**Tech Stack:** Python 3.11, `cryptography` Ed25519, PowerShell 5.1, PyInstaller, Vite/TypeScript, pytest.

**Spec:** 用户提供的 Release Security Hardening Task A-E；当前基线 `1dc52e0ce720a15594cb09720e77bdb3d73f9496`。

## Global Constraints

- 只在 `G:/刷刷宝/GameScript-Local` 工作；当前 `HEAD == origin/trial-merge == 1dc52e0...`。
- 保留未跟踪用户文件 `docs/CURRENT_STATUS_AND_HANDOFF_20260901_UI_12_8.md`，不加入改造提交。
- 禁止修改游戏 FSM、OCR 识别、Boss 路线、真实输入算法、OD12 CSS/页面壳。
- 私钥不得进入仓库、测试 fixture、PyInstaller 数据或日志；测试私钥只在测试进程临时生成。
- 当前没有 Subscription Server、生产 Permit、签名证书时，external-beta/release 必须 fail-closed。
- 失败必须早于 Mediator、OCR、live.lock、InputExecutor；网络失败不得授权。
- dev/internal-pilot 可以使用明确的 `DevStartCapability`，不能由 external/release 接受。

---

### Task 1: Signed Permit Protocol And Verifier

**Files:**
- Create: `src/shuabao/subscription_permit.py`
- Create: `config/entitlement_public_keys.json`
- Modify: `requirements-desktop.txt`
- Modify: `requirements-build.txt` only if the frozen runtime imports the verifier through the build environment
- Test: `tests/test_subscription_permit.py`
- Documentation: `docs/SIGNED_ENTITLEMENT_PROTOCOL.md`

**Interfaces:**
- `EntitlementPermit.from_mapping(payload: Mapping[str, Any]) -> EntitlementPermit`
- `EntitlementPermit.canonical_payload() -> bytes`
- `PermitVerificationContext` fields: `device_id`, `source_sha`, `release_manifest_sha256`, `release_channel`, `mode_id`, `now`
- `PermitVerifier(public_keys: Mapping[str, bytes], replay_store: ReplayStore | None = None)`
- `PermitVerifier.verify(permit: EntitlementPermit, context: PermitVerificationContext) -> VerifiedPermit`
- `PermitVerificationError(code: str, message: str)`
- Canonical JSON: UTF-8, `sort_keys=True`, compact separators, no signature field; signature is base64url without padding.

- [ ] Write negative-first tests for malformed schema, unknown key ID, bad signature, changed payload, expiry, future issue time, device/source/manifest/channel/mode mismatch, replay, and successful verification.
- [ ] Run `python -m pytest tests/test_subscription_permit.py -q`; expected RED before implementation.
- [ ] Implement strict schema validation for all required fields: `schema_version`, `permit_id`, `license_id`, `device_id`, `release_channel`, `source_sha`, `release_manifest_sha256`, `allowed_modes`, `features`, `issued_at`, `expires_at`, `nonce`, `signature_algorithm`, `key_id`, `signature`.
- [ ] Use `cryptography.hazmat.primitives.asymmetric.ed25519.Ed25519PublicKey`; reject algorithms other than `Ed25519` and public keys not found by `key_id`.
- [ ] Enforce UTC timestamps, bounded future skew, `issued_at <= now <= expires_at`, exact context bindings, non-empty allowed mode membership, and one-time `permit_id`/nonce policy when a replay store is supplied.
- [ ] Add empty public-key registry with documented operator replacement; no private material.
- [ ] Add protocol/server contract documentation specifying response `permit`, signing input, key rotation, rejection codes, revocation/network-failure semantics, and the fact that the repository does not implement the server.
- [ ] Run focused tests and commit `feat(subscription): add signed entitlement permit verifier`.

### Task 2: Integrate Permit Into Subscription And LIVE Capability

**Files:**
- Modify: `src/shuabao/subscription_client.py`
- Modify: `src/shuabao/shell/runner_service.py`
- Modify: `src/shuabao/shell/headless_runner.py`
- Modify: `src/shuabao/shell/live_execute.py`
- Modify: `src/shuabao/shell/dashboard_facade.py` only for context construction/cache handoff
- Modify: `src/shuabao/shell/main_window.py` only to pass the shared verified result
- Test: `tests/test_subscription_client.py`, `tests/test_dashboard_facade_runner.py`, `tests/test_live_execute.py` or existing equivalent

**Interfaces:**
- `DevStartCapability(mode: str, reason: str)` is the only explicit local development capability.
- `StartPermission` carries a parsed server permit and server decision; `allowed=True` without a cryptographically verified permit is never LIVE-authorizing.
- `verify_live_capability(capability, *, context) -> VerifiedPermit | DevStartCapability` is the one shared decision function used by all three LIVE layers.

- [ ] Update server response parsing so enforce mode requires a `permit` object; malformed/missing permit becomes a denial. Preserve key omission from messages/logs.
- [ ] Make off-mode return `DevStartCapability`, keep shadow as observational/non-production state, and ensure external/release cannot accept either off/shadow/dev capability.
- [ ] Build runtime binding from current device fingerprint, build identity `source_sha`, release manifest hash, release channel, and requested mode. Missing production identity/public key registry fails closed.
- [ ] Replace duplicate permission truth checks in RunnerService and HeadlessRunner with the shared verifier while preserving mode check → permission → lock → worker order.
- [ ] Replace `start_permission_allows()` final check in `execute_runtime_mediator()` with the same verifier/context. It must execute before logging install, RuntimeMediator import/construction, OCR bootstrap, or input initialization.
- [ ] Keep stop-before-permission semantics and existing dev-only dry-run behavior explicit; do not convert dry-run into a LIVE bypass.
- [ ] Update tests that currently construct `StartPermission(allowed=True)` to use temporary test-scope signed permits or `DevStartCapability` only in dev paths.
- [ ] Run focused subscription/runner tests; commit `feat(subscription): require verified permit for live capability`.

### Task 3: Permit Security Matrix And Crash-Path Regression Tests

**Files:**
- Modify/Create: `tests/test_subscription_permit.py`
- Modify: existing runner/facade/live execution tests
- Create: `tests/test_hitch_preflight.py` only if existing test modules cannot express the boundary without fixtures

**Interfaces:**
- Test-only Ed25519 keypair fixture generated in memory; no checked-in key bytes.
- Test context must use explicit source SHA, manifest hash, device ID, channel, and mode.

- [ ] Cover valid permit allow and ordinary manually constructed `StartPermission(True)` reject.
- [ ] Cover missing permit, one-byte signature mutation, payload mutation, expired, future-issued, device mismatch, source mismatch, manifest mismatch, channel mismatch, unauthorized mode, malformed JSON, unknown schema, unknown key ID, duplicate permit/replay, and network failure.
- [ ] Assert denial happens before `live.lock`, incident directory creation, Mediator construction, OCR startup, and InputExecutor invocation.
- [ ] Reproduce yesterday’s NameError crash path using the existing test stub; prove it is a test-stub/log-isolation leak rather than lobby business logic. Do not run true game input.
- [ ] Add deterministic startup classification for `EXPIRED`, missing OCR, missing identity, and UAC/permission failures.
- [ ] Commit `test(subscription): cover signed permit fail-closed matrix`.

### Task 4: Release Manifest Signing And Runtime Verification

**Files:**
- Create: `src/shuabao/release_signing.py`
- Create: `tools/sign_release_manifest.py`
- Create: `config/release_public_keys.json`
- Modify: `src/shuabao/shell/dashboard_facade.py`
- Modify: `build_release.ps1`
- Modify: `ShuaBao.spec`
- Modify: `tests/test_release_signing.py`, `tests/test_packaging_spec.py`
- Documentation: extend `docs/SIGNED_ENTITLEMENT_PROTOCOL.md` with release manifest contract

**Interfaces:**
- `canonical_manifest_bytes(manifest: Mapping[str, Any]) -> bytes`
- `sign_manifest(manifest_path, signature_path, key_file, key_id) -> SignatureEnvelope`
- `verify_manifest_signature(manifest, envelope, public_keys) -> None`
- Envelope fields: `schema_version`, `algorithm`, `key_id`, `manifest_sha256`, `signature`.

- [ ] Write tests for canonicalization stability, valid signature, changed manifest, changed signature, unknown key ID, malformed envelope, and private-key path absence; run RED.
- [ ] Implement key input as external path/env reference. Accept PEM or raw/base64 test-compatible private key only through the signing tool; never write private bytes into output.
- [ ] Sign canonical manifest content after `release_manifest.json` is assembled and before identity hashes are recorded. Keep `.sig` outside `manifest.files` or define explicit self-exclusion to avoid circular hashing.
- [ ] Verify signature immediately after signing and record `manifest_signature_status`, `signing_key_id`, `manifest_sha256`, source SHA, channel in `build_identity.json`.
- [ ] Runtime production identity verification must verify the signature envelope, public key ID, manifest hash, and every listed file hash. Dev/internal unsigned sidecars remain allowed only for their channels.
- [ ] Add both public-key registries to the explicit runtime config whitelist; no private key, test fixture, or raw live evidence enters the package.
- [ ] Update external preflight: absent signing key/public key mapping or unsigned manifest remains blocked before packaging. Do not remove existing fail-closed behavior.
- [ ] Commit `feat(release): sign and verify release manifests`.

### Task 5: Authenticode Signing Hook

**Files:**
- Modify: `build_release.ps1`
- Modify: `tests/test_packaging_spec.py`
- Documentation: `docs/SIGNED_ENTITLEMENT_PROTOCOL.md`

**Interfaces:**
- External environment: `SHUABAO_AUTHENTICODE_CERT_THUMBPRINT`, `SHUABAO_TIMESTAMP_URL`, optional `SHUABAO_SIGNTOOL_PATH`.
- `Invoke-AuthenticodeSigning($ExePath, $Role)` signs with `signtool.exe /fd SHA256 /tr <timestamp> /td SHA256 /sha1 <thumbprint>` and then calls `Assert-AuthenticodeValid`.

- [ ] Add static/PowerShell contract tests proving missing thumbprint, timestamp, signtool, or certificate blocks external builds before PyInstaller.
- [ ] Add signing hook between OCR copy and Authenticode verification; calculate release manifest file hashes only after signing.
- [ ] Preserve dev/internal build behavior and `signature_status=UNSIGNED` for those channels.
- [ ] Do not generate or trust a self-signed certificate as production evidence.
- [ ] Commit `build(release): wire external Authenticode signing hook`.

### Task 6: Packaging Minimality Review

**Files:**
- Modify: `ShuaBao.spec` only if a non-runtime file is proven unused
- Modify: `tests/test_packaging_spec.py`

- [ ] Trace `dashboard_test_profiles.json` production consumers. Remove it only if no production/frozen runtime consumer exists; otherwise retain and document the consumer test.
- [ ] Assert tests, fixtures, research docs, raw live evidence, unused knowledge bases, internal tools, keys, and license keys are absent from the release file list.
- [ ] Do not introduce XOR/base64 obfuscation or unrelated asset vault work.
- [ ] Commit `chore(packaging): verify runtime-only release contents` only when an actual allowlist change is required; otherwise keep source unchanged and record test evidence.

### Task 7: Schedule Unfinished Dashboard And Hitch Tests

**Files:**
- Modify: existing UI/package test modules only for regression contracts; no `ui-v2/index.html` or `ui-v2/src/main.ts` implementation changes in this round.
- Test: `tests/test_packaging_spec.py`, existing desktop/facade tests, optional `tests/test_hitch_preflight.py`.

- [ ] Record, but do not add failing tests for, five switch persistence, prestige-off persistence, empty skills/alloc/boss/CJB snapshot clearing, dynamic `lobby_hitch` startable badge, and misleading production “沙盒” success text. These belong to a later UI-only round; this security round must keep the existing suite green.
- [ ] Record lobby-hitch prerequisites: no production `lobby_refresh`, `room_list_row`, `lobby_home`, or join templates; OCR source currently returns empty text. Therefore do not start true-machine auto-room test yet.
- [ ] Run only existing safe preflight tests for subscription, identity, OCR worker, target window, mode catalog, and required anchors. A failed preflight must leave no live lock or input action; add new tests only in the later hitch-preflight round.
- [ ] Keep yesterday’s crash classification as BLOCKED until the desktop shortcut can be launched without UAC failure and the target game/anchors are available.
- [ ] Commit tests/schedule separately if repository policy requires persisted evidence; otherwise include in final report without changing product UI.

### Task 8: Verification And Delivery

**Files:**
- No new implementation files; use existing scripts and test modules.

- [ ] Run `python -m pytest tests -q`.
- [ ] Run `python tools/release_gate.py` and `python tools/release_gate.py --strict-release`; expected standard PASS and external strict BLOCKED until real signing/evidence exists.
- [ ] Run `npm run check`, `npm test`, and `npm run build` from `ui-v2` according to the actual package scripts; report missing scripts explicitly rather than substituting commands.
- [ ] Validate dev and internal-pilot build paths; validate external-beta/release fail before build side effects when signing prerequisites are absent.
- [ ] Rebuild current HEAD only after source tree identity is stable; compare build identity, manifest signature state, EXE/OCR hashes, and public-key registry contents.
- [ ] Attempt desktop shortcut and auto-room only if UAC, subscription, OCR, target window, mode evidence, and anchor gates all pass. Otherwise record exact BLOCKED reason, PID/exit status where available, and no synthetic evidence.
- [ ] Commit any final test-only changes, push `trial-merge` without force, verify `HEAD == origin/trial-merge`, and preserve the user’s untracked handoff document. Final tracked worktree must be clean.
