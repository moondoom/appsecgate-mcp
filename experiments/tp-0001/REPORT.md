# TP-0001 Experiment Report

## 1. Scope and result

TP-0001 exercised AppSecGate's full local pipeline on real repositories:

**SAST/SCA/IaC scan → deduplication → LLM triage → fix/verify where applicable → CI gate → edge/master consistency checks.**

The work had three goals:

1. Select and freeze a local LLM for cheap triage using throughput, stability and quality measurements.
2. Verify gate behaviour in deterministic and live tests.
3. Measure the funnel on 100 popular but non-top-tier repositories, including 70 self-identified AI/vibe-coded projects and 30 conventional controls.

Final state:

- Frozen model: **gemmaq3**, `hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-Q3_K_M`, digest recorded in [stage2-freeze.json](artifacts/stage2-freeze.json).
- Gate tests: 8/8 deterministic, 3/3 live, 80/80 across ten repeated cycles.
- Stage 3: **100/100 repositories completed** after an agent robustness fix.
- Final reviewed findings: **389 true positives and 116 false positives**.
- Detailed findings: [FINDINGS.md](FINDINGS.md). Cluster analysis: [vibe100-clusters.md](artifacts/vibe100-clusters.md).

## 2. Test stand

| Component | Configuration |
|---|---|
| Host | Proxmox VE, IOMMU enabled, both GPUs passed through |
| CPU / RAM / disk | Intel i7-13700K (8P+8E), 64 GB, Samsung 980 PRO NVMe on ZFS |
| Workstation VM | 8P vCPU, 24 GB RAM, Intel UHD 770; UI and AppSecGate Docker edge |
| LLM VM | 8P vCPU, 24 GB RAM, NVIDIA RTX 4060 Ti 16 GB; headless inference |
| Inference | Ollama and LiteLLM on the LLM VM (private endpoints) |
| Metrics | Prometheus on the LLM VM, GPU and LiteLLM time series |
| Master | AppSecGate master + PostgreSQL in Docker Compose |
| Electricity model | 3.56 RUB/kWh; measured GPU power plus 150 W for CPU, board, RAM, storage and workstation VM |

The attempted GPU power-limit unlock was **not used in the final measurements**: it failed to reset WPR2 and was rolled back. Cost and throughput figures therefore describe the stock RTX 4060 Ti setup.

Sources: [progress.json](progress.json), [cost-system-baseline.json](artifacts/cost-system-baseline.json), [decode-tps-baseline.json](artifacts/decode-tps-baseline.json).

## 3. Stages and artifacts

### Stage 1 — acceptance cycles

Thirty acceptance runs completed with stability, CI correctness and master score at 1.0; 135/135 gate tests passed. Early model comparisons also showed that patch application and finding triage are separate capabilities: a model can produce good verdicts while producing unusable patches.

Machine-readable status and historical metrics: [progress.json](progress.json). Original scenario and known limitations: [scenario.md](scenario.md), [fault_injection.md](fault_injection.md).

### Stage 2.0 — expanded model benchmark

Twenty representative OSS repositories were scanned at parallelism 4, `num_ctx=4096`, synchronization enabled. Each model used the same agent and prompts. Ground truth contained 63 positions: 54 user-reviewed and 9 reachability-based decisions subsequently confirmed by the user. Only three positions were TPs, so F1 is a useful discriminator on this fixture but not a universal quality estimate.

Artifacts:

- Benchmarks: [oss20-benchmark.json](artifacts/oss20-benchmark.json) and the other `artifacts/oss20-benchmark-*.json` files.
- Ground truth: [oss20-ground-truth.json](artifacts/oss20-ground-truth.json).
- F1 scores: [oss20-f1-scores.json](artifacts/oss20-f1-scores.json).
- System cost: [cost-system-baseline.json](artifacts/cost-system-baseline.json).

### Stage 2.1–2.3 — gate verification and freeze

