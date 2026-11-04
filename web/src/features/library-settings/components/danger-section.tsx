import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { Button } from "@/shared/ui/button";
import { refreshLibraries, removeLibrary } from "../api/settings";
import { explainRemove, isAlreadyGone, type SettingsLibrary } from "../model/settings";
import { danger } from "./styles";
import { TypedConfirm } from "./typed-confirm";

/** Removing the whole library: kept apart at the bottom, and behind its ID typed in full. */
export function DangerSection({
  owner,
  repo,
  library,
}: {
  owner: string;
  repo: string;
  library: SettingsLibrary;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const count = library.versions.length;

  const remove = useMutation({
    mutationFn: () =>
      removeLibrary(owner, repo).catch((error: unknown) => {
        if (isAlreadyGone(error)) return undefined;
        throw error;
      }),
    onSuccess: async () => {
      refreshLibraries(queryClient);
      // The page it was on is gone: nothing to return focus to, so leave for the list.
      setOpen(false);
      await navigate({ to: "/" });
    },
    onError: () => refreshLibraries(queryClient),
  });

  return (
    <section aria-labelledby="danger-heading" className="mt-12 border-t border-border pt-10">
      <h2 id="danger-heading" className="font-serif text-2xl font-semibold tracking-tight">
        Remove library
      </h2>
      <p className="mt-1.5 max-w-prose text-muted-foreground">
        Take{" "}
        <span className="font-mono text-[0.95em] text-foreground [overflow-wrap:anywhere]">
          {library.id}
        </span>{" "}
        out of ExactDocs
        {count > 0 && ` with its ${count === 1 ? "version" : `${count} versions`}`}. The repository
        itself is never touched.
      </p>
      <div className="mt-5">
        <Button
          ref={button}
          type="button"
          onClick={() => {
            remove.reset();
            setOpen(true);
          }}
          className={danger}
        >
          Remove library…
        </Button>
      </div>
      <TypedConfirm
        open={open}
        onOpenChange={setOpen}
        title={`Remove ${library.id}?`}
        consequence={
          <>
            {count > 0 ? "All its versions and their articles leave" : "It leaves"} browse, search
            and agents right away. Text that other libraries share is kept. This can't be undone,
            but you can add the library again.
          </>
        }
        phrase={library.id}
        confirmLabel="Remove library"
        pending={remove.isPending}
        problem={remove.isError ? explainRemove(remove.error, "this library") : undefined}
        onConfirm={() => remove.mutate()}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          button.current?.focus();
        }}
      />
    </section>
  );
}
