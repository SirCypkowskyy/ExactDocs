import { KeyRound } from "lucide-react";
import { type ChangeEvent, useEffect, useRef, useState } from "react";
import type { CredentialDraft, CredentialKind } from "@/shared/lib/credentials";
import { Button } from "./button";
import { Field } from "./field";

/** A deploy key file is a few kilobytes; anything far bigger is not one. */
const MAX_KEY_FILE = 32 * 1024;

interface Props {
  /** The secret's input id; the user name box and the file picker derive theirs from it. */
  id: string;
  kind: CredentialKind;
  draft: CredentialDraft;
  error?: string | undefined;
  /** Replaces the default hint (what happens to the secret). */
  hint?: string | undefined;
  onChange: (draft: CredentialDraft) => void;
  /** Focus left the secret: a caller that lists refs with it can do so now, not per keystroke. */
  onCommit?: (() => void) | undefined;
}

/**
 * The token or deploy key of a private repository. A password input, so the secret is never
 * shown, and nothing a browser or password manager should keep: it lives in the caller's state
 * only and goes out in a request body.
 */
export function CredentialField({ id, kind, draft, error, hint, onChange, onCommit }: Props) {
  const file = useRef<HTMLInputElement>(null);
  // Uncontrolled: React would mirror a controlled value into the `value` attribute, where CSS
  // selectors and DOM snapshots could read the secret. Only the property ever holds it.
  const secret = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const input = secret.current;
    if (input && input.value !== draft.secret) input.value = draft.secret;
  }, [draft.secret]);
  const [loaded, setLoaded] = useState<string>();
  const [fileError, setFileError] = useState<string>();
  const token = kind === "token";

  async function read(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0];
    // The input keeps no copy: the same file can be chosen again, and nothing lingers in the DOM.
    event.target.value = "";
    if (!chosen) return;
    if (chosen.size > MAX_KEY_FILE) {
      setLoaded(undefined);
      setFileError("That file is too big to be a deploy key.");
      return;
    }
    setFileError(undefined);
    onChange({ ...draft, secret: await chosen.text() });
    setLoaded(chosen.name);
    onCommit?.();
  }

  return (
    <div className="flex flex-col gap-4">
      <Field
        id={id}
        label={token ? "Access token" : "Deploy key"}
        type="password"
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        data-1p-ignore
        data-lpignore="true"
        data-bwignore
        placeholder={token ? "Paste the token" : "Paste the private key"}
        ref={secret}
        error={error ?? fileError}
        hint={
          hint ??
          (token
            ? "A token that can read this repository. It is stored encrypted and never shown again."
            : "The private half of a deploy key without a passphrase. Paste it or choose its file. It is stored encrypted and never shown again.")
        }
        className="font-mono"
        onChange={(e) => {
          setLoaded(undefined);
          onChange({ ...draft, secret: e.target.value });
        }}
        onBlur={() => onCommit?.()}
      />
      {token ? (
        <Field
          id={`${id}-user`}
          label="User name (optional)"
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          placeholder="x-access-token"
          value={draft.username}
          hint="Leave it empty for GitHub and GitLab. Bitbucket repository tokens use x-token-auth."
          className="font-mono"
          onChange={(e) => onChange({ ...draft, username: e.target.value })}
        />
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={file}
            id={`${id}-file`}
            type="file"
            className="sr-only"
            tabIndex={-1}
            aria-hidden="true"
            onChange={(e) => void read(e)}
          />
          <Button
            variant="outline"
            aria-describedby={`${id}-file-status`}
            onClick={() => file.current?.click()}
          >
            <KeyRound aria-hidden="true" className="size-4" />
            Choose key file
          </Button>
          <p id={`${id}-file-status`} role="status" className="text-body text-muted-foreground">
            {loaded && `Key read from ${loaded}.`}
          </p>
        </div>
      )}
    </div>
  );
}
