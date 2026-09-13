# Runtime Artifact Identity & Packaging Architecture (2026-09-10)

## 1. Executive Summary

A critical issue in local deployment is version drift between the Git source repository, the built dist folder, and desktop shortcuts.
This document details the exact cause of version desynchronization observed on this machine and provides the design and specification for `RuntimeIdentityManifest` and the proposed `ShuaBaoLauncher`.

---

## 2. Desktop Shortcut & Installation Dissection

### 2.1 The Concrete Physical Findings
On this workstation:
- **Git HEAD**: `3e9c50a` (Clean, commit on 2026-09-09)
- **Primary Desktop Shortcut**: `C:\Users\10639\Desktop\刷刷宝.lnk`
- **Shortcut Target**: `C:\Users\10639\AppData\Local\ShuaBao\app-0.3-dev-b15da05f4fd7\ShuaBao.exe`
- **Embedded Manifest (`build_identity.json`)**:
  ```json
  {
    "schema_version": 1,
    "source_sha": "b15da05f4fd7313b02b2cc466e319d9683aa979c",
    "source_tree_clean": true,
    "build_id": "v0.3",
    "version": "0.3",
    "exe_name": "ShuaBao.exe",
    "exe_sha256": "9562d4fcdcbad6e30a132625cc190db1dc7762e256ba3d013bd8a81d0d557f4c",
    "bridge_schema_version": 2,
    "release_channel": "dev",
    "signature_status": "SIGNED",
    "ocr_model_manifest_sha256": "32dbdbed1e113e7db587e02b341e66bf97797c792db85b2f8e63d184d08ba660",
    "release_manifest_sha256": "a37e1e6eacdcc27ab8cd6700ccda17c88fa6eaa2d6f913d2be2fa60fa44f2b47",
    "created_at_utc": "2026-09-07T06:29:14.7019156Z"
  }
  ```

### 2.2 Why Desktop Updates Fail Silently
1. **Directory-Per-Build Structure**: Build scripts produce `app-<version>-<sha>` subdirectories.
2. **Fixed Shortcut Link Target**: The desktop shortcut created during initial setup links to the specific folder `app-0.3-dev-b15da05f4fd7`.
3. **No Dynamic Pointer Resolution**: Windows `.lnk` files do not evaluate JSON files. When a user double-clicks `刷刷宝.lnk`, Windows directly executes the path stored in the link header.
4. **Resolution**: The shortcut target must point to a stable wrapper (such as `ShuaBaoLauncher.exe` or `ShuaBao.cmd`) that reads `current.json` or evaluates the latest folder by build timestamp.

---

## 3. Stable Launcher Architecture Specification

### 3.1 Launcher Responsibilities
The proposed `ShuaBaoLauncher`:
1. **Find Installed Releases**: Inspect `C:\Users\10639\AppData\Local\ShuaBao\app-*`.
2. **Read Pointer**: Check `current.json` to identify the approved release folder.
3. **Verify Integrity**: Compare `ShuaBao.exe` SHA256 against `build_identity.json`.
4. **Launch & Handshake**: Launch child process with `--launcher-pid` and verify that the GUI main window renders within 15 seconds.
5. **Auto-Rollback**: If the new build crashes on boot (exit code != 0 or heartbeat missing), revert `current.json` to the prior working version.

### 3.2 Runtime Self-Reporting Contract
At application startup, `ShuaBao` must emit a structured log event and expose an HTTP/WebShell diagnostic endpoint:
```json
{
  "event": "RUNTIME_IDENTITY_HANDSHAKE",
  "source_sha": "3e9c50ab9dbf53b384e5460101f428e305d8db78",
  "build_id": "v0.3-g0-closure",
  "version": "0.3.0",
  "model_id": "rapid_ocr_v3_ch",
  "asset_id": "assets_vault_20260910",
  "running_pid": 14220,
  "canonical_repo_match": true
}
```
If `source_sha` in memory does not match `git rev-parse HEAD` during local development, a prominent warning badge is displayed on the UI.
