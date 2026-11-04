import { Plus, X } from "lucide-react";
import { useRef } from "react";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { MAX_TAG_RULES, type TagRuleDraft, validateRule } from "../model/add-library";

const textarea =
  "min-h-24 w-full rounded-md border border-input bg-secondary px-3 py-2.5 font-mono text-[15px] leading-6 outline-none transition-[border-color,box-shadow] duration-150 placeholder:text-muted-foreground/80 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 aria-invalid:border-destructive";

interface PathsProps {
  include: string;
  exclude: string;
  error: string | undefined;
  onInclude: (v: string) => void;
  onExclude: (v: string) => void;
}

export function PathFields({ include, exclude, error, onInclude, onExclude }: PathsProps) {
  const described = ["paths-hint", error && "paths-error"].filter(Boolean).join(" ");
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="include" className="text-sm font-medium">
          Only these paths
        </label>
        <textarea
          id="include"
          value={include}
          rows={3}
          spellCheck={false}
          autoComplete="off"
          placeholder={"docs/\nREADME.md"}
          aria-invalid={error ? true : undefined}
          aria-describedby={described}
          onChange={(e) => onInclude(e.target.value)}
          className={textarea}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor="exclude" className="text-sm font-medium">
          Leave out
        </label>
        <textarea
          id="exclude"
          value={exclude}
          rows={2}
          spellCheck={false}
          autoComplete="off"
          placeholder="docs/internal/**"
          aria-invalid={error ? true : undefined}
          aria-describedby={described}
          onChange={(e) => onExclude(e.target.value)}
          className={textarea}
        />
        <p id="paths-hint" className="text-sm text-muted-foreground">
          One per line, relative to the repository root: a folder (<code>docs/</code>), a file or a
          glob (<code>**/*.mdx</code>). Empty means every Markdown file. Leaving a path out always
          wins.
        </p>
        {error && (
          <p id="paths-error" className="fade-in text-sm font-medium text-destructive">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

interface RulesProps {
  rules: readonly TagRuleDraft[];
  /** Show per-field messages once the user has tried to submit. */
  showErrors: boolean;
  error: string | undefined;
  onChange: (rules: TagRuleDraft[]) => void;
}

export function TagRules({ rules, showErrors, error, onChange }: RulesProps) {
  const next = useRef(rules.reduce((n, r) => Math.max(n, r.key + 1), 0));
  const set = (key: number, patch: Partial<TagRuleDraft>) =>
    onChange(rules.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1.5 text-sm font-medium">Tags by path</legend>
      <p id="tags-hint" className="text-sm text-muted-foreground">
        Give articles a tag by where they live, so agents can filter by it. Added to the tags in
        each article's front matter.
      </p>
      {rules.length > 0 && (
        <ul className="flex flex-col gap-3">
          {rules.map((rule, i) => {
            const problem = showErrors ? validateRule(rule) : {};
            return (
              <li key={rule.key} className="flex items-start gap-2">
                <div className="grid min-w-0 flex-1 gap-2 sm:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
                  <div>
                    <label htmlFor={`rule-path-${rule.key}`} className="sr-only">
                      Path for tag rule {i + 1}
                    </label>
                    <Input
                      id={`rule-path-${rule.key}`}
                      value={rule.pattern}
                      placeholder="docs/api/**"
                      spellCheck={false}
                      autoComplete="off"
                      aria-invalid={problem.pattern ? true : undefined}
                      aria-describedby={problem.pattern ? `rule-path-${rule.key}-error` : undefined}
                      onChange={(e) => set(rule.key, { pattern: e.target.value })}
                      className="font-mono text-[15px]"
                    />
                    {problem.pattern && (
                      <p
                        id={`rule-path-${rule.key}-error`}
                        className="fade-in mt-1 text-sm font-medium text-destructive"
                      >
                        {problem.pattern}
                      </p>
                    )}
                  </div>
                  <div>
                    <label htmlFor={`rule-tag-${rule.key}`} className="sr-only">
                      Tag for rule {i + 1}
                    </label>
                    <Input
                      id={`rule-tag-${rule.key}`}
                      value={rule.tag}
                      placeholder="api"
                      spellCheck={false}
                      autoComplete="off"
                      aria-invalid={problem.tag ? true : undefined}
                      aria-describedby={problem.tag ? `rule-tag-${rule.key}-error` : undefined}
                      onChange={(e) => set(rule.key, { tag: e.target.value })}
                      className="font-mono text-[15px]"
                    />
                    {problem.tag && (
                      <p
                        id={`rule-tag-${rule.key}-error`}
                        className="fade-in mt-1 text-sm font-medium text-destructive"
                      >
                        {problem.tag}
                      </p>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  aria-label={`Remove tag rule ${i + 1}`}
                  onClick={() => onChange(rules.filter((r) => r.key !== rule.key))}
                  className="grid size-11 shrink-0 place-items-center rounded-md text-muted-foreground outline-none transition-colors duration-150 hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97]"
                >
                  <X aria-hidden="true" className="size-4" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {error && (
        <p id="tags-error" className="fade-in text-sm font-medium text-destructive">
          {error}
        </p>
      )}
      <div>
        <Button
          id="add-rule"
          variant="ghost"
          className="-ml-3"
          disabled={rules.length >= MAX_TAG_RULES}
          aria-describedby="tags-hint"
          onClick={() => {
            const key = next.current++;
            onChange([...rules, { key, pattern: "", tag: "" }]);
            requestAnimationFrame(() => document.getElementById(`rule-path-${key}`)?.focus());
          }}
        >
          <Plus aria-hidden="true" className="size-4" />
          Add a tag rule
        </Button>
      </div>
    </fieldset>
  );
}
