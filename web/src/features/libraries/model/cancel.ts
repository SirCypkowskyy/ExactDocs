import { HttpError } from "@/shared/lib/http";
import type { progressMessages } from "../messages/progress";

type CancelMessages = (typeof progressMessages)["en"]["cancel"];

/** Why a cancel did not happen, in words (the jobs table's confirmation says the same). */
export function explainCancel(error: unknown, t: CancelMessages): string {
  if (!(error instanceof HttpError)) return t.offline;
  if (error.status === 403) return t.forbidden;
  if (error.status === 409) return t.ended;
  return t.server(error.status);
}
