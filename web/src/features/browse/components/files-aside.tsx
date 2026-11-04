import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ChevronRight, FolderTree } from "lucide-react";
import { type ReactNode, useCallback, useState } from "react";
import { cn } from "@/shared/lib/utils";
import { tagsQueryOptions } from "../api/browse-queries";
import { parseTags, type Version, visibleTags } from "../model/browse";
import { TagFilter } from "./tag-filter";
import { TreePane } from "./tree-pane";
import { VersionPicker } from "./version-picker";

interface FilesAsideProps {
  owner: string;
  repo: string;
  versions: readonly Version[];
  version: Version;
  path: string | undefined;
  tags: string | undefined;
  /** The search box and its query, when the search slice is mounted. */
  searchBox?: ReactNode;
  q?: string | undefined;
  match?: "all" | undefined;
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
  path,
  tags: tagsParam,
  searchBox,
  q,
  match,
}: FilesAsideProps) {
  const navigate = useNavigate();
  const tags = parseTags(tagsParam);
  // On a phone the tree starts open until an article is open; after that the reader decides.
  const [chosen, setChosen] = useState<boolean>();
  const filesOpen = chosen ?? (!path && !q);
  const counted = useQuery(
    tagsQueryOptions({ owner, repo, ref: version.ref, sha: version.commit_sha }),
  );
  const offered = visibleTags(tags, counted.data?.tags.map((t) => t.tag) ?? []);

  const setTags = (next: string | undefined) =>
    navigate({
      to: "/libraries/$owner/$repo",
      params: { owner, repo },
      search: { version: version.ref, path, tags: next, q, match },
      replace: true,
    });
  const closeFiles = useCallback(() => setChosen(false), []);
  const name = path?.split("/").pop();

  return (
    <aside aria-label="Files" className="min-w-0 space-y-3 lg:sticky lg:top-4">
      <div className="grid grid-cols-2 gap-2 lg:block">
        <VersionPicker
          owner={owner}
          repo={repo}
          versions={versions}
          current={version}
          keep={{ path, tags: tagsParam, q, match }}
        />
        <button
          type="button"
          aria-expanded={filesOpen}
          aria-controls="file-tree"
          onClick={() => setChosen(!filesOpen)}
          className="flex h-11 min-w-0 cursor-pointer items-center gap-2 rounded-md bg-secondary px-3 text-sm font-medium outline-none ring-1 ring-inset ring-border transition-transform duration-150 focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.98] lg:hidden"
        >
          <FolderTree aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate">
            {filesOpen || !name ? (path ? "Files" : "Browse files") : name}
          </span>
          <ChevronRight
            aria-hidden="true"
            className={cn(
              "ml-auto size-4 shrink-0 text-muted-foreground transition-transform duration-150 motion-reduce:transition-none",
              filesOpen && "rotate-90",
            )}
          />
        </button>
      </div>
      {searchBox}
      <div id="file-tree" className={cn("space-y-3", !filesOpen && "max-lg:hidden")}>
        {/* While searching, the search box carries its own filter (same `tags` param). */}
        {!q && (
          <TagFilter
            tags={offered}
            selected={tags}
            loading={counted.isPending}
            truncated={counted.data?.truncated ?? false}
            onChange={setTags}
          />
        )}
        <div className="max-h-[min(70dvh,32rem)] overflow-y-auto overscroll-contain lg:max-h-[calc(100dvh-14rem)]">
          <TreePane
            key={tagsParam ?? ""}
            target={{ owner, repo, ref: version.ref, sha: version.commit_sha }}
            tagsParam={tagsParam}
            selected={path}
            onClearTags={() => setTags(undefined)}
            onOpen={closeFiles}
          />
        </div>
      </div>
    </aside>
  );
}
