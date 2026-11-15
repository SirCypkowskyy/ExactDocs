# Ingestion benchmark

The golden corpus (starlette, pydantic, tanstack-query, zod, electron; every pinned version) imported with each chunking configuration; BM25 over the golden set's 321 cases (`sha256:39f6f9d5e909d128`). Tokens are estimated at 4 characters; a small chunk is under 50 tokens. Definitions: docs/evals.md#the-ingestion-benchmark.

| configuration | coverage | held | cut fence / table / list | lost chars | tokens p50 / p95 / max | small | multi-top | empty / wrong path | headings missed / extra | BM25 recall@5 (exact) | MRR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `default` | 100.0% | 367/367 | 4 / 0 / 0 | 11446 of 7940351 | 88 / 516 / 8645 | 32.2% | 0.0% | 723 / 103 | 60 / 3 | 79.8% (79.8%) | 0.626 |
| `h2` | 51.8% | 367/367 | 3 / 0 / 0 | 11446 of 7940351 | 179 / 1699 / 8645 | 14.3% | 0.6% | 726 / 95 | 60 / 3 | 76.0% (39.3%) | 0.626 |
| `h3-max-4000` | 91.3% | 367/367 | 4 / 0 / 0 | 11446 of 7940351 | 114 / 738 / 8645 | 23.1% | 0.0% | 723 / 102 | 60 / 3 | 81.7% (76.8%) | 0.651 |
| `merge-400` | 77.1% | 367/367 | 4 / 0 / 0 | 11446 of 7940351 | 183 / 654 / 8645 | 3.0% | 5.1% | 723 / 88 | 60 / 3 | 74.2% (65.2%) | 0.602 |

- `default`: today's default: every heading starts a chunk; nothing is merged or bounded.
- `h2`: only # and ## start a chunk; deeper sections stay inside their parent.
- `h3-max-4000`: # to ### start a chunk; one over 4,000 characters is cut again at deeper headings.
- `merge-400`: every heading starts a chunk, then one under 400 characters is merged with the next while the result stays within 4,000.

## `default` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 346 | 100.0% | 0 | 0 | 64 / 446 / 825 | 41.6% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 500 | 100.0% | 0 | 0 | 52 / 418 / 932 | 48.6% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 538 | 100.0% | 0 | 0 | 52 / 431 / 923 | 49.1% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 248 | 100.0% | 0 | 0 | 147 / 582 / 3017 | 10.9% | 23 / 0 | 0 / 0 | 23 | 117 | 67 |
| pydantic | v2.5.3 | 67 (1) | 553 | 100.0% | 0 | 0 | 138 / 738 / 3017 | 12.3% | 56 / 40 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 677 | 100.0% | 0 | 0 | 159 / 871 / 2762 | 10.6% | 77 / 60 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 497 | 100.0% | 0 | 0 | 134 / 540 / 3424 | 14.9% | 103 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 574 | 100.0% | 0 | 0 | 143 / 600 / 3269 | 12.9% | 110 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 1322 | 100.0% | 0 | 0 | 71 / 506 / 3571 | 40.5% | 211 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 118 | 100.0% | 2 | 0 | 150 / 528 / 996 | 11.0% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 244 | 100.0% | 1 | 5289 | 166 / 630 / 2306 | 13.9% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 351 | 100.0% | 1 | 6157 | 183 / 684 / 8645 | 12.5% | 24 / 3 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 2853 | 100.0% | 0 | 0 | 70 / 398 / 2493 | 38.0% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 3180 | 100.0% | 0 | 0 | 77 / 448 / 3582 | 35.3% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 3464 | 100.0% | 0 | 0 | 81 / 470 / 3582 | 33.9% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

## `h2` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 159 | 63.2% | 0 | 0 | 123 / 1040 / 1821 | 26.4% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 224 | 60.9% | 0 | 0 | 115 / 875 / 1923 | 25.4% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 235 | 53.6% | 0 | 0 | 107 / 978 / 1946 | 25.1% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 136 | 68.8% | 0 | 0 | 215 / 1591 / 3017 | 7.3% | 23 / 0 | 0 / 0 | 23 | 81 | 67 |
| pydantic | v2.5.3 | 67 (1) | 400 | 50.0% | 0 | 0 | 148 / 1378 / 3017 | 9.5% | 56 / 40 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 504 | 57.1% | 0 | 0 | 156 / 1610 / 2762 | 9.7% | 77 / 55 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 339 | 61.9% | 0 | 0 | 166 / 1027 / 3424 | 10.9% | 104 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 374 | 61.9% | 0 | 0 | 179 / 1182 / 3269 | 8.8% | 111 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 893 | 72.0% | 0 | 0 | 98 / 802 / 3571 | 32.9% | 212 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 41 | 22.2% | 1 | 0 | 334 / 1846 / 1969 | 4.9% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 146 | 72.0% | 1 | 5289 | 243 / 1263 / 2306 | 7.5% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 200 | 59.4% | 1 | 6157 | 265 / 1402 / 8645 | 7.5% | 24 / 0 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 742 | 34.6% | 0 | 0 | 220 / 1906 / 2493 | 10.0% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 871 | 26.9% | 0 | 0 | 238 / 1931 / 3582 | 9.4% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 965 | 17.9% | 0 | 0 | 265 / 1929 / 3582 | 8.8% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

Sections that start no chunk under `h2`:

