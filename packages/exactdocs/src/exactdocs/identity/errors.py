from collections.abc import Sequence

from exactdocs_kernel import (
    BusyError,
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthenticatedError,
    ValidationError,
)


class InvalidUsernameError(ValidationError):
    """A username is blank, too long or contains whitespace or control characters."""

    code = "invalid_username"

    def __init__(self, max_length: int) -> None:
        """Create the error.

        Args:
            max_length: The most characters allowed, for the message.
        """
        super().__init__(
            f"username must be 1 to {max_length} characters, "
            "without whitespace or control characters"
        )


class AlreadySetUpError(ConflictError):
    """The first admin exists, so the setup is over."""

    code = "already_set_up"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the instance is already set up: an account exists")


class InvalidCredentialsError(UnauthenticatedError):
    """Wrong password or unknown user; deliberately the same error for both."""

    code = "invalid_credentials"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("invalid username or password")


class WrongPasswordError(ForbiddenError):
    """A signed-in person gave a wrong current password while changing it.

    Not ``InvalidCredentialsError``: the caller stays signed in (a 401 would read as signed out).
    """

    code = "wrong_password"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the current password is wrong")


class NotSignedInError(UnauthenticatedError):
    """No session, or one that is unknown, expired or ended; deliberately not told apart."""

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("sign in to use this")


class UnknownAccountError(NotFoundError):
    """No account has this username or id. Only operators (command line, users page) learn this."""

    code = "unknown_account"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("no account has this username")


class ReservedUsernameError(ValidationError):
    """A new username holds a sequence the sign-in throttle uses in its own keys."""

    code = "invalid_username"

    def __init__(self, reserved: str) -> None:
        """Create the error.

        Args:
            reserved: The sequence that is not allowed, for the message.
        """
        super().__init__(f"a username may not contain {reserved!r}")


class UsernameTakenError(ConflictError):
    """Another account already has this username (compared case-insensitively)."""

    code = "username_taken"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("another account already has this username")


class NotSetUpError(ConflictError):
    """No account exists yet: the first one is the admin, made by the setup, not a user."""

    code = "not_set_up"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__(
            "the instance is not set up: create the first admin first (exactdocs admin create)"
        )


class LastOperatorError(ConflictError):
    """Disabling this account would leave no enabled admin to manage the others."""

    code = "last_operator"

    def __init__(self, message: str = "the last enabled admin cannot be disabled") -> None:
        """Create the error.

        Args:
            message: What was refused.
        """
        super().__init__(message)


class NotAnOperatorError(ForbiddenError):
    """The caller is signed in, but only an admin may do this."""

    def __init__(self, action: str = "manages user accounts") -> None:
        """Say what only an admin does.

        Args:
            action: What was refused, e.g. ``manages user accounts``.
        """
        super().__init__(f"only an admin {action}")


class InvalidTokenNameError(ValidationError):
    """A token name is blank or too long."""

    code = "invalid_token_name"

    def __init__(self, max_length: int) -> None:
        """Create the error.

        Args:
            max_length: The most characters allowed, for the message.
        """
        super().__init__(f"token name must be 1 to {max_length} characters")


class InvalidTokenExpiryError(ValidationError):
    """A token would expire before it exists."""

    code = "invalid_token_expiry"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("a token must expire in the future")


class TooManyTokensError(ConflictError):
    """The account already holds the most tokens it may."""

    code = "too_many_tokens"

    def __init__(self, limit: int) -> None:
        """Create the error.

        Args:
            limit: The most tokens an account may hold, for the message.
        """
        super().__init__(f"an account may hold at most {limit} API tokens; revoke one first")


class InvalidTokenError(UnauthenticatedError):
    """An API token that is unknown, expired or revoked; deliberately not told apart."""

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the API token is invalid, expired or revoked")


class UnknownTokenError(NotFoundError):
    """No token of the caller has this id."""

    code = "unknown_token"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("no such token")


