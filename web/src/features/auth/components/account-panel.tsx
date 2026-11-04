import { useSession } from "../hooks/use-session";

export function AccountPanel() {
  const account = useSession()?.account;
  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="font-serif text-3xl font-semibold tracking-tight">Settings</h1>
      <dl className="mt-8 grid max-w-sm grid-cols-[auto_1fr] gap-x-8 gap-y-3">
        <dt className="text-muted-foreground">Signed in as</dt>
        <dd className="font-medium">{account?.username}</dd>
        <dt className="text-muted-foreground">Role</dt>
        <dd className="font-medium">{account?.role}</dd>
      </dl>
    </main>
  );
}
