# ADR-0002: Языковая консистентность user-facing слоя и надёжность фиксов AI-агента

**Статус:** Proposed
**Дата:** 2026-10-21
**Контекст:** прогон harness на внешнем полигоне (qwen3-coder:30b), отчёт report.md
**Решает:** recall 25% (2/8) при fix-workflow + precision 0.00 из-за бага метрики

---

## 1. Контекст

Прогон AppSecGate MCP через harness на внешнем проекте-полигоне дал
recall 25% (2/8 sentinel-фиксов) и precision 0.00. Разбор показал три
независимые причины.

### 1.1. Precision 0.00 — баг метрики, не провал модели

`harness/metrics.py → extract_finding_texts_from_trace` кладёт в множество
`touched` только вызовы `scan_project` / `get_fix_context` / `verify_fix`.
Модель вызывала `get_fix_context_batch` и ни разу `verify_fix`, поэтому
`touched = ∅ → precision = 0`, хотя модель трогала правильные findings.

### 1.2. Recall 6/8 — промах `apply_changes`, не язык

coding-tools `apply_changes` правит по номерам строк. Первая правка сжала
SQL (4 строки → 2), все последующие правки по старым номерам строк попали
не туда (pickle «заявлен как удалён», секрет только закомментирован).
6 из 8 sentinel-строк остались в файле.

### 1.3. Языковой «винегрет» в контексте модели

У англоязычной код-модели в контексте смешаны:
русский SYSTEM_PROMPT/DEFAULT_TASK (harness), русские docstrings 14 тулов
AppSecGate и русская error-строка — поверх английских данных findings и
английского coding-tools. Это когнитивный разрыв + лишние токены
(кириллица дороже).

### 1.4. Что уже в норме

- `FastMCP(instructions=...)` — английский.
- ContextPack `_INSTRUCTIONS` — английский.
- Данные findings (rule_id/severity/message) — английские.
- coding-tools — английский.

---

## 2. Цели и не-цели

### Цели

| # | Цель | Метрика |
|---|------|---------|
| G1 | Поднять recall fix-workflow с 25% к ~100% | sentinel-чек |
| G2 | Сделать precision честным | touched-множество не пустое |
| G3 | Убрать языковой разрыв в контексте модели | 0 кириллицы в user-facing слое |
| G4 | Не сломать существующие 283 теста | make check |

### Не-цели

- Не переводить комментарии/логи/внутренние docstrings (модель их не видит).
- Не трогать данные findings (уже EN).
- Не менять сигнатуры MCP-тулов.
- Не нарушать инварианты AGENTS.md (все 6 сохраняются).
- Не добавлять новые production-зависимости.
- Не рефакторить harness/coding-tools в этом репозитории (их здесь нет).
---

## 3. Решение

Три независимых направления + валидация. Направления 2 и 3 физически живут
вне этого репозитория (harness, coding-tools); здесь фиксируется только
решение, правки вносятся в соответствующих проектах.

### 3.1. Направление 1 — языковая консистентность (этот репозиторий)

**Перевести на английский user-facing слой AppSecGate MCP:**

1. Docstrings всех 14 тулов `@mcp.tool()` в
   `mcp-server/src/appsecgate_mcp/server.py`:
   `scan_file`, `scan_diff`, `scan_project`, `get_config`, `update_config`,
   `submit_feedback`, `get_scan_history`, `suppress_finding`,
   `get_fix_context`, `get_fix_context_batch`, `verify_fix`,
   `verify_fix_batch`, `query_findings_db`, `export_snapshot`.

2. Единственная русская user-facing error-строка в ответе:
   `"not a directory: {path} (используйте scan_file для файла)"` →
   `"not a directory: {path} (use scan_file for a single file)"`.

3. Внешние правки (другой репозиторий): harness `SYSTEM_PROMPT`,
   `DEFAULT_TASK`, финальный отчёт → EN. `FINAL_REPORT_RE` уже матчит
   `fixed|finding|исправлен|находк`, метрика не ломается.

**Не переводить:** module docstring, docstrings хелперов, `logger.*`,
комментарии — они не попадают в контекст модели.

### 3.2. Направление 2 — надёжность патчей (coding-tools, внешний)

**2.1.** Убрать `apply_changes` из coding-tools MCP. Оставить `apply_patch`
(unified diff, матчит по контексту) и `write_file` (полная перезапись) —
оба не ломаются от сдвига строк.

**2.2.** В harness `SYSTEM_PROMPT` добавить техническое правило (про
инструменты, не про уязвимости): применять изменения снизу вверх /
перечитывать файл после каждой правки / для множественных правок —
`write_file`.

