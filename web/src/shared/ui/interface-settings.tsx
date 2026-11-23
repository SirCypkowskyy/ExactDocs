import { RotateCcw } from "lucide-react";
import { RadioGroup as R, Switch as S } from "radix-ui";
import { useId } from "react";
import { LANGUAGE_NAMES, LANGUAGES, useMessages } from "@/shared/lib/i18n";
import {
  DEFAULT_PREFERENCES,
  type LanguageChoice,
  type Preferences,
  resetPreferences,
  resolveLanguage,
  setPreferences,
  TEXT_SCALES,
  usePreferences,
} from "@/shared/lib/preferences";
import { cn } from "@/shared/lib/utils";
import { Button } from "./button";
import { interfaceMessages } from "./interface-messages";

/*
 * Account → Interface (#486): every interface preference with a sentence on what it does, applied
 * as it is chosen (no Save button: the band works the same way). `status` says where the choices
 * are kept ("Saved to your account" or "Kept in this browser"), from the auth feature's sync.
 */

type Option<T> = { value: T; label: string; hint?: string | undefined; lang?: string };

function Choice<T extends string | number>({
  legend,
  description,
  options,
  value,
  onChange,
  columns = 3,
  preview,
}: {
  legend: string;
  description?: string;
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
  columns?: 2 | 3 | 4 | 5;
  preview?: (option: Option<T>) => React.ReactNode;
}) {
  const id = useId();
  return (
    <fieldset className="grid gap-3 md:grid-cols-[minmax(0,15rem)_1fr] md:gap-8">
      <div>
        <legend className="text-section font-semibold" id={`${id}-l`}>
          {legend}
        </legend>
        {description && (
          <p className="mt-1 text-body text-muted-foreground" id={`${id}-d`}>
            {description}
          </p>
        )}
      </div>
      <R.Root
        aria-labelledby={`${id}-l`}
        aria-describedby={description ? `${id}-d` : undefined}
        value={String(value)}
        onValueChange={(v) => {
          const match = options.find((o) => String(o.value) === v);
          if (match) onChange(match.value);
        }}
        className={cn(
          "grid gap-2",
          columns === 2 && "grid-cols-2",
          columns === 3 && "grid-cols-2 sm:grid-cols-3",
          columns === 4 && "grid-cols-2 sm:grid-cols-4",
          columns === 5 && "grid-cols-3 sm:grid-cols-5",
        )}
      >
        {options.map((option) => (
          <R.Item
            key={String(option.value)}
            value={String(option.value)}
            lang={option.lang}
            className="group flex min-h-11 cursor-pointer flex-col items-start justify-center gap-0.5 rounded-md border border-input bg-background px-3 py-2 text-left outline-none transition-[border-color,background-color,box-shadow,transform] duration-(--dur-fast) ease-(--ease-out) focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:scale-[0.98] data-[state=checked]:border-selection data-[state=checked]:bg-selection-soft data-[state=checked]:shadow-[inset_0_0_0_1px_var(--selection)] can-hover:hover:border-muted-foreground/50"
          >
            {preview?.(option)}
            <span className="text-body font-medium">{option.label}</span>
            {option.hint && <span className="text-small text-muted-foreground">{option.hint}</span>}
          </R.Item>
        ))}
      </R.Root>
    </fieldset>
  );
}

function Toggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="grid gap-3 md:grid-cols-[minmax(0,15rem)_1fr] md:gap-8">
      <label htmlFor={id} className="cursor-pointer text-section font-semibold">
        {label}
      </label>
      <div className="flex items-start justify-between gap-6">
        <p className="text-body text-muted-foreground" id={`${id}-d`}>
          {description}
        </p>
        <S.Root
          id={id}
          checked={checked}
          onCheckedChange={onChange}
          aria-describedby={`${id}-d`}
          className="relative inline-flex h-6 w-10 flex-none cursor-pointer items-center rounded-full border border-input bg-secondary p-0.5 outline-none transition-colors duration-(--dur) ease-(--ease-out) focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background data-[state=checked]:border-selection data-[state=checked]:bg-selection [&::before]:absolute [&::before]:-inset-2.5 [&::before]:content-['']"
        >
          <S.Thumb className="block size-4.5 rounded-full bg-background ring-1 ring-input transition-transform duration-(--dur) ease-(--ease-out) data-[state=checked]:translate-x-4" />
        </S.Root>
      </div>
    </div>
  );
}

