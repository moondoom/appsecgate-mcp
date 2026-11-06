# TP-0001 Script Guide

Run commands from `experiments/tp-0001/` unless stated otherwise. Scripts use only Python standard library and local project tooling; scanner/LLM execution goes through the existing AppSecGate Docker image. Do not commit `.env`, `runtime/`, cloned repositories or API keys.

## Experiment drivers

### Autonomous agent smoke

From the repository root, start the deterministic mock and run the live T-01/T-04/T-07 checks in separate terminals:

```bash
make experiment-master-up
make experiment-mock-llm
make experiment-gate-smoke
```

The gate uses an isolated master on port 8001 with three explicitly test-only project keys and the new `agent-dev-v1` namespace; the primary master and historical artifacts are not affected. Explicit smoke keys take precedence over root/runtime env files. Stop it with `make experiment-master-down` after the run.

### `benchmark_parallel.py`

Runs one or more models against repeated `pygoat` runs or an explicit repository list, collects wall time, throughput, p50/p95, protocol retries, token usage, master checks and Prometheus metrics.

Environment:

- `BENCH_MODELS`: comma-separated labels from the script's `MODELS` map; default all.
- `BENCH_PARALLELISM`: comma-separated worker counts; default `1,2,4`.
- `BENCH_PROJECTS`: comma-separated names under `repos/`; empty means repeated pygoat.
- `BENCH_RUNS`: pygoat repetitions; default 4.
- `BENCH_LABEL`: run/artifact prefix; default `bench`.
- `BENCH_OUTPUT`: filename under `artifacts/`; default `parallel-benchmark.json`.
- `APPSECGATE_MASTER_API_KEYS`: JSON object mapping project IDs to master keys.
- `NO_SYNC=1`: skip master evaluation.

Example — the frozen model on two repositories:

```bash
BENCH_MODELS=gemmaq3 BENCH_PARALLELISM=4 \
BENCH_PROJECTS=repo-a,repo-b BENCH_LABEL=smoke \
BENCH_OUTPUT=smoke-benchmark.json python3 benchmark_parallel.py
```

The Docker image must be rebuilt after agent changes (`make docker-build` from repository root); otherwise the benchmark runs stale code.

### `invoke-docker.sh`

Canonical isolated agent invocation. Mounts the target repository read-only, stores state outside the project and writes `report.json`, `agent.log` and `exit_code`.

Required: `RUN_ID`, `DATA_DIR`, `APPSECGATE_LLM_MODEL`. Optional: `PROJECT`, `ARTIFACT_DIR`, `CACHE_DIR`, `POLICY`, `NO_SYNC`, `APPSECGATE_PROJECT_ID`, `APPSECGATE_MASTER_API_KEY`, `APPSECGATE_MASTER_URL`, LLM generation parameters.

```bash
RUN_ID=manual-001 DATA_DIR=runtime/data-manual-001 \
PROJECT=repos/pygoat APPSECGATE_LLM_MODEL=ollama/gemma4:26b \
./invoke-docker.sh
```

### `invoke.sh`

Host-venv equivalent of `invoke-docker.sh`, using `mcp-server/.venv/bin/appsecgate-mcp`. Required: `RUN_ID`, `DATA_DIR`. Prefer the Docker variant for benchmark parity.

### `eval.py`

Evaluates one agent report against approved fixture ground truth and optional master checks.

```bash
python3 eval.py artifacts/<run>/report.json \
  --ground-truth repos/stage1_project.json \
  --master-checks artifacts/<run>/master-checks.json \
  --output artifacts/<run>/eval.json
```

It refuses unapproved ground truth. This fixture evaluator is distinct from the later 63-position oss20 ground-truth analysis.

### `master_checks.py`

Compares edge `shown_findings.db` with master findings/audit and computes D1–D4 plus synchronization p95.

```bash
python3 master_checks.py \
  --edge-db runtime/data-<run>/shown_findings.db \
  --master-url http://127.0.0.1:8000 \
  --api-key "$MASTER_KEY" --project-id "$PROJECT_ID" \
  --agent-exit 0 --output artifacts/<run>/master-checks.json
```

### `mock_llm.py`

Deterministic OpenAI-compatible HTTP server returning TRUE_POSITIVE for every supplied finding. Used for gate mechanics, not model-quality tests.

```bash
python3 mock_llm.py --port 4001
```

### `gate_tests/run_cycle.sh` and `gate_tests/evaluate.py`

Runs T-01–T-08 against master fixtures and evaluates the resulting artifacts.

```bash
GATE_PREFIX=gate-test TESTS="t01 t04 t07" \
APPSECGATE_LLM_URL=http://<llm-host>:4000/v1 \
APPSECGATE_LLM_MODEL=ollama/<model> \
./gate_tests/run_cycle.sh gemmaq3

GATE_PREFIX=gate-test python3 gate_tests/evaluate.py gemmaq3
```

`TESTS` defaults to all eight tests; `POLICY` defaults to warn. Evaluation writes `artifacts/<prefix>-gate-results.json`.

## Stage 3 repository sourcing and metadata

### `find_vibe_repos.py`

