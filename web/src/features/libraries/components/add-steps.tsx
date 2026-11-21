import { Check } from "lucide-react";
import { cn } from "@/shared/lib/utils";

/** Where the person is in adding a library; each phase is one step further along. */
export type AddPhase = "check" | "choose" | "import" | "done" | "failed";

const STEPS = [
  { label: "Check repository", hint: "Is it reachable?" },
  { label: "Choose version", hint: "Branch, tag or commit" },
  { label: "Choose files", hint: "Optional" },
  { label: "Import", hint: "Reads and indexes it" },
] as const;

/** The step the phase is on (0-based); past the last one means everything is done. */
const CURRENT: Record<AddPhase, number> = { check: 0, choose: 1, import: 3, done: 4, failed: 3 };

type State = "done" | "current" | "upcoming" | "failed";

function stateOf(index: number, phase: AddPhase): State {
  if (phase === "failed" && index === 3) return "failed";
  if (index < CURRENT[phase]) return "done";
  return index === CURRENT[phase] ? "current" : "upcoming";
}

/**
 * The steps of adding a library as a station line (DESIGN.md, The idea): a ring per step, filled
 * for the one you are on, a tick for the ones behind. On a phone it folds to one line and a bar.
 */
export function AddSteps({ phase }: { phase: AddPhase }) {
  const current = Math.min(CURRENT[phase], STEPS.length - 1);
  return (
    <>
      <div className="mb-6 lg:hidden">
        <p className="text-body">
          <span className="text-muted-foreground tabular-nums">
            Step {current + 1} of {STEPS.length}:{" "}
          </span>
          <span className="font-medium">{STEPS[current]?.label}</span>
        </p>
        <div aria-hidden="true" className="mt-2 flex gap-1">
          {STEPS.map((step, i) => (
            <span
              key={step.label}
              className={cn(
                "h-1 flex-1 rounded-full transition-colors duration-(--dur) ease-(--ease-out)",
                stateOf(i, phase) === "upcoming" ? "bg-secondary" : "bg-route",
                stateOf(i, phase) === "failed" && "bg-destructive",
              )}
            />
          ))}
        </div>
      </div>
      <nav aria-label="Steps" className="hidden lg:block">
        <ol className="sticky top-17">
          {STEPS.map((step, i) => {
            const state = stateOf(i, phase);
            return (
              <li
                key={step.label}
                aria-current={state === "current" ? "step" : undefined}
                className="relative pb-6 pl-8 last:pb-0 before:absolute before:top-2 before:bottom-0 before:left-[9px] before:w-0.5 before:bg-rule last:before:hidden data-[state=done]:before:bg-route"
                data-state={state}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "absolute top-0.5 left-0 flex size-5 items-center justify-center rounded-full border-2 bg-background transition-colors duration-(--dur) ease-(--ease-out)",
                    state === "upcoming" && "border-input",
                    state === "current" && "border-route",
                    state === "done" && "border-route bg-route text-white",
                    state === "failed" && "border-destructive bg-destructive text-white",
                  )}
                >
                  {state === "done" && <Check className="size-3" strokeWidth={3} />}
                  {state === "current" && <span className="size-2 rounded-full bg-route" />}
                </span>
                <p
                  className={cn(
                    "text-body",
                    state === "upcoming" ? "text-muted-foreground" : "font-medium",
                  )}
                >
                  {step.label}
                  <span className="sr-only">
                    {state === "done" ? " (done)" : state === "failed" ? " (failed)" : ""}
                  </span>
                </p>
                <p className="text-small text-muted-foreground">{step.hint}</p>
              </li>
            );
          })}
        </ol>
      </nav>
    </>
  );
}
