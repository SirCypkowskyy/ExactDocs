// The file selection and tag rules of a library, as the add form and the settings page show them.
import { Plus, X } from "lucide-react";
import {
  badPathBox,
  MAX_TAG_RULES,
  type TagRuleDraft,
  validateRule,
} from "@/shared/lib/path-selection";
import { useFocusAfterRender } from "@/shared/lib/use-focus-after-render";
import { Button } from "./button";
import { Input } from "./input";
import { control } from "./recipes";

const textarea = `${control} min-h-24 scroll-mt-6 px-3 py-2 font-mono leading-6`;
const errorText = "fade-in text-small font-medium text-destructive";

interface PathsProps {
  include: string;
  exclude: string;
  error: string | undefined;
  onInclude: (v: string) => void;
  onExclude: (v: string) => void;
}

function PathError({ id, message }: { id: string; message: string | undefined }) {
  return message ? (
    <p id={id} className={errorText}>
      {message}
    </p>
  ) : null;
}

/** The include and exclude boxes: one pattern per line. */
export function PathFields({ include, exclude, error, onInclude, onExclude }: PathsProps) {
  // A local mistake sits under the box it is in. A server refusal cannot say which box, so its
  // message goes under the last one and marks both.
  const box = error ? badPathBox(include, exclude) : undefined;
  const bad = (name: "include" | "exclude") => Boolean(error) && (box ? box === name : true);
  const own = (name: "include" | "exclude") => (error && box === name ? error : undefined);
  const shared = error && !box ? error : undefined;
  const describe = (name: "include" | "exclude") =>
    [own(name) && `${name}-error`, shared && "paths-error", "paths-hint"].filter(Boolean).join(" ");
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <label htmlFor="include" className="text-body font-medium">
          Only these paths
        </label>
        <textarea
          id="include"
          value={include}
          rows={3}
          spellCheck={false}
          autoComplete="off"
          placeholder={"docs/\nREADME.md"}
          aria-invalid={bad("include") ? true : undefined}
          aria-describedby={describe("include")}
          onChange={(e) => onInclude(e.target.value)}
          className={textarea}
        />
        <PathError id="include-error" message={own("include")} />
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor="exclude" className="text-body font-medium">
          Leave out
        </label>
        <textarea
          id="exclude"
          value={exclude}
          rows={2}
          spellCheck={false}
          autoComplete="off"
          placeholder="docs/internal/**"
          aria-invalid={bad("exclude") ? true : undefined}
          aria-describedby={describe("exclude")}
          onChange={(e) => onExclude(e.target.value)}
          className={textarea}
        />
        <PathError id="exclude-error" message={own("exclude")} />
        <PathError id="paths-error" message={shared} />
        <p id="paths-hint" className="text-body text-muted-foreground">
          One per line, relative to the repository root: a folder (<code>docs/</code>), a file or a
          glob (<code>**/*.mdx</code>). Empty means every Markdown and reStructuredText (.rst) file.
          A .txt file needs a path that names .txt. Leaving a path out always wins.
        </p>
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

const label = "mb-1 block text-body text-muted-foreground md:sr-only";

/** Tag rules as rows of path and tag, added and removed one at a time. */
export function TagRules({ rules, showErrors, error, onChange }: RulesProps) {
  const set = (key: number, patch: Partial<TagRuleDraft>) =>
    onChange(rules.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const full = rules.length >= MAX_TAG_RULES;
  const focusAfterRender = useFocusAfterRender();
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1.5 text-body font-medium">Tags by path</legend>
      <p id="tags-hint" className="text-body text-muted-foreground">
        Give articles a tag by where they live, so agents can filter by it. Added to the tags in
        each article's front matter.
        {full && ` You can have up to ${MAX_TAG_RULES} rules.`}
      </p>
      {rules.length > 0 && (
        <>
          <div
            aria-hidden="true"
            className="hidden gap-2 pr-[3.25rem] text-body text-muted-foreground md:grid md:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]"
          >
            <span>Path</span>
            <span>Tag</span>
          </div>
          <ul className="flex flex-col gap-5 md:gap-3">
            {rules.map((rule, i) => {
              const problem = showErrors ? validateRule(rule) : {};
              return (
                <li key={rule.key} className="flex items-start gap-2">
                  <div className="grid min-w-0 flex-1 gap-x-2 gap-y-2 md:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
                    <div>
                      <label htmlFor={`rule-path-${rule.key}`} className={label}>
                        Path for tag rule {i + 1}
                      </label>
                      <Input
                        id={`rule-path-${rule.key}`}
                        value={rule.pattern}
                        placeholder="docs/api/**"
                        spellCheck={false}
                        autoComplete="off"
                        aria-invalid={problem.pattern ? true : undefined}
                        aria-describedby={
                          problem.pattern ? `rule-path-${rule.key}-error` : undefined
                        }
                        onChange={(e) => set(rule.key, { pattern: e.target.value })}
                        className="scroll-mt-6 font-mono"
                      />
                    </div>
                    <div>
                      <label htmlFor={`rule-tag-${rule.key}`} className={label}>
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
                        className="scroll-mt-6"
                      />
                    </div>
                    {/* One message per rule, across both columns, so it never wraps in a half. */}
                    {(problem.pattern || problem.tag) && (
                      <div className="grid gap-1 md:col-span-2">
                        {problem.pattern && (
                          <p id={`rule-path-${rule.key}-error`} className={errorText}>
                            {problem.pattern}
                          </p>
                        )}
                        {problem.tag && (
                          <p id={`rule-tag-${rule.key}-error`} className={errorText}>
                            {problem.tag}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    aria-label={`Remove tag rule ${i + 1}`}
                    title={`Remove tag rule ${i + 1}`}
                    onClick={() => onChange(rules.filter((r) => r.key !== rule.key))}
                    className="grid size-11 shrink-0 place-items-center rounded-md text-muted-foreground outline-none transition-colors duration-(--dur-fast) hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] max-md:mt-6"
                  >
                    <X aria-hidden="true" className="size-4" />
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}
      {error && (
        <p id="tags-error" className={errorText}>
          {error}
        </p>
      )}
      <div>
        {/* aria-disabled, not disabled: the button keeps focus and says why in the hint. */}
        <Button
          id="add-rule"
          variant="ghost"
          className="-ml-3"
          aria-disabled={full}
          aria-describedby="tags-hint"
          onClick={() => {
            if (full) return;
            const key = rules.reduce((n, r) => Math.max(n, r.key + 1), 0);
            onChange([...rules, { key, pattern: "", tag: "" }]);
            focusAfterRender(() => document.getElementById(`rule-path-${key}`));
          }}
        >
          <Plus aria-hidden="true" className="size-4" />
          Add a tag rule
        </Button>
      </div>
    </fieldset>
  );
}