class SignInThrottledError(RateLimitedError):
    """Too many failed sign-ins from this address or for this username; the password is unchecked.

    Deliberately says neither which of the two it is nor whether the username exists.
    """

    def __init__(self, retry_after: int) -> None:
        """Create the error.

        Args:
            retry_after: Seconds until the next attempt may go ahead.
        """
        super().__init__(
            f"too many failed sign-ins; try again in {retry_after} seconds", retry_after
        )


class UnknownSignInProviderError(NotFoundError):
    """No sign-in provider of this name is configured."""

    code = "unknown_provider"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("no sign-in provider of this name is configured")


class ExternalSignInFailedError(UnauthenticatedError):
    """An external sign-in could not be completed and proves nothing about who the caller is.

    The browser binding, the ``state``, the attempt's age, the code exchange or the ID token
    (signature, issuer, audience, times, ``nonce``) did not check out. Deliberately not told
    apart: the adapter logs the reason, the caller only learns to start again.
    """

    code = "sign_in_failed"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the sign-in could not be completed; start it again")


class SignInCancelledError(UnauthenticatedError):
    """The identity provider answered the sign-in with an error (the person cancelled, say)."""

    code = "sign_in_cancelled"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the identity provider did not sign you in")


class NotAllowedError(ForbiddenError):
    """The provider vouched for the person, who is in none of its allowed groups."""

    code = "not_allowed"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("not a member of an allowed group")


class AccountDisabledError(ForbiddenError):
    """An operator disabled the account an external identity is linked to."""

    code = "account_disabled"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("account disabled")


class UsernameUnavailableError(ConflictError):
    """A first external sign-in found no free username: neither its own nor ``<name>@<provider>``.

    The message is for the operator, who reads it in the person's report.
    """

    code = "username_unavailable"

    def __init__(self, taken: Sequence[str] = ()) -> None:
        """Create the error.

        Args:
            taken: The usernames tried, all taken; empty when the provider sent none usable.
        """
        detail = (
            f"the usernames {' and '.join(repr(name) for name in taken)} are taken"
            if taken
            else "the identity provider sent no usable username or email"
        )
        super().__init__(
            f"no account could be created: {detail}; an operator can free the name or set "
            "the provider's username_claim"
        )


class ProviderUnavailableError(BusyError):
    """The identity provider could not be reached, or answered in a way that cannot be used."""

    code = "provider_unavailable"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the identity provider cannot be reached; try again later", retry_after=30)


class AccessAssertionRefusedError(UnauthenticatedError):
    """A Cloudflare Access token that proves nothing: its signature, issuer, audience or times.

    Deliberately not told apart: the verifier logs the reason (never the token), and the request
    is treated as if it carried no token.
    """

    code = "access_assertion_refused"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the Cloudflare Access token was refused")


class ProviderAccessRevokedError(UnauthenticatedError):
    """The identity provider refused the stored refresh token: the grant was revoked or expired."""

    code = "provider_access_revoked"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the identity provider revoked the sign-in")


class ExternalAccountError(ConflictError):
    """The account signs in through an identity provider: it has no password to check or reset."""

    code = "external_account"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("this account signs in through an identity provider and has no password")


class LibraryRoleRequiredError(ForbiddenError):
    """The caller's role on the library is too low for what they asked."""

    def __init__(self, needed: str) -> None:
        """Say which role is missing.

        Args:
            needed: The lowest library role that may do it.
        """
        super().__init__(f"this needs the {needed} role on the library")


class InvalidGrantError(ValidationError):
    """A library grant asks for something the sharing routes do not do."""

    code = "invalid_grant"

    def __init__(self, reason: str) -> None:
        """Say what is wrong.

        Args:
            reason: What is wrong with the grant.
        """
        super().__init__(reason)


class UnknownGrantError(NotFoundError):
    """The library has no grant for this user or group."""

    code = "unknown_grant"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("the library has no such grant")


