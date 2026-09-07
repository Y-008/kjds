import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ui = readFileSync(new URL("../features/ai-erp/ai-erp-ui.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../features/ai-erp/ai-erp-ui.module.css", import.meta.url), "utf8");
const shell = readFileSync(new URL("../features/enterprise-shell/enterprise-shell.tsx", import.meta.url), "utf8");

test("AI ERP kit keeps truth states and action contracts explicit", () => {
  assert.match(ui, /NO_DATA/);
  assert.match(ui, /UNKNOWN_OUTCOME/);
  assert.match(ui, /DataState/);
  assert.match(ui, /ActionContractPanel/);
  assert.match(ui, /EvidenceTrail/);
  assert.match(ui, /FourStateMatrix/);
  assert.doesNotMatch(ui, /fetch\(|axios|method:\s*["'](?:POST|PUT|PATCH|DELETE)/);
});

test("AI ERP kit exposes accessible responsive boundaries", () => {
  assert.match(ui, /const titleId = useId\(\)/);
  assert.doesNotMatch(ui, /aria-labelledby="(?:action-contract-title|evidence-trail-title|state-matrix-title)"/);
  assert.match(styles, /@media \(max-width: 700px\)/);
  assert.match(styles, /prefers-reduced-motion/);
  assert.match(styles, /:focus-visible/);
  assert.match(styles, /overflow-wrap: anywhere/);
  assert.match(styles, /--kjds-surface-elevated/);
  assert.match(styles, /--kjds-border-default/);
  assert.doesNotMatch(styles, /--ui2-/);
  assert.doesNotMatch(styles, /@media[^{}]*\{\s*\*[, ]/);
});

test("EnterpriseShell provides scope, evidence, activity and read-only boundary", () => {
  assert.match(shell, /ScopeContext|EnterpriseContext/);
  assert.match(shell, /当前上下文/);
  assert.match(shell, /Evidence \/ AI/);
  assert.match(shell, /Activity/);
  assert.match(shell, /只读模式/);
  assert.doesNotMatch(shell, /fetch\(|axios|method:\s*["'](?:POST|PUT|PATCH|DELETE)/);
});
