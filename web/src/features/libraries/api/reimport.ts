import { sendJson } from "@/shared/lib/http";
import type { ReimportedVersion } from "../model/library";

const seg = encodeURIComponent;

/** Confirm a moved tag: re-import it at the commit it names now. The ref goes in the body. */
export const reimportVersion = (library: string, ref: string) => {
  const [, owner = "", repo = ""] = library.split("/");
  return sendJson<ReimportedVersion>(
    "POST",
    `/v1/libraries/${seg(owner)}/${seg(repo)}/versions/reimport`,
    { ref },
  );
};
