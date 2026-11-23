import {
  type InfiniteData,
  type UseInfiniteQueryResult,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRightLeft, History, Lock, UserPlus } from "lucide-react";
import { type ReactNode, useState } from "react";
import { toast } from "sonner";
import { HttpError } from "@/shared/lib/http";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { usePrefetchedPages } from "@/shared/lib/use-prefetched-pages";
import { Button, buttonVariants } from "@/shared/ui/button";
import {
  ConfirmAction,
  ConfirmCancel,
  ConfirmContent,
  ConfirmDescription,
  ConfirmRoot,
  ConfirmTitle,
} from "@/shared/ui/dialog";
import { EmptyState, Page, PageHeader } from "@/shared/ui/page";
import { LibraryBullet } from "@/shared/ui/route";
import { Skeleton } from "@/shared/ui/skeleton";
import { grantsQueryOptions, putGrant, revokeGrant, sharingKey } from "../api/grants";
import {
  explainSharingError,
  type Grant,
  type GrantedRole,
  type GrantList,
  grantKey,
  ROLE_LABELS,
  who,
  whoFirst,
} from "../model/grant";
import { type SharingView, sharingFiltered } from "../model/grants-view";
import { GrantsTable } from "./grants-table";
import { ShareDialog } from "./share-dialog";
import { TransferDialog } from "./transfer-dialog";

const crumb =
  "-ml-1 inline-flex min-h-11 items-center rounded px-1 outline-none transition-colors duration-(--dur-fast) hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring lg:min-h-7";

const NO_VIEW: SharingView = {};
const ignore = () => {};

interface Props {
  owner: string;
  repo: string;
  /** The library's ID (`/owner/repo`) and title, for the header. */
  libraryId: string;
  title?: string | undefined;
  /** The grants table's filters and sort, held in the URL by the route. */
  view?: SharingView;
  onView?: (view: SharingView) => void;
}

/** Who may read, change and manage one library; its admins share it, its creator hands it over. */
export function SharingPage({
  owner,
  repo,
  libraryId,
  title,
  view = NO_VIEW,
  onView = ignore,
}: Props) {
  const heading = usePageTitle(`Sharing ${title || libraryId}`);
  const queryClient = useQueryClient();
  const query = useInfiniteQuery(grantsQueryOptions(owner, repo, view));
  const first = query.data?.pages[0];
  const caller = first?.caller_role;
  const [sharing, setSharing] = useState(false);
  const [transferring, setTransferring] = useState(false);
  const [removing, setRemoving] = useState<Grant>();
  const [announcement, setAnnouncement] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey: sharingKey(owner, repo) });
  const say = (text: string) => {
    setAnnouncement(text);
    toast.success(text);
  };

  const change = useMutation({
    mutationFn: ({ grant, role }: { grant: Grant; role: GrantedRole }) =>
      putGrant(owner, repo, { kind: grant.kind, subject: grant.subject, role }),
    onSuccess: (_, { grant, role }) => say(`${whoFirst(grant)} is now ${article(role)}.`),
    onError: (error, { grant }) =>
      toast.error(`Couldn't change the role of ${who(grant)}. ${explainSharingError(error)}`),
    onSettled: refresh,
  });

  return (
    <Page>
      <PageHeader
        headingRef={heading}
        title="Sharing"
        description={
          first ? <Owner creator={first.creator} /> : "Who can find, read, change and manage it."
        }
        actions={
          caller && (
            <>
              <Link
                to="/libraries/$owner/$repo/access-log"
                params={{ owner, repo }}
                className={buttonVariants({ variant: "ghost" })}
              >
                <History aria-hidden="true" />
                Access log
              </Link>
              {caller === "creator" && (
                <Button variant="outline" onClick={() => setTransferring(true)}>
                  <ArrowRightLeft aria-hidden="true" />
                  Transfer ownership
                </Button>
              )}
              <Button onClick={() => setSharing(true)}>
                <UserPlus aria-hidden="true" />
                Share
              </Button>
            </>
          )
        }
        above={<Breadcrumb owner={owner} repo={repo} libraryId={libraryId} />}
      />
      <p role="status" className="sr-only">
        {announcement}
      </p>

      <GrantsBody query={query} view={view} onShare={() => setSharing(true)}>
        {(grants) =>
          caller && (
            <GrantsTable
              {...grants}
              view={view}
              onView={onView}
              caller={caller}
              busy={change.isPending ? grantKey(change.variables.grant) : undefined}
              onRole={(grant, role) => !change.isPending && change.mutate({ grant, role })}
              onRemove={setRemoving}
            />
          )
        }
      </GrantsBody>

      {caller && (
        <ShareDialog
          owner={owner}
          repo={repo}
          libraryId={libraryId}
          caller={caller}
          open={sharing}
          onOpenChange={setSharing}
          onShared={(kind, subject, role) => {
            void refresh();
            say(`${whoFirst({ kind, subject })} is now ${article(role)}.`);
          }}
        />
      )}
      {caller === "creator" && (
        <TransferDialog
          owner={owner}
          repo={repo}
          libraryId={libraryId}
          open={transferring}
          onOpenChange={setTransferring}
          onTransferred={(username) => {
            void refresh();
            say(`${username} is now the creator of ${libraryId}.`);
          }}
        />
      )}
      <RemoveDialog
        owner={owner}
        repo={repo}
        grant={removing}
        onClose={() => setRemoving(undefined)}
        onRemoved={(grant) => {
          setRemoving(undefined);
          void refresh();
          say(`${whoFirst(grant)} no longer has access.`);
        }}
      />
    </Page>
  );
}

