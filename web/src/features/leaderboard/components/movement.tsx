import { useMessages } from "@/shared/lib/i18n";
import { leaderboardMessages } from "../messages";
import type { Movement } from "../model/leaderboard";
import { movementWords } from "./movement-words";

/**
 * The move as a mark (▲ 2, ▼ 1, –, New), neutral in colour: a leaderboard is not a verdict. The
 * mark is decoration; pass `words` to add the move in words for screen readers.
 */
export function MovementMark({ movement, words = false }: { movement: Movement; words?: boolean }) {
  const t = useMessages(leaderboardMessages);
  const mark =
    movement.kind === "up"
      ? `▲ ${movement.by}`
      : movement.kind === "down"
        ? `▼ ${movement.by}`
        : movement.kind === "same"
          ? "–"
          : t.movement.newShort;
  return (
    <span className="num inline-flex items-center whitespace-nowrap text-small text-muted-foreground">
      <span aria-hidden="true">{mark}</span>
      {words && <span className="sr-only">{movementWords(t, movement)}</span>}
    </span>
  );
}
