import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { Button } from "@/shared/ui/button";
import { forgetLibrary, refreshLibraries, removeLibrary } from "../api/settings";
import { explainRemove, isAlreadyGone, type SettingsLibrary } from "../model/settings";
import { danger } from "./styles";
import { TypedConfirm } from "./typed-confirm";

const LISTED = 5;

/** Removing the whole library: kept apart at the bottom, and behind its ID typed in full. */
export function DangerSection({
  owner,
  repo,
  library,
  onStart,
}: {
  owner: string;
  repo: string;
  library: SettingsLibrary;
  onStart: () => void;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const refs = library.versions.map((v) => v.ref);
  const count = refs.length;

  const remove = useMutation({
    mutationFn: () =>
      removeLibrary(owner, repo).catch((error: unknown) => {
        if (isAlreadyGone(error)) return undefined;
        throw error;
      }),
    onSuccess: async () => {
      // Leave first: while this page is mounted, dropping the library's cache would refetch it.
      setOpen(false);
      await navigate({ to: "/" });
      forgetLibrary(queryClient, owner, repo);
    },
    onError: () => refreshLibraries(queryClient),
  });

  return (
    <section
      aria-labelledby="danger-heading"
      className="mt-16 rounded-lg border border-destructive/30 p-5"
    >
      <h2
        id="danger-heading"
        className="text-xl font-semibold tracking-tight text-destructive [scroll-margin-top:1.5rem]"
      >
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
            onStart();
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
        title={
          <>
            Remove <span className="font-mono text-[0.9em]">{library.id}</span>?
          </>
        }
        loss={
          count > 0
            ? `${count === 1 ? "Its version" : `All ${count} versions`} (${refs.slice(0, LISTED).join(", ")}${count > LISTED ? `, and ${count - LISTED} more` : ""}) and their articles disappear from browse, search and agents now.`
            : "The library disappears from browse, search and agents now."
        }
        safe="Nothing in the repository changes. Content that other libraries share stays available. You can add the library again."
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
