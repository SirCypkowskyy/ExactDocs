import { type UseQueryResult, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  ArrowRightLeft,
  Eye,
  Lock,
  type LucideIcon,
  Pencil,
  ScrollText,
  ShieldCheck,
  Trash2,
  UserPlus,
} from "lucide-react";
import { type ReactNode, useRef, useState } from "react";
import { toast } from "sonner";
import { HttpError } from "@/shared/lib/http";
import { common, useLanguage, useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import { cn } from "@/shared/lib/utils";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/shared/ui/breadcrumb";
import { Button, buttonVariants, type IconMotion } from "@/shared/ui/button";
import { ConfirmDialog } from "@/shared/ui/confirm-dialog";
import { type RowAction, restoreRowFocus } from "@/shared/ui/data-table/row-actions";
import { TableError, TableMessage } from "@/shared/ui/data-table/states";
import { LibraryMark } from "@/shared/ui/library-mark";
import { Page, PageHeader } from "@/shared/ui/page";
import { Skeleton } from "@/shared/ui/skeleton";
import { putGrant, revokeGrant, sharingKey, sharingSummaryQueryOptions } from "../api/grants";
import { messages } from "../messages";
import {
  explainSharingError,
  type Grant,
  type GrantedRole,
  type GrantList,
  givableRoles,
  grantKey,
} from "../model/grant";
import { GrantsTable } from "./grants-table";
import { ShareDialog } from "./share-dialog";
import { TransferDialog } from "./transfer-dialog";

/** A role offered in a row's menu, by its icon and reaction. */
const ROLE_ICONS: Record<GrantedRole, { icon: LucideIcon; motion: IconMotion }> = {
  viewer: { icon: Eye, motion: "pop" },
  contributor: { icon: Pencil, motion: "tilt" },
  admin: { icon: ShieldCheck, motion: "pop" },
};

interface Props {
  owner: string;
  repo: string;
  /** The library's ID (`/owner/repo`), title and `logo` (its version), for the header. */
  libraryId: string;
  title?: string | undefined;
  logo?: string | null | undefined;
}

/** Who may read, change and manage one library; its admins share it, its creator hands it over. */
export function SharingPage({ owner, repo, libraryId, title, logo }: Props) {
  const t = useMessages(messages);
  const c = useMessages(common);
  const language = useLanguage();
  const heading = usePageTitle(t.page.documentTitle(title || libraryId));
  const queryClient = useQueryClient();
  const summary = useQuery(sharingSummaryQueryOptions(owner, repo));
  const caller = summary.data?.caller_role;
  const [sharing, setSharing] = useState(false);
  const [transferring, setTransferring] = useState(false);
  const [removing, setRemoving] = useState<Grant>();
  const [announcement, setAnnouncement] = useState("");
  // Once a grant is gone its row is too: focus goes to the heading instead of the row's menu.
  const removed = useRef(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: sharingKey(owner, repo) });
  const say = (text: string) => {
    setAnnouncement(text);
    toast.success(text);
  };

  const change = useMutation({
    mutationFn: ({ grant, role }: { grant: Grant; role: GrantedRole }) =>
      putGrant(owner, repo, { kind: grant.kind, subject: grant.subject, role }),
    onSuccess: (_, { grant, role }) => say(t.done.nowRole(grant, role)),
    onError: (error, { grant }) =>
      toast.error(t.done.roleFailed(grant, explainSharingError(error, language))),
    onSettled: refresh,
  });
  const onRole = (grant: Grant, role: GrantedRole) => {
    if (!change.isPending) change.mutate({ grant, role });
  };

  const remove = useMutation({
    mutationFn: (g: Grant) => revokeGrant(owner, repo, g.kind, g.subject),
    onSuccess: (_, grant) => {
      removed.current = true;
      setRemoving(undefined);
      void refresh();
      say(t.done.noAccess(grant));
    },
  });

  const shareButton = (
    <Button onClick={() => setSharing(true)}>
      <UserPlus aria-hidden="true" data-icon-motion="pop" />
      {t.page.share}
    </Button>
  );

  // One list for each row's kebab and its context menu: another role, removal, the hand-over.
  const rowActions = (grant: Grant): RowAction<Grant>[] => {
    if (!caller) return [];
    if (grant.role === "creator") {
      return caller === "creator"
        ? [
            {
              id: "transfer",
              label: t.table.transferAction,
              icon: ArrowRightLeft,
              motion: "forward",
              onSelect: () => setTransferring(true),
            },
          ]
        : [];
    }
    if (grant.role === "admin" && caller !== "creator") return [];
    return [
      ...givableRoles(caller)
        .filter((role) => role !== grant.role)
        .map(
          (role): RowAction<Grant> => ({
            id: `role-${role}`,
            label: t.table.changeTo(role),
            icon: ROLE_ICONS[role].icon,
            motion: ROLE_ICONS[role].motion,
            onSelect: (g) => onRole(g, role),
          }),
        ),
      {
        id: "remove",
        label: t.table.removeAction,
        icon: Trash2,
        motion: "warn",
        destructive: true,
        group: true,
        onSelect: setRemoving,
      },
    ];
  };

  return (
    <Page>
      <PageHeader
        headingRef={heading}
        mark={<LibraryMark id={libraryId} logo={logo} size="lg" />}
        title={t.page.title}
        description={summary.data ? <Owner creator={summary.data.creator} /> : t.page.description}
        actions={
          caller && (
            <>
              <Link
                to="/libraries/$owner/$repo/access-log"
                params={{ owner, repo }}
                className={buttonVariants({ variant: "ghost" })}
              >
                <ScrollText aria-hidden="true" />
                {t.page.accessLog}
              </Link>
              {caller === "creator" && (
                <Button variant="outline" onClick={() => setTransferring(true)}>
                  <ArrowRightLeft aria-hidden="true" data-icon-motion="forward" />
                  {t.page.transfer}
                </Button>
              )}
              {shareButton}
            </>
          )
        }
        above={<SharingBreadcrumb owner={owner} repo={repo} libraryId={libraryId} />}
      />
      <p role="status" className="sr-only">
        {announcement}
      </p>

      <GrantsBody summary={summary} shareAction={shareButton}>
        {(callerRole) => (
          <GrantsTable
            owner={owner}
            repo={repo}
            caller={callerRole}
            busy={change.isPending ? grantKey(change.variables.grant) : undefined}
            onRole={onRole}
            rowActions={rowActions}
            shareAction={shareButton}
          />
        )}
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
            say(t.done.nowRole({ kind, subject }, role));
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
            say(t.done.nowCreator(username, libraryId));
          }}
        />
      )}
      <ConfirmDialog
        open={removing !== undefined}
        onOpenChange={(open) => {
          if (!open) {
            remove.reset();
            setRemoving(undefined);
          }
        }}
        title={t.remove.title(removing)}
        description={
          <>
            {removing && t.remove.loses(removing, removing.role)}
            {t.remove.description}
          </>
        }
        confirmLabel={c.remove}
        pending={remove.isPending}
        error={remove.isError ? explainSharingError(remove.error, language) : undefined}
        onConfirm={() => {
          if (removing && !remove.isPending) remove.mutate(removing);
        }}
        onCloseAutoFocus={(event) => {
          if (removed.current) {
            removed.current = false;
            event.preventDefault();
            heading.current?.focus();
            return;
          }
          restoreRowFocus(event);
        }}
      />
    </Page>
  );
}

