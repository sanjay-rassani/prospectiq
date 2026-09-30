"""Local LLM gateway.

Single seam between deterministic code and the model (spec section 15). Two protocols:

* schema-constrained JSON for general instruct models
* NuExtract template role for the extraction specialist

Deterministic Python owns retries and validation; the model never mutates state.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.services.llm.schemas import nuextract_template, strict_schema

logger = logging.getLogger(__name__)

PayloadBuilder = Callable[[int, str | None, str | None], dict[str, Any]]


@dataclass
class CallResult:
    """Everything worth persisting about one model call (spec section 15.2)."""

    ok: bool
    parsed: BaseModel | None
    raw_output: str
    model: str
    prompt_version: str
    task: str
    seconds: float
    attempts: int
    errors: list[str] = field(default_factory=list)


class LlmGateway(Protocol):
    def extract_facts(self, *, url: str, text: str) -> CallResult: ...


class OllamaGateway:
    """Production gateway talking to a local Ollama instance."""

    def __init__(
        self, settings: Settings | None = None, client: httpx.Client | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=self.settings.ollama_url,
            timeout=self.settings.llm_timeout_seconds,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> OllamaGateway:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def extract_facts(self, *, url: str, text: str) -> CallResult:
        from app.services.llm import prompts
        from app.services.llm.schemas import CompanyFacts
        from app.services.llm.untrusted import sanitize_fetched_text

        cleaned = sanitize_fetched_text(text, max_chars=self.settings.llm_max_input_chars)
        model = self.settings.extraction_model
        if "nuextract" in model.lower():
            return self.call_nuextract(
                model=model,
                document=prompts.facts_document(url, cleaned),
                output_model=CompanyFacts,
                prompt_version=prompts.PROMPT_VERSION,
                task="extract_company_facts",
                instructions=prompts.EXTRACT_FACTS_INSTRUCTIONS,
            )
        return self.call_schema(
            model=model,
            system=prompts.EXTRACT_FACTS_SYSTEM,
            user=prompts.facts_user_prompt(url, cleaned),
            output_model=CompanyFacts,
            prompt_version=prompts.PROMPT_VERSION,
            task="extract_company_facts",
        )

    def call_schema(
        self,
        *,
        model: str,
        system: str,
        user: str,
        output_model: type[BaseModel],
        prompt_version: str,
        task: str,
        max_attempts: int | None = None,
    ) -> CallResult:
        schema = strict_schema(output_model)
        attempts = max_attempts or self.settings.llm_max_attempts
        num_ctx = self.settings.llm_num_ctx

        def build(attempt: int, last_error: str | None, _last_raw: str | None) -> dict[str, Any]:
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            if attempt > 1 and last_error:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your previous reply failed validation: {last_error}\n"
                            "Return only valid JSON matching the schema."
                        ),
                    }
                )
            return {
                "model": model,
                "messages": messages,
                "format": schema,
                "stream": False,
                "options": {"temperature": 0, "num_ctx": num_ctx},
                "think": False,
            }

        return self._execute(build, model, output_model, prompt_version, task, attempts)

    def call_nuextract(
        self,
        *,
        model: str,
        document: str,
        output_model: type[BaseModel],
        prompt_version: str,
        task: str,
        instructions: str | None = None,
        max_attempts: int | None = None,
    ) -> CallResult:
        template = nuextract_template(output_model)
        attempts = max_attempts or self.settings.llm_max_attempts
        num_ctx = self.settings.llm_num_ctx

        def build(attempt: int, last_error: str | None, last_raw: str | None) -> dict[str, Any]:
            messages: list[dict[str, Any]] = [
                {"role": "template", "content": json.dumps(template, indent=4)}
            ]
            if instructions:
                messages.append({"role": "instructions", "content": instructions})
            messages.append({"role": "user", "content": document})
            if attempt > 1 and last_raw:
                messages.append({"role": "previous_output", "content": last_raw})
                messages.append(
                    {
                        "role": "instructions",
                        "content": (
                            f"The previous output was rejected: {last_error}\n"
                            "Correct it and return only JSON matching the template."
                        ),
                    }
                )
            return {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0, "num_ctx": num_ctx},
                "think": False,
            }

        return self._execute(build, model, output_model, prompt_version, task, attempts)

    def _execute(
        self,
        build_payload: PayloadBuilder,
        model: str,
        output_model: type[BaseModel],
        prompt_version: str,
        task: str,
        max_attempts: int,
    ) -> CallResult:
        errors: list[str] = []
        raw = ""
        started = time.monotonic()

        for attempt in range(1, max_attempts + 1):
            payload = build_payload(attempt, errors[-1] if errors else None, raw or None)
            try:
                response = self.client.post("/api/chat", json=payload)
                response.raise_for_status()
                raw = response.json()["message"]["content"]
            except Exception as exc:  # noqa: BLE001 - record and retry; never raise into callers
                errors.append(f"transport: {type(exc).__name__}: {exc}")
                logger.warning("llm %s attempt %s transport failure: %s", task, attempt, exc)
                continue

            try:
                parsed = output_model.model_validate(json.loads(raw))
            except (json.JSONDecodeError, ValidationError) as exc:
                errors.append(f"validation: {exc}")
                logger.warning("llm %s attempt %s validation failure: %s", task, attempt, exc)
                continue

            return CallResult(
                ok=True,
                parsed=parsed,
                raw_output=raw,
                model=model,
                prompt_version=prompt_version,
                task=task,
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
            task=task,
            seconds=time.monotonic() - started,
            attempts=max_attempts,
            errors=errors,
        )
