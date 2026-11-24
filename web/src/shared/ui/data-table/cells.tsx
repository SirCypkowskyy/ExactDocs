import { Link } from "@tanstack/react-router";
import {
  Ban,
  CircleCheck,
  CircleSlash,
  CircleX,
  Clock,
  Copy,
  LoaderCircle,
  type LucideIcon,
  TriangleAlert,
} from "lucide-react";
import type { ReactNode } from "react";
import { formatBytes, formatMoney } from "@/shared/lib/format";
import { formatNumber, useLanguage, useMessages } from "@/shared/lib/i18n";
import { absoluteTimeWithZone, relativeTime } from "@/shared/lib/time";
import { useFlash } from "@/shared/lib/use-flash";
import { useNow } from "@/shared/lib/use-now";
import { cn } from "@/shared/lib/utils";
import { Avatar } from "../avatar";
import { Badge, type BadgeTone } from "../badge";
import { IconButton } from "../button";
import { LibraryMark } from "../library-mark";
import { messages } from "../messages";
import { Meter } from "../meter";
import { Commit, VersionStation } from "../route";
import { Tooltip } from "../tooltip";

/*
 * The cell kit of DataTable v2 (blocks-map §2.2): one way to show each kind of value in a table,
 * so every list reads alike. Literals in mono, figures tabular and aligned at the end, states as
 * pills with an icon, times relative with the exact time one hover (or the accessible name) away.
 */

/**
 * "3 days ago" ("in 12 days" with `future`, for an expiry); the exact time with its zone in the
 * tooltip, the accessible name and `dateTime`.
 */
export function RelativeTime({
  iso,
  empty = "–",
  future = false,
}: {
  iso: string | null | undefined;
  empty?: string;
  /** A time ahead: "in 3 days", "tomorrow". */
  future?: boolean;
}) {
  const now = useNow();
  const language = useLanguage();
  if (!iso) return <span className="text-muted-foreground">{empty}</span>;
  const relative = relativeTime(iso, now, language, { future });
  const exact = absoluteTimeWithZone(iso, language);
  return (
    <Tooltip label={exact}>
      <time dateTime={iso} className="whitespace-nowrap">
        <span aria-hidden="true">{relative}</span>
        <span className="sr-only">
          {relative}, {exact}
        </span>
      </time>
    </Tooltip>
  );
}

/** A version as a station on its line, and the short commit it was pinned to under it. */
export function VersionCell({
  version,
  sha,
  isDefault = false,
  empty,
}: {
  version: string | null | undefined;
  sha?: string | null | undefined;
  isDefault?: boolean;
  /** What a row without a version shows ("all"). */
  empty?: ReactNode;
}) {
  if (!version) return <span className="text-muted-foreground">{empty ?? "–"}</span>;
  return (
    <span className="flex min-w-0 flex-col items-start gap-0.5">
      <VersionStation version={version} isDefault={isDefault} className="max-w-56" />
      {sha && <Commit sha={sha} className="pl-4" />}
    </span>
  );
}

/** A library: its mark, then its title over its mono ID (or the ID alone), linking to its page. */
export function LibraryCell({
  id,
  title,
  logo,
  size = "sm",
  link = true,
}: {
  id: string;
  title?: string | null | undefined;
  logo?: string | null | undefined;
  size?: "sm" | "md";
  link?: boolean;
}) {
  const [, owner = "", repo = ""] = id.split("/");
  const name = title ? (
    <span className="flex min-w-0 flex-col">
      <span className="truncate font-medium">{title}</span>
      <span className="truncate font-mono text-small text-muted-foreground">{id}</span>
    </span>
  ) : (
    <span className="truncate font-mono text-mono">{id}</span>
  );
  return (
    <span className="flex min-w-0 items-center gap-2">
      <LibraryMark id={id} logo={logo} size={size} />
      {link && owner && repo ? (
        <Link
          to="/libraries/$owner/$repo"
          params={{ owner, repo }}
          className="min-w-0 rounded underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
        >
          {name}
        </Link>
      ) : (
        name
      )}
    </span>
  );
}

