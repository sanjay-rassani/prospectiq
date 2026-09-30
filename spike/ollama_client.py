"""Minimal Ollama client for the spike.

Deliberately thin and dependency-free beyond httpx, because this is the seam that becomes
app/services/llm in Phase 3. Nothing here should need LangChain to exist.

Two protocols, because the two models want different things:

* `call_schema` -- ordinary instruct models. System prompt plus grammar-constrained JSON
  via Ollama's `format` parameter. Used for hypothesis generation and drafting.
* `call_nuextract` -- NuExtract3, which takes no system prompt. It expects a template in
  its own vocabulary via a `template` message role, with `instructions` standing in for
  the system prompt. Used for fact and signal extraction.

Both validate with Pydantic and retry, because constrained decoding and specialist
training both guarantee shape, never correctness.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError
from schemas import nuextract_template, strict_schema

OLLAMA_URL = "http://127.0.0.1:11434"

# The KV cache at NuExtract's default 131072-token context would not fit in the RAM
# available on this machine. Pages are truncated to match.
NUM_CTX = 8192


@dataclass
class CallResult:
    """Everything worth knowing about one model call, including the failures.

    Spec section 15.2 requires persisting model name, prompt version, and output for
    debugging. The spike records the same fields so the production gateway can inherit
    the shape.
    """

    ok: bool
    parsed: BaseModel | None
    raw_output: str
    model: str
    prompt_version: str
    seconds: float
    attempts: int
    errors: list[str] = field(default_factory=list)


PayloadBuilder = Callable[[int, str | None, str | None], dict[str, Any]]


def _execute(
    build_payload: PayloadBuilder,
    model: str,
    output_model: type[BaseModel],
    prompt_version: str,
    max_attempts: int,
    timeout: float,
) -> CallResult:
    """Shared validate-and-retry loop. `build_payload` receives (attempt, last_error, last_raw)."""
    errors: list[str] = []
    raw = ""
    started = time.monotonic()

    for attempt in range(1, max_attempts + 1):
        payload = build_payload(attempt, errors[-1] if errors else None, raw or None)

        try:
            response = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
            response.raise_for_status()
            raw = response.json()["message"]["content"]
        except Exception as exc:  # noqa: BLE001 - spike: record anything that goes wrong
            errors.append(f"transport: {type(exc).__name__}: {exc}")
            continue

        try:
            parsed = output_model.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            errors.append(f"validation: {exc}")
            continue

        return CallResult(
            ok=True,
            parsed=parsed,
            raw_output=raw,
            model=model,
            prompt_version=prompt_version,
            seconds=time.monotonic() - started,
            attempts=attempt,
            errors=errors,
        )

    return CallResult(
        ok=False,
        parsed=None,
        raw_output=raw,
        model=model,
        prompt_version=prompt_version,
        seconds=time.monotonic() - started,
        attempts=max_attempts,
        errors=errors,
    )


def call_schema(
    model: str,
    system: str,
    user: str,
    output_model: type[BaseModel],
    prompt_version: str,
    max_attempts: int = 3,
    timeout: float = 600.0,
) -> CallResult:
    """Standard instruct-model call with grammar-constrained JSON output."""
    schema = strict_schema(output_model)

    def build(attempt: int, last_error: str | None, _last_raw: str | None) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if attempt > 1 and last_error:
            messages.append({
                "role": "user",
                "content": (
                    f"Your previous reply failed validation: {last_error}\n"
                    "Return only valid JSON matching the schema."
                ),
            })
        return {
            "model": model,
            "messages": messages,
            "format": schema,
            "stream": False,
            # Extraction must be reproducible: same page, same answer.
            "options": {"temperature": 0, "num_ctx": NUM_CTX},
            # Reasoning traces waste minutes of CPU time for no gain here.
            "think": False,
        }

    return _execute(build, model, output_model, prompt_version, max_attempts, timeout)


def call_nuextract(
    model: str,
    document: str,
    output_model: type[BaseModel],
    prompt_version: str,
    instructions: str | None = None,
    max_attempts: int = 3,
    timeout: float = 600.0,
) -> CallResult:
    """NuExtract3 call using its native template protocol.

    No `format` parameter: the model is trained to emit JSON matching the template, and
    imposing a second grammar on top risks fighting that training. Pydantic still
    validates the result.
    """
    template = nuextract_template(output_model)

    def build(attempt: int, last_error: str | None, last_raw: str | None) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "template", "content": json.dumps(template, indent=4)}
        ]
        if instructions:
            messages.append({"role": "instructions", "content": instructions})
        messages.append({"role": "user", "content": document})
        if attempt > 1 and last_raw:
            # NuExtract has a purpose-built role for refining a prior answer, which is a
            # better fit for correction than appending a scolding user turn.
            messages.append({"role": "previous_output", "content": last_raw})
            messages.append({
                "role": "instructions",
                "content": (
                    f"The previous output was rejected: {last_error}\n"
                    "Correct it and return only JSON matching the template."
                ),
            })
        return {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": NUM_CTX},
            # NuMind recommends non-thinking mode for deterministic extraction.
            "think": False,
        }

    return _execute(build, model, output_model, prompt_version, max_attempts, timeout)


def available_models() -> list[str]:
    response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10)
    response.raise_for_status()
    return [m["name"] for m in response.json().get("models", [])]


def is_installed(model: str, installed: list[str]) -> bool:
    """Tolerate the implicit `:latest` tag, which /api/tags reports but users omit."""
    candidates = {model, f"{model}:latest", model.removesuffix(":latest")}
    return any(c in installed for c in candidates)
