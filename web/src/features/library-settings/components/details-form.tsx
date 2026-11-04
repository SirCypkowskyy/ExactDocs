import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Info } from "lucide-react";
import { type FormEvent, useState } from "react";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { Field, TextareaField } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { refreshLibraries, saveDetails } from "../api/settings";
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

interface Props {
  owner: string;
  repo: string;
  library: SettingsLibrary;
  activity: Activity;
  onStart: () => void;
}

/** Title and description. Only the fields that changed are sent. */
export function DetailsForm({ owner, repo, library, activity, onStart }: Props) {
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

  const save = useMutation({
    mutationFn: () => saveDetails(owner, repo, patch),
    onSuccess: () => {
      setSaved(true);
      setProblem(undefined);
      refreshLibraries(queryClient);
    },
    onError: (error) => {
      const p = explainSave(error);
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
    const found = validateDetails(draft);
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
    <form onSubmit={submit} noValidate className="mt-4">
      <FormAlert id="details-alert" message={problem?.message} link={problem?.link} />
      <div className="flex flex-col gap-5">
        <Field
          id="title"
          label="Title"
          autoComplete="off"
          value={title}
          error={errors.title}
          hint="Shown in the library list and as the page heading."
          onChange={(e) => edit("title")(e.target.value)}
        />
        <TextareaField
          id="description"
          label="Description"
          value={description}
          error={errors.description}
          hint={`Shown on the library page. Up to ${MAX_DESCRIPTION} characters, and it can be empty.`}
          onChange={(e) => edit("description")(e.target.value)}
        />
        {/* Said when it matters: once something is edited. */}
        <div
          className={cn(
            "grid transition-[grid-template-rows] duration-200 ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none",
            unchanged ? "grid-rows-[0fr]" : "grid-rows-[1fr]",
          )}
        >
          <div className="overflow-hidden" inert={unchanged}>
            <p className="flex items-start gap-2 text-sm text-muted-foreground">
              <Info aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-mark" />
              <span>
                Edited fields are kept when the library is re-imported. Fields you leave alone keep
                following the repository's README.
              </span>
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button
            type="submit"
            aria-disabled={save.isPending || unchanged}
            aria-busy={save.isPending}
            className="min-w-32 aria-disabled:cursor-default"
          >
            {save.isPending ? "Saving" : "Save changes"}
          </Button>
          <p role="status" className="min-h-5 text-sm">
            {saved && unchanged && activity.by === "details" && (
              <span className="fade-in inline-flex items-center gap-1.5">
                <Check aria-hidden="true" className="size-4 text-mark" />
                Saved.
              </span>
            )}
          </p>
        </div>
      </div>
    </form>
  );
}
