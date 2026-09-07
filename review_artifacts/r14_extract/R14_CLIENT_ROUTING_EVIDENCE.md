# ImageLab R14-9 — client routing evidence

Review-only. No authoritative product/static file was modified.

## Exact input

`R13_app_extract_snippet.txt` is the exact captured R13 client call and has Git blob SHA `e96f7dce1248942f62856c60a03e38c5e997d2dc`.

The R13 manual `mode=region` call still sends cutout-only controls:
`sensitivity`, `texture_reduction`, `reduce_fabric_texture`, `feather`, `crop_output`, `padding_mm`, and uses the success text `Принт извлечён в отдельный PNG`.

## Candidate

`R14_APP_EXTRACT_ROUTING.patch` changes only the Extract Print click handler:
- ROI coordinates + `strict_roi=true` are always sent for region mode;
- cutout-only controls are added only for `mode=auto`;
- explicit enabled four-point perspective remains routed for both modes;
- region success text becomes `Рабочий фрагмент создан`;
- auto success text and cutout controls remain unchanged.

Artifact hashes from the executed local review copy:

```text
R14_APP_EXTRACT_ROUTING.patch  c57289a243413e698fb25dc201d788ceedea1f67caac26faeae25799de3a4e07
R14_CLIENT_ROUTING_REGRESSION.js  7ede595d2d512afb1eeb369045f940787e6b294de7a234814d685aa7aea9146b
```

## Test

```text
node --check R14_CLIENT_ROUTING_REGRESSION.js
node R14_CLIENT_ROUTING_REGRESSION.js
R14_CLIENT_ROUTING_REGRESSION: 3/3 PASS
```

Cases:
1. region: no cutout-only key leaks, `strict_roi=true`, working-fragment message;
2. region + perspective: explicit four-point perspective retained, no cutout-only leak;
3. auto: all established cutout parameters and old success message retained.

Evidence ceiling: **L1**. This is a deterministic review harness, not a real packaged browser or installed Windows user path. Product R14-9 remains PARTIAL until the exact product client is patched and verified at source/package/installed levels.

FAIL-CLOSED
PROTOCOL_IMPLEMENTATION_INCOMPLETE
MILESTONE_NOT_COMPLETE
RELEASE_BLOCKED