interface LoadedGrants {
  grants: Grant[];
  total: number;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}

/** The list in each of its states: loading, refused, failed, empty, or the table. */
function GrantsBody({
  query,
  view,
  onShare,
  children,
}: {
  query: UseInfiniteQueryResult<InfiniteData<GrantList>>;
  view: SharingView;
  onShare: () => void;
  children: (grants: LoadedGrants) => ReactNode;
}) {
  const { pages, hasMore, loadingMore, loadMore } = usePrefetchedPages(query, view);
  const total = pages.at(-1)?.total ?? 0;
  if (query.isPending) return <GrantsSkeleton />;
  if (query.error instanceof HttpError && query.error.status === 403) {
    return (
      <EmptyState
        icon={<Lock aria-hidden="true" />}
        title="Only the library's admins manage its sharing"
        className="max-w-2xl"
      >
        Ask its creator or an operator to make you an admin, or to share it with the people you have
        in mind.
      </EmptyState>
    );
  }
  if (query.isError && !query.data) {
    return (
      <div
        role="alert"
        className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-lg bg-destructive-soft py-1.5 pr-1.5 pl-4"
      >
        <p className="text-body font-medium text-destructive-ink">
          {explainSharingError(query.error)}
        </p>
        <Button variant="ghost" onClick={() => query.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  if (total === 0 && !sharingFiltered(view)) {
    return (
      <EmptyState
        icon={<UserPlus aria-hidden="true" />}
        title="Not shared with anyone yet"
        className="max-w-2xl"
        action={<Button onClick={onShare}>Share</Button>}
      >
        Only operators can see it for now. Share it with people or identity-provider groups as
        viewers, contributors or admins.
      </EmptyState>
    );
  }
  return children({
    grants: pages.flatMap((p) => p.grants),
    total,
    hasMore,
    loadingMore,
    onLoadMore: loadMore,
  });
}

/** Asks before a grant is taken away, and says why the server refused. */
function RemoveDialog({
  owner,
  repo,
  grant,
  onClose,
  onRemoved,
}: {
  owner: string;
  repo: string;
  grant: Grant | undefined;
  onClose: () => void;
  onRemoved: (grant: Grant) => void;
}) {
  const remove = useMutation({
    mutationFn: (g: Grant) => revokeGrant(owner, repo, g.kind, g.subject),
    onSuccess: (_, g) => onRemoved(g),
  });
  return (
    <ConfirmRoot
      open={grant !== undefined}
      onOpenChange={(open) => {
        if (!open) {
          remove.reset();
          onClose();
        }
      }}
    >
      <ConfirmContent>
        <ConfirmTitle>Remove {grant && who(grant)}?</ConfirmTitle>
        <ConfirmDescription>
          {grant && `${whoFirst(grant)} loses the ${roleName(grant.role)} role. `}
          Access ends at once, on the web and over MCP, unless another grant or a group still gives
          one.
        </ConfirmDescription>
        <p
          role="alert"
          className="mt-4 rounded-md bg-destructive-soft px-3 py-2.5 text-body font-medium text-destructive-ink empty:hidden"
        >
          {remove.isError && explainSharingError(remove.error)}
        </p>
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <ConfirmCancel asChild>
            <Button variant="ghost">Cancel</Button>
          </ConfirmCancel>
          <ConfirmAction asChild>
            <Button
              variant="destructive-solid"
              pending={remove.isPending}
              onClick={(event) => {
                event.preventDefault(); // stay open until the server answers
                if (grant && !remove.isPending) remove.mutate(grant);
              }}
            >
              Remove
            </Button>
          </ConfirmAction>
        </div>
      </ConfirmContent>
    </ConfirmRoot>
  );
}

function Breadcrumb({
  owner,
  repo,
  libraryId,
}: {
  owner: string;
  repo: string;
  libraryId: string;
}) {
  return (
    <nav aria-label="Breadcrumb" className="text-body text-muted-foreground">
      <ol className="flex flex-wrap items-center gap-x-1.5">
        <li>
          <Link to="/" className={crumb}>
            Libraries
          </Link>
        </li>
        <li aria-hidden="true">/</li>
        <li className="inline-flex items-center gap-1.5">
          <LibraryBullet id={libraryId} size="sm" />
          <Link
            to="/libraries/$owner/$repo"
            params={{ owner, repo }}
            className={`${crumb} font-mono text-small`}
          >
            {libraryId}
          </Link>
        </li>
        <li aria-hidden="true">/</li>
        <li aria-current="page" className="text-foreground">
          Sharing
        </li>
      </ol>
    </nav>
  );
}

function Owner({ creator }: { creator: string | null }) {
  if (creator === null) {
    return <>No creator: it was added before library roles, so operators manage it.</>;
  }
  return (
    <>
      Created by <span className="font-medium text-foreground">{creator}</span>, who alone makes or
      removes admins and can hand it over.
    </>
  );
}

const roleName = (role: string) => (ROLE_LABELS[role] ?? role).toLowerCase();
/** "a viewer", "an admin". */
const article = (role: string) =>
  `${/^[aeiou]/.test(roleName(role)) ? "an" : "a"} ${roleName(role)}`;

function GrantsSkeleton() {
  return (
    <div aria-busy="true">
      <span className="sr-only">Loading who has access</span>
      <div aria-hidden="true" className="divide-y divide-rule border-y border-border">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center justify-between gap-4 py-4">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-8 w-40" />
          </div>
        ))}
      </div>
    </div>
  );
}
