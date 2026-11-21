import { sendJson } from "@/shared/lib/http";
import type { Job } from "../model/library";

/** Cancel a queued or running job: a queued one never starts, a running one stops after its step. */
export const cancelJob = (id: string) =>
  sendJson<Job>("POST", `/v1/jobs/${encodeURIComponent(id)}/cancel`);