/** The grants in each of their states: loading, refused, failed, never shared, or the table. */
function GrantsBody({
  summary,
  shareAction,
  children,
}: {
  summary: UseQueryResult<GrantList>;
  shareAction: ReactNode;
  children: (caller: GrantList["caller_role"]) => ReactNode;
}) {
  const t = useMessages(messages);
  const language = useLanguage();
  if (summary.isPending) return <GrantsSkeleton />;
  if (summary.error instanceof HttpError && summary.error.status === 403) {
    return (
      <TableMessage icon={Lock} title={t.page.adminsOnlyTitle}>
        {t.page.adminsOnly}
      </TableMessage>
    );
  }
  if (summary.isError) {
    return (
      <TableError
        message={explainSharingError(summary.error, language)}
        onRetry={() => void summary.refetch()}
      />
    );
  }
  if (summary.data.total === 0) {
    return (
      <TableMessage icon={UserPlus} title={t.page.emptyTitle} action={shareAction}>
        {t.page.empty}
      </TableMessage>
    );
  }
  return children(summary.data.caller_role);
}

function SharingBreadcrumb({
  owner,
  repo,
  libraryId,
}: {
  owner: string;
  repo: string;
  libraryId: string;
}) {
  const t = useMessages(messages);
  return (
    <Breadcrumb>
      <BreadcrumbList>
        <BreadcrumbItem>
          <BreadcrumbLink asChild>
            <Link to="/">{t.page.libraries}</Link>
          </BreadcrumbLink>
        </BreadcrumbItem>
        <BreadcrumbSeparator />
        <BreadcrumbItem>
          <BreadcrumbLink asChild className="font-mono text-small">
            <Link to="/libraries/$owner/$repo" params={{ owner, repo }}>
              {libraryId}
            </Link>
          </BreadcrumbLink>
        </BreadcrumbItem>
        <BreadcrumbSeparator />
        <BreadcrumbItem>
          <BreadcrumbPage>{t.page.title}</BreadcrumbPage>
        </BreadcrumbItem>
      </BreadcrumbList>
    </Breadcrumb>
  );
}