export function InterfaceSettings({ status }: { status?: React.ReactNode }) {
  const { prefs } = usePreferences();
  const t = useMessages(interfaceMessages);
  const scaleHint: Partial<Record<number, string>> = {
    90: t.compact,
    100: t.default,
    150: t.largest,
  };
  const set = (patch: Partial<Preferences>) => setPreferences(patch);
  const isDefault = JSON.stringify(prefs) === JSON.stringify(DEFAULT_PREFERENCES);
  return (
    <div className="grid gap-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-body text-muted-foreground" role="status">
          {status}
        </p>
        <Button variant="outline" size="sm" disabled={isDefault} onClick={() => resetPreferences()}>
          <RotateCcw aria-hidden="true" data-icon-motion="refresh" />
          {t.resetToDefaults}
        </Button>
      </div>

      <Choice<LanguageChoice>
        legend={t.language}
        description={t.languageDescription}
        options={[
          ...LANGUAGES.map((code) => ({ value: code, label: LANGUAGE_NAMES[code], lang: code })),
          {
            value: "system",
            label: t.system,
            hint: t.followsBrowser(LANGUAGE_NAMES[resolveLanguage("system")]),
          },
        ]}
        value={prefs.language}
        onChange={(language) => set({ language })}
      />

      <Choice
        legend={t.theme}
        options={[
          { value: "light", label: t.light },
          { value: "dark", label: t.dark },
          { value: "system", label: t.system, hint: t.followsDevice },
        ]}
        value={prefs.theme}
        onChange={(theme) => set({ theme })}
      />

      <Choice
        legend={t.textSizeLegend}
        description={t.textSizeDescription}
        columns={5}
        options={TEXT_SCALES.map((value) => ({
          value,
          label: `${value}%`,
          hint: scaleHint[value],
        }))}
        value={prefs.text_scale}
        onChange={(text_scale) => set({ text_scale })}
        preview={(option) => (
          <span
            aria-hidden="true"
            className="font-semibold leading-none"
            style={{ fontSize: `${(Number(option.value) / 100) * 1.125}rem` }}
          >
            Aa
          </span>
        )}
      />

      <Choice
        legend={t.font}
        description={t.fontDescription}
        columns={4}
        options={[
          { value: "default", label: "ExactDocs", hint: t.theDefault },
          { value: "hyperlegible", label: "Atkinson Hyperlegible", hint: t.distinctShapes },
          { value: "dyslexic", label: "OpenDyslexic", hint: t.weightedBottoms },
          { value: "system", label: t.systemFont, hint: t.devicesOwn },
        ]}
        value={prefs.font}
        onChange={(font) => set({ font })}
        preview={(option) => (
          <span
            aria-hidden="true"
            data-font-preview={option.value}
            className="text-section leading-tight font-medium"
          >
            Rg 1Il0O
          </span>
        )}
      />

      <Choice
        legend={t.contrast}
        columns={2}
        options={[
          { value: "standard", label: t.standardContrast },
          { value: "more", label: t.more, hint: t.moreHint },
        ]}
        value={prefs.contrast}
        onChange={(contrast) => set({ contrast })}
      />

      <Choice
        legend={t.motion}
        description={t.motionDescription}
        options={[
          { value: "system", label: t.system, hint: t.followsDevice },
          { value: "reduced", label: t.reduced },
          { value: "full", label: t.full },
        ]}
        value={prefs.motion}
        onChange={(motion) => set({ motion })}
      />

      <Choice
        legend={t.textSpacing}
        description={t.textSpacingDescription}
        columns={2}
        options={[
          { value: "standard", label: t.standardSpacing },
          { value: "wide", label: t.wide },
        ]}
        value={prefs.text_spacing}
        onChange={(text_spacing) => set({ text_spacing })}
      />

      <Toggle
        label={t.underlineLinks}
        description={t.underlineLinksDescription}
        checked={prefs.underline_links}
        onChange={(underline_links) => set({ underline_links })}
      />

      <Toggle
        label={t.largerTargets}
        description={t.largerTargetsDescription}
        checked={prefs.large_targets}
        onChange={(large_targets) => set({ large_targets })}
      />

      <Toggle
        label={t.libraryLogos}
        description={t.libraryLogosDescription}
        checked={prefs.library_logos}
        onChange={(library_logos) => set({ library_logos })}
      />
    </div>
  );
}
