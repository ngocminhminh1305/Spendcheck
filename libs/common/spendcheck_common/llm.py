"""One LLM interface for Module 4 (chat agent) and Module 5 (report reader), several providers.

The provider is chosen with environment variables only, so the same image runs anywhere:

    LLM_PROVIDER=openrouter   (default) OpenRouter, including its free models. Needs OPENROUTER_API_KEY.
                              Free models allow 20 requests/minute and 50/day per account.
    LLM_PROVIDER=anthropic    Claude API. Needs ANTHROPIC_API_KEY.
    LLM_PROVIDER=bedrock      Claude in Amazon Bedrock, using AWS credentials (e.g. an EC2 role).

    LLM_MODEL                 model ID for that provider (defaults below). For OpenRouter, a
                              comma-separated list: the first is used while it is up, and
                              OpenRouter falls back to the next when one is down or busy.
    LLM_FALLBACK_MODEL        Claude only: model that retries a request the main model declines
    AWS_REGION                Bedrock only, default ap-southeast-1

Callers use two methods and never see provider formats:
    reply = llm.chat(system=..., messages=..., tools=..., max_tokens=..., effort=...)
    messages.append(reply.assistant_message); messages.extend(llm.tool_results([...]))
Tools are defined once, in Anthropic's shape ({"name", "description", "input_schema"}); the
OpenRouter client converts them to the OpenAI "function" shape.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal

import anthropic
import httpx

DEFAULT_MODELS = {
    # Free models come and go: on 20 Oct 2026 Nemotron 3 Super had 0% uptime for an hour.
    "openrouter": "nvidia/nemotron-3-super-120b-a12b:free,nvidia/nemotron-3-ultra-550b-a55b:free,"
                  "google/gemma-4-31b-it:free",
    "anthropic": "claude-opus-5-5",
    "bedrock": "claude-opus-5-5",
}
DEFAULT_FALLBACK_MODEL = "claude-opus-4-8"
# Claude models that accept a refusal fallback. Others (e.g. claude-haiku-5-5) reject the parameter.
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
BEDROCK_PREFIX = "anthropic."
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

Stop = Literal["tool_use", "end", "refusal", "max_tokens"]


class LLMError(Exception):
    """The model could not be reached or returned an error. status is the HTTP status if known."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any] | None          # None if the model sent arguments that are not valid JSON
    parse_error: str | None = None


@dataclass
class LLMReply:
    text: str
    tool_calls: list[ToolCall]
    stop: Stop
    assistant_message: dict[str, Any]     # provider-native; append it to `messages` unchanged
    usage: dict[str, Any] = field(default_factory=dict)


class LLM:
    """Base class. Subclasses implement chat() and tool_results() for one provider."""

    provider: str
    model: str

    def chat(self, *, system: str, messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int = 4096, effort: str = "medium") -> LLMReply:
        raise NotImplementedError

    def tool_results(self, results: list[tuple[str, str, bool]]) -> list[dict]:
        """Messages to append after running tools. results = [(tool_call_id, content, is_error)]."""
        raise NotImplementedError


# ---- Claude (Claude API or Bedrock) ------------------------------------------------------------

class ClaudeLLM(LLM):
    def __init__(self, client: Any, model: str, provider: str, request_defaults: dict | None = None):
        self.client, self.model, self.provider = client, model, provider
        self.request_defaults = request_defaults or {}

    def chat(self, *, system, messages, tools=None, max_tokens=4096, effort="medium") -> LLMReply:
        kwargs = dict(self.request_defaults)
        if tools:
            kwargs["tools"] = tools
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                # cache_control: the system prompt (and tools before it) is reused from the prompt cache
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                max_tokens=max_tokens,
                output_config={"effort": effort},
                **kwargs,
            )
        except anthropic.APIStatusError as err:
            raise LLMError(f"Claude API error: {err.message}", err.status_code) from err
        except anthropic.APIConnectionError as err:
            raise LLMError(f"Could not reach Claude: {err}") from err

        calls = [ToolCall(b.id, b.name, b.input) for b in response.content if b.type == "tool_use"]
        stop: Stop = {"tool_use": "tool_use", "refusal": "refusal", "max_tokens": "max_tokens"}.get(
            response.stop_reason, "end")
        return LLMReply(
            text="".join(b.text for b in response.content if b.type == "text"),
            tool_calls=calls,
            stop=stop,
            # the whole turn (thinking + tool_use blocks) must go back exactly as returned
            assistant_message={"role": "assistant", "content": response.content},
            usage={"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        )

    def tool_results(self, results):
        # Claude expects all results of one turn together, in a single user message.
        return [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call_id, "content": content, "is_error": is_error}
            for call_id, content, is_error in results
        ]}]


# ---- OpenRouter (OpenAI-compatible chat completions) -------------------------------------------