- `gate21`: deterministic mock LLM, T-01 through T-08, **8/8**.
- `gate23`: live gemmaq3, T-01/T-04/T-07, **3/3**, with Prometheus evidence.
- `gate30`–`gate39`: ten deterministic cycles, **80/80**, stability 1.0. Serial execution was intentional to isolate correctness from GPU contention.

Artifacts: [gate21-gate-results.json](artifacts/gate21-gate-results.json), [gate23-live-results.json](artifacts/gate23-live-results.json), `artifacts/gate30-gate-results.json` through `gate39-gate-results.json`.

The final selection rule was **throughput-first among candidates with complete successful runs; F1 and precision as secondary quality checks**. gemmaq3 was frozen before the 100-repository run.

### Stage 3.0 — 100 repositories

Sourcing used GitHub Search API queries for explicit AI/vibe-code signals and a conventional control cohort. The final set contained 70 vibe and 30 contrast repositories. Metadata included stars, languages, detected agents, contributors and last commit.

Artifacts: [vibe100-final.json](artifacts/vibe100-final.json), [vibe100-benchmark.json](artifacts/vibe100-benchmark.json), [vibe100fix-benchmark.json](artifacts/vibe100fix-benchmark.json), [vibe100-funnel.json](artifacts/vibe100-funnel.json).

## 4. Model comparison

Speed is repositories/minute and median repository wall time at p4 unless noted. F1/precision are measured against the small 63-position critical ground truth. Cost is system-level RUB per one million generated tokens; it is unavailable for the external API and not directly comparable to provider pricing.

| Model | Successful runs | rpm | p50, s | p95, s | RUB/1M tok | F1 | Precision | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| **gemmaq3 (frozen)** | 20/20 | **4.40** | 35.8 | 126.4 | **0.61** | 0.143 | 0.077 | Best local speed/cost balance |
| deepseek-v4.1-flash (external) | 20/20 | 6.45 | 32.3 | 57.4 | — | **0.375** | **0.231** | Fastest and best F1, but external |
| gemma4:12b | 20/20 | 4.01 | 35.0 | 148.0 | 0.72 | 0.115 | 0.061 | Fast, weaker critical-set F1 |
| qwen3.5:4b | 18/20 | 5.39 | 33.4 | 111.7 | 0.63 | 0.250 | 0.143 | Fast but incomplete |
| qwen3.8 GSQ IQ3_S | 20/20 | 2.06 | 67.1 | 316.7 | 1.59 | 0.194 | 0.107 | No advantage over gemmaq3 |
| qwen3.8 Q3_K_M | 20/20 | 1.85 | 79.2 | 346.7 | 1.85 | 0.261 | 0.150 | Faster than Q4; same 3 TP, fewer FP on this fixture |
| gemma4:26b QAT | 20/20 | 2.32 | 64.9 | 265.2 | 1.00 | 0.146 | 0.079 | Q3 replacement is 1.9× faster |
| glm-4.7-flash Q4 | 18/20 | 1.60 | 75.0 | 329.3 | 2.36 | 0.300 | 0.176 | Good F1, incomplete and CPU-offloaded |
| glm Q3_K_XL | 17/20 at p1 | 2.17 | 17.7 | 111.7 | — | 0.240 | 0.140 | p4/p2 do not fit VRAM |
| qwen3.8:27b Q4 | 20/20 | 0.85 | 157.6 | 725.8 | 2.82 | 0.214 | 0.120 | Too slow; D2 p95 exceeded |
| qwen3.8 MTP Q4 | 20/20 | 0.90 | 168.1 | 700.9 | 2.68 | 0.231 | 0.130 | Speculation gave little under p4 |
| qwen3.5:9b | 16/20 | 3.45 | 43.7 | 180.2 | 1.38 | **0.000** | 0.000 | Disqualified: zero TP, four errors |

Quality conclusions:

