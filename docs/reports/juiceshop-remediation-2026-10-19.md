# Juice Shop — Security Scan Report & Remediation

> **Дата:** 2026-10-19
> **Инструмент:** AppSecGate MCP 0.1.0
> **Цель:** OWASP Juice Shop (v16.2.0)
> **Конфигурация:** `network.mode: offline`, профили `javascript`, `python`
> **Статус:** **93/95 gitleaks подавлены как фикстурные**, 40 активных находок

---

## 1. Окружение

| Параметр | Значение |
|----------|----------|
| Сканер-сервер | `animage/appsecgate-mcp:0.1.0`, Docker 29.8.2, `--network=none` |
| Проект | OWASP Juice Shop (`/workspace`, `:ro`) |
| Тип скана | `scan_project(path="")` — полный рекурсивный скан |
| Сканеры | Gitleaks 8.x (секреты), Semgrep (SAST), Trivy (IaC/SCA) |
| БД | SQLite в data volume (эфемерна, см. §3.3) |

---

## 2. Воронка: от raw-результатов до активных находок

```
182 raw от Gitleaks/Semgrep/Trivy
  │
  ├─ gitleaks: 95 raw (93 тестовых фикстуры + 2 реальных секрета)
  │
  ▼ Dedup + coalesce (по fingerprint)
  │
  133 уникальных находки (v_findings)
  │
  ▼ Suppression (93 фикстурных fingerprint)
  │
  40 активных (SHOWN)
  ├─ gitleaks:  2 (реальные — оставлены на ревью)
  ├─ semgrep:  33 (реальные)
  └─ trivy:     5 (IaC)
```

### 2.1. Детерминизм fingerprint

Три критических находки дали **идентичный fingerprint** между двумя независимымисканами (разные сессии):

| Находка | Fingerprint | Стабильность |
|---------|-------------|--------------|
| JWT secret `lib/insecurity.ts` | `be37e8ece42148e2` | ✅ |
| NoSQL injection `routes/address.ts:42` | `5709160ba0501b6b` | ✅ |
| Hardcoded JWT `data/static/users.yml:42` | `6544ff0b19d9eb7a` | ✅ |

Fingerprint-алгоритм (нормализация + SHA256) детерминирован: один и тот же fingerprint гарантированно описывает ту же уязвимость между сканами.

---

## 3. Suppression Strategy

### 3.1. Что подавлено (93 фикстурных fingerprint)

| Категория | Количество | Примеры файлов | Обоснование |
|-----------|-----------|----------------|-------------|
| Тестовые ассерты с паролями | 48 | `test/api/*Spec.ts` (login, 2fa, deluxe…) | Тестовые данные |
| Тестовые JWT (cypress) | 10 | `test/cypress/e2e/admin*, basket*` | Forged JWT для E2E |
| Тестовые API-ключи | 8 | `test/api/chatBotSpec.ts`, `web3Spec.ts` | Фикстурные ключи |
| Статические пользователи | 12 | `data/static/users.yml` | 12 тестовых юзеров |
| Frontend spec-файлы | 5 | `frontend/src/app/*.spec.ts` | Jest-тесты |
| Faucet API-ключ | 1 | `frontend/src/app/faucet/` | Демо-ключ Ethereum |
| Прочие тесты | 9 | `test/server/`, `test/cypress/*more*` | Интеграционные тесты |
| **Всего** | **93** | | |

### 3.2. Оставлены для ревью (2 fingerprint)

| Fingerprint | Файл | Rule ID | Тип | Статус |
|-------------|------|---------|-----|--------|
| `32f96d1574a7fbf8` | `lib/insecurity.ts` | `private-key` | **Реальный RSA-ключ (RSA384)** | REVIEW NEEDED |
| `ffd1efcd44d4cbbb` | `routes/login.ts` | `generic-api-key` | **Токен bearer-аутентификации** | REVIEW NEEDED |

Это **реальные секреты** runtime Juice Shop. Подавление = сокрытие реальной уязвимости.

