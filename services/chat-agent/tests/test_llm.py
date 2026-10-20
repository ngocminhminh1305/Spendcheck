"""Unit tests for the provider adapters in spendcheck_common.llm, using fake HTTP / SDK responses.

Checks that the OpenRouter and Claude adapters build the right requests and turn every kind of
response (answer, tool calls, broken arguments, errors, rate limits) into the same LLMReply.
"""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from spendcheck_common.llm import ClaudeLLM, LLMError, OpenRouterLLM, build_llm

TOOL = {"name": "run_sql", "description": "Run SQL", "strict": True,
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}


def openrouter_with(response_json=None, status=200, seen=None, model="some/model:free"):
    """An OpenRouterLLM whose HTTP calls return `response_json`; requests are appended to `seen`."""
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(status, json=response_json)
    return OpenRouterLLM("test-key", model, http=httpx.Client(transport=httpx.MockTransport(handler)))


def completion(message, finish="stop"):
    return {"choices": [{"message": message, "finish_reason": finish}], "usage": {"prompt_tokens": 10}}


class OpenRouterAdapter(unittest.TestCase):
    def test_request_body(self):
        seen = []
        llm = openrouter_with(completion({"content": "Hi"}), seen=seen)
        llm.chat(system="SYS", messages=[{"role": "user", "content": "hello"}], tools=[TOOL], max_tokens=99, effort="low")
        body = seen[0]
        self.assertEqual(body["model"], "some/model:free")
        self.assertEqual(body["messages"][0], {"role": "system", "content": "SYS"})
        self.assertEqual(body["tools"][0]["function"]["name"], "run_sql")
        self.assertEqual(body["tools"][0]["function"]["parameters"], TOOL["input_schema"])
        self.assertEqual(body["max_tokens"], 99)
        self.assertEqual(body["reasoning"], {"effort": "low"})

    def test_plain_answer(self):
        r = openrouter_with(completion({"content": "You spent $5."})).chat(system="s", messages=[])
        self.assertEqual((r.stop, r.text, r.tool_calls), ("end", "You spent $5.", []))

    def test_tool_calls_and_results(self):
        msg = {"content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "run_sql", "arguments": '{"query": "SELECT 1"}'}},
            {"id": "c2", "type": "function", "function": {"name": "run_sql", "arguments": '{"query": '}},
        ]}
        llm = openrouter_with(completion(msg, "tool_calls"))
        r = llm.chat(system="s", messages=[], tools=[TOOL])
        self.assertEqual(r.stop, "tool_use")
        self.assertEqual(r.tool_calls[0].input, {"query": "SELECT 1"})
        self.assertIsNone(r.tool_calls[1].input)                        # broken JSON is flagged, not raised
        self.assertIn("not valid JSON", r.tool_calls[1].parse_error)
        self.assertEqual(r.assistant_message["tool_calls"], msg["tool_calls"])
        self.assertEqual(llm.tool_results([("c1", "rows", False), ("c2", "bad", True)]), [
            {"role": "tool", "tool_call_id": "c1", "content": "rows"},
            {"role": "tool", "tool_call_id": "c2", "content": "ERROR: bad"},
        ])

    def test_rate_limit_and_errors(self):
        with self.assertRaises(LLMError) as ctx:
            openrouter_with({"error": {"message": "Rate limit exceeded", "code": 429}}, status=429).chat(system="s", messages=[])
        self.assertEqual(ctx.exception.status, 429)
        with self.assertRaises(LLMError):   # some upstream errors arrive with HTTP 200
            openrouter_with({"error": {"message": "Provider returned error", "code": 502}}).chat(system="s", messages=[])

    def test_content_filter_is_a_refusal(self):
        r = openrouter_with(completion({"content": ""}, "content_filter")).chat(system="s", messages=[])
        self.assertEqual(r.stop, "refusal")


class ClaudeAdapter(unittest.TestCase):
    def fake_client(self, content, stop_reason, seen):
        def create(**kwargs):
            seen.append(kwargs)
            return SimpleNamespace(content=content, stop_reason=stop_reason,
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=2))
        return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))

    def test_tool_use_turn(self):
        seen = []
        blocks = [SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="Checking."),
                  SimpleNamespace(type="tool_use", id="t1", name="run_sql", input={"query": "q"})]
        llm = ClaudeLLM(self.fake_client(blocks, "tool_use", seen), "claude-haiku-5-5", "anthropic")
        r = llm.chat(system="SYS", messages=[], tools=[TOOL], effort="low")
        self.assertEqual((r.stop, r.text, r.tool_calls[0].id), ("tool_use", "Checking.", "t1"))
        self.assertIs(r.assistant_message["content"], blocks)          # thinking blocks kept unchanged
        self.assertEqual(seen[0]["system"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(seen[0]["output_config"], {"effort": "low"})
        self.assertNotIn("tool_choice", seen[0])
        results = llm.tool_results([("t1", "rows", False)])
        self.assertEqual(results[0]["content"][0]["type"], "tool_result")

    def test_fallbacks_only_for_models_that_accept_them(self):
        env = {"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "test"}
        with patch.dict(os.environ, {**env, "LLM_MODEL": "claude-haiku-5-5"}):
            self.assertEqual(build_llm().request_defaults, {})            # Haiku 5.5 rejects `fallbacks`
        with patch.dict(os.environ, {**env, "LLM_MODEL": "claude-opus-5-5"}):
            self.assertEqual(build_llm().request_defaults["fallbacks"], "default")


class Factory(unittest.TestCase):
    def test_openrouter_model_list_becomes_fallbacks(self):
        seen = []
        openrouter_with(completion({"content": "ok"}), seen=seen,
                        model="main/model:free, backup/model:free").chat(system="s", messages=[])
        self.assertEqual(seen[0]["model"], "main/model:free")
        self.assertEqual(seen[0]["models"], ["main/model:free", "backup/model:free"])
        openrouter_with(completion({"content": "ok"}), seen=seen).chat(system="s", messages=[])
        self.assertNotIn("models", seen[1])   # a single model sends no fallback list

    def test_openrouter_is_default_and_needs_a_key(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False):
            os.environ.pop("LLM_PROVIDER", None)
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY"):
                build_llm()
        with patch.dict(os.environ, {"LLM_PROVIDER": "openrouter", "OPENROUTER_API_KEY": "k", "LLM_MODEL": ""}):
            llm = build_llm()
            self.assertEqual((llm.provider, llm.model), ("openrouter", "nvidia/nemotron-3-super-120b-a12b:free"))


if __name__ == "__main__":
    unittest.main()
