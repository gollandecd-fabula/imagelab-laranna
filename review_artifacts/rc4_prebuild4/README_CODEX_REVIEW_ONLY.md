# ImageLab RC4-PREBUILD4 — Codex review only

STATUS: REVIEW_ONLY / DO_NOT_MERGE / RELEASE_BLOCKED

This PR must contain only review artifacts. It does not apply PREBUILD4 to the authoritative ImageLab branch.

- local build: `A28-PROJECT-HARDEN-20260906-RC4-PREBUILD4`
- source-tree SHA-256: `3d5055966628e006b7e21462a427ecef31e1ac3687ba9e47f8249a624e496e71`
- source ZIP SHA-256: `95fa2076858d7c8b8f4c9c3fb6ddeb8e44e4c05f5500bf16ceab26530d547320`
- source files: 214
- tests: 423 = 418 PASS / 4 FAIL / 1 SKIP
- unresolved runtime deps: `psd_tools`, `pillow_heif`
- external real-camera HEIC user-path test: BLOCKED (fixture transport unavailable)

- GitHub review payload: `RC4_PREBUILD2_TO_PREBUILD4_COMBINED.patch`
- combined patch SHA-256: `ea248617d91b334db0cf9016138a10dbcfc71b8bf91640295ccf69f5ac7169c0`
- combined patch bytes: `85391`
- composition: exact concatenation of the 11 per-file patches in `PATCH_INDEX.json` order; local per-file patches remain evidence artifacts.

## Codex PREBUILD2 findings to re-check
1. P1 unsigned runtime receipt forgery — corrected by fresh rebuild from exact wheel bytes.
2. P1 forged source-test receipt — builder now runs full source gate internally.
3. P1 import shadowing — Python `-P` + verified-runtime origin enforcement.
4. P1 narrowed pytest collection — sanitized env + plugin autoload off + pinned 423-node manifest.
5. P1 TOCTOU live source — test/build from a private snapshot + post-build source/runtime recheck and cleanup.
6. P2 HEIF user path — NOT CLOSED; external hash-pinned real HEIC fixture still unavailable to the local runtime.

Audit for bypasses, regressions, symlink/ZIP issues, receipt replay, collection-manifest weaknesses, snapshot mutation, and claims exceeding evidence. Do not modify product code or merge.

FAIL-CLOSED
PROTOCOL_IMPLEMENTATION_INCOMPLETE
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
