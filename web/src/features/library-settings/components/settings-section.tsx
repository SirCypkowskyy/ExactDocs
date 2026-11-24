import {
  Cpu,
  FolderTree,
  GitBranch,
  type LucideIcon,
  RefreshCw,
  Settings2,
  Share2,
  ShieldAlert,
} from "lucide-react";
import type { ReactNode, Ref } from "react";
import type { SectionId } from "../model/sections";

/** Each section's icon (icons-motion.md): small and muted before its heading; it only labels. */
const ICONS = {
  details: Settings2,
  paths: FolderTree,
  versions: GitBranch,
  ai: Cpu,
  sync: RefreshCw,
  sharing: Share2,
  danger: ShieldAlert,
} as const satisfies Record<SectionId, LucideIcon>;

/** A section's heading: its icon and title. The id is `<id>-heading`, which the nav points at. */
function SectionHeading({
  id,
  headingRef,
  children,
}: {
  id: SectionId;
  headingRef?: Ref<HTMLHeadingElement> | undefined;
  children: ReactNode;
}) {
  const Icon = ICONS[id];
  return (
    <h2
      id={`${id}-heading`}
      ref={headingRef}
      tabIndex={-1}
      className="flex items-center gap-2 text-section font-semibold outline-none [scroll-margin-top:5rem]"
    >
      <Icon aria-hidden="true" className="size-4 flex-none text-muted-foreground" />
      {children}
    </h2>
  );
}

/**
 * One settings section: its title and one line of help on the left, its controls on the right
 * (stacked on a phone). Sections are told apart by a rule, not by boxes. The heading's id is
 * `<id>-heading`, which the section nav and the tests point at.
 */
export function SettingsSection({
  id,
  title,
  description,
  headingRef,
  children,
}: {
  id: SectionId;
  title: ReactNode;
  description: ReactNode;
  headingRef?: Ref<HTMLHeadingElement>;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={`${id}-heading`}
      className="scroll-mt-20 border-t border-rule py-8 first:border-t-0 first:pt-0 lg:grid lg:grid-cols-[14rem_minmax(0,1fr)] lg:gap-x-10"
    >
      <header className="mb-5 lg:mb-0">
        <SectionHeading id={id} headingRef={headingRef}>
          {title}
        </SectionHeading>
        <p className="mt-1 max-w-[60ch] text-body text-muted-foreground">{description}</p>
      </header>
      <div className="min-w-0 max-w-[40rem]">{children}</div>
    </section>
  );
}