- Every successful local model preserved recall on the three ground-truth TPs except qwen3.5:9b. Low precision is expected of a deliberately permissive cheap-triage stage, but it creates substantial human workload.
- The external DeepSeek baseline was strongest on F1 and speed; it is not an offline/local candidate.
- Quantization is model-specific: gemma Q3 improved throughput without losing the three critical TPs. Qwen Q3 also preserved all three and produced fewer FP than Q4 on this fixture, but remained much slower than gemmaq3; these three TPs are insufficient for a general quality ranking.
- Stage 3 is a separate, larger measurement: after automated and human review, **80.0% of gemmaq3's TRUE_POSITIVE verdicts remained TP** (348 of 435 before the final human corrections; final TP total is 389 including NEEDS_REVIEW promotions). This is not comparable to the three-TP oss20 F1.

## 5. Agent changes during the experiment

Fourteen Stage 3 runs initially aborted with `LLM verdict IDs do not match supplied findings exactly`. One malformed verdict discarded the entire repository result.

The agent was changed in `mcp-server/src/appsecgate_mcp/agent/llm.py`:

1. A case-insensitive single-ID fuzzy remap accepts an unambiguous model response.
2. After two failed protocol attempts, only the affected finding becomes `NEEDS_REVIEW`; the run continues.
3. `usage.protocol_failures` records degraded findings.
4. Regression tests cover fuzzy remapping and persistent mismatch.

`make check` passed (515 MCP + 143 master + 8 agent tests), and the Docker image was rebuilt. The 14 failed repositories then completed **14/14** in 620 seconds with zero protocol failures. The aggregate Stage 3 result is 100/100.

## 6. Stage 3 funnel and triage

| Step | Count |
|---|---:|
| Source/IaC files | 58,446 |
| Source/IaC lines | 13,485,009 |
| Raw scanner findings | 4,931 |
| Deduplicated findings shown to the agent (top 10 per repository) | 574 |
| Model TRUE_POSITIVE | 435 |
| Model NEEDS_REVIEW | 70 |
| Model FALSE_POSITIVE | 59 |
| Shown findings without a model verdict | 10 |
| Reviewed model TP/NR | 505 |
| Final human-adjusted TRUE_POSITIVE | **389** |
| Final FALSE_POSITIVE among reviewed TP/NR | **116** |

The `scan_project` response exposes only its severity-ranked top 10 findings, so 574 is the reviewed funnel's input, not the complete deduplicated corpus. The 564 model verdicts account for 435 TP + 70 NR + 59 FP; ten shown findings have no verdict. Only model TP and NEEDS_REVIEW findings were manually triaged, per the experiment protocol. Automated heuristics checked non-production paths, placeholders, installed/fixed versions and lockfile dependency type. The final TP list was exported to SARIF 2.1.0:

- Per-repository files: `artifacts/vibe100-sarif/<repo>.sarif`, paths relative to each target repository.
- Combined file: [vibe100-all.sarif](artifacts/vibe100-all.sarif), paths relative to the AppSecGate repository root.
- Human SARIF Explorer annotations: [vibe100-all.sarif.sarifexplorer](artifacts/vibe100-all.sarif.sarifexplorer). Twenty-four annotations were mapped back into triage; human verdicts took priority and seven automated TPs were corrected to FP.

Cluster results are in [vibe100-clusters.md](artifacts/vibe100-clusters.md). The key caveat is that absolute TP counts do not establish a vibe-code effect: vibe and contrast cohorts are nearly identical after line normalization (3.9 vs 3.8 TP per 100k lines). Small repositories and small contributor teams have much higher finding density.

## 7. Reproduction and remaining limitations

See [SCRIPTS.md](SCRIPTS.md) for all commands and [FINDINGS.md](FINDINGS.md) for category-level results.

- SCA TP means a vulnerable locked version and policy acceptance, not proof of runtime exploitability.
- The top-10 output limit hides part of the deduplicated corpus; the separate effects of deduplication and output truncation were not measured.
- The 59 model FALSE_POSITIVE verdicts were not reviewed, so Stage 3 recall is unknown.
- Forty repositories still lack contributor counts because of GitHub rate limiting; affected cluster labels are `unknown`.
- SCA ages are lower bounds from shallow clones, not vulnerability disclosure-to-fix durations.
- The three-TP oss20 ground truth is too small to rank models by general triage quality with high confidence.
