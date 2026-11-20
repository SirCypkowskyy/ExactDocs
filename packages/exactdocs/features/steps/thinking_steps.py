"""Steps for the thinking level of the llm and judge roles (#421).

The ``llm`` role is a Gemini API profile and a library's own judge an OpenAI-compatible one,
both on one fake gateway on loopback and built by the real pydantic-ai factory, so the request
body each sends is what Google or the gateway would get.
"""

from contextlib import ExitStack
from http import HTTPStatus
from typing import Any

from behave import given, then, when
from behave.runner import Context

from fake_llm import Seen, gateway
from steps.hybrid_search_steps import step_embedded
from steps.hyde_steps import serve_with_llm

SEARCH = "/api/v1/libraries/fixture/docs-repo/search"
SETTING = "/api/v1/libraries/fixture/docs-repo/retrieval"
ROLES = "/api/v1/ai/roles"
GEMINI = "gemini-4-hydrogen"
JUDGE = "corp:judge-mini"
QUERY = "how do I retry failed calls"


def _gemini_calls(context: Context) -> list[Seen]:
    return [s for s in context.endpoint.seen if s.path.split("?")[0].endswith(":generateContent")]


def _chat_calls(context: Context) -> list[Seen]:
    return [s for s in context.endpoint.seen if s.path.endswith("/chat/completions")]


def _google_level(call: Seen) -> str | None:
    """Read the thinking level of a Gemini request, as the google-genai SDK writes it.

    Args:
        call: The ``generateContent`` request.

    Returns:
        ``thinking_level`` of its ``thinkingConfig``, or ``None`` without one.
    """
    config = call.body.get("generationConfig", {}).get("thinkingConfig")
    return None if config is None else config["thinking_level"]


def _serve(context: Context, thinking: str | None) -> None:
    stack = ExitStack()
    context.add_cleanup(stack.close)
    context.endpoint = stack.enter_context(gateway())
    providers: dict[str, Any] = {
        "gem": {"kind": "google", "base_url": context.endpoint.url + "/", "api_key": "gem-key"},
        "corp": {"kind": "openai-compatible", "base_url": context.endpoint.v1},
    }
    llm: dict[str, Any] = {"model": f"gem:{GEMINI}"}
    if thinking is not None:
        llm["thinking"] = thinking
    serve_with_llm(context, mode="hybrid_hyde", providers=providers, llm=llm)
    step_embedded(context, "v1.4.0")


def _role(context: Context, name: str) -> dict[str, Any]:
    response = context.client.get(ROLES)
    assert response.status_code == HTTPStatus.OK, response.text
    (role,) = [r for r in response.json()["roles"] if r["role"] == name]
    return role


@given('the llm role is a Gemini model with thinking level "{level}"')
def step_gemini_with_level(context: Context, level: str) -> None:
    _serve(context, level)


@given("the llm role is a Gemini model with no thinking level")
def step_gemini_without_level(context: Context) -> None:
    _serve(context, None)


@when("a hybrid_hyde search runs")
def step_hyde_search(context: Context) -> None:
    context.response = context.client.get(
        SEARCH, params={"q": "retry_policy", "ref": "v1.4.0", "mode": "hybrid_hyde"}
    )
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    body = context.response.json()
    assert (body["retrieval_mode"], body["fallback_reason"]) == ("hybrid_hyde", None), body


@then('the model is called with Google\'s thinking level "{level}"')
def step_gemini_level(context: Context, level: str) -> None:
    (call,) = _gemini_calls(context)
    assert _google_level(call) == level, call.body["generationConfig"]


@then("the model is called without a thinking setting")
def step_gemini_no_level(context: Context) -> None:
    (call,) = _gemini_calls(context)
    assert "thinkingConfig" not in call.body.get("generationConfig", {}), call.body


@then("the instance's roles show the {name} role's thinking level as \"{level}\"")
def step_role_level(context: Context, name: str, level: str) -> None:
    role = _role(context, name)
    assert role["thinking"] == level, role


@given('the library\'s retrieval settings set its own judge with thinking level "{level}"')
def step_library_judge(context: Context, level: str) -> None:
    body = {"rerank_with": "judge", "judge": JUDGE, "judge_thinking": level}
    response = context.client.put(SETTING, json=body)
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["effective_reranker"] == "judge", response.text


@when("its search is reranked by the judge")
def step_judged_search(context: Context) -> None:
    context.response = context.client.get(SEARCH, params={"q": QUERY, "ref": "v1.4.0"})
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    assert context.response.json()["reranked"] is True, context.response.text


@then('the judge is called with reasoning effort "{level}"')
def step_judge_effort(context: Context, level: str) -> None:
    (call,) = _chat_calls(context)
    assert call.body["model"] == JUDGE.partition(":")[2], call.body
    assert call.body["reasoning_effort"] == level, call.body
    (gemini,) = _gemini_calls(context)  # the library's HyDE still uses the instance's level
    assert _google_level(gemini) == "LOW", gemini.body


@then("the library's retrieval settings show the judge's thinking level as \"{level}\"")
def step_library_level(context: Context, level: str) -> None:
    response = context.client.get(SETTING)
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["judge_thinking"] == level, response.text


@when('the admin saves thinking level "{level}" for the library\'s own llm "{model}"')
def step_save_unsupported(context: Context, level: str, model: str) -> None:
    body = {"llm": f"gem:{model}", "llm_thinking": level}
    context.response = context.client.put(SETTING, json=body)


@then('the save is refused with "{code}" naming the role "{role}" and the model "{model}"')
def step_refused(context: Context, code: str, role: str, model: str) -> None:
    assert context.response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, context.response.text
    body = context.response.json()
    assert body["error"] == code, body
    assert f"the {role} role" in body["detail"], body
    assert f"gem:{model}" in body["detail"], body
    shown = context.client.get(SETTING).json()
    assert (shown["llm"], shown["llm_thinking"]) == (None, None), "nothing was stored"


@when('the admin sets the instance judge role\'s thinking level to "{level}"')
def step_set_instance_judge(context: Context, level: str) -> None:
    response = context.client.put(f"{ROLES}/judge", json={"thinking": level})
    assert response.status_code == HTTPStatus.OK, response.text
    assert response.json()["thinking"] == level, response.text


@then("setting the llm role's thinking level over the REST API is refused as configured")
def step_llm_configured(context: Context) -> None:
    response = context.client.put(f"{ROLES}/llm", json={"thinking": "high"})
    assert response.status_code == HTTPStatus.CONFLICT, response.text
    assert response.json()["error"] == "role_configured", response.text
    assert _role(context, "llm")["thinking"] == "low"
