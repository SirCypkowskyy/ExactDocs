import { useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Plus, TriangleAlert } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { reducedMotion } from "@/shared/lib/preferences";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { DialogContent, DialogDescription, DialogRoot, DialogTitle } from "@/shared/ui/dialog";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { LibraryCombobox } from "@/shared/ui/library-combobox";
import { codeWell } from "@/shared/ui/recipes";
import { SelectField } from "@/shared/ui/select-field";
import { createToken, scopeLibrariesQueryOptions, tokensKey } from "../api/tokens-query";
import { messages } from "../messages";
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
  const language = useLanguage();
  const t = useMessages(messages).create;
  const c = useMessages(common);
  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState<ExpiryChoice>("never");
  const [scope, setScope] = useState("all");
  const [libraries, setLibraries] = useState<string[]>([]);
  const [nameMissing, setNameMissing] = useState(false);
  // The failure itself, so its words follow the language if it changes meanwhile.
  const [failure, setFailure] = useState<{ error: unknown }>();
  const [pending, setPending] = useState(false);
  const [secret, setSecret] = useState<string>();
  const nameInput = useRef<HTMLInputElement>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    const trimmed = name.trim();
    if (!trimmed) {
      setNameMissing(true);
      nameInput.current?.focus();
      return;
    }
    setNameMissing(false);
    setFailure(undefined);
    setPending(true);
    onLock(true);
    try {
      const grant = await createToken(
        trimmed,
        expiresAt(expiry),
        scope === "all" ? undefined : libraries,
      );
      setSecret(grant.token);
      onCreated(grant.name);
    } catch (error) {
      onLock(false);
      setFailure({ error });
    } finally {
      setPending(false);
      // Refetch either way: a refused create (409) means the cached list is out of date.
      void queryClient.invalidateQueries({ queryKey: tokensKey });
    }
  }

  if (secret) return <Reveal secret={secret} nudge={nudge} onDone={onClose} />;

  return (
    <form onSubmit={submit} noValidate>
      <DialogTitle>{t.title}</DialogTitle>
      <DialogDescription>{t.description(<code>/mcp</code>)}</DialogDescription>
      <div className="mt-5">
        <FormAlert
          id="token-alert"
          message={failure && explainTokenError(failure.error, language)}
          link={
            failure && isSessionEnded(failure.error)
              ? { href: "/sign-in", label: t.signIn }
              : undefined
          }
        />
      </div>
      <div className="mt-5 flex flex-col gap-4">
        <Field
          id="token-name"
          ref={nameInput}
          label={t.name}
          value={name}
          maxLength={MAX_NAME_LENGTH}
          autoComplete="off"
          placeholder={t.namePlaceholder}
          hint={t.nameHint}
          error={nameMissing ? t.nameRequired : undefined}
          onChange={(e) => setName(e.target.value)}
        />
        <SelectField
          id="token-expiry"
          label={t.expires}
          value={expiry}
          onChange={(e) => setExpiry(e.target.value as ExpiryChoice)}
        >
          {EXPIRY_CHOICES.map((choice) => (
            <option key={choice} value={choice}>
              {t.expiry[choice]}
            </option>
          ))}
        </SelectField>
        <SelectField
          id="token-scope"
          label={t.access}
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          hint={t.accessHint}
        >
          <option value="all">{t.allLibraries}</option>
          <option value="selected">{t.selectedLibraries}</option>
        </SelectField>
        {scope === "selected" && (
          <LibraryCombobox
            multiple
            id="token-libraries"
            label={t.libraries}
            query={scopeLibrariesQueryOptions}
            value={libraries}
            onChange={setLibraries}
          />
        )}
      </div>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" aria-disabled={pending} onClick={() => !pending && onClose()}>
          {c.cancel}
        </Button>
        <Button type="submit" pending={pending}>
          {!pending && <Plus aria-hidden="true" data-icon-motion="turn" />}
          {t.submit}
        </Button>
      </div>
    </form>
  );
}

type CopyState = "idle" | "copied" | "failed";

function Reveal({ secret, nudge, onDone }: { secret: string; nudge: number; onDone: () => void }) {
  const t = useMessages(messages).create;
  const c = useMessages(common);
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
    if (nudge === 0 || reducedMotion()) return;
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
      toast.success(t.tokenCopied);
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
      <DialogTitle>{t.revealTitle}</DialogTitle>
      <DialogDescription asChild>
        <p
          ref={warning}
          id="token-warning"
          className="mt-4 flex gap-2.5 rounded-md bg-warning-soft px-3 py-2.5 text-body font-medium text-warning-ink"
        >
          <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>{t.revealWarning}</span>
        </p>
      </DialogDescription>
      <code
        ref={code}
        className={cn(
          codeWell,
          "mt-4 block border border-input px-4 py-3.5 text-small select-all [font-variant-numeric:slashed-zero]",
        )}
      >
        {secret}
      </code>
      <p role="status" className="mt-2 min-h-5 text-body text-muted-foreground">
        {copy === "idle" && t.clickToSelect}
        {copy === "copied" && t.copiedToClipboard}
        {copy === "failed" && t.copyFailed}
      </p>
      <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" onClick={onDone}>
          {c.done}
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
          {copy === "copied" ? c.copied : t.copyToken}
        </Button>
      </div>
    </div>
  );
}
