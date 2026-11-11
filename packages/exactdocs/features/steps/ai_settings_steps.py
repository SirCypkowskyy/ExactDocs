"""Steps for the library AI settings and the instance's AI state the UI shows (#102).

The embedding endpoint is the fake gateway (``fake_llm``) and the hybrid pipeline a stand-in, as
in ``embedding_steps``; budgets reuse the movable clock and the ledger of ``ai_budget_steps``.
"""

from http import HTTPStatus
from typing import Any

from behave import given, then, when
from behave.runner import Context

from exactdocs.bootstrap.settings import AiSettings
from exactdocs.retrieval.models import ModelRole, RetrievalMode, SpendWindow
from steps.ai_budget_steps import ONE_USD, StandInAgentic, record_spend, serve_budgets
from steps.embedding_steps import (
    embedding_ai,
    serve_embedding,
    start_gateway,
    wait_for_embedding,
)
from steps.search_steps import LIBRARY

RETRIEVAL = f"/api/v1/libraries{LIBRARY}/retrieval"


def _put(context: Context, body: dict[str, Any]) -> None:
    """Set the library's retrieval settings, keeping the response.

    Args:
        context: The behave context.
        body: The settings.
    """
    context.response = context.client.put(RETRIEVAL, json=body)


def _read(context: Context) -> dict[str, Any]:
    """Read the library's retrieval settings.

    Args:
        context: The behave context.

    Returns:
        The settings.
    """
    response = context.client.get(RETRIEVAL)
    assert response.status_code == HTTPStatus.OK, response.text
    return response.json()


@given("an embedding model is configured and every version is embedded")
def step_embedded(context: Context) -> None:
    context.endpoint = start_gateway(context)
    ai: AiSettings = embedding_ai(context.endpoint, "e5")
    serve_embedding(context, ai)
    jobs = wait_for_embedding(context, LIBRARY)
    assert all(job["state"] == "succeeded" for job in jobs), jobs


@when("the admin reads the library's retrieval settings")
def step_read_settings(context: Context) -> None:
    context.settings_read = _read(context)


@then('the effective pipeline is "{mode}" and only "{modes}" can be chosen')
def step_effective(context: Context, mode: str, modes: str) -> None:
    body = context.settings_read
    assert body["effective_mode"] == mode, body
    assert body["available_modes"] == modes.split(", "), body
    assert body["configured_roles"] == ["embedding"], body


@when('the admin switches the library\'s AI to "off"')
def step_ai_off(context: Context) -> None:
    _put(context, {"ai_enabled": False})
    assert context.response.status_code == HTTPStatus.OK, context.response.text


@then('the effective pipeline is "{mode}" and the library uses no model role')
def step_no_role(context: Context, mode: str) -> None:
    for body in (context.response.json(), _read(context)):
        assert (body["ai_enabled"], body["effective_mode"]) == (False, mode), body
        assert body["configured_roles"] == [], body
        assert body["available_modes"] == ["bm25"], body


@when("the admin reads the embedding progress")
def step_read_progress(context: Context) -> None:
    response = context.client.get("/api/v1/ai/embedding")
    assert response.status_code == HTTPStatus.OK, response.text
    context.progress = response.json()


@then(
    "the configured model's space is active and covers {done:d} of {total:d} versions "
    "and every chunk"
)
def step_progress(context: Context, done: int, total: int) -> None:
    body = context.progress
    assert body["model"] == "corp:e5", body
    (space,) = body["spaces"]
    assert (space["model"], space["state"], space["current"]) == ("e5", "active", True), space
    assert (space["versions_embedded"], space["versions"]) == (done, total), space
    assert space["chunks"] > 0, space
    assert space["chunks_embedded"] == space["chunks"], space


def _per_library_daily(context: Context, usd: int) -> None:
    """Serve with a per-library daily budget and a stand-in LLM search.

    Args:
        context: The behave context.
        usd: US dollars each library may spend a day.
    """
    serve_budgets(
        context,
        {"budgets": {"per_library_daily_usd": usd}},
        roles=frozenset({ModelRole.LLM}),
        pipelines={RetrievalMode.AGENTIC: StandInAgentic()},
    )


@given("each library may spend {usd:d} USD a day and the library's own daily budget is {own:d} USD")
def step_own_budget(context: Context, usd: int, own: int) -> None:
    _per_library_daily(context, usd)
    _put(context, {"budgets": {"daily_usd": own}})
    assert context.response.status_code == HTTPStatus.OK, context.response.text
    body = context.response.json()
    assert body["budgets"]["daily_usd"] == own, body
    assert body["budget_ceilings"]["daily_usd"] == usd, body


@given("the library spent {usd:d} USD today")
def step_library_spent(context: Context, usd: int) -> None:
    record_spend(context, "library", LIBRARY, SpendWindow.DAY, usd * ONE_USD)


@then("the AI usage shows the library's daily budget of {usd:d} USD as reached")
def step_usage_library(context: Context, usd: int) -> None:
    response = context.client.get("/api/v1/ai/usage")
    assert response.status_code == HTTPStatus.OK, response.text
    (scope,) = [s for s in response.json()["scopes"] if s["scope"] == "library"]
    assert scope["id"].casefold() == LIBRARY.casefold(), scope
    (budget,) = [b for b in scope["budgets"] if b["window"] == "day"]
    assert (budget["usd_limit"], budget["reached"]) == (usd, True), budget


@given("each library may spend {usd:d} USD a day")
def step_per_library(context: Context, usd: int) -> None:
    _per_library_daily(context, usd)


@when("the admin sets the library's daily budget to {usd:d} USD")
def step_set_budget(context: Context, usd: int) -> None:
    _put(context, {"budgets": {"daily_usd": usd}})


@then('it is refused with "{code}" and the library keeps no budget of its own')
def step_refused(context: Context, code: str) -> None:
    response = context.response
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY, response.text
    assert response.json()["error"] == code, response.text
    assert _read(context)["budgets"] == {
        "daily_usd": None,
        "monthly_usd": None,
        "daily_tokens": None,
        "monthly_tokens": None,
    }