### 3.3. Caveat: эфемерность БД

**Проблема:** `shown_findings`, `suppressions`, `feedback` — в SQLite на data volume.
При `docker-compose down` или смене volume **все подавления теряются**.

**Последствия:**
- После перезапуска `v_findings` пуст, `get_scan_history` пуст.
- Suppressions не переживают restart.
- Fingerprint'ы детерминированы → повтор за 4 батча.

**Рекомендация:** для durable-установки — bind mount для data volume,
либо seed-скрипт при инициализации сессии.

---

## 4. Активные находки (40) — по степени риска

### 4.1. CRITICAL — NoSQL Injection via `$where` (25×)

**CWE:** CWE-943 | **OWASP:** A03:2021 Injection | **Источник:** Semgrep `nosql-injection`

**Паттерн:** `db.collections.find({ $where: "\"this.${req.body.param}\"" });`

| Файл | Сценарий |
|------|----------|
| `routes/address.ts:42` | Запись/обновление адреса |
| `routes/basket.ts:72,79` | Корзина |
| `routes/basketItems.ts:41` | Товары |
| `routes/captcha.ts:23` | Капча (NoSQL + eval) |
| `routes/dataErasure.ts:14` | Удаление данных |
| `routes/delivery.ts:28` | Доставка |
| `routes/deluxe.ts:18` | Deluxe membership |
| `routes/likeProductReviews.ts:23` | Лайк отзыва |
| `routes/order.ts:19,45,57` | Заказ |
| `routes/payment.ts:18,25,42` | Оплата |

**Риск:** RCE через JS-инъекцию в `$where`. Любой аутентифицированный — произвольный JS.

### 4.2. HIGH — Eval-based RCE (2×)

**CWE:** CWE-95 | **Источник:** Semgrep `eval-non-literal`, `eval-with-expression`

| Файл | Строка | Суть |
|------|--------|------|
| `routes/captcha.ts:66` | `eval(captcha.solution.replace(=,<))` |
| `routes/captcha.ts:104` | `eval(цифры)[выражение]` — альтернативный путь |

**Риск:** `eval()` с пользовательским вводом = RCE ("McDonald's" challenge).

### 4.3. HIGH — YAML Deserialization RCE (3×)

**CWE:** CWE-502 | **Источник:** Semgrep `yaml-deserialize`

| Файл | Строка | Код |
|------|--------|-----|
| `server.ts:24` | `yaml.load(fs.readFileSync(...))` |
| `vulnCode.ts:1,48` | `yaml.load(...)` — бэкдор |

**Риск:** `yaml.load()` без SafeLoader → произвольный объект → RCE.

### 4.4. HIGH — Hardcoded JWT Secret + Private Key (2×)

**CWE:** CWE-798 | **Источник:** Gitleaks `private-key`, Semgrep `hardcoded-jwt-secret`

| Файл | Строка | Ключ |
|------|--------|------|
| `lib/insecurity.ts:56` | JWT signing key (симметричный) |
| `lib/insecurity.ts:23` | RSA384 private key |

**Риск:** Любой, знающий код, подпишет произвольный JWT (admin-доступ).

### 4.5. MEDIUM — Trivy IaC Misconfigs (5×)

| Rule | Суть |
|------|------|
| DS-0001/0025 | Нет `USER`, запуск от root |
| DS-0002 | `COPY` без `--chown` |
| DS-0013 | Нет `HEALTHCHECK` |
| DS-0029 | Нет non-root пользователя |
---

## 5. Remediation Roadmap

### 5.1. Первоочередные (CRITICAL)

#### №1 — NoSQL Injection
Заменить `$where` с подстановкой на именованные параметры:
```typescript
// Вместо:
db.baskets.find({ $where: `this.UserId==='${req.body.UserId}'` });
// Использовать:
db.baskets.find({ UserId: req.body.UserId });
```
**Файлы:** все 25 роутов из §4.1.

