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
    admin_session,
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


SOURCES = {"GitHub team": "github_team", "GitHub organization": "github_org", "group": "group"}


def _rule(context: Context, rule: dict[str, str]) -> None:
    context.provider_config.setdefault("rules", []).append(rule)


def _parsed(text: str) -> dict[str, str]:
    """``GitHub team acme/docs-writers: contributor on every library`` as a REST rule."""
    named, grant = text.split(": ", 1)
    kind, value = named.rsplit(" ", 1)
    return {"source": SOURCES[kind], "value": value, "grant": GRANTS[grant]}


def _create(context: Context, library: str) -> None:
    command = CreateLibraryCommand(
        id=library,
        title=library.rsplit("/", 1)[-1],
        source_url=f"https://git.example.com{library}.git",
        host=HostKind.GIT,
    )
    context.client.portal.call(context.container.catalog.create_library, command)


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
        _create(context, library)


@given('an admin adds the rule "{text}"')
def step_admin_adds(context: Context, text: str) -> None:
    body = {"provider": context.provider, **_parsed(text)}
    added = send_as(
        context, "POST", "/api/v1/role-rules", session=admin_session(context), json=body
    )
    assert added.status_code == HTTPStatus.CREATED, added.text
    context.rule_ids = {**getattr(context, "rule_ids", {}), text: added.json()["id"]}


@when('an admin removes the rule "{text}"')
def step_admin_removes(context: Context, text: str) -> None:
    removed = send_as(
        context,
        "DELETE",
        f"/api/v1/role-rules/{context.rule_ids[text]}",
        session=admin_session(context),
    )
    assert removed.status_code == HTTPStatus.NO_CONTENT, removed.text


@when('the library "{library}" is created after the rule')
def step_created_later(context: Context, library: str) -> None:
    _create(context, library)
    context.libraries.append(library)


@then("they can edit and re-sync every library, including one created after the rule")
def step_contributor_everywhere(context: Context) -> None:
    assert _roles(context, context.session) == dict.fromkeys(context.libraries, "contributor")


@then("the Users page shows that this role comes from the rule")
def step_users_page(context: Context) -> None:
    users = send_as(context, "GET", "/api/v1/users", session=admin_session(context))
    assert users.status_code == HTTPStatus.OK, users.text
    [member] = [u for u in users.json()["users"] if u["provider"] == context.provider]
    assert member["rules"] == list(context.rule_ids.values()), member


@then("the UI shows these mappings as set by the configuration, read-only")
def step_read_only_rules(context: Context) -> None:
    session = admin_session(context)
    listed = send_as(context, "GET", "/api/v1/role-rules", session=session)
    assert listed.status_code == HTTPStatus.OK, listed.text
    body = listed.json()
    assert [(r["value"], r["configured"]) for r in body["rules"]] == [
        ("ExactDocs.Admin", True),
        ("ExactDocs.Reader", True),
    ]
    assert body["providers"][0]["configured_rules_only"] is True
    refused = send_as(
        context,
        "POST",
        "/api/v1/role-rules",
        session=session,
        json={"provider": "corp", "source": "role", "value": "Other", "grant": "viewer"},
    )
    assert (refused.status_code, refused.json()["error"]) == (409, "rules_configured_only")
    removed = send_as(
        context, "DELETE", f"/api/v1/role-rules/{body['rules'][0]['id']}", session=session
    )
    assert (removed.status_code, removed.json()["error"]) == (409, "configured_rule")


@then("their next edit of a library they could edit only through that rule is refused")
def step_refused_after_removal(context: Context) -> None:
    # A library its caller holds no role on is hidden: it answers as a missing one.
    read = send_as(context, "GET", "/api/v1/libraries/acme/docs", session=context.session)
    assert (read.status_code, read.json()["error"]) == (404, "not_found"), read.text
    assert _roles(context, context.session) == {}


@then("the access log names who added and removed the rule")
def step_rule_log(context: Context) -> None:
    log = send_as(context, "GET", "/api/v1/access-log", session=admin_session(context))
    assert log.status_code == HTTPStatus.OK, log.text
    events = [(e["change"], e["actor"], e["rule"]["value"]) for e in log.json()["events"]]
    assert events == [
        ("rule_removed", "ada", "acme/docs-writers"),
        ("rule_added", "ada", "acme/docs-writers"),
    ]


@given("the local admin is disabled")
def step_local_admin_disabled(context: Context) -> None:
    session = admin_session(context)
    me = whoami(context, session)["account"]["id"]
    disabled = send_as(context, "POST", f"/api/v1/users/{me}/disable", session=session)
    assert disabled.status_code == HTTPStatus.OK, disabled.text


@when('the admin from platform-admins removes the rule "{text}"')
def step_member_removes(context: Context, text: str) -> None:
    context.response = send_as(
        context, "DELETE", f"/api/v1/role-rules/{context.rule_ids[text]}", session=context.session
    )


@then('the removal is refused with "{code}"')
def step_removal_refused(context: Context, code: str) -> None:
    response = context.response
    assert (response.status_code, response.json()["error"]) == (409, code), response.text


@then("they are still an admin")
def step_still_admin(context: Context) -> None:
    step_is_admin(context)


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


@given("a member of {group} is signed in")
@given("a member of {group} signs in")
@when("a member of {group} signs in")
def step_group_member(context: Context, group: str) -> None:
    if context.provider_config["kind"] == "github":
        context.issuer.add_user("123", "carol")
        context.issuer.teams[:] = [tuple(group.split("/", 1))]
        context.session = session_of(browser_sign_in(context, "123"))
        return
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
