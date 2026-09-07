# ImageLab R14 composite source rehearsal evidence

Review-only compatibility evidence. This does not establish a full exact-R13 product tree, packaged L3, installed L4, physical L5, milestone completion, or release readiness.

## Baseline identity gate

The applicator accepts only the tested PREBUILD6 source baseline for the four affected surrounding files:

| Path | required baseline SHA-256 | required final R14 SHA-256 |
|---|---|---|
| `app/services/extract_fidelity.py` | `5051f1ee2dde767cc5ab1b2f884fba4e5fa0bf8c9d11d5e10a1eb836b260a44f` | `a5576f436874d9da6e460d96e2bdc1b80f0bec8dc9139f61b58fd7e8d543b73c` |
| `app/services/qa_service.py` | `eba31662dfb3e0fcded0673fdb4e949f2e419d8cddbbadff548d660254aee062` | `c1d12ae55467c664e0a26459cba05535b5c866b01ac15e90886e9f51755dd10a` |
| `app/services/repair_service.py` | `084f682b3bf279bf13d27c85c33ba6d8c3a92854a7479d153a6e9e3a1689b97f` | `a28023a8625f45a0f7cf014194255d12c5c3141d9b783977bcf23f70007f9533` |
| `app/static/app.js` | `b84c7665be2e819cb12a83316d01b891a17e3b627aa3b7f995696375e00ccfb7` | `2e4d2d2f554e0e48de23835cd9a56f2956e2f0a2123e501a9c104878abd19997` |

`extract_fidelity.py` is not patched from the PREBUILD6 implementation. The applicator first verifies that PREBUILD6 baseline, then reconstructs exact R13 extraction source SHA-256 `60763e3b70142b334445d68c5ec82d83a14cf717e13b1e35c842faa559e9b991` from the three committed R13 fragments and derives R14 with the hash-gated R14 patcher.

## Fresh source application

A new directory was extracted from the retained PREBUILD6 source ZIP and the applicator was executed once.

```text
R14_COMPOSITE_APPLY: PASS
app/services/extract_fidelity.py a5576f436874d9da6e460d96e2bdc1b80f0bec8dc9139f61b58fd7e8d543b73c
app/services/qa_service.py c1d12ae55467c664e0a26459cba05535b5c866b01ac15e90886e9f51755dd10a
app/services/repair_service.py a28023a8625f45a0f7cf014194255d12c5c3141d9b783977bcf23f70007f9533
app/static/app.js 2e4d2d2f554e0e48de23835cd9a56f2956e2f0a2123e501a9c104878abd19997
```

A second application against the already modified tree returned exit code `2` and failed closed on the first baseline SHA mismatch. This proves the applicator is not a fuzzy/idempotent patch that can silently consume an unknown source state.

## Fresh-tree source runtime checks

On that newly constructed source tree:

```text
R14 exact composite E2E: 5/5 PASS
R14 working-fragment QA: 5/5 PASS
```

The E2E path covers exact manual ROI pixel preservation, destructive-path spies, plain ROI, QA, `Extract -> Improve -> Remove Background`, and unchanged auto execution.

## Immutable delta

After removing test-only `.pytest_cache` and temporary copied test files, a byte-level comparison of PREBUILD6 source against the rehearsal tree reported:

```text
CHANGED 4
app/services/extract_fidelity.py
app/services/qa_service.py
app/services/repair_service.py
app/static/app.js
ADDED 0
REMOVED 0
```

The zero-trust builder `compute_source_tree()` reports the R14 rehearsal source tree as:

```json
{"sha256":"b992edd8afae7c568c901078b1e5e0180c96050b45d1ea45c58c4b7b5197a709","file_count":215}
```

## Package capability gate

The actual retained `l3_dependency_intake.py` was run with a clean wheel cache. It returned exit code `2`:

```json
{
  "status": "BLOCKED",
  "error": "exact wheel missing: .../pillow_heif-1.6.0-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
}
```

The intake itself pins the missing file to SHA-256 `1629b5d5aaf484d5901297be024228abf8182c671e6c31dbbadf280faf1115c2` and also requires `psd_tools-1.19.0-cp313-abi3-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl` SHA-256 `36e9057f6c1e8e1092b83b6974f221577d8df0e49455f50cebaeca61bcbb4c69`. No substitute version/file is accepted.

## Evidence status

- Composite apply/reapply gates: L1/L2 compatibility evidence.
- Fresh real API E2E/QA: compatibility source-runtime L2.
- Exact full R13 product-tree provenance: UNVERIFIED.
- Exact R14 packaged runtime: BLOCKED at dependency/full-tree gates.
- Installed Windows: NOT_STARTED.
- Physical user path: NOT_STARTED.

FAIL-CLOSED
PROTOCOL_IMPLEMENTATION_INCOMPLETE
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
