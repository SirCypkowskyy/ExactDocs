"""Steps for the fixture docs repository itself (the other features import it)."""

from behave import given, then, when
from behave.runner import Context


@given("the fixture docs repository is built and served")
def step_built(context: Context) -> None:
    assert context.fixture_repo.path.is_dir()


@when("I list the remote refs of the fixture repository over {transport}")
def step_ls_remote(context: Context, transport: str) -> None:
    url = {"file": context.fixture_repo.file_url, "http": context.fixture_repo.http_url}[transport]
    context.refs = context.fixture_git("ls-remote", "--heads", "--tags", url).split("\n")


@then('the remote has the tags "{tags}" and the branch "{branch}"')
def step_refs(context: Context, tags: str, branch: str) -> None:
    names = {line.split("\t")[1] for line in context.refs}
    expected = {f"refs/tags/{tag}" for tag in tags.split(", ")} | {f"refs/heads/{branch}"}
    assert expected <= names, names


@then('"{text}" occurs in version "{present}" but not in version "{absent}"')
def step_occurs(context: Context, text: str, present: str, absent: str) -> None:
    def hits(version: str) -> str:
        args = ("grep", "-Il", "-F", text, version, "--", "docs")
        return context.fixture_git(*args, cwd=context.fixture_repo.path, check=False)

    assert hits(present), f"{text} is missing from {present}"
    assert not hits(absent), f"{text} leaked into {absent}"
