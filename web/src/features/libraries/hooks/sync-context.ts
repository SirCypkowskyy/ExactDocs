import { createContext } from "react";
import type { SyncStates } from "./use-libraries";

/** Every library's sync, from one request: cells read it here, so a poll never rebuilds the columns. */
export const SyncContext = createContext<SyncStates | null>(null);
