import type { KeyboardEvent } from "react";
import { INPUT_ID } from "./search-box";

/** True while a version's own search box is on the page; it owns the `/` key then. */
export const hasVersionBox = () => document.getElementById(INPUT_ID) !== null;

/** The visible global box (the header's from `sm`, the page's below it) takes focus. */
export const focusGlobalInput = () => {
  const boxes = [...document.querySelectorAll<HTMLInputElement>("input[data-global-search]")];
  (boxes.find((box) => box.offsetParent !== null) ?? boxes[0])?.focus();
};

export const onArrows = (focusInput: () => void) => (event: KeyboardEvent<HTMLElement>) => {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  const links = [...event.currentTarget.querySelectorAll<HTMLElement>("a[data-result]")];
  const at = links.indexOf(document.activeElement as HTMLElement);
  if (at < 0) return;
  event.preventDefault();
  if (event.key === "ArrowUp" && at === 0) focusInput();
  else
    links[
      Math.min(Math.max(at + (event.key === "ArrowDown" ? 1 : -1), 0), links.length - 1)
    ]?.focus();
};
