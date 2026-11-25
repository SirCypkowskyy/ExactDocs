# Behind a reverse proxy

!!! abstract "TL;DR"

    - Set `EXACTDOCS_ALLOWED_HOSTS` to the public host names and `EXACTDOCS_FORWARDED_ALLOW_IPS` to the proxy's address.
    - List only the proxy, never a whole range.
    - With a sign-in provider, also set `EXACTDOCS_PUBLIC_URL`.
    - Behind Cloudflare Access, keep the origin reachable only through the tunnel.

Set these:

- `EXACTDOCS_ALLOWED_HOSTS`: the public host name(s). The server answers only to localhost and the
  names listed here; this is its guard against DNS rebinding.
- `EXACTDOCS_FORWARDED_ALLOW_IPS`: the proxy's own address, so that `X-Forwarded-*` is trusted.
- `EXACTDOCS_SECURE_COOKIES=true`, if TLS ends at a proxy that does not forward
  `X-Forwarded-Proto` from a trusted address. An `https://` `EXACTDOCS_PUBLIC_URL` makes the
  cookies `Secure` too, so with one set you can leave this out.

If people sign in through an identity provider, also set `EXACTDOCS_PUBLIC_URL` to the address
they use, such as `https://docs.example.com` (no path). The redirect URI that ExactDocs sends to
the provider is built from it, never from the request's `Host` header, so it stays right behind
any proxy. The server refuses to start with a provider configured and no public URL (see
[Sign in through an identity provider](../getting-started.md#sign-in-through-an-identity-provider)).

If the proxy is not listed in `EXACTDOCS_FORWARDED_ALLOW_IPS`, every client looks like the proxy,
and 5 failed sign-ins from anyone throttle everyone.

!!! warning "List only the proxy"
    Whatever `EXACTDOCS_FORWARDED_ALLOW_IPS` lists can choose the client address the server sees,
    through `X-Forwarded-For`. List only the proxy, not a range such as `172.16.0.0/12`, which
    covers every container on every Docker network of the host.

To pin the proxy's address, give it a fixed one on a network of its own:

```yaml
services:
  proxy:
    networks: { edge: { ipv4_address: 172.30.0.2 } }
  exactdocs:
    environment:
      EXACTDOCS_FORWARDED_ALLOW_IPS: "172.30.0.2"
    networks: [edge]
networks:
  edge:
    ipam: { config: [{ subnet: 172.30.0.0/24 }] }
```

## Behind Cloudflare Access

A common setup publishes ExactDocs through a Cloudflare Tunnel with an Access application in
front. ExactDocs can then trust the identity Access checked, so people do not sign in a second
time and MCP clients need only the Access service-token headers.

1. **Make the origin reachable only through the tunnel.** Run `cloudflared` next to ExactDocs and
   do not publish ExactDocs' port to the host or the internet (no `ports:` in Compose, a
   firewall in front of anything else). Anyone who can reach the origin directly can replay a
   stolen Access token; nobody can forge one, since its signature is checked.
2. **Create a self-hosted Access application** for the public host name. Copy its
   **Application Audience (AUD) tag** (application overview) and note your team domain
   (`https://<team>.cloudflareaccess.com`, under Zero Trust settings).
3. **Configure ExactDocs** (all fields: [Cloudflare Access](../configuration/sign-in.md#cloudflare-access)):

    ```yaml
    services:
      exactdocs:
        environment:
          EXACTDOCS_ALLOWED_HOSTS: "docs.acme.com"
          EXACTDOCS_PUBLIC_URL: "https://docs.acme.com"
          EXACTDOCS_AUTH__CLOUDFLARE_ACCESS__TEAM_DOMAIN: "https://acme.cloudflareaccess.com"
          EXACTDOCS_AUTH__CLOUDFLARE_ACCESS__AUDIENCE: '["<aud tag>"]'
          EXACTDOCS_AUTH__CLOUDFLARE_ACCESS__ADMIN_EMAILS: '["ada@acme.com"]'
          EXACTDOCS_AUTH__CLOUDFLARE_ACCESS__SERVICE_TOKENS: '{"<client id>.access": "ci-bot"}'
      cloudflared:
        image: cloudflare/cloudflared:latest
        command: tunnel --no-autoupdate run
        environment:
          TUNNEL_TOKEN: ${TUNNEL_TOKEN}
    ```

4. **For MCP clients and scripts**, create an Access **service token**, add a *Service Auth*
   policy for it to the application, create the account it acts as on the **Users** page (for
   example `ci-bot`, then give it library roles), and map the token's client ID to that account
   in `service_tokens`. See [MCP behind Cloudflare Access](../mcp.md#behind-cloudflare-access).

What people see: after the Access login, the web UI opens signed in, with no sign-in form. The
**Account** page says the sign-in comes from Cloudflare Access, and **Sign out** goes to
`<team_domain>/cdn-cgi/access/logout`, which ends the Access session too (ending only the
ExactDocs session would sign the browser straight back in). The local admin from the setup keeps
working with its password, for example from inside the network.