Queries GitHub Search for explicit AI/vibe-code signals plus conventional controls, filters languages and writes `artifacts/vibe100-shortlist.json`. It sleeps between requests to respect search limits. Selection, manual sample validation and cloning into `repos/` are separate steps; the final selection is `artifacts/vibe100-final.json`.

```bash
python3 find_vibe_repos.py
```

### `enrich_repos.py`

Reads `vibe100-final.json`, downloads README files, detects coding-agent names, attempts HTML-based contributor counts, reads last local git commit and rewrites the same JSON.

```bash
python3 enrich_repos.py
```

It overwrites metadata fields; preserve any manual additions before rerunning.

### `fetch_contributors.py`

Fills missing contributor counts through GitHub's contributors API and stops when the rate limit is nearly exhausted. Safe to rerun; existing counts are skipped.

```bash
python3 fetch_contributors.py
```

After metadata changes, rerun collection and clustering to refresh dependent artifacts.

## Autonomous corpus preparation

`prepare_agent_corpus.py` builds `agent300-manifest.json`: the existing 100 development repositories plus 200 new held-out repositories. Git clones have a timeout and a codeload tarball fallback with a fixed commit SHA.

`prepare_agent_run_config.py` writes the frozen model/image/prompt/budget configuration, repeat list, knowledge cutoff and test-only project keys.

`prepare_master_knowledge.py` imports human-confirmed development verdicts through `/v1/events`. `prepare_cve_snapshot.py` downloads a frozen OSV snapshot; `appsecgate_master.cve_ingest` imports it into master.

Use the Make targets from `scenario-agent.md` instead of invoking these scripts directly. The main launchers are `experiment-agent300-preflight`, `experiment-agent300-run`, and `experiment-agent300-repeat`; they do not run until explicitly selected.

## Collection, triage and reporting

### `collect_agent_funnel.py`

Collects the autonomous `asgfree` runs without reading counts from log text. It validates eligible/assigned and verdict coverage, includes TP, FP, NEEDS_REVIEW and missing findings, and writes `<prefix>-funnel.json` plus `<prefix>-review.json`.

```bash
python3 collect_agent_funnel.py --label asgfree300 --model gemmaq3 --parallelism 4
```

The review file contains every assigned finding. Existing human verdicts, reviewer, timestamps, notes and adjudication fields are preserved when the file is regenerated. The script refuses reports without structured `scan_meta` and reports with an inventory/coverage mismatch.

The older `vibe100` scripts below document the diagnostic top-10 pilot and must not be used for the new corpus.

### `collect_tp_review.py`

Combines `vibe100` and `vibe100fix` reports, collects only model TP/NEEDS_REVIEW findings, counts source/IaC files and lines, and writes:

- `artifacts/vibe100-tp-review.json`
- `artifacts/vibe100-funnel.json`
- `artifacts/vibe100-tp-review.md`

```bash
python3 collect_tp_review.py
```

### `auto_triage.py`

Applies heuristic review to the collected TP/NR rows: non-production paths, placeholders, installed/fixed version comparison and dev/prod lockfile checks. Writes `artifacts/vibe100-triage.json`.

```bash
python3 auto_triage.py
```

**Warning:** this regenerates triage and removes later human verdicts. Back up the triage JSON before rerunning, then reapply human review. Do not use it as a post-human-report formatting command.

### `export_sarif.py`

Exports final triage TPs as SARIF 2.1.0:

- `artifacts/vibe100-sarif/<repo>.sarif`: paths relative to the target repository.
- `artifacts/vibe100-all.sarif`: paths prefixed with `experiments/tp-0001/repos/<repo>/`, relative to AppSecGate root.

```bash
python3 export_sarif.py
```

SARIF Explorer stores annotations in `vibe100-all.sarif.sarifexplorer`; the exporter does not delete that sidecar. Human annotations from the completed experiment have already been merged into `vibe100-triage.json`.

### `cluster_tp.py`

Groups final TPs by cohort, language, stars, contributors, detected agents and scanner. Adds TP per 100k lines where repository volume is known.

```bash
python3 cluster_tp.py
```

Outputs `artifacts/vibe100-clusters.json` and `vibe100-clusters.md`.

### `findings_report.py`

Builds the category breakdown behind [FINDINGS.md](FINDINGS.md), extracts SCA package/version data from explanations and estimates package age in code using lockfile `git log -S`.

```bash
python3 findings_report.py
```

Output: `artifacts/vibe100-findings-analysis.json`. Ages are lower bounds for shallow clones; full clones are required for exact lifetimes.

## Recommended refresh order

When only final triage/human verdicts changed:

```bash
python3 export_sarif.py
python3 cluster_tp.py
python3 findings_report.py
```

After a new benchmark or metadata change, the full destructive-refresh sequence is:

```bash
python3 collect_tp_review.py
python3 auto_triage.py       # human verdicts must then be reapplied
python3 export_sarif.py
python3 cluster_tp.py
python3 findings_report.py
```

Narrative documents (`REPORT.md`, `FINDINGS.md`) are maintained separately from generated JSON/Markdown summaries.
