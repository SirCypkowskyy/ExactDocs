import { useCallback } from "react";
import { common, useMessages } from "@/shared/lib/i18n";
import { Button } from "@/shared/ui/button";
import { Skeleton as Bar } from "@/shared/ui/skeleton";
import type { VersionArgs } from "../api/browse-queries";
import { useTree } from "../hooks/use-tree";
import { messages } from "../messages";
import { FileTree } from "./file-tree";

interface TreePaneProps {
  target: VersionArgs;
  tagsParam: string | undefined;
  selected: string | undefined;
  onClearTags: () => void;
  onOpen: () => void;
}

const bars = [
  ["a", "w-28"],
  ["b", "w-40"],
  ["c", "w-32"],
  ["d", "w-36"],
  ["e", "w-24"],
  ["f", "w-44"],
  ["g", "w-32"],
] as const;

function TreeSkeleton() {
  const t = useMessages(messages).tree;
  return (
    <div role="status" aria-busy="true" className="py-2">
      <span className="sr-only">{t.loadingFiles}</span>
      <ul aria-hidden="true" className="space-y-1">
        {bars.map(([id, w], i) => (
          <li
            key={id}
            className="flex h-8 items-center gap-2"
            style={{ paddingLeft: `${(i % 3) * 12 + 8}px` }}
          >
            <Bar className="size-4 shrink-0" />
            <Bar className={`h-3.5 ${w}`} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The files of one version and tag filter. Mount it with a `key`, so changing either starts afresh. */
export function TreePane({ target, tagsParam, selected, onClearTags, onOpen }: TreePaneProps) {
  const t = useMessages(messages).tree;
  const c = useMessages(common);
  const { owner, repo, ref, sha } = target;
  const tree = useTree({ owner, repo, ref, sha, tags: tagsParam, selected });
  const { scopes, loadMore } = tree;
  const scopeState = useCallback(
    (scope: string) => {
      const status = scopes[scope]?.status;
      return status === "paging" ? "paging" : status === "error" ? "error" : "idle";
    },
    [scopes],
  );
  const tags = tagsParam?.split(",").filter(Boolean) ?? [];

  if (tree.status === "loading") return <TreeSkeleton />;
  if (tree.status === "error") {
    return (
      <div role="alert" className="py-3 text-body">
        <p className="text-muted-foreground">{t.filesFailed(ref)}</p>
        <Button variant="outline" size="sm" className="mt-2" onClick={() => loadMore("")}>
          {c.retry}
        </Button>
      </div>
    );
  }
  if (tree.rows.length === 0) {
    return (
      <div className="py-3 text-body">
        <p className="font-medium">{tags.length > 0 ? t.noneTagged(tags) : t.nothingHere}</p>
        <p className="mt-1 text-muted-foreground">
          {tags.length > 0 ? t.noneWithTags(ref, tags.length) : t.noArticles(ref)}
        </p>
        {tags.length > 0 && (
          <Button variant="outline" size="sm" className="mt-2" onClick={onClearTags}>
            {t.showAll}
          </Button>
        )}
      </div>
    );
  }
  return (
    <FileTree
      owner={owner}
      repo={repo}
      version={ref}
      tags={tagsParam}
      selected={selected}
      rows={tree.rows}
      scopeState={scopeState}
      label={t.filesOf(ref)}
      onToggle={tree.toggle}
      onMore={loadMore}
      onOpen={onOpen}
    />
  );
}
