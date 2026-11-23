import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { defineMessages, formatNumber, plural, useMessages } from "./i18n";
import { resetPreferences, setPreferences } from "./preferences";
import { relativeTime } from "./time";

afterEach(() => resetPreferences());

describe("plural", () => {
  const pl = (n: number) =>
    plural.pl(n, { one: "# biblioteka", few: "# biblioteki", many: "# bibliotek" });

  it("picks Polish one / few / many", () => {
    expect(pl(1)).toBe("1 biblioteka");
    expect(pl(2)).toBe("2 biblioteki");
    expect(pl(4)).toBe("4 biblioteki");
    expect(pl(5)).toBe("5 bibliotek");
    expect(pl(12)).toBe("12 bibliotek");
    expect(pl(22)).toBe("22 biblioteki");
    expect(pl(0)).toBe("0 bibliotek");
  });

  it("uses few for fractions unless other is given, and formats the count", () => {
    expect(pl(1.5)).toBe("1,5 biblioteki");
    expect(plural.en(1, { one: "# library", other: "# libraries" })).toBe("1 library");
    expect(plural.en(1200, { one: "# library", other: "# libraries" })).toBe("1,200 libraries");
  });
});

describe("formatNumber", () => {
  it("groups the way each language does", () => {
    expect(formatNumber(12345, "en")).toBe("12,345");
    expect(formatNumber(12345, "pl")).toBe("12 345");
    expect(formatNumber(1234, "pl")).toBe("1234");
  });
});

const messages = defineMessages(
  { hello: "Hello", count: (n: number) => plural.en(n, { one: "# token", other: "# tokens" }) },
  {
    hello: "Cześć",
    count: (n) => plural.pl(n, { one: "# token", few: "# tokeny", many: "# tokenów" }),
  },
);
function Greeting() {
  const t = useMessages(messages);
  return (
    <p>
      {t.hello}, {t.count(5)}
    </p>
  );
}

describe("useMessages", () => {
  it("renders English by default and re-renders in Polish when the language changes", () => {
    render(<Greeting />);
    expect(screen.getByText("Hello, 5 tokens")).toBeInTheDocument();
    act(() => setPreferences({ language: "pl" }));
    expect(screen.getByText("Cześć, 5 tokenów")).toBeInTheDocument();
  });
});

describe("relativeTime", () => {
  const now = Date.parse("2026-11-23T12:00:00Z");
  it("speaks the language it is given", () => {
    expect(relativeTime("2026-11-23T11:59:50Z", now, "pl")).toBe("przed chwilą");
    expect(relativeTime("2026-11-20T12:00:00Z", now, "pl")).toBe("3 dni temu");
    expect(relativeTime("2026-11-20T12:00:00Z", now, "en")).toBe("3 days ago");
  });
});
