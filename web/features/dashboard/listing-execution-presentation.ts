import type {
  ApprovalRecord,
  EvidenceSummary,
  GovernedExecutionPlan,
  LimitedExecutionCommand,
  LimitedExecutionCommandStatus,
  OperationalIncident,
} from "./contracts";

export type ListingExecutionPresentation = {
  draftId: string;
  plan: GovernedExecutionPlan | undefined;
  executionApproval: ApprovalRecord | undefined;
  executeCommand: LimitedExecutionCommand | undefined;
  rollbackCommand: LimitedExecutionCommand | undefined;
  lifecycle: LimitedExecutionCommandStatus | "preflight" | "compensated";
  rollbackLifecycle: LimitedExecutionCommandStatus | undefined;
  incident: OperationalIncident | undefined;
  blockers: string[];
  evidenceReferences: EvidenceSummary[];
};

type ListingExecutionCollections = {
  listingApprovals: ApprovalRecord[];
  approvals: ApprovalRecord[];
  plans: GovernedExecutionPlan[];
  commands: LimitedExecutionCommand[];
  incidents: OperationalIncident[];
  evidenceRecords: EvidenceSummary[];
};

export function selectListingExecutionPresentations({
  listingApprovals,
  approvals,
  plans,
  commands,
  incidents,
  evidenceRecords,
}: ListingExecutionCollections): Map<string, ListingExecutionPresentation> {
  const plansByDraft = new Map(plans.map((plan) => [plan.source_id, plan]));
  const plansBySourceApproval = new Map(
    plans.map((plan) => [plan.source_approval_id, plan]),
  );
  const approvalsById = new Map(approvals.map((approval) => [approval.id, approval]));
  const commandsByPlan = new Map<string, LimitedExecutionCommand[]>();
  for (const command of commands) {
    const planCommands = commandsByPlan.get(command.plan_id) ?? [];
    planCommands.push(command);
    commandsByPlan.set(command.plan_id, planCommands);
  }
  const incidentsByCommand = new Map(
    incidents
      .filter(
        (incident) =>
          incident.source_type === "limited_execution_command" && incident.source_id,
      )
      .map((incident) => [incident.source_id as string, incident]),
  );
  const evidenceById = new Map(evidenceRecords.map((record) => [record.id, record]));

  return new Map(
    listingApprovals.map((listingApproval) => {
      const draftId = String(
        listingApproval.payload.draft_id ?? listingApproval.resource_id,
      );
      const plan =
        plansByDraft.get(draftId) ?? plansBySourceApproval.get(listingApproval.id);
      const planCommands = plan ? commandsByPlan.get(plan.id) ?? [] : [];
      const executeCommand = planCommands.find(
        (command) => command.command_kind === "execute",
      );
      const rollbackCommand = planCommands.find(
        (command) => command.command_kind === "rollback",
      );
      const readinessBlockers = plan
        ? Object.entries(plan.current_readiness_snapshot).flatMap(([key, readiness]) =>
            readiness.ready ? [] : [key, ...readiness.blocking_reasons],
          )
        : [];
      const lifecycle =
        rollbackCommand?.status === "succeeded"
          ? "compensated"
          : executeCommand?.status ?? "preflight";

      return [
        listingApproval.id,
        {
          draftId,
          plan,
          executionApproval: plan
            ? approvalsById.get(plan.approval_id)
            : undefined,
          executeCommand,
          rollbackCommand,
          lifecycle,
          rollbackLifecycle: rollbackCommand?.status,
          incident: executeCommand
            ? incidentsByCommand.get(executeCommand.id)
            : undefined,
          blockers: plan
            ? [
                ...new Set([
                  ...plan.authorization_blocking_reasons,
                  ...readinessBlockers,
                ]),
              ]
            : [],
          evidenceReferences:
            plan?.evidence_ids.flatMap((id) => {
              const record = evidenceById.get(id);
              return record ? [record] : [];
            }) ?? [],
        },
      ];
    }),
  );
}
