import { useNavigate } from "@tanstack/react-router";

export interface SearchPatch {
  q?: string | undefined;
  tags?: string | undefined;
  match?: "all" | undefined;
}

/** Changes the search part of the URL in place (no history entry per keystroke), keeping the rest. */
export function useSearchNav(owner: string, repo: string) {
  const navigate = useNavigate();
  return (patch: SearchPatch) =>
    navigate({
      to: "/libraries/$owner/$repo",
      params: { owner, repo },
      search: (prev) => ({ ...prev, ...patch }),
      replace: true,
    });
}
