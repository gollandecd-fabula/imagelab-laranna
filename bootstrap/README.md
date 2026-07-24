# ImageLab bootstrap source bundle

Эта папка используется только для запуска Windows Zero-Trust Gate. Она не является каналом пользовательского релиза.

## Exact source identity

Для текущего recovery-цикла разрешён только один исходный пакет:

- файл: `imagelab-source.zip`;
- версия: `1.4.9-recovery-candidate`;
- Build ID: `REC-RT8-M6-20260724-06`;
- SHA-256: `83bcfcc9e9d6dfaa29ef2827f3a967d9719cbff2650672b7d5d9d3eac1af4885`.

Файл `imagelab-source.sha256` закрепляет этот SHA-256. Совпадение только с checksum-файлом недостаточно: B0 независимо проверяет ожидаемую версию, Build ID, безопасные пути архива, CRC, обязательные файлы и privacy denylist.

## Подтверждённые hosted-проверки

Workflow run `30111216367` подтвердил для точного кандидата:

- B0: exact source admission — `PASS`;
- B1: source gate — `PASS`;
- B2: две byte-identical Windows-сборки — `PASS`;
- B3–B5: чистая Windows-установка, Edge UI и валидация реальных PNG/SVG — `PASS`;
- B8: независимый повтор на другом Windows runner с bundled Chromium — `PASS`.

Точная сводка evidence:

- `recovery/evidence/windows-gate/rc13-windows-evidence-summary.json`.

## Update / rollback

Механизм обновления и forced-failure rollback диагностически проверен на переходе `1.4.8` → `1.4.9` и прошёл. Эта проверка не является authorizing G6/G7, потому что `1.4.8` никогда не имела статуса `RELEASE_AUTHORIZED`.

Evidence:

- `recovery/evidence/update-rollback/diagnostic-update-rollback-148-149-summary.json`;
- `recovery/evidence/update-rollback/g6-authorized-baseline-blocker.json`.

## Текущие блокеры

- G6: отсутствует реальная предыдущая версия `RELEASE_AUTHORIZED`, опубликованная внешним GitHub Release и независимо закреплённая SHA-256;
- authorizing G7: заблокирован недействительным G6 baseline, несмотря на PASS технического rollback-механизма;
- физический пользовательский Windows L5: `UNVERIFIED`;
- RT8-M7 и RT8-M8: не завершены.

Bootstrap никогда не публикует установщик как пользовательский релиз. Текущий итог:

`FAIL-CLOSED`

`PROTOCOL_IMPLEMENTATION_INCOMPLETE`

`MILESTONE_NOT_COMPLETE`

`RELEASE_BLOCKED`
