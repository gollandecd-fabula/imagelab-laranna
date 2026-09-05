# ImageLab RC4-PREBUILD2 — Codex review-only snapshot

STATUS: REVIEW_ONLY / DO_NOT_MERGE / NO_PRODUCT_MUTATION / RELEASE_BLOCKED

This directory is an **external review artifact**, not authoritative ImageLab source. It was generated from the locally verified recovery checkpoint and is placed on a separate GitHub branch only so Codex can audit the exact local delta without merging it into the authoritative line.

## Identity
- Authoritative GitHub base PR: #11
- Base head used for review branch: `7db657da93ad04326fe76a24829c856b1fc0af21`
- Local build id: `A28-PROJECT-HARDEN-20260905-RC4-PREBUILD2`
- Local source-tree SHA-256: `17805176058d7b2e662690a5794d2209c74c4834fcaed4357df38737d57e1c56`
- Local source ZIP SHA-256: `31c3696c0efce52bd99e84f1bc5b9f3bf68e71906c8b9dc75c726918c3d7c3ce`
- Local PREBUILD2 vs PREBUILD changed files: 9

## Exact local test state
- Total: 416
- PASS: 411
- FAIL: 4
- SKIP: 1
- Browser: 33/33 PASS
- Independent non-browser: 372/372 PASS
- PSD/PSB dependency group: 6 PASS / 3 FAIL / 1 SKIP; cause `psd_tools` missing
- HEIF E2E: 1 FAIL; cause `pillow_heif` missing
- Other failures: 0
- Installer built: NO
- L3: NOT ESTABLISHED
- L4: NOT STARTED
- L5: NOT STARTED
- release_authorization: false

## What Codex must review
1. Prebuild capability gate occurs before any build/output mutation.
2. Exact dependency intake binds filename + SHA-256 + METADATA Name/Version.
3. Verified runtime cannot be forged with JSON only; exact wheel bytes are re-hashed.
4. Full source-test receipt is required before build and binds source tree + verified runtime.
5. Source-tree binding covers release-relevant paths and excludes only explicit generated/cache/data/build/evidence paths.
6. Verified runtime is forbidden inside source root to prevent self-referential hashing.
7. HEIF E2E test is real and correctly remains fail-closed when `pillow_heif` is absent.
8. No old evidence is transferred to changed source identity.
9. No GitHub/Codex/CI result may be called physical L5.
10. Review whether the local delta has any bypass, TOCTOU, path traversal, hash-scope, receipt-forgery, or build-order weakness.

## Files in this review artifact
- `PATCH_INDEX.json` + `patches/*.patch` — byte-bound per-file unified patches for all 9 local changes.
- `RC4_PREBUILD2_CHANGED_FILES.json` — per-file before/after SHA and size.
- `A28_RC4_PREBUILD2_EVIDENCE.json` — local fail-closed evidence summary.
- `RC4_PREBUILD2_TEST_SUMMARY.json` — exact local test classification.

Do not modify product code from this PR. Do not merge this PR. Report findings only.

FAIL-CLOSED
PROTOCOL_IMPLEMENTATION_INCOMPLETE
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
