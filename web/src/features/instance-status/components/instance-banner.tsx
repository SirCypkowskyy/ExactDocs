import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, Check, Copy, TriangleAlert, X } from "lucide-react";
import { type ReactNode, useId, useRef } from "react";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { relativeTime } from "@/shared/lib/time";
import { useFlash } from "@/shared/lib/use-flash";
import { useNow } from "@/shared/lib/use-now";
import { cn } from "@/shared/lib/utils";
import { IconButton } from "@/shared/ui/button";
import { aiUsageQueryOptions, healthQueryOptions } from "../api/instance-status";
import { useDismissed } from "../hooks/use-dismissed";
import { messages } from "../messages";
import { dismissKey, type Notice, noticesOf } from "../model/notices";

/*
 * The instance banner, after the free shadcnblocks Banner (`banner1`): a `warning-soft` strip with
 * a hairline under it at the top of the sheet, one sentence and its action, and a Dismiss. For
 * operators only; it reserves no space, so a healthy instance shows nothing at all.
 */

const action =
  "inline-flex items-center gap-1 font-medium whitespace-nowrap underline underline-offset-2 outline-none focus-visible:rounded-sm focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-3.5";

/** What the banner tells operators to run where the server runs. */
const REINDEX = "exactdocs reindex";

function NoticeAction({ notice }: { notice: Notice }) {
  const t = useMessages(messages);
  const c = useMessages(common);
  const [copied, flash] = useFlash(2000);
  if (notice.kind === "reindex") {
    // The fix happens on the server: the action hands over the command.
    const copy = () => {
      // A refused clipboard changes nothing: the command is in the sentence to copy by hand.
      navigator.clipboard?.writeText(REINDEX).then(flash, () => {});
    };
    return (
      <button type="button" onClick={copy} className={cn(action, "cursor-pointer")}>
        {copied ? c.copied : t.reindex.action}
        {copied ? (
          <Check aria-hidden="true" data-icon-motion="draw" />
        ) : (
          <Copy aria-hidden="true" data-icon-motion="pop" />
        )}
      </button>
    );
  }
  const [hash, label] =
    notice.kind === "budget" ? ["usage", t.budget.action] : ["embedding", t.vectorStore.action];
  return (
    <Link to="/ai" hash={hash} className={action}>
      {label}
      <ArrowRight aria-hidden="true" data-icon-motion="forward" />
    </Link>
  );
}

function NoticeText({ notice }: { notice: Notice }): ReactNode {
  const t = useMessages(messages);
  const language = useLanguage();
  const now = useNow();
  switch (notice.kind) {
    case "reindex":
      return t.reindex.text();
    case "vector-store":
      return t.vectorStore.text(notice.extension);
    case "budget":
      return t.budget.text(
        notice.window,
        relativeTime(notice.resetsAt, now, language, { future: true }),
      );
  }
}

function NoticeRow({ notice, onDismiss }: { notice: Notice; onDismiss: () => void }) {
  const t = useMessages(messages);
  const textId = useId();
  return (
    <div
      data-notice={notice.kind}
      className="reveal flex items-start gap-3 border-b border-border bg-warning-soft py-1.5 pr-1.5 pl-4 text-body text-warning-ink sm:pl-6 lg:pl-8"
    >
      <TriangleAlert
        aria-hidden="true"
        data-icon-motion="alert"
        className="mt-3 size-4 flex-none fine:mt-2.5"
      />
      <p id={textId} className="min-w-0 flex-1 py-2 fine:py-1.5">
        <NoticeText notice={notice} /> <NoticeAction notice={notice} />
      </p>
      {notice.dismissible ? (
        <IconButton
          label={t.dismiss}
          size="icon-sm"
          motion="turn"
          aria-describedby={textId}
          data-dismiss=""
          onClick={onDismiss}
          className="flex-none text-warning-ink can-hover:hover:bg-warning/10"
        >
          <X aria-hidden="true" />
        </IconButton>
      ) : (
        // The reindex notice cannot be dismissed; the gap keeps the text clear of the edge.
        <span aria-hidden="true" className="size-11 flex-none fine:size-8" />
      )}
    </div>
  );
}

/**
 * The banner for operators (`operator` false renders nothing and asks nothing). Notices arrive in
 * a polite live region that is mounted first, so screen readers announce them without moving
 * focus; it becomes the named `role="status"` once it holds one (an empty status would be one more
 * status on every page). Dismissing one moves focus to the next notice, else to the page's heading.
 */
export function InstanceBanner({ operator }: { operator: boolean }) {
  const t = useMessages(messages);
  const health = useQuery({ ...healthQueryOptions(), enabled: operator });
  const usage = useQuery({ ...aiUsageQueryOptions(), enabled: operator });
  const { dismissed, dismiss } = useDismissed();
  const region = useRef<HTMLDivElement>(null);
  if (!operator) return null;

  const notices = noticesOf(health.data, usage.data).filter((n) => !dismissed.has(dismissKey(n)));

  function onDismiss(notice: Notice, index: number) {
    dismiss(dismissKey(notice));
    // The button is about to go: hand focus on before the browser drops it to <body>.
    const rows = region.current?.querySelectorAll<HTMLElement>("[data-notice]") ?? [];
    const next = rows[index + 1] ?? rows[index - 1];
    // Its Dismiss (so dismissing one after another stays put), its action when it has none.
    const target =
      next?.querySelector<HTMLElement>("[data-dismiss]") ??
      next?.querySelector<HTMLElement>("a, button") ??
      document.querySelector<HTMLElement>("#main h1[tabindex]");
    target?.focus();
  }

  return (
    <div
      ref={region}
      aria-live="polite"
      {...(notices.length > 0 && { role: "status", "aria-label": t.region })}
      className="overflow-hidden md:rounded-t-[calc(var(--radius-sheet)-1px)]"
    >
      {notices.map((notice, index) => (
        <NoticeRow
          key={dismissKey(notice)}
          notice={notice}
          onDismiss={() => onDismiss(notice, index)}
        />
      ))}
    </div>
  );
}
