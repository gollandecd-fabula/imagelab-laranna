# ImageLab R14 current RTM

| ID | Milestone | Requirement | Action | Test | Evidence | Artifact | PASS criterion | Actual status |
|---|---|---|---|---|---:|---|---|---|
| R14-0 | Boundary | Accepted R12 modules frozen | Scope-only review changes | Changed-path audit | L0 | PR diff | no product/R12 change | VERIFIED |
| R14-1 | F03 ROI | Manual ROI hard rectangular boundary | working-fragment branch | pixel/bounds/API | L1 + compatibility runtime | R14 extract candidate/tests | exact ROI; no outside pixels | PARTIAL |
| R14-2 | F03 Fragment | Preserve fabric/background/RGBA | non-destructive crop | RGB/RGBA equality | L1 + compatibility runtime | extract regression | source pixels/alpha preserved | PARTIAL |
| R14-3 | F03 No segmentation | No default segmentation/removal/fallback | hard manual branch | spies/branch/API | L1 + compatibility runtime | extract regression | no segment/remove/fallback | PARTIAL |
| R14-4 | F03 Perspective | Explicit valid 4-point perspective remains | validate/apply explicit transform | identity/non-identity/invalid | L1 + compatibility runtime | extract regression | valid applies; invalid fail-closed | PARTIAL |
| R14-5 | F03 Dewarp | Alpha silhouette cannot auto-dewarp | disable from manual path | negative straighten | L1 + compatibility runtime | extract regression | silhouette never changes manual geometry | PARTIAL |
| R14-6 | F03 Alignment | No guessed alignment | fail closed to unchanged ROI | no-confidence/no-op | L1 | diagnostics/tests | unproved correction is no-op | PARTIAL |
| R14-7 | F03->F04 | Extract, Improve, Remove Background remain distinct | preserve pipeline separation | API chain | compatibility runtime | chain regression | F03 preserves data; F04 removes bg | PARTIAL |
| R14-8 | Diagnostics | Diagnostics/QA truthfully expose working-fragment semantics | explicit semantic contract | API QA | L1 + compatibility runtime | R14 QA evidence | no ambiguous cutout claims | PARTIAL |
| R14-9 | Client | Manual UI routes strict region working-fragment path | split region vs auto request parameters | exact snippet + Node routing harness | L1 | R14_APP_EXTRACT_ROUTING.patch + R14_CLIENT_ROUTING_EVIDENCE.md | region sends ROI/strict/perspective only; auto cutout controls unchanged | PARTIAL — product/browser runtime not patched |
| R14-10 | Regression | Focused + neighboring regressions | deterministic regression sets | custom/focused/broad/full | L1 + compatibility runtime | test logs | no R14 regression; full suite clean | PARTIAL — full suite scaffold-blocked |
| R14-11 | Packaging | R14 exact packaged runtime | build/package exact verified source | packaged E2E | — | package evidence | R14 code executes in package | NOT_STARTED |
| R14-12 | Installed | Installed Windows runtime | install exact package | installed tests | — | installed evidence | installed path works | NOT_STARTED |
| R14-13 | Physical | Physical user path | user tests real image | manual physical | — | user evidence | expected visual behavior | NOT_STARTED |
| R14-14 | QA boundary | Working fragment must not be rejected/repaired as cutout | semantic QA + manual repair guard | direct QA + FastAPI + auto regression | L1 + compatibility runtime | R14 QA patch/tests/evidence | correct working fragment accepted; bad contract blocked; auto unchanged | PARTIAL — exact R13 QA provenance UNVERIFIED |

No milestone/release completion is claimed while any row is PARTIAL, UNVERIFIED, NOT_STARTED, FAILED, or BLOCKED.

FAIL-CLOSED
PROTOCOL_IMPLEMENTATION_INCOMPLETE
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
