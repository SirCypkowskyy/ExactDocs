# Ingestion benchmark

The golden corpus (starlette, pydantic, tanstack-query, zod, electron; every pinned version) imported with each chunking configuration; BM25 over the golden set's 321 cases (`sha256:39f6f9d5e909d128`). Tokens are estimated at 4 characters; a small chunk is under 50 tokens. Definitions: docs/evals.md#the-ingestion-benchmark.

| configuration | coverage | held | cut fence / table / list | lost chars | tokens p50 / p95 / max | small | multi-top | empty / wrong path | headings missed / extra | BM25 recall@5 (exact) | MRR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `default` | 100.0% | 367/367 | 4 / 0 / 0 | 11446 of 7940351 | 88 / 507 / 9276 | 32.2% | 0.0% | 713 / 103 | 60 / 3 | 79.4% (79.4%) | 0.626 |
| `h2` | 49.9% | 367/367 | 3 / 0 / 0 | 11446 of 7940351 | 166 / 1311 / 22515 | 15.1% | 0.6% | 716 / 95 | 60 / 3 | 81.3% (37.8%) | 0.670 |
| `h3-max-4000` | 91.3% | 367/367 | 4 / 0 / 0 | 11446 of 7940351 | 114 / 727 / 9276 | 23.1% | 0.0% | 713 / 102 | 60 / 3 | 81.3% (76.4%) | 0.651 |
| `merge-400` | 77.1% | 367/367 | 4 / 0 / 0 | 11446 of 7940351 | 183 / 651 / 9276 | 3.0% | 5.1% | 713 / 88 | 60 / 3 | 74.2% (65.2%) | 0.604 |

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
| pydantic | v1.10.22 | 25 (0) | 246 | 100.0% | 0 | 0 | 147 / 582 / 3216 | 11.0% | 23 / 0 | 0 / 0 | 23 | 117 | 67 |
| pydantic | v2.5.3 | 67 (1) | 549 | 100.0% | 0 | 0 | 138 / 729 / 3226 | 12.4% | 56 / 40 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 674 | 100.0% | 0 | 0 | 156 / 871 / 3116 | 10.7% | 77 / 60 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 494 | 100.0% | 0 | 0 | 133 / 526 / 3572 | 15.0% | 100 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 571 | 100.0% | 0 | 0 | 142 / 598 / 3417 | 13.0% | 107 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 1318 | 100.0% | 0 | 0 | 70 / 506 / 3719 | 40.6% | 207 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 118 | 100.0% | 2 | 0 | 150 / 528 / 996 | 11.0% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 242 | 100.0% | 1 | 5289 | 164 / 630 / 2721 | 14.1% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 348 | 100.0% | 1 | 6157 | 183 / 684 / 9276 | 12.4% | 24 / 3 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 2852 | 100.0% | 0 | 0 | 70 / 395 / 2732 | 38.0% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 3174 | 100.0% | 0 | 0 | 77 / 440 / 5140 | 35.4% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 3455 | 100.0% | 0 | 0 | 80 / 464 / 5140 | 34.0% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

## `h2` per version

