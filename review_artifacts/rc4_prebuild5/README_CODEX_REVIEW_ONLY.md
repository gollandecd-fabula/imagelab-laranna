# ImageLab RC4-PREBUILD5 — CODEX REVIEW ONLY / DO NOT MERGE

This review container does **not** apply local ImageLab source to the authoritative product branch.

Exact local identity:
- build: `A28-PROJECT-HARDEN-20260906-RC4-PREBUILD5`
- source-tree: `95b7c2d2bfd104500d794ada51940aaccbd7e8e3494d51abf3ac14d5fb2bdb9e`
- source files: `215`
- pinned pytest collection: `428` nodeids
- collection manifest SHA-256: `766043a9e1516ae80fefd61f2af37354c35525e9908d4ec0f301890c0f9c9e38`

## Full-source review payload
PREBUILD4 Codex correctly rejected an 11-file-only delta as insufficient to prove the local tree. PREBUILD5 therefore provides:
1. all **205 UTF-8 release-relevant source/test/build files** losslessly in a deterministic tar.xz, base64-split under `source_bundle_chunks/`;
2. `PREBUILD5_BINARY_OBJECTS.json` binding the remaining **10 binary release-relevant objects** by path/size/SHA-256/Git-blob SHA-1;
3. `VERIFY_PREBUILD5_REVIEW_PAYLOAD.py`, which reconstructs the exact 215-entry source-tree digest and must print the exact target SHA above;
4. critical hardening files duplicated unencoded under `critical/` for direct review.

This fixes the *review-payload* P1 without pretending the 10 binary objects are source code. Binary dependencies remain subject to their own dependency/supply-chain gates.

## PREBUILD4 findings that PREBUILD5 must re-audit
- P1: mutation of source during pytest gate → pre-gate tree is bound through gate and checked post-pytest.
- P1: inherited PYTHONPATH/sitecustomize → Python/pytest startup vars are discarded; isolated `-I -S` bootstrap uses explicit verified paths.
- P1: incomplete full-source review payload → addressed by this full UTF-8 bundle + binary manifest + verifier.
- P2: final output visible before post-build validation → candidate is built in private staging and atomically promoted only after final checks.
- Existing HEIC independent real-user-path P2 remains OPEN.

No installer was built from PREBUILD5. L3 is not established. L4/L5 are not started. GitHub/Codex evidence is never physical L5.

FAIL-CLOSED
PROTOCOL_IMPLEMENTATION_INCOMPLETE
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
