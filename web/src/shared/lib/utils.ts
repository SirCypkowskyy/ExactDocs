import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// The type scale in styles.css (@theme) names font sizes `text-small`, `text-body`, ...; without
// this, tailwind-merge reads them as colours and drops a `text-white` next to them.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [
        { text: ["small", "body", "section", "title", "figure", "mono", "reader-title"] },
      ],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