function Owner({ creator }: { creator: string | null }) {
  const t = useMessages(messages);
  if (creator === null) return <>{t.page.noCreator}</>;
  return <>{t.page.createdBy(<span className="font-medium text-foreground">{creator}</span>)}</>;
}

const SKELETON_ROWS = [
  ["w-24", "w-14", "w-40"],
  ["w-20", "w-14", "w-40"],
  ["w-28", "w-14", "w-40"],
  ["w-32", "w-16", "w-20"],
] as const;

/** The grants table as it will stand: the toolbar, then rows of who, kind and role. */
function GrantsSkeleton() {
  const t = useMessages(messages);
  return (
    <div aria-busy="true" className="pending-in">
      <p role="status" className="sr-only">
        {t.page.loading}
      </p>
      <div aria-hidden="true">
        <div className="mb-4 flex flex-wrap items-end gap-2">
          <span className="flex w-full max-w-md flex-col gap-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-11 w-full fine:h-9" />
          </span>
          <Skeleton className="h-11 w-20 fine:h-8" />
          <Skeleton className="h-11 w-20 fine:h-8" />
        </div>
        <div className="divide-y divide-rule rounded-lg border border-border">
          <div className="flex gap-6 px-4 py-2.5">
            <Skeleton className="h-4 w-12" />
            <Skeleton className="h-4 w-12" />
            <Skeleton className="h-4 w-12" />
          </div>
          {SKELETON_ROWS.map(([who, kind, role]) => (
            <div key={who} className="flex items-center gap-6 px-4 py-3">
              <span className="flex flex-1 items-center gap-2">
                <Skeleton className="size-6 flex-none rounded-full" />
                <Skeleton className={cn("h-4", who)} />
              </span>
              <Skeleton className={cn("h-5 rounded-full max-md:hidden", kind)} />
              <Skeleton className={cn("h-9 rounded-md", role)} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** The sharing page while its library loads (the route's `pendingComponent`). */
export function SharingSkeleton() {
  const t = useMessages(messages);
  return (
    <Page aria-busy="true" className="pending-in">
      <PageHeader
        mark={<Skeleton className="size-9 rounded-md" />}
        title={t.page.title}
        description={<Skeleton className="mt-1 h-4 w-80 max-w-full" />}
        above={<Skeleton className="h-4 w-56" />}
      />
      <GrantsSkeleton />
    </Page>
  );
}
