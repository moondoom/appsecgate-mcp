# TP-0001 Stage 1 scenario

Объект: `appsecgate-mcp agent --mode=ro --output-format json`.
Проект: PyGoat, SHA `1b63054befb45aca53c761c421d883aa2e5fd6c1`.
Лимиты: `T_budget=7 календарных дней`, `K=3` fix-and-resume.

## Подготовка

1. `invoke.sh` загружает корневой `.env` и использует `LITELLM_API_KEY`, не копируя секрет.
2. Задать `APPSECGATE_LLM_MODEL` из `ci_config/<model>.env.example` и `APPSECGATE_LLM_URL`
   для своего окружения. Для master-прогона задать URL и project-scoped key.
3. Для каждого прогона создать чистый writable `DATA_DIR`, новые `RUN_ID` и project-scoped key.
4. Выполнить `invoke.sh`. Без master-параметров допустим только предварительный `--no-sync` прогон.
5. Исходный PyGoat монтируется только read-only. Патчи применяются лишь на отдельной копии.

`invoke-docker.sh` не выполняет собственный триаж и не вызывает LLM напрямую. Sync выполняет
сам agent после формирования отчёта. Внешний timeout — 35 минут; LLM timeout — 300 секунд. Gate block даёт
exit 0, ошибка инфраструктуры или обязательный sync — exit 2.

## Циклы

Стадия 1A: 10 циклов, последовательно Qwen → GLM → Gemma4 на неизменном SHA.
Стадия 1B: T-01…T-08 на циклах 1, 5, 10; T-01/T-04/T-07 на остальных. Mock-LLM
используется только для gate correctness и исключается из F1.

После прогона сохранить JSON, agent/sync log, edge DB, LiteLLM usage и выполнить
`master_checks.py`, затем `eval.py`. До A8 Стадия 2 не начинается. Ground truth используется
только в `eval.py`; человек утверждает 20% случайных и все спорные находки.
