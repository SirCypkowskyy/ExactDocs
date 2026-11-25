import { formatNumber, useLanguage } from "@/shared/lib/i18n";
import { usePhoneLayout } from "@/shared/lib/use-media-query";
import { Count } from "@/shared/ui/data-table/cells";
import { Meter } from "@/shared/ui/meter";
import { Tooltip } from "@/shared/ui/tooltip";
import type { versionsMessages } from "../messages/versions";

/*
 * A version's sizes (#513) in the versions table (blocks-map §2.3, "Versions"): how many articles
 * it has, and how many of its chunks carry a vector from the embedding model.
 */

type Texts = (typeof versionsMessages)["en"]["table"];

/** Why the instance embeds nothing of this library, when the page can tell. */
export type NoEmbedding = keyof Texts["notEmbeddedWhy"];

/** The articles of a version: a figure under the column's header, "120 articles" on a phone card. */
export function ArticlesCell({ value, t }: { value: number; t: Texts }) {
  const phone = usePhoneLayout();
  if (phone) return <span className="num">{t.articles(value)}</span>;
  return <Count value={value} muted={value === 0} />;
}

/**
 * How much of a version is embedded: a Meter of `embedded` of `chunks`, named (and explained in
 * the tooltip) "1,234 of 2,000 chunks embedded", with the share beside it. A version with no
 * chunks is not indexed (a dash). With no vectors while the instance embeds nothing of this
 * library (`none`), it says "Not embedded" rather than an empty bar.
 */
export function EmbeddingCell({
  embedded,
  chunks,
  none,
  t,
}: {
  embedded: number;
  chunks: number;
  /** Set when the page knows nothing of the library is embedded, and why. */
  none: NoEmbedding | undefined;
  t: Texts;
}) {
  const language = useLanguage();
  const phone = usePhoneLayout();
  if (chunks === 0) {
    if (phone) return <span className="text-muted-foreground">{t.notIndexedShort}</span>;
    return (
      <Tooltip label={t.notIndexed}>
        <span className="text-muted-foreground">
          <span aria-hidden="true">—</span>
          <span className="sr-only">{t.notIndexed}</span>
        </span>
      </Tooltip>
    );
  }
  if (embedded === 0 && none) {
    return (
      <Tooltip label={t.notEmbeddedWhy[none]}>
        <span className="whitespace-nowrap text-muted-foreground">
          {t.notEmbedded}
          <span className="sr-only">. {t.notEmbeddedWhy[none]}</span>
        </span>
      </Tooltip>
    );
  }
  const done = Math.min(embedded, chunks);
  // Floor, so 100 % is only ever said of a version embedded in full.
  const percent = Math.floor((done / chunks) * 100);
  const share = formatNumber(percent / 100, language, { style: "percent" });
  const name = t.embedded(done, chunks);
  return (
    <Tooltip label={name}>
      <span className="inline-flex min-w-0 items-center gap-2">
        <Meter value={percent} label={name} role="meter" className="w-16 lg:w-20" />
        <span aria-hidden="true" className="num whitespace-nowrap text-small text-muted-foreground">
          {phone ? t.embeddedShare(share) : share}
        </span>
      </span>
    </Tooltip>
  );
}