class OpenRouterLLM(LLM):
    provider = "openrouter"

    def __init__(self, api_key: str, model: str, http: httpx.Client | None = None):
        # "a,b,c": a is the main model, b and c are fallbacks OpenRouter tries in order.
        self.models = [m.strip() for m in model.split(",") if m.strip()]
        self.model = self.models[0]
        self.http = http or httpx.Client(timeout=120.0)
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Title": "Spendcheck (DSA2111)",   # shows the app name in OpenRouter's usage page
        }

    @staticmethod
    def _to_openai_tool(tool: dict) -> dict:
        return {"type": "function", "function": {
            "name": tool["name"], "description": tool["description"], "parameters": tool["input_schema"]}}

    def chat(self, *, system, messages, tools=None, max_tokens=4096, effort="medium") -> LLMReply:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": max_tokens,
            "reasoning": {"effort": effort},   # ignored by models without a reasoning mode
        }
        if len(self.models) > 1:
            body["models"] = self.models
        if tools:
            body["tools"] = [self._to_openai_tool(t) for t in tools]
        try:
            response = self.http.post(OPENROUTER_URL, json=body, headers=self.headers)
        except httpx.HTTPError as err:
            raise LLMError(f"Could not reach OpenRouter: {err}") from err

        try:
            data = response.json()
        except ValueError:   # e.g. an HTML error page from a proxy
            data = {}
        if response.status_code != 200 or "error" in data or "choices" not in data:
            message = (data.get("error") or {}).get("message", response.text[:200])
            status = (data.get("error") or {}).get("code") if response.status_code == 200 else response.status_code
            raise LLMError(f"OpenRouter error: {message}", status if isinstance(status, int) else None)

        choice = data["choices"][0]
        message = choice["message"]
        calls = []
        for tc in message.get("tool_calls") or []:
            raw = tc["function"].get("arguments") or "{}"
            try:
                calls.append(ToolCall(tc["id"], tc["function"]["name"], json.loads(raw)))
            except json.JSONDecodeError as err:
                calls.append(ToolCall(tc["id"], tc["function"]["name"], None, f"arguments are not valid JSON ({err})"))

        finish = choice.get("finish_reason")
        stop: Stop = ("tool_use" if calls else "refusal" if finish == "content_filter"
                      else "max_tokens" if finish == "length" else "end")
        assistant = {"role": "assistant", "content": message.get("content") or ""}
        if message.get("tool_calls"):
            assistant["tool_calls"] = message["tool_calls"]
        if message.get("reasoning_details"):   # some models need their reasoning passed back
            assistant["reasoning_details"] = message["reasoning_details"]
        return LLMReply(text=message.get("content") or "", tool_calls=calls, stop=stop,
                        assistant_message=assistant, usage=data.get("usage") or {})

    def tool_results(self, results):
        # OpenAI format: one "tool" message per call. There is no error flag, so say it in the text.
        return [{"role": "tool", "tool_call_id": call_id,
                 "content": f"ERROR: {content}" if is_error else content}
                for call_id, content, is_error in results]


# ---- factory -----------------------------------------------------------------------------------

def _bedrock_id(model: str) -> str:
    return model if model.startswith(BEDROCK_PREFIX) else BEDROCK_PREFIX + model


def build_llm() -> LLM:
    """Build the LLM client from environment variables (see module docstring)."""
    provider = os.getenv("LLM_PROVIDER", "openrouter").lower()
    if provider not in DEFAULT_MODELS:
        raise ValueError(f"Unknown LLM_PROVIDER {provider!r}; use openrouter, anthropic or bedrock")
    model = os.getenv("LLM_MODEL") or DEFAULT_MODELS[provider]
    fallback = os.getenv("LLM_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL)
    wants_fallback = model.removeprefix(BEDROCK_PREFIX) in FALLBACK_MODELS

    if provider == "openrouter":
        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY is not set. Create a free key at openrouter.ai and put it in .env.")
        return OpenRouterLLM(key, model)

    if provider == "anthropic":
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        defaults = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if wants_fallback else {}
        return ClaudeLLM(anthropic.Anthropic(), model, provider, defaults)

    import boto3  # installed with anthropic[bedrock]

    # The Bedrock client only looks for credentials on the first request; check now so a missing
    # role or key shows up as a clear startup message instead of a failed request.
    if boto3.Session().get_credentials() is None:
        raise RuntimeError("no AWS credentials for Bedrock (instance role, AWS_* env vars or ~/.aws).")
    middleware = [anthropic.BetaRefusalFallbackMiddleware([{"model": _bedrock_id(fallback)}])] if wants_fallback else []
    client = anthropic.AnthropicBedrockMantle(aws_region=os.getenv("AWS_REGION", "ap-southeast-1"), middleware=middleware)
    return ClaudeLLM(client, _bedrock_id(model), provider)
