import { useState } from "react";
import {
  type Credential,
  type CredentialDraft,
  credentialKindFor,
  credentialOf,
  EMPTY_CREDENTIAL,
  validateCredential,
} from "@/shared/lib/credentials";
import { type Language, useLanguage, useMessages } from "@/shared/lib/i18n";
import { addMessages } from "../messages/add";

/** The credential to send with a check of `url`, or why the boxes can't be sent. */
function credentialToSend(
  open: boolean,
  url: string,
  draft: CredentialDraft,
  needsAddress: string,
  language: Language,
): { credential?: Credential; error?: string } {
  if (!open) return {};
  const kind = credentialKindFor(url);
  if (!kind) return { error: needsAddress };
  const error = validateCredential(kind, draft, language);
  if (error) return { error };
  const credential = credentialOf(kind, draft);
  return credential ? { credential } : {};
}

/**
 * "This repository is private" and its token or key. The secret lives in this state only (and in
 * what a check passed with): never a query, storage or a URL.
 */
export function usePrivateAccess() {
  const t = useMessages(addMessages).address;
  const language = useLanguage();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<CredentialDraft>(EMPTY_CREDENTIAL);
  return {
    open,
    draft,
    /** Closing the box forgets what was typed in it. */
    setOpen: (next: boolean) => {
      setOpen(next);
      if (!next) setDraft(EMPTY_CREDENTIAL);
    },
    setDraft,
    /** The library holds it now (stored encrypted): let go of the typed copy. */
    forget: () => setDraft(EMPTY_CREDENTIAL),
    reset: () => {
      setOpen(false);
      setDraft(EMPTY_CREDENTIAL);
    },
    toSend: (url: string) => credentialToSend(open, url, draft, t.credentialNeedsAddress, language),
  };
}
