Feature: MCP hosts connect with OAuth as well as API tokens
  As a team that signs in through its identity provider
  I want web MCP hosts (Claude, ChatGPT), which cannot paste a token, to connect with OAuth
  So that agents use the same identity and membership checks as people do

  Background:
    Given sign-in provider "corp" of kind "oidc" with issuer "https://idp.example.com"
    And MCP OAuth is served through provider "corp", which allows only group "docs"

  Scenario: A web host connects with OAuth
    When a web MCP host discovers the OAuth metadata and signs "alice" (group "docs") in
    Then it can call "list_libraries" as that user
    And API tokens keep working

  Scenario: A person outside the allowed group cannot use a token
    When a web MCP host signs "bob" (group "other") in
    Then the token is refused and no tool can be called

  Scenario: An OAuth member reads a library shared with their group
    Given the library "/acme/docs" is shared with OAuth group "docs"
    When a web MCP host discovers the OAuth metadata and signs "alice" (group "docs") in
    Then the OAuth host lists the library "/acme/docs"