/** A person: the initials disc and the username. */
export function Person({ name, children }: { name: string; children?: ReactNode }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <Avatar name={name} />
      <span className="truncate">{name}</span>
      {children}
    </span>
  );
}

type StateLook = { tone: BadgeTone; icon: LucideIcon; spin?: boolean };

/** Job and sync states as pill tones and icons (the icon spins while running). */
export const STATE_LOOKS: Readonly<Record<string, StateLook>> = {
  queued: { tone: "neutral", icon: Clock },
  running: { tone: "route", icon: LoaderCircle, spin: true },
  succeeded: { tone: "positive", icon: CircleCheck },
  failed: { tone: "destructive", icon: CircleX },
  cancelled: { tone: "neutral", icon: Ban },
  skipped: { tone: "neutral", icon: CircleSlash },
  warning: { tone: "warning", icon: TriangleAlert },
};

/** A state as a pill: its tone and icon from `STATE_LOOKS`, its name from the caller. */
export function StateBadge({ state, label }: { state: string; label: ReactNode }) {
  const look = STATE_LOOKS[state] ?? { tone: "neutral" as const, icon: Clock };
  const Icon = look.icon;
  return (
    <Badge tone={look.tone}>
      <Icon aria-hidden="true" className={cn("size-3", look.spin && "spin")} />
      {label}
    </Badge>
  );
}

/**
 * How far a job got: a Meter and "1,204 / 2,000 files". With no total yet the fill travels the
 * track. `label` names what progresses ("Progress of the import of v1.4.0").
 */
export function Progress({
  done,
  total,
  unit,
  label,
  meter = true,
}: {
  done: number;
  total: number;
  unit: "files" | "chunks" | "versions" | "steps";
  label: string;
  /** Leave out the bar (a finished job): the count alone. */
  meter?: boolean;
}) {
  const t = useMessages(messages).dataTable;
  return (
    <span className="flex min-w-28 flex-col gap-1">
      {meter && (
        <Meter
          value={total > 0 ? Math.round((done / total) * 100) : null}
          label={label}
          className="max-w-40"
        />
      )}
      {total > 0 ? (
        <span className="num text-small text-muted-foreground">
          {t.progress(done, total, unit)}
        </span>
      ) : (
        !meter && <span className="text-muted-foreground">–</span>
      )}
    </span>
  );
}

/** A size in bytes: "12.4 kB". */
export function Bytes({ value }: { value: number }) {
  return <span className="num whitespace-nowrap">{formatBytes(value, useLanguage())}</span>;
}

/** A count: "1,204" ("1204" in Polish, which groups from 10 000). */
export function Count({ value, muted = false }: { value: number; muted?: boolean }) {
  return (
    <span className={cn("num", muted && "text-muted-foreground")}>
      {formatNumber(value, useLanguage())}
    </span>
  );
}

/** US dollars: "$3.10". */
export function Money({ usd }: { usd: number }) {
  return <span className="num whitespace-nowrap">{formatMoney(usd, useLanguage())}</span>;
}

/**
 * A literal to copy (an ID, a token prefix): mono text and a copy button whose icon turns into a
 * check for a moment; a status line says it was copied.
 */
export function MonoCopy({
  value,
  display,
  what,
}: {
  value: string;
  /** What to show when it differs from what is copied (a shortened ID). */
  display?: string;
  /** What it is, for the button's name: "job ID". */
  what: string;
}) {
  const t = useMessages(messages).dataTable;
  const [done, flash] = useFlash();
  return (
    <span className="inline-flex min-w-0 items-center gap-0.5">
      <span className="truncate font-mono text-mono">{display ?? value}</span>
      <IconButton
        label={t.copy(what)}
        size="icon-sm"
        done={done}
        className="-my-2 text-muted-foreground"
        onClick={() => {
          void navigator.clipboard?.writeText(value).then(flash, () => {});
        }}
      >
        <Copy aria-hidden="true" data-icon-motion="pop" />
      </IconButton>
      <span role="status" className="sr-only">
        {done ? t.copied(what) : ""}
      </span>
    </span>
  );
}
