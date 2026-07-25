# ImageLab by LarannA — Genesis Release Gate Change Register

Date: 2026-07-25  
Mode: PROTOCOL LOCK / FAIL-CLOSED  
Status: USER-APPROVED SPECIFICATION CHANGE

## User authorization

The product owner explicitly authorized the following rule:

> Разрешаю одноразовый Genesis Release Gate для первого официального релиза ImageLab. Первый установщик может получить статус GENESIS_RELEASE_AUTHORIZED после прохождения всех остальных обязательных проверок и физического L5. После этого он становится обязательным baseline для G6/G7 всех последующих релизов. Запрещено ослаблять G6/G7 для последующих версий.

## Problem being corrected

The original G6 contract requires a previous externally authorized release. ImageLab has never had an official `RELEASE_AUTHORIZED` installer and prior-finalizer authorization record, so the first release cannot satisfy G6 without circular self-authorization or fabricated history. Both are forbidden.

## Approved one-time rule

1. Genesis mode is allowed only when no prior ImageLab `RELEASE_AUTHORIZED` or `GENESIS_RELEASE_AUTHORIZED` release exists.
2. Genesis mode may bypass only the requirement to update from a previous authorized baseline. It does not bypass or weaken any other gate.
3. The exact first installer may receive `GENESIS_RELEASE_AUTHORIZED` only after:
   - G0–G5 and G8 are PASS for the exact installer;
   - G7 rollback mechanism is PASS using an explicitly non-authorizing diagnostic baseline where required by the first-release condition;
   - all required evidence is present, valid, internally consistent and bound to the exact source and installer SHA-256;
   - physical user-machine L5 is genuinely completed and independently SHA-pinned;
   - the complete red-team audit is closed with no unresolved P0/P1 defect;
   - no previous authorized release is found in the supplied release-history evidence.
4. Genesis mode must emit a distinct status and record: `GENESIS_RELEASE_AUTHORIZED` and `ImageLab-GENESIS-RELEASE-AUTHORIZATION.json`.
5. The Genesis authorization record must bind the exact installer, source, version, Build ID, install ID, physical-L5 record, final verdict and evidence archive hashes.
6. Once a Genesis release exists, Genesis mode is permanently unavailable. Every later release must satisfy normal G6/G7 using the Genesis release or a later normal authorized release as the externally pinned baseline.
7. A normal release must never accept a diagnostic, recovery-candidate, filename-only claim, operator boolean or the current candidate as its own baseline.
8. Missing, malformed, stale, contradictory or duplicate Genesis evidence produces non-zero exit and `RELEASE_BLOCKED`.

## Required implementation surfaces

- `release_gate/finalize_gate.py`;
- active root/source release workflows;
- `ZERO_TRUST_RELEASE_GATE_RTM_V1.md`;
- `ZERO_TRUST_RELEASE_GATE_RUNBOOK_V1.md`;
- change register and implementation report;
- positive parser/contract tests and adversarial negative tests;
- current-state/evidence index where applicable.

## Mandatory negative tests

Genesis authorization must fail when:

- a previous authorized or Genesis release exists;
- release-history evidence is missing, malformed, unpinned or contradictory;
- the current installer is reused as its own baseline;
- any G0–G5, G7 or G8 evidence is missing or failed;
- physical L5 is absent, hosted, stale, mismatched or not directly witnessed;
- source, installer, version, Build ID or install ID mismatches;
- an ordinary `RELEASE_AUTHORIZED` record is emitted in Genesis mode;
- Genesis mode is requested for a second or later release;
- an authorized output from an earlier failed run remains on disk.

## Release state after this change

This authorization changes the specification only. It does not itself authorize any installer, satisfy physical L5, close the full audit, or publish a release.

`FAIL-CLOSED`  
`PROTOCOL_IMPLEMENTATION_INCOMPLETE`  
`MILESTONE_NOT_COMPLETE`  
`RELEASE_BLOCKED`
