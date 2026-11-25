# Behind a corporate proxy

!!! abstract "TL;DR"

    - Give ExactDocs the standard `HTTPS_PROXY`, `HTTP_PROXY` and `NO_PROXY`, plus a CA bundle if the proxy re-signs TLS.
    - Every outbound client uses them, except Redis and MongoDB, whose protocols an HTTP proxy does not carry.
    - AI provider profiles use the proxy only with `EXACTDOCS_AI__USE_INSTANCE_PROXY=true`.
    - Git over SSH needs a forwarder in front of ExactDocs.

In a network whose only way out is a forward proxy, give ExactDocs the standard variables. It
reads them once, with the CA bundle, and hands the result to every client that connects out: git,
model downloads, AI providers, external index backends, sign-in providers, the OpenTelemetry
exporter and the command-line client ([Outbound connections](../configuration/outbound.md)
lists the settings).

=== "Docker Compose"

    ```yaml
    # docker-compose.yml, behind a proxy
    services:
      exactdocs:
        image: ghcr.io/sircypkowskyy/exactdocs:latest
        environment:
          HTTPS_PROXY: ${CORP_PROXY_URL}            # http://user:password@proxy.corp.example:3128
          HTTP_PROXY: ${CORP_PROXY_URL}
          NO_PROXY: ".corp.example,10.0.0.0/8"      # internal git, model gateway, index backends
          EXACTDOCS_CA_BUNDLE: /etc/exactdocs/ca/corp-ca.pem   # only if the proxy re-signs TLS
          EXACTDOCS_AI__USE_INSTANCE_PROXY: "true"  # only if AI providers are reached through it too
        volumes:
          - exactdocs-data:/data
          - ./corp-ca.pem:/etc/exactdocs/ca/corp-ca.pem:ro
    ```

=== "uvx"

    With `uvx`, export the same variables; uv itself downloads ExactDocs through the same proxy (it
    reads `HTTPS_PROXY`, and trusts the company CA with `SSL_CERT_FILE` or `--native-tls`):

    ```bash
    export HTTPS_PROXY=http://proxy.corp.example:3128 NO_PROXY=.corp.example,10.0.0.0/8
    export SSL_CERT_FILE=/usr/local/share/ca-certificates/corp-ca.pem   # read by uv and ExactDocs
    uvx exactdocs serve
    ```

=== "Kubernetes"

    On Kubernetes, keep a proxy URL with credentials in a Secret, the CA in a ConfigMap, and list the
    cluster's own names in `NO_PROXY`:

    ```yaml
    env:
      - name: HTTPS_PROXY
        valueFrom: { secretKeyRef: { name: corp-proxy, key: url } }
      - name: HTTP_PROXY
        valueFrom: { secretKeyRef: { name: corp-proxy, key: url } }
      - name: NO_PROXY
        value: ".svc.cluster.local,.corp.example,10.0.0.0/8"
      - name: EXACTDOCS_CA_BUNDLE
        value: /etc/exactdocs/ca/corp-ca.pem
    volumeMounts:
      - { name: corp-ca, mountPath: /etc/exactdocs/ca, readOnly: true }
    volumes:
      - { name: corp-ca, configMap: { name: corp-ca } }
    ```

How it is read:

- **Each setting on its own.** `EXACTDOCS_HTTPS_PROXY`, `EXACTDOCS_HTTP_PROXY`, `EXACTDOCS_NO_PROXY`
  and `EXACTDOCS_CA_BUNDLE` replace their standard variable when set, so ExactDocs can use another
  proxy than the rest of the machine. Otherwise lower case wins over upper case (`https_proxy`
  over `HTTPS_PROXY`), and `ALL_PROXY` fills a scheme without a proxy of its own.
- **`NO_PROXY`.** Host names match themselves and every name under them, IP addresses and CIDR
  ranges match URLs that name an address (host names are never resolved for it), `host:port`
  matches one port, `*` every host. Loopback, link-local addresses (the cloud metadata endpoint,
  `169.254.169.254`, where managed identities get their tokens) and `metadata.google.internal`
  are never proxied.
- **Credentials** in the proxy URL work everywhere and are never shown: logs, errors and the
  probes print `http://***@proxy.corp.example:3128`. At start the server logs the proxies,
  `NO_PROXY` and the CA bundle it uses, that way.
