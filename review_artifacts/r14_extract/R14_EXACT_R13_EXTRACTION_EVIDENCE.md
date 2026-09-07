# ImageLab R14 — exact R13 extraction / compatibility source-runtime evidence

Review-only. No authoritative product path, accepted R12 module, CI, packaging, installer, release metadata or merge state was changed.

## Exact R13 identity and deterministic patch

The three committed R13 source fragments were concatenated byte-for-byte:

- `R13_extract_fidelity.part01.py.txt` — 7,947 bytes
- `R13_extract_fidelity.part02.py.txt` — 9,149 bytes
- `R13_extract_fidelity.part03.py.txt` — 4,580 bytes
- reconstructed size — 21,676 bytes
- reconstructed SHA-256 — `60763e3b70142b334445d68c5ec82d83a14cf717e13b1e35c842faa559e9b991`

This exactly matches `EXPECTED_R13_SHA256` in `R14_APPLY_TO_EXACT_R13.py`.

The hash-gated patcher was executed against those exact bytes. It accepted the input and produced:

- R14 extraction candidate size — 19,232 bytes
- candidate SHA-256 — `a5576f436874d9da6e460d96e2bdc1b80f0bec8dc9139f61b58fd7e8d543b73c`
- `python -m py_compile` — PASS

This advances the extraction implementation itself beyond the previous L0 patcher-only state. It does **not** prove that every surrounding R13 product file is exact, because the full R13 source tree is not available.

## Compatibility source-runtime integration

The exact R13-derived R14 extraction candidate was installed only into an isolated PREBUILD6 recovery/reference scaffold. The already-reviewed R14 QA/repair/client semantic changes were present there. Current composite hashes:

```text
a5576f436874d9da6e460d96e2bdc1b80f0bec8dc9139f61b58fd7e8d543b73c  app/services/extract_fidelity.py
c1d12ae55467c664e0a26459cba05535b5c866b01ac15e90886e9f51755dd10a  app/services/qa_service.py
a28023a8625f45a0f7cf014194255d12c5c3141d9b783977bcf23f70007f9533  app/services/repair_service.py
2e4d2d2f554e0e48de23835cd9a56f2956e2f0a2123e501a9c104878abd19997  app/static/app.js
```

`R14_EXACT_COMPOSITE_E2E.py` SHA-256: `1b48a867696b8523aeb6f9e52f19e11f6cea264f760236d728ff82987f9449e3`.

## Repeated executable control set

```text
pytest -q tests/test_r14_exact_composite_e2e.py
..... [100%]                         5/5 PASS

pytest -q tests/test_r14_working_fragment_qa_candidate.py
..... [100%]                         5/5 PASS

pytest -q tests/test_print_extraction.py::test_extract_print_auto_mode_and_identity_perspective tests/test_m2b_extract.py
........ [100%]                      8/8 PASS

pytest -q tests/test_browser_user_recheck_20260901.py
...... [100%]                        6/6 PASS

R14_CLIENT_ROUTING_REGRESSION
3/3 PASS
```

The 5-test real API composite proves on the isolated source runtime:

1. manual ROI is pixel-equal to the selected RGB/RGBA rectangle when no geometry transform is applied;
2. old destructive controls may be supplied but are ignored by the manual working-fragment server branch;
3. spies prove `segment_print`, legacy auto fallback and alpha-silhouette dewarp are not called for manual region;
4. a plain selected region is valid because F03 manual region is now a working-fragment crop, not a print detector;
5. QA accepts working-fragment semantics without the old cutout/transparency requirement;
6. the real API chain `Extract -> Improve -> Remove Background` executes with correct source lineage;
7. the auto extraction branch still executes.

## Superseded old-contract tests

Three existing assertions in the old `test_print_extraction.py` manual-region cases fail because they explicitly require the former cutout semantics: transparent coverage <= 0.88, rejection of a plain selected region, and QA code `print_coverage`. They conflict with the binding R14 working-fragment requirement and are recorded as superseded expectations, not hidden or rewritten into a false PASS. The unchanged auto test in the same file passes.

## Wider regression evidence

The compatibility composite was exercised in completed split groups across core, M2B/M2C, background, QA, project hardening/recovery, project store/concurrency, red-team/segmentation governance, storage/package-integrity contracts, upload/user-recheck, Windows packaging configuration, zero-trust gate contracts, and browser M1/M2A/closure/matrix/project/RTM/export/real-API-curtain/user-recheck suites. Completed split groups were PASS. Monolithic runs that hit execution timeout are **not** counted as PASS.

Two Linux-scaffold dependency-only blockers remain separate from R14 logic:

- PSD/PSB tests require pinned `psd_tools` runtime bytes not present in the generic container;
- HEIF test requires pinned `pillow_heif` runtime bytes not present in the generic container.

The prior PREBUILD6 release evidence recorded a verified 85-file runtime SHA-256 `6b14436f3ed63349592f073369d72f2d128474843b4e03b9a93a3ca022b90827`, but those runtime bytes are no longer present in the current workspace.

The current `scripts/l3_dependency_intake.py` is fail-closed and pins:

```text
pillow_heif-1.6.0-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl
SHA-256 1629b5d5aaf484d5901297be024228abf8182c671e6c31dbbadf280faf1115c2

psd_tools-1.19.0-cp313-abi3-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl
SHA-256 36e9057f6c1e8e1092b83b6974f221577d8df0e49455f50cebaeca61bcbb4c69
```

Running intake with the current empty pinned-wheel cache returns exit code 2 and `status: BLOCKED` at the first missing exact wheel. No alternate version is accepted.

## Evidence ceiling / unresolved provenance

- Exact R13 extraction bytes -> deterministic R14 extraction patch: executable evidence established.
- F03 behavior in an isolated ImageLab source runtime with real API: compatibility/source-runtime **L2**.
- QA/repair/client surrounding files: compatibility L2/L1 only; full exact-R13 provenance for those surrounding files is still unavailable.
- Final exact-R13 product-tree L2: **not claimed**.
- Packaged R14 L3: **not claimed**.
- Installed Windows L4: **not started**.
- Physical user path L5: **not started**.

FAIL-CLOSED
PROTOCOL_IMPLEMENTATION_INCOMPLETE
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
