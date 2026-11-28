import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError } from "@/shared/lib/http";
import { ruleText } from "@/shared/lib/role-rules";
import { TestRouter } from "@/shared/lib/test-router";
import { TooltipProvider } from "@/shared/ui/tooltip";
import { RoleRulesPage, UsersPage } from "./index";
import { explainRuleError, sourcesOf } from "./model/role-rule";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const json = (body: unknown, status = 200) => Response.json(body, { status });

const configured = {
  id: "config:corp:admin_groups:ops",
  provider: "corp",
  source: "group",
  value: "ops",
  grant: "instance_admin",
  libraries: null,
  configured: true,
  created_by: null,
  created_at: null,
};
const stored = {
  id: "r1",
  provider: "gh",
  source: "github_team",
  value: "acme/docs-writers",
  grant: "contributor",
  libraries: null,
  configured: false,
  created_by: "ada",
  created_at: "2026-11-26T10:00:00Z",
};
const everyone = {
  ...configured,
  id: "config:default_library_role",
  provider: null,
  source: "everyone",
  value: "",
  grant: "viewer",
};
const providers = [
  {
    name: "corp",
    display_name: "Corp SSO",
    github: false,
    role_claim: true,
    configured_rules_only: true,
  },
  {
    name: "gh",
    display_name: "GitHub",
    github: true,
    role_claim: false,
    configured_rules_only: false,
  },
];

/** A role rules API: list, add, remove (removing `r1` refused as the last admin when asked). */
function stubApi({ lastAdmin = false, extra = [] as Record<string, unknown>[] } = {}) {
  let rules: Record<string, unknown>[] = [configured, ...extra, stored];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/api/v1/role-rules" && method === "GET") return json({ rules, providers });
    if (url === "/api/v1/role-rules" && method === "POST") {
      const made = { ...JSON.parse(String(init?.body)), id: "r2", configured: false };
      rules = [...rules, { libraries: null, ...made }];
      return json(made, 201);
    }
    const removed = url.match(/^\/api\/v1\/role-rules\/([^/]+)$/);
    if (removed && method === "DELETE") {
      if (lastAdmin) return json({ error: "last_operator", detail: "no", fields: [] }, 409);
      rules = rules.filter((r) => r.id !== decodeURIComponent(removed[1] ?? ""));
      return new Response(null, { status: 204 });
    }
    if (url.startsWith("/api/v1/users?"))
      return json({
        users: [
          {
            id: "c",
            username: "carol",
            role: "admin",
            created_at: "2026-11-13T10:00:00Z",
            disabled: false,
            last_active_at: null,
            token_count: 0,
            provider: "corp",
            groups: ["ops"],
            rules: [configured.id],
          },
        ],
        next_cursor: null,
        total: 1,
      });
    return json({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderAt(path: "/users/rules" | "/users") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <TestRouter
          history={createMemoryHistory({ initialEntries: [path] })}
          pages={{
            "/users/rules": () => <RoleRulesPage />,
            "/users": () => <UsersPage currentUserId="a" />,
          }}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("role rules page", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lists the configured rules read-only and the stored ones removable", async () => {
    stubApi();
    renderAt("/users/rules");

    const table = await screen.findByRole("table", { name: "Role rules" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("group ops");
    expect(rows[0]).toHaveTextContent("Configuration file");
    expect(within(rows[0] as HTMLElement).queryByRole("button")).toBeNull();
    expect(rows[1]).toHaveTextContent("GitHub team acme/docs-writers");
    expect(rows[1]).toHaveTextContent("contributor on every library");
    expect(screen.getByText(/Corp SSO takes only the configuration file's rules/)).toBeVisible();
  });

  it("shows the default library role as a read-only rule for every account", async () => {
    stubApi({ extra: [everyone] });
    renderAt("/users/rules");

    const table = await screen.findByRole("table", { name: "Role rules" });
    const row = within(table).getByRole("row", { name: /every account/ });
    expect(row).toHaveTextContent("viewer on every library");
    expect(row).toHaveTextContent("Every account (local included)");
    expect(row).toHaveTextContent("Configuration file");
    expect(within(row).queryByRole("button")).toBeNull();
  });

  it("adds a rule for a provider that takes stored rules", async () => {
    const fetchMock = stubApi();
    renderAt("/users/rules");

    await userEvent.click(await screen.findByRole("button", { name: "Add rule" }));
    const dialog = await screen.findByRole("dialog");
    // Only GitHub takes stored rules here, and it offers GitHub names first.
    expect(within(dialog).getByLabelText("Provider")).toHaveValue("gh");
    expect(within(dialog).getByLabelText("Members of")).toHaveValue("github_team");
    await userEvent.type(within(dialog).getByLabelText("Name"), "acme/reviewers");
    await userEvent.selectOptions(within(dialog).getByLabelText("Get"), "viewer");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add rule" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      provider: "gh",
      source: "github_team",
      value: "acme/reviewers",
      grant: "viewer",
    });
    expect(toast.success).toHaveBeenCalledWith(
      "Rule added: GitHub team acme/reviewers → viewer on every library",
    );
  });

  it("asks for a name before sending anything", async () => {
    const fetchMock = stubApi();
    renderAt("/users/rules");

    await userEvent.click(await screen.findByRole("button", { name: "Add rule" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add rule" }));

    expect(await within(dialog).findByText("Name the membership.")).toBeVisible();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });

  it("says why a removal that would leave no admin is refused, inside the confirmation", async () => {
    stubApi({ lastAdmin: true });
    renderAt("/users/rules");

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Remove rule GitHub team acme/docs-writers → contributor on every library",
      }),
    );
    const confirm = await screen.findByRole("alertdialog");
    await userEvent.click(within(confirm).getByRole("button", { name: "Remove" }));

    expect(await within(confirm).findByText(/would leave no enabled admin/)).toBeVisible();
  });

  it("shows on the users page which rule gives a role", async () => {
    stubApi();
    renderAt("/users");

    const table = await screen.findByRole("table", { name: "User accounts" });
    const row = (await within(table).findByText("carol")).closest("tr") as HTMLElement;
    expect(await within(row).findByText("From a rule")).toBeVisible();
    expect(within(row).getByText("group ops → instance admin")).toBeInTheDocument();
  });
});

describe("role rule words", () => {
  it("name every source and grant", () => {
    expect(
      ruleText({ ...stored, source: "github_team", grant: "admin", libraries: ["/a/b"] } as never),
    ).toBe("GitHub team acme/docs-writers → admin on /a/b");
    expect(ruleText({ ...configured } as never, "pl")).toBe("grupa ops → administrator instancji");
    expect(ruleText(everyone as never, "en")).toBe("every account → viewer on every library");
  });

  it("offer GitHub names only on GitHub and role values only with a role claim", () => {
    expect(sourcesOf(providers[1])).toEqual(["github_team", "github_org", "group"]);
    expect(sourcesOf(providers[0])).toEqual(["group", "role"]);
    expect(sourcesOf({ ...providers[0], role_claim: false } as never)).toEqual(["group"]);
  });

  it("explain refusals in words", () => {
    const refusal = (code: string, status = 409) =>
      new HttpError(status, "/v1/role-rules", { error: code });
    expect(explainRuleError(refusal("role_rule_exists"))).toBe(
      "This provider already has that rule.",
    );
    expect(explainRuleError(refusal("configured_rule"))).toMatch(/configuration file/);
  });
});
