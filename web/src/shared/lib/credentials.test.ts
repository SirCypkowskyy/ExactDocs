import { describe, expect, it } from "vitest";
import {
  credentialKindFor,
  credentialOf,
  explainInvalidCredential,
  hasPassphrase,
  hostKeyChanged,
  normalizeKey,
  PASSPHRASE,
  refusedCredential,
  validateCredential,
} from "./credentials";

// Not a real key: the shape is all that matters here.
const BODY = "QUJDREVGR0hJSktMTU5PUFFS".repeat(8);
const wrapped = (label: string, width: number) =>
  [
    `-----BEGIN ${label}-----`,
    ...(BODY.match(new RegExp(`.{1,${width}}`, "g")) ?? []),
    `-----END ${label}-----`,
  ].join("\n");

describe("credentials", () => {
  it("picks the credential an address can carry", () => {
    expect(credentialKindFor("https://github.com/acme/x")).toBe("token");
    expect(credentialKindFor("http://localhost:8080/acme/x.git")).toBe("token");
    expect(credentialKindFor("http://git.example.com/acme/x.git")).toBeUndefined();
    expect(credentialKindFor("ssh://git@github.com/acme/x.git")).toBe("ssh_key");
    expect(credentialKindFor("git@github.com:acme/x.git")).toBe("ssh_key");
    expect(credentialKindFor("file:///srv/x")).toBeUndefined();
  });

  it("wraps a key a password box put on one line, as ssh-keygen writes it", () => {
    const openssh = wrapped("OPENSSH PRIVATE KEY", 70);
    expect(normalizeKey(openssh.replaceAll("\n", ""))).toBe(openssh);
    const pem = wrapped("RSA PRIVATE KEY", 64);
    expect(normalizeKey(pem.replaceAll("\n", ""))).toBe(pem);
    // A key with its line breaks is left as it is, minus Windows line ends and outer space.
    expect(normalizeKey(`\n${openssh.replaceAll("\n", "\r\n")}\n`)).toBe(openssh);
  });

  it("refuses what the server would refuse, without repeating the secret", () => {
    const token = (secret: string, username = "") =>
      validateCredential("token", { secret, username });
    expect(token("")).toMatch(/Paste/);
    expect(token("ghp_a b")).toMatch(/one line/);
    expect(token("ghp_abc", "bad user")).toMatch(/user name/);
    expect(token("ghp_abc", "x-token-auth")).toBeUndefined();
    const key = (secret: string) => validateCredential("ssh_key", { secret, username: "" });
    expect(key("")).toMatch(/Paste/);
    expect(key("ssh-ed25519 AAAA public")).toMatch(/isn't a private key/);
    expect(key(wrapped("OPENSSH PRIVATE KEY", 70))).toBeUndefined();
    for (const words of [token("ghp_a b"), key("not-a-key-secret")]) {
      expect(words).not.toMatch(/ghp_a|not-a-key-secret/);
    }
  });

  it("builds the request value, leaving out an empty user name", () => {
    expect(credentialOf("token", { secret: " ghp_abc ", username: "" })).toEqual({
      kind: "token",
      token: "ghp_abc",
    });
    expect(credentialOf("token", { secret: "t", username: "x-token-auth" })).toEqual({
      kind: "token",
      token: "t",
      username: "x-token-auth",
    });
    const key = wrapped("OPENSSH PRIVATE KEY", 70);
    expect(credentialOf("ssh_key", { secret: key.replaceAll("\n", ""), username: "" })).toEqual({
      kind: "ssh_key",
      private_key: key,
    });
    expect(credentialOf("token", { secret: "  ", username: "" })).toBeUndefined();
  });

  it("puts the server's fixed refusal in a sentence", () => {
    expect(
      explainInvalidCredential(
        "not a usable credential: an access token goes with an https:// URL (http:// only for localhost)",
      ),
    ).toBe(
      "The server can't use it: an access token goes with an https:// URL (http:// only for localhost).",
    );
  });
});

/** The start of an OpenSSH key blob naming `cipher`, padded like a real key's body. */
const openssh = (cipher: string) => {
  const size = String.fromCharCode(0, 0, 0, cipher.length);
  const blob = `openssh-key-v1\0${size}${cipher}${String.fromCharCode(0, 0, 0, 4)}none`;
  const body = btoa(blob + "x".repeat(120)).match(/.{1,70}/g) ?? [];
  return ["-----BEGIN OPENSSH PRIVATE KEY-----", ...body, "-----END OPENSSH PRIVATE KEY-----"].join(
    "\n",
  );
};

describe("keys with a passphrase", () => {
  const key = (secret: string) => validateCredential("ssh_key", { secret, username: "" });

  it("reads an OpenSSH key's cipher, wrapped or pasted on one line", () => {
    expect(hasPassphrase(openssh("none"))).toBe(false);
    expect(hasPassphrase(openssh("aes256-ctr"))).toBe(true);
    expect(key(openssh("aes256-ctr").replaceAll("\n", ""))).toBe(PASSPHRASE);
    expect(key(openssh("none").replaceAll("\n", ""))).toBeUndefined();
  });

  it("sees a PEM key's Proc-Type header before anything re-wraps it", () => {
    const pem = [
      "-----BEGIN RSA PRIVATE KEY-----",
      "Proc-Type: 4,ENCRYPTED",
      "DEK-Info: AES-128-CBC,0123456789ABCDEF0123456789ABCDEF",
      "",
      ...(BODY.match(/.{1,64}/g) ?? []),
      "-----END RSA PRIVATE KEY-----",
    ].join("\n");
    expect(key(pem)).toBe(PASSPHRASE);
    // A password box drops the line breaks: still found, and the key is not mangled.
    expect(key(pem.replaceAll("\n", ""))).toBe(PASSPHRASE);
    expect(normalizeKey(pem.replaceAll("\n", ""))).toBe(pem.replaceAll("\n", ""));
    expect(key(wrapped("ENCRYPTED PRIVATE KEY", 64))).toBe(PASSPHRASE);
  });

  it("says so for the server's refusal too", () => {
    expect(
      explainInvalidCredential(
        "not a usable credential: the deploy key has a passphrase: use a key without one",
      ),
    ).toBe(PASSPHRASE);
  });
});

describe("credential words in Polish", () => {
  it("say the checks in Polish and keep the server's reason as sent", () => {
    expect(validateCredential("token", { secret: "", username: "" }, "pl")).toBe(
      "Wklej token dostępu.",
    );
    expect(
      validateCredential("ssh_key", { secret: "ssh-ed25519 AAAA", username: "" }, "pl"),
    ).toMatch(/^To nie jest klucz prywatny/);
    expect(
      explainInvalidCredential("not a usable credential: the key is not a private key", "pl"),
    ).toBe("Serwer nie może go użyć: the key is not a private key.");
    expect(explainInvalidCredential("it has a passphrase", "pl")).toMatch(/chroniony hasłem/);
    expect(refusedCredential("ssh_key", "pl")).toMatch(/^Repozytorium odrzuciło ten klucz/);
    expect(hostKeyChanged("pl")).toMatch(/^Serwer SSH repozytorium/);
    expect(hostKeyChanged("en")).toMatch(/^The repository's SSH server/);
  });
});
