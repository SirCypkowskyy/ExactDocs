import { Avatar as A } from "radix-ui";
import { cn } from "@/shared/lib/utils";

/*
 * Avatar (shadcn/ui on Radix, MIT), initials only: ExactDocs keeps no pictures of people. A full
 * round disc on `secondary` with the person's initials in ink (12 px / 600), 24 or 32 px.
 * Decorative: the username is always written next to it.
 */

/** Two letters for a username: "alice.smith" → "AS", "bob" → "BO", "jan-kowalski@sso" → "JK". */
export function initials(name: string): string {
  const words = name
    .replace(/@.*$/, "")
    .split(/[\s._-]+/)
    .filter(Boolean);
  const [first = "", second = ""] = words;
  const letters = second ? `${first[0] ?? ""}${second[0] ?? ""}` : first.slice(0, 2);
  return (letters || "?").toUpperCase();
}

const SIZES = {
  md: "size-6 text-small",
  lg: "size-8 text-small",
} as const;

export function Avatar({
  name,
  size = "md",
  className,
}: {
  name: string;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  return (
    <A.Root
      data-slot="avatar"
      aria-hidden="true"
      className={cn(
        "relative inline-flex flex-none overflow-hidden rounded-full select-none",
        SIZES[size],
        className,
      )}
    >
      <A.Fallback
        data-slot="avatar-fallback"
        className="flex size-full items-center justify-center rounded-full bg-secondary leading-none font-semibold text-secondary-foreground"
      >
        {initials(name)}
      </A.Fallback>
    </A.Root>
  );
}
