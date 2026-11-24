import { Eye, EyeOff, KeyRound } from "lucide-react";
import type { ComponentProps } from "react";
import { IconButton } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";

interface PasswordInputProps extends Omit<ComponentProps<"input">, "id" | "type" | "autoComplete"> {
  id: string;
  label: string;
  autoComplete: "current-password" | "new-password";
  /** The toggle's names: what it does while the password is hidden, and while it is shown. */
  showLabel: string;
  hideLabel: string;
  hint?: string | undefined;
  error?: string | undefined;
  /** Shown is the caller's state, so the form can hide every password again after a change. */
  shown: boolean;
  onShownChange: (shown: boolean) => void;
}

/**
 * A labelled password box (the shape of `Field`): a KeyRound before the text, a show/hide toggle
 * at its end. The toggle is an IconButton whose name and tooltip say what pressing it does next;
 * it sits after the input in the tab order. Uncontrolled: the secret lives only in the input's
 * value property, never in React state or a DOM attribute.
 */
export function PasswordInput({
  id,
  label,
  showLabel,
  hideLabel,
  hint,
  error,
  shown,
  onShownChange,
  ...props
}: PasswordInputProps) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean).join(" ");
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-body font-medium">
        {label}
      </label>
      <div className="relative">
        <KeyRound
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          id={id}
          name={id}
          type={shown ? "text" : "password"}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy || undefined}
          className="pr-12 pl-9 fine:pr-10"
          {...props}
        />
        <div className="absolute inset-y-0 right-0 flex items-center">
          <IconButton
            label={shown ? hideLabel : showLabel}
            motion="pop"
            className="rounded-l-none"
            onClick={() => onShownChange(!shown)}
          >
            {shown ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
          </IconButton>
        </div>
      </div>
      {hint && (
        <p id={`${id}-hint`} className="text-small text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="fade-in text-small font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
