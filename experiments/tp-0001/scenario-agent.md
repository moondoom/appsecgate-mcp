# Autonomous agent experiment scenario

## Scope

Evaluate the single autonomous RO-agent from ADR-0015. Do not preserve or rerun the old one-shot agent as a product mode. Historical model selection and the diagnostic 100-repository run remain preliminary evidence only.

The initial main corpus has 300 repositories: the previous 100 development/pilot repositories and 200 new held-out repositories. Expansion proceeds in blocks of 100 new held-out repositories, up to 1000, only under the pre-registered confidence-interval/category rules and available blind-review budget.

## Development iterations

Before freezing the main run, agent code, prompts, tools, batching, compaction, restart policy, and budgets may be improved iteratively. Each version receives a unique `agent-dev-vN` label with image, prompt, tool, and configuration hashes. Every candidate passes `make check` and the same development suite. Development results are never mixed with the main corpus.

The frozen release candidate is used for every main run. Any behavioral change requires a new version and a complete rerun of the affected corpus.

## Frozen configuration

Record before the main run:

- repository names, commit SHAs, development/held-out labels, and inventory hashes;
- model name and digest, generation parameters, and context size;
- scanner versions, ruleset hash, Trivy DB, image digest, prompt/tool hashes, and budgets;
- master MCP URL, project-scoped credentials, knowledge cutoff, and CVE content snapshot;
- TP/FP/NEEDS_REVIEW policy, blind-review policy, repeat list, and expansion rule.

The knowledge cutoff excludes current-run and parallel-run verdicts. Repeats use the same cutoff and CVE snapshot.

## Launch sequence

After development is complete and the 300 repositories are present, prepare the external rules once, generate the frozen configuration, and start master. The host-only downloader uses the `agent300` language profile; the same read-only rules directory is reused by every run. External rules and their licenses are not committed or added to the image, and no image rebuild is needed.

```bash
make experiment-semgrep-rules-prepare
make experiment-semgrep-rules-validate
make experiment-run-config
make experiment-agent300-master
make experiment-master-knowledge
```

Run the no-sync preflight to collect the CVE IDs, then import the frozen OSV snapshot:

```bash
make experiment-agent300-preflight
make experiment-cve-prepare
```

Only after the configuration, image, knowledge, and CVE manifests are verified should the main corpus start:

```bash
make experiment-readiness-check
make experiment-agent300-run
make experiment-agent300-repeat
```

These targets are launch commands, not a claim that the 300-repository experiment has already run. The manifest is `artifacts/agent300-run-config.json`; test-only project keys are under `runtime/`.

## Per-run artifacts

Each report contains structured scan counters, full inventory and hash, all verdicts, evidence, pending/missing IDs, action log, loops, restarts, compactions, usage, and master degradation.

The local `triage_verdicts.ndjson` journal is synchronized through the durable outbox as idempotent `triage_verdicted` events. Master MCP is read-only; it never receives writes from the agent.

## Collection

Run from `experiments/tp-0001/`:

```bash
python3 collect_agent_funnel.py --label asgfree300 --model gemmaq3 --parallelism 4
```

Outputs:

- `artifacts/asgfree300-funnel.json`: per-repository raw, scope, dedup, suppression, eligible, assigned, verdict, and missing counts;
- `artifacts/asgfree300-review.json`: every assigned finding, including model FP and missing, with empty or preserved human-review fields.

Do not run the old `auto_triage.py` over the new review file. Blind review covers every assigned finding. Human labels are frozen before joining them with model verdicts. At least 20% stratified findings and all disputed cases receive a second review with agreement/adjudication records.

## Expansion

After each block, complete blind review first. Then compute repository-clustered 95% bootstrap intervals. Add 100 held-out repositories only if a key precision/NPV/recall interval half-width remains above five percentage points or a key category has fewer than 30 human TPs. Stop at 1000 or when the approved review/inference budget is exhausted. Publish every intermediate N and expansion reason.
