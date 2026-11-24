# Icons and their reactions (#486)

Every page and element gets an icon where it helps people scan or act, and every icon inside
something pressable gets a small reaction that says what the action does. The CSS lives in
`src/app/icon-motion.css`; opt in with `data-icon-motion="<name>"` on the lucide icon. Reduced
motion turns it all off. Icons are always `aria-hidden="true"`; the text or the accessible name
carries the meaning.

## Where icons go

| Element | Icon | Notes |
|---|---|---|
| Page header (`PageHeader`) | the page's nav icon (LibraryBig, Search, FlaskConical, Activity, Cpu, Users, ScrollText, UserRound for Account) | 20 px, muted, beside the title; not on auth pages |
| Section headings | one per section (Settings2, GitBranch, Tags, FolderTree, Share2, ShieldAlert for danger) | 16 px muted |
| Tabs | icon + label (KeyRound tokens, SlidersHorizontal interface, LogIn sign-in) | 16 px |
| Primary and secondary buttons | a leading icon for every action (Plus add, Save, RefreshCw sync, Trash2 delete, Copy, Download, Upload, ExternalLink, LogIn/LogOut, Send, Check) | 16 px |
| Menu items | every item has a leading icon | 16 px, muted |
| Badges for states | succeeded CircleCheck, failed CircleX, running LoaderCircle (spins), queued Clock, cancelled Ban, skipped CircleSlash, warning TriangleAlert | 12-14 px inside the pill |
| Empty states | one large muted icon (32 px) above the sentence | no animation |
| Alerts and toasts | CircleCheck success (draw), TriangleAlert warning, CircleAlert error (alert), Info | |
| Form fields | leading icon only in search/filter inputs (Search) and on credentials (KeyRound) | |
| Links that leave the app | ExternalLink after the text | |
| Row links | ChevronRight at the row's end | |

## Reaction per icon

| Reaction | Motion | Icons |
|---|---|---|
| `forward` | 2 px right on hover/focus | ArrowRight, ChevronRight, LogIn, LogOut, Send, CornerDownRight |
| `back` | 2 px left | ArrowLeft, ChevronLeft, Undo2 |
| `out` | 1.5 px up-right | ExternalLink, ArrowUpRight, Share2 |
| `down` | 1.5 px down | Download, ChevronsDown, ArrowDown |
| `up` | 1.5 px up | Upload, ArrowUp |
| `turn` | quarter turn | Plus, X (close) |
| `cog` | 60° on hover, 180° while pressed | Settings, Settings2, SlidersHorizontal |
| `refresh` | 60° on hover, 180° pressed, spins while `aria-busy` | RefreshCw, RotateCcw, History |
| `tilt` | -10° | Search, Pencil, Tag, Tags, KeyRound, Filter, Languages |
| `pop` | scale 1.12, 0.9 pressed | Copy, Check, Star, Sparkles, Eye, Bookmark, CircleCheck in buttons |
| `warn` | one small swing on hover/focus | Trash2, Ban, UserX, ShieldAlert, LogOut in destructive menus |
| `draw` | draws itself in once on arrival | Check / CircleCheck in "done" and success toasts |
| `alert` | one nudge on arrival | CircleAlert / TriangleAlert in form alerts and error toasts |

Not animated: icons that only label (page headers, section headings, empty states, badges other
than "running"), and the band's daily links (they move with their underline already).
