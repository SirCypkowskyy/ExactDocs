import { useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, Copy, TriangleAlert } from "lucide-react";
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
  isSessionEnded,
  MAX_NAME_LENGTH,
} from "../model/token";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (name: string) => void;
}

export function CreateTokenDialog({ open, onOpenChange, onCreated }: Props) {
  // While a request is in flight or the secret is on screen, Done is the only way out: closing
  // would lose the one copy. A blocked attempt nudges the warning so it never reads as frozen.
  const locked = useRef(false);
  const [nudge, setNudge] = useState(0);
  const block = (event: Event) => {
    if (!locked.current) return;
    event.preventDefault();
    setNudge((n) => n + 1);
  };
  return (
    <DialogRoot
      open={open}
      onOpenChange={(next) => {
        if (!next) locked.current = false;
        onOpenChange(next);
      }}
    >
      <DialogContent onInteractOutside={block} onEscapeKeyDown={block}>
        <Body
          nudge={nudge}
          onLock={(v) => {
            locked.current = v;
          }}
          onCreated={onCreated}
          onClose={() => {
            locked.current = false;
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </DialogRoot>
  );
}

function Body({
  nudge,
  onLock,
  onCreated,
  onClose,
}: {
  nudge: number;
  onLock: (v: boolean) => void;
  onCreated: (name: string) => void;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState<ExpiryChoice>("never");
  const [scope, setScope] = useState("all");
  const [libraries, setLibraries] = useState("");
  const [nameError, setNameError] = useState<string>();
  const [problem, setProblem] = useState<{ message: string; signIn: boolean }>();
  const [pending, setPending] = useState(false);
  const [secret, setSecret] = useState<string>();
  const nameInput = useRef<HTMLInputElement>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    const trimmed = name.trim();
    if (!trimmed) {
      setNameError("Name the token after where it will run, like “laptop”.");
      nameInput.current?.focus();
      return;
    }
    setNameError(undefined);
    setProblem(undefined);
    setPending(true);
    onLock(true);
    try {
      const grant = await createToken(
        trimmed,
        expiresAt(expiry),
        scope === "all" ? undefined : libraries.split(/[\s,]+/).filter(Boolean),
      );
      setSecret(grant.token);
      onCreated(grant.name);
    } catch (error) {
      onLock(false);
      setProblem({ message: explainTokenError(error), signIn: isSessionEnded(error) });
    } finally {
      setPending(false);
      // Refetch either way: a refused create (409) means the cached list is out of date.
      void queryClient.invalidateQueries({ queryKey: tokensKey });
    }
  }

  if (secret) return <Reveal secret={secret} nudge={nudge} onDone={onClose} />;

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
              {problem.message}
              {problem.signIn && (
                <>
                  {" "}
                  <a href="/sign-in" className="underline underline-offset-2">
                    Sign in
                  </a>
                </>
              )}
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
          placeholder="e.g. laptop"
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
        <div className="relative">
          <select
            id="token-expiry"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value as ExpiryChoice)}
            className="h-11 w-full cursor-pointer appearance-none rounded-md border border-input bg-secondary pr-10 pl-3 text-base outline-none transition-[border-color,box-shadow] duration-150 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40"
          >
            {EXPIRY_CHOICES.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
          <ChevronDown
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-muted-foreground"
          />
        </div>
      </div>
      <div className="mt-4 flex flex-col gap-1.5">
        <label htmlFor="token-scope" className="text-sm font-medium">
          Library access
        </label>
        <select
          id="token-scope"
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          className="h-11 rounded-md border border-input bg-secondary px-3"
        >
          <option value="all">All libraries I can access</option>
          <option value="selected">Selected libraries</option>
        </select>
        {scope === "selected" && (
          <>
            <label htmlFor="token-libraries" className="text-sm font-medium">
              Library IDs
            </label>
            <Input
              id="token-libraries"
              value={libraries}
              onChange={(e) => setLibraries(e.target.value)}
              placeholder="/owner/repo, /owner/another"
            />
          </>
        )}
        <p className="text-sm text-muted-foreground">
          Access always follows your current permissions. An empty selection allows no libraries.
        </p>
      </div>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" aria-disabled={pending} onClick={() => !pending && onClose()}>
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

function Reveal({ secret, nudge, onDone }: { secret: string; nudge: number; onDone: () => void }) {
  const [copy, setCopy] = useState<CopyState>("idle");
  const copyButton = useRef<HTMLButtonElement>(null);
  const code = useRef<HTMLElement>(null);
  const warning = useRef<HTMLParagraphElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Focus lands on the action the user needs next; the warning is its accessible description.
  useEffect(() => {
    copyButton.current?.focus();
    return () => clearTimeout(timer.current);
  }, []);

  // A blocked Escape or outside click answers with one short pulse on the warning.
  useEffect(() => {
    if (nudge === 0 || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    warning.current?.animate?.(
      [{ transform: "scale(1)" }, { transform: "scale(1.02)" }, { transform: "scale(1)" }],
      { duration: 160, easing: "cubic-bezier(0.23, 1, 0.32, 1)" },
    );
  }, [nudge]);

  async function run() {
    clearTimeout(timer.current);
    try {
      await navigator.clipboard.writeText(secret);
      setCopy("copied");
      timer.current = setTimeout(() => setCopy("idle"), 2500);
    } catch {
      // No clipboard API (plain-HTTP self-host) or refused: select the token for Ctrl+C.
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
      <DialogDescription asChild>
        <p
          ref={warning}
          id="token-warning"
          className="mt-4 flex gap-2.5 rounded-md bg-accent px-3 py-2.5 text-sm font-medium text-accent-foreground"
        >
          <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>
            This is the only time you will see it. If you lose it, revoke it and create a new one.
          </span>
        </p>
      </DialogDescription>
      <code
        ref={code}
        className="mt-4 block rounded-md border border-input bg-secondary px-4 py-3.5 font-mono text-[15px] leading-6 tracking-[0.02em] break-all text-foreground select-all [font-variant-numeric:slashed-zero]"
      >
        {secret}
      </code>
      <p role="status" className="mt-2 min-h-5 text-sm text-muted-foreground">
        {copy === "idle" && "Click the token to select it."}
        {copy === "copied" && "Copied to the clipboard."}
        {copy === "failed" && "Couldn't copy automatically. The token is selected: press Ctrl+C."}
      </p>
      <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" onClick={onDone}>
          Done
        </Button>
        <Button
          ref={copyButton}
          className="min-w-36"
          aria-describedby="token-warning"
          onClick={run}
        >
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
