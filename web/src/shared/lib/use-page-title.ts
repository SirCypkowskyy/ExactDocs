import { useEffect, useRef } from "react";
import { useLanguage } from "./i18n";

/**
 * Names the page for the tab and for screen readers, and moves focus to its `<h1>` after a
 * navigation (attach the returned ref; give the heading `tabIndex={-1}`). A title that changes
 * only because the language did renames the tab but leaves focus where it is (the language menu).
 */
export function usePageTitle(title: string) {
  const heading = useRef<HTMLHeadingElement>(null);
  const language = useLanguage();
  const shownIn = useRef(language);
  useEffect(() => {
    document.title = `${title} - ExactDocs`;
    if (shownIn.current !== language) {
      shownIn.current = language;
      return;
    }
    heading.current?.focus({ preventScroll: true });
  }, [title, language]);
  return heading;
}
