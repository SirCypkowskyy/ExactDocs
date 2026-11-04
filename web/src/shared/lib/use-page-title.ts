import { useEffect, useRef } from "react";

/**
 * Names the page for the tab and for screen readers, and moves focus to its `<h1>` after a
 * navigation (attach the returned ref; give the heading `tabIndex={-1}`).
 */
export function usePageTitle(title: string) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${title} - ExactDocs`;
    heading.current?.focus({ preventScroll: true });
  }, [title]);
  return heading;
}
