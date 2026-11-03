from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import ValidationError

from appsecgate_mcp.agent.models import AgentConfig, LlmResult, Verdict


class LlmError(RuntimeError):
    pass


class LlmProtocolError(LlmError):
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


def _content(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise LlmProtocolError("LLM returned no message content") from exc
    if not isinstance(content, str):
        raise LlmProtocolError("LLM returned invalid message content")
    if not content.strip():
        reason = getattr(response.choices[0], "finish_reason", "unknown")
        raise LlmProtocolError(f"LLM returned empty content (finish_reason={reason})")
    return content


def _response_format() -> dict[str, Any]:
    verdict_schema = {
        "type": "object",
        "properties": {
            "finding_id": {"type": "string"},
            "verdict": {
                "type": "string",
                "enum": ["TRUE_POSITIVE", "FALSE_POSITIVE", "NEEDS_REVIEW"],
            },
            "explanation": {"type": "string"},
            "patch": {},
        },
        "required": ["finding_id", "verdict", "explanation", "patch"],
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "triage_result",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"verdicts": {"type": "array", "items": verdict_schema}},
                "required": ["verdicts"],
                "additionalProperties": False,
            },
        },
    }


def _request(config: AgentConfig, payload: dict[str, Any]) -> LlmResult:
    client = _load_openai()(
        base_url=config.llm_url,
        api_key=config.llm_api_key,
        timeout=config.llm_timeout,
        max_retries=0,
    )
    try:
        response = client.chat.completions.create(
            model=config.llm_model,
            messages=[
                {"role": "system", "content": config.prompt_path.read_text(encoding="utf-8")},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format=_response_format(),
            extra_body={"think": False, "num_ctx": config.llm_num_ctx},
            temperature=config.llm_temperature,
            top_p=config.llm_top_p,
            max_tokens=config.llm_max_tokens,
        )
        raw = _content(response)
        parsed = json.loads(raw)
        result = LlmResult.model_validate(parsed)
        usage = getattr(response, "usage", None)
        if usage is not None:
            result.usage = usage.model_dump(mode="json")
        return result
    except LlmError:
        raise
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LlmProtocolError(f"LLM returned invalid protocol: {exc}") from exc
    except Exception as exc:
        raise LlmError(f"LLM request failed: {exc}") from exc


async def triage(config: AgentConfig, contexts: list[dict[str, Any]]) -> LlmResult:
    project_context = _project_context(config)
    combined = LlmResult()
    for context in contexts:
        payload = {"project_context": project_context, "contexts": [context]}
        encoded = json.dumps(payload, ensure_ascii=False)
        if len(encoded) > config.max_context_chars:
            raise LlmError(
                f"context size {len(encoded)} exceeds max_context_chars={config.max_context_chars}"
            )
        expected = {context.get("finding", {}).get("fingerprint") or context.get("finding_id")}
        expected.discard(None)
        result = None
        for attempt in range(2):
            try:
                result = await asyncio.to_thread(_request, config, payload)
                actual = [item.finding_id for item in result.verdicts]
                if len(expected) == 1 and len(result.verdicts) == 1:
                    # fuzzy-remap: модель вернула один вердикт с «почти тем» ID
                    only = next(iter(expected))
                    if actual[0] != only and actual[0].strip().lower() == only.strip().lower():
                        result.verdicts[0].finding_id = only
                        actual = [only]
                if len(actual) != len(set(actual)) or set(actual) != expected:
                    raise LlmProtocolError("LLM verdict IDs do not match supplied findings exactly")
            except LlmProtocolError:
                result = None
                if attempt == 0:
                    combined.usage["protocol_retries"] = combined.usage.get("protocol_retries", 0) + 1
                    continue
                # skip-and-continue: прогон не абортируется, находка эскалируется
                combined.usage["protocol_failures"] = combined.usage.get("protocol_failures", 0) + 1
                for fid in expected:
                    combined.verdicts.append(
                        Verdict(
                            finding_id=fid,
                            verdict="NEEDS_REVIEW",
                            explanation="protocol failure: verdict id mismatch",
                        )
                    )
                break
            break
        if result is None:
            continue
        combined.verdicts.extend(result.verdicts)
        for key, value in result.usage.items():
            if isinstance(value, int):
                combined.usage[key] = combined.usage.get(key, 0) + value
    return combined
