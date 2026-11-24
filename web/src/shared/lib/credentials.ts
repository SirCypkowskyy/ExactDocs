import type { components } from "./api-schema";
import { currentLanguage, defineMessages, type Language } from "./i18n";

/** What the credential checks and the server's credential refusals say. */
const messages = defineMessages(
  {
    pasteToken: "Paste the access token.",
    tokenShape: "A token is one line without spaces. Paste it again.",
    usernameShape: "A user name has only letters, digits, dots, dashes and underscores.",
    pasteKey: "Paste the private deploy key, or choose its file.",
    keyTooLong: "That key is too long for a deploy key.",
    notPrivate:
      "That isn't a private key. Use the file without .pub (its first line names a PRIVATE KEY).",
    passphrase:
      "This key has a passphrase, and ExactDocs can't type it. Use a deploy key without one.",
    serverRefused: (why: string) => `The server can't use it: ${why}.`,
    hostKeyChanged:
      "The repository's SSH server shows a different host key from the one ExactDocs saw first, so nothing was fetched. Someone may be intercepting the connection, or the server's key was replaced. Ask whoever runs that server; if the change is expected, an admin removes the old key from the known_hosts file in ExactDocs' data directory.",
    refusedToken:
      "The repository refused this token. Check that it can read the repository and hasn't expired.",
    refusedKey:
      "The repository refused this deploy key. Check that its public half is added to the repository.",
  },
  {
    pasteToken: "Wklej token dostępu.",
    tokenShape: "Token to jeden wiersz bez spacji. Wklej go ponownie.",
    usernameShape:
      "Nazwa użytkownika może zawierać tylko litery, cyfry, kropki, myślniki i podkreślenia.",
    pasteKey: "Wklej prywatny klucz wdrożeniowy albo wybierz jego plik.",
    keyTooLong: "Ten klucz jest za długi jak na klucz wdrożeniowy.",
    notPrivate:
      "To nie jest klucz prywatny. Użyj pliku bez rozszerzenia .pub (jego pierwszy wiersz zawiera PRIVATE KEY).",
    passphrase:
      "Ten klucz jest chroniony hasłem, którego ExactDocs nie może wpisać. Użyj klucza wdrożeniowego bez hasła.",
    serverRefused: (why) => `Serwer nie może go użyć: ${why}.`,
    hostKeyChanged:
      "Serwer SSH repozytorium przedstawia inny klucz hosta niż ten, który ExactDocs zobaczył za pierwszym razem, więc nic nie zostało pobrane. Ktoś może przechwytywać połączenie albo klucz serwera został wymieniony. Zapytaj osobę, która zarządza tym serwerem; jeśli zmiana jest oczekiwana, administrator usuwa stary klucz z pliku known_hosts w katalogu danych ExactDocs.",
    refusedToken:
      "Repozytorium odrzuciło ten token. Sprawdź, czy ma prawo odczytu repozytorium i czy nie wygasł.",
    refusedKey:
      "Repozytorium odrzuciło ten klucz wdrożeniowy. Sprawdź, czy jego część publiczna została dodana do repozytorium.",
  },
);

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

/**
 * Which credential the address can carry: a token over https, a key over ssh, else none. Plain
 * http to localhost takes a token too: it mirrors the server's `check_credential_fits`, which
 * allows it for local mirrors (the token never crosses a network there).
 */
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
  // Already wrapped, or PEM headers (an encrypted key): leave it as it is.
  if (body.trim().includes("\n") || body.includes(":")) return text;
  const width = label === "OPENSSH PRIVATE KEY" ? 70 : 64;
  const rows = body.replace(/\s+/g, "").match(new RegExp(`.{1,${width}}`, "g")) ?? [];
  return [`-----BEGIN ${label}-----`, ...rows, `-----END ${label}-----`].join("\n");
}

/** The checks that need no server; the words never repeat the secret. */
export function validateCredential(
  kind: CredentialKind,
  draft: CredentialDraft,
  language: Language = currentLanguage(),
) {
  const t = messages[language];
  if (kind === "token") {
    const token = draft.secret.trim();
    if (!token) return t.pasteToken;
    if (token.length > MAX_TOKEN || /\s/.test(token)) return t.tokenShape;
    const user = draft.username.trim();
    if (user && !USERNAME.test(user)) return t.usernameShape;
    return undefined;
  }
  const key = normalizeKey(draft.secret);
  if (!key) return t.pasteKey;
  if (key.length > MAX_KEY) return t.keyTooLong;
  if (!KEY.test(key)) return t.notPrivate;
  if (hasPassphrase(draft.secret)) return t.passphrase;
  return undefined;
}

/**
 * The English sentence for a key with a passphrase.
 * @deprecated The words depend on the language: compare with `validateCredential`'s result in
 * the language under test instead.
 */
export const PASSPHRASE = messages.en.passphrase;

const MAGIC = "openssh-key-v1\0";

/**
 * Whether a key is encrypted, read from what was typed (before any re-wrapping): the PEM armour
 * or `Proc-Type` header says so, and an OpenSSH key names its cipher (`none` without a passphrase)
 * right after its magic. The server makes the same check.
 */
export function hasPassphrase(raw: string): boolean {
  if (/-----BEGIN [A-Z ]*ENCRYPTED/.test(raw) || /Proc-Type:\s*4,\s*ENCRYPTED/.test(raw)) {
    return true;
  }
  const match = KEY.exec(raw.replace(/\r\n?/g, "\n").trim());
  if (match?.[1] !== "OPENSSH PRIVATE KEY") return false;
  let blob: string;
  try {
    // Enough of the key for the magic and the cipher name; the rest is never decoded.
    blob = atob((match?.[2] ?? "").replace(/\s+/g, "").slice(0, 64));
  } catch {
    return false;
  }
  if (!blob.startsWith(MAGIC)) return false;
  const at = MAGIC.length;
  const size =
    ((blob.charCodeAt(at) << 24) |
      (blob.charCodeAt(at + 1) << 16) |
      (blob.charCodeAt(at + 2) << 8) |
      blob.charCodeAt(at + 3)) >>>
    0;
  const cipher = blob.slice(at + 4, at + 4 + size);
  return cipher !== "none" && cipher !== "";
}

/** The value to send, or nothing when the boxes are empty. Validate first. */
export function credentialOf(kind: CredentialKind, draft: CredentialDraft): Credential | undefined {
  if (!draft.secret.trim()) return undefined;
  if (kind === "ssh_key") return { kind, private_key: normalizeKey(draft.secret) };
  const username = draft.username.trim();
  return { kind, token: draft.secret.trim(), ...(username && { username }) };
}

const SERVER_PREFIX = /^not a usable credential:\s*/i;

/**
 * `invalid_credential`: the server's sentence is fixed text (it never repeats the secret). Its
 * reason stays in the server's words; only the sentence around it follows the language.
 */
export function explainInvalidCredential(detail: string, language: Language = currentLanguage()) {
  const t = messages[language];
  if (/passphrase/i.test(detail)) return t.passphrase;
  const why = detail.replace(SERVER_PREFIX, "").replace(/\.$/, "");
  return t.serverRefused(why);
}

/** `host_key_changed`, in words: someone may be in the middle, or the server got a new key. */
export const hostKeyChanged = (language: Language = currentLanguage()) =>
  messages[language].hostKeyChanged;

/** A login refused with a token or key sent: it does not read this repository. */
export const refusedCredential = (kind: CredentialKind, language: Language = currentLanguage()) =>
  kind === "token" ? messages[language].refusedToken : messages[language].refusedKey;
