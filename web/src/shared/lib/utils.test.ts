import { describe, expect, it } from "vitest";
import { cn } from "./utils";

describe("cn", () => {
  it("keeps a text colour next to a named type size, in either order", () => {
    expect(cn("text-white text-small")).toBe("text-white text-small");
    expect(cn("text-small text-muted-foreground")).toBe("text-small text-muted-foreground");
  });

  it("still lets a later size or colour win over an earlier one", () => {
    expect(cn("text-body", "text-small")).toBe("text-small");
    expect(cn("text-foreground", "text-muted-foreground")).toBe("text-muted-foreground");
  });
});
