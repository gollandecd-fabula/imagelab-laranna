# ImageLab bootstrap source bundle

Эта папка используется только для первоначального запуска Windows Zero-Trust Gate.

## Exact source identity

Для текущего recovery-цикла разрешён только один исходный пакет:

- файл: `imagelab-source.zip`;
- версия: `1.4.9-recovery-candidate`;
- Build ID: `REC-RT8-M6-20260724-06`;
- SHA-256: `83bcfcc9e9d6dfaa29ef2827f3a967d9719cbff2650672b7d5d9d3eac1af4885`;
- размер: `378975` bytes;
- entries: `87`;
- canonical provenance: `recovery/dist/ImageLab_by_LarannA_RECOVERY_1.4.9_SOURCE.zip`;
- promotion commit: `87dfdb2f1c37359028320a2df3b055baf9a03b1f`.

`bootstrap/imagelab-source.zip` и `recovery/dist/ImageLab_by_LarannA_RECOVERY_1.4.9_SOURCE.zip` являются одним и тем же Git blob `31ca6f0643b4b769ce99c6edeeb2bc98f1caafd6`.

Файл `imagelab-source.sha256` закрепляет тот же SHA-256. Совпадение только с checksum-файлом недостаточно: B0 независимо проверяет ожидаемый SHA-256, версию, Build ID, CRC, безопасные пути архива, обязательные файлы и privacy denylist.

## Canonical-source evidence

Текущая source identity подтверждена следующими независимыми артефактами:

- `recovery/dist/source-manifest-1.4.9.json` — reproducible source bundle `2/2 BYTE_IDENTICAL`;
- `recovery/evidence/bootstrap-promotion-1.4.9/admission.json` — intentional 1.4.9 → bootstrap promotion, expected SHA = actual SHA;
- `recovery/evidence/windows-gate/rc13-windows-evidence-summary.json` — hosted B0/B1/B2/B3-B5/B8 PASS для source SHA `83bc...4885`;
- `recovery/evidence/windows-gate/bootstrap-canonical-source-pin.json` — текущая синхронизированная canonical-source pinning запись.

Исторические evidence-файлы не переписываются для подгонки нового кандидата.

## Проверки bootstrap

Workflow выполняет:

- B0: точный SHA-256, CRC, безопасные пути, denylist, version/build identity;
- B1: обязательный Source Gate и критические изолированные regression tests;
- B2: две воспроизводимые Windows-сборки и manifest identity;
- B3–B5: чистую Windows-установку, установленный UI-путь и проверку результатов;
- B8: независимый повторный Windows-прогон.

Bootstrap никогда не авторизует пользовательский релиз. Авторизующая проверка update/rollback требует реального предыдущего `RELEASE_AUTHORIZED` baseline, а физический пользовательский путь требует отдельного L5 на реальном пользовательском компьютере.

Пока эти обязательные gates не доказаны, итог остаётся:

`FAIL-CLOSED`

`PROTOCOL_IMPLEMENTATION_INCOMPLETE`

`MILESTONE_NOT_COMPLETE`

`RELEASE_BLOCKED`
