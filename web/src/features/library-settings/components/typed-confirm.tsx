import { type FormEvent, type ReactNode, useRef, useState } from "react";
import { common, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import {
  ConfirmCancel,
  ConfirmContent,
  ConfirmDescription,
  ConfirmRoot,
  ConfirmTitle,
} from "@/shared/ui/dialog";
import { FormAlert } from "@/shared/ui/form-alert";
import { control, controlHeight } from "@/shared/ui/recipes";
import { pageMessages } from "../messages/page";
import type { Problem } from "../model/settings";

interface TypedConfirmProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** “Remove ”, the thing, “?”: the thing is set in mono by the caller. */
  title: ReactNode;
  /** What is lost, in the full ink. */
  loss: ReactNode;
  /** What is safe, in the muted ink. */
  safe: ReactNode;
  /** The exact text the person has to type (the version, or the library ID). */
  phrase: string;
  confirmLabel: string;
  pending: boolean;
  problem: Problem | undefined;
  onConfirm: () => void;
  /** Where focus goes when the dialog closes: back to the button that opened it, or elsewhere. */
  onCloseAutoFocus: (event: Event) => void;
}

type BodyProps = Pick<
  TypedConfirmProps,
  "loss" | "safe" | "phrase" | "confirmLabel" | "pending" | "problem" | "onConfirm"
>;

function Body({ loss, safe, phrase, confirmLabel, pending, problem, onConfirm }: BodyProps) {
  const t = useMessages(pageMessages).confirm;
  const { cancel } = useMessages(common);
  const [typed, setTyped] = useState("");
  const armed = typed === phrase;
  const blocked = !armed || pending;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!blocked) onConfirm();
  }

  return (
    <form onSubmit={submit} noValidate>
      <ConfirmDescription asChild>
        <div>
          <p className="text-foreground">{loss}</p>
          <p className="mt-1.5">{safe}</p>
        </div>
      </ConfirmDescription>
      <div className="mt-5 flex flex-col gap-1.5">
        <label htmlFor="confirm-phrase" className="text-body font-medium">
          {t.typeToConfirm(<span className="font-mono">{phrase}</span>)}
        </label>
        <input
          id="confirm-phrase"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          readOnly={pending}
          className={cn(control, controlHeight, "px-3 font-mono")}
        />
      </div>
      <div className="mt-4">
        <FormAlert id="confirm-alert" message={problem?.message} tone={problem?.tone} />
      </div>
      <div className="mt-2 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <ConfirmCancel asChild>
          <Button variant="ghost" aria-disabled={pending}>
            {cancel}
          </Button>
        </ConfirmCancel>
        <Button
          type="submit"
          aria-disabled={blocked}
          aria-busy={pending}
          className={cn(
            "min-w-32 bg-destructive text-primary-foreground hover:bg-destructive/90",
            // Not armed yet: a neutral, readable button. The red arrives with the matching text.
            "aria-disabled:bg-secondary aria-disabled:text-muted-foreground aria-disabled:ring-1 aria-disabled:ring-inset aria-disabled:ring-border aria-disabled:hover:bg-secondary",
            pending ? "aria-disabled:cursor-progress" : "aria-disabled:cursor-not-allowed",
            // Waiting on the server: keep the red, it was armed.
            pending &&
              armed &&
              "aria-disabled:bg-destructive aria-disabled:text-primary-foreground aria-disabled:ring-0",
          )}
        >
          {pending ? t.removing : confirmLabel}
        </Button>
      </div>
    </form>
  );
}

/**
 * Removal behind a typed phrase. The button stays on screen but inert until the text matches, so
 * the next step is visible; `aria-disabled` keeps focus where it is while the request runs, and
 * the dialog cannot be closed while it does (the answer would land on a page that moved on).
 */
export function TypedConfirm({
  open,
  onOpenChange,
  title,
  onCloseAutoFocus,
  ...body
}: TypedConfirmProps) {
  const content = useRef<HTMLDivElement>(null);
  return (
    <ConfirmRoot
      open={open}
      onOpenChange={(next) => {
        if (!next && body.pending) return;
        onOpenChange(next);
      }}
    >
      <ConfirmContent
        ref={content}
        // Anchored near the top: an error arriving below must not re-centre (move) the panel.
        className="sm:top-[22vh] sm:translate-y-0"
        onCloseAutoFocus={onCloseAutoFocus}
        onOpenAutoFocus={(event) => {
          // The field is the next thing to do; Cancel stays one Shift+Tab away.
          event.preventDefault();
          content.current?.querySelector<HTMLElement>("#confirm-phrase")?.focus();
        }}
      >
        <ConfirmTitle className="[overflow-wrap:anywhere]">{title}</ConfirmTitle>
        <Body {...body} />
      </ConfirmContent>
    </ConfirmRoot>
  );
}
