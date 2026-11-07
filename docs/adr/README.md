# Architecture Decision Records

| ADR | Название | Статус |
|---|---|---|
| [ADR-0001](ADR-0001-fingerprint-and-semantic-dedup.md) | Fingerprint and semantic dedup | Accepted |
| [ADR-0002](ADR-0002-language-consistency-and-agent-fix-reliability.md) | Language consistency & agent fix reliability | Proposed |
| [ADR-0003](ADR-0003-ci-unresolved-local-delivery.md) | CI unresolved local delivery | Repurposed as classic hard-gate (ADR-0008) |
| [ADR-0004](ADR-0004-master-server-sync.md) | Master server sync | Accepted (MS-1..7; MS-8 ⏸) |
| [ADR-0005](ADR-0005-project-reconciliation.md) | Project reconciliation & shown state machine | Accepted |
| [ADR-0006](ADR-0006-unified-finding-lifecycle-model.md) | Unified finding lifecycle model | Accepted (SM-1..3,5,6; SM-4 удалён MS-6) |
| [ADR-0007](ADR-0007-per-branch-state.md) | Per-branch state | Proposed (Фаза 3) |
| [ADR-0008](ADR-0008-orchestrator-presets.md) | Orchestrator modes | Proposed |
| [ADR-0009](ADR-0009-agent-implementation-model.md) | Agent implementation model | Proposed (depends on ADR-0008) |
| [ADR-0010](ADR-0010-rw-agent.md) | RW-agent | Proposed (Пауза) |
| [ADR-0011](ADR-0011-scan-run-observability.md) | Scan run observability, passive counters, pattern promotion | Proposed |
| [ADR-0012](ADR-0012-master-database-and-auth.md) | Master database and auth foundation | Proposed |
| [ADR-0013](ADR-0013-master-mcp-interface.md) | Master MCP interface | Accepted (MCP-M-1..7 implemented) |
| [ADR-0014](ADR-0014-multi-mode-mcp-image.md) | Multi-mode MCP image (serve/sync/ci/agent ro+rw) | Proposed; изменяет G7 ADR-0004 |
| [ADR-0015](ADR-0015-autonomous-triage-and-master-knowledge.md) | Autonomous triage agent and master knowledge | Accepted |
| [ADR-0016](ADR-0016-llm-throughput-and-context-lanes.md) | LLM throughput, context lanes and dynamic parallelism | Proposed (замеры завершены; guided-sched не реализован) |
| [ADR-0017](ADR-0017-ttl-verdict-reevaluation-experiment.md) | TTL verdict reuse and re-evaluation experiment | Proposed |
| [ADR-0018](ADR-0018-evidence-based-confidence.md) | Evidence-based confidence and master-owned escalation | Proposed |
| [ADR-0019](ADR-0019-guided-mode-redesign.md) | Guided mode redesign and operating-point acceptance | Proposed (acceptance required) |
| [ADR-0020](ADR-0020-guided-full-experiment-and-statistics.md) | Guided mode full experiment and statistics (Parts 3–10 of the ADR-0019 plan) | Реализовано (GD-1..GD-17); замеры GD-7/GD-8 в работе; pending review |

## Publication policy

ADR files are published as written, so they must be safe to publish:

- **No RFC1918 addresses** (`10/8`, `172.16/12`, `192.168/16`) and no raw internal
  hostnames. Use placeholders: `<llm-host>`, `<mgmt-host>`, `<runner-host>`.
  The owner-approved logical alias `appsecgate-lab` is allowed for the lab.
- **No credentials**, tokens, Bearer secrets, API keys, or connection strings.
- **Public OSS repositories** may be named only with the workload-fixture
  disclaimer (see ADR-0019 §2.2). They are fixtures, not assessments.
- **Private/internal repositories** are replaced by stable identifiers
  (`repo-heavy-1`); the mapping lives only in
  `experiments/tp-0001/fixtures/private-map.json` (gitignored).
- **Artifacts** under `experiments/` follow the same rules; raw logs with
  internal identifiers are written to gitignored `runtime/` and summarized.

Enforced by `scripts/check-no-private-infra.sh` via pre-commit.
