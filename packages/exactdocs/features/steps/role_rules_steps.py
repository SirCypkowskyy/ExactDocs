"""Steps for role rules (#577): a provider's memberships mapped to instance and library roles.

The instance, the browser and the identity provider are those of ``external_sign_in_steps``
(a fake OIDC issuer or a stand-in GitHub API in the process). Libraries are created as the
instance's own work, so nobody is their creator and only the rules give anyone a role on them.
"""

from datetime import timedelta
from http import HTTPStatus
from importlib import import_module

from behave import given, then, when
from behave.runner import Context

from exactdocs.catalog.dtos import CreateLibraryCommand, HostKind
from exactdocs.identity.dtos import LibraryRolesQuery
from steps.external_sign_in_steps import (
    add_person,
    browser_sign_in,
    instance_client,
    send_as,
    session_of,
    step_provider,
    whoami,
)

GRANTS = {
    "viewer on every library": "viewer",
    "contributor on every library": "contributor",
    "instance admin": "instance_admin",
    "may create libraries": "create_libraries",
}


def _rule(context: Context, rule: dict[str, str]) -> None:
    context.provider_config.setdefault("rules", []).append(rule)


def _roles(context: Context, session: str) -> dict[str, str]:
    """The signed-in person's role on each library that exists."""
    account = whoami(context, session)["account"]["id"]
    query = LibraryRolesQuery(account_id=account, libraries=context.libraries)
    found = context.client.portal.call(context.container.identity.resolve_library_roles, query)
    return found.roles


@given('GitHub sign-in admits the organization "{org}"')
def step_github_org(context: Context, org: str) -> None:
    step_provider(context, "gh", "github", "https://github.example.com")
    context.issuer = import_module("fake_github").FakeGithub(
        issuer="https://github.example.com", now=context.clock.now
    )
    context.provider_config.pop("issuer")
    context.provider_config.update(
        {"base_url": context.issuer.issuer, "allowed_orgs": [org], "allow_any_user": False}
    )


@given('the rule "GitHub organization {org}: {grant}"')
def step_org_rule(context: Context, org: str, grant: str) -> None:
    _rule(context, {"github_org": org, "grant": GRANTS[grant]})


@given('the rules "group {first}: {first_grant}" and "group {second}: {second_grant}"')
def step_group_rules(
    context: Context, first: str, first_grant: str, second: str, second_grant: str
) -> None:
    _rule(context, {"group": first, "grant": GRANTS[first_grant]})
    _rule(context, {"group": second, "grant": GRANTS[second_grant]})


@given(
    'its role claim is "{claim}", configured to map "{admin}" to instance admin '
    'and "{reader}" to viewer on every library'
)
def step_role_claim(context: Context, claim: str, admin: str, reader: str) -> None:
    context.provider_config.update({"role_claim": claim, "configured_rules_only": True})
    _rule(context, {"role": admin, "grant": "instance_admin"})
    _rule(context, {"role": reader, "grant": "viewer"})


@given('the libraries "{first}" and "{second}" exist')
def step_libraries(context: Context, first: str, second: str) -> None:
    instance_client(context)
    context.libraries = [first, second]
    for library in context.libraries:
        command = CreateLibraryCommand(
            id=library,
            title=library.rsplit("/", 1)[-1],
            source_url=f"https://git.example.com{library}.git",
            host=HostKind.GIT,
        )
        context.client.portal.call(context.container.catalog.create_library, command)


@when("an acme member who is in no team signs in")
def step_github_member(context: Context) -> None:
    context.issuer.add_user("123", "carol")
    context.issuer.teams.clear()
    context.session = session_of(browser_sign_in(context, "123"))


@then("they can read every library and edit none")
def step_read_only(context: Context) -> None:
    listed = send_as(context, "GET", "/api/v1/libraries", session=context.session)
    assert listed.status_code == HTTPStatus.OK, listed.text
    assert sorted(lib["id"] for lib in listed.json()["libraries"]) == sorted(context.libraries)
    assert _roles(context, context.session) == dict.fromkeys(context.libraries, "viewer")


@when("a member of {group} signs in")
def step_group_member(context: Context, group: str) -> None:
    add_person(context, "dana", "u-dana", groups=[group])
    context.session = session_of(browser_sign_in(context, "u-dana"))


@then("they are an admin")
def step_is_admin(context: Context) -> None:
    assert whoami(context, context.session)["account"]["role"] == "admin"


@when("they are removed from {group} at the identity provider")
def step_removed_at_idp(context: Context, group: str) -> None:
    user = context.issuer.users["u-dana"]
    user.groups = [g for g in user.groups if g != group]


@then("they are a user again after the next membership check, without signing in again")
def step_user_again(context: Context) -> None:
    context.clock.advance(timedelta(minutes=61))
    report = context.client.portal.call(context.container.identity.revalidate_external_accounts)
    assert report.extended == 1, report
    assert whoami(context, context.session)["account"]["role"] == "user"


@when('someone holding the app role "{role}" signs in')
def step_app_role(context: Context, role: str) -> None:
    add_person(context, "erin", "u-erin")
    context.issuer.users["u-erin"].roles = [role]
    context.session = session_of(browser_sign_in(context, "u-erin"))


@then("they are a user with viewer on every library")
def step_user_viewer(context: Context) -> None:
    assert whoami(context, context.session)["account"]["role"] == "user"
    assert _roles(context, context.session) == dict.fromkeys(context.libraries, "viewer")
