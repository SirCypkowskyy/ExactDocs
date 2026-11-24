import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetPreferences, setPreferences } from "@/shared/lib/preferences";
import { Button } from "./button";
import { ConfirmDialog, TypedConfirmDialog } from "./confirm-dialog";

/** A page with a button that opens the confirmation; the caller closes it on success. */
function Remove({
  onConfirm = () => {},
  pending = false,
  error,
  typed = false,
  initialFocus,
  tone,
  cancelLabel,
}: {
  onConfirm?: (close: () => void) => void;
  pending?: boolean;
  error?: string;
  typed?: boolean;
  initialFocus?: "cancel" | "phrase";
  tone?: "default" | "destructive";
  cancelLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const props = {
    open,
    onOpenChange: setOpen,
    title: "Remove v1.4.0?",
    description: "Its articles leave search.",
    confirmLabel: "Remove version",
    pending,
    error,
    onConfirm: () => onConfirm(() => setOpen(false)),
    ...(tone && { tone }),
    ...(cancelLabel && { cancelLabel }),
  };
  return (
    <>
      <Button onClick={() => setOpen(true)}>Remove…</Button>
      {typed ? (
        <TypedConfirmDialog {...props} phrase="v1.4.0" {...(initialFocus && { initialFocus })} />
      ) : (
        <ConfirmDialog {...props} />
      )}
    </>
  );
}

const open = async () => {
  await userEvent.click(screen.getByRole("button", { name: "Remove…" }));
  return screen.findByRole("alertdialog", { name: "Remove v1.4.0?" });
};

afterEach(() => resetPreferences());

describe("ConfirmDialog", () => {
  it("is an alert dialog that asks, says what happens and puts focus on Cancel", async () => {
    render(<Remove />);
    const dialog = await open();
    expect(dialog).toHaveAccessibleDescription("Its articles leave search.");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(within(dialog).getByRole("button", { name: "Remove version" })).toBeInTheDocument();
  });

  it("stays open on a click outside, and Escape or Cancel takes focus back to the opener", async () => {
    render(<Remove />);
    const dialog = await open();
    const overlay = document.querySelector("[data-slot='alert-dialog-overlay']") as HTMLElement;
    fireEvent.pointerDown(overlay);
    fireEvent.click(overlay);
    expect(dialog).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove…" })).toHaveFocus();

    await userEvent.click(within(await open()).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("confirms and stays open until the caller closes it", async () => {
    const asked = vi.fn();
    render(<Remove onConfirm={asked} />);
    const dialog = await open();
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove version" }));
    expect(asked).toHaveBeenCalledOnce();
    expect(dialog).toBeInTheDocument();
  });

  it("closes once the caller says it worked", async () => {
    render(<Remove onConfirm={(close) => close()} />);
    const dialog = await open();
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove version" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("cannot be left or sent twice while the request runs", async () => {
    const asked = vi.fn();
    render(<Remove pending onConfirm={asked} />);
    const dialog = await open();
    const confirm = within(dialog).getByRole("button", { name: "Remove version" });
    expect(confirm).toHaveAttribute("aria-busy", "true");
    await userEvent.click(confirm);
    expect(asked).not.toHaveBeenCalled();

    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveAttribute("aria-disabled", "true");
    await userEvent.keyboard("{Escape}");
    expect(dialog).toBeInTheDocument();
  });

  it("says inside the dialog why it did not work", async () => {
    render(<Remove error="The version is the default; pick another first." />);
    const dialog = await open();
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "The version is the default; pick another first.",
    );
  });

  it("offers the refusal's way out as a link after its sentence", async () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={() => {}}
        title="Remove v1.4.0?"
        confirmLabel="Remove version"
        error="Your session ended."
        errorLink={{ href: "/sign-in", label: "Sign in" }}
        onConfirm={() => {}}
      />,
    );
    const alert = within(await screen.findByRole("alertdialog")).getByRole("alert");
    expect(alert).toHaveTextContent("Your session ended. Sign in");
    expect(within(alert).getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/sign-in",
    );
  });

  it("can be a plain primary confirm with its own way out", async () => {
    render(<Remove tone="default" cancelLabel="Keep it" />);
    const dialog = await open();
    expect(within(dialog).getByRole("button", { name: "Keep it" })).toHaveFocus();
    expect(within(dialog).queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });
});

describe("TypedConfirmDialog", () => {
  it("stays inert until the phrase is typed exactly, then Enter confirms", async () => {
    const asked = vi.fn();
    render(<Remove typed onConfirm={asked} />);
    const dialog = await open();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    const field = within(dialog).getByLabelText("Type v1.4.0 to confirm");
    const confirm = within(dialog).getByRole("button", { name: "Remove version" });
    expect(confirm).toHaveAttribute("aria-disabled", "true");

    await userEvent.type(field, "v1.4");
    await userEvent.click(confirm);
    expect(asked).not.toHaveBeenCalled();

    await userEvent.type(field, ".0{Enter}");
    expect(confirm).not.toHaveAttribute("aria-disabled");
    expect(asked).toHaveBeenCalledOnce();
  });

  it("starts empty every time it opens", async () => {
    render(<Remove typed />);
    let dialog = await open();
    await userEvent.type(within(dialog).getByLabelText("Type v1.4.0 to confirm"), "v1.4.0");
    await userEvent.keyboard("{Escape}");

    dialog = await open();
    expect(within(dialog).getByLabelText("Type v1.4.0 to confirm")).toHaveValue("");
  });

  it("can put focus in the field when typing is plainly the next step", async () => {
    render(<Remove typed initialFocus="phrase" />);
    const dialog = await open();
    expect(within(dialog).getByLabelText("Type v1.4.0 to confirm")).toHaveFocus();
  });

  it("asks for the phrase in Polish", async () => {
    setPreferences({ language: "pl" });
    render(<Remove typed />);
    const dialog = await open();
    expect(within(dialog).getByLabelText("Wpisz v1.4.0, aby potwierdzić")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Anuluj" })).toHaveFocus();
  });
});
