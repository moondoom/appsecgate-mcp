# TP-0001 Findings Report

## 1. Dataset and review status

This public report contains **aggregate statistics only**. Repository names, vulnerable file paths and per-project findings are intentionally excluded. Detailed local artifacts remain outside git.

The report covers **389 final true positives** from 100 successfully scanned repositories. The model produced 435 TRUE_POSITIVE and 70 NEEDS_REVIEW verdicts; only those 505 findings entered manual/automated triage. Final review also classified 116 findings as false positives.

| Category | Scanner | Final TP | Share |
|---|---|---:|---:|
| SCA: vulnerable dependencies | Trivy CVE/GHSA | **371** | 95.4% |
| Docker/IaC misconfiguration | Trivy DS/AWS | **13** | 3.3% |
| Secrets | Gitleaks | **4** | 1.0% |
| SAST: code-level execution flaw | Semgrep | **1** | 0.3% |

The distribution means this experiment primarily measured dependency-review throughput, not broad SAST detection quality. Local-only source data is `artifacts/vibe100-triage.json`; regenerate aggregate analysis with `python3 findings_report.py`.

## 2. Secrets — 4 TP

Four committed credentials or sensitive identifiers were confirmed across client-side code, deployment configuration, build automation and backend code. No values, repository names or exact locations are published.

Common rejected candidates were variable names containing `key`, enum strings, documentation examples, placeholders and test vectors. Human review corrected several automated secret verdicts.

## 3. SAST — 1 TP

One production-code execution finding was confirmed: unnecessary `subprocess` shell execution on a locally resolved path. Several SSRF candidates were rejected after code review because remote URL retrieval was the intended application behaviour or used owner-controlled configuration.

## 4. SCA — 371 TP

### Severity and ecosystems

- **157 critical**, **214 high**.
- npm: **276** findings across `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock` and `bun.lock`.
- PyPI: **82** across `requirements.txt` and `uv.lock`.
- Go: **11** in `go.mod`.
- crates.io: **2** in `Cargo.lock`.

### Most frequent vulnerability IDs

| CVE/GHSA | Findings |
|---|---:|
| CVE-2026-90711 | 15 |
| CVE-2026-102276 | 12 |
| CVE-2026-111181 | 11 |
| CVE-2026-102278 | 10 |
| CVE-2026-59873 | 8 |
| CVE-2026-101898 | 7 |
| CVE-2026-75604 | 7 |
| GHSA-2464-fhr4-w9xw | 7 |
| GHSA-2xp9-vwfh-vxw4 | 7 |
| CVE-2026-101901 | 6 |

### Packages with the most findings

| Package | Findings | Affected repository count |
|---|---:|---:|
| `brace-expansion` | 26 | 10 |
| `tar` | 17 | 8 |
| `axios` | 12 | 7 |
| `pillow` | 11 | 3 |
| `proxy-addr` | 10 | 8 |
| `transformers` | 10 | 2 |
| `gradio` | 9 | 2 |
| `Next.js` | 9 | 6 |
| `body-parser` | 8 | 7 |

Package extraction was unavailable for 106 findings whose model explanations did not contain a parseable name/version. Their vulnerability IDs and lockfile formats remain represented in aggregate counts.

### Age of the most frequent critical vulnerabilities

For each of the five most frequent critical IDs, the analyzer selected one finding with a parseable package and searched lockfile history using `git log -S<package>`. “Age” is the time from the first reachable package-adding commit to the scan date (2026-11-03). It is **not** vulnerability disclosure age or proof of exploitability throughout that period.

Available histories came from shallow clones, so values are **minimum observable ages**, not exact lifetimes. Project identities are withheld.

| Vulnerability | Example package and version | First reachable introduction | Minimum age |
|---|---|---|---:|
| CVE-2026-90711 | `proxy-addr 2.0.7` → fixed 2.0.8 | 2026-09-12 | **51 days** |
| CVE-2026-59873 | `tar 6.2.1` → fixed 7.5.19 | 2026-02-02 | **272 days** |
| CVE-2026-75604 | `next 15.5.15` | 2026-10-23 | **10 days** |
| GHSA-2464-fhr4-w9xw | `Next.js 16.2.7` | Not found in reachable history | Unknown |
| GHSA-2xp9-vwfh-vxw4 | `Next.js 15.5.15` | Not found in reachable history | Unknown |

Exact ages require full repository history.

### Interpretation limits

An SCA TP means that the scanner matched a vulnerable version and review policy accepted it. It does not prove production reachability: dev-only dependencies, indirect dependencies and unused vulnerable paths can remain. Lockfile findings were treated as TP under the Stage 3 policy when dev/prod status could not be established.

## 5. Docker and IaC — 13 TP

| Rule | Count | Aggregate meaning |
|---|---:|---|
| `DS-0002` | 6 | Container runs as root or has no non-root USER |
| `DS-0029` | 6 | `apt-get` usage without recommended pinning/cleanup hygiene |
| `AWS-0104` | 1 | Security-group ingress on port 443 from `0.0.0.0/0` |

One Terraform candidate was rejected because the reviewed configuration disabled public IPv4 access.

## 6. Cohort observations

Normalized comparison does **not** show a higher TP density in self-identified vibe-coded projects: **3.9 versus 3.8 TP per 100k source/IaC lines** for vibe and contrast cohorts respectively.

Stronger density signals are repository maturity and team size: projects with fewer than 100 stars show **34.8 TP/100k lines**, and teams with up to five contributors show **21.4 TP/100k lines**. These are observational correlations, not causal estimates. Forty repositories still have unknown contributor counts because of API rate limiting.

Detailed cluster and triage artifacts contain project identifiers and are intentionally kept outside the public repository.
