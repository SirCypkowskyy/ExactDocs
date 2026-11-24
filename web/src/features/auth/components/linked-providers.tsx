import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Link2, RefreshCw, Unlink } from "lucide-react";
import { type ReactNode, type RefObject, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { HttpError } from "@/shared/lib/http";
import { common, type Language, useLanguage, useMessages } from "@/shared/lib/i18n";
import { absoluteTime } from "@/shared/lib/time";
import { Badge } from "@/shared/ui/badge";
import { ProviderMark } from "@/shared/ui/brand-marks";
import { Button } from "@/shared/ui/button";
import { ConfirmDialog } from "@/shared/ui/confirm-dialog";
import { FormAlert } from "@/shared/ui/form-alert";
import { Section } from "@/shared/ui/page";
import { Skeleton } from "@/shared/ui/skeleton";
import { Tooltip } from "@/shared/ui/tooltip";
import { accountProvidersQueryOptions, browser, startLink, unlink } from "../api/providers-query";
import { useSession } from "../hooks/use-session";
import { messages } from "../messages";
import {
  type AccountProvider,
  type AccountProviders,
  explainLinkError,
  explainProviderError,
  linkedProvider,
} from "../model/providers";

/*
 * Account → Sign-in → Linked sign-in providers (#506, blocks-map §3, after integration3's rows):
 * every configured provider with its mark, whether it is linked and since when, and the one action
 * that fits. Link leaves for the provider (a full navigation) and comes back to this tab with
 * `?linked=` or `?link_error=`, which this section turns into a toast or an alert and then drops
 * from the URL. Unlink asks first. The origin of an account without a password cannot be
 * unlinked (409 `last_sign_in_method`): its button stays visible but inert, and the row says why.
 */

const ALERT_ID = "providers-alert";
const actionId = (name: string) => `provider-${name}-action`;
const PROVIDERS_KEY = accountProvidersQueryOptions().queryKey;

/** Codes after which the list on screen is out of date. */
const STALE_CODES = new Set([
  "provider_linked",
  "unknown_provider",
  "provider_not_linked",
  "last_sign_in_method",
]);

type Problem = { kind: "result"; code: string } | { kind: "request"; error: unknown; name: string };

const doneIcon = <CircleCheck aria-hidden="true" data-icon-motion="draw" className="size-4" />;

/** True after a refusal that says the list on screen is out of date: read it again. */
const isStale = (error: unknown) =>
  error instanceof HttpError && error.code !== undefined && STALE_CODES.has(error.code);

/**
 * The link's result arrives once, in the URL: a success is a toast, a refusal goes to `onRefused`
 * (an alert that stays); then `onSeen` drops it from the URL so a reload does not repeat it.
 */
function useLinkResult(
  linked: string | undefined,
  linkError: string | undefined,
  onRefused: (problem: Problem) => void,
  onSeen: (() => void) | undefined,
) {
  const t = useMessages(messages).providers;
  const queryClient = useQueryClient();
  const known = useSession()?.providers;
  const handled = useRef<string>(undefined);
  useEffect(() => {
    if (!linked && !linkError) return;
    const key = `${linked ?? ""}|${linkError ?? ""}`;
    if (handled.current === key) return;
    handled.current = key;
    if (linkError) onRefused({ kind: "result", code: linkError });
    else if (linked) {
      const provider = linkedProvider(linked, known ?? []);
      toast.success(provider ? t.linkedToast(provider.display_name) : t.linkedGeneric, {
        id: `linked-${linked}`,
        ...(provider && { description: t.linkedToastHint(provider.display_name) }),
        icon: doneIcon,
      });
      void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
    }
    onSeen?.();
  }, [linked, linkError, known, t, queryClient, onRefused, onSeen]);
}

export function LinkedProviders({
  linked,
  linkError,
  onLinkResultSeen,
}: {
  /** `?linked=<provider>`: a link that just finished. Not trusted to name a real provider. */
  linked?: string | undefined;
  /** `?link_error=<code>`: a link that came back refused. */
  linkError?: string | undefined;
  /** Called once the result was shown, to drop it from the URL. */
  onLinkResultSeen?: (() => void) | undefined;
}) {
  const session = useSession();
  const t = useMessages(messages).providers;
  const language = useLanguage();
  const signedIn = Boolean(session?.account);
  const query = useQuery({ ...accountProvidersQueryOptions(), enabled: signedIn });
  const [problem, setProblem] = useState<Problem>();
  const [target, setTarget] = useState<AccountProvider>();
  const list = useRef<HTMLUListElement>(null);
  const queryClient = useQueryClient();
  useLinkResult(linked, linkError, setProblem, onLinkResultSeen);

  const link = useMutation({
    mutationFn: (provider: AccountProvider) => startLink(provider.name),
    onMutate: () => setProblem(undefined),
    onSuccess: ({ redirect_url }) => browser.leaveFor(redirect_url),
    onError: (error, provider) => {
      setProblem({ kind: "request", error, name: provider.display_name });
      if (isStale(error)) void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
    },
  });
  // After a successful start the browser is leaving: the button stays busy until it has.
  const linking = link.isPending || link.isSuccess ? link.variables?.name : undefined;

  const providers = query.data?.providers ?? [];
  const configured = (session?.providers?.length ?? 0) > 0 || providers.length > 0;
  if (!signedIn || !(configured || problem)) return null;

  const explained = explainProblem(problem, language);
  return (
    <Section id="providers" title={t.title} icon={<Link2 />} description={t.description}>
      <FormAlert id={ALERT_ID} message={explained?.message} link={explained?.link} />
      {query.isPending ? (
        <ProvidersSkeleton label={t.loading} rows={session?.providers?.length || 2} />
      ) : query.isError ? (
        <LoadFailed message={t.loadFailed} onRetry={() => void query.refetch()} />
      ) : (
        <ul
          ref={list}
          tabIndex={-1}
          aria-label={t.list}
          className="max-w-2xl divide-y divide-border rounded-lg border border-border outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {providers.map((provider) => (
            <ProviderRow key={provider.name} provider={provider}>
              <RowAction
                provider={provider}
                linking={linking === provider.name}
                busy={linking !== undefined}
                onLink={() => link.mutate(provider)}
                onUnlink={() => setTarget(provider)}
              />
            </ProviderRow>
          ))}
        </ul>
      )}
      <UnlinkDialog target={target} onClose={() => setTarget(undefined)} list={list} />
    </Section>
  );
}