- electron v30.0.0:docs/api/app.md [app > Events > Event: 'second-instance'] (held)
- electron v30.0.0:docs/api/app.md [app > Methods > app.requestSingleInstanceLock([additionalData])] (held)
- electron v30.0.0:docs/api/app.md [app > Methods > app.setAsDefaultProtocolClient(protocol[, path, args])] (held)
- electron v30.0.0:docs/api/auto-updater.md [autoUpdater > Platform Notices > macOS] (held)
- electron v30.0.0:docs/api/context-bridge.md [contextBridge > Methods > contextBridge.exposeInMainWorld(apiKey, api)] (held)
- electron v30.0.0:docs/api/web-contents-view.md [WebContentsView > Class: WebContentsView extends View > new WebContentsView([options])] (held)
- electron v30.0.0:docs/breaking-changes.md [Breaking Changes > Planned Breaking API Changes (30.0) > Behavior Changed: BrowserView.setAutoResize behavior on macOS] (held)
- electron v30.0.0:docs/breaking-changes.md [Breaking Changes > Planned Breaking API Changes (30.0) > Removed: params.inputFormType property on context-menu on WebContents] (held)
- electron v30.0.0:docs/tutorial/dark-mode.md [Dark Mode > Overview > Manually update your own interfaces] (held)
- electron v30.0.0:docs/tutorial/esm.md [ES Modules (ESM) in Electron > Main process > Caveats > You must use await generously before the app's ready event] (held)
- electron v30.0.0:docs/tutorial/esm.md [ES Modules (ESM) in Electron > Preload scripts > Caveats > Sandboxed preload scripts can't use ESM imports] (held)
- electron v30.0.0:docs/tutorial/ipc.md [Inter-Process Communication > Pattern 2: Renderer to main (two-way) > 1. Listen for events with ipcMain.handle] (held)
- electron v30.0.0:docs/tutorial/ipc.md [Inter-Process Communication > Pattern 2: Renderer to main (two-way) > 2. Expose ipcRenderer.invoke via preload] (held)
- electron v30.0.0:docs/tutorial/launch-app-from-url-in-another-app.md [Deep Links > Examples > Main Process (main.js) > Windows and Linux code:] (held)
- electron v30.0.0:docs/tutorial/sandbox.md [Process Sandboxing > Configuring the sandbox > Disabling the sandbox for a single process] (held)
- electron v30.0.0:docs/tutorial/sandbox.md [Process Sandboxing > Sandbox behavior in Electron > Preload scripts] (held)
- electron v30.0.0:docs/tutorial/security.md [Security > Checklist: Security recommendations > 14. Disable or limit creation of new windows > How?] (held)
- electron v38.0.0:docs/api/app.md [app > Methods > app.getPath(name)] (held)
- electron v38.0.0:docs/api/corner-smoothing-css.md [CSS Rule: -electron-corner-smoothing > Matching the system UI] (held)
- electron v38.0.0:docs/api/navigation-history.md [Class: NavigationHistory > Instance Methods > navigationHistory.restore(options)] (held)
- electron v38.0.0:docs/api/session.md [session > Class: Session > Instance Methods > ses.registerPreloadScript(script)] (held)
- electron v38.0.0:docs/api/utility-process.md [utilityProcess > Methods > utilityProcess.fork(modulePath[, args][, options])] (held)
- electron v38.0.0:docs/api/web-utils.md [webUtils > Methods > webUtils.getPathForFile(file)] (held)
- electron v38.0.0:docs/breaking-changes.md [Breaking Changes > Planned Breaking API Changes (32.0) > Deprecated: clearHistory, canGoBack, goBack, canGoForward, goForward, goToIndex, canGoToOffset, goToOffset on WebContents] (held)
- electron v38.0.0:docs/breaking-changes.md [Breaking Changes > Planned Breaking API Changes (32.0) > Removed: File.path] (held)
- electron v38.0.0:docs/breaking-changes.md [Breaking Changes > Planned Breaking API Changes (35.0) > Deprecated: setPreloads, getPreloads on Session] (held)
- electron v38.0.0:docs/breaking-changes.md [Breaking Changes > Planned Breaking API Changes (37.0) > Utility Process unhandled rejection behavior change] (held)
- electron v38.0.0:docs/breaking-changes.md [Breaking Changes > Planned Breaking API Changes (38.0) > Removed: ELECTRON_OZONE_PLATFORM_HINT environment variable] (held)
- electron v38.0.0:docs/breaking-changes.md [Breaking Changes > Planned Breaking API Changes (38.0) > Removed: macOS 11 support] (held)
- electron v38.0.0:docs/tutorial/asar-archives.md [Limitations of the Node API > Executing Binaries Inside ASAR archive] (held)
- electron v38.0.0:docs/tutorial/custom-title-bar.md [Custom Title Bar > Basic tutorial > Add native window controls Windows Linux] (held)
- electron v38.0.0:docs/tutorial/custom-title-bar.md [Custom Title Bar > Basic tutorial > Create a custom title bar] (held)
- electron v38.0.0:docs/tutorial/fuses.md [Electron Fuses > Current Fuses > cookieEncryption] (held)
- electron v38.0.0:docs/tutorial/fuses.md [Electron Fuses > Current Fuses > runAsNode] (held)
- electron v38.0.0:docs/tutorial/fuses.md [Electron Fuses > How do I flip the fuses? > The easy way] (held)
- electron v38.0.0:docs/tutorial/security.md [Security > Checklist: Security recommendations > 19. Check which fuses you can change > Why?] (held)
- electron v45.3.2:docs/api/auto-updater.md [autoUpdater > Platform Notices > macOS] (held)
- electron v45.3.2:docs/api/base-window.md [BaseWindow > Class: BaseWindow > Instance Events > Event: 'persisted-state-restored'] (held)
- electron v45.3.2:docs/api/base-window.md [BaseWindow > Class: BaseWindow > Static Methods > BaseWindow.clearPersistedState(name)] (held)
- electron v45.3.2:docs/api/clipboard-item.md [ClipboardItem > Class: ClipboardItem > new ClipboardItem(items)] (held)
- electron v45.3.2:docs/api/clipboard.md [clipboard > Methods > clipboard.write(data)] (held)
- electron v45.3.2:docs/api/safe-storage.md [safeStorage > Methods > safeStorage.decryptStringAsync(encrypted)] (held)
- electron v45.3.2:docs/api/safe-storage.md [safeStorage > Methods > safeStorage.isAsyncEncryptionAvailable()] (held)
- electron v45.3.2:docs/api/session.md [session > Class: Session > Instance Methods > ses.registerLocalAIHandler(handler) Experimental] (held)
- electron v45.3.2:docs/breaking-changes.md [Breaking Changes > Breaking API Changes (42.0) > Behavior Changed: electron no longer downloads itself via postinstall script] (held)
- electron v45.3.2:docs/breaking-changes.md [Breaking Changes > Breaking API Changes (43.0) > Behavior Changed: Dialog methods default to Downloads directory] (held)
- electron v45.3.2:docs/breaking-changes.md [Breaking Changes > Breaking API Changes (44.0) > Removed: clipboard module is no longer available in the renderer process] (held)
- electron v45.3.2:docs/breaking-changes.md [Breaking Changes > Breaking API Changes (45.0) > Deprecated: safeStorage.isEncryptionAvailable(), safeStorage.encryptString() and safeStorage.decryptString()] (held)
- electron v45.3.2:docs/breaking-changes.md [Breaking Changes > Breaking API Changes (45.0) > Removed: Node.js module shims and Buffer, setImmediate, clearImmediate globals in sandboxed preload scripts] (held)
- electron v45.3.2:docs/tutorial/local-ai-handler.md [Local AI Handler > Quick start > 1. Create the utility process script] (held)
- electron v45.3.2:docs/tutorial/local-ai-handler.md [Local AI Handler > Quick start > 2. Register the handler in the main process] (held)
- electron v45.3.2:docs/tutorial/offscreen-rendering.md [Offscreen Rendering > Overview > Rendering Modes > GPU accelerated] (held)
- electron v45.3.2:docs/tutorial/offscreen-rendering.md [Offscreen Rendering > Overview > Rendering Modes > Software output device] (held)
- electron v45.3.2:docs/tutorial/sandbox.md [Process Sandboxing > Sandbox behavior in Electron > Preload scripts] (held)
- electron v45.3.2:docs/tutorial/web-embeds.md [Web Embeds > Overview > WebContentsView] (held)
- electron v45.3.2:docs/tutorial/web-embeds.md [Web Embeds > Overview > WebViews] (held)
- electron v45.3.2:docs/tutorial/window-state-persistence.md [Window State Persistence > Usage > Basic usage] (held)
- electron v45.3.2:docs/tutorial/window-state-persistence.md [Window State Persistence > Usage > Clearing persisted state] (held)
- electron v45.3.2:docs/tutorial/window-state-persistence.md [Window State Persistence > Usage > Selective persistence] (held)
- pydantic v1.10.22:docs/install.md [Compiled with Cython > Performance vs package size trade-off] (held)
- pydantic v1.10.22:docs/mypy_plugin.md [Plugin Capabilities > Respect Config.allow_mutation] (held)
- pydantic v1.10.22:docs/usage/models.md [Helper Functions > Creating models without validation] (held)
- pydantic v1.10.22:docs/usage/models.md [Required fields > Required Optional fields] (held)
- pydantic v1.10.22:docs/usage/types.md [Custom Data Types > Classes with __get_validators__] (held)
- pydantic v2.14.3:docs/concepts/alias.md [Alias Configuration > ConfigDict Settings > Validation] (held)
- pydantic v2.14.3:docs/concepts/alias.md [Alias Configuration > Runtime Settings > Validation] (held)
- pydantic v2.14.3:docs/concepts/experimental.md [Experimental Features > Partial Validation > Limitations of Partial Validation > TypeAdapter only] (held)
- pydantic v2.14.3:docs/concepts/fields.md [Deprecated fields > deprecated as a string] (held)
- pydantic v2.14.3:docs/concepts/json.md [JSON > Json Parsing > Partial JSON Parsing] (held)
- pydantic v2.14.3:docs/concepts/models.md [Validating data > Defining a custom __init__()] (held)
- pydantic v2.14.3:docs/concepts/serialization.md [Serializing subclasses > Polymorphic serialization] (held)
- pydantic v2.14.3:docs/concepts/types.md [Utility types > FailFast] (held)
- pydantic v2.14.3:docs/concepts/types.md [Utility types > OnErrorOmit] (held)
- pydantic v2.14.3:docs/concepts/unions.md [Discriminated unions > Discriminated unions with string discriminators] (held)
- pydantic v2.14.3:docs/integrations/aws_lambda.md [Troubleshooting > Missing pydantic_core module] (held)
- pydantic v2.14.3:docs/integrations/aws_lambda.md [Troubleshooting > No package metadata was found for email-validator] (held)
- pydantic v2.14.3:docs/integrations/mypy.md [Configuring the Plugin > init_forbid_extra] (held)
- pydantic v2.14.3:docs/migration.md [Continue using Pydantic V1 features > Using Pydantic v1 features in a v1/v2 environment] (held)
- pydantic v2.14.3:docs/migration.md [Migration guide > Type conversion from floats to integers] (held)
- pydantic v2.5.3:docs/concepts/serialization.md [Serializing subclasses > Serializing with duck-typing] (held)
- pydantic v2.5.3:docs/concepts/serialization.md [Serializing subclasses > Subclass instances for fields of BaseModel, dataclasses, TypedDict] (held)
- pydantic v2.5.3:docs/concepts/unions.md [Union Modes > Smart Mode] (held)
- pydantic v2.5.3:docs/concepts/validators.md [Annotated Validators > Before, After, Wrap and Plain validators] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > BaseSettings has moved to pydantic-settings] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to Handling of Standard Types > Patterns / regex on strings] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to config] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to pydantic.BaseModel] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to pydantic.Field] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to validators > @validator and @root_validator are deprecated] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Constrained types] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Introduction of TypeAdapter] (held)
- starlette 0.27.0:docs/endpoints.md [WebSocketEndpoint] (held)
- starlette 0.27.0:docs/middleware.md [BaseHTTPMiddleware > Limitations] (held)
- starlette 0.27.0:docs/release-notes.md [0.26.0 > Deprecated] (held)
- starlette 0.27.0:docs/release-notes.md [0.27.0 > Fixed] (held)
- starlette 0.27.0:docs/requests.md [Request > Client Address] (held)
- starlette 0.27.0:docs/responses.md [RedirectResponse] (held)
- starlette 0.27.0:docs/staticfiles.md [StaticFiles] (held)
- starlette 0.52.1:docs/middleware.md [CORSMiddleware > Private Network Access (PNA)] (held)
- starlette 0.52.1:docs/release-notes.md [0.29.0 (July 13, 2023) > Added] (held)
- starlette 0.52.1:docs/release-notes.md [0.33.0 (December 1, 2023) > Added] (held)
- starlette 0.52.1:docs/release-notes.md [0.39.0 (September 23, 2024) > Added] (held)
- starlette 0.52.1:docs/requests.md [Request > Other state] (held)
- starlette 0.52.1:docs/requests.md [Request > Request Files] (held)
- starlette 0.52.1:docs/responses.md [FileResponse] (held)
- starlette 0.52.1:docs/testclient.md [Change client address] (held)
- starlette 0.52.1:docs/websockets.md [Send Denial Response] (held)
- starlette 1.10.0:docs/background.md [BackgroundTasks] (held)
- starlette 1.10.0:docs/early-hints.md [Request.send_early_hints] (held)
- starlette 1.10.0:docs/middleware.md [CORSMiddleware > CORSMiddleware Global Enforcement] (held)
- starlette 1.10.0:docs/middleware.md [OpenTelemetry > Exclude URLs] (held)
- starlette 1.10.0:docs/release-notes.md [1.0.0rc1 (February 23, 2026) > Fixed] (held)
- starlette 1.10.0:docs/release-notes.md [1.0.0rc1 (February 23, 2026) > Removed] (held)
- starlette 1.10.0:docs/release-notes.md [1.2.0 (May 28, 2026) > Added] (held)
- starlette 1.10.0:docs/release-notes.md [1.5.0 (August 8, 2026) > Fixed] (held)
- starlette 1.10.0:docs/requests.md [Request > Request Files] (held)
- starlette 1.10.0:docs/responses.md [Response > Delete Cookie] (held)
- starlette 1.10.0:docs/staticfiles.md [StaticFiles] (held)
- starlette 1.10.0:docs/testclient.md [Asynchronous tests] (held)
- starlette 1.10.0:docs/testclient.md [HTTP trailers] (held)
- tanstack-query v4.36.1:docs/react/guides/infinite-queries.md [What happens when an infinite query needs to be refetched? > refetchPage] (held)
- tanstack-query v4.36.1:docs/react/guides/migrating-to-react-query-4.md [Breaking Changes > Query Keys (and Mutation Keys) need to be an Array] (held)
- tanstack-query v4.36.1:docs/react/guides/migrating-to-react-query-4.md [Breaking Changes > The idle state has been removed] (held)
- tanstack-query v4.36.1:docs/react/guides/migrating-to-react-query-4.md [Breaking Changes > The idle state has been removed > disabled queries] (held)
- tanstack-query v4.36.1:docs/react/guides/migrating-to-react-query-4.md [Breaking Changes > react-query is now @tanstack/react-query] (held)
- tanstack-query v4.36.1:docs/react/guides/queries.md [Query Basics > FetchStatus] (held)
- tanstack-query v4.36.1:docs/react/guides/queries.md [Query Basics > Why two different states?] (held)
- tanstack-query v4.36.1:docs/react/guides/ssr.md [Using Next.js > Using Hydration] (held)
- tanstack-query v5.0.0:docs/react/guides/advanced-ssr.md [Server Components & Next.js app router > Prefetching and de/hydrating data] (held)
- tanstack-query v5.0.0:docs/react/guides/migrating-to-v5.md [Breaking Changes > Callbacks on useQuery (and QueryObserver) have been removed] (held)
- tanstack-query v5.0.0:docs/react/guides/migrating-to-v5.md [Breaking Changes > Infinite queries now need a initialPageParam] (held)
- tanstack-query v5.0.0:docs/react/guides/migrating-to-v5.md [Breaking Changes > Removed keepPreviousData in favor of placeholderData identity function] (held)
- tanstack-query v5.0.0:docs/react/guides/migrating-to-v5.md [Breaking Changes > Rename cacheTime to gcTime] (held)
- tanstack-query v5.0.0:docs/react/guides/migrating-to-v5.md [Breaking Changes > The useErrorBoundary option has been renamed to throwOnError] (held)
- tanstack-query v5.0.0:docs/react/guides/migrating-to-v5.md [Breaking Changes > status: loading has been changed to status: pending and isLoading has been changed to isPending and isInitialLoading has now been renamed to isLoading] (held)
- tanstack-query v5.0.0:docs/react/guides/optimistic-updates.md [Via the UI > If the mutation and the query don't live in the same component] (held)
- tanstack-query v5.90.3:docs/framework/react/guides/filters.md [Utils > matchQuery] (held)
- tanstack-query v5.90.3:docs/framework/react/guides/migrating-to-v5.md [Breaking Changes > hashQueryKey has been renamed to hashKey] (held)
- tanstack-query v5.90.3:docs/framework/react/guides/optimistic-updates.md [Via the cache > Updating a single todo] (held)
- tanstack-query v5.90.3:docs/framework/react/guides/render-optimizations.md [select > memoization] (held)
- tanstack-query v5.90.3:docs/framework/react/guides/render-optimizations.md [structural sharing > referential identity] (held)
- tanstack-query v5.90.3:docs/framework/react/guides/suspense.md [throwOnError default] (held)
- tanstack-query v5.90.3:docs/framework/react/typescript.md [Typing the error field > Registering a global Error] (held)
- zod v3.23.8:README.md [Guides and concepts > Type inference] (held)
- zod v3.23.8:README.md [Objects > .catchall] (held)
- zod v3.23.8:README.md [Objects > .passthrough] (held)
- zod v3.23.8:README.md [Objects > .strict] (held)
- zod v3.23.8:README.md [Schema methods > .brand] (held)
- zod v3.23.8:README.md [Schema methods > .catch] (held)
- zod v3.23.8:README.md [Schema methods > .default] (held)
- zod v3.23.8:README.md [Schema methods > .pipe > You can use .pipe() to fix common issues with z.coerce.] (held)
- zod v3.23.8:README.md [Schema methods > .refine > Arguments] (held)
- zod v3.23.8:README.md [Schema methods > .refine > Customize error path] (held)
- zod v3.23.8:README.md [Schema methods > .safeParse] (held)
- zod v3.23.8:README.md [Schema methods > .superRefine > Abort early] (held)
- zod v3.23.8:README.md [Schema methods > .transform > Chaining order] (held)
- zod v3.23.8:README.md [Strings > IP addresses] (held)
- zod v4.0.17:packages/docs/content/metadata.mdx [Metadata > .meta()] (held)
- zod v4.0.17:packages/docs/content/packages/mini.mdx [When (not) to use Zod Mini > Backend development] (held)
- zod v4.0.17:packages/docs/content/packages/mini.mdx [ZodMiniType > .check()] (held)
- zod v4.0.17:packages/docs/content/v4/changelog.mdx [ZodError > changes error map precedence] (held)
- zod v4.0.17:packages/docs/content/v4/changelog.mdx [z.object() > deprecates .strict() and .passthrough()] (held)
- zod v4.0.17:packages/docs/content/v4/changelog.mdx [z.record() > drops single argument usage] (held)
- zod v4.0.17:packages/docs/content/v4/versioning.mdx [Update — July 8th, 2025] (held)
- zod v4.6.7:packages/docs/content/api.mdx [Objects > z.deepPartial() [#deep-partial]] (held)
- zod v4.6.7:packages/docs/content/api.mdx [Primitives > Coercion] (held)
- zod v4.6.7:packages/docs/content/api.mdx [Records > z.looseRecord] (held)
- zod v4.6.7:packages/docs/content/api.mdx [Records > z.record] (held)
- zod v4.6.7:packages/docs/content/api.mdx [String formats > IBANs] (held)
- zod v4.6.7:packages/docs/content/api.mdx [String formats > ISO datetimes] (held)
- zod v4.6.7:packages/docs/content/blog/zod-4-5.mdx [Bug fixes > ⚠️ z.iso.datetime() requires seconds] (held)
- zod v4.6.7:packages/docs/content/codecs.mdx [How encoding works > Transforms] (held)
- zod v4.6.7:packages/docs/content/codecs.mdx [How encoding works > isoDatetimeToDate] (held)
- zod v4.6.7:packages/docs/content/error-customization.mdx [Internationalization > Locales] (held)
- zod v4.6.7:packages/docs/content/json-schema.mdx [z.toJSONSchema() > metadata] (held)
- zod v4.6.7:packages/docs/content/metadata.mdx [Metadata > .meta()] (held)
- zod v4.6.7:packages/docs/content/v4/changelog.mdx [z.object() > changes z.unknown() optionality] (held)

## `h3-max-4000` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 299 | 89.5% | 0 | 0 | 69 / 569 / 900 | 40.5% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 390 | 87.0% | 0 | 0 | 69 / 540 / 932 | 39.0% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 396 | 85.7% | 0 | 0 | 69 / 561 / 989 | 38.1% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 233 | 93.8% | 0 | 0 | 153 / 641 / 3017 | 10.7% | 23 / 0 | 0 / 0 | 23 | 113 | 67 |
| pydantic | v2.5.3 | 67 (1) | 537 | 91.7% | 0 | 0 | 138 / 832 / 3017 | 12.1% | 56 / 40 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 644 | 91.4% | 0 | 0 | 160 / 910 / 2762 | 10.2% | 77 / 59 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 475 | 95.2% | 0 | 0 | 140 / 585 / 3424 | 14.5% | 103 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 550 | 100.0% | 0 | 0 | 152 / 637 / 3269 | 12.4% | 110 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 1253 | 100.0% | 0 | 0 | 81 / 528 / 3571 | 38.1% | 211 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 97 | 72.2% | 2 | 0 | 157 / 814 / 996 | 13.4% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 243 | 100.0% | 1 | 5289 | 169 / 630 / 2306 | 14.0% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 351 | 100.0% | 1 | 6157 | 183 / 684 / 8645 | 12.5% | 24 / 3 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 1852 | 84.6% | 0 | 0 | 103 / 765 / 2493 | 24.2% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 2099 | 92.3% | 0 | 0 | 110 / 824 / 3582 | 22.3% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 2329 | 82.1% | 0 | 0 | 120 / 828 / 3582 | 21.8% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

Sections that start no chunk under `h3-max-4000`:

- electron v30.0.0:docs/tutorial/esm.md [ES Modules (ESM) in Electron > Main process > Caveats > You must use await generously before the app's ready event] (held)
- electron v30.0.0:docs/tutorial/esm.md [ES Modules (ESM) in Electron > Preload scripts > Caveats > Sandboxed preload scripts can't use ESM imports] (held)
- electron v30.0.0:docs/tutorial/launch-app-from-url-in-another-app.md [Deep Links > Examples > Main Process (main.js) > Windows and Linux code:] (held)
- electron v30.0.0:docs/tutorial/security.md [Security > Checklist: Security recommendations > 14. Disable or limit creation of new windows > How?] (held)
- electron v38.0.0:docs/api/navigation-history.md [Class: NavigationHistory > Instance Methods > navigationHistory.restore(options)] (held)
- electron v38.0.0:docs/tutorial/security.md [Security > Checklist: Security recommendations > 19. Check which fuses you can change > Why?] (held)
- electron v45.3.2:docs/api/base-window.md [BaseWindow > Class: BaseWindow > Instance Events > Event: 'persisted-state-restored'] (held)
- electron v45.3.2:docs/api/base-window.md [BaseWindow > Class: BaseWindow > Static Methods > BaseWindow.clearPersistedState(name)] (held)
- electron v45.3.2:docs/api/session.md [session > Class: Session > Instance Methods > ses.registerLocalAIHandler(handler) Experimental] (held)
- electron v45.3.2:docs/tutorial/offscreen-rendering.md [Offscreen Rendering > Overview > Rendering Modes > GPU accelerated] (held)
- electron v45.3.2:docs/tutorial/offscreen-rendering.md [Offscreen Rendering > Overview > Rendering Modes > Software output device] (held)
- pydantic v1.10.22:docs/mypy_plugin.md [Plugin Capabilities > Respect Config.allow_mutation] (held)
- pydantic v2.14.3:docs/concepts/alias.md [Alias Configuration > ConfigDict Settings > Validation] (held)
- pydantic v2.14.3:docs/concepts/alias.md [Alias Configuration > Runtime Settings > Validation] (held)
- pydantic v2.14.3:docs/concepts/experimental.md [Experimental Features > Partial Validation > Limitations of Partial Validation > TypeAdapter only] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to Handling of Standard Types > Required, optional, and nullable fields] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to validators > @validator and @root_validator are deprecated] (held)
- starlette 0.27.0:docs/middleware.md [Pure ASGI Middleware > Gotchas > ASGI middleware should be stateless] (held)
- starlette 0.27.0:docs/requests.md [Request > Client Address] (held)
- starlette 0.52.1:docs/middleware.md [CORSMiddleware > Private Network Access (PNA)] (held)
- starlette 0.52.1:docs/release-notes.md [0.39.0 (September 23, 2024) > Added] (held)
- starlette 0.52.1:docs/requests.md [Request > Other state] (held)
- starlette 1.10.0:docs/release-notes.md [1.0.0rc1 (February 23, 2026) > Fixed] (held)
- starlette 1.10.0:docs/release-notes.md [1.2.0 (May 28, 2026) > Added] (held)
- starlette 1.10.0:docs/release-notes.md [1.5.0 (August 8, 2026) > Fixed] (held)
- starlette 1.10.0:docs/responses.md [Response > Delete Cookie] (held)
- tanstack-query v4.36.1:docs/react/guides/migrating-to-react-query-4.md [Breaking Changes > The idle state has been removed > disabled queries] (held)
- zod v3.23.8:README.md [Schema methods > .pipe > You can use .pipe() to fix common issues with z.coerce.] (held)
- zod v3.23.8:README.md [Schema methods > .refine > Arguments] (held)
- zod v3.23.8:README.md [Schema methods > .refine > Customize error path] (held)
- zod v3.23.8:README.md [Schema methods > .superRefine > Abort early] (held)
- zod v3.23.8:README.md [Schema methods > .transform > Chaining order] (held)

## `merge-400` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 184 | 68.4% | 0 | 0 | 160 / 561 / 891 | 4.3% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 236 | 73.9% | 0 | 0 | 153 / 605 / 932 | 3.8% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 250 | 82.1% | 0 | 0 | 153 / 560 / 989 | 3.2% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 194 | 68.8% | 0 | 0 | 215 / 637 / 3017 | 1.6% | 23 / 0 | 0 / 0 | 23 | 91 | 67 |
| pydantic | v2.5.3 | 67 (1) | 440 | 87.5% | 0 | 0 | 207 / 830 / 3017 | 5.7% | 56 / 33 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 568 | 80.0% | 0 | 0 | 213 / 930 / 2762 | 6.2% | 77 / 52 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 388 | 90.5% | 0 | 0 | 184 / 644 / 3424 | 5.1% | 103 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 455 | 90.5% | 0 | 0 | 191 / 679 / 3269 | 4.0% | 110 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 796 | 92.0% | 0 | 0 | 176 / 656 / 3571 | 9.7% | 211 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 88 | 77.8% | 2 | 0 | 200 / 564 / 996 | 0.0% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 182 | 80.0% | 1 | 5289 | 237 / 701 / 2306 | 1.1% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 273 | 71.9% | 1 | 6157 | 237 / 761 / 8645 | 1.1% | 24 / 3 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 1521 | 69.2% | 0 | 0 | 171 / 544 / 2493 | 1.4% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 1768 | 46.2% | 0 | 0 | 177 / 628 / 3582 | 1.2% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 1979 | 78.6% | 0 | 0 | 181 / 627 / 3582 | 1.4% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

Sections that start no chunk under `merge-400`:

- electron v30.0.0:docs/api/app.md [app > Events > Event: 'second-instance'] (held)
- electron v30.0.0:docs/api/app.md [app > Methods > app.setAsDefaultProtocolClient(protocol[, path, args])] (held)
- electron v30.0.0:docs/api/context-bridge.md [contextBridge > Methods > contextBridge.exposeInMainWorld(apiKey, api)] (held)
- electron v30.0.0:docs/api/web-contents-view.md [WebContentsView > Class: WebContentsView extends View > new WebContentsView([options])] (held)
- electron v30.0.0:docs/tutorial/context-isolation.md [Context Isolation > What is it?] (held)
- electron v30.0.0:docs/tutorial/esm.md [ES Modules (ESM) in Electron > Main process > Caveats > You must use await generously before the app's ready event] (held)
- electron v30.0.0:docs/tutorial/process-model.md [Process Model > Why not a single process?] (held)
- electron v30.0.0:docs/tutorial/sandbox.md [Process Sandboxing > Configuring the sandbox > Disabling the sandbox for a single process] (held)
- electron v38.0.0:docs/api/app.md [app > Methods > app.getPath(name)] (held)
- electron v38.0.0:docs/api/session.md [session > Class: Session > Instance Methods > ses.registerPreloadScript(script)] (held)
- electron v38.0.0:docs/api/utility-process.md [utilityProcess > Methods > utilityProcess.fork(modulePath[, args][, options])] (held)
- electron v38.0.0:docs/api/web-utils.md [webUtils > Methods > webUtils.getPathForFile(file)] (held)
- electron v38.0.0:docs/breaking-changes.md [Breaking Changes > Planned Breaking API Changes (32.0) > Removed: File.path] (held)
- electron v38.0.0:docs/breaking-changes.md [Breaking Changes > Planned Breaking API Changes (37.0) > Utility Process unhandled rejection behavior change] (held)
- electron v38.0.0:docs/breaking-changes.md [Breaking Changes > Planned Breaking API Changes (38.0) > Removed: ELECTRON_OZONE_PLATFORM_HINT environment variable] (held)
- electron v38.0.0:docs/breaking-changes.md [Breaking Changes > Planned Breaking API Changes (38.0) > Removed: macOS 11 support] (held)
- electron v38.0.0:docs/tutorial/asar-archives.md [Limitations of the Node API > Executing Binaries Inside ASAR archive] (held)
- electron v38.0.0:docs/tutorial/custom-title-bar.md [Custom Title Bar > Basic tutorial > Add native window controls Windows Linux] (held)
- electron v38.0.0:docs/tutorial/fuses.md [Electron Fuses > Current Fuses > runAsNode] (held)
- electron v38.0.0:docs/tutorial/fuses.md [Electron Fuses > How do I flip the fuses? > The easy way] (held)
- electron v38.0.0:docs/tutorial/fuses.md [Electron Fuses > What are fuses?] (held)
- electron v38.0.0:docs/tutorial/navigation-history.md [Navigation History > Accessing NavigationHistory] (held)
- electron v45.3.2:docs/api/safe-storage.md [safeStorage > Methods > safeStorage.decryptStringAsync(encrypted)] (held)
- electron v45.3.2:docs/breaking-changes.md [Breaking Changes > Breaking API Changes (45.0) > Removed: Node.js module shims and Buffer, setImmediate, clearImmediate globals in sandboxed preload scripts] (held)
- electron v45.3.2:docs/tutorial/local-ai-handler.md [Local AI Handler > Quick start > 1. Create the utility process script] (held)
- electron v45.3.2:docs/tutorial/offscreen-rendering.md [Offscreen Rendering > Overview > Rendering Modes > GPU accelerated] (held)
- electron v45.3.2:docs/tutorial/web-embeds.md [Web Embeds > Overview] (held)
- electron v45.3.2:docs/tutorial/window-state-persistence.md [Window State Persistence > Usage > Basic usage] (held)
- pydantic v1.10.22:docs/mypy_plugin.md [Plugin Capabilities > Respect Config.allow_mutation] (held)
- pydantic v1.10.22:docs/usage/models.md [ORM Mode (aka Arbitrary Class Instances)] (held)
- pydantic v1.10.22:docs/usage/types.md [Custom Data Types > Classes with __get_validators__] (held)
- pydantic v1.10.22:docs/usage/validation_decorator.md [Custom Config] (held)
- pydantic v1.10.22:docs/usage/validators.md [Validate Always] (held)
- pydantic v2.14.3:docs/concepts/alias.md [Alias Configuration > Runtime Settings > Validation] (held)
- pydantic v2.14.3:docs/concepts/experimental.md [Experimental Features > Partial Validation > Limitations of Partial Validation > TypeAdapter only] (held)
- pydantic v2.14.3:docs/concepts/fields.md [Discriminator] (held)
- pydantic v2.14.3:docs/concepts/performance.md [Performance tips > Failing early with FailFast] (held)
- pydantic v2.14.3:docs/concepts/types.md [Utility types > OnErrorOmit] (held)
- pydantic v2.14.3:docs/integrations/aws_lambda.md [Troubleshooting > Missing pydantic_core module] (held)
- pydantic v2.14.3:docs/integrations/logfire.md [Pydantic Logfire > Record failed validations] (held)
- pydantic v2.5.3:docs/concepts/json.md [JSON > Json Parsing] (held)
- pydantic v2.5.3:docs/concepts/performance.md [Performance tips > Use model_validate_json() not model_validate(json.loads(...))] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to validators > @validator and @root_validator are deprecated] (held)
- starlette 0.27.0:docs/authentication.md [Permissions] (held)
- starlette 0.27.0:docs/config.md [Secrets] (held)
- starlette 0.27.0:docs/middleware.md [Pure ASGI Middleware > Gotchas > ASGI middleware should be stateless] (held)
- starlette 0.27.0:docs/release-notes.md [0.26.0 > Deprecated] (held)
- starlette 0.27.0:docs/release-notes.md [0.27.0 > Fixed] (held)
- starlette 0.27.0:docs/requests.md [Request > Client Address] (held)
- starlette 0.52.1:docs/config.md [A full example] (held)
- starlette 0.52.1:docs/config.md [Secrets] (held)
- starlette 0.52.1:docs/release-notes.md [0.29.0 (July 13, 2023) > Added] (held)
- starlette 0.52.1:docs/release-notes.md [0.33.0 (December 1, 2023) > Added] (held)
- starlette 0.52.1:docs/release-notes.md [0.39.0 (September 23, 2024) > Added] (held)
- starlette 0.52.1:docs/requests.md [Request > Other state] (held)
- starlette 1.10.0:docs/release-notes.md [1.0.0rc1 (February 23, 2026) > Fixed] (held)
- starlette 1.10.0:docs/release-notes.md [1.2.0 (May 28, 2026) > Added] (held)
- starlette 1.10.0:docs/release-notes.md [1.5.0 (August 8, 2026) > Fixed] (held)
- starlette 1.10.0:docs/templates.md [Autoescape] (held)
- starlette 1.10.0:docs/testclient.md [Asynchronous tests] (held)
- tanstack-query v4.36.1:docs/react/guides/migrating-to-react-query-4.md [Breaking Changes > react-query is now @tanstack/react-query] (held)
- tanstack-query v4.36.1:docs/react/plugins/persistQueryClient.md [How It Works] (held)
- tanstack-query v5.0.0:docs/react/guides/migrating-to-v5.md [Breaking Changes > Removed keepPreviousData in favor of placeholderData identity function] (held)
- tanstack-query v5.0.0:docs/react/reference/hydration.md [HydrationBoundary] (held)
- tanstack-query v5.90.3:docs/framework/react/guides/filters.md [Utils > matchQuery] (held)
- tanstack-query v5.90.3:docs/framework/react/guides/render-optimizations.md [tracked properties] (held)
- zod v3.23.8:README.md [Guides and concepts > Type inference] (held)
- zod v3.23.8:README.md [Schema methods > .brand] (held)
- zod v3.23.8:README.md [Schema methods > .pipe > You can use .pipe() to fix common issues with z.coerce.] (held)
- zod v3.23.8:README.md [Schema methods > .transform > Chaining order] (held)
- zod v4.0.17:packages/docs/content/api.mdx [Template literals] (held)
- zod v4.0.17:packages/docs/content/packages/mini.mdx [ZodMiniType > .check()] (held)
- zod v4.0.17:packages/docs/content/v4/changelog.mdx [z.function()] (held)
- zod v4.0.17:packages/docs/content/v4/changelog.mdx [z.record() > drops single argument usage] (held)
- zod v4.0.17:packages/docs/content/v4/index.mdx [Refinements live inside schemas] (held)
- zod v4.6.7:packages/docs/content/api.mdx [Primitives > Coercion] (held)
- zod v4.6.7:packages/docs/content/api.mdx [Records > z.record] (held)
- zod v4.6.7:packages/docs/content/api.mdx [String formats > IBANs] (held)
- zod v4.6.7:packages/docs/content/api.mdx [String formats > ISO datetimes] (held)
- zod v4.6.7:packages/docs/content/blog/zod-4-5.mdx [Bug fixes > ⚠️ z.iso.datetime() requires seconds] (held)
- zod v4.6.7:packages/docs/content/blog/zod-4-5.mdx [z.deepPartial()] (held)
- zod v4.6.7:packages/docs/content/codecs.mdx [How encoding works > isoDatetimeToDate] (held)
- zod v4.6.7:packages/docs/content/json-schema.mdx [z.toJSONSchema() > metadata] (held)
- zod v4.6.7:packages/docs/content/packages/mini.mdx [No default locale] (held)

## Examples (`default`)

- wrong heading path: Class not fully defined {#class-not-fully-defined}
- wrong heading path: Custom JSON Schema {#custom-json-schema}
- wrong heading path: Decorator on missing field {#decorator-missing-field}
- wrong heading path: Discriminator no field {#discriminator-no-field}
- wrong heading path: Discriminator alias type {#discriminator-alias-type}
- wrong heading path: Discriminator needs literal {#discriminator-needs-literal}
- wrong heading path: Discriminator alias {#discriminator-alias}
- wrong heading path: Invalid discriminator validator {#discriminator-validator}
- wrong heading path: Callable discriminator case with no tag {#callable-discriminator-no-tag}
- wrong heading path: TypedDict version {#typed-dict-version}
- mkdocs_blocks_as_code: starlette 0.27.0:docs/authentication.md, starlette 0.27.0:docs/background.md, starlette 0.27.0:docs/middleware.md, starlette 0.27.0:docs/requests.md, starlette 0.27.0:docs/templates.md, starlette 0.27.0:docs/testclient.md, starlette 0.52.1:docs/applications.md, starlette 0.52.1:docs/authentication.md, starlette 0.52.1:docs/background.md, starlette 0.52.1:docs/config.md
- unexpanded_includes: pydantic v1.10.22:docs/changelog.md, pydantic v1.10.22:docs/datamodel_code_generator.md, pydantic v1.10.22:docs/hypothesis_plugin.md, pydantic v1.10.22:docs/index.md, pydantic v1.10.22:docs/mypy_plugin.md, pydantic v1.10.22:docs/usage/dataclasses.md, pydantic v1.10.22:docs/usage/devtools.md, pydantic v1.10.22:docs/usage/exporting_models.md, pydantic v1.10.22:docs/usage/model_config.md, pydantic v1.10.22:docs/usage/models.md
- articles_without_chunks: pydantic v2.5.3:docs/api/pydantic_extra_types_mac_address.md, tanstack-query v4.36.1:docs/vue/community/lukemorales-query-key-factory.md, tanstack-query v4.36.1:docs/vue/community/tkdodos-blog.md, tanstack-query v4.36.1:docs/vue/guides/caching.md, tanstack-query v4.36.1:docs/vue/guides/custom-logger.md, tanstack-query v4.36.1:docs/vue/guides/does-this-replace-client-state.md, tanstack-query v4.36.1:docs/vue/guides/filters.md, tanstack-query v4.36.1:docs/vue/guides/network-mode.md, tanstack-query v4.36.1:docs/vue/guides/prefetching.md, tanstack-query v4.36.1:docs/vue/guides/query-invalidation.md
- headings_extra: zod v3.23.8:README.md, zod v4.0.17:packages/docs/content/packages/core.mdx, zod v4.6.7:packages/docs/content/packages/core.mdx
- cuts_in_code_fence: zod v3.23.8:README.md, zod v4.0.17:packages/docs/content/packages/core.mdx, zod v4.6.7:packages/docs/content/packages/core.mdx
- headings_missed: zod v4.0.17:README.md, zod v4.0.17:packages/docs/content/api.mdx, zod v4.0.17:packages/docs/content/error-customization.mdx, zod v4.0.17:packages/docs/content/metadata.mdx, zod v4.0.17:packages/docs/content/v4/changelog.mdx, zod v4.6.7:README.md, zod v4.6.7:packages/docs/content/api.mdx, zod v4.6.7:packages/docs/content/basics.mdx, zod v4.6.7:packages/docs/content/codecs.mdx, zod v4.6.7:packages/docs/content/error-customization.mdx
- lost_chars: zod v4.0.17:README.md, zod v4.6.7:README.md