class GithubAccessDeniedError(ProviderAccessRevokedError):
    """GitHub refused organization/team admission or requires administrator action."""

    code = "github_access_denied"

    def __init__(self, reason: str, *, refusal_code: str = "github_access_denied") -> None:
        """Create a safe refusal containing only configured organization names.

        Args:
            reason: The fixed refusal message with the configured organization, if applicable.
            refusal_code: A known browser refusal code, optionally suffixed with a safe org.
        """
        self.code = refusal_code
        UnauthenticatedError.__init__(self, reason)


class InvalidPreferencesError(ValidationError):
    """Interface preferences hold a value the interface does not offer."""

    code = "invalid_preferences"

    def __init__(self, reason: str) -> None:
        """Create the error.

        Args:
            reason: Which preference is wrong, and what it may be.
        """
        super().__init__(reason)


class NoLinkedAccountError(ForbiddenError):
    """A provider that creates no accounts vouched for an identity no account has linked."""

    code = "not_linked"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__(
            "no account is linked to this identity: sign in another way and link it under "
            "Account settings"
        )


class IdentityLinkedElsewhereError(ConflictError):
    """The identity a person tried to link to their account is linked to another account."""

    code = "identity_linked_elsewhere"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("this identity is linked to another account")


class ProviderAlreadyLinkedError(ConflictError):
    """The account has an identity of this provider already (one per provider)."""

    code = "provider_linked"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("an identity of this provider is linked to the account already")


class ProviderNotLinkedError(NotFoundError):
    """The account has no identity of this provider to unlink."""

    code = "provider_not_linked"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("no identity of this provider is linked to the account")


class LastSignInMethodError(ConflictError):
    """Unlinking would take away the account's way in: the provider it was created through.

    An account without a password follows that provider (its role, groups and access), so it
    stays linked whatever else is.
    """

    code = "last_sign_in_method"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__(
            "the account has no password and was created through this provider, which it signs "
            "in with and follows: it cannot be unlinked"
        )


class NoProviderIconError(NotFoundError):
    """The provider has no icon of its own for ExactDocs to serve (none, or a built-in one)."""

    code = "no_icon"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("this sign-in provider has no icon of its own")


class LinkRefusedError(DomainError):
    """A link from Account settings came back from the provider and was refused.

    Carries where the browser goes back to (the link's ``return_to``) and why (``refusal``);
    the error's own code is the refusal's.
    """

    def __init__(self, refusal: DomainError, return_to: str) -> None:
        """Wrap the refusal.

        Args:
            refusal: Why the link was refused.
            return_to: The same-origin path the link was started from.
        """
        super().__init__(str(refusal))
        self.code = refusal.code
        self.refusal = refusal
        self.return_to = return_to


class InvalidRoleRuleError(ValidationError):
    """A role rule names its source or its libraries in a form that cannot match anyone."""

    code = "invalid_role_rule"

    def __init__(self, reason: str) -> None:
        """Create the error.

        Args:
            reason: What is wrong with the rule.
        """
        super().__init__(f"invalid role rule: {reason}")


class UnknownRoleRuleError(NotFoundError):
    """No stored role rule has this ID."""

    code = "unknown_role_rule"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("no role rule has this ID")


class ConfiguredRuleError(ConflictError):
    """The rule comes from the configuration file, which is the only place to change it."""

    code = "configured_rule"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("this rule is set by the configuration file: change it there")


class RulesConfiguredOnlyError(ConflictError):
    """The provider takes only the rules of the configuration file."""

    code = "rules_configured_only"

    def __init__(self, provider: str) -> None:
        """Create the error.

        Args:
            provider: The provider's name.
        """
        super().__init__(
            f"sign-in provider {provider!r} takes only the configuration file's rules "
            "(configured_rules_only)"
        )


class RoleRuleExistsError(ConflictError):
    """The same rule is stored already."""

    code = "role_rule_exists"

    def __init__(self) -> None:
        """Create the error with its fixed message."""
        super().__init__("this provider already has a rule with this source and grant")
