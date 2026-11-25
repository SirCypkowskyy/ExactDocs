import { KeyRound } from "lucide-react";
import { type ChangeEvent, useEffect, useRef, useState } from "react";
import type { CredentialDraft, CredentialKind } from "@/shared/lib/credentials";
import { useMessages } from "@/shared/lib/i18n";
import { Button } from "./button";
import { Field } from "./field";
import { messages } from "./messages";

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
  const t = useMessages(messages).credential;
  const file = useRef<HTMLInputElement>(null);
  // Uncontrolled: React would mirror a controlled value into the `value` attribute, where CSS
  // selectors and DOM snapshots could read the secret. Only the property ever holds it.
  const secret = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const input = secret.current;
    if (input && input.value !== draft.secret) input.value = draft.secret;
  }, [draft.secret]);
  const [loaded, setLoaded] = useState<string>();
  const [fileTooBig, setFileTooBig] = useState(false);
  const token = kind === "token";

  async function read(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0];
    // The input keeps no copy: the same file can be chosen again, and nothing lingers in the DOM.
    event.target.value = "";
    if (!chosen) return;
    if (chosen.size > MAX_KEY_FILE) {
      setLoaded(undefined);
      setFileTooBig(true);
      return;
    }
    setFileTooBig(false);
    onChange({ ...draft, secret: await chosen.text() });
    setLoaded(chosen.name);
    onCommit?.();
  }

  return (
    <div className="flex flex-col gap-4">
      <Field
        id={id}
        label={token ? t.token : t.key}
        type="password"
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        data-1p-ignore
        data-lpignore="true"
        data-bwignore
        placeholder={token ? t.pasteToken : t.pasteKey}
        ref={secret}
        error={error ?? (fileTooBig ? t.fileTooBig : undefined)}
        hint={hint ?? (token ? t.tokenHint : t.keyHint)}
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
          label={t.username}
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          placeholder="x-access-token"
          value={draft.username}
          hint={t.usernameHint}
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
            {t.chooseFile}
          </Button>
          <p id={`${id}-file-status`} role="status" className="text-body text-muted-foreground">
            {loaded && t.keyRead(loaded)}
          </p>
        </div>
      )}
    </div>
  );
}
