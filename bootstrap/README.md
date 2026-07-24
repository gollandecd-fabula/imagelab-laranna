# ImageLab bootstrap source bundle

Эта папка используется только для первоначального запуска Windows Zero-Trust Gate.

## Exact source identity

Для текущего цикла разрешён только один исходный пакет:

- файл: `imagelab-source.zip`;
- версия: `1.4.3-redteam-cycle6-candidate`;
- Build ID: `RT8-M6-20260724-02`;
- SHA-256: `272e825aa4dc320bc6c287fe44700d1c234a9cd97414b719fc62a74b0fc37ab5`.

Файл `imagelab-source.sha256` закрепляет этот SHA-256. Совпадение только с самим checksum-файлом недостаточно: B0 независимо проверяет ожидаемую версию, Build ID, безопасные пути архива, CRC, обязательные файлы и privacy denylist.

## Текущий блокер

На ветке всё ещё находится предыдущий архив с SHA-256 `c236656f53447996dc837a206a8896fc6abacf13d45829d8e9e64888b9f6b308`. Он не соответствует cycle 6 и обязан блокироваться до распаковки/исполнения последующих ворот.

Для продолжения RT8-M6 необходимо атомарно заменить только `bootstrap/imagelab-source.zip` точным cycle-6 архивом. Подмена checksum, ручное изменение версии внутри старого ZIP или ослабление B0 запрещены.

## Проверки bootstrap

Workflow выполняет:

- B0: точный SHA-256, CRC, безопасные пути, denylist, version/build identity;
- B1: обязательный Source Gate и критические изолированные regression tests;
- B2: две воспроизводимые Windows-сборки и manifest identity;
- B3–B5: чистую Windows-установку, установленный UI-путь и проверку результатов;
- B8: независимый повторный Windows-прогон.

Bootstrap никогда не публикует установщик как пользовательский релиз. Пока не проверены обновление реальной предыдущей версии, forced-failure rollback и физический пользовательский путь, итог остаётся:

`FAIL-CLOSED`

`PROTOCOL_IMPLEMENTATION_INCOMPLETE`

`MILESTONE_NOT_COMPLETE`

`RELEASE_BLOCKED`
