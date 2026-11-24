import { useQuery } from "@tanstack/react-query";
import { useMessages } from "@/shared/lib/i18n";
import { setPreferences, usePreferences } from "@/shared/lib/preferences";
import { PreferenceToggle } from "@/shared/ui/interface-settings";
import { usageSettingsQueryOptions } from "../api/providers-query";
import { usePreferencesSyncStatus } from "../hooks/use-preferences-sync";
import { useSession } from "../hooks/use-session";
import { messages } from "../messages";

/*
 * Account → Interface → "Show me on the leaderboard" (#510): the person's consent to be named on
 * the people leaderboard. It is the account's, so it shows only while signed in to one, and it can
 * be changed only once the account's own answer is known (the browser's copy may be someone
 * else's). The operator's switch (`GET /stats/settings`) is said in words; the choice stays
 * changeable while the board is off, ready for when it is turned on.
 */
export function LeaderboardOptIn() {
  const session = useSession();
  const t = useMessages(messages).leaderboard;
  const { prefs } = usePreferences();
  const status = usePreferencesSyncStatus();
  const settings = useQuery({ ...usageSettingsQueryOptions(), enabled: Boolean(session?.account) });
  if (!session?.account) return null;
  const known = status === "saved" || status === "saving";
  const failed = status === "unavailable" || status === "error";
  const board = settings.data?.people_leaderboard;
  return (
    <PreferenceToggle
      label={t.label}
      checked={known && prefs.leaderboard_opt_in}
      disabled={!known}
      onChange={(leaderboard_opt_in) => setPreferences({ leaderboard_opt_in })}
      description={
        <>
          <p>{t.description}</p>
          {failed ? (
            <p className="mt-2">{t.unavailable}</p>
          ) : board !== undefined ? (
            <p className="mt-2">{board ? t.on : t.off}</p>
          ) : null}
        </>
      }
    />
  );
}