| project | version | articles (no chunk) | chunks | coverage | cut fence | lost chars | tokens p50 / p95 / max | small | empty / wrong path | headings missed / extra | no H1 | includes | MkDocs blocks as code |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 (0) | 157 | 57.9% | 0 | 0 | 122 / 875 / 3993 | 26.8% | 20 / 0 | 0 / 0 | 21 | 0 | 9 |
| starlette | 0.52.1 | 25 (0) | 222 | 60.9% | 0 | 0 | 114 / 759 / 3992 | 25.7% | 20 / 0 | 0 / 0 | 21 | 0 | 14 |
| starlette | 1.10.0 | 25 (0) | 232 | 53.6% | 0 | 0 | 106 / 875 / 3992 | 25.4% | 21 / 0 | 0 / 0 | 22 | 0 | 20 |
| pydantic | v1.10.22 | 25 (0) | 129 | 68.8% | 0 | 0 | 207 / 1513 / 5995 | 7.8% | 23 / 0 | 0 / 0 | 23 | 79 | 67 |
| pydantic | v2.5.3 | 67 (1) | 382 | 37.5% | 0 | 0 | 138 / 1124 / 8044 | 10.0% | 56 / 40 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 477 | 57.1% | 0 | 0 | 144 / 1476 / 8983 | 10.3% | 77 / 55 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 332 | 61.9% | 0 | 0 | 164 / 900 / 4911 | 11.1% | 101 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 362 | 61.9% | 0 | 0 | 174 / 900 / 5431 | 9.1% | 108 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 879 | 68.0% | 0 | 0 | 96 / 708 / 5971 | 33.5% | 208 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 37 | 16.7% | 1 | 0 | 311 / 4007 / 4411 | 5.4% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 143 | 72.0% | 1 | 5289 | 243 / 1171 / 3984 | 7.7% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 191 | 59.4% | 1 | 6157 | 259 / 1479 / 9276 | 7.3% | 24 / 0 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 685 | 34.6% | 0 | 0 | 195 / 1610 / 19229 | 10.8% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 787 | 26.9% | 0 | 0 | 211 / 1867 / 21312 | 10.3% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 862 | 14.3% | 0 | 0 | 220 / 1963 / 22515 | 9.9% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

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
- electron v45.3.2:docs/breaking-changes.md [Breaking Changes > Breaking API Changes (44.0) > API Changed: clipboard module rearchitected to align with the W3C Clipboard API] (held)
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
- pydantic v2.5.3:docs/concepts/fields.md [Field aliases > AliasPath and AliasChoices] (held)
- pydantic v2.5.3:docs/concepts/serialization.md [Serializing subclasses > Serializing with duck-typing] (held)
- pydantic v2.5.3:docs/concepts/serialization.md [Serializing subclasses > Subclass instances for fields of BaseModel, dataclasses, TypedDict] (held)
- pydantic v2.5.3:docs/concepts/unions.md [Union Modes > Smart Mode] (held)
- pydantic v2.5.3:docs/concepts/validators.md [Annotated Validators > Before, After, Wrap and Plain validators] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > BaseSettings has moved to pydantic-settings] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to Handling of Standard Types > Patterns / regex on strings] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to Handling of Standard Types > Required, optional, and nullable fields] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to config] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to pydantic.BaseModel] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to pydantic.Field] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to validators > @validator and @root_validator are deprecated] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Changes to validators > TypeError is no longer converted to ValidationError in validators] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Constrained types] (held)
- pydantic v2.5.3:docs/migration.md [Migration guide > Introduction of TypeAdapter] (held)
- starlette 0.27.0:docs/endpoints.md [WebSocketEndpoint] (held)
- starlette 0.27.0:docs/middleware.md [BaseHTTPMiddleware > Limitations] (held)
- starlette 0.27.0:docs/middleware.md [Pure ASGI Middleware > Gotchas > ASGI middleware should be stateless] (held)
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
- tanstack-query v5.90.3:docs/framework/react/guides/migrating-to-v5.md [Breaking Changes > Query defaults changes] (held)
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
- zod v3.23.8:README.md [Schema methods > .readonly] (held)
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
| pydantic | v1.10.22 | 25 (0) | 231 | 93.8% | 0 | 0 | 153 / 641 / 3216 | 10.8% | 23 / 0 | 0 / 0 | 23 | 113 | 67 |
| pydantic | v2.5.3 | 67 (1) | 533 | 91.7% | 0 | 0 | 136 / 830 / 3226 | 12.2% | 56 / 40 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 641 | 91.4% | 0 | 0 | 160 / 910 / 3116 | 10.3% | 77 / 59 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 472 | 95.2% | 0 | 0 | 140 / 550 / 3572 | 14.6% | 100 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 547 | 100.0% | 0 | 0 | 152 / 614 / 3417 | 12.4% | 107 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 1249 | 100.0% | 0 | 0 | 80 / 523 / 3719 | 38.3% | 207 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 97 | 72.2% | 2 | 0 | 157 / 814 / 996 | 13.4% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 241 | 100.0% | 1 | 5289 | 167 / 630 / 2721 | 14.1% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 348 | 100.0% | 1 | 6157 | 183 / 684 / 9276 | 12.4% | 24 / 3 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 1851 | 84.6% | 0 | 0 | 103 / 765 / 2732 | 24.2% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 2093 | 92.3% | 0 | 0 | 109 / 819 / 5140 | 22.4% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 2320 | 82.1% | 0 | 0 | 119 / 821 / 5140 | 21.9% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

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
| pydantic | v1.10.22 | 25 (0) | 192 | 68.8% | 0 | 0 | 216 / 637 / 3216 | 1.6% | 23 / 0 | 0 / 0 | 23 | 91 | 67 |
| pydantic | v2.5.3 | 67 (1) | 436 | 87.5% | 0 | 0 | 207 / 830 / 3226 | 5.7% | 56 / 33 | 0 / 0 | 56 | 0 | 118 |
| pydantic | v2.14.3 | 91 (0) | 566 | 80.0% | 0 | 0 | 213 / 930 / 3116 | 6.2% | 77 / 52 | 0 / 0 | 79 | 0 | 204 |
| tanstack-query | v4.36.1 | 140 (27) | 385 | 90.5% | 0 | 0 | 184 / 644 / 3572 | 5.2% | 100 / 0 | 0 / 0 | 113 | 0 | 0 |
| tanstack-query | v5.0.0 | 147 (25) | 452 | 90.5% | 0 | 0 | 189 / 659 / 3417 | 4.0% | 107 / 0 | 0 / 0 | 122 | 0 | 0 |
| tanstack-query | v5.90.3 | 327 (67) | 792 | 92.0% | 0 | 0 | 174 / 651 / 3719 | 9.7% | 207 / 0 | 0 / 0 | 170 | 0 | 0 |
| zod | v3.23.8 | 1 (0) | 88 | 77.8% | 2 | 0 | 200 / 564 / 996 | 0.0% | 1 / 0 | 0 / 1 | 1 | 0 | 0 |
| zod | v4.0.17 | 17 (0) | 180 | 80.0% | 1 | 5289 | 237 / 701 / 2721 | 1.1% | 17 / 0 | 27 / 1 | 17 | 0 | 0 |
| zod | v4.6.7 | 24 (0) | 270 | 71.9% | 1 | 6157 | 237 / 761 / 9276 | 0.7% | 24 / 3 | 33 / 1 | 24 | 0 | 0 |
| electron | v30.0.0 | 239 (0) | 1520 | 69.2% | 0 | 0 | 171 / 544 / 2732 | 1.4% | 12 / 0 | 0 / 0 | 34 | 0 | 0 |
| electron | v38.0.0 | 264 (0) | 1762 | 46.2% | 0 | 0 | 177 / 621 / 5140 | 1.2% | 14 / 0 | 0 / 0 | 37 | 0 | 0 |
| electron | v45.3.2 | 301 (0) | 1970 | 78.6% | 0 | 0 | 181 / 615 / 5140 | 1.4% | 14 / 0 | 0 / 0 | 40 | 0 | 0 |

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
