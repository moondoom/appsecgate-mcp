# Fault injection

- Master down: обязательный master недоступен; agent/sync exit 2 до внешнего timeout (D8/T-04).
- Master 5xx: outbox сохраняется; повторный push не создаёт дублей (D3/T-09).
- Master 401: запрет считается инфраструктурной ошибкой, секрет не попадает в JSON/log.
- Обрыв sync: повтор с тем же `run_id`; события идемпотентны, дублей нет.
- Policy: изменить master policy, выполнить pull, затем сверить `GateSummary` (D7/T-05).
- Remote suppression: создать только фикстурой/человеком, pull и повторный scan (D6/T-06).
- LLM down/invalid JSON/stall: exit 2 с `llm_error` или `timeout`; это не gate block.

Каждая инжекция выполняется на отдельном чистом data-dir и документируется в artifacts прогона.
