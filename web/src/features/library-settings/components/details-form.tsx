import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Button } from "@/shared/ui/button";
import { Field, TextareaField } from "@/shared/ui/field";
import { FormAlert } from "@/shared/ui/form-alert";
import { refreshLibraries, saveDetails } from "../api/settings";
import {
  changedFields,
  explainSave,
  MAX_DESCRIPTION,
  MAX_TITLE,
  type Problem,
  type SettingsLibrary,
  validateDetails,
} from "../model/settings";

interface Props {
  owner: string;
  repo: string;
  library: SettingsLibrary;
}

/** Title and description. Only the fields that changed are sent. */
export function DetailsForm({ owner, repo, library }: Props) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState(library.title);
  const [description, setDescription] = useState(library.description);
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
        document.getElementById(p.field === "title" ? "title" : "description")?.focus();
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
    save.mutate();
  }

  const edit = (set: (v: string) => void, field: "title" | "description") => (value: string) => {
    set(value);
    setSaved(false);
    setErrors((e) => ({ ...e, [field]: undefined }));
  };

  return (
    <form onSubmit={submit} noValidate className="mt-6 flex flex-col gap-5">
      <FormAlert id="details-alert" message={problem?.message} link={problem?.link} />
      <Field
        id="title"
        label="Title"
        autoComplete="off"
        maxLength={MAX_TITLE + 50}
        value={title}
        error={errors.title}
        hint="Shown in the library list and as the page heading."
        onChange={(e) => edit(setTitle, "title")(e.target.value)}
      />
      <TextareaField
        id="description"
        label="Description"
        value={description}
        error={errors.description}
        hint={`Shown on the library page. Up to ${MAX_DESCRIPTION} characters, and it can be empty.`}
        onChange={(e) => edit(setDescription, "description")(e.target.value)}
      />
      <p className="text-sm text-muted-foreground">
        A field you change here stays as you wrote it when the library is imported again. Until then
        it follows the repository's README.
      </p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button
          type="submit"
          aria-disabled={save.isPending || unchanged}
          aria-busy={save.isPending}
          className="min-w-32 aria-disabled:cursor-default"
        >
          {save.isPending ? "Saving" : "Save changes"}
        </Button>
        <p role="status" className="min-h-5 text-sm text-muted-foreground">
          {saved && unchanged && <span className="fade-in">Saved.</span>}
        </p>
      </div>
    </form>
  );
}
