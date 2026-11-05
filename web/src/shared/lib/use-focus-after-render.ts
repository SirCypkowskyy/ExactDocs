import { useLayoutEffect, useState } from "react";

type Find = () => HTMLElement | null | undefined;

/**
 * Moves focus to an element that the current state change puts on screen (an error's field, a
 * field that just appeared). Focus moves in the same commit that shows the change, before the
 * browser handles the next click or key, so it never lands a frame late and pulls focus away from
 * a field the user has already moved to.
 */
export function useFocusAfterRender() {
  // A fresh object per request, so asking for the same element twice still moves focus.
  const [request, setRequest] = useState<{ find: Find }>();
  useLayoutEffect(() => {
    request?.find()?.focus();
  }, [request]);
  return (find: Find) => setRequest({ find });
}
