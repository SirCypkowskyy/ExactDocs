import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ChevronRight, FolderTree } from "lucide-react";
import { useState } from "react";
import { cn } from "@/shared/lib/utils";
import { articlesPageQueryOptions } from "../api/browse-queries";
import { parseTags } from "../model/browse";
import { TagFilter } from "./tag-filter";
import { TreePane } from "./tree-pane";

interface FilesAsideProps {
  owner: string;
  repo: string;
  version: string;
  path: string | undefined;
  tags: string | undefined;
}

/** The tag filter and the file tree. On a phone they fold behind one button. */
export function FilesAside({ owner, repo, version, path, tags: tagsParam }: FilesAsideProps) {
  const navigate = useNavigate();
  const tags = parseTags(tagsParam);
  // On a phone the tree starts open until an article is open; after that the reader decides.
  const [chosen, setChosen] = useState<boolean>();
  const filesOpen = chosen ?? !path;
  // ponytail: the offered tags are those of the first page of the unfiltered listing (100 articles).
  // Add a tag-count endpoint if large versions need the full list.
  const everything = useQuery(
    articlesPageQueryOptions({ owner, repo, ref: version, tags: [], prefix: "" }),
  );
  const counts = new Map<string, number>();
  for (const a of everything.data?.articles ?? []) {
    for (const t of a.tags) counts.set(t, (counts.get(t) ?? 0) + 1);
  }
  const facets = [...counts]
    .sort((x, y) => y[1] - x[1] || x[0].localeCompare(y[0]))
    .map(([t]) => t);
  for (const t of tags)
    if (!facets.some((f) => f.toLowerCase() === t.toLowerCase())) facets.unshift(t);

  const setTags = (next: string | undefined) =>
    navigate({
      to: "/libraries/$owner/$repo",
      params: { owner, repo },
      search: { version: version, path: path, tags: next },
      replace: true,
    });

  return (
    <aside aria-label="Files" className="min-w-0 lg:sticky lg:top-4">
      <button
        type="button"
        aria-expanded={filesOpen}
        aria-controls="file-tree"
        onClick={() => setChosen(!filesOpen)}
        className="flex h-11 w-full cursor-pointer items-center gap-2 rounded-md bg-secondary px-3 text-sm font-medium outline-none ring-1 ring-inset ring-border focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.99] lg:hidden"
      >
        <FolderTree aria-hidden="true" className="size-4 text-muted-foreground" />
        {path ? "Files" : "Browse files"}
        {tags.length > 0 && (
          <span className="font-normal text-muted-foreground">
            filtered by {tags.length === 1 ? "1 tag" : `${tags.length} tags`}
          </span>
        )}
        <ChevronRight
          aria-hidden="true"
          className={cn(
            "ml-auto size-4 text-muted-foreground transition-transform duration-150 motion-reduce:transition-none",
            filesOpen && "rotate-90",
          )}
        />
      </button>
      <div id="file-tree" className={cn("mt-3 space-y-3 lg:mt-0", !filesOpen && "max-lg:hidden")}>
        <TagFilter facets={facets.slice(0, 14)} selected={tags} onChange={setTags} />
        <div className="max-h-[min(70dvh,32rem)] overflow-y-auto overscroll-contain lg:max-h-[calc(100dvh-12rem)]">
          <TreePane
            key={tagsParam ?? ""}
            owner={owner}
            repo={repo}
            version={version}
            tags={tags}
            tagsParam={tagsParam}
            selected={path}
            onClearTags={() => setTags(undefined)}
            onOpen={() => setChosen(false)}
          />
        </div>
      </div>
    </aside>
  );
}
