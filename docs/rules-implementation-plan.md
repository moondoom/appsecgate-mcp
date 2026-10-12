# План реализации: Rules Bundle, остаток работ

> **Источник требований:** [`docs/session-handoff.md`](session-handoff.md) (Дизайн v1).
> **Статус:** этапы 0–7 реализованы (подробности в истории git). Остался этап 8 (CI-валидация bundle) и открытые вопросы из спеки.

---

## 0. Как пользоваться этим файлом

1. Прочитать `docs/session-handoff.md` (требования) и этот файл (остаток работ).
2. Взять первый незакрытый пункт из раздела «2. Статус».
3. После выполнения отметить чекбоксы и дописать запись в «7. Журнал».

**Конвенции проекта (соблюдать):**
- Python ≥ 3.11, `from __future__ import annotations` в каждом модуле.
- Pydantic v2 модели (`BaseModel`, `Field(default_factory=...)`).
- Русские докстринги, `ruff` (line-length 100, select E/F/I/W/UP/B), `pytest` (asyncio_mode=auto).
- Сканеры запускаются только через `subprocess` без shell (см. `scanners/runner.py`).
- Store-классы находятся в `storage/stores.py`, доступ к SQLite только через `storage/db.py`.
- Новые пакеты экспортируются через `__init__.py` с `__all__`.

---

## 1. Текущее состояние

Реализовано:
- пакет `src/appsecgate_mcp/rules/` (`manifest.py`, `resolver.py`, `license_guard.py`, `trivy_db.py`);
- `RuleResolver` и `LicenseGuard` подключены в `ConfigLoader`;
- провод `--config` и путей правил в сканеры и реестр;
- Trivy DB seed и проверка возраста БД;
- `session_start` с rules-метой и `ruleset_hash`;
- содержимое bundle `mcp-server/rules/` (`manifest.yaml`, `opengrep-community/` без `jetbrains/**`, `semgrep-custom/`, `gitleaks/`, `trufflehog/`, `THIRD_PARTY_NOTICES.md`);
- `Dockerfile` (COPY rules, seed Trivy DB, `WITH_JAVA_DB`), `docker-compose.yml`;
- раздел лицензионной модели в `docs/architecture.md`.

Отклонение от плана: `appsecgate-secrets.yaml` не создан, секреты покрыты `gitleaks/default.toml`.
Образ Docker в сессии не собирался, проверка сборки входит в этап 8.

---

## 2. Статус

- [ ] Этап 8: CI-валидация bundle

---

## 3. Этап 8: CI-пайплайн валидации bundle

- [ ] GitHub Actions workflow:
  - `semgrep --validate` по `rules/semgrep-custom/` и `rules/opengrep-community/`;
  - `semgrep --test` для правил с тестовыми фикстурами;
  - dry-run `gitleaks detect --config rules/gitleaks/default.toml`;
  - schema-check `rules/trufflehog/detectors.yaml`;
  - проверка `LicenseGuard` по `rules/manifest.yaml` при `distribution_mode: mit`;
  - `du -sh` образа и каталога `rules/` (лимит размера);
  - сборка Docker-образа (проверка `COPY rules/` и seed Trivy DB);
  - регрессия на 3–5 эталонных проектах.
- [ ] Тесты и линт остаются зелёными: `make test`, `make lint`.

**Готово, когда:** PR в rules-repo прогоняет проверки из `session-handoff.md §4.2`.

---

## 4. Открытые вопросы (из `session-handoff.md §11`)

- [ ] §11.2 схема custom-detectors TruffleHog 3.82
- [ ] §11.3 реальный размер `trivy-db-seed` (amd64)
- [ ] §11.4 `--network=none` для sync или отдельная команда
- [ ] §11.5 автогенерация `THIRD_PARTY_NOTICES.md` (Syft/Grype)
- [ ] §11.6 юридическая проверка изоляции `subprocess` для AGPL

§11.1 закрыт: исключён `jetbrains/`, Commons Clause в срезе не найден.

---

## 5. Не делать в v1

Watcher'ы, автоопределение сети и языков, deep-merge правил, hot-reload, MCP-инструменты `update_rule`/`reload_rules`, UI, `extends`, версионирование отдельных правил.

---

## 6. Ключевые решения (фиксированы)

- Bundle — атомарная единица; замена файла целиком, без deep-merge.
- Офлайн по умолчанию (`network.mode: offline`), без автодетекта сети.
- Языковая оптимизация только через явные профили, автоопределения нет.
- Trivy DB — seed-on-first-run.
- Лицензии: Semgrep-правила MIT/Apache/LGPL-3.0; TruffleHog (AGPL) только как внешний бинарь; `jetbrains/**` и `semgrep/semgrep-rules` исключены.

---

## 7. Журнал

| Дата | Этап | Что сделано |
|------|------|-------------|
| — | 0–7 | Реализованы, пункты удалены из плана. |
| — | 8 | Ожидает реализации. |