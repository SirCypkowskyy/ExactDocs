import { type FormEvent, type ReactNode, useRef, useState } from "react";
import { Button } from "@/shared/ui/button";
import {
  ConfirmCancel,
  ConfirmContent,
  ConfirmDescription,
  ConfirmRoot,
  ConfirmTitle,
} from "@/shared/ui/dialog";
import type { Problem } from "../model/settings";

interface TypedConfirmProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** What is removed, and what stays. */
  consequence: ReactNode;
  /** The exact text the person has to type (the version, or the library ID). */
  phrase: string;
  confirmLabel: string;
  pending: boolean;
  problem: Problem | undefined;
  onConfirm: () => void;
  /** Where focus goes when the dialog closes: back to the button that opened it, or elsewhere. */
  onCloseAutoFocus: (event: Event) => void;
}

function Body({
  consequence,
  phrase,
  confirmLabel,
  pending,
  problem,
  onConfirm,
}: Omit<TypedConfirmProps, "open" | "onOpenChange" | "title" | "onCloseAutoFocus">) {
  const [typed, setTyped] = useState("");
  const matches = typed === phrase;
  const blocked = !matches || pending;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!blocked) onConfirm();
  }

  return (
    <form onSubmit={submit} noValidate>
      <ConfirmDescription>{consequence}</ConfirmDescription>
      <div className="mt-5 flex flex-col gap-1.5">
        <label htmlFor="confirm-phrase" className="text-sm font-medium">
          Type <span className="font-mono">{phrase}</span> to confirm
        </label>
        <input
          id="confirm-phrase"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          className="h-11 w-full rounded-md border border-input bg-secondary px-3 font-mono text-[15px] outline-none transition-[border-color,box-shadow] duration-150 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40"
        />
      </div>
      <p
        role="alert"
        className="mt-4 rounded-md bg-destructive/10 px-3 py-2.5 text-sm font-medium text-destructive empty:hidden"
      >
        {problem?.message}
      </p>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <ConfirmCancel asChild>
          <Button variant="ghost">Cancel</Button>
        </ConfirmCancel>
        <Button
          type="submit"
          aria-disabled={blocked}
          aria-busy={pending}
          className="min-w-32 bg-destructive text-primary-foreground hover:bg-destructive/90 aria-disabled:bg-destructive/40 aria-disabled:hover:bg-destructive/40"
        >
          {pending ? "Removing" : confirmLabel}
        </Button>
      </div>
    </form>
  );
}

/**
 * Removal behind a typed phrase. The button stays on screen but inert until the text matches, so
 * the next step is visible; `aria-disabled` keeps focus where it is while the request runs.
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
    <ConfirmRoot open={open} onOpenChange={onOpenChange}>
      <ConfirmContent
        ref={content}
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
