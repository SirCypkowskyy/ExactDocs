import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/shared/ui/card";
import { useLibraries } from "../hooks/use-libraries";
import { LibrariesTable } from "./libraries-table";

export function LibrariesPage() {
  const { data: libraries } = useLibraries();
  return (
    <main className="mx-auto max-w-4xl p-6">
      <Card>
        <CardHeader>
          <CardTitle>Libraries</CardTitle>
          <CardDescription>Documentation indexed by ExactDocs, per version.</CardDescription>
        </CardHeader>
        <CardContent>
          <LibrariesTable libraries={libraries} />
        </CardContent>
      </Card>
    </main>
  );
}
