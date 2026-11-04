import { useTree } from "../hooks/use-tree";
import { FileTree } from "./file-tree";

interface TreePaneProps {
  owner: string;
  repo: string;
  version: string;
  tags: readonly string[];
  tagsParam: string | undefined;
  selected: string | undefined;
  onClearTags: () => void;
  onOpen: () => void;
}

function Skeleton() {
  const rows = [
    ["a", "w-28"],
    ["b", "w-40"],
    ["c", "w-32"],
    ["d", "w-36"],
    ["e", "w-24"],
    ["f", "w-44"],
    ["g", "w-32"],
  ] as const;
  return (
    <div role="status" aria-busy="true" className="py-2">
      <span className="sr-only">Loading files</span>
      <ul aria-hidden="true" className="space-y-1 motion-safe:animate-pulse">
        {rows.map(([id, w], i) => (
          <li
            key={id}
            className="flex h-9 items-center gap-2 px-2"
            style={{ paddingLeft: `${(i % 3) * 14 + 8}px` }}
          >
            <span className="size-4 shrink-0 rounded bg-muted-foreground/10" />
            <span className={`h-3.5 rounded bg-muted-foreground/10 ${w}`} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The files of one version and tag filter. Mount it with a `key`, so changing either starts afresh. */
export function TreePane({
  owner,
  repo,
  version,
  tags,
  tagsParam,
  selected,
  onClearTags,
  onOpen,
}: TreePaneProps) {
  const tree = useTree({ owner, repo, ref: version, tags: tagsParam, selected });

  if (tree.status === "loading") return <Skeleton />;
  if (tree.status === "error") {
    return (
      <div role="alert" className="py-3 text-sm">
        <p className="text-muted-foreground">Couldn't load the files of {version}.</p>
        <button
          type="button"
          onClick={tree.retry}
          className="mt-1 min-h-11 cursor-pointer rounded-md px-1 font-medium underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring lg:min-h-8"
        >
          Try again
        </button>
      </div>
    );
  }
  if (tree.rows.length === 0) {
    return (
      <div className="py-3 text-sm">
        <p className="font-medium">
          {tags.length > 0 ? `No articles tagged ${tags.join(" or ")}` : "Nothing imported here"}
        </p>
        <p className="mt-1 text-muted-foreground">
          {tags.length > 0
            ? `${version} has no article with ${tags.length > 1 ? "any of these tags" : "this tag"}.`
            : `${version} has no articles. Its import may have skipped every file.`}
        </p>
        {tags.length > 0 && (
          <button
            type="button"
            onClick={onClearTags}
            className="mt-1 min-h-11 cursor-pointer rounded-md px-1 font-medium underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring lg:min-h-8"
          >
            Show all articles
          </button>
        )}
      </div>
    );
  }
  const failed = new Set(
    Object.entries(tree.scopes)
      .filter(([, s]) => s.status === "error")
      .map(([f]) => f),
  );
  return (
    <FileTree
      owner={owner}
      repo={repo}
      version={version}
      tags={tagsParam}
      selected={selected}
      rows={tree.rows}
      failed={failed}
      label={`Files of ${version}`}
      onToggle={tree.toggle}
      onMore={(scope) => void tree.load(scope)}
      onOpen={onOpen}
    />
  );
}
