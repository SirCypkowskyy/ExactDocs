import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { Toaster as Sonner, type ToasterProps } from "sonner";
import { useMessages } from "@/shared/lib/i18n";
import { useTheme } from "@/shared/lib/theme";
import { messages } from "./messages";

const Toaster = ({ ...props }: ToasterProps) => {
  const { resolved } = useTheme();
  const t = useMessages(messages).toasts;

  return (
    <Sonner
      theme={resolved}
      className="toaster group"
      containerAriaLabel={t.region}
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="spin size-4" />,
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)",
          "--width": "22rem",
        } as React.CSSProperties
      }
      position="bottom-right"
      toastOptions={{
        classNames: { toast: "font-sans text-body", description: "text-muted-foreground" },
        closeButtonAriaLabel: t.close,
      }}
      {...props}
    />
  );
};

export { Toaster };
