# Zero-Trust Release Gate — Change Register v1

Date: 2026-07-24

| Change ID | Milestone | Implemented change | Test/evidence | Rollback | Status |
|---|---|---|---|---|---|
| ZTR-C001 | ZTR-M0 | Added isolated unit-case runner, complete matrix verdict and comprehensive fail-closed finalizer | `tests/test_zero_trust_release_gate.py`; missing-case negative test | Remove `release_gate/run_unit_case.py` and verdict scripts | IMPLEMENTED / L1 VERIFIED |
| ZTR-C002 | ZTR-M1 | Added deterministic production-service self-test and pre/post-promotion installer execution | Local `app.release_selftest`; source gate | Revert self-test module and installer calls | IMPLEMENTED; WINDOWS EXECUTION PENDING |
| ZTR-C003 | ZTR-M2 | Added deterministic candidate builder, required payload validation and double-build byte identity check | Two local builds produced identical installer SHA | Revert build script | IMPLEMENTED / L3 LOCAL VERIFIED |
| ZTR-C004 | ZTR-M3 | Added clean Windows installation harness with exact version/build/install-ID verification | PowerShell harness static tests | Remove clean-install job and script | IMPLEMENTED / NOT EXECUTED |
| ZTR-C005 | ZTR-M4 | Added Playwright UI path, Edge coverage, independent Chromium path, traces/video/screenshots and output validators | Python compilation and static tests | Remove UI/output gate files | IMPLEMENTED / NOT EXECUTED |
| ZTR-C006 | ZTR-M5 | Added externally pinned real baseline installer, running-version update, project-data sentinel and forced rollback | Static and workflow tests | Remove baseline/update/fault-injection path | IMPLEMENTED / NOT EXECUTED |
| ZTR-C007 | ZTR-M6 | Added independent verifier, always-produced release verdict/evidence and conditional authorized artifact | Finalizer negative test and workflow tests | Remove final aggregation job | IMPLEMENTED; WINDOWS CI PENDING |
| ZTR-C008 | ZTR-M6 | Installer CI mode now suppresses external browser and uses exact health checks; visible log stages corrected to 11 | Go source tests and deterministic rebuild | Revert installer environment/log changes | IMPLEMENTED / L3 LOCAL VERIFIED |
