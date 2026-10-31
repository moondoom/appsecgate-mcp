"""CLI точка входа E2E-харнесса: ``cd scripts && python3 -m e2e_measure ...``."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from subprocess import run as subprocess_run
from typing import Any

from e2e_measure.report import E2eReport
from e2e_measure.scenarios.reconcile import run_reconcile_scenarios
from e2e_measure.scenarios.sessions import run_e2e_session, run_parallel_sessions
from e2e_measure.scenarios.t14 import run_fix_verify_scenarios, run_git_diff_scenarios, run_memory_scenario

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("e2e_measure")


def main() -> None:
    parser = argparse.ArgumentParser(description="AppSecGate MCP E2E test runner")
    parser.add_argument("--project-path", required=True)
    parser.add_argument("--other-project-path", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--skip-parallel", action="store_true")
    args = parser.parse_args()

    resolved = str(Path(args.project_path).resolve())
    if not Path(resolved).is_dir():
        sys.exit(f"Error: directory not found: {resolved}")

    other_resolved = None
    if args.other_project_path:
        other_resolved = str(Path(args.other_project_path).resolve())
        if not Path(other_resolved).is_dir():
            sys.exit(f"Error: other-project directory not found: {other_resolved}")

    async def run_all() -> dict[str, Any]:
        report = E2eReport(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            project_path=resolved,
        )
        # Свежий data volume на каждый прогон: shown_findings.db живёт там,
        # и чистая история (SHOWN/верификации) между прогонами важнее, чем
        # переиспользование. Suppressions после T7 изолированы по project_id,
        # но показанная история остаётся общей для проекта. Кэш-волум
        # (контентно-адресуемый) шарим — это безопасно.
        data_volume = f"appsecgate-data-e2e-{uuid.uuid4().hex[:12]}"
        try:
            subprocess_run(
                ["docker", "volume", "create", data_volume], check=True, capture_output=True
            )
        except Exception as exc:
            logger.error("Failed to create data volume %s: %s", data_volume, exc)
            raise

        try:
            # Параллельные сессии запускаем ДО основного прогона: после T7
            # suppressions изолированы по project_id (SuppressionStore), но
            # показанная история (SHOWN) у other-project должна быть чистой на
            # старте — поэтому параллельный скан идёт раньше мутаций funnel.
            if other_resolved and not args.skip_parallel:
                logger.info("=" * 60)
                logger.info("E2E: parallel sessions (before mutations)")
                logger.info("=" * 60)
                pr = await run_parallel_sessions(resolved, other_resolved, data_volume)
                report.results.extend(pr.results)
            logger.info("=" * 60)
            logger.info("E2E: running for %s", resolved)
            logger.info("=" * 60)
            funnel = await run_e2e_session(resolved, data_volume)
            report.results.extend(funnel.results)
            # T14 iteration-2: verify fixed/wont_fix, staged-diff (B5), память (E1).
            # Свежий volume: после T7 suppressions изолированы по project_id,
            # но чистая история SHOWN нужна для verify-сценариев — находки из
            # funnel-прогона (тот же контент → тот же fingerprint) не должны
            # считаться «уже показанными».
            t14_volume = f"appsecgate-data-e2e-t14-{uuid.uuid4().hex[:12]}"
            subprocess_run(
                ["docker", "volume", "create", t14_volume], check=True, capture_output=True
            )
            try:
                await run_fix_verify_scenarios(resolved, t14_volume, report)
                await run_git_diff_scenarios(resolved, t14_volume, report)
                await run_memory_scenario(resolved, t14_volume, report)
                # T14 итерация 3 (PR-E): reconciliation scan_project (ADR-0005 §3.4).
                await run_reconcile_scenarios(resolved, t14_volume, report)
            finally:
                subprocess_run(["docker", "volume", "rm", "-f", t14_volume], capture_output=True)
        finally:
            subprocess_run(
                ["docker", "volume", "rm", "-f", data_volume],
                capture_output=True,
            )
        logger.info("")
        logger.info("=" * 60)
        logger.info("SUMMARY: %s", report.summary())
        logger.info("=" * 60)
        return report.to_dict()

    result = asyncio.run(run_all())
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        logger.info("Report saved: %s", out_path)
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
