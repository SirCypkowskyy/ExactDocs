import { Check, Monitor, Moon, Sun } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import { setTheme, THEMES, type Theme, useTheme } from "@/shared/lib/theme";
import { cn } from "@/shared/lib/utils";

const LABELS: Record<Theme, string> = { light: "Light", dark: "Dark", system: "System" };
const ICONS = { light: Sun, dark: Moon, system: Monitor } as const;

/**
 * Light, Dark or System. The button names the current choice ("Theme: System, dark now"); the menu
 * is a radio group, so a screen reader announces which item is checked.
 */
export function ThemeSwitch({ className }: { className?: string }) {
  const { theme, resolved } = useTheme();
  const Icon = theme === "system" ? Monitor : resolved === "dark" ? Moon : Sun;
  const label =
    theme === "system"
      ? `Theme: System (${LABELS[resolved].toLowerCase()})`
      : `Theme: ${LABELS[theme]}`;
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        aria-label={label}
        title={label}
        className={cn(
          "inline-flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground outline-none transition-[color,background-color,transform] duration-(--dur-fast) ease-(--ease-out) focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] data-[state=open]:bg-accent data-[state=open]:text-foreground [@media(hover:hover)]:size-9 [@media(hover:hover)]:hover:bg-accent [@media(hover:hover)]:hover:text-foreground",
          className,
        )}
      >
        <Icon aria-hidden="true" className="size-[1.125rem]" />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className="z-50 min-w-36 origin-(--radix-dropdown-menu-content-transform-origin) rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-md outline-none transition-none data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-safe:data-[state=open]:zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:duration-(--dur-fast) data-[state=open]:ease-(--ease-out) data-[state=closed]:duration-(--dur-fast)"
        >
          <DropdownMenu.Label className="px-2 py-1.5 text-small font-medium text-muted-foreground">
            Theme
          </DropdownMenu.Label>
          <DropdownMenu.RadioGroup value={theme} onValueChange={(v) => setTheme(v as Theme)}>
            {THEMES.map((option) => {
              const OptionIcon = ICONS[option];
              return (
                <DropdownMenu.RadioItem
                  key={option}
                  value={option}
                  className="flex min-h-11 cursor-pointer items-center gap-2 rounded-md px-2 text-body outline-none select-none data-highlighted:bg-accent data-highlighted:text-accent-foreground [@media(hover:hover)]:min-h-8"
                >
                  <OptionIcon aria-hidden="true" className="size-4 text-muted-foreground" />
                  <span className="flex-1">{LABELS[option]}</span>
                  <DropdownMenu.ItemIndicator>
                    <Check aria-hidden="true" className="size-4 text-route" />
                  </DropdownMenu.ItemIndicator>
                </DropdownMenu.RadioItem>
              );
            })}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
