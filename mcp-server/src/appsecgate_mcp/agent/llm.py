from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from appsecgate_mcp.agent.controller import AgentController
from appsecgate_mcp.agent.models import AgentConfig, LlmResult


class LlmError(RuntimeError):
    pass


class LlmProtocolError(LlmError):
    pass


class LlmTimeoutError(LlmError):
    pass


def _load_openai():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LlmError("OpenAI client is not installed; install appsecgate-mcp[agent]") from exc
    return OpenAI


def _project_context(config: AgentConfig) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("AGENTS.md", ".appsecgate.yaml", ".appsecgate.yml"):
        path = config.project / name
        if path.is_file():
            result[name] = path.read_text(encoding="utf-8")[:20_000]
    return result


def _request(
    config: AgentConfig,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int | None = None,
) -> Any:
    request_timeout = (
        config.llm_failure_timeout if config.agent_mode == "guided" else config.llm_timeout
    )
    client = _load_openai()(
        base_url=config.llm_url,
        api_key=config.llm_api_key,
        timeout=request_timeout,
        max_retries=0,
    )
    for attempt in (0, 1):
        try:
            return client.chat.completions.create(
                model=config.llm_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                extra_body={"think": False, "num_ctx": config.llm_num_ctx},
                temperature=config.llm_temperature,
                top_p=config.llm_top_p,
                max_tokens=max_tokens or config.llm_max_tokens,
            )
        except Exception as exc:
            marker = f"{type(exc).__name__} {exc}".lower()
            if "timeout" in marker or "timed out" in marker:
                raise LlmTimeoutError(f"LLM request timed out: {exc}") from exc
            # GD-15: one transient transport retry (5xx / connection reset);
            # never on timeout or invalid output (ADR-0019 GD-9).
            status_code = getattr(exc, "status_code", None)
            transient = (isinstance(status_code, int) and status_code >= 500) or (
                "connection" in marker or "reset" in marker
            )
            if attempt == 0 and transient:
                time.sleep(1)
                continue
            raise LlmError(f"LLM request failed: {exc}") from exc
    raise LlmError("unreachable")


def _message(response: Any) -> Any:
    try:
        return response.choices[0].message
    except (AttributeError, IndexError, TypeError) as exc:
        raise LlmProtocolError("LLM returned no message") from exc


def _response_usage(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        key: value for key, value in usage.model_dump(mode="json").items() if isinstance(value, int)
    }


def _add_usage(target: dict[str, Any], response: Any) -> None:
    for key, value in _response_usage(response).items():
        target[key] = target.get(key, 0) + value


def _checkpoint_messages(
    config: AgentConfig,
    controller: AgentController,
    project_context: dict[str, str],
    reason: str,
) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": config.prompt_path.read_text(encoding="utf-8")},
        {
            "role": "user",
            "content": json.dumps(
                controller.checkpoint_payload(project_context, reason=reason), ensure_ascii=False
            ),
        },
    ]


async def triage(config: AgentConfig, controller: AgentController) -> LlmResult:
    project_context = _project_context(config)
    messages = _checkpoint_messages(config, controller, project_context, "initial")
    tools = controller.tool_schemas()
    llm_usage: dict[str, Any] = {}
    if config.reuse_verdicts:
        from appsecgate_mcp.agent.reuse import reuse_prior_verdicts

        stats: dict[str, int] = {}
        await reuse_prior_verdicts(config, controller, stats)
        llm_usage.update(stats)
        if not controller.pending:
            result = controller.result()
            result.usage = {**llm_usage, **result.usage, "iterations": 0}
            return result
    iterations = 0
    limit_reason = ""
    while iterations < config.max_iterations:
        iterations += 1
        context_size = len(json.dumps(messages, ensure_ascii=False, default=str))
        if context_size > config.max_context_chars:
            if controller.metrics["compactions"] >= config.max_compactions:
                limit_reason = "compaction_limit_reached"
                break
            controller.compact()
            messages = _checkpoint_messages(config, controller, project_context, "compaction")
            continue
        try:
            response = await asyncio.to_thread(_request, config, messages, tools)
        except LlmError as exc:
            if "token repeat limit reached" not in str(exc):
                raise
            if controller.metrics["restarts"] >= config.max_restarts:
                limit_reason = "provider_repeat_limit_reached"
                break
            controller.metrics["provider_repeat_restarts"] += 1
            controller.restart()
            messages = _checkpoint_messages(
                config, controller, project_context, "provider_repeat_restart"
            )
            continue
        _add_usage(llm_usage, response)
        message = _message(response)
        messages.append(message.model_dump(exclude_none=True))
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            if not controller.pending:
                break
            messages.append(
                {
                    "role": "user",
                    "content": json.dumps(controller.pending_payload(), ensure_ascii=False),
                }
            )
            continue
        for call in tool_calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("tool arguments must be an object")
            except (json.JSONDecodeError, ValueError) as exc:
                controller.metrics["tool_errors"] += 1
                result = {"status": "error", "reason": f"invalid tool arguments: {exc}"}
            else:
                result = await controller.execute(call.function.name, arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.function.name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )
        if controller.restart_required:
            if controller.metrics["restarts"] >= config.max_restarts:
                limit_reason = "restart_limit_reached"
                break
            controller.restart()
            messages = _checkpoint_messages(config, controller, project_context, "loop_restart")
    result = controller.result()
    result.usage = {**llm_usage, **result.usage, "iterations": iterations}
    if limit_reason:
        result.usage[limit_reason] = 1
    elif controller.pending and iterations >= config.max_iterations:
        result.usage["iteration_limit_reached"] = 1
    return result
