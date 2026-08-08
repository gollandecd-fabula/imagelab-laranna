# ImageLab Zero-Trust Release Gate — Implementation Report v1

Date: 2026-07-24  
Build identity: `1.4.2-zero-trust-candidate` / `ZTR-M6-20260724-01`

## Implemented release path

```text
manual workflow start
→ G0 source/identity/backend self-test
→ G1 18 isolated test-file jobs
→ G2 two byte-identical Windows installer builds
→ G3 exact EXE clean Windows install
→ G4 Microsoft Edge UI path with Playwright trace/video/screenshots
→ G5 generated PNG/SVG/lineage validation
→ G6 update from externally SHA-pinned previous authorized installer
→ G7 forced failure and rollback with project-data preservation
→ G8 independent reinstall and bundled-Chromium rerun
→ fail-closed finalizer
→ authorized artifact only on complete PASS
```

## Main protections

- The internal candidate is uploaded under `UNVERIFIED_INTERNAL_EXACT_CANDIDATE` and cannot be confused with an authorized release.
- Every downstream Windows job receives the same candidate artifact and validates its SHA-256.
- The installer runs production-service self-tests both before promotion and after installation.
- CI mode prevents the installer from opening an unmanaged browser window.
- Every unit test file executes in an isolated process. A missing result is a failure, not a skip.
- The update test uses a real previous release downloaded by tag and externally pinned SHA-256. The baseline must differ from the candidate.
- Existing project data is checked with a sentinel through update and rollback.
- The final verdict job runs even when earlier jobs fail and produces `ImageLab-RELEASE-VERDICT`.
- `ImageLab-RELEASE-AUTHORIZED` is uploaded only when the finalizer exits successfully.
- A blocked run never creates an authorized EXE copy.

## Local verification

| Gate | Result |
|---|---|
| G0 source/identity/backend | PASS |
| G1 isolated unit matrix | 18/18 test files PASS |
| G2 candidate package | PASS |
| G2 deterministic rebuild | installer and source ZIP byte-identical across two builds |
| Missing-evidence negative test | `RELEASE_BLOCKED`, no authorized EXE |
| G3–G8 | NOT EXECUTED — require GitHub Windows runners and prior authorized baseline release |

Local exact candidate SHA-256 used only for reproducibility testing:

`7f3a48ee595d8435ef5c64b9c0fcf73cd9ce669179f999c4dae67ee5cfea3474`

This candidate is not authorized for distribution because G3–G8 have not run.

## Required operation

1. Push the source package to a private GitHub repository.
2. Attach the previous authorized installer to a GitHub Release.
3. Record its SHA-256 independently.
4. Manually run `ImageLab Zero-Trust Release Gate` with the release tag and pinned SHA.
5. Distribute only the `ImageLab-RELEASE-AUTHORIZED` artifact.

## Evidence boundary

Maximum current evidence: **L3 local packaged build**.

No claim is made that the current installer has passed clean Windows installation, installed Edge interaction, real update, rollback or independent Windows verification.
