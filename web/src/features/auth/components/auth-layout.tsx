import type { ReactNode } from "react";
import { useMessages } from "@/shared/lib/i18n";
import { usePageTitle } from "@/shared/lib/use-page-title";
import {
  InterfaceMenu,
  LanguageMenu,
  TextSizeControl,
  ThemeButton,
} from "@/shared/ui/interface-controls";
import { Wordmark } from "@/shared/ui/wordmark";
import { messages } from "../messages";

/**
 * The frame for setup and sign-in, after the free shadcnblocks "Login 2" block (a wordmark over
 * one centred form card): the card is the app's white sheet on its tinted frame, and the line
 * under it says what the server is for.
 */
export function AuthLayout({
  title,
  intro,
  children,
}: {
  title: string;
  intro: string;
  children: ReactNode;
}) {
  const heading = usePageTitle(title);
  const t = useMessages(messages);
  return (
    <div className="relative grid flex-1 place-items-center bg-frame px-4 py-12">
      <div className="absolute top-2 right-2 flex items-center sm:top-3 sm:right-3">
        <TextSizeControl />
        <ThemeButton />
        <LanguageMenu />
        <InterfaceMenu settings={null} />
      </div>
      <div className="w-full max-w-[25rem]">
        <div className="rise mb-6 flex justify-center">
          <Wordmark className="h-12" />
        </div>
        <main
          id="main"
          className="rise rounded-sheet border border-border bg-background px-6 py-7 sm:px-8 sm:py-8"
          style={{ "--i": 1 } as React.CSSProperties}
        >
          <h1 ref={heading} tabIndex={-1} className="text-title font-semibold outline-none">
            {title}
          </h1>
          <p className="mt-1.5 text-body text-muted-foreground">{intro}</p>
          <div className="mt-6">{children}</div>
        </main>
        <p
          className="rise mx-auto mt-6 max-w-[22rem] text-center text-body text-muted-foreground text-balance"
          style={{ "--i": 2 } as React.CSSProperties}
        >
          {t.layout.tagline}
        </p>
      </div>
    </div>
  );
}
