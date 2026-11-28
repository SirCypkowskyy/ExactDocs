import { Link } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useMessages } from "@/shared/lib/i18n";
import { buttonVariants } from "@/shared/ui/button";
import { listMessages } from "../messages/list";

export function AddLibraryLink() {
  const t = useMessages(listMessages);
  return (
    <Link to="/libraries/new" data-tour="add-library" className={buttonVariants()}>
      <Plus aria-hidden="true" data-icon-motion="turn" />
      {t.addLibrary}
    </Link>
  );
}
