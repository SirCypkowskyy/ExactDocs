import {
  Blocks,
  Boxes,
  Braces,
  Component,
  Layers,
  type LucideIcon,
  Package,
  Puzzle,
  SquareTerminal,
} from "lucide-react";
import { useState } from "react";
import { usePreferences } from "@/shared/lib/preferences";
import { cn } from "@/shared/lib/utils";
import { LibraryBullet, lineIndex } from "./route";

/*
 * A library's mark beside its name (#504): the project's own logo when the importer found one
 * (served by ExactDocs, never fetched from elsewhere), otherwise a generic icon on the library's
 * line colour, picked from its ID so it is the same on every visit. A logo sits on the white
 * `logo-tile` with its hairline in both themes, so a dark logo with a transparent ground stays
 * visible in dark mode. With "Library logos" off in the interface preferences it falls back to the
 * line-coloured monogram bullet. Decorative: the library's name is always next to it.
 */

const ICONS: readonly LucideIcon[] = [
  Package,
  Boxes,
  Blocks,
  Braces,
  Puzzle,
  Layers,
  Component,
  SquareTerminal,
];

const LINE_BG = [
  "bg-line-1",
  "bg-line-2",
  "bg-line-3",
  "bg-line-4",
  "bg-line-5",
  "bg-line-6",
  "bg-line-7",
  "bg-line-8",
] as const;

/** A second stable pick from the ID, so icon and colour do not always travel together. */
function iconIndex(libraryId: string): number {
  let h = 5381;
  for (let i = 0; i < libraryId.length; i++) h = Math.imul(h, 33) ^ libraryId.charCodeAt(i);
  return (h >>> 0) % ICONS.length;
}

const SIZES = {
  sm: "size-6 [&_svg]:size-3.5",
  md: "size-7 [&_svg]:size-4",
  lg: "size-9 [&_svg]:size-5",
  xl: "size-12 [&_svg]:size-6",
} as const;

export function LibraryMark({
  id,
  logo,
  size = "md",
  className,
}: {
  id: string;
  /** The URL of the library's logo on this server, when it has one. */
  logo?: string | null | undefined;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const { prefs } = usePreferences();
  const [broken, setBroken] = useState<string | null>(null);
  if (!prefs.library_logos) {
    return (
      <LibraryBullet id={id} size={size === "xl" ? "lg" : size} {...(className && { className })} />
    );
  }
  const box = cn(
    "inline-flex flex-none items-center justify-center overflow-hidden rounded-md select-none",
    SIZES[size],
    className,
  );
  if (logo && broken !== logo) {
    return (
      <span
        aria-hidden="true"
        className={cn(box, "border border-logo-tile-edge bg-logo-tile p-0.5")}
      >
        <img
          src={logo}
          alt=""
          loading="lazy"
          decoding="async"
          className="size-full object-contain"
          onError={() => setBroken(logo)}
        />
      </span>
    );
  }
  const Icon = ICONS[iconIndex(id)] ?? Package;
  return (
    <span aria-hidden="true" className={cn(box, "text-white", LINE_BG[lineIndex(id)])}>
      <Icon strokeWidth={2} />
    </span>
  );
}
