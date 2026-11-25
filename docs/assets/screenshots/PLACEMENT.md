# Where the new screenshots go

Pictures added for #563, taken from the deployed instance in Chrome. Each comes as
`<name>-light.webp` and `<name>-dark.webp` (1384 px wide, WebP quality 88). Account names,
token prefixes and the host name were replaced in the page before the capture (ada, grace,
admin, `exd_a1b2…`, `exactdocs.example.com`).

Pages are being split, so the topic says where each one belongs, not a file name.

| Name | What it shows | Alt text | Docs topic |
|---|---|---|---|
| `add-library` | First step of the Add a library page: repository address, the private checkbox and the four steps on the left | The Add a library page asking for a repository address, with the steps check repository, choose version, choose files and import | getting started → adding your first library |
| `add-version` | A library's settings with the Add a version form open above the versions table | The Add a version form in a library's settings, with a branch or tag picker above the table of imported versions | configuration → libraries and versions |
| `library-settings` | Top of a library's settings: title, description and the paths to import | A library's settings page with its title, description and the paths it imports from the repository | configuration → library settings (paths and tags) |
| `library-versions` | A library's versions table and the Retrieval and AI section with the effective pipeline | The versions table of a library and, below it, the retrieval mode and embedding model the library uses | configuration → versions, retrieval modes |
| `library-sharing` | A library's sharing page: creator, a viewer, Share and Transfer ownership buttons | The sharing page of a library, listing its creator and a viewer, with buttons to share it and hand it over | REST/auth → library access and roles |
| `jobs` | The Jobs page: import and embed jobs with state, progress, origin and duration | The Jobs page listing import and embed jobs, each with its library, version, state, progress and how long it took | operations → jobs and imports |
| `overview` | The operator overview: library, job, AI spend and read counters, and daily charts | The operator overview with counters for libraries, jobs, AI spend and reads, and charts of reads and AI spend per day | operations → monitoring the instance |
| `leaderboard` | Leaderboard by searches over a month, top three libraries | The leaderboard ranking libraries by searches this month, with the note that people are not ranked on this instance | operations → usage / leaderboard |
| `users` | Users page: four accounts with role, sign-in method, status and token count | The Users page listing four accounts with their role, how they sign in, status and number of tokens | deployment → auth, managing users |
| `users-tokens` | Users → API tokens: every account's tokens with owner, prefix, expiry and last use | The admin list of every account's API tokens, showing owner, token prefix, expiry and last use | REST/auth → API tokens (admin view) |
| `new-user` | The New user dialog: username, password twice, role | The New user dialog with fields for username, password, repeated password and role | deployment → auth, creating accounts |
| `account-tokens` | Account page, API tokens tab, with the MCP client config snippet below | The account page with one API token and a ready-to-paste MCP client config that uses a token placeholder | REST/auth → API tokens; getting started → connecting an agent |
| `new-token` | The New API token dialog: name, expiry, library access | The New API token dialog with a name, an expiry and a choice of which libraries the token can read | REST/auth → creating a token |
| `account-sign-in` | Account page, Sign-in tab: password note and linked sign-in providers | The Sign-in tab of the account page, with the password section and the list of linked sign-in providers | configuration → auth/OIDC, linking providers |
| `account-interface` | Account page, Interface tab: language, theme, text size, font, contrast | The Interface tab of the account page with choices for language, theme, text size, font and contrast | getting started → using the web UI (preferences) |

## Not captured

- Sign-in page with OIDC/OAuth buttons and the setup page: both redirect away while signed in,
  and signing out of the instance was out of scope.
- Global search: the header box goes to the search page, which is already pictured (`search`).
- Access log (instance and per library): empty on this instance, so the picture would only show
  the empty state.
- AI spend history: the Usage and budgets table is already in `ai`.
