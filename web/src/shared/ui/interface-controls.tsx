import { Link } from "@tanstack/react-router";
import {
  AArrowDown,
  AArrowUp,
  Accessibility,
  Check,
  Moon,
  SlidersHorizontal,
  Sun,
} from "lucide-react";
import { DropdownMenu as M } from "radix-ui";
import { LANGUAGE_NAMES, LANGUAGES, useMessages } from "@/shared/lib/i18n";
import {
  type Contrast,
  type Font,
  type LanguageChoice,
  type Motion,
  resolveLanguage,
  setPreferences,
  TEXT_SCALES,
  type TextScale,
  usePreferences,
} from "@/shared/lib/preferences";
import { cn } from "@/shared/lib/utils";
import { buttonVariants, IconButton } from "./button";
import { menuContent, menuItem, menuLabel, menuSeparator } from "./dropdown-menu";
import { interfaceMessages } from "./interface-messages";

/*
 * The interface controls in the band (#486): text size, theme and language are one press away;
 * everything else (contrast, motion, font, spacing, links, targets) sits in one menu whose last item opens
 * Account → Interface. They change the preferences store, which applies at once and, when signed
 * in, saves to the account.
 */

/**
 * The band's square icon button as classes, for a trigger that cannot be an `IconButton` (a
 * Sheet trigger with its own name): 44 px on touch, 36 px with a mouse, press 0.94.
 */
export const bandIconButton = cn(buttonVariants({ variant: "band", size: "icon" }));

const scaleIndex = (scale: TextScale) => TEXT_SCALES.indexOf(scale);

/** Smaller and larger text: one step of 90, 100, 110, 125, 150 %. */
export function TextSizeControl({ className }: { className?: string }) {
  const { prefs } = usePreferences();
  const t = useMessages(interfaceMessages);
  const i = scaleIndex(prefs.text_scale);
  const step = (delta: number) => {
    const next = TEXT_SCALES[i + delta];
    if (next) setPreferences({ text_scale: next });
  };
  return (
    // biome-ignore lint/a11y/useSemanticElements: a group of two buttons, not a form fieldset
    <div role="group" aria-label={t.textSize(prefs.text_scale)} className={cn("flex", className)}>
      <IconButton
        variant="band"
        label={t.smallerText}
        shortcut="Ctrl −"
        disabled={i <= 0}
        onClick={() => step(-1)}
      >
        <AArrowDown aria-hidden="true" data-icon-motion="down" />
      </IconButton>
      <IconButton
        variant="band"
        label={t.largerText}
        shortcut="Ctrl +"
        disabled={i >= TEXT_SCALES.length - 1}
        onClick={() => step(1)}
      >
        <AArrowUp aria-hidden="true" data-icon-motion="up" />
      </IconButton>
    </div>
  );
}

/**
 * Light or dark in one press. The icon turns over (a quarter turn with a cross-fade), the page
 * cross-fades; "follow the system" lives in the interface menu and on the Interface tab.
 */
export function ThemeButton({ className }: { className?: string }) {
  const { resolved } = usePreferences();
  const t = useMessages(interfaceMessages);
  // What the page shows right now wins over the media query (they can disagree for a moment).
  const dark =
    typeof document !== "undefined"
      ? document.documentElement.classList.contains("dark")
      : resolved === "dark";
  const next = dark ? "light" : "dark";
  const label = next === "dark" ? t.darkTheme : t.lightTheme;
  return (
    <IconButton
      variant="band"
      label={label}
      className={cn("overflow-hidden", className)}
      onClick={() => setPreferences({ theme: next })}
    >
      <Sun
        aria-hidden="true"
        className="absolute transition-[opacity,transform] duration-(--dur) ease-(--ease-out) dark:scale-75 dark:-rotate-90 dark:opacity-0 motion-reduce:transition-opacity"
      />
      <Moon
        aria-hidden="true"
        className="absolute scale-75 rotate-90 opacity-0 transition-[opacity,transform] duration-(--dur) ease-(--ease-out) dark:scale-100 dark:rotate-0 dark:opacity-100 motion-reduce:transition-opacity"
      />
    </IconButton>
  );
}

function RadioRow<T extends string>({
  value,
  lang,
  children,
}: {
  value: T;
  lang?: string;
  children: React.ReactNode;
}) {
  return (
    <M.RadioItem value={value} lang={lang} className={menuItem}>
      <span className="flex-1">{children}</span>
      <M.ItemIndicator>
        <Check aria-hidden="true" data-icon-motion="draw" className="text-selection" />
      </M.ItemIndicator>
    </M.RadioItem>
  );
}

function CheckRow({
  checked,
  onChange,
  children,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <M.CheckboxItem
      checked={checked}
      onCheckedChange={(v) => onChange(v === true)}
      onSelect={(e) => e.preventDefault()}
      className={menuItem}
    >
      <span className="flex-1">{children}</span>
      <M.ItemIndicator>
        <Check aria-hidden="true" data-icon-motion="draw" className="text-selection" />
      </M.ItemIndicator>
    </M.CheckboxItem>
  );
}