**Решение: 2.1 + 2.2 вместе** (надёжный инструмент + мягкая подсказка).

### 3.3. Направление 3 — честный precision (harness metrics.py, внешний)

В `harness/metrics.py → extract_finding_texts_from_trace` обрабатывать:
- `appsecgate-shop__get_fix_context_batch` — парсить `finding_ids` из `arguments`;
- `appsecgate-shop__verify_fix_batch` — добавлять в `touched`.

(`tool_assertions` уже расширен: `apply_changes`, `get_fix_context_batch`,
`scan_diff`, `query_findings_db`.)

### 3.4. Направление 4 — валидация

1. Mock-прогон → recall 100%, restore OK.
2. Реальный прогон `qwen3-coder:30b` (1 run).
3. Multi-run (3–5) — стабильность recall.
4. (Опц.) сравнить `gemma4:26b`.

---

## 4. Инварианты и ограничения

Ни один из шести инвариантов AGENTS.md не затрагивается: перевод docstrings
и error-строк не меняет поведение сервера, не добавляет сетевых/LLM-вызовов,
не трогает схему БД и сигнатуры тулов. Направления 2–3 относятся к
внешним проектам и в этом репозитории не реализуются.

---

## 5. Последствия

### Положительные

- Направление 2 — прямой вклад в recall (основная причина 6/8 промахов).
- Направление 3 — precision станет отражать реальную работу модели.
- Направление 1 — единый EN-контекст для код-модели, меньше токенов,
  стабильнее поведение; сама по себе recall не поднимает, но убирает шум.
- Docstrings после перевода остаются валидными — FastMCP берёт описание из
  `__doc__`, сигнатуры не меняются, 283 теста не затронуты.

### Отрицательные / риски

- Перевод docstrings требует ручной выверки: «мёржит»/«снапшот»/«находка»
  должны переводиться однозначно, чтобы не потерять смысл контракта тула
  (напр. announce-only у `scan_project`, read-only у `query_findings_db`).
- `apply_patch`/`write_file` требуют от модели корректного unified-diff /
  полного содержимого файла — при слабой модели возможен регресс по
  другому сценарию; компенсируется правилом 2.2.
- Направление 3 меняет только метрику, не поведение — риск «метрика зелёная,
  а фикс не применён» остаётся вне scope (валидируется Направлением 4).

### Нейтральные

- Русскоязычные комментарии/логи и внутренние docstrings остаются — на
  продукт и модель не влияют.

---

## 6. План внедрения

| Этап | Содержание | Репо | Оценка |
|------|------------|------|--------|
| 1 | Перевод docstrings 14 тулов + error-строки в `server.py` | appsecgate-mcp | 0.5 дн |
| 2 | `make check` (283 теста зелёные) + `make format` | appsecgate-mcp | 0.5 дн |
| 3 | Harness: SYSTEM_PROMPT/DEFAULT_TASK/отчёт → EN | harness | 0.5 дн |
| 4 | coding-tools: убрать `apply_changes`, правило 2.2 в SYSTEM_PROMPT | coding-tools | 0.5 дн |
| 5 | metrics.py: get_fix_context_batch / verify_fix_batch в `touched` | harness | 0.5 дн |
| 6 | Валидация: mock → 1 run → multi-run (3–5) | harness | 1–2 дн |

**Условие выхода:** recall ~100% на mock и реальном прогоне, precision ≠ 0
и соответствует реальной работе, 283 теста зелёные.

---

## 7. Открытые вопросы

1. **Единый EN-отчёт** vs «report in Russian» как требование к модели — по
   умолчанию единый EN (см. 3.1 п. 3), но можно зафиксировать явно.
2. **`apply_patch` как единственный патч-инструмент** — достаточно ли
   unified-diff для всех сценариев полигона, или нужен fallback `write_file`
   для крупных правок (решается валидацией, Направление 4).
3. **`gemma4:26b`** — обязательный прогон сравнения или только при
   нестабильном recall у `qwen3-coder:30b`.

---

## 8. Ссылки

- `AGENTS.md` — инварианты, Definition of Done.
- `docs/fix-workflow-design.md` — спецификация Фазы 1 (§5 — MCP-тулы,
  §8.4 — English instructions).
- `docs/adr/ADR-0001-fingerprint-and-semantic-dedup.md` — формат ADR.
- Внешние: `harness/metrics.py`, `harness/scenarios.py`, coding-tools MCP.

---

## Список изменений

| Версия | Изменения |
|--------|-----------|
| 0.1    | Первый черновик по итогам прогона harness на внешнем полигоне |