import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { ruleText } from "@/shared/lib/role-rules";
import { Button } from "@/shared/ui/button";
import { DialogContent, DialogDescription, DialogRoot, DialogTitle } from "@/shared/ui/dialog";
import { Field } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { LibraryCombobox } from "@/shared/ui/library-combobox";
import { SelectField } from "@/shared/ui/select-field";
import { addRoleRule, RULE_CHANGE_KEYS, ruleLibrariesQueryOptions } from "../api/role-rules-query";
import {
  explainRuleError,
  GRANTS,
  isLibraryGrant,
  type RuleGrant,
  type RuleProvider,
  type RuleSource,
  sourcesOf,
} from "../model/role-rule";
import { rulesMessages } from "../rules-messages";

interface Props {
  providers: readonly RuleProvider[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded: (text: string) => void;
}

/** A new role rule: a provider's membership and what its members get. */
export function AddRuleDialog({ providers, open, onOpenChange, onAdded }: Props) {
  return (
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <Body providers={providers} onDone={() => onOpenChange(false)} onAdded={onAdded} />
      </DialogContent>
    </DialogRoot>
  );
}

type Errors = Partial<Record<"value" | "libraries", string>>;

function Body({
  providers,
  onDone,
  onAdded,
}: {
  providers: readonly RuleProvider[];
  onDone: () => void;
  onAdded: (text: string) => void;
}) {
  const queryClient = useQueryClient();
  const language = useLanguage();
  const t = useMessages(rulesMessages).add;
  const c = useMessages(common);
  const [providerName, setProviderName] = useState(providers[0]?.name ?? "");
  const provider = providers.find((p) => p.name === providerName);
  const sources = sourcesOf(provider);
  const [picked, setSource] = useState<RuleSource>();
  const source = picked && sources.includes(picked) ? picked : (sources[0] ?? "group");
  const [grant, setGrant] = useState<RuleGrant>("viewer");
  const [chosen, setChosen] = useState(false);
  const [libraries, setLibraries] = useState<string[]>([]);
  const [errors, setErrors] = useState<Errors>({});
  const [failure, setFailure] = useState<{ error: unknown }>();
  const [pending, setPending] = useState(false);
  const scoped = isLibraryGrant(grant) && chosen;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const value = String(new FormData(event.currentTarget).get("rule-value") ?? "").trim();
    const found: Errors = {
      ...(!value && { value: t.valueMissing }),
      ...(scoped && libraries.length === 0 && { libraries: t.librariesMissing }),
    };
    setErrors(found);
    setFailure(undefined);
    if (found.value) {
      document.getElementById("rule-value")?.focus();
      return;
    }
    if (found.libraries) return;
    setPending(true);
    try {
      const added = await addRoleRule({
        provider: providerName,
        source,
        value,
        grant,
        ...(scoped && { libraries: [...libraries].sort() }),
      });
      onAdded(ruleText(added, language));
      onDone();
    } catch (error) {
      setFailure({ error });
    } finally {
      setPending(false);
      for (const queryKey of RULE_CHANGE_KEYS) void queryClient.invalidateQueries({ queryKey });
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <DialogTitle>{t.title}</DialogTitle>
      <DialogDescription>{t.description}</DialogDescription>
      <div className="mt-5">
        <FormAlert id="rule-alert" message={failure && explainRuleError(failure.error, language)} />
      </div>
      <div className="flex flex-col gap-4">
        <SelectField
          id="rule-provider"
          label={t.provider}
          value={providerName}
          onChange={(e) => setProviderName(e.target.value)}
        >
          {providers.map((p) => (
            <option key={p.name} value={p.name}>
              {p.display_name}
            </option>
          ))}
        </SelectField>
        <SelectField
          id="rule-source"
          label={t.source}
          value={source}
          onChange={(e) => setSource(e.target.value as RuleSource)}
        >
          {sources.map((s) => (
            <option key={s} value={s}>
              {t.sources[s]}
            </option>
          ))}
        </SelectField>
        <Field
          id="rule-value"
          label={t.value}
          hint={t.valueHints[source]}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          className="font-mono"
          error={errors.value}
        />
        <SelectField
          id="rule-grant"
          label={t.grant}
          value={grant}
          onChange={(e) => setGrant(e.target.value as RuleGrant)}
        >
          {GRANTS.map((g) => (
            <option key={g} value={g}>
              {t.grants[g]}
            </option>
          ))}
        </SelectField>
        {isLibraryGrant(grant) && (
          <SelectField
            id="rule-scope"
            label={t.scope}
            value={chosen ? "chosen" : "every"}
            onChange={(e) => setChosen(e.target.value === "chosen")}
          >
            <option value="every">{t.everyLibrary}</option>
            <option value="chosen">{t.chosen}</option>
          </SelectField>
        )}
        {scoped && (
          <div>
            <LibraryCombobox
              multiple
              label={t.libraries}
              hint={t.librariesHint}
              query={ruleLibrariesQueryOptions}
              value={libraries}
              onChange={(ids) => {
                setLibraries(ids);
                if (ids.length > 0) setErrors(({ libraries: _, ...rest }) => rest);
              }}
            />
            {errors.libraries && (
              <p
                id="rule-libraries-error"
                role="alert"
                className="mt-2 text-small font-medium text-destructive"
              >
                {errors.libraries}
              </p>
            )}
          </div>
        )}
      </div>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="ghost" aria-disabled={pending} onClick={() => !pending && onDone()}>
          {c.cancel}
        </Button>
        <Button type="submit" pending={pending}>
          {t.submit}
        </Button>
      </div>
    </form>
  );
}
