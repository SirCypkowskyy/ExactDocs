"""Steps for the text scorer (packages/exactdocs/evals): a tool's text results, scored in-process.

The project is ``text_corpus``'s guide at v1 and v2: ``Install`` is the same in both,
``Configure`` changed in v2 and ``Lifespan`` exists only in v2. V is v2.
"""

from behave import given, then, when
from behave.runner import Context
from pydantic_evals import Case

from retrieval_eval.dataset import Answer, CaseInfo, Hit, Question
from retrieval_eval.text_bench import TextAnswer, text_metrics, text_row
from text_corpus import CONFIGURE_V1, INSTALL, LIFESPAN, two_version_index

ASKED = "v2"
UNRELATED = "Kubernetes operators reconcile custom resources against the desired cluster state."


def _case(context: Context, *path: str) -> None:
    context.case = Case(
        name=f"demo {ASKED}: {' > '.join(path)}",
        inputs=Question(query="how?", version=ASKED, project="demo"),
        metadata=CaseInfo(kind="how-to"),
        expected_output=Answer(
            hits=[Hit(version=ASKED, article="docs/guide.md", heading_path=["Guide", *path])],
            reference="r",
            facts=["f"],
        ),
    )


@given("a project whose docs are pinned at two versions")
def step_project(context: Context) -> None:
    context.index = two_version_index()


@given("a case whose expected section S belongs to version V")
def step_case(context: Context) -> None:
    _case(context, "Lifespan")


@given("a tool returned text results for the question")
def step_results(context: Context) -> None:
    context.texts = [UNRELATED, INSTALL, LIFESPAN, LIFESPAN]


@given("a result whose text matches a section of another pinned version and no section of V")
def step_other_version(context: Context) -> None:
    _case(context, "Configure")
    context.texts = [CONFIGURE_V1]  # v1's Configure: v2 rewrote it


@given("a result whose text is identical in V and in another pinned version")
def step_shared(context: Context) -> None:
    _case(context, "Install")
    context.texts = [INSTALL]


@when("the results are scored")
def step_score(context: Context) -> None:
    context.row = text_row(context.case, TextAnswer(texts=context.texts), context.index)
    context.metrics = text_metrics([context.row])


@then("the first result whose text holds S's text counts as a hit at its rank")
def step_hit(context: Context) -> None:
    first = context.texts.index(LIFESPAN) + 1  # S's text comes back third and fourth
    assert context.row.row.rank == first, context.row
    assert context.metrics.metrics.recall_at_1 == 0
    assert context.metrics.metrics.recall_at_5 == 1
    assert context.metrics.metrics.mrr == round(1 / 3, 4)


@then("the case counts towards the wrong-version rate")
def step_wrong(context: Context) -> None:
    assert context.row.row.wrong_version
    assert context.metrics.metrics.wrong_version_rate == 1
    assert context.row.row.rank is None  # v1's text is no hit for v2's section


@then("it is counted as version-neutral, not as wrong-version")
def step_neutral(context: Context) -> None:
    assert context.row.neutral == 1
    assert not context.row.row.wrong_version
    assert context.metrics.version_neutral_share == 1
    assert context.metrics.metrics.wrong_version_rate == 0
    assert context.row.row.rank == 1  # it holds the expected section's text
