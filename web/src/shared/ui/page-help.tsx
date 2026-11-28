import type { LucideIcon } from "lucide-react";
import { BookOpen, CircleHelp, ExternalLink, X } from "lucide-react";
import { Dialog } from "radix-ui";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import type { Language } from "@/shared/lib/i18n";
import { useLanguage, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button, IconButton } from "./button";
import { messages } from "./messages";

/*
 * Page tours (DESIGN.md, Help tours). A page passes a HelpTopic to `PageHeader help={…}`; the
 * header then shows a Help button that walks through the page: each step rings one part of it
 * (the element whose `data-tour` names the step's target) on a dimmed page, and a card says what
 * that part is for, with a link to the matching page of the documentation.
 */

/** One string per language; the type makes both required. */
export type Localized = Readonly<Record<Language, string>>;

export interface HelpStep {
  icon: LucideIcon;
  /** Names the part of the page, in two to four words. */
  title: Localized;
  /** What it is for, in one or two short sentences. */
  body: Localized;
  /** The `data-tour` value of the element to ring. A missing or hidden element rings nothing. */
  target?: string;
  /** A page of the docs site, relative to its root: `mcp/connect/#over-http`. */
  guide: string;
}

/** A page's tour: a title and 3 to 6 steps. */
export interface HelpTopic {
  title: Localized;
  steps: readonly [HelpStep, ...HelpStep[]];
}

/** The published documentation (zensical.toml `site_url`); guide paths resolve under it. */
export const DOCS_URL = "https://sircypkowskyy.github.io/ExactDocs/";

export const guideUrl = (path: string) => new URL(path, DOCS_URL).href;

interface Spot {
  top: number;
  left: number;
  width: number;
  height: number;
  /** Its centre is in the lower half of the screen: the card moves to the top. */
  low: boolean;
}

/** Where the step's target is on the screen, after scrolling it into view; undefined if absent. */
function useSpot(target: string | undefined): Spot | undefined {
  const [spot, setSpot] = useState<Spot>();
  useEffect(() => {
    const element = target ? document.querySelector(`[data-tour="${target}"]`) : null;
    const box = () => element?.getBoundingClientRect();
    const first = box();
    // Not on the page, or hidden (a phone folds some parts away): the card shows on its own.
    if (!element || !first || first.width === 0 || first.height === 0) {
      setSpot(undefined);
      return;
    }
    const tall = () => (box()?.height ?? 0) > window.innerHeight * 0.6;
    element.scrollIntoView({ block: tall() ? "start" : "nearest" });
    let frame = 0;
    const measure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const rect = box();
        if (!rect || rect.width === 0) return setSpot(undefined);
        // A target taller than the screen is ringed where it is visible.
        const top = Math.max(rect.top, 8);
        const bottom = Math.min(rect.bottom, window.innerHeight - 8);
        setSpot({
          top,
          left: rect.left,
          width: rect.width,
          height: Math.max(bottom - top, 0),
          low: (top + bottom) / 2 > window.innerHeight / 2,
        });
      });
    };
    measure();
    // Data that arrives later moves and resizes the target under the open tour.
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    observer.observe(document.body);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [target]);
  return spot;
}