function explainProblem(problem: Problem | undefined, language: Language) {
  if (problem?.kind === "result") return explainLinkError(problem.code, language);
  if (problem) return explainProviderError(problem.error, problem.name, language);
  return undefined;
}

/** "Unlink GitHub?": Cancel first; after the unlink, focus lands on the row's new action. */
function UnlinkDialog({
  target,
  onClose,
  list,
}: {
  target: AccountProvider | undefined;
  onClose: () => void;
  list: RefObject<HTMLUListElement | null>;
}) {
  const t = useMessages(messages).providers;
  const language = useLanguage();
  const queryClient = useQueryClient();
  const focusAfter = useRef<string>(undefined);
  const remove = useMutation({
    mutationFn: (provider: AccountProvider) => unlink(provider.name),
    onSuccess: (next: AccountProviders, provider) => {
      queryClient.setQueryData(PROVIDERS_KEY, next);
      focusAfter.current = provider.name;
      onClose();
      toast.success(t.unlinkedToast(provider.display_name), { icon: doneIcon });
    },
    onError: (error) => {
      if (isStale(error)) void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
    },
  });
  const name = target?.display_name ?? "";
  return (
    <ConfirmDialog
      open={target !== undefined}
      onOpenChange={(open) => {
        if (open) return;
        onClose();
        remove.reset();
      }}
      title={t.confirmTitle(name)}
      description={t.confirmBody(name)}
      confirmLabel={t.confirm}
      pendingLabel={t.pending}
      icon={<Unlink aria-hidden="true" data-icon-motion="warn" />}
      pending={remove.isPending}
      error={
        remove.isError ? explainProviderError(remove.error, name, language).message : undefined
      }
      onConfirm={() => target && remove.mutate(target)}
      onCloseAutoFocus={(event) => {
        const gone = focusAfter.current;
        if (gone === undefined) return;
        // The Unlink button is gone: land on the row's new action, else on the list.
        focusAfter.current = undefined;
        event.preventDefault();
        (document.getElementById(actionId(gone)) ?? list.current)?.focus();
      }}
    />
  );
}

