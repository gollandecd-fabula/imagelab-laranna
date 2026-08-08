# ImageLab by LarannA — Codex instructions

## Project map

- Active recovery branch: `bootstrap/zero-trust-gate`.
- Active PR: `#2`, draft, unmerged, release blocked.
- Application source: `recovery/source/`.
- Release RTM: `recovery/source/docs/ZERO_TRUST_RELEASE_GATE_RTM_V1.md`.
- Release runbook: `recovery/source/docs/ZERO_TRUST_RELEASE_GATE_RUNBOOK_V1.md`.
- Current hosted Windows evidence: `recovery/evidence/windows-gate/rc13-windows-evidence-summary.json`.
- Update/rollback diagnostic: `recovery/evidence/update-rollback/diagnostic-update-rollback-148-149-summary.json`.
- G6 blocker: `recovery/evidence/update-rollback/g6-authorized-baseline-blocker.json`.
- Collaboration plan: `recovery/source/docs/CODEX_COLLABORATION_PLAN_V1.md`.

## Binding constraints

1. The selected technical specification and RTM are executable requirements. Do not weaken, reinterpret, merge, skip, or silently replace requirements.
2. Work fail-closed. A missing, malformed, skipped, stale, or contradictory check is a failure, not a pass.
3. Never fabricate or retroactively label a prior installer as `RELEASE_AUTHORIZED`.
4. Never publish an installer, merge PR #2, modify `main`, or claim release authorization while any required gate remains blocked.
5. Do not use the current candidate as its own G6 baseline.
6. Physical user-machine L5 evidence cannot be replaced by GitHub-hosted runners or simulated evidence.
7. Claims must not exceed evidence. Report exact PASS, FAIL, BLOCKED, and NOT VERIFIED states.
8. Do not add text-to-image generation. ImageLab processes uploaded images only.
9. Keep physical dimensions in millimetres and edge softness in pixels. Do not add an mm/cm toggle.
10. Preserve separate operations for background removal and print extraction.

## Current exact candidate

- Version: `1.4.9-recovery-candidate`.
- Build ID: `REC-RT8-M6-20260724-06`.
- Source SHA-256: `83bcfcc9e9d6dfaa29ef2827f3a967d9719cbff2650672b7d5d9d3eac1af4885`.
- Windows installer SHA-256: `12817550c2fac6a6453945c38eefe86368cd4cfa1991c1565e49b092bd818d56`.
- Hosted gates B0–B5 and B8: verified PASS by the current evidence summary.
- G6 authorizing baseline: unavailable.
- Physical user-machine L5: not verified.
- Final state: `RELEASE_BLOCKED`.

## Codex task workflow

1. Read this file, the relevant RTM rows, the runbook, and current evidence before editing.
2. State the exact requirement IDs and PASS criteria affected by the task.
3. Use one focused task per branch/worktree. Preferred branch prefix: `codex/imagelab-`.
4. Make the smallest patch that satisfies the assigned requirement. Avoid architecture rewrites.
5. Add or update automated tests for every behavioral change.
6. Run the relevant focused tests, then the complete source test suite and release self-test when applicable.
7. Produce evidence with exact commands, outputs, hashes, and remaining limitations.
8. Open a draft PR only. Do not merge it.
9. Request independent review from the ChatGPT technical lead before any promotion into the recovery branch.

## Role boundaries

- Codex implementation agent: code, tests, focused documentation, and reproducible evidence.
- Codex red-team agent: independent review of the implementation PR; it must not reuse the implementation agent's conclusions as evidence.
- ChatGPT technical lead: RTM ownership, task decomposition, GitHub Actions analysis, evidence review, integration decision, and release-state reporting.
- Dmitry / product owner: approves material specification changes, performs or directly witnesses physical Windows L5, and makes the final release decision.
- GitHub Actions: automated execution environment only; it cannot authorize physical L5 or invent an authorized historical baseline.

## Stop conditions

Stop and report `BLOCKED` rather than improvising when:

- a task requires changing the selected specification;
- the required source, secret, device, prior authorized installer, or external evidence is absent;
- a proposed patch weakens a gate or changes its PASS criterion;
- test or evidence results are inconsistent;
- the task would publish, merge, or release a blocked candidate.