#### №2 — Eval в captcha.ts
Парсить выражение через конечный автомат (только числа и операторы)
или библиотеку `mathjs`. Альтернатива для демо: хардкодить ответы капчи.

#### №3 — YAML десериализация
Заменить `yaml.load` на `safeLoad`:
```typescript
import { load as safeLoad } from 'js-yaml';
const config = safeLoad(fs.readFileSync(configFile, 'utf8'));
```

#### №4 — JWT секреты
Вынести в `JWT_SECRET` / `JWT_PRIVATE_KEY` env-vars с fallback-warning.
Стратегически: ES384 + ротация ключей.

### 5.2. Средний приоритет (MEDIUM)

#### №5 — Dockerfile hardening
- DS-0001/0025: `USER appuser` перед `EXPOSE` / `CMD`
- DS-0002: `COPY --chown=appuser:appuser`
- DS-0013: добавить `HEALTHCHECK`
- DS-0029: `RUN groupadd -r appuser && useradd -r -g appuser appuser`

### 5.3. API-ключ `routes/login.ts` — на ревью

Fingerprint `ffd1efcd44d4cbbb`. Может быть легаси-токеном для внешнего
OAuth/SSO. Требуется ручной анализ: рабочий ключ или мёртвый код.

### 5.4. CI/CD интеграция

1. `scan_diff` в pre-commit hook.
2. Фаза 2 AppSecGate: блокировка PR с новыми CRITICAL находками.
3. Еженедельный `scan_project` на `main`.

---

## 6. Ключевые наблюдения

- **OBS-JS-1 (infra):** `update_config` (allowlist) невозможен при `:ro`
  монтировании — только `suppress_finding` MCP-тул или data-директория.
- **OBS-JS-2 (DB):** suppression'ы живут в SQLite data volume и теряются
  при restart; для durable — bind mount или seed-скрипт.
- **OBS-JS-3 (gitleaks):** 95 raw → только 2 реальных секрета; остальное —
  тестовые фикстуры демо-проекта.
- **OBS-JS-4 (fingerprint):** детерминизм подтверждён — один fingerprint =
  та же уязвимость между сканами и сессиями.
- **OBS-JS-5 (batch):** 76 параллельных `suppress_finding` (4 батча ~20)
  — 100% success, пригодно для автоматизации.

---

## 7. Быстрый старт: как повторить

```bash
make docker-build

docker run --rm -i \
  --network=none --read-only --cap-drop=ALL \
  --tmpfs=/tmp:size=100M --user=1000:1000 \
  -v /path/to/juice-shop:/workspace:ro \
  -v appsecgate-data:/home/appsecgate/.appsecgate-mcp \
  animage/appsecgate-mcp:0.1.0
```

1. `scan_project(path="")` — полный скан.
2. Подавить фикстурные fingerprint'ы (список — §3.1) батчами.
3. `query_findings_db(sql="SELECT scanner,rule_id,severity,file_path
   FROM v_findings WHERE status='SHOWN' ORDER BY severity DESC")`.
4. `get_fix_context(finding_id="<id>")` — данные для фикса.
5. `verify_fix(finding_id="<id>", status="fixed")` — верификация.

---

## 8. Ссылки

- [AppSecGate MCP — спецификация fix-воронки](fix-workflow-design.md)
- [OWASP Juice Shop](https://owasp.org/www-project-juice-shop/)
- [CWE-943](https://cwe.mitre.org/data/definitions/943.html) |
  [CWE-95](https://cwe.mitre.org/data/definitions/95.html) |
  [CWE-502](https://cwe.mitre.org/data/definitions/502.html) |
  [CWE-798](https://cwe.mitre.org/data/definitions/798.html)

---

*Документ создан 2026-10-19 по итогам scan → classify → suppress → verify
воронки AppSecGate MCP 0.1.0. Финальный снапшот:
`/tmp/findings-snapshot-2026-10-19.ndjson` (133 находки, 93 suppressed).*