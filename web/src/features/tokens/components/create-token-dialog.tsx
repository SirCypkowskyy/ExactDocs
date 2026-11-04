import { useQueryClient } from "@tanstack/react-query";
import { Check, Copy, TriangleAlert } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Button } from "@/shared/ui/button";
import { DialogContent, DialogDescription, DialogRoot, DialogTitle } from "@/shared/ui/dialog";
import { Input } from "@/shared/ui/input";
import { createToken, tokensKey } from "../api/tokens-query";
import {
  EXPIRY_CHOICES,
  type ExpiryChoice,
  expiresAt,
  explainTokenError,
  MAX_NAME_LENGTH,
} from "../model/token";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (name: string) => void;
}

export function CreateTokenDialog({ open, onOpenChange, onCreated }: Props) {
  // The secret lives in <Body> state, and <DialogContent> unmounts it when the dialog closes.
  const revealed = useRef(false);
  return (
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogContent
        // Clicking outside must not throw the only copy of the secret away.
        onInteractOutside={(e) => revealed.current && e.preventDefault()}
      >
        <Body
          onRevealed={(v) => {
            revealed.current = v;
          }}
          onCreated={onCreated}
          onClose={() => {
            revealed.current = false;
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </DialogRoot>
  );
}

function Body({
  onRevealed,
  onCreated,
  onClose,
}: {
  onRevealed: (v: boolean) => void;
  onCreated: (name: string) => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState<ExpiryChoice>("never");
  const [nameError, setNameError] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const [pending, setPending] = useState(false);
  const [secret, setSecret] = useState<string>();
  const nameInput = useRef<HTMLInputElement>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    const trimmed = name.trim();
    if (!trimmed) {
      setNameError("Give the token a name, such as the machine or agent that will use it.");
      nameInput.current?.focus();
      return;
    }
    setNameError(undefined);
    setProblem(undefined);
    setPending(true);
    try {
      const grant = await createToken(trimmed, expiresAt(expiry));
      setSecret(grant.token);
      onRevealed(true);
      onCreated(grant.name);
      await queryClient.invalidateQueries({ queryKey: tokensKey });
    } catch (error) {
      setProblem(explainTokenError(error));
    } finally {
      setPending(false);
    }
  }

  if (secret) return <Reveal secret={secret} onDone={onClose} />;

  return (
    <form onSubmit={submit} noValidate>
      <DialogTitle>New API token</DialogTitle>
      <DialogDescription>
        Tokens let an agent read your documentation over <code>/mcp</code>.
      </DialogDescription>
      <div
        role="alert"
        className={`grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none ${problem ? "mt-4 grid-rows-[1fr]" : "grid-rows-[0fr]"}`}
      >
        <div className="overflow-hidden">
          {problem && (
            <p className="rounded-md bg-destructive/10 px-3 py-2.5 text-sm font-medium text-destructive">
              {problem}
            </p>
          )}
        </div>
      </div>
      <div className="mt-5 flex flex-col gap-1.5">
        <label htmlFor="token-name" className="text-sm font-medium">
          Name
        </label>
        <Input
          ref={nameInput}
          id="token-name"
          value={name}
          maxLength={MAX_NAME_LENGTH}
          autoComplete="off"
          placeholder="laptop"
          aria-invalid={nameError ? true : undefined}
          aria-describedby={nameError ? "token-name-error" : "token-name-hint"}
          onChange={(e) => setName(e.target.value)}
        />
        {nameError ? (
          <p id="token-name-error" className="fade-in text-sm font-medium text-destructive">
            {nameError}
          </p>
        ) : (
          <p id="token-name-hint" className="text-sm text-muted-foreground">
            Only for you: it tells your tokens apart.
          </p>
        )}
      </div>
      <div className="mt-4 flex flex-col gap-1.5">
        <label htmlFor="token-expiry" className="text-sm font-medium">
          Expires
        </label>
        <select
          id="token-expiry"
          value={expiry}
          onChange={(e) => setExpiry(e.target.value as ExpiryChoice)}
          className="h-11 w-full cursor-pointer rounded-md border border-input bg-secondary px-3 text-base outline-none transition-[border-color,box-shadow] duration-150 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40"
        >
          {EXPIRY_CHOICES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </div>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" aria-disabled={pending} aria-busy={pending}>
          {pending ? "Creating" : "Create token"}
        </Button>
      </div>
    </form>
  );
}

type CopyState = "idle" | "copied" | "failed";

function Reveal({ secret, onDone }: { secret: string; onDone: () => void }) {
  const [copy, setCopy] = useState<CopyState>("idle");
  const copyButton = useRef<HTMLButtonElement>(null);
  const code = useRef<HTMLElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Focus lands on the action the user needs next; the title and warning are read first.
  useEffect(() => {
    copyButton.current?.focus();
    return () => clearTimeout(timer.current);
  }, []);

  async function run() {
    clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(secret);
      setCopy("copied");
      timer.current = setTimeout(() => setCopy("idle"), 2500);
    } catch {
      setCopy("failed");
      const range = document.createRange();
      if (code.current) range.selectNodeContents(code.current);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
    }
  }

  return (
    <div className="fade-in">
      <DialogTitle>Copy your token now</DialogTitle>
      <DialogDescription>Paste it into your agent's configuration.</DialogDescription>
      <p className="mt-4 flex gap-2.5 rounded-md bg-accent px-3 py-2.5 text-sm font-medium text-accent-foreground">
        <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <span>
          This is the only time it is shown. ExactDocs keeps a hash, so it can't be shown again; if
          you lose it, revoke it and create a new one.
        </span>
      </p>
      <code
        ref={code}
        className="mt-4 block rounded-md border border-input bg-secondary px-3 py-3 font-mono text-sm break-all select-all"
      >
        {secret}
      </code>
      <p role="status" className="mt-2 min-h-5 text-sm text-muted-foreground">
        {copy === "copied" && "Copied to the clipboard."}
        {copy === "failed" && "Couldn't copy automatically. The token is selected: press Ctrl+C."}
      </p>
      <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" onClick={onDone}>
          Done
        </Button>
        <Button ref={copyButton} onClick={run}>
          {copy === "copied" ? (
            <Check aria-hidden="true" className="size-4" />
          ) : (
            <Copy aria-hidden="true" className="size-4" />
          )}
          {copy === "copied" ? "Copied" : "Copy token"}
        </Button>
      </div>
    </div>
  );
}
