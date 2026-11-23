import { Trash2 } from "lucide-react";
import { type FormEvent, type ReactNode, type Ref, useId, useRef, useState } from "react";
import { common, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
} from "./alert-dialog";
import { Button } from "./button";
import { FormAlert } from "./form-alert";
import { messages } from "./messages";
import { control, controlHeight } from "./recipes";

/*
 * Confirmations (DESIGN.md, "Confirm with AlertDialog"). The typed confirmation follows the
 * validation pattern of the basic shadcnblocks Alert Dialog Form 5 (`alert-dialog-form-5`; own
 * code): the confirm stays on screen but inert until the text matches, so the next step is visible.
 *
 * Both are AlertDialogs: `role="alertdialog"`, Cancel focused first, Escape cancels, a click
 * outside does nothing. The confirm runs `onConfirm` and the dialog stays open until the caller
 * closes it (on success), so a refusal is shown inside it; while `pending` it cannot be closed
 * (the answer would land on a page that moved on) and Cancel keeps focus with `aria-disabled`.
 */

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** A question: "Cancel this job?", "Remove v1.4.0?". */
  title: ReactNode;
  /** What happens, in one or two sentences. */
  description?: ReactNode;
  /** More body under the description (what is lost, what is kept). */
  children?: ReactNode;
  /** The verb that does it: "Cancel job", "Remove". */
  confirmLabel: string;
  /** The confirm's label while the request runs (the label stays otherwise, with a spinner). */
  pendingLabel?: string | undefined;
  /** "Cancel" unless the action is itself a cancel ("Keep it"). */
  cancelLabel?: string | undefined;
  /** `destructive` (the default) fills the confirm red; `default` makes it the primary button. */
  tone?: "destructive" | "default";
  /**
   * The confirm's leading icon (`aria-hidden`). A destructive confirm has Trash2 with the `warn`
   * reaction unless another fits better (Ban for a cancel); `null` for none.
   */
  icon?: ReactNode;
  pending?: boolean;
  /** Why it did not work, announced inside the dialog; `info` for a wait, not a mistake. */
  error?: string | undefined;
  errorTone?: "error" | "info" | undefined;
  onConfirm: () => void;
  /**
   * Where focus goes when it closes; call `preventDefault` and focus something yourself. By
   * default it goes back to what had focus when it opened.
   */
  onCloseAutoFocus?: ((event: Event) => void) | undefined;
}

type Shell = Omit<ConfirmDialogProps, "description" | "children" | "onConfirm"> & {
  body: ReactNode;
  armed: boolean;
  onSubmit: () => void;
  initialFocus?: () => HTMLElement | null | undefined;
};

function ConfirmShell({
  open,
  onOpenChange,
  title,
  body,
  confirmLabel,
  pendingLabel,
  cancelLabel,
  tone = "destructive",
  icon,
  pending = false,
  error,
  errorTone,
  armed,
  onSubmit,
  onCloseAutoFocus,
  initialFocus,
}: Shell) {
  const c = useMessages(common);
  const alertId = useId();
  const blocked = !armed || pending;
  // What had focus when it opened (the button or menu that asked): focus goes back there when it
  // closes, unless the caller sends it elsewhere. Radix only knows its own Trigger, and a
  // confirmation is usually opened from state, so without this focus would fall to the page.
  const opener = useRef<HTMLElement | null>(null);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!blocked) onSubmit();
  }
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && pending) return;
        onOpenChange(next);
      }}
    >
      <AlertDialogContent
        // Anchored near the top: an error arriving below must not re-centre (move) the panel.
        className="sm:top-[22vh] sm:translate-y-0"
        {...(!body && { "aria-describedby": undefined })}
        onCloseAutoFocus={(event) => {
          onCloseAutoFocus?.(event);
          if (!event.defaultPrevented && opener.current?.isConnected) {
            event.preventDefault();
            opener.current.focus();
          }
        }}
        onOpenAutoFocus={(event) => {
          opener.current =
            document.activeElement instanceof HTMLElement ? document.activeElement : null;
          const target = initialFocus?.();
          if (target) {
            event.preventDefault();
            target.focus();
          }
        }}
      >
        <form onSubmit={submit} noValidate>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {body}
          <div className="mt-4">
            <FormAlert id={alertId} message={error} tone={errorTone} />
          </div>
          <AlertDialogFooter className="mt-2">
            <AlertDialogCancel aria-disabled={pending || undefined}>
              {cancelLabel ?? c.cancel}
            </AlertDialogCancel>
            <Button
              type="submit"
              variant={tone === "destructive" ? "destructive-solid" : "default"}
              pending={pending}
              aria-disabled={blocked || undefined}
              className={cn(
                "min-w-32",
                // Not armed yet (typed confirmation): a neutral, readable button that is clearly
                // not ready. The colour arrives with the matching text.
                !armed &&
                  "aria-disabled:cursor-not-allowed aria-disabled:bg-secondary aria-disabled:text-muted-foreground aria-disabled:ring-1 aria-disabled:ring-border aria-disabled:ring-inset aria-disabled:hover:bg-secondary",
              )}
            >
              {!pending &&
                (icon === undefined && tone === "destructive" ? (
                  <Trash2 aria-hidden="true" data-icon-motion="warn" />
                ) : (
                  icon
                ))}
              {pending && pendingLabel ? pendingLabel : confirmLabel}
            </Button>
          </AlertDialogFooter>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/** A yes-or-no confirmation: the title asks, the description says what happens, the confirm does it. */
