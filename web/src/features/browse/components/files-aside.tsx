import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ChevronRight, FolderTree } from "lucide-react";
import { type ReactNode, useCallback, useState } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { tagsQueryOptions } from "@/shared/lib/tags-query";
import { cn } from "@/shared/lib/utils";
import { trigger } from "@/shared/ui/recipes";
import { TagChips } from "@/shared/ui/tag-chips";
import { messages } from "../messages";
import type { Version } from "../model/browse";
import { TreePane } from "./tree-pane";
import { VersionPicker } from "./version-picker";

interface FilesAsideProps {
  owner: string;
  repo: string;
  versions: readonly Version[];
  version: Version;
  /** The library's default version is pinned (`default_pinned`). */
  pinned: boolean;
  path: string | undefined;
  tags: string | undefined;
  /** The search box and its query, when the search slice is mounted. */
  searchBox?: ReactNode;
  q?: string | undefined;
  match?: "all" | undefined;
}

function FilesToggle({
  open,
  label,
  onToggle,
}: {
  open: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-controls="file-tree"
      onClick={onToggle}
      className={cn(trigger, "justify-start font-medium lg:hidden")}
    >
      <FolderTree aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
      <span title={label} className="truncate">
        {label}
      </span>
      <ChevronRight
        aria-hidden="true"
        className={cn(
          "ml-auto size-4 shrink-0 text-muted-foreground transition-transform duration-(--dur) ease-(--ease-out) motion-reduce:transition-none",
          open && "rotate-90",
        )}
      />
    </button>
  );
}

/**
 * The version picker, the tag filter and the file tree. On a phone the picker and a "Files"
 * button share a row, and the filter and tree fold behind that button.
 */
export function FilesAside({
  owner,
  repo,
  versions,
  version,
  pinned,
  path,
  tags: tagsParam,
  searchBox,
  q,
  match,
}: FilesAsideProps) {
  const t = useMessages(messages).tree;
  const navigate = useNavigate();
  // On a phone the tree starts open until an article is open; after that the reader decides.
  const [chosen, setChosen] = useState<boolean>();
  const filesOpen = chosen ?? (!path && !q);
  const counted = useQuery(
    tagsQueryOptions({ owner, repo, ref: version.ref, sha: version.commit_sha }),
  );

  const setTags = (next: string | undefined) =>
    navigate({
      to: "/libraries/$owner/$repo",
      params: { owner, repo },
      search: { version: version.ref, path, tags: next, q, match },
      replace: true,
    });
  // While searching the tree is only navigation: the search owns the tag filter (with its any/all),
  // so the tree is never narrower or wider than the results beside it.
  const treeTags = q ? undefined : tagsParam;
  const closeFiles = useCallback(() => setChosen(false), []);
  const name = path?.split("/").pop();
  const label = filesOpen || !name ? (path || q ? t.files : t.browseFiles) : name;

  return (
    <aside aria-label={t.files} className="flex min-w-0 flex-col gap-3 lg:sticky lg:top-17">
      {/* Two side by side while both fit 10rem; one above the other at a large text size (#576). */}
      <div
        data-tour="library-version"
        className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,10rem),1fr))] gap-2 lg:block"
      >
        <VersionPicker
          owner={owner}
          repo={repo}
          versions={versions}
          current={version}
          pinned={pinned}
          keep={{ path, tags: tagsParam, q, match }}
        />
        <FilesToggle open={filesOpen} label={label} onToggle={() => setChosen(!filesOpen)} />
      </div>
      {/* On a phone the box leads while searching: it is the one control the reader is using. */}
      {searchBox && (
        <div data-tour="library-search" className={cn(q && "max-lg:order-first")}>
          {searchBox}
        </div>
      )}
      <div
        id="file-tree"
        data-tour="library-files"
        className={cn("space-y-3", !filesOpen && "max-lg:hidden")}
      >
        {/* While searching, the search box carries its own filter (same `tags` param). */}
        {!q && (
          <TagChips
            facets={counted.data?.tags ?? []}
            value={tagsParam}
            loading={counted.isPending}
            truncated={counted.data?.truncated ?? false}
            onChange={setTags}
          />
        )}
        <div className="-mx-1 max-h-[min(70dvh,32rem)] overflow-y-auto overscroll-contain px-1 lg:max-h-[calc(100dvh-17rem)]">
          <TreePane
            key={treeTags ?? ""}
            target={{ owner, repo, ref: version.ref, sha: version.commit_sha }}
            tagsParam={treeTags}
            selected={path}
            onClearTags={() => setTags(undefined)}
            onOpen={closeFiles}
          />
        </div>
      </div>
    </aside>
  );
}
