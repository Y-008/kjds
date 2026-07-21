import { readFileSync, readdirSync } from "node:fs";

export function readDashboardSource(): string {
  const directory = new URL("../features/dashboard/", import.meta.url);
  return readdirSync(directory)
    .filter((name) => name.endsWith(".ts") || name.endsWith(".tsx"))
    .sort()
    .map((name) => readFileSync(new URL(name, directory), "utf8"))
    .join("\n");
}
