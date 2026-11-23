import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { useLanguage } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";
import { forgetLibrary, refreshLibraries, removeLibrary } from "../api/settings";
import { errorMessages } from "../messages/errors";
import { pageMessages } from "../messages/page";
import { explainRemove, isAlreadyGone, listed, type SettingsLibrary } from "../model/settings";
import { SettingsSection } from "./settings-section";
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
  const language = useLanguage();
  const t = pageMessages[language];
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
      toast.success(t.danger.removedToast(library.id), {
        description: t.danger.removedDescription,
      });
      forgetLibrary(queryClient, owner, repo);
    },
    onError: () => refreshLibraries(queryClient),
  });

  return (
    <SettingsSection id="danger" title={t.sections.danger} description={t.danger.description}>
      <div className="rounded-lg border border-destructive/30 p-5">
        <p className="text-body">
          {t.danger.body(
            <span className="font-mono text-small [overflow-wrap:anywhere]">{library.id}</span>,
            count,
          )}
        </p>
        <div className="mt-4">
          <Button
            ref={button}
            type="button"
            variant="destructive"
            onClick={() => {
              remove.reset();
              onStart();
              setOpen(true);
            }}
          >
            {t.danger.button}
          </Button>
        </div>
      </div>
      <TypedConfirm
        open={open}
        onOpenChange={setOpen}
        title={t.confirm.title(<span className="font-mono">{library.id}</span>)}
        loss={
          count > 0
            ? t.danger.lossVersions(count, listed(refs, language, LISTED))
            : t.danger.lossLibrary
        }
        safe={t.danger.safe}
        phrase={library.id}
        confirmLabel={t.danger.confirm}
        pending={remove.isPending}
        problem={
          remove.isError
            ? explainRemove(remove.error, errorMessages[language].remove.library, language)
            : undefined
        }
        onConfirm={() => remove.mutate()}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          button.current?.focus();
        }}
      />
    </SettingsSection>
  );
}
