# ImageLab RC4 PREBUILD6-R1 — FINAL CODEX REVIEW ONLY

DO NOT MERGE. DO NOT MODIFY PRODUCT SOURCE. DO NOT AUTHORIZE RELEASE.

Exact local source under review:
- build_id: `A28-PROJECT-HARDEN-20260906-RC4-PREBUILD6-R1`
- source-tree SHA-256: `8f5b45292612a1ba12857b6c2fbcd62306dc539125fa169270cf946496f4a4e9`
- source files: 215
- pinned tests: 428/428 PASS, 0 FAIL, 0 ERROR, 0 SKIP
- verified runtime tree: `6b14436f3ed63349592f073369d72f2d128474843b4e03b9a93a3ca022b90827`
- reproducibility: A/B installer byte-equal and source ZIP byte-equal
- installer SHA-256: `ca5d259d22038ab2752355f20ca448d784a3e4ecdc158c0140dedd668329281f`
- source ZIP SHA-256: `945d665c5a5e93b9fd198690d1dffa4aa9512e468277813c772c54560505a464`
- packaged self-test: PASS for EPS import, resize/PPI, background, halftone, vector, history/lineage, PNG export.

## Full-source delivery
`chunks/part-01.b64` ... `part-08.b64` concatenate to base64 of a deterministic XZ-compressed TAR containing all 205 UTF-8 source/test/build files. Decode with:

```bash
cat review_artifacts/rc4_prebuild6_r1/chunks/part-*.b64 | base64 -d > /tmp/prebuild6-r1.tar.xz
sha256sum /tmp/prebuild6-r1.tar.xz
mkdir -p /tmp/prebuild6-r1 && tar -xJf /tmp/prebuild6-r1.tar.xz -C /tmp/prebuild6-r1
```

Expected XZ SHA-256: `6f39c31d7ed216615a85a6a4b480e45def4f5abcd38d2a7438b168c2261c043b`.
Ten non-UTF8 objects are enumerated by exact path/size/SHA in `BINARY_OBJECTS.json`.
Critical release files are also duplicated in `critical/` for immediate review.

## Review scope — P0/P1 only
Review the exact delivered code for release-blocking issues only:
1. source mutation / TOCTOU around test gate, build and promotion;
2. Python path/sitecustomize/plugin/collection bypass;
3. forged/replayed dependency or source receipts;
4. exact-wheel/runtime substitution or unsafe archive extraction;
5. publishing candidate artifacts before final validation;
6. Go build reproducibility change (stable GOPATH import path);
7. installer extraction/update/rollback issues that could cause code execution, data loss, or unusable install;
8. any other concrete P0/P1 affecting a local single-user ImageLab release.

Do NOT block on P2/P3, style, refactoring, theoretical hardening, documentation, or additional nice-to-have tests. Do NOT treat GitHub evidence as physical L5.

Required final answer: exact head SHA reviewed; `P0=<n>, P1=<n>`; concise concrete findings with file/line; and either `RELEASE_BLOCKING_FINDINGS_PRESENT` or `NO_P0_P1_FOUND`.
