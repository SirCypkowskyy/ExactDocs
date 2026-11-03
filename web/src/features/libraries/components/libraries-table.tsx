import { Badge } from "@/shared/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/shared/ui/table";
import type { Library } from "../model/library";

interface LibrariesTableProps {
  libraries: readonly Library[];
}

export function LibrariesTable({ libraries }: LibrariesTableProps) {
  if (libraries.length === 0) {
    return <p className="text-muted-foreground text-sm">No libraries indexed yet.</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Library</TableHead>
          <TableHead>Indexed versions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {libraries.map((library) => (
          <TableRow key={library.name}>
            <TableCell className="font-medium">{library.name}</TableCell>
            <TableCell className="flex flex-wrap gap-1">
              {library.versions.map((version) => (
                <Badge key={version} variant="secondary">
                  {version}
                </Badge>
              ))}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
