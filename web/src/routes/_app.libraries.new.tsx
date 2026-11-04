import { createFileRoute } from "@tanstack/react-router";
import { RouteError } from "@/features/auth";
import { AddLibraryPage } from "@/features/libraries";

export const Route = createFileRoute("/_app/libraries/new")({
  errorComponent: (props) => <RouteError {...props} wide />,
  component: AddLibraryPage,
});
