import assert from "node:assert/strict";
import test from "node:test";

import { moduleDomains } from "../features/module-catalog/module-catalog.ts";

test("module catalog has a complete four-level navigation tree", () => {
  const ids = new Set<string>();
  assert.equal(moduleDomains.length, 9);
  for (const domain of moduleDomains) {
    assert.ok(domain.id && domain.title && domain.summary);
    assert.equal(ids.has(domain.id), false);
    ids.add(domain.id);
    assert.ok(domain.workspaces.length > 0);
    for (const workspace of domain.workspaces) {
      assert.equal(ids.has(workspace.id), false);
      ids.add(workspace.id);
      for (const module of workspace.modules) {
        assert.equal(ids.has(module.id), false);
        ids.add(module.id);
        assert.ok(module.operations.length > 0);
        for (const operation of module.operations) {
          assert.equal(ids.has(operation.id), false);
          ids.add(operation.id);
          assert.ok(operation.title && operation.action);
          assert.ok(operation.inputs.length > 0);
          assert.ok(operation.steps.length > 0);
          assert.ok(operation.output);
          assert.ok(operation.preconditions.length > 0);
          assert.ok(["available", "partial", "gated"].includes(operation.availability));
        }
      }
    }
  }
});

test("module catalog is navigation metadata and never an execution shortcut", async () => {
  const source = await import("node:fs/promises").then((fs) => fs.readFile(
    new URL("../features/module-catalog/module-catalog-console.tsx", import.meta.url),
    "utf8",
  ));
  assert.doesNotMatch(source, /fetch\(/);
  assert.doesNotMatch(source, /method:\s*["']POST/i);
  assert.match(source, /目录只提供操作说明/);
});

