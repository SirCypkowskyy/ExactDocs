import { useMessages } from "@/shared/lib/i18n";
import { Page, PageHeader } from "@/shared/ui/page";
import { Skeleton as Bar } from "@/shared/ui/skeleton";
import { messages } from "../messages";

const tree = [
  ["a", "w-28", 0],
  ["b", "w-40", 1],
  ["c", "w-32", 1],
  ["d", "w-36", 2],
  ["e", "w-24", 0],
  ["f", "w-44", 1],
] as const;
const rows = ["a", "b", "c", "d", "e"];

/**
 * The library page's final layout with grey bars where the values will be (route
 * `pendingComponent`): breadcrumb and header, the version picker and the tree beside the
 * overview and the articles table, so nothing jumps when the library lands.
 */
export function BrowseSkeleton() {
  const t = useMessages(messages);
  return (
    <Page width="wide" className="pending-in" aria-busy="true">
      <PageHeader
        mark={<Bar className="size-12 rounded-md" />}
        above={
          <div aria-hidden="true" className="flex min-h-11 items-center gap-1.5 lg:min-h-7">
            <Bar className="h-4 w-16" />
            <span className="text-muted-foreground/70">/</span>
            <Bar className="h-4 w-36" />
          </div>
        }
        title={
          <>
            <Bar className="h-7 w-56 max-w-full" />
            <span className="sr-only">{t.page.loading}</span>
          </>
        }
        description={<Bar className="mt-1 h-4 w-72 max-w-full" />}
        actions={
          <>
            <Bar className="h-11 w-24 fine:h-8 max-sm:hidden" />
            <Bar className="h-11 w-11 fine:h-8 sm:w-28" />
          </>
        }
      />
      <div
        aria-hidden="true"
        className="grid gap-x-10 gap-y-5 lg:grid-cols-[minmax(17rem,20rem)_minmax(0,1fr)] lg:items-start xl:gap-x-14"
      >
        <div className="flex min-w-0 flex-col gap-3">
          <div className="grid grid-cols-2 gap-2 lg:block">
            <Bar className="h-11 w-full fine:h-9" />
            <Bar className="h-11 w-full lg:hidden" />
          </div>
          <div className="flex flex-wrap gap-1.5 max-lg:hidden">
            {["w-12", "w-16", "w-14", "w-10"].map((w) => (
              <Bar key={w} className={`h-6 rounded-full ${w}`} />
            ))}
          </div>
          <ul className="space-y-1 max-lg:hidden">
            {tree.map(([id, w, depth]) => (
              <li
                key={id}
                className="flex h-8 items-center gap-2"
                style={{ paddingLeft: `${depth * 12 + 8}px` }}
              >
                <Bar className="size-4 shrink-0" />
                <Bar className={`h-3.5 ${w}`} />
              </li>
            ))}
          </ul>
        </div>
        <div className="min-w-0">
          <div className="max-w-[72ch] space-y-3">
            <Bar className="h-6 w-48" />
            <Bar className="h-5 w-full" />
            <div className="grid gap-x-8 gap-y-4 border-t border-rule pt-5 sm:grid-cols-2">
              <Bar className="h-10 w-full" />
              <Bar className="h-10 w-full" />
            </div>
          </div>
          <div className="mt-8 border-t border-rule pt-5">
            <Bar className="mb-4 h-6 w-32" />
            <Bar className="mb-4 h-11 w-full max-w-md fine:h-9" />
            <div className="rounded-lg border border-border">
              {rows.map((id) => (
                <div
                  key={id}
                  className="flex items-center gap-6 border-b border-rule px-3 py-3 last:border-b-0"
                >
                  <Bar className="h-4 w-56 max-w-[50%]" />
                  <Bar className="h-4 w-32 max-md:hidden" />
                  <Bar className="ml-auto h-4 w-12" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Page>
  );
}
