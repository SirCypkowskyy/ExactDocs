# Outbound connections

!!! abstract "TL;DR"

    - ExactDocs reads the standard proxy and CA bundle variables once, and every outbound client uses them.
    - `EXACTDOCS_HTTPS_PROXY`, `EXACTDOCS_HTTP_PROXY`, `EXACTDOCS_NO_PROXY` and `EXACTDOCS_CA_BUNDLE` replace their standard variable for ExactDocs alone.
    - AI provider profiles connect directly unless `EXACTDOCS_AI__USE_INSTANCE_PROXY=true` or they have a `proxy` of their own.
    - Loopback, link-local addresses and `metadata.google.internal` are never proxied.

ExactDocs reads the standard proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`,
`NO_PROXY`, in upper or lower case, lower case winning) and the standard CA bundle variables
(`SSL_CERT_FILE`, then `REQUESTS_CA_BUNDLE`, then `CURL_CA_BUNDLE`) once, and every outbound
client takes them from there: git, model downloads, AI providers, index backends, sign-in
providers, the OpenTelemetry exporter and the command-line client. Each `EXACTDOCS_` variable
below replaces its standard one, so ExactDocs can use another proxy than the rest of the machine.
[Behind a corporate proxy](../deployment/corporate-proxy.md) shows complete setups.

| Variable | Default | What it does |
|---|---|---|
| `EXACTDOCS_HTTPS_PROXY` | `https_proxy`, `HTTPS_PROXY`, then `ALL_PROXY` | The forward proxy of `https://` connections, as `http://host:port`; credentials go in the URL (`http://user:password@host:port`, percent-encoded) and are never logged or shown |
| `EXACTDOCS_HTTP_PROXY` | `http_proxy`, `HTTP_PROXY`, then `ALL_PROXY` | The forward proxy of plain `http://` connections |
| `EXACTDOCS_NO_PROXY` | `no_proxy`, `NO_PROXY` | Hosts reached without the proxy, separated by commas or spaces:<br/>a host name (and every name under it: `example.com`, `.example.com` and `*.example.com` all match `docs.example.com`),<br/>an IP address, a CIDR range (`10.0.0.0/8`, `fd00::/8`, matched against URLs that name an address; a host name is never resolved for it),<br/>`host:port` for one port only,<br/>or `*` for every host.<br/>Set but empty, it lists no host.<br/>Loopback (`localhost`, `127.0.0.0/8`, `::1`), link-local addresses (`169.254.0.0/16`, the cloud metadata endpoints) and `metadata.google.internal` are never proxied, whatever it says |
| `EXACTDOCS_CA_BUNDLE` | `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, then `CURL_CA_BUNDLE` | A PEM file of the CA certificates every outbound TLS connection trusts, git included (as its `http.sslCAInfo`), instead of the system's: the company CA of a proxy that re-signs TLS.<br/>It replaces the system's certificates, so include the public ones too when some hosts are reached without the re-signing proxy.<br/>A file that cannot be read stops the server at start.<br/>Verification is never turned off |
| `EXACTDOCS_AI__USE_INSTANCE_PROXY` | `false` | AI provider profiles without a `proxy` of their own call their provider (and Entra ID) through the proxy above, unless `NO_PROXY` lists the endpoint.<br/>Off, they connect directly, as before #538; a profile's own `proxy` always wins.<br/>The CA bundle applies to them either way.<br/>See [Behind a corporate proxy](../deployment/corporate-proxy.md) |

The proxy can be `socks5://` (or `socks5h://`) where the client supports it: git does, the Python
clients need the `socksio` package. Redis and MongoDB backends speak their own protocols, which no
HTTP proxy carries: they connect directly, and use the CA bundle for TLS when their options name
no CA file.