/** Everything else, in one menu. `settings` is where "All interface settings" goes. */
export function InterfaceMenu({
  settings = "/account",
  className,
}: {
  settings?: "/account" | null;
  className?: string;
}) {
  const { prefs } = usePreferences();
  const t = useMessages(interfaceMessages);
  const changed =
    prefs.contrast !== "standard" ||
    prefs.motion !== "system" ||
    prefs.font !== "default" ||
    prefs.text_spacing !== "standard" ||
    prefs.underline_links ||
    prefs.large_targets ||
    !prefs.library_logos;
  return (
    <M.Root>
      <M.Trigger asChild>
        <IconButton variant="band" label={t.interfaceAndAccessibility} className={className}>
          <Accessibility aria-hidden="true" data-icon-motion="pop" />
          {changed && (
            <span
              aria-hidden="true"
              className="absolute top-2 right-2 size-1.5 rounded-full bg-selection fine:top-1.5 fine:right-1.5"
            />
          )}
        </IconButton>
      </M.Trigger>
      <M.Portal>
        <M.Content
          align="end"
          sideOffset={6}
          collisionPadding={8}
          className={cn(menuContent, "w-64")}
        >
          <M.Label className={menuLabel}>{t.theme}</M.Label>
          <M.RadioGroup
            value={prefs.theme}
            onValueChange={(v) => setPreferences({ theme: v as typeof prefs.theme })}
          >
            <RadioRow value="light">{t.light}</RadioRow>
            <RadioRow value="dark">{t.dark}</RadioRow>
            <RadioRow value="system">{t.followSystem}</RadioRow>
          </M.RadioGroup>
          <M.Separator className={menuSeparator} />
          <CheckRow
            checked={prefs.contrast === "more"}
            onChange={(v) => setPreferences({ contrast: (v ? "more" : "standard") as Contrast })}
          >
            {t.moreContrast}
          </CheckRow>
          <CheckRow
            checked={prefs.motion === "reduced"}
            onChange={(v) => setPreferences({ motion: (v ? "reduced" : "system") as Motion })}
          >
            {t.reduceMotion}
          </CheckRow>
          <CheckRow
            checked={prefs.font === "hyperlegible" || prefs.font === "dyslexic"}
            onChange={(v) => setPreferences({ font: (v ? "hyperlegible" : "default") as Font })}
          >
            {t.easierFont}
          </CheckRow>
          <CheckRow
            checked={prefs.text_spacing === "wide"}
            onChange={(v) => setPreferences({ text_spacing: v ? "wide" : "standard" })}
          >
            {t.widerSpacing}
          </CheckRow>
          <CheckRow
            checked={prefs.underline_links}
            onChange={(v) => setPreferences({ underline_links: v })}
          >
            {t.underlineLinks}
          </CheckRow>
          <CheckRow
            checked={prefs.large_targets}
            onChange={(v) => setPreferences({ large_targets: v })}
          >
            {t.largerTargets}
          </CheckRow>
          <CheckRow
            checked={prefs.library_logos}
            onChange={(v) => setPreferences({ library_logos: v })}
          >
            {t.libraryLogos}
          </CheckRow>
          {settings && (
            <>
              <M.Separator className={menuSeparator} />
              <M.Item asChild className={menuItem}>
                <Link to={settings} search={{ tab: "interface" }}>
                  <SlidersHorizontal
                    aria-hidden="true"
                    data-icon-motion="cog"
                    className="text-muted-foreground"
                  />
                  <span className="flex-1">{t.allSettings}</span>
                </Link>
              </M.Item>
            </>
          )}
        </M.Content>
      </M.Portal>
    </M.Root>
  );
}

/**
 * The language in one menu: the code of the language the UI speaks now (EN, PL) on the button,
 * each language named in itself in the list, and "browser language" to follow the browser.
 */
export function LanguageMenu({ className }: { className?: string }) {
  const { prefs, language } = usePreferences();
  const t = useMessages(interfaceMessages);
  const browser = LANGUAGE_NAMES[resolveLanguage("system")];
  return (
    <M.Root>
      <M.Trigger asChild>
        <IconButton
          variant="band"
          label={t.languageNow(LANGUAGE_NAMES[language])}
          className={className}
        >
          <span aria-hidden="true" className="text-small font-semibold tracking-wide uppercase">
            {language}
          </span>
        </IconButton>
      </M.Trigger>
      <M.Portal>
        <M.Content
          align="end"
          sideOffset={6}
          collisionPadding={8}
          className={cn(menuContent, "w-60")}
        >
          <M.Label className={menuLabel}>{t.language}</M.Label>
          <M.RadioGroup
            value={prefs.language}
            onValueChange={(v) => setPreferences({ language: v as LanguageChoice })}
          >
            {LANGUAGES.map((code) => (
              <RadioRow key={code} value={code} lang={code}>
                {LANGUAGE_NAMES[code]}
              </RadioRow>
            ))}
            <M.Separator className={menuSeparator} />
            <RadioRow value="system">{t.followBrowser(browser)}</RadioRow>
          </M.RadioGroup>
        </M.Content>
      </M.Portal>
    </M.Root>
  );
}

/**
 * The band's interface console: text size, theme, language and the interface menu as one bordered group,
 * so they read as one instrument instead of loose icons. Text size hides below `sm`.
 */
export function InterfaceCluster({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex items-center rounded-lg border border-border bg-background/70 p-0.5 dark:bg-background/40 [&_button]:size-10 fine:[&_button]:size-8 [&_button]:rounded-md",
        className,
      )}
    >
      <TextSizeControl className="hidden sm:flex" />
      <span aria-hidden="true" className="mx-0.5 hidden h-4 w-px bg-border sm:block" />
      <ThemeButton />
      <LanguageMenu />
      <InterfaceMenu />
    </div>
  );
}
