"""LLM layer: Groq provider, Bedrock, Ollama, router, budget."""

import json
import logging

import httpx
import pytest
from pydantic import BaseModel

from packages.infrastructure.key_vault import SecretsManager
from packages.infrastructure.key_vault.store import KeyRecord
from packages.infrastructure.llm import groq_provider
from packages.infrastructure.llm.base import (
    LLMBudgetExceeded, LLMProvider, LLMResult, LLMSchemaError, LLMUnavailable, extract_json,
)
from packages.infrastructure.llm.bedrock_provider import BedrockProvider
from packages.infrastructure.llm.groq_provider import GroqProvider, probe_groq_key
from packages.infrastructure.llm.ollama_provider import OllamaProvider
from packages.infrastructure.llm.router import RoutedLLM, configured_chain, get_llm

from .conftest import FAKE_KEY_A, FAKE_KEY_B


class Person(BaseModel):
    name: str
    age: int


def _ok(content, tokens=(11, 7)):
    return httpx.Response(200, json={
        "model": "openai/gpt-oss-120b",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]},
    })


class Script:
    """MockTransport handler that replays queued responses and records requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        return item(request) if callable(item) else item


class FakeStore:
    def __init__(self, keys):
        self.keys = keys
        self.failed = []

    def usable_keys(self, provider):
        return list(self.keys)

    def mark_failed(self, key_id, status_code, cooldown_s):
        self.failed.append((key_id, status_code))
        if status_code in (401, 403, 429):
            self.keys = [k for k in self.keys if k.id != key_id]

    def mark_used(self, key_id):
        pass


def _mgr(*values):
    keys = [KeyRecord(id=f"db-{i}", provider="groq", value=v, priority=10 + i, source="db")
            for i, v in enumerate(values)]
    return SecretsManager(db_store=FakeStore(keys)), keys


def _provider(script, *values, sleeps=None, **kw):
    mgr, _ = _mgr(*values)
    sleeps = sleeps if sleeps is not None else []
    prov = GroqProvider(secrets=mgr, transport=httpx.MockTransport(script), sleep=sleeps.append, **kw)
    return prov, mgr, sleeps


@pytest.fixture(autouse=True)
def _no_usage_db(monkeypatch):
    calls = []
    monkeypatch.setattr(groq_provider, "record_usage", lambda **kw: calls.append(kw))
    monkeypatch.setattr("packages.infrastructure.llm.bedrock_provider.record_usage", lambda **kw: calls.append(kw))
    monkeypatch.setattr("packages.infrastructure.llm.ollama_provider.record_usage", lambda **kw: calls.append(kw))
    return calls


# ── helpers ──────────────────────────────────────────────────────────────────

def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here it is: {"a": 2} hope it helps') == {"a": 2}
    with pytest.raises(ValueError):
        extract_json("no json here")


# ── Groq: happy path ─────────────────────────────────────────────────────────

def test_groq_plain_chat_success_and_request_shape():
    script = Script(_ok("hello"))
    prov, _, _ = _provider(script, FAKE_KEY_A)
    res = prov.chat([{"role": "user", "content": "hi"}])
    assert res.text == "hello" and res.provider == "groq"
    assert res.usage == {"prompt_tokens": 11, "completion_tokens": 7}
    req = script.requests[0]
    assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {FAKE_KEY_A}"
    body = json.loads(req.content)
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["reasoning_effort"] == "low"
    assert "max_completion_tokens" in body


def test_groq_structured_output_uses_json_schema_and_parses():
    script = Script(_ok('{"name": "Ana", "age": 31}'))
    prov, _, _ = _provider(script, FAKE_KEY_A)
    res = prov.chat([{"role": "user", "content": "x"}], schema=Person)
    assert res.parsed == Person(name="Ana", age=31)
    rf = json.loads(script.requests[0].content)["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["schema"]["title"] == "Person"


# ── Groq: key rotation ───────────────────────────────────────────────────────

def test_groq_401_marks_key_invalid_and_retries_with_next_key():
    script = Script(httpx.Response(401, json={"error": "bad key"}), _ok("fine"))
    prov, mgr, _ = _provider(script, FAKE_KEY_A, FAKE_KEY_B)
    res = prov.chat([{"role": "user", "content": "x"}])
    assert res.text == "fine"
    used = [r.headers["authorization"] for r in script.requests]
    assert used == [f"Bearer {FAKE_KEY_A}", f"Bearer {FAKE_KEY_B}"]
    assert mgr._db_store.failed == [("db-0", 401)]


def test_groq_long_429_switches_to_next_key():
    script = Script(httpx.Response(429, headers={"retry-after": "120"}), _ok("ok"))
    prov, mgr, sleeps = _provider(script, FAKE_KEY_A, FAKE_KEY_B)
    assert prov.chat([{"role": "user", "content": "x"}]).text == "ok"
    assert mgr._db_store.failed == [("db-0", 429)]
    assert sleeps == []  # switched key instead of waiting


def test_groq_short_429_waits_and_retries_same_key():
    script = Script(httpx.Response(429, headers={"retry-after": "2"}), _ok("ok"))
    prov, mgr, sleeps = _provider(script, FAKE_KEY_A)
    assert prov.chat([{"role": "user", "content": "x"}]).text == "ok"
    assert sleeps == [2.0]
    assert mgr._db_store.failed == []
    assert len({r.headers["authorization"] for r in script.requests}) == 1


def test_groq_all_keys_invalid_raises_unavailable():
    script = Script(httpx.Response(401), httpx.Response(401))
    prov, _, _ = _provider(script, FAKE_KEY_A, FAKE_KEY_B)
    with pytest.raises(LLMUnavailable, match="No usable Groq API key"):
        prov.chat([{"role": "user", "content": "x"}])


def test_groq_without_any_key_raises_unavailable():
    prov = GroqProvider(secrets=SecretsManager(db_store=FakeStore([])),
                        transport=httpx.MockTransport(Script()), sleep=lambda s: None)
    with pytest.raises(LLMUnavailable, match="Settings > API Keys"):
        prov.chat([{"role": "user", "content": "x"}])


def test_groq_5xx_retries_then_succeeds_and_gives_up_after_three():
    prov, _, sleeps = _provider(Script(httpx.Response(503), _ok("ok")), FAKE_KEY_A)
    assert prov.chat([{"role": "user", "content": "x"}]).text == "ok"
    assert len(sleeps) == 1
    prov2, _, _ = _provider(Script(httpx.Response(500), httpx.Response(500), httpx.Response(500)), FAKE_KEY_A)
    with pytest.raises(LLMUnavailable, match="server error"):
        prov2.chat([{"role": "user", "content": "x"}])


def test_groq_network_error_is_retried():
    def boom(request):
        raise httpx.ConnectError("down")
    prov, _, sleeps = _provider(Script(boom, _ok("ok")), FAKE_KEY_A)
    assert prov.chat([{"role": "user", "content": "x"}]).text == "ok"
    assert len(sleeps) == 1


def test_groq_model_not_found_switches_to_fallback_model():
    script = Script(httpx.Response(404, json={"error": {"message": "The model `x` does not exist"}}), _ok("ok"))
    prov, _, _ = _provider(script, FAKE_KEY_A)
    assert prov.chat([{"role": "user", "content": "x"}]).text == "ok"
    models = [json.loads(r.content)["model"] for r in script.requests]
    assert models == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


# ── Groq: schema handling ────────────────────────────────────────────────────

def test_groq_malformed_json_reasks_with_error_then_succeeds():
    script = Script(_ok("not json at all"), _ok('{"name": "Bo", "age": 5}'))
    prov, _, _ = _provider(script, FAKE_KEY_A)
    res = prov.chat([{"role": "user", "content": "x"}], schema=Person)
    assert res.parsed.name == "Bo"
    second = json.loads(script.requests[1].content)["messages"]
    assert second[-1]["role"] == "user" and "invalid" in second[-1]["content"].lower()
    assert second[-2]["role"] == "assistant"


def test_groq_wrong_types_fail_validation_and_raise_after_retries():
    bad = _ok('{"name": "Bo", "age": "old"}')
    prov, _, _ = _provider(Script(bad, bad, bad), FAKE_KEY_A)
    with pytest.raises(LLMSchemaError):
        prov.chat([{"role": "user", "content": "x"}], schema=Person)


def test_groq_400_on_response_format_falls_back_to_prompt_json():
    script = Script(httpx.Response(400, json={"error": {"message": "unsupported schema"}}),
                    _ok('{"name": "Cy", "age": 9}'))
    prov, _, _ = _provider(script, FAKE_KEY_A)
    res = prov.chat([{"role": "user", "content": "x"}], schema=Person)
    assert res.parsed.age == 9
    first, second = (json.loads(r.content) for r in script.requests)
    assert "response_format" in first and "response_format" not in second
    assert second["messages"][0]["role"] == "system"


def test_groq_other_4xx_surfaces_as_unavailable():
    prov, _, _ = _provider(Script(httpx.Response(422, text="bad request body")), FAKE_KEY_A)
    with pytest.raises(LLMUnavailable, match="HTTP 422"):
        prov.chat([{"role": "user", "content": "x"}])


# ── secret hygiene ───────────────────────────────────────────────────────────

def test_key_never_appears_in_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    prov, _, _ = _provider(Script(httpx.Response(401), httpx.Response(401)), FAKE_KEY_A, FAKE_KEY_B)
    with pytest.raises(LLMUnavailable) as exc:
        prov.chat([{"role": "user", "content": "x"}])
    assert FAKE_KEY_A not in str(exc.value) and FAKE_KEY_B not in str(exc.value)
    assert FAKE_KEY_A not in caplog.text and FAKE_KEY_B not in caplog.text


def test_usage_ledger_records_counts_but_never_prompt_text(_no_usage_db):
    prov, _, _ = _provider(Script(_ok("answer")), FAKE_KEY_A)
    prov.chat([{"role": "user", "content": "SECRET PROMPT TEXT"}], purpose="unit")
    row = _no_usage_db[0]
    assert row["prompt_tokens"] == 11 and row["completion_tokens"] == 7 and row["success"] is True
    assert "SECRET PROMPT TEXT" not in str(row) and "answer" not in str(row)


def test_probe_groq_key_reports_status_without_raising():
    ok = probe_groq_key(FAKE_KEY_A, transport=httpx.MockTransport(Script(_ok("k"))))
    bad = probe_groq_key(FAKE_KEY_A, transport=httpx.MockTransport(Script(httpx.Response(401))))
    assert ok["ok"] is True and bad["ok"] is False and bad["status_code"] == 401
    assert FAKE_KEY_A not in json.dumps(bad)


def test_groq_healthcheck_without_key_is_not_ok():
    prov = GroqProvider(secrets=SecretsManager(db_store=FakeStore([])))
    h = prov.healthcheck()
    assert h["ok"] is False and "key" in h["error"]


# ── Bedrock ──────────────────────────────────────────────────────────────────

class FakeBedrock:
    def __init__(self, *texts, fail=False):
        self.texts, self.calls, self.fail = list(texts), [], fail

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("AccessDenied")
        return {"output": {"message": {"content": [{"text": self.texts.pop(0)}]}},
                "usage": {"inputTokens": 5, "outputTokens": 3}}


def test_bedrock_chat_maps_messages_and_usage():
    client = FakeBedrock("hi there")
    prov = BedrockProvider(client=client, model_id="m-1")
    res = prov.chat([{"role": "system", "content": "be brief"}, {"role": "user", "content": "hello"}])
    assert res.text == "hi there" and res.provider == "bedrock"
    assert res.usage == {"prompt_tokens": 5, "completion_tokens": 3}
    call = client.calls[0]
    assert call["modelId"] == "m-1"
    assert call["system"] == [{"text": "be brief"}]
    assert call["messages"] == [{"role": "user", "content": [{"text": "hello"}]}]


def test_bedrock_schema_retry_then_success():
    client = FakeBedrock("garbage", '{"name": "Di", "age": 40}')
    res = BedrockProvider(client=client).chat([{"role": "user", "content": "x"}], schema=Person)
    assert res.parsed.name == "Di" and len(client.calls) == 2


def test_bedrock_failure_becomes_unavailable():
    with pytest.raises(LLMUnavailable):
        BedrockProvider(client=FakeBedrock(fail=True)).chat([{"role": "user", "content": "x"}])


def test_bedrock_without_boto3_is_a_clean_error(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "boto3":
            raise ImportError("no boto3")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(LLMUnavailable, match="boto3"):
        BedrockProvider().chat([{"role": "user", "content": "x"}])


# ── Ollama ───────────────────────────────────────────────────────────────────

def test_ollama_chat_and_schema():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": '{"name": "Ed", "age": 2}'},
                                         "prompt_eval_count": 4, "eval_count": 2})
    prov = OllamaProvider(transport=httpx.MockTransport(handler))
    res = prov.chat([{"role": "user", "content": "x"}], schema=Person)
    assert res.parsed.name == "Ed" and res.usage["prompt_tokens"] == 4


def test_ollama_down_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(LLMUnavailable):
        OllamaProvider(transport=httpx.MockTransport(handler)).chat([{"role": "user", "content": "x"}])


# ── router, chain, budget ────────────────────────────────────────────────────

class StubProvider(LLMProvider):
    def __init__(self, name, error=None, text="ok"):
        self.name, self.error, self.text, self.calls = name, error, text, 0

    def chat(self, messages, **kw):
        self.calls += 1
        if self.error:
            raise self.error
        return LLMResult(text=self.text, provider=self.name, model="m")

    def healthcheck(self):
        return {"ok": self.error is None}


def test_router_falls_through_chain():
    a, b = StubProvider("groq", LLMUnavailable("down")), StubProvider("bedrock", text="from bedrock")
    res = RoutedLLM([a, b]).chat([{"role": "user", "content": "x"}])
    assert res.text == "from bedrock" and a.calls == 1 and b.calls == 1


def test_router_raises_when_all_fail():
    a, b = StubProvider("groq", LLMUnavailable("a")), StubProvider("ollama", LLMSchemaError("b"))
    with pytest.raises(LLMUnavailable, match="All LLM providers failed"):
        RoutedLLM([a, b]).chat([{"role": "user", "content": "x"}])


def test_router_budget_exceeded_blocks_before_calling_provider():
    a = StubProvider("groq")
    llm = RoutedLLM([a], budget_fn=lambda: 1000, used_fn=lambda: 1000)
    with pytest.raises(LLMBudgetExceeded):
        llm.chat([{"role": "user", "content": "x"}])
    assert a.calls == 0


def test_router_budget_zero_means_unlimited_and_unknown_usage_allows_call():
    a = StubProvider("groq")
    RoutedLLM([a], budget_fn=lambda: 0, used_fn=lambda: 10**9).chat([{"role": "user", "content": "x"}])
    RoutedLLM([a], budget_fn=lambda: 10, used_fn=lambda: None).chat([{"role": "user", "content": "x"}])
    assert a.calls == 2


def test_configured_chain_reads_env_each_time(monkeypatch):
    assert configured_chain() == ["groq"]
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("LLM_FALLBACK_CHAIN", "groq, ollama, bedrock, bogus")
    assert configured_chain() == ["bedrock", "groq", "ollama"]
    assert [p.name for p in get_llm().providers] == ["bedrock", "groq", "ollama"]


def test_budget_flows_from_env(monkeypatch):
    from packages.infrastructure.llm.usage import daily_budget
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "5000")
    assert daily_budget() == 5000
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", "junk")
    assert daily_budget() == 0


def test_usage_ledger_and_daily_total_in_database(db, cursor_ctx, monkeypatch):
    from packages.infrastructure.llm import usage
    monkeypatch.setattr("packages.infrastructure.db_connector.get_db_cursor", cursor_ctx)
    usage.record_usage(provider="groq", model="m", key_id="env:groq:0", purpose="t",
                       prompt_tokens=100, completion_tokens=50, latency_ms=10, status_code=200, success=True)
    usage.record_usage(provider="groq", model="m", key_id=None, purpose="t",
                       prompt_tokens=10, completion_tokens=5, latency_ms=10, status_code=200, success=True)
    assert usage.tokens_used_today() == 165
    status = usage.budget_status()
    assert status["unlimited"] is True and status["tokens_used_today"] == 165


def test_entity_resolver_uses_new_layer_only_when_provider_is_set(monkeypatch):
    """LLM_PROVIDER unset keeps the original Ollama behaviour; groq routes through the new layer."""
    import asyncio
    from packages.domain import llm_entity_resolver as mod
    calls = {"ollama": 0, "new": 0}

    class FakeOllama:
        def is_available(self):
            return True

        async def generate_structured(self, **kw):
            calls["ollama"] += 1
            return {"decision": "MERGE", "is_same_entity": True, "confidence": 0.9, "reasoning": "r"}

    async def fake_new(prompt, system=None, timeout=None):
        calls["new"] += 1
        return {"decision": "SEPARATE", "is_same_entity": False, "confidence": 0.8, "reasoning": "r"}

    monkeypatch.setattr(mod, "ollama_client", FakeOllama())
    monkeypatch.setattr("packages.infrastructure.llm.generate_structured_json", fake_new)
    resolver = mod.LLMEntityResolver() if hasattr(mod, "LLMEntityResolver") else None
    if resolver is None:
        pytest.skip("resolver class name differs")
    resolver.enabled = True
    a = {"name": "Acme Dental LLC", "domain": "acme.com"}
    b = {"name": "Acme Dentistry", "domain": "acme.com"}

    r1 = asyncio.run(resolver.adjudicate_pair(a, b, prior_prob=0.8))
    assert calls == {"ollama": 1, "new": 0} and r1.method == "ollama_llama3.1:8b"
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    r2 = asyncio.run(resolver.adjudicate_pair(a, b, prior_prob=0.8))
    assert calls == {"ollama": 1, "new": 1} and r2.method == "llm_groq"
