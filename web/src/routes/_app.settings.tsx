import { createFileRoute } from "@tanstack/react-router";
import { AccountPanel } from "@/features/auth";

export const Route = createFileRoute("/_app/settings")({ component: AccountPanel });
