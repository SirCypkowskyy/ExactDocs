import type { leaderboardMessages } from "../messages";
import type { Movement } from "../model/leaderboard";

type M = (typeof leaderboardMessages)["en"];

/** The move against the previous period in words: "up 2 from #5", "new this period". */
export function movementWords(t: M, m: Movement): string {
  switch (m.kind) {
    case "up":
      return t.movement.up(m.by, m.from);
    case "down":
      return t.movement.down(m.by, m.from);
    case "same":
      return t.movement.same(m.from);
    default:
      return t.movement.new;
  }
}
