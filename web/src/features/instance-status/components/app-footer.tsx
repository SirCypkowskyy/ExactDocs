import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, ExternalLink } from "lucide-react";
import type { ReactNode } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { Mark } from "@/shared/ui/wordmark";
import { healthQueryOptions } from "../api/instance-status";
import { messages } from "../messages";

const REPO = "https://github.com/SirCypkowskyy/ExactDocs";
const DOCS = "https://sircypkowskyy.github.io/ExactDocs/";

/** A footer link: muted ink that turns to ink and underlines, a line high with a mouse, 44px on touch. */
const link =
  "inline-flex min-h-11 items-center gap-1 rounded-sm underline-offset-4 outline-none transition-colors duration-(--dur-fast) ease-(--ease-out) fine:min-h-7 focus-visible:ring-2 focus-visible:ring-ring can-hover:hover:text-foreground can-hover:hover:underline [&_svg]:size-3";

function Away({ href, children }: { href: string; children: ReactNode }) {
  const t = useMessages(messages).footer;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={link}>
      {children}
      <ExternalLink aria-hidden="true" data-icon-motion="out" />
      <span className="sr-only">{t.newTab}</span>
    </a>
  );
}

/**
 * The footer on every page, on the frame under the sheet like the docs site's: the sign, the
 * version the server reports on `/api/health`, and where to read more. `signedIn` adds the way to
 * the MCP config (Account, API tokens), which only a signed-in person can open.
 */
export function AppFooter({ signedIn }: { signedIn: boolean }) {
  const t = useMessages(messages).footer;
  // The banner polls the same entry once a minute; the footer only needs it once.
  const { data } = useQuery({ ...healthQueryOptions(), refetchInterval: false });
  // An untrusted Host, an older server or a proxy's page carries no version: show none.
  const version = typeof data?.version === "string" ? data.version : null;
  return (
    <footer className="flex flex-none flex-wrap items-center justify-between gap-x-6 bg-frame pt-1 pb-[max(0.25rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] text-small text-muted-foreground max-sm:flex-col max-sm:items-start">
      <p className="flex min-h-11 max-w-full min-w-0 items-center gap-2 fine:min-h-7">
        <Mark className="size-5" />
        <span className="font-medium text-foreground">ExactDocs</span>
        {version && (
          // A dev build's version is long (0.9.1.dev3+g1a2b3c4): it wraps instead of widening the page.
          <span className="min-w-0 font-mono [overflow-wrap:anywhere]">
            <span className="sr-only">{t.version} </span>
            {version}
          </span>
        )}
      </p>
      <nav aria-label={t.nav}>
        <ul className="flex flex-wrap items-center gap-x-4">
          {signedIn && (
            <li>
              <Link to="/account" className={link}>
                {t.connect}
                <ArrowRight aria-hidden="true" data-icon-motion="forward" />
              </Link>
            </li>
          )}
          <li>
            <Away href={DOCS}>{t.docs}</Away>
          </li>
          <li>
            <Away href={`${DOCS}rest-api/`}>{t.api}</Away>
          </li>
          <li>
            {/* The instance's own description of /api/v1, served without a caller. */}
            <a href="/api/v1/openapi.json" className={link}>
              {t.openapi}
            </a>
          </li>
          <li>
            <Away href={REPO}>{t.source}</Away>
          </li>
          <li>
            <Away href={`${REPO}/blob/main/LICENSE`}>{t.license}</Away>
          </li>
        </ul>
      </nav>
    </footer>
  );
}
