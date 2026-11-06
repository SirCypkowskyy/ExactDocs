import type { components } from "./api-schema";

/**
 * What reads a private repository: a token (https) or a deploy key (ssh). Write-only: it lives in
 * the form's own state, goes out in a request body, and never into a query key, the query cache,
 * a URL, storage or a log.
 */
export type Credential =
  | components["schemas"]["AccessTokenIn"]
  | components["schemas"]["DeployKeyIn"];
export type CredentialKind = Credential["kind"];

/** What the person typed. `username` only counts for a token. */
export interface CredentialDraft {
  secret: string;
  username: string;
}

export const EMPTY_CREDENTIAL: CredentialDraft = { secret: "", username: "" };

const MAX_TOKEN = 4096;
const MAX_KEY = 16 * 1024;
const USERNAME = /^[A-Za-z0-9._-]{1,100}$/;
const LOOPBACK = /^http:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?\//i;

/** Which credential the address can carry: a token over https, a key over ssh, else none. */
export function credentialKindFor(rawUrl: string): CredentialKind | undefined {
  const url = rawUrl.trim();
  if (/^https:\/\//i.test(url) || LOOPBACK.test(url)) return "token";
  if (/^ssh:\/\//i.test(url) || /^[\w.-]+@[\w.-]+:(?!\/\/)/.test(url)) return "ssh_key";
  return undefined;
}

const KEY = /^-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----([\s\S]*?)-----END \1-----$/;

/**
 * A private key as ssh reads it. A password input drops line breaks from a pasted key, so a key
 * on one line is wrapped again: 70 columns for OpenSSH, 64 for PEM, as the tools write them.
 */
export function normalizeKey(raw: string): string {
  const text = raw.replace(/\r\n?/g, "\n").trim();
  const match = KEY.exec(text);
  if (!match) return text;
  const [, label = "", body = ""] = match;
  if (body.trim().includes("\n")) return text;
  const width = label === "OPENSSH PRIVATE KEY" ? 70 : 64;
  const rows = body.replace(/\s+/g, "").match(new RegExp(`.{1,${width}}`, "g")) ?? [];
  return [`-----BEGIN ${label}-----`, ...rows, `-----END ${label}-----`].join("\n");
}

/** The checks that need no server; the words never repeat the secret. */
export function validateCredential(kind: CredentialKind, draft: CredentialDraft) {
  if (kind === "token") {
    const token = draft.secret.trim();
    if (!token) return "Paste the access token.";
    if (token.length > MAX_TOKEN || /\s/.test(token)) {
      return "A token is one line without spaces. Paste it again.";
    }
    const user = draft.username.trim();
    if (user && !USERNAME.test(user)) {
      return "A user name has only letters, digits, dots, dashes and underscores.";
    }
    return undefined;
  }
  const key = normalizeKey(draft.secret);
  if (!key) return "Paste the private deploy key, or choose its file.";
  if (key.length > MAX_KEY) return "That key is too long for a deploy key.";
  const first = key.split("\n")[0] ?? "";
  if (!KEY.test(key)) {
    return "That isn't a private key. Use the file without .pub (its first line names a PRIVATE KEY).";
  }
  if (first.includes("ENCRYPTED") || key.includes("Proc-Type: 4,ENCRYPTED")) {
    return "That key has a passphrase. Use a deploy key without one.";
  }
  return undefined;
}

/** The value to send, or nothing when the boxes are empty. Validate first. */
export function credentialOf(kind: CredentialKind, draft: CredentialDraft): Credential | undefined {
  if (!draft.secret.trim()) return undefined;
  if (kind === "ssh_key") return { kind, private_key: normalizeKey(draft.secret) };
  const username = draft.username.trim();
  return { kind, token: draft.secret.trim(), ...(username && { username }) };
}

const SERVER_PREFIX = /^not a usable credential:\s*/i;

/** `invalid_credential`: the server's sentence is fixed text (it never repeats the secret). */
export function explainInvalidCredential(detail: string) {
  const why = detail.replace(SERVER_PREFIX, "").replace(/\.$/, "");
  return `The server can't use it: ${why}.`;
}

/** `host_key_changed`, in words: someone may be in the middle, or the server got a new key. */
export const HOST_KEY_CHANGED =
  "The repository's SSH server shows a different host key from the one ExactDocs saw first, so nothing was fetched. Someone may be intercepting the connection, or the server's key was replaced. Ask whoever runs that server; if the change is expected, an admin removes the old key from the known_hosts file in ExactDocs' data directory.";

/** A login refused with a token or key sent: it does not read this repository. */
export const refusedCredential = (kind: CredentialKind) =>
  kind === "token"
    ? "The repository refused this token. Check that it can read the repository and hasn't expired."
    : "The repository refused this deploy key. Check that its public half is added to the repository.";
