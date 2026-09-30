"""Minimal Ollama client for the spike.

Deliberately thin and dependency-free beyond httpx, because this is the seam that becomes
app/services/llm in Phase 3. Nothing here should need LangChain to exist.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from schemas import strict_schema

OLLAMA_URL = "http://127.0.0.1:11434"


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


def call(
    model: str,
    system: str,
    user: str,
    output_model: type[BaseModel],
    prompt_version: str,
    max_attempts: int = 3,
    timeout: float = 600.0,
) -> CallResult:
    """Call Ollama with grammar-constrained JSON output, validating against a Pydantic model.

    Constrained decoding guarantees the *shape* of the output, not its correctness, so the
    Pydantic validation and retry loop stay in place regardless.
    """
    schema = strict_schema(output_model)
    errors: list[str] = []
    raw = ""
    started = time.monotonic()

    for attempt in range(1, max_attempts + 1):
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,
            "stream": False,
            # Extraction must be reproducible: same page, same answer.
            "options": {"temperature": 0, "num_ctx": 8192},
            # Reasoning traces waste minutes of CPU time for no gain on extraction.
            "think": False,
        }
        if attempt > 1:
            payload["messages"].append(
                {
                    "role": "user",
                    "content": (
                        f"Your previous reply failed validation: {errors[-1]}\n"
                        "Return only valid JSON matching the schema."
                    ),
                }
            )

        try:
            response = httpx.post(
                f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout
            )
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


def available_models() -> list[str]:
    response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10)
    response.raise_for_status()
    return [m["name"] for m in response.json().get("models", [])]
