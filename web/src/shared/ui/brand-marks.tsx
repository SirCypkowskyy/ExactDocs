import { KeyRound } from "lucide-react";
import { type ComponentProps, useState } from "react";
import { cn } from "@/shared/lib/utils";

/*
 * Sign-in providers' marks (#506, blocks-map §3 "Brand icons"): the four built-in brands as inline
 * SVG (no icon package, no remote loads), and an operator's own icon for any other provider,
 * served by this server (`icon_url`). Google's G and Microsoft's four squares keep their colours,
 * as their sign-in guidelines ask; GitHub's and Discord's marks are drawn in the text colour, which
 * both brands allow and which keeps them legible in either theme. Every mark is decoration: the
 * provider's name is always written next to it.
 */

/** The providers the UI ships a mark for (`icon` in the API's provider summaries). */
export type BrandIcon = "google" | "microsoft" | "discord" | "github";

/** Every mark is decoration: `aria-hidden` is fixed on the element itself. */
type SvgProps = Omit<ComponentProps<"svg">, "children" | "viewBox" | "aria-hidden" | "focusable">;

function GoogleMark(props: SvgProps) {
  return (
    <svg viewBox="0 0 48 48" aria-hidden="true" focusable="false" {...props}>
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

function MicrosoftMark(props: SvgProps) {
  return (
    <svg viewBox="0 0 21 21" aria-hidden="true" focusable="false" {...props}>
      <rect x="1" y="1" width="9" height="9" fill="#F25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7FBA00" />
      <rect x="1" y="11" width="9" height="9" fill="#00A4EF" />
      <rect x="11" y="11" width="9" height="9" fill="#FFB900" />
    </svg>
  );
}

function DiscordMark(props: SvgProps) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false" {...props}>
      <path d="M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z" />
    </svg>
  );
}

function GitHubMark(props: SvgProps) {
  return (
    <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" focusable="false" {...props}>
      <path d="M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z" />
    </svg>
  );
}

const BRAND_MARKS: Record<BrandIcon, (props: SvgProps) => React.ReactNode> = {
  google: GoogleMark,
  microsoft: MicrosoftMark,
  discord: DiscordMark,
  github: GitHubMark,
};

/** True for a provider whose mark the UI ships (the sign-in page lists these first). */
export const isBrandIcon = (icon: unknown): icon is BrandIcon =>
  typeof icon === "string" && Object.hasOwn(BRAND_MARKS, icon);

/** Only a path on this server is loaded: the page never asks another origin for an image. */
const sameOrigin = (url: string | null | undefined): url is string =>
  typeof url === "string" && url.startsWith("/") && !url.startsWith("//") && !url.includes("\\");

const SIZES = { sm: "size-4", md: "size-5" } as const;

/**
 * A provider's mark: its built-in brand (`icon`), else the operator's icon from this server
 * (`iconUrl`, fitted into the same square), else a key. `sm` is 16 px (in buttons), `md` 20 px (in
 * lists). Always decorative (`aria-hidden`, empty `alt`).
 */
export function ProviderMark({
  icon,
  iconUrl,
  size = "sm",
  className,
}: {
  icon?: string | null | undefined;
  iconUrl?: string | null | undefined;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const [broken, setBroken] = useState<string>();
  const box = cn(SIZES[size], "shrink-0", className);
  if (isBrandIcon(icon)) {
    const Mark = BRAND_MARKS[icon];
    return <Mark data-brand={icon} className={box} />;
  }
  if (sameOrigin(iconUrl) && broken !== iconUrl) {
    const px = size === "sm" ? 16 : 20;
    return (
      <img
        src={iconUrl}
        alt=""
        aria-hidden="true"
        width={px}
        height={px}
        decoding="async"
        draggable={false}
        onError={() => setBroken(iconUrl)}
        className={cn(box, "object-contain")}
      />
    );
  }
  return <KeyRound aria-hidden="true" data-icon-motion="tilt" className={box} />;
}