export function ConfirmDialog({ description, children, onConfirm, ...props }: ConfirmDialogProps) {
  return (
    <ConfirmShell
      {...props}
      armed
      onSubmit={onConfirm}
      body={
        (description || children) && (
          <AlertDialogDescription asChild>
            <div>
              {description && <p>{description}</p>}
              {children}
            </div>
          </AlertDialogDescription>
        )
      }
    />
  );
}

interface TypedConfirmDialogProps extends ConfirmDialogProps {
  /** The exact text to type (the version, the library ID). */
  phrase: string;
  /** The field's label; "Type <phrase> to confirm" by default, with the phrase in mono. */
  phraseLabel?: ReactNode;
  /**
   * What takes focus when it opens: Cancel (the default, the safe choice) or the field, when
   * typing is plainly the next step and Cancel stays one Shift+Tab away.
   */
  initialFocus?: "cancel" | "phrase";
}

function PhraseField({
  id,
  inputRef,
  phrase,
  label,
  value,
  onChange,
  readOnly,
}: {
  id: string;
  inputRef: Ref<HTMLInputElement>;
  phrase: string;
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  readOnly: boolean;
}) {
  const t = useMessages(messages).confirm;
  return (
    <div className="mt-5 flex flex-col gap-1.5">
      <label htmlFor={id} className="text-body font-medium">
        {label ?? t.typeToConfirm(<span className="font-mono">{phrase}</span>)}
      </label>
      <input
        ref={inputRef}
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        readOnly={readOnly}
        className={cn(control, controlHeight, "px-3 font-mono")}
      />
    </div>
  );
}

/**
 * A removal behind a typed phrase (a library, a version): the confirm stays inert until the
 * field holds exactly `phrase`. Enter in the field confirms once it matches.
 */
export function TypedConfirmDialog({
  description,
  children,
  onConfirm,
  phrase,
  phraseLabel,
  initialFocus = "cancel",
  ...props
}: TypedConfirmDialogProps) {
  const id = useId();
  const field = useRef<HTMLInputElement>(null);
  const [typed, setTyped] = useState("");
  const [wasOpen, setWasOpen] = useState(props.open);
  // A new opening starts with an empty field.
  if (wasOpen !== props.open) {
    setWasOpen(props.open);
    if (props.open) setTyped("");
  }
  return (
    <ConfirmShell
      {...props}
      armed={typed === phrase}
      onSubmit={onConfirm}
      {...(initialFocus === "phrase" && { initialFocus: () => field.current })}
      body={
        <>
          {(description || children) && (
            <AlertDialogDescription asChild>
              <div>
                {description && <p>{description}</p>}
                {children}
              </div>
            </AlertDialogDescription>
          )}
          <PhraseField
            id={id}
            inputRef={field}
            phrase={phrase}
            label={phraseLabel}
            value={typed}
            onChange={setTyped}
            readOnly={props.pending ?? false}
          />
        </>
      }
    />
  );
}
