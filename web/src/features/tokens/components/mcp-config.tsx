import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { common, useMessages } from "@/shared/lib/i18n";
import { cn } from "@/shared/lib/utils";
import { Button } from "@/shared/ui/button";
import { codeWell } from "@/shared/ui/recipes";
import { messages } from "../messages";

/** The MCP client config for this server, with a placeholder where the token goes. */
function mcpConfig(origin: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        exactdocs: {
          url: `${origin}/mcp`,
          headers: { Authorization: "Bearer exd_YOUR_TOKEN" },
        },
      },
    },
    null,
    2,
  );
}

/** A ready-to-paste client config: the real server address, a placeholder token, one-click copy. */
export function McpConfig({ className }: { className?: string }) {
  const t = useMessages(messages).config;
  const c = useMessages(common);
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const config = mcpConfig(window.location.origin);

  async function copy() {
    try {
      await navigator.clipboard.writeText(config);
      setCopied(true);
      toast.success(t.copied, { description: t.copiedHint });
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t.copyFailed);
    }
  }

  return (
    <div className={className}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-body font-medium">{t.heading}</h3>
        <Button
          variant="outline"
          size="sm"
          aria-label={copied ? t.copied : t.copyConfig}
          onClick={copy}
        >
          {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          {copied ? c.copied : c.copy}
        </Button>
      </div>
      <p className="mt-1 text-body text-muted-foreground">{t.description}</p>
      <section
        aria-label={t.label}
        // biome-ignore lint/a11y/noNoninteractiveTabindex: a snippet wider than the screen scrolls
        tabIndex={0}
        className="mt-3 overflow-x-auto rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <pre className={cn(codeWell, "whitespace-pre")}>
          <code>{config}</code>
        </pre>
      </section>
    </div>
  );
}