- **The CA bundle replaces the system's certificates**, as `SSL_CERT_FILE` does, for every client
  and for git (`GIT_SSL_CAINFO`, its `http.sslCAInfo`). If some hosts are reached without the
  re-signing proxy, use a bundle with the public CAs and the company's (`cat
  /etc/ssl/certs/ca-certificates.crt corp-ca.pem`). Verification is never turned off.
- **Libraries that read only the environment** (google-auth's token refresh for Vertex AI,
  FastMCP's MCP OAuth proxy, the Elasticsearch and Chroma clients) follow the same settings: the
  server and every command write the resolution into the standard variables of their own process
  when they start. Their HTTP library may not understand everything `NO_PROXY` can say (a CIDR
  range, for httpx): list such a host by name too.
- **AI provider profiles** keep their own `proxy`, which always wins. A profile without one
  connects directly unless `EXACTDOCS_AI__USE_INSTANCE_PROXY=true`; then it goes through the
  instance's proxy unless `NO_PROXY` lists its endpoint. The default keeps what profiles did
  before: a proxy set in the environment for git does not reroute a profile's traffic to an
  internal gateway that `NO_PROXY` does not list. The CA bundle applies to profiles either way.

| Connection | Through the proxy | CA bundle |
|---|---|---|
| git over HTTP(S) (imports, syncs, previews) | yes, unless `NO_PROXY` lists the host | yes |
| git over SSH | no: see below | (SSH has no CA) |
| `exactdocs models pull` (Hugging Face Hub, `HF_ENDPOINT`) | yes; the Hub's Xet transfers are turned off for the pull when a proxy or a CA bundle is set, so every byte goes through the same client | yes |
| AI providers | the profile's `proxy`; else the instance's with `EXACTDOCS_AI__USE_INSTANCE_PROXY` | yes |
| Entra ID for AI profiles and Azure AI Search | as the profile; otherwise the standard variables, which azure-identity reads.<br/>Managed identity's endpoint never | yes |
| Sign-in providers (OIDC, OAuth2, GitHub), Cloudflare Access keys | yes | yes |
| Qdrant, Pinecone, libSQL server, Azure AI Search, OpenSearch | yes, given to the client explicitly | yes |
| Elasticsearch, Chroma | yes, through the standard variables (their clients read only those) | yes (`ca_certs` / `chroma_server_ssl_verify` by default) |
| Milvus (gRPC) | yes, as the channel's `grpc.http_proxy` | yes, for `https://` |
| Redis, MongoDB | no: an HTTP proxy does not carry their protocols | yes, for TLS, when the options name no CA file |
| DuckDB, LanceDB or Milvus Lite on a local directory | no connection at all | - |
| OpenTelemetry exporter | yes | yes, unless `OTEL_EXPORTER_OTLP_CERTIFICATE` names one |
| The command-line client | yes for a remote server; never for loopback | yes |

When the proxy is what failed, the error says so, with the proxy and the host:

```text
the repository is unreachable: the proxy http://***@proxy.corp.example:3128 wants credentials to reach github.com:443 (407 Proxy Authentication Required): give them in the proxy URL, http://user:password@host:port
TLS failed reaching llm.example.com:443 through the proxy http://proxy.corp.example:3128 (...): a proxy that re-signs TLS needs its CA in the CA bundle (EXACTDOCS_CA_BUNDLE or SSL_CERT_FILE)
the proxy http://proxy.corp.example:3128 refused the connection to git.example.com:443 (CONNECT tunnel failed, HTTP 403)
```

## Git over SSH behind a proxy

An HTTP proxy does not carry SSH, and ExactDocs runs `ssh` with no configuration file
(`-F /dev/null`, no agent), so a `ProxyCommand` in `~/.ssh/config` does not apply to it. Either
import over HTTPS with a token, or do what a `ProxyCommand` would do in front of ExactDocs: a
forwarder that opens a `CONNECT` tunnel through the proxy, on a port of its own, with the library
pointing at that port. Many proxies allow `CONNECT` to port 443 only; GitHub answers SSH there as
`ssh.github.com`:

```bash
# one forwarder per SSH host, next to ExactDocs (socat; `ncat --proxy` works the same way)
socat TCP-LISTEN:2222,fork,reuseaddr \
  PROXY:proxy.corp.example:ssh.github.com:443,proxyport=3128,proxyauth=user:password
# then add the library as ssh://git@localhost:2222/acme/docs.git (with its deploy key)
```

The host key is then remembered for `[localhost]:2222`, and checked on every fetch as usual.
