# Third-Party Notices: Rules Bundle

Этот файл перечисляет сторонние правила и данные, распространяемые вместе с каталогом `rules/`.

## 1. opengrep-community (Semgrep-правила)

- **Источник:** https://github.com/qodana/opengrep-sast-rules
- **Срез:** каталоги `c/`, `csharp/`, `go/`, `javascript/`, `python/`, `scala/` и `lgpl/` из `rules/lgpl/`.
- **Исключено:** каталог `jetbrains/` целиком (содержит Commons Clause, запрещающий коммерческую продажу).
- **Лицензии:**
  - `LICENSE-MIT` — MIT Expat (GitLab Inc.), применяется к содержимому вне `doc/`, `ee/`, `jh/`.
  - `LICENSE-LGPL-3.0` — GNU LGPL v3, применяется к правилам из `lgpl/`.
- **Проверка:** поиск по строке `commons clause` в срезе не дал совпадений (см. `manifest.yaml`, поле `license`).

## 2. semgrep-custom (собственные правила)

- **Файлы:** `semgrep-custom/appsecgate-base.yaml`.
- **Лицензия:** MIT (правила проекта AppSecGate).

## 3. gitleaks (конфигурация)

- **Файлы:** `gitleaks/default.toml`, `gitleaks/allowlist.toml`.
- **Лицензия:** MIT (собственные правила проекта). Встроенные правила Gitleaks подключаются через `[extend] useDefault = true` и распространяются по лицензии MIT, Copyright (c) Zachary Rice / Gitleaks contributors.

## 4. trufflehog (конфигурация)

- **Файлы:** `trufflehog/detectors.yaml`.
- **Статус:** данные конфигурации, не производная работа TruffleHog. Сам TruffleHog распространяется под AGPL-3.0 и запускается только как внешний немодифицированный бинарник через `subprocess`. Исходники TruffleHog в этом каталоге не вендорятся.

## 5. Trivy DB (не входит в каталог `rules/`)

- Вендорная база данных Trivy распространяется Aqua Security под Apache-2.0.
- В образ не вкладывается напрямую: засевается на первом запуске из `/opt/appsecgate/trivy-db-seed` (см. дизайн v1, §5).

## Ограничение ответственности

Сведения носят информационный характер и не являются юридическим заключением. Юридическая проверка изоляции AGPL-компонентов открыта (`session-handoff.md §11.6`).