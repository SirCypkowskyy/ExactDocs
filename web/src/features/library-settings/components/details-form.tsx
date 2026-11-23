import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { useLanguage } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Field, TextareaField } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { refreshLibraries, saveDetails } from "../api/settings";
import { pageMessages } from "../messages/page";
import {
  type Activity,
  changedFields,
  type DetailsDraft,
  explainSave,
  MAX_DESCRIPTION,
  type Problem,
  type SettingsLibrary,
  validateDetails,
} from "../model/settings";
import { useReportDirty } from "./dirty";
import { SaveRow } from "./save-row";

interface Props {
  owner: string;
  repo: string;
  library: SettingsLibrary;
  activity: Activity;
  onStart: () => void;
}

/** Title and description. Only the fields that changed are sent. */
export function DetailsForm({ owner, repo, library, activity, onStart }: Props) {
  const language = useLanguage();
  const t = pageMessages[language].details;
  const queryClient = useQueryClient();
  // Only what the person typed is state; an untouched field shows what the library has.
  const [edits, setEdits] = useState<Partial<DetailsDraft>>({});
  const title = edits.title ?? library.title;
  const description = edits.description ?? library.description;
  const [errors, setErrors] = useState<{
    title?: string | undefined;
    description?: string | undefined;
  }>({});
  const [problem, setProblem] = useState<Problem>();
  const [saved, setSaved] = useState(false);

  const draft = { title, description };
  const patch = changedFields(library, draft);
  const unchanged = Object.keys(patch).length === 0;
  useReportDirty("details", !unchanged);

  const save = useMutation({
    mutationFn: () => saveDetails(owner, repo, patch),
    onSuccess: () => {
      setSaved(true);
      setProblem(undefined);
      toast.success(t.savedToast);
      refreshLibraries(queryClient);
    },
    onError: (error) => {
      const p = explainSave(error, language);
      if (p.field) {
        setErrors({ [p.field]: p.message });
        document.getElementById(p.field)?.focus();
      } else {
        setProblem(p);
      }
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (save.isPending || unchanged) return;
    const found = validateDetails(draft, language);
    setErrors(found);
    setProblem(undefined);
    if (found.title || found.description) {
      document.getElementById(found.title ? "title" : "description")?.focus();
      return;
    }
    setSaved(false);
    onStart();
    save.mutate();
  }

  const edit = (field: "title" | "description") => (value: string) => {
    setEdits((e) => ({ ...e, [field]: value }));
    setSaved(false);
    setErrors((e) => ({ ...e, [field]: undefined }));
  };

  return (
    <form onSubmit={submit} noValidate>
      <FormAlert id="details-alert" message={problem?.message} link={problem?.link} />
      <div className="flex flex-col gap-5">
        <Field
          id="title"
          label={t.titleLabel}
          autoComplete="off"
          value={title}
          error={errors.title}
          hint={t.titleHint}
          onChange={(e) => edit("title")(e.target.value)}
        />
        <TextareaField
          id="description"
          label={t.descriptionLabel}
          value={description}
          error={errors.description}
          hint={t.descriptionHint(MAX_DESCRIPTION)}
          onChange={(e) => edit("description")(e.target.value)}
        />
        {/* Said when it matters: once something is edited. */}
        {/* The room is kept, so the note fading in moves nothing (only opacity changes). */}
        <div
          inert={unchanged}
          className={cn(
            "transition-opacity duration-(--dur) ease-(--ease-out) motion-reduce:transition-none",
            unchanged && "opacity-0",
          )}
        >
          <p className="flex items-start gap-2 text-body text-muted-foreground">
            <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-route" />
            <span>{t.editedNote}</span>
          </p>
        </div>
        <SaveRow
          label={t.save}
          pending={save.isPending}
          blocked={save.isPending || unchanged}
          saved={saved && unchanged && activity.by === "details"}
        />
      </div>
    </form>
  );
}
