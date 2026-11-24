import { createContext } from "react";

/**
 * Each library's `logo` (its version) by ID, from the list the page already loaded for its
 * picker, so a result shows its library's logo without asking for anything else.
 */
export const LibraryLogos = createContext<ReadonlyMap<string, string | null>>(new Map());
