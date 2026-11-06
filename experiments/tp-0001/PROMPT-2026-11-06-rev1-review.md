# Handoff: REV-1 accepted; SEV-1 calibration и corpus blockers

Дата: 2026-11-06. Репозиторий: appsecgate-mcp (корень).

## Текущий статус

ADR-0017 **Accepted только для TTL reuse / revisions / provenance**. Основной
корпус 300 **не запускать**. Severity escalation **не включать**. Git commit не
создан. ADR-0018 **Proposed** заменяет numeric confidence для новых событий на
categorical evidence-based protocol и переносит severity escalation на master;
он ещё НЕ реализован. Исторические numeric events не удаляются, но в новый reuse
не входят. Прочитать:

- `docs/adr/ADR-0018-evidence-based-confidence.md`
- `docs/adr/ADR-0017-ttl-verdict-reevaluation-experiment.md`
- `experiments/tp-0001/artifacts/rev1v3-validation.json`
- `experiments/tp-0001/artifacts/rev1-operations.json`
- `experiments/tp-0001/artifacts/rev1-confidence-review.json`
- `docs/open-tasks.md`, REV-1 и SEV-1

## Что подтверждено controlled rev1v3

- Phase A1: свежая база на structlog (2) и aitextgen (3), TTL 0.
- Phase A2: 5/5 fresh reused, те же verdict/confidence, 0 LLM batches/tokens,
  0 новых local/master verdict events.
- Phase B: 2 TTL re-evaluations, `revision_reason=ttl_expired`, точные supersedes
  на A1 events.
- Phase C: 3 legacy re-evaluations, `revision_reason=legacy_confidence_missing`,
  точные supersedes на новые append-only seed events.
- `rev1v3-validation.json`: `passed=true`, все errors=[].

При валидации исправлены две integration ошибки: пустой knowledge cutoff теперь
`None`; PostgreSQL textual JSON confidence нормализуется в int перед TTL check.
Для повторных controlled серий использовать уникальный `REV1_RUN_PREFIX`.

## Operational blockers

- bitcore: 441/958 за 1693 s, 15.63 verdict/min, max gap 67.7 s, loop/restart/
  token-repeat = 0. Это continuous sizing/timeout, полный inventory требует около
  часа при timeout 1800 s. Нужно отдельное sizing/resume решение.
- AIWriteX: 2 failed findings в одном minified Monaco `workerMain.js`, 8 batch
  retries, 217374 tokens, tool errors=0, guided_incomplete=1. Large-context/
  protocol failure не закрыт.
- 38 duplicate raw rows / 22 groups: все same scanner/rule/exact normalized
  snippet на разных строках. Line намеренно не входит в fingerprint; dedup
  regression в этих artifacts не найден.

## Confidence / SEV-1

- По 1014 verdicts 10-run: 960 confidence 80…100, 54 в 50…79, 0 в 0…49.
- Порог 80 вырождается в эскалацию почти всех TP и не оправдан.
- Подготовлен human review bundle на 100 findings: все 54 medium + 46 high.
- Human labels пока отсутствуют. Нужны reliability bins/accuracy/Brier score после
  ручной разметки. Не присваивать ground truth моделью автоматически.
- `--force-reevaluate` остаётся future task с `revision_reason=manual`; не путать
  с `--no-reuse-verdicts`.

## Следующие решения владельца

1. Для REV-1 protocol дальнейшая реализация не требуется, кроме отдельного решения
   о `--force-reevaluate`.
2. Не запускать 300 до sizing/resume решения bitcore и разбора AIWriteX.
3. Не включать severity escalation до человеческой confidence calibration.
4. Commit/фиксация и продолжение corpus — отдельные явные команды владельца.

Полезные команды:

```bash
make check
make experiment-rev1-operations
make experiment-confidence-review
REV1_RUN_PREFIX=<unique> make experiment-rev1-validation
```

Основной corpus, CVE refreeze, readiness и cron monitoring из этого handoff не
запускать.
