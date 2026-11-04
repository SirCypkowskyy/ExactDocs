import { Link } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { buttonVariants } from "@/shared/ui/button";

export function AddLibraryLink() {
  return (
    <Link to="/libraries/new" className={buttonVariants()}>
      <Plus aria-hidden="true" className="size-4" />
      Add library
    </Link>
  );
}