/** The Help button and its tour. PageHeader renders it for `help={topic}`. */
export function PageHelp({ topic }: { topic: HelpTopic }) {
  const t = useMessages(messages).help;
  const language = useLanguage();
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const nextRef = useRef<HTMLButtonElement>(null);
  const total = topic.steps.length;
  const step = topic.steps[Math.min(index, total - 1)] ?? topic.steps[0];
  const last = index >= total - 1;
  const spot = useSpot(open ? step.target : undefined);
  const count = t.step(index + 1, total);
  const go = (to: number) => {
    const next = Math.min(Math.max(to, 0), total - 1);
    setIndex(next);
    // Back turns off on the first step: focus moves on to Next instead of falling to the page.
    if (next === 0) nextRef.current?.focus();
  };
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "ArrowRight") go(index + 1);
    else if (event.key === "ArrowLeft") go(index - 1);
    // The close button's tooltip would take the first Escape for itself: one press leaves.
    else if (event.key === "Escape") setOpen(false);
  };
  const Icon = step.icon;

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        setOpen(value);
        if (value) setIndex(0);
      }}
    >
      <Dialog.Trigger asChild>
        <Button variant="ghost" size="sm" className="max-sm:w-11 max-sm:px-0">
          <CircleHelp aria-hidden="true" data-icon-motion="pop" />
          <span className="max-sm:sr-only">{t.button}</span>
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        {/* With a ring, the ring's own shadow is the scrim; the overlay only catches clicks. */}
        <Dialog.Overlay
          className={cn(
            "fixed inset-0 z-50 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-(--dur) data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:duration-(--dur-fast)",
            !spot && "bg-overlay",
          )}
        />
        {spot && (
          // Keyed by step: each ring fades in where its part is (no travel across the page).
          <div
            key={index}
            aria-hidden="true"
            data-slot="tour-spotlight"
            className="fade-in pointer-events-none fixed z-50 rounded-lg shadow-[0_0_0_100vmax_var(--overlay)] outline-2 outline-offset-2 outline-ring"
            style={{
              top: spot.top - 6,
              left: spot.left - 6,
              width: spot.width + 12,
              height: spot.height + 12,
            }}
          />
        )}
        <Dialog.Content
          data-slot="tour-card"
          onKeyDown={onKeyDown}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            nextRef.current?.focus();
          }}
          // One layer above the ring: its 100vmax shadow would otherwise dim the card too.
          className={cn(
            "fixed z-[51] grid max-h-[85dvh] gap-4 overflow-y-auto bg-popover p-5 text-popover-foreground shadow-float outline-none",
            "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-(--dur) data-[state=open]:ease-(--ease-out) data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:duration-(--dur-fast)",
            // A sheet on a phone, a card in a corner from 48rem; it keeps off the ringed part.
            "max-md:inset-x-0 md:right-6 md:w-[26rem] md:rounded-lg",
            spot?.low
              ? "top-0 max-md:rounded-b-xl max-md:data-[state=open]:slide-in-from-top md:top-6 md:origin-top-right md:data-[state=open]:zoom-in-97"
              : "bottom-0 pb-[max(1.25rem,env(safe-area-inset-bottom))] max-md:rounded-t-xl max-md:data-[state=open]:slide-in-from-bottom md:bottom-6 md:origin-bottom-right md:data-[state=open]:zoom-in-97",
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <Dialog.Title className="text-body font-semibold">{topic.title[language]}</Dialog.Title>
            <Dialog.Close asChild>
              <IconButton label={t.close} size="icon-sm" className="-mt-1.5 -mr-2" motion="turn">
                <X aria-hidden="true" />
              </IconButton>
            </Dialog.Close>
          </div>
          {/* Announced on every step: where you are, the part's name and what it does. */}
          <Dialog.Description asChild>
            <div aria-live="polite" aria-atomic="true" className="min-h-24">
              <span className="sr-only">{count}. </span>
              <div key={index} className="fade-in flex gap-3">
                <span
                  aria-hidden="true"
                  className="inline-flex size-9 flex-none items-center justify-center rounded-lg border border-border bg-raised text-muted-foreground [&_svg]:size-[1.125rem]"
                >
                  <Icon />
                </span>
                <span className="grid min-w-0 gap-1">
                  <span className="text-body font-semibold text-foreground">
                    {step.title[language]}
                  </span>
                  <span className="text-body text-pretty text-muted-foreground">
                    {step.body[language]}
                  </span>
                </span>
              </div>
            </div>
          </Dialog.Description>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div aria-hidden="true" className="flex items-center gap-2.5">
              <ol className="flex gap-1">
                {topic.steps.map((item, position) => (
                  <li
                    key={item.title.en}
                    className={cn(
                      "h-1.5 rounded-full transition-colors duration-(--dur) ease-(--ease-out)",
                      position === index ? "w-4 bg-foreground" : "w-1.5 bg-foreground/25",
                    )}
                  />
                ))}
              </ol>
              <span className="num text-small text-muted-foreground">{count}</span>
            </div>
            <div className="flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                disabled={index === 0}
                onClick={() => go(index - 1)}
              >
                {t.back}
              </Button>
              <Button
                ref={nextRef}
                size="sm"
                onClick={() => (last ? setOpen(false) : go(index + 1))}
              >
                {last ? t.done : t.next}
              </Button>
            </div>
          </div>
          <div className="border-t border-rule pt-3">
            <a
              href={guideUrl(step.guide)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-8 items-center gap-2 rounded text-small font-medium text-foreground underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
            >
              <BookOpen aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
              {t.guide}
              <ExternalLink aria-hidden="true" data-icon-motion="out" className="size-3 shrink-0" />
              <span className="sr-only">{t.newTab}</span>
            </a>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
