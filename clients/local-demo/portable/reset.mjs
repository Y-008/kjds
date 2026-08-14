import { cleanupPortableRuntime } from "./cleanup.mjs";

await cleanupPortableRuntime("RESET");
process.stdout.write("RESET_COMPLETE start again with start.ps1 or start.cmd\n");