function ProviderRow({ provider, children }: { provider: AccountProvider; children: ReactNode }) {
  const t = useMessages(messages).providers;
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-3 px-4 py-3">
      <ProviderMark icon={provider.icon} iconUrl={provider.icon_url} size="md" />
      <div className="min-w-0 flex-1 basis-48">
        <p className="flex flex-wrap items-center gap-2 text-body font-medium">
          {provider.display_name}
          {provider.origin && <Badge>{t.origin}</Badge>}
        </p>
        <p className="text-small text-muted-foreground">
          <Status provider={provider} />
        </p>
        {provider.linked && !provider.can_unlink && (
          <p
            id={reasonId(provider.name)}
            className="mt-1 max-w-prose text-small text-muted-foreground"
          >
            {t.cannotUnlink(provider.display_name)}
          </p>
        )}
      </div>
      {children}
    </li>
  );
}

const reasonId = (name: string) => `provider-${name}-reason`;

/** The one action that fits the row: Link, Unlink, or an Unlink that says why it cannot. */
function RowAction({
  provider,
  linking,
  busy,
  onLink,
  onUnlink,
}: {
  provider: AccountProvider;
  linking: boolean;
  busy: boolean;
  onLink: () => void;
  onUnlink: () => void;
}) {
  const t = useMessages(messages).providers;
  const name = provider.display_name;
  const id = actionId(provider.name);
  if (provider.can_link) {
    return (
      <Button
        id={id}
        variant="outline"
        size="sm"
        pending={linking}
        aria-disabled={busy && !linking ? true : undefined}
        onClick={() => !busy && onLink()}
      >
        {!linking && <ProviderMark icon={provider.icon} iconUrl={provider.icon_url} />}
        {t.link(name)}
      </Button>
    );
  }
  if (!provider.linked) return null;
  if (!provider.can_unlink) {
    return (
      <Tooltip label={t.cannotUnlink(name)}>
        <Button
          id={id}
          variant="destructive"
          size="sm"
          aria-label={t.unlinkName(name)}
          aria-disabled="true"
          aria-describedby={reasonId(provider.name)}
          className="cursor-not-allowed opacity-60 hover:border-destructive/40 hover:bg-background"
        >
          <Unlink aria-hidden="true" />
          {t.unlink}
        </Button>
      </Tooltip>
    );
  }
  return (
    <Button
      id={id}
      variant="destructive"
      size="sm"
      aria-label={t.unlinkName(name)}
      aria-disabled={busy ? true : undefined}
      onClick={() => !busy && onUnlink()}
    >
      <Unlink aria-hidden="true" data-icon-motion="warn" />
      {t.unlink}
    </Button>
  );
}

const DATE_OPTIONS: Intl.DateTimeFormatOptions = {
  day: "numeric",
  month: "short",
  year: "numeric",
};
const DATES: Record<Language, Intl.DateTimeFormat> = {
  en: new Intl.DateTimeFormat("en", DATE_OPTIONS),
  pl: new Intl.DateTimeFormat("pl", DATE_OPTIONS),
};

function Status({ provider }: { provider: AccountProvider }) {
  const t = useMessages(messages).providers;
  const language = useLanguage();
  if (!provider.configured) return t.notConfigured;
  if (!provider.linked) return t.notLinked;
  if (!provider.linked_at) return t.linked;
  return (
    <time dateTime={provider.linked_at} title={absoluteTime(provider.linked_at, language)}>
      {t.linkedSince(DATES[language].format(new Date(provider.linked_at)))}
    </time>
  );
}

function ProvidersSkeleton({ label, rows }: { label: string; rows: number }) {
  return (
    <div aria-busy="true" className="max-w-2xl rounded-lg border border-border">
      <p role="status" className="sr-only">
        {label}
      </p>
      {Array.from({ length: rows }, (_, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: placeholder rows have nothing else
        <div key={i} className="flex items-center gap-4 border-border px-4 py-3 not-first:border-t">
          <Skeleton className="size-5" />
          <div className="flex-1">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="mt-1.5 h-3.5 w-40" />
          </div>
          <Skeleton className="h-8 w-28" />
        </div>
      ))}
    </div>
  );
}

function LoadFailed({ message, onRetry }: { message: string; onRetry: () => void }) {
  const c = useMessages(common);
  return (
    <div className="flex flex-wrap items-center gap-3">
      <p role="alert" className="text-body text-destructive-ink">
        {message}
      </p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        <RefreshCw aria-hidden="true" data-icon-motion="refresh" />
        {c.retry}
      </Button>
    </div>
  );
}
