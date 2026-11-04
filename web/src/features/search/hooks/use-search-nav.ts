import { useNavigate } from "@tanstack/react-router";

export interface SearchPatch {
  q?: string | undefined;
  tags?: string | undefined;
  match?: "all" | undefined;
}

/**
 * Changes the search part of the URL and keeps the rest. Typing replaces the history entry (one
 * per keystroke would bury Back); a deliberate step (Enter, a tag, the any/all switch) pushes one,
 * so Back returns to the previous search.
 */
export function useSearchNav(owner: string, repo: string) {
  const navigate = useNavigate();
  return (patch: SearchPatch, mode: "replace" | "push" = "push") =>
    navigate({
      to: "/libraries/$owner/$repo",
      params: { owner, repo },
      search: (prev) => ({ ...prev, ...patch }),
      replace: mode === "replace",
    });
}
