"""Add governed closed-loop Outcome Evidence ledger.

Revision ID: 20260805_0096
Revises: 20260804_0095
Create Date: 2026-08-05
"""

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "20260805_0096"
down_revision = "20260804_0095"
branch_labels = None
depends_on = None

BUNDLES = "closed_loop_outcome_bundles"
LINKS = "closed_loop_outcome_evidence_links"
EVENTS = "closed_loop_outcome_events"
AUTHORITY_RECEIPTS = "closed_loop_authority_receipts"
ISSUANCES = "closed_loop_evidence_issuances"
ACL_RECEIPTS = "closed_loop_acl_baseline_receipts"
TABLES = (BUNDLES, LINKS, EVENTS)
AUTHORITY_SOURCES = (
    "closed-loop-experiment-receipt",
    "closed-loop-cost-receipt",
    "closed-loop-business-outcome-receipt",
    "closed-loop-review-authority-receipt",
)
SOURCES = (
    *AUTHORITY_SOURCES,
    "governed-closed-loop-evolution",
)
SOURCES_SQL = ",".join(f"'{source}'" for source in SOURCES)
AUTHORITY_SOURCES_SQL = ",".join(f"'{source}'" for source in AUTHORITY_SOURCES)
CLOSED_LOOP_LINEAGE_TYPES = (
    "closed_loop_outcome_bundle",
    "closed_loop_outcome_event",
    "closed_loop_authority_receipt",
    "closed_loop_evidence_issuance",
)
CLOSED_LOOP_LINEAGE_TYPES_SQL = ",".join(
    f"'{target_type}'" for target_type in CLOSED_LOOP_LINEAGE_TYPES
)
HEX64 = "^[0-9a-f]{64}$"
ISSUANCE_OWNER_ROLE = "kjds_cloe_issuance_owner"
ISSUANCE_RUNTIME_ROLE = "kjds_cloe_issuance_runtime"
EVENT_ISSUANCE_OWNER_ROLE = "kjds_cloe_event_issuance_owner"
ATTESTATION_ROLES = {
    "experiment": "kjds_cloe_experiment_authority",
    "cost": "kjds_cloe_cost_authority",
    "business_outcome": "kjds_cloe_outcome_authority",
    "review_event": "kjds_cloe_review_authority",
}
ISSUANCE_ROLES = (
    ISSUANCE_OWNER_ROLE,
    EVENT_ISSUANCE_OWNER_ROLE,
    ISSUANCE_RUNTIME_ROLE,
    *ATTESTATION_ROLES.values(),
)
AGENT_RUN_EVENT_KEYS = (
    "event_index",
    "event_type",
    "reason_code",
    "adapter_sha256",
    "provider_sha256",
    "model_sha256",
    "adapter_config_sha256",
    "output_sha256",
    "eval_sha256",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "latency_ms",
    "safe_payload",
    "previous_event_sha256",
    "occurred_at",
    "event_sha256",
)
AGENT_RUN_EVENT_TYPES = (
    "run_started",
    "route_selected",
    "attempt_started",
    "attempt_completed",
    "attempt_denied",
    "attempt_failed",
    "eval_completed",
    "run_succeeded",
    "run_failed",
    "run_denied",
    "unknown_outcome",
)
AGENT_RUN_TERMINAL_EVENT_TYPES = (
    "run_succeeded",
    "run_failed",
    "run_denied",
    "unknown_outcome",
)
AGENT_RUN_UNKNOWN_REASON_CODES = (
    "provider_outcome_not_persisted",
    "provider_outcome_not_terminal",
)
AGENT_RUN_TRANSITIONS = {
    None: ("run_started",),
    "run_started": ("route_selected", "run_denied"),
    "route_selected": ("attempt_started", "run_failed", "unknown_outcome"),
    "attempt_started": (
        "attempt_completed",
        "attempt_denied",
        "attempt_failed",
        "unknown_outcome",
    ),
    "attempt_completed": ("eval_completed", "unknown_outcome"),
    "attempt_denied": ("run_denied", "unknown_outcome"),
    "attempt_failed": ("attempt_started", "run_failed", "unknown_outcome"),
    "eval_completed": ("run_succeeded", "unknown_outcome"),
}
AGENT_RUN_SAFE_PAYLOAD_KEYS = {
    "run_started": (),
    "route_selected": ("adapter_count", "adapter_config_sha256"),
    "attempt_started": ("attempt",),
    "attempt_completed": ("attempt",),
    "attempt_denied": ("attempt",),
    "attempt_failed": ("attempt",),
    "eval_completed": ("passed", "assertion_count"),
    "run_succeeded": ("attempt_count",),
    "run_failed": (),
    "run_denied": (),
    "unknown_outcome": (),
}

ACL_SCHEMA_ROLES = ISSUANCE_ROLES
ACL_TABLE_ROLES = (ISSUANCE_OWNER_ROLE, EVENT_ISSUANCE_OWNER_ROLE)
ACL_TABLES = ("evidence_records", "evidence_blobs")
ACL_TABLE_PRIVILEGES = ("SELECT", "INSERT")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _acl_entries(
    connection, *, schema: str, object_kind: str, object_name: str
) -> tuple[list[dict[str, object]], str | None]:
    if object_kind == "schema":
        rows = connection.execute(
            sa.text(
                "SELECT grantor.rolname AS grantor_name,"
                "CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END "
                "AS grantee_name,acl.privilege_type,acl.is_grantable "
                "FROM pg_catalog.pg_namespace namespace "
                "CROSS JOIN LATERAL aclexplode(coalesce(namespace.nspacl,"
                "acldefault('n',namespace.nspowner))) acl "
                "LEFT JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor "
                "LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee "
                "WHERE namespace.nspname=:schema "
                "ORDER BY grantor_name,grantee_name,acl.privilege_type,"
                "acl.is_grantable"
            ),
            {"schema": schema},
        ).mappings().all()
        raw_acl = connection.scalar(
            sa.text(
                "SELECT nspacl::text FROM pg_catalog.pg_namespace "
                "WHERE nspname=:schema"
            ),
            {"schema": schema},
        )
    elif object_kind == "table":
        rows = connection.execute(
            sa.text(
                "SELECT grantor.rolname AS grantor_name,"
                "CASE WHEN acl.grantee=0 THEN 'PUBLIC' ELSE grantee.rolname END "
                "AS grantee_name,acl.privilege_type,acl.is_grantable "
                "FROM pg_catalog.pg_class relation "
                "JOIN pg_catalog.pg_namespace namespace "
                "ON namespace.oid=relation.relnamespace "
                "CROSS JOIN LATERAL aclexplode(coalesce(relation.relacl,"
                "acldefault('r',relation.relowner))) acl "
                "LEFT JOIN pg_catalog.pg_roles grantor ON grantor.oid=acl.grantor "
                "LEFT JOIN pg_catalog.pg_roles grantee ON grantee.oid=acl.grantee "
                "WHERE namespace.nspname=:schema AND relation.relname=:object_name "
                "ORDER BY grantor_name,grantee_name,acl.privilege_type,"
                "acl.is_grantable"
            ),
            {"schema": schema, "object_name": object_name},
        ).mappings().all()
        raw_acl = connection.scalar(
            sa.text(
                "SELECT relation.relacl::text FROM pg_catalog.pg_class relation "
                "JOIN pg_catalog.pg_namespace namespace "
                "ON namespace.oid=relation.relnamespace "
                "WHERE namespace.nspname=:schema AND relation.relname=:object_name"
            ),
            {"schema": schema, "object_name": object_name},
        )
    else:
        raise RuntimeError("BAS-204 ACL object kind is invalid")
    entries = [
        {
            "grantor": row["grantor_name"],
            "grantee": row["grantee_name"],
            "privilege": row["privilege_type"],
            "grant_option": bool(row["is_grantable"]),
        }
        for row in rows
    ]
    return entries, raw_acl


def _acl_effective(
    connection,
    *,
    schema: str,
    object_kind: str,
    object_name: str,
    role_name: str,
    privilege_type: str,
) -> bool:
    if object_kind == "schema":
        return bool(
            connection.scalar(
                sa.text("SELECT has_schema_privilege(:role,:schema,:privilege)"),
                {
                    "role": role_name,
                    "schema": schema,
                    "privilege": privilege_type,
                },
            )
        )
    return bool(
        connection.scalar(
            sa.text("SELECT has_table_privilege(:role,:object_name,:privilege)"),
            {
                "role": role_name,
                "object_name": f"{schema}.{object_name}",
                "privilege": privilege_type,
            },
        )
    )


def _acl_object_grantor(
    connection, *, schema: str, object_kind: str, object_name: str
) -> str:
    if object_kind == "schema":
        grantor = connection.scalar(
            sa.text(
                "SELECT owner.rolname FROM pg_catalog.pg_namespace namespace "
                "JOIN pg_catalog.pg_roles owner ON owner.oid=namespace.nspowner "
                "WHERE namespace.nspname=:schema"
            ),
            {"schema": schema},
        )
    elif object_kind == "table":
        grantor = connection.scalar(
            sa.text(
                "SELECT owner.rolname FROM pg_catalog.pg_class relation "
                "JOIN pg_catalog.pg_namespace namespace "
                "ON namespace.oid=relation.relnamespace "
                "JOIN pg_catalog.pg_roles owner ON owner.oid=relation.relowner "
                "WHERE namespace.nspname=:schema AND relation.relname=:object_name"
            ),
            {"schema": schema, "object_name": object_name},
        )
    else:
        grantor = None
    if not isinstance(grantor, str) or not grantor:
        raise RuntimeError("BAS-204 ACL object grantor is unavailable")
    return grantor


def _acl_cells(schema: str) -> list[dict[str, str]]:
    cells = [
        {
            "cell_id": f"schema:{schema}:{role}:USAGE",
            "role_name": role,
            "object_kind": "schema",
            "object_name": schema,
            "privilege_type": "USAGE",
        }
        for role in ACL_SCHEMA_ROLES
    ]
    cells.extend(
        {
            "cell_id": f"table:{schema}.{table}:{role}:{privilege}",
            "role_name": role,
            "object_kind": "table",
            "object_name": table,
            "privilege_type": privilege,
        }
        for role in ACL_TABLE_ROLES
        for table in ACL_TABLES
        for privilege in ACL_TABLE_PRIVILEGES
    )
    return cells


def _managed_acl_cell(
    entry: dict[str, object], *, object_kind: str, object_name: str, grantor: str
) -> bool:
    if entry["grantor"] != grantor:
        return False
    if object_kind == "schema":
        return (
            entry["grantee"] in ACL_SCHEMA_ROLES
            and entry["privilege"] == "USAGE"
        )
    return (
        object_name in ACL_TABLES
        and entry["grantee"] in ACL_TABLE_ROLES
        and entry["privilege"] in ACL_TABLE_PRIVILEGES
    )


def _acl_receipt_payload(row: dict[str, object]) -> dict[str, object]:
    return {
        key: row[key]
        for key in (
            "cell_id",
            "role_name",
            "object_kind",
            "object_name",
            "privilege_type",
            "migration_grantor",
            "baseline_direct",
            "baseline_grant_option",
            "baseline_effective",
            "introduced",
            "baseline_acl_json",
            "baseline_acl_text",
            "baseline_acl_sha256",
            "baseline_outside_acl_sha256",
        )
    }


def _raise_acl_downgrade_blocked(connection, failure: str) -> None:
    messages = {
        "baseline": "0096 downgrade blocked: ACL baseline drifted",
        "projection": "0096 downgrade blocked: ACL projection drifted",
        "roles": "0096 downgrade blocked: issuance role contract drifted",
        "restore": "0096 downgrade blocked: ACL restore drifted",
    }
    message = messages[failure]
    connection.exec_driver_sql(
        "DO $$ BEGIN RAISE EXCEPTION USING ERRCODE='55000', "
        f"MESSAGE='{message}'; END; $$"
    )
    raise RuntimeError(message)


def _issuance_role_contract_status(connection) -> str | None:
    role_contract = connection.execute(
        sa.text(
            "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,"
            "rolcanlogin,rolreplication,rolbypassrls FROM pg_roles "
            "WHERE rolname=ANY(:roles)"
        ),
        {"roles": list(ISSUANCE_ROLES)},
    ).mappings().all()
    roles = {row["rolname"]: row for row in role_contract}
    if set(roles) != set(ISSUANCE_ROLES):
        return "missing"

    def _matches(
        role_name: str, *, can_login: bool, bypass_rls: bool
    ) -> bool:
        role = roles[role_name]
        return (
            bool(role["rolcanlogin"]) == can_login
            and bool(role["rolbypassrls"]) == bypass_rls
            and not role["rolsuper"]
            and not role["rolinherit"]
            and not role["rolcreaterole"]
            and not role["rolcreatedb"]
            and not role["rolreplication"]
        )

    if (
        not _matches(
            ISSUANCE_OWNER_ROLE,
            can_login=False,
            bypass_rls=True,
        )
        or not _matches(
            EVENT_ISSUANCE_OWNER_ROLE,
            can_login=False,
            bypass_rls=True,
        )
        or not _matches(
            ISSUANCE_RUNTIME_ROLE,
            can_login=True,
            bypass_rls=False,
        )
        or any(
            not _matches(role, can_login=True, bypass_rls=False)
            for role in ATTESTATION_ROLES.values()
        )
    ):
        return "attributes"
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_auth_members membership "
            "JOIN pg_roles granted ON granted.oid=membership.roleid "
            "JOIN pg_roles member_role ON member_role.oid=membership.member "
            "WHERE granted.rolname=ANY(:roles) "
            "OR member_role.rolname=ANY(:roles))"
        ),
        {"roles": list(ISSUANCE_ROLES)},
    ):
        return "memberships"
    return None


def _capture_acl_baseline(connection, *, schema: str) -> None:
    for cell in _acl_cells(schema):
        migration_grantor = _acl_object_grantor(
            connection,
            schema=schema,
            object_kind=cell["object_kind"],
            object_name=cell["object_name"],
        )
        entries, raw_acl = _acl_entries(
            connection,
            schema=schema,
            object_kind=cell["object_kind"],
            object_name=cell["object_name"],
        )
        direct_entries = [
            entry
            for entry in entries
            if entry["grantor"] == migration_grantor
            and entry["grantee"] == cell["role_name"]
            and entry["privilege"] == cell["privilege_type"]
        ]
        if len(direct_entries) > 1:
            raise RuntimeError("BAS-204 ACL baseline is ambiguous")
        baseline_effective = _acl_effective(
            connection,
            schema=schema,
            object_kind=cell["object_kind"],
            object_name=cell["object_name"],
            role_name=cell["role_name"],
            privilege_type=cell["privilege_type"],
        )
        outside_entries = [
            entry
            for entry in entries
            if not _managed_acl_cell(
                entry,
                object_kind=cell["object_kind"],
                object_name=cell["object_name"],
                grantor=migration_grantor,
            )
        ]
        row: dict[str, object] = {
            **cell,
            "migration_grantor": migration_grantor,
            "baseline_direct": bool(direct_entries),
            "baseline_grant_option": bool(
                direct_entries and direct_entries[0]["grant_option"]
            ),
            "baseline_effective": baseline_effective,
            "introduced": not baseline_effective,
            "baseline_acl_json": _canonical_json_bytes(entries).decode("ascii"),
            "baseline_acl_text": raw_acl,
            "baseline_acl_sha256": _sha256_json(entries),
            "baseline_outside_acl_sha256": _sha256_json(outside_entries),
        }
        row["receipt_sha256"] = _sha256_json(_acl_receipt_payload(row))
        connection.execute(
            sa.text(
                f"INSERT INTO {ACL_RECEIPTS}("
                "cell_id,role_name,object_kind,object_name,privilege_type,"
                "migration_grantor,baseline_direct,baseline_grant_option,"
                "baseline_effective,introduced,baseline_acl_json,baseline_acl_text,"
                "baseline_acl_sha256,baseline_outside_acl_sha256,receipt_sha256) "
                "VALUES (:cell_id,:role_name,:object_kind,:object_name,"
                ":privilege_type,:migration_grantor,:baseline_direct,"
                ":baseline_grant_option,:baseline_effective,:introduced,"
                ":baseline_acl_json,"
                ":baseline_acl_text,:baseline_acl_sha256,"
                ":baseline_outside_acl_sha256,:receipt_sha256)"
            ),
            row,
        )


def _validated_acl_receipts(connection, *, schema: str) -> list[dict[str, object]]:
    rows = [
        dict(row)
        for row in connection.execute(
            sa.text(f"SELECT * FROM {ACL_RECEIPTS} ORDER BY cell_id")
        ).mappings()
    ]
    expected_cells = {cell["cell_id"]: cell for cell in _acl_cells(schema)}
    if len(rows) != 15 or {row["cell_id"] for row in rows} != set(expected_cells):
        _raise_acl_downgrade_blocked(connection, "baseline")
    for row in rows:
        expected = expected_cells[str(row["cell_id"])]
        if any(row[key] != value for key, value in expected.items()):
            _raise_acl_downgrade_blocked(connection, "baseline")
        current_grantor = _acl_object_grantor(
            connection,
            schema=schema,
            object_kind=str(row["object_kind"]),
            object_name=str(row["object_name"]),
        )
        if row["migration_grantor"] != current_grantor:
            _raise_acl_downgrade_blocked(connection, "baseline")
        if row["receipt_sha256"] != _sha256_json(_acl_receipt_payload(row)):
            _raise_acl_downgrade_blocked(connection, "baseline")
        if (
            bool(row["introduced"]) != (not bool(row["baseline_effective"]))
            or (row["baseline_grant_option"] and not row["baseline_direct"])
            or (row["baseline_direct"] and not row["baseline_effective"])
        ):
            _raise_acl_downgrade_blocked(connection, "baseline")
        try:
            baseline_entries = json.loads(str(row["baseline_acl_json"]))
        except (TypeError, ValueError) as error:
            del error
            _raise_acl_downgrade_blocked(connection, "baseline")
        if (
            not isinstance(baseline_entries, list)
            or row["baseline_acl_sha256"] != _sha256_json(baseline_entries)
        ):
            _raise_acl_downgrade_blocked(connection, "baseline")
        entries, _ = _acl_entries(
            connection,
            schema=schema,
            object_kind=str(row["object_kind"]),
            object_name=str(row["object_name"]),
        )
        outside_entries = [
            entry
            for entry in entries
            if not _managed_acl_cell(
                entry,
                object_kind=str(row["object_kind"]),
                object_name=str(row["object_name"]),
                grantor=current_grantor,
            )
        ]
        direct_entries = [
            entry
            for entry in entries
            if entry["grantor"] == current_grantor
            and entry["grantee"] == row["role_name"]
            and entry["privilege"] == row["privilege_type"]
        ]
        current_effective = _acl_effective(
            connection,
            schema=schema,
            object_kind=str(row["object_kind"]),
            object_name=str(row["object_name"]),
            role_name=str(row["role_name"]),
            privilege_type=str(row["privilege_type"]),
        )
        if row["introduced"]:
            managed_projection_valid = (
                not row["baseline_effective"]
                and not row["baseline_direct"]
                and len(direct_entries) == 1
                and not bool(direct_entries[0]["grant_option"])
                and current_effective
            )
        else:
            managed_projection_valid = (
                bool(row["baseline_effective"])
                and (
                    (
                        bool(row["baseline_direct"])
                        and len(direct_entries) == 1
                        and bool(direct_entries[0]["grant_option"])
                        == bool(row["baseline_grant_option"])
                    )
                    or (not row["baseline_direct"] and not direct_entries)
                )
                and current_effective
            )
        if (
            row["baseline_outside_acl_sha256"] != _sha256_json(outside_entries)
            or not managed_projection_valid
        ):
            _raise_acl_downgrade_blocked(connection, "projection")
    return rows


def _grant_introduced_acl(connection, *, schema: str) -> None:
    preparer = connection.dialect.identifier_preparer
    quoted_schema = preparer.quote_schema(schema)
    rows = connection.execute(
        sa.text(
            f"SELECT role_name,object_kind,object_name,privilege_type "
            f"FROM {ACL_RECEIPTS} WHERE introduced ORDER BY cell_id"
        )
    ).mappings()
    for row in rows:
        quoted_role = preparer.quote(str(row["role_name"]))
        privilege = str(row["privilege_type"])
        if row["object_kind"] == "schema":
            connection.exec_driver_sql(
                f"GRANT {privilege} ON SCHEMA {quoted_schema} TO {quoted_role}"
            )
        else:
            quoted_table = preparer.quote(str(row["object_name"]))
            connection.exec_driver_sql(
                f"GRANT {privilege} ON TABLE {quoted_schema}.{quoted_table} "
                f"TO {quoted_role}"
            )


def _restore_acl_baseline(
    connection, *, schema: str, rows: list[dict[str, object]]
) -> None:
    preparer = connection.dialect.identifier_preparer
    quoted_schema = preparer.quote_schema(schema)
    for row in rows:
        if not row["introduced"]:
            continue
        quoted_role = preparer.quote(str(row["role_name"]))
        privilege = str(row["privilege_type"])
        if row["object_kind"] == "schema":
            connection.exec_driver_sql(
                f"REVOKE {privilege} ON SCHEMA {quoted_schema} FROM {quoted_role}"
            )
        else:
            quoted_table = preparer.quote(str(row["object_name"]))
            connection.exec_driver_sql(
                f"REVOKE {privilege} ON TABLE {quoted_schema}.{quoted_table} "
                f"FROM {quoted_role}"
            )
    checked_objects: set[tuple[str, str]] = set()
    for row in rows:
        object_key = (str(row["object_kind"]), str(row["object_name"]))
        if object_key not in checked_objects:
            entries, raw_acl = _acl_entries(
                connection,
                schema=schema,
                object_kind=object_key[0],
                object_name=object_key[1],
            )
            if (
                row["baseline_acl_sha256"] != _sha256_json(entries)
                or (
                    row["baseline_acl_text"] is not None
                    and row["baseline_acl_text"] != raw_acl
                )
            ):
                _raise_acl_downgrade_blocked(connection, "restore")
            checked_objects.add(object_key)
        if _acl_effective(
            connection,
            schema=schema,
            object_kind=str(row["object_kind"]),
            object_name=str(row["object_name"]),
            role_name=str(row["role_name"]),
            privilege_type=str(row["privilege_type"]),
        ) != bool(row["baseline_effective"]):
            _raise_acl_downgrade_blocked(connection, "restore")


def _scope_columns() -> list[sa.Column]:
    return [
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("scope_grant_authority_sha256", sa.String(64), nullable=False),
    ]


def _root_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [
            "bundle_id",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
        ],
        [
            f"{BUNDLES}.bundle_id",
            f"{BUNDLES}.tenant_ref",
            f"{BUNDLES}.entity_ref",
            f"{BUNDLES}.store_ref",
            f"{BUNDLES}.scope_grant_authority_sha256",
        ],
        name=f"fk_cloe_{name}_exact_scope",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )


def _evidence_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [
            "evidence_id",
            "evidence_sha256",
            "evidence_source",
            "evidence_source_ref",
            "evidence_grade",
            "evidence_effective_at",
        ],
        [
            "evidence_records.id",
            "evidence_records.blob_sha256",
            "evidence_records.source",
            "evidence_records.source_ref",
            "evidence_records.grade",
            "evidence_records.effective_at",
        ],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.execute("SELECT pg_advisory_xact_lock(hashtext('kjds-cloe-0096-lifecycle'))")
    connection = op.get_bind()
    schema = str(connection.scalar(sa.text("SELECT current_schema()")))
    quoted_schema = connection.dialect.identifier_preparer.quote_schema(schema)
    role_status = _issuance_role_contract_status(connection)
    if role_status == "missing":
        raise RuntimeError("BAS-204 Evidence issuance principals are not provisioned")
    if role_status == "attributes":
        raise RuntimeError("BAS-204 Evidence issuance principal contract drifted")
    if role_status == "memberships":
        raise RuntimeError("BAS-204 Evidence issuance roles must have no memberships")
    for table_name in ("evidence_blobs", "evidence_records", "lineage_edges"):
        op.execute(
            f"LOCK TABLE {quoted_schema}.{table_name} "
            "IN SHARE ROW EXCLUSIVE MODE"
        )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM {quoted_schema}.evidence_records
                WHERE source IN ({SOURCES_SQL})
            ) OR EXISTS (
                SELECT 1
                FROM {quoted_schema}.lineage_edges lineage
                LEFT JOIN {quoted_schema}.evidence_records source_evidence
                  ON lineage.from_type='evidence'
                 AND source_evidence.id=lineage.from_id
                LEFT JOIN {quoted_schema}.evidence_records target_evidence
                  ON lineage.to_type='evidence'
                 AND target_evidence.id=lineage.to_id
                WHERE source_evidence.source IN ({SOURCES_SQL})
                   OR target_evidence.source IN ({SOURCES_SQL})
                   OR lineage.from_type IN ({CLOSED_LOOP_LINEAGE_TYPES_SQL})
                   OR lineage.to_type IN ({CLOSED_LOOP_LINEAGE_TYPES_SQL})
                   OR lineage.from_id LIKE 'clob!_%' ESCAPE '!'
                   OR lineage.to_id LIKE 'clob!_%' ESCAPE '!'
                   OR lineage.from_id LIKE 'cloev!_%' ESCAPE '!'
                   OR lineage.to_id LIKE 'cloev!_%' ESCAPE '!'
            ) OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class object
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid=object.relnamespace
                WHERE namespace.nspname=current_schema()
                  AND (
                    object.relname LIKE 'closed!_loop!_%' ESCAPE '!'
                    OR object.relname='uq_closed_loop_authority_evidence_source_ref'
                  )
            ) OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_proc function
                JOIN pg_catalog.pg_namespace namespace
                  ON namespace.oid=function.pronamespace
                WHERE namespace.nspname=current_schema()
                  AND function.proname LIKE 'kjds!_cloe!_%' ESCAPE '!'
            ) OR EXISTS (
                SELECT 1
                FROM pg_catalog.pg_trigger trigger
                WHERE NOT trigger.tgisinternal
                  AND trigger.tgname LIKE 'trg!_cloe!_%' ESCAPE '!'
            ) THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE='0096 upgrade blocked: legacy closed-loop artifacts exist';
            END IF;
        END;
        $$
        """
    )
    op.create_table(
        ACL_RECEIPTS,
        sa.Column("cell_id", sa.String(320), primary_key=True),
        sa.Column("role_name", sa.String(160), nullable=False),
        sa.Column("object_kind", sa.String(16), nullable=False),
        sa.Column("object_name", sa.Text(), nullable=False),
        sa.Column("privilege_type", sa.String(16), nullable=False),
        sa.Column("migration_grantor", sa.String(160), nullable=False),
        sa.Column("baseline_direct", sa.Boolean(), nullable=False),
        sa.Column("baseline_grant_option", sa.Boolean(), nullable=False),
        sa.Column("baseline_effective", sa.Boolean(), nullable=False),
        sa.Column("introduced", sa.Boolean(), nullable=False),
        sa.Column("baseline_acl_json", sa.Text(), nullable=False),
        sa.Column("baseline_acl_text", sa.Text(), nullable=True),
        sa.Column("baseline_acl_sha256", sa.String(64), nullable=False),
        sa.Column("baseline_outside_acl_sha256", sa.String(64), nullable=False),
        sa.Column("receipt_sha256", sa.String(64), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "object_kind IN ('schema','table') AND "
            "privilege_type IN ('USAGE','SELECT','INSERT') AND "
            f"baseline_acl_sha256 ~ '{HEX64}' AND "
            f"baseline_outside_acl_sha256 ~ '{HEX64}' AND "
            f"receipt_sha256 ~ '{HEX64}' AND "
            "introduced=(NOT baseline_effective) AND "
            "(NOT baseline_grant_option OR baseline_direct) AND "
            "(NOT baseline_direct OR baseline_effective)",
            name="ck_cloe_acl_baseline_receipt",
        ),
        sa.UniqueConstraint(
            "role_name",
            "object_kind",
            "object_name",
            "privilege_type",
            name="uq_cloe_acl_baseline_cell",
        ),
    )
    op.execute(f"REVOKE ALL ON {quoted_schema}.{ACL_RECEIPTS} FROM PUBLIC")
    _capture_acl_baseline(connection, schema=schema)
    op.execute(
        f"""
        CREATE FUNCTION {quoted_schema}.kjds_cloe_prevent_acl_receipt_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path=pg_catalog,{quoted_schema}
        AS $$
        BEGIN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='closed-loop ACL baseline receipts are immutable';
        END;
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION "
        f"{quoted_schema}.kjds_cloe_prevent_acl_receipt_mutation() FROM PUBLIC"
    )
    op.execute(
        f"CREATE TRIGGER trg_cloe_acl_receipt_immutable "
        f"BEFORE INSERT OR UPDATE OR DELETE ON {quoted_schema}.{ACL_RECEIPTS} "
        "FOR EACH ROW EXECUTE FUNCTION "
        f"{quoted_schema}.kjds_cloe_prevent_acl_receipt_mutation()"
    )
    op.execute(
        f"CREATE TRIGGER trg_cloe_acl_receipt_truncate_immutable "
        f"BEFORE TRUNCATE ON {quoted_schema}.{ACL_RECEIPTS} "
        "FOR EACH STATEMENT EXECUTE FUNCTION "
        f"{quoted_schema}.kjds_cloe_prevent_acl_receipt_mutation()"
    )
    op.create_table(
        AUTHORITY_RECEIPTS,
        sa.Column("authority_receipt_id", sa.String(160), primary_key=True),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("metadata_sha256", sa.String(64), nullable=False),
        sa.Column("source", sa.String(160), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("attestation_sha256", sa.String(64), nullable=False),
        sa.Column("attestation_signature_sha256", sa.String(64), nullable=False),
        sa.Column("issuer_id", sa.String(160), nullable=False),
        sa.Column("issuer_contract_id", sa.String(160), nullable=False),
        sa.Column("issuer_contract_version", sa.String(32), nullable=False),
        sa.Column("issuer_contract_sha256", sa.String(64), nullable=False),
        sa.Column("schema_sha256", sa.String(64), nullable=False),
        sa.Column("issuer_actor_id", sa.String(160), nullable=False),
        sa.Column("tenant_ref", sa.String(160), nullable=False),
        sa.Column("entity_ref", sa.String(160), nullable=False),
        sa.Column("store_ref", sa.String(160), nullable=False),
        sa.Column("scope_grant_authority_sha256", sa.String(64), nullable=False),
        sa.Column("data_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(
            "purpose IN ('experiment','cost','business_outcome','review_event') AND "
            f"source IN ({AUTHORITY_SOURCES_SQL}) AND "
            f"content_sha256 ~ '{HEX64}' AND metadata_sha256 ~ '{HEX64}' AND "
            f"attestation_sha256 ~ '{HEX64}' AND "
            f"attestation_signature_sha256 ~ '{HEX64}' AND "
            f"issuer_contract_sha256 ~ '{HEX64}' AND schema_sha256 ~ '{HEX64}' AND "
            f"scope_grant_authority_sha256 ~ '{HEX64}' AND "
            "effective_at<=recorded_at AND recorded_at<=data_as_of AND "
            "data_as_of<review_due_at AND review_due_at<=effective_until",
            name="ck_cloe_authority_receipt",
        ),
        sa.UniqueConstraint(
            "evidence_id",
            name="uq_cloe_authority_receipt_evidence",
        ),
    )
    op.create_table(
        ISSUANCES,
        sa.Column("evidence_id", sa.String(), primary_key=True),
        sa.Column("authority_receipt_id", sa.String(160), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("source", sa.String(160), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("attestation_sha256", sa.String(64), nullable=False),
        sa.Column("attestation_signature_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(
            f"content_sha256 ~ '{HEX64}' AND attestation_sha256 ~ '{HEX64}' "
            f"AND attestation_signature_sha256 ~ '{HEX64}' "
            f"AND source IN ({AUTHORITY_SOURCES_SQL})",
            name="ck_cloe_issuance",
        ),
        sa.UniqueConstraint(
            "authority_receipt_id",
            name="uq_cloe_issuance_authority_receipt",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_records.id"],
            name="fk_cloe_issuance_evidence",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["authority_receipt_id"],
            [f"{AUTHORITY_RECEIPTS}.authority_receipt_id"],
            name="fk_cloe_issuance_authority_receipt",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        BUNDLES,
        sa.Column("bundle_id", sa.String(64), primary_key=True),
        *_scope_columns(),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("agent_run_ref", sa.String(64), nullable=False),
        sa.Column("agent_run_terminal_event_sha256", sa.String(64), nullable=False),
        sa.Column("contract_id", sa.String(160), nullable=False),
        sa.Column("contract_version", sa.String(32), nullable=False),
        sa.Column("registry_sha256", sa.String(64), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("bundle_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_sha256", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("bundle_sha256", sa.String(64), nullable=False),
        sa.Column("data_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authority_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("experiment_ref", sa.String(160), nullable=False),
        sa.Column("experiment_method", sa.String(80), nullable=False),
        sa.Column("treatment_ref", sa.String(160), nullable=False),
        sa.Column("control_ref", sa.String(160), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("minimum_sample_size", sa.Integer(), nullable=False),
        sa.Column("experiment_confidence_level", sa.Numeric(8, 6), nullable=False),
        sa.Column("experiment_independent_review_passed", sa.Boolean(), nullable=False),
        sa.Column("metric_id", sa.String(160), nullable=False),
        sa.Column("metric_unit", sa.String(80), nullable=False),
        sa.Column("metric_currency", sa.String(3), nullable=True),
        sa.Column("experiment_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("experiment_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost_ref", sa.String(160), nullable=False),
        sa.Column("cost_amount_minor_units", sa.BigInteger(), nullable=False),
        sa.Column("cost_currency", sa.String(3), nullable=False),
        sa.Column("cost_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost_allocation_method", sa.String(80), nullable=False),
        sa.Column("outcome_ref", sa.String(160), nullable=False),
        sa.Column("outcome_value_decimal", sa.Numeric(30, 12), nullable=False),
        sa.Column("outcome_interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome_interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome_confidence_level", sa.Numeric(8, 6), nullable=False),
        sa.Column("outcome_independent_review_passed", sa.Boolean(), nullable=False),
        sa.Column("causal_claim_allowed", sa.Boolean(), nullable=False),
        sa.UniqueConstraint(
            "bundle_id",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            name="uq_cloe_bundle_exact_scope",
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "idempotency_sha256",
            name="uq_cloe_scope_idempotency",
        ),
        sa.ForeignKeyConstraint(
            [
                "agent_run_ref",
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "scope_grant_authority_sha256",
            ],
            [
                "agent_runtime_run_envelopes.run_id",
                "agent_runtime_run_envelopes.tenant_ref",
                "agent_runtime_run_envelopes.entity_ref",
                "agent_runtime_run_envelopes.store_ref",
                "agent_runtime_run_envelopes.authority_sha256",
            ],
            name="fk_cloe_agent_run_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_ref", "agent_run_terminal_event_sha256"],
            ["agent_runtime_run_events.run_id", "agent_runtime_run_events.event_sha256"],
            name="fk_cloe_agent_run_terminal_receipt",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("sample_size > 0 AND minimum_sample_size > 0", name="ck_cloe_sample_sizes"),
        sa.CheckConstraint("cost_amount_minor_units >= 0", name="ck_cloe_cost_amount"),
        sa.CheckConstraint(
            "experiment_confidence_level > 0 AND "
            "experiment_confidence_level <= 1 AND "
            "outcome_confidence_level > 0 AND outcome_confidence_level <= 1",
            name="ck_cloe_confidence_range",
        ),
        sa.CheckConstraint(
            "lower(experiment_confidence_level::text) NOT IN "
            "('nan','infinity','-infinity') AND "
            "lower(outcome_confidence_level::text) NOT IN "
            "('nan','infinity','-infinity')",
            name="ck_cloe_confidence_finite",
        ),
        sa.CheckConstraint(
            "lower(outcome_value_decimal::text) NOT IN "
            "('nan','infinity','-infinity')",
            name="ck_cloe_outcome_value_finite",
        ),
        sa.CheckConstraint(
            "(metric_unit = 'minor_currency_units' AND "
            "metric_currency ~ '^[A-Z]{3}$' AND "
            "cost_currency = metric_currency) OR "
            "(metric_unit <> 'minor_currency_units' AND metric_currency IS NULL)",
            name="ck_cloe_metric_currency",
        ),
        sa.CheckConstraint(
            "causal_claim_allowed IS FALSE",
            name="ck_cloe_association_only_v1",
        ),
        sa.CheckConstraint(
            "effective_at <= data_as_of AND data_as_of <= authority_checked_at "
            "AND recorded_at = authority_checked_at "
            "AND authority_checked_at < review_due_at",
            name="ck_cloe_temporal_window",
        ),
        sa.CheckConstraint(
            "actor_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$'",
            name="ck_cloe_bundle_actor",
        ),
        sa.CheckConstraint(
            f"scope_grant_authority_sha256 ~ '{HEX64}' AND registry_sha256 ~ '{HEX64}' "
            f"AND idempotency_sha256 ~ '{HEX64}' AND request_sha256 ~ '{HEX64}' "
            f"AND bundle_sha256 ~ '{HEX64}' AND agent_run_terminal_event_sha256 ~ '{HEX64}'",
            name="ck_cloe_bundle_hashes",
        ),
    )
    op.create_index(
        "ix_cloe_scope_recorded",
        BUNDLES,
        ["tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256", "recorded_at"],
    )

    op.create_table(
        LINKS,
        sa.Column("link_id", sa.String(64), primary_key=True),
        sa.Column("bundle_id", sa.String(64), nullable=False),
        *_scope_columns(),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_source", sa.String(160), nullable=False),
        sa.Column("evidence_source_ref", sa.Text(), nullable=False),
        sa.Column("evidence_grade", sa.String(1), nullable=False),
        sa.Column("evidence_effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_effective_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_review_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issuer_actor_id", sa.String(160), nullable=False),
        sa.Column("claims_sha256", sa.String(64), nullable=False),
        sa.Column("link_sha256", sa.String(64), nullable=False),
        _root_fk("link"),
        _evidence_fk("fk_cloe_link_evidence_binding"),
        sa.UniqueConstraint("bundle_id", "purpose", name="uq_cloe_link_purpose"),
        sa.UniqueConstraint("evidence_id", name="uq_cloe_evidence_single_purpose"),
        sa.CheckConstraint(
            "purpose IN ('experiment','cost','business_outcome')",
            name="ck_cloe_link_purpose",
        ),
        sa.CheckConstraint(
            f"scope_grant_authority_sha256 ~ '{HEX64}' AND evidence_sha256 ~ '{HEX64}' "
            f"AND claims_sha256 ~ '{HEX64}' AND link_sha256 ~ '{HEX64}'",
            name="ck_cloe_link_hashes",
        ),
    )
    op.create_index("ix_cloe_link_bundle", LINKS, ["bundle_id", "purpose"])

    op.create_table(
        EVENTS,
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("bundle_id", sa.String(64), nullable=False),
        *_scope_columns(),
        sa.Column("event_index", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(160), nullable=False),
        sa.Column("actor_id", sa.String(160), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_sha256", sa.String(64), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("previous_event_sha256", sa.String(64), nullable=False),
        sa.Column("event_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("evidence_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_source", sa.String(160), nullable=False),
        sa.Column("evidence_source_ref", sa.Text(), nullable=False),
        sa.Column("evidence_grade", sa.String(1), nullable=False),
        sa.Column("evidence_effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_evidence_id", sa.String(), nullable=True),
        sa.Column("review_evidence_sha256", sa.String(64), nullable=True),
        sa.Column("review_evidence_source", sa.String(160), nullable=True),
        sa.Column("review_evidence_source_ref", sa.Text(), nullable=True),
        sa.Column("review_evidence_grade", sa.String(1), nullable=True),
        sa.Column(
            "review_evidence_effective_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("review_attestation_sha256", sa.String(64), nullable=True),
        sa.Column("replacement_bundle_id", sa.String(64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        _root_fk("event"),
        _evidence_fk("fk_cloe_event_evidence_binding"),
        sa.ForeignKeyConstraint(
            [
                "review_evidence_id", "review_evidence_sha256",
                "review_evidence_source", "review_evidence_source_ref",
                "review_evidence_grade", "review_evidence_effective_at",
            ],
            [
                "evidence_records.id", "evidence_records.blob_sha256",
                "evidence_records.source", "evidence_records.source_ref",
                "evidence_records.grade", "evidence_records.effective_at",
            ],
            name="fk_cloe_event_review_evidence_binding",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "replacement_bundle_id", "tenant_ref", "entity_ref",
                "store_ref", "scope_grant_authority_sha256",
            ],
            [
                f"{BUNDLES}.bundle_id", f"{BUNDLES}.tenant_ref",
                f"{BUNDLES}.entity_ref", f"{BUNDLES}.store_ref",
                f"{BUNDLES}.scope_grant_authority_sha256",
            ],
            name="fk_cloe_event_replacement_exact_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("bundle_id", "event_index", name="uq_cloe_event_index"),
        sa.UniqueConstraint("bundle_id", "idempotency_sha256", name="uq_cloe_event_idempotency"),
        sa.CheckConstraint("event_index > 0", name="ck_cloe_event_index"),
        sa.CheckConstraint(
            "occurred_at <= recorded_at",
            name="ck_cloe_event_bitemporal",
        ),
        sa.CheckConstraint(
            "actor_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$' AND "
            "reason_code ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$'",
            name="ck_cloe_event_tokens",
        ),
        sa.CheckConstraint(
            "event_type IN ('bundle_recorded','review_requested','invalidated','revoked','superseded')",
            name="ck_cloe_event_type",
        ),
        sa.CheckConstraint(
            f"scope_grant_authority_sha256 ~ '{HEX64}' AND idempotency_sha256 ~ '{HEX64}' "
            f"AND request_sha256 ~ '{HEX64}' AND previous_event_sha256 ~ '{HEX64}' "
            f"AND event_sha256 ~ '{HEX64}' AND evidence_sha256 ~ '{HEX64}'",
            name="ck_cloe_event_hashes",
        ),
        sa.CheckConstraint(
            "(event_type='bundle_recorded' AND review_evidence_id IS NULL "
            "AND review_evidence_sha256 IS NULL AND review_evidence_source IS NULL "
            "AND review_evidence_source_ref IS NULL AND review_evidence_grade IS NULL "
            "AND review_evidence_effective_at IS NULL "
            "AND review_attestation_sha256 IS NULL AND replacement_bundle_id IS NULL) "
            "OR (event_type IN ('review_requested','invalidated','revoked') "
            "AND review_evidence_id IS NOT NULL "
            "AND review_attestation_sha256 IS NOT NULL "
            "AND replacement_bundle_id IS NULL) "
            "OR (event_type='superseded' AND review_evidence_id IS NOT NULL "
            "AND review_attestation_sha256 IS NOT NULL "
            "AND replacement_bundle_id IS NOT NULL)",
            name="ck_cloe_event_review_authority",
        ),
    )
    op.create_index("ix_cloe_event_bundle", EVENTS, ["bundle_id", "event_index"])
    op.create_index(
        "uq_closed_loop_authority_evidence_source_ref",
        "evidence_records",
        ["source", "source_ref"],
        unique=True,
        postgresql_where=sa.text(f"source IN ({SOURCES_SQL})"),
    )

    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_json_is_canonical_utc(p_value jsonb)
        RETURNS boolean LANGUAGE plpgsql IMMUTABLE
        SET search_path=pg_catalog,{quoted_schema} AS $$
        DECLARE value_text text;
        DECLARE parsed_value timestamptz;
        DECLARE canonical_text text;
        DECLARE micros bigint;
        BEGIN
            IF jsonb_typeof(p_value) IS DISTINCT FROM 'string' THEN
                RETURN false;
            END IF;
            value_text := p_value #>> '{{}}';
            IF value_text !~
               '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}([.][0-9]{{6}})?[+]00:00$' THEN
                RETURN false;
            END IF;
            parsed_value := value_text::timestamptz;
            micros := mod(
                date_part('microseconds', parsed_value AT TIME ZONE 'UTC')::bigint,
                1000000
            );
            canonical_text := to_char(
                parsed_value AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS'
            ) || CASE WHEN micros=0 THEN ''
                ELSE '.' || lpad(micros::text,6,'0') END || '+00:00';
            RETURN value_text IS NOT DISTINCT FROM canonical_text;
        EXCEPTION WHEN others THEN
            RETURN false;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_json_is_canonical_decimal(
          p_value jsonb, p_max_scale integer, p_max_integer_digits integer
        ) RETURNS boolean LANGUAGE plpgsql IMMUTABLE
        SET search_path=pg_catalog,{quoted_schema} AS $$
        DECLARE value_text text;
        DECLARE unsigned_text text;
        DECLARE integer_text text;
        DECLARE fraction_text text;
        BEGIN
            IF jsonb_typeof(p_value) IS DISTINCT FROM 'string' THEN
                RETURN false;
            END IF;
            value_text := p_value #>> '{{}}';
            IF value_text !~ '^-?(0|[1-9][0-9]*)([.][0-9]+)?$' THEN
                RETURN false;
            END IF;
            unsigned_text := ltrim(value_text, '-');
            integer_text := split_part(unsigned_text, '.', 1);
            fraction_text := CASE WHEN position('.' IN unsigned_text)>0
                THEN split_part(unsigned_text, '.', 2) ELSE '' END;
            IF char_length(integer_text)>p_max_integer_digits
               OR (char_length(fraction_text)>p_max_scale
                   AND substring(fraction_text FROM p_max_scale+1) !~ '^0*$') THEN
                RETURN false;
            END IF;
            PERFORM value_text::numeric;
            RETURN true;
        EXCEPTION WHEN others THEN
            RETURN false;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_claims_are_canonical(
          p_purpose text, p_claims jsonb
        ) RETURNS boolean LANGUAGE plpgsql IMMUTABLE
        SET search_path=pg_catalog,{quoted_schema} AS $$
        BEGIN
            IF jsonb_typeof(p_claims) IS DISTINCT FROM 'object' THEN
                RETURN false;
            END IF;
            CASE p_purpose
              WHEN 'experiment' THEN
                RETURN kjds_cloe_json_is_canonical_utc(p_claims->'window_start')
                   AND kjds_cloe_json_is_canonical_utc(p_claims->'window_end')
                   AND kjds_cloe_json_is_canonical_decimal(
                         p_claims->'confidence_level_decimal',6,1);
              WHEN 'cost' THEN
                RETURN kjds_cloe_json_is_canonical_utc(p_claims->'period_start')
                   AND kjds_cloe_json_is_canonical_utc(p_claims->'period_end');
              WHEN 'business_outcome' THEN
                RETURN kjds_cloe_json_is_canonical_utc(p_claims->'interval_start')
                   AND kjds_cloe_json_is_canonical_utc(p_claims->'interval_end')
                   AND kjds_cloe_json_is_canonical_decimal(
                         p_claims->'value_decimal',12,18)
                   AND kjds_cloe_json_is_canonical_decimal(
                         p_claims->'confidence_level_decimal',6,1);
              WHEN 'review_event' THEN
                RETURN true;
              ELSE
                RETURN false;
            END CASE;
        EXCEPTION WHEN others THEN
            RETURN false;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_agent_evidence_is_typed(
          p_payload jsonb, p_metadata jsonb
        ) RETURNS boolean LANGUAGE plpgsql IMMUTABLE
        SET search_path=pg_catalog,{quoted_schema} AS $$
        BEGIN
            RETURN jsonb_typeof(p_metadata)='object'
               AND (SELECT count(*) FROM jsonb_object_keys(p_metadata))=11
               AND p_metadata ?& ARRAY[
                    'contract_id','tenant_ref','entity_ref','store_ref',
                    'authority_sha256','run_id','event_id','event_type',
                    'event_sha256','retention_class','legal_hold']::text[]
               AND NOT EXISTS (
                    SELECT 1 FROM jsonb_each(p_metadata) item
                    WHERE (item.key='legal_hold'
                           AND jsonb_typeof(item.value)<>'boolean')
                       OR (item.key<>'legal_hold'
                           AND jsonb_typeof(item.value)<>'string'))
               AND p_metadata->'legal_hold'='false'::jsonb
               AND jsonb_typeof(p_payload)='object'
               AND (SELECT count(*) FROM jsonb_object_keys(p_payload))=24
               AND p_payload ?& ARRAY[
                    'contract_id','run_id','event_id','event_index','event_type',
                    'reason_code','adapter_sha256','provider_sha256','model_sha256',
                    'adapter_config_sha256','output_sha256','eval_sha256',
                    'input_tokens','output_tokens','cost_usd','latency_ms',
                    'safe_payload','previous_event_sha256','occurred_at',
                    'event_sha256','payload_status','proposal_only','formal_fact',
                    'external_write_allowed']::text[]
               AND NOT EXISTS (
                    SELECT 1 FROM jsonb_each(p_payload) item
                    WHERE (item.key IN (
                             'contract_id','run_id','event_id','event_type','cost_usd',
                             'previous_event_sha256','occurred_at','event_sha256',
                             'payload_status')
                           AND jsonb_typeof(item.value)<>'string')
                       OR (item.key IN (
                             'reason_code','adapter_sha256','provider_sha256',
                             'model_sha256','adapter_config_sha256','output_sha256',
                             'eval_sha256')
                           AND jsonb_typeof(item.value) NOT IN ('null','string'))
                       OR (item.key IN (
                             'event_index','input_tokens','output_tokens','latency_ms')
                           AND (jsonb_typeof(item.value)<>'number'
                                OR item.value #>> '{{}}' !~ '^[0-9]+$'))
                       OR (item.key='safe_payload'
                           AND jsonb_typeof(item.value)<>'object')
                       OR (item.key IN (
                             'proposal_only','formal_fact','external_write_allowed')
                           AND jsonb_typeof(item.value)<>'boolean'))
               AND p_payload->'proposal_only'='true'::jsonb
               AND p_payload->'formal_fact'='false'::jsonb
               AND p_payload->'external_write_allowed'='false'::jsonb
               AND kjds_cloe_json_is_canonical_utc(p_payload->'occurred_at');
        EXCEPTION WHEN others THEN
            RETURN false;
        END;
        $$
        """
    )
    for signature in (
        "kjds_cloe_json_is_canonical_utc(jsonb)",
        "kjds_cloe_json_is_canonical_decimal(jsonb,integer,integer)",
        "kjds_cloe_claims_are_canonical(text,jsonb)",
        "kjds_cloe_agent_evidence_is_typed(jsonb,jsonb)",
    ):
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {ISSUANCE_OWNER_ROLE}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        for helper_runtime in (
            EVENT_ISSUANCE_OWNER_ROLE,
            "kjds_runtime",
            "kjds_g1_runtime",
        ):
            if connection.scalar(
                sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:role)"),
                {"role": helper_runtime},
            ):
                op.execute(
                    f"GRANT EXECUTE ON FUNCTION {signature} TO {helper_runtime}"
                )

    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_register_authority_receipt(p_receipt jsonb)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public AS $$
        DECLARE expected_purpose text;
        DECLARE expected_source text;
        DECLARE expected_issuer text;
        DECLARE expected_contract text;
        DECLARE expected_contract_hash text;
        DECLARE expected_schema text;
        DECLARE existing {quoted_schema}.{AUTHORITY_RECEIPTS}%ROWTYPE;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('kjds-cloe-0096-lifecycle'));
            expected_purpose := CASE session_user
                WHEN '{ATTESTATION_ROLES['experiment']}' THEN 'experiment'
                WHEN '{ATTESTATION_ROLES['cost']}' THEN 'cost'
                WHEN '{ATTESTATION_ROLES['business_outcome']}' THEN 'business_outcome'
                WHEN '{ATTESTATION_ROLES['review_event']}' THEN 'review_event'
                ELSE NULL END;
            IF current_user<>'{ISSUANCE_OWNER_ROLE}' OR expected_purpose IS NULL
               OR pg_has_role(session_user,'{ISSUANCE_OWNER_ROLE}','SET')
               OR EXISTS (
                    SELECT 1 FROM pg_auth_members m
                    JOIN pg_roles granted ON granted.oid=m.roleid
                    JOIN pg_roles member_role ON member_role.oid=m.member
                    WHERE granted.rolname=ANY(ARRAY[{','.join(repr(role) for role in ISSUANCE_ROLES)}])
                       OR member_role.rolname=ANY(ARRAY[{','.join(repr(role) for role in ISSUANCE_ROLES)}])
               ) THEN
                RAISE EXCEPTION USING ERRCODE='42501',
                    MESSAGE='closed-loop attestation registrar is invalid';
            END IF;
            CASE expected_purpose
              WHEN 'experiment' THEN
                expected_source := 'closed-loop-experiment-receipt';
                expected_issuer := 'kjds-closed-loop-experiment-authority';
                expected_contract := 'kjds-closed-loop-experiment-authority-v1';
                expected_contract_hash := 'f97fe473225e7ffc13f42e94f164f3cfc3fba028179e1b04864c09203a7576ea';
                expected_schema := 'a24df85fd76d9bebdd112c619ac8d171814323971f0f8aff162458667b0d1213';
              WHEN 'cost' THEN
                expected_source := 'closed-loop-cost-receipt';
                expected_issuer := 'kjds-closed-loop-cost-authority';
                expected_contract := 'kjds-closed-loop-cost-authority-v1';
                expected_contract_hash := '26d5067a2eb437e757258fa60d072074771161025d3354e87d4710a26bb4602f';
                expected_schema := '298f97894b3742fc42e1c65ac1fd78384243e59f7be8c9f24c2e9174e8f6da68';
              WHEN 'business_outcome' THEN
                expected_source := 'closed-loop-business-outcome-receipt';
                expected_issuer := 'kjds-closed-loop-business_outcome-authority';
                expected_contract := 'kjds-closed-loop-business_outcome-authority-v1';
                expected_contract_hash := '707982da198bd289c13fbc7151ded979e0125672b7b341e5728079467147db6c';
                expected_schema := '8058a54faabd6781b147b96efeb5bc55172a5413fa444f0f1eea153da786b3c9';
              ELSE
                expected_source := 'closed-loop-review-authority-receipt';
                expected_issuer := 'kjds-closed-loop-review-authority';
                expected_contract := 'kjds-closed-loop-review-authority-v1';
                expected_contract_hash := 'd85428cb588631ff0afd0592b08d5c4bd372aed4abbd543c0fbb07f4c5a773e7';
                expected_schema := 'c79a43be77115a956ff2d996261e4f1223ab0468ae08bcb17c3656be1c37f111';
            END CASE;
            IF jsonb_typeof(p_receipt)<>'object'
               OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(p_receipt) key)
                    <> ARRAY['attestation_sha256','attestation_signature_sha256',
                       'authority_receipt_id','content_sha256','data_as_of','effective_at',
                       'effective_until','entity_ref','evidence_id','issuer_actor_id',
                       'issuer_contract_id','issuer_contract_sha256',
                       'issuer_contract_version','issuer_id','metadata_sha256','purpose',
                       'recorded_at','review_due_at','schema_sha256',
                       'scope_grant_authority_sha256','source','source_ref','store_ref',
                       'tenant_ref']::text[]
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(p_receipt) item
                    WHERE jsonb_typeof(item.value)<>'string')
               OR NOT kjds_cloe_json_is_canonical_utc(p_receipt->'data_as_of')
               OR NOT kjds_cloe_json_is_canonical_utc(p_receipt->'effective_at')
               OR NOT kjds_cloe_json_is_canonical_utc(p_receipt->'effective_until')
               OR NOT kjds_cloe_json_is_canonical_utc(p_receipt->'recorded_at')
               OR NOT kjds_cloe_json_is_canonical_utc(p_receipt->'review_due_at')
               OR p_receipt->>'purpose'<>expected_purpose
               OR p_receipt->>'source'<>expected_source
               OR p_receipt->>'issuer_id'<>expected_issuer
               OR p_receipt->>'issuer_contract_id'<>expected_contract
               OR p_receipt->>'issuer_contract_version'<>'1.0.0'
               OR p_receipt->>'issuer_contract_sha256'<>expected_contract_hash
               OR p_receipt->>'schema_sha256'<>expected_schema
               OR p_receipt->>'authority_receipt_id' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
               OR p_receipt->>'evidence_id' !~ '^evd_[0-9a-z]{{20,}}$'
               OR p_receipt->>'content_sha256' !~ '^[0-9a-f]{{64}}$'
               OR p_receipt->>'metadata_sha256' !~ '^[0-9a-f]{{64}}$'
               OR p_receipt->>'attestation_sha256' !~ '^[0-9a-f]{{64}}$'
               OR p_receipt->>'attestation_signature_sha256' !~ '^[0-9a-f]{{64}}$'
               OR p_receipt->>'scope_grant_authority_sha256' !~ '^[0-9a-f]{{64}}$'
               OR COALESCE(p_receipt->>'tenant_ref','')=''
               OR COALESCE(p_receipt->>'entity_ref','')=''
               OR COALESCE(p_receipt->>'store_ref','')=''
               OR (p_receipt->>'effective_at')::timestamptz>
                    (p_receipt->>'recorded_at')::timestamptz
               OR (p_receipt->>'recorded_at')::timestamptz>
                    (p_receipt->>'data_as_of')::timestamptz
               OR (p_receipt->>'data_as_of')::timestamptz>=
                    (p_receipt->>'review_due_at')::timestamptz
               OR statement_timestamp()>=(p_receipt->>'review_due_at')::timestamptz
               OR (p_receipt->>'review_due_at')::timestamptz>
                    (p_receipt->>'effective_until')::timestamptz THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop attestation receipt is invalid';
            END IF;
            INSERT INTO {quoted_schema}.{AUTHORITY_RECEIPTS}(
              authority_receipt_id,purpose,evidence_id,content_sha256,
              metadata_sha256,source,source_ref,attestation_sha256,
              attestation_signature_sha256,issuer_id,issuer_contract_id,
              issuer_contract_version,issuer_contract_sha256,schema_sha256,
              issuer_actor_id,tenant_ref,entity_ref,store_ref,
              scope_grant_authority_sha256,data_as_of,effective_at,
              effective_until,recorded_at,review_due_at)
            VALUES (
              p_receipt->>'authority_receipt_id',expected_purpose,
              p_receipt->>'evidence_id',p_receipt->>'content_sha256',
              p_receipt->>'metadata_sha256',expected_source,p_receipt->>'source_ref',
              p_receipt->>'attestation_sha256',
              p_receipt->>'attestation_signature_sha256',expected_issuer,
              expected_contract,'1.0.0',expected_contract_hash,expected_schema,
              p_receipt->>'issuer_actor_id',p_receipt->>'tenant_ref',
              p_receipt->>'entity_ref',p_receipt->>'store_ref',
              p_receipt->>'scope_grant_authority_sha256',
              (p_receipt->>'data_as_of')::timestamptz,
              (p_receipt->>'effective_at')::timestamptz,
              (p_receipt->>'effective_until')::timestamptz,
              (p_receipt->>'recorded_at')::timestamptz,
              (p_receipt->>'review_due_at')::timestamptz)
            ON CONFLICT (authority_receipt_id) DO NOTHING;
            SELECT * INTO STRICT existing FROM {quoted_schema}.{AUTHORITY_RECEIPTS}
             WHERE authority_receipt_id=p_receipt->>'authority_receipt_id';
            IF existing.purpose<>expected_purpose
               OR existing.evidence_id<>p_receipt->>'evidence_id'
               OR existing.content_sha256<>p_receipt->>'content_sha256'
               OR existing.metadata_sha256<>p_receipt->>'metadata_sha256'
               OR existing.source<>expected_source
               OR existing.source_ref<>p_receipt->>'source_ref'
               OR existing.attestation_sha256<>p_receipt->>'attestation_sha256'
               OR existing.attestation_signature_sha256<>
                    p_receipt->>'attestation_signature_sha256'
               OR existing.issuer_id<>expected_issuer
               OR existing.issuer_contract_id<>expected_contract
               OR existing.issuer_contract_version<>'1.0.0'
               OR existing.issuer_contract_sha256<>expected_contract_hash
               OR existing.schema_sha256<>expected_schema
               OR existing.issuer_actor_id<>p_receipt->>'issuer_actor_id'
               OR existing.tenant_ref<>p_receipt->>'tenant_ref'
               OR existing.entity_ref<>p_receipt->>'entity_ref'
               OR existing.store_ref<>p_receipt->>'store_ref'
               OR existing.scope_grant_authority_sha256<>
                    p_receipt->>'scope_grant_authority_sha256'
               OR existing.data_as_of<>(p_receipt->>'data_as_of')::timestamptz
               OR existing.effective_at<>(p_receipt->>'effective_at')::timestamptz
               OR existing.effective_until<>
                    (p_receipt->>'effective_until')::timestamptz
               OR existing.recorded_at<>(p_receipt->>'recorded_at')::timestamptz
               OR existing.review_due_at<>
                    (p_receipt->>'review_due_at')::timestamptz THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop attestation receipt replay drifted';
            END IF;
            RETURN existing.authority_receipt_id;
        EXCEPTION WHEN others THEN
            IF SQLSTATE IN ('23514','42501') THEN RAISE; END IF;
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='closed-loop attestation registration failed';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_canonical_json(p_value jsonb)
        RETURNS text LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        SET search_path=pg_catalog AS $$
          SELECT CASE jsonb_typeof(p_value)
            WHEN 'object' THEN (
              SELECT '{{' || COALESCE(string_agg(
                to_jsonb(item.key)::text || ':' ||
                {quoted_schema}.kjds_cloe_canonical_json(item.value),
                ',' ORDER BY item.key COLLATE "C"), '') || '}}'
              FROM jsonb_each(p_value) item
            )
            WHEN 'array' THEN (
              SELECT '[' || COALESCE(string_agg(
                {quoted_schema}.kjds_cloe_canonical_json(item.value),
                ',' ORDER BY item.ordinality), '') || ']'
              FROM jsonb_array_elements(p_value) WITH ORDINALITY item(value, ordinality)
            )
            ELSE p_value::text
          END
        $$
        """
    )
    op.execute(
        f"ALTER FUNCTION {quoted_schema}.kjds_cloe_canonical_json(jsonb) "
        f"OWNER TO {ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {quoted_schema}.kjds_cloe_canonical_json(jsonb) "
        "FROM PUBLIC"
    )

    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_issue_evidence(
          p_authority_receipt_id text, p_evidence_id text, p_content bytea,
          p_filename text, p_source text, p_source_ref text,
          p_effective_at timestamptz, p_effective_until timestamptz,
          p_metadata jsonb, p_attestation_sha256 text,
          p_attestation_signature_sha256 text
        ) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public AS $$
        DECLARE receipt {quoted_schema}.{AUTHORITY_RECEIPTS}%ROWTYPE;
        DECLARE evidence {quoted_schema}.evidence_records%ROWTYPE;
        DECLARE issuance {quoted_schema}.{ISSUANCES}%ROWTYPE;
        DECLARE payload jsonb;
        DECLARE content_sha256 text;
        DECLARE metadata_sha256 text;
        DECLARE expected_source text;
        DECLARE expected_contract text;
        DECLARE expected_issuer text;
        DECLARE expected_issuer_contract text;
        DECLARE expected_issuer_hash text;
        DECLARE expected_schema text;
        DECLARE claims jsonb;
        DECLARE expected_claim_keys text[];
        DECLARE computed_claims_sha text;
        DECLARE expected_scope_binding text;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('kjds-cloe-0096-lifecycle'));
            IF session_user<>'{ISSUANCE_RUNTIME_ROLE}'
               OR current_user<>'{ISSUANCE_OWNER_ROLE}'
               OR pg_has_role(session_user,'{ISSUANCE_OWNER_ROLE}','SET')
               OR EXISTS (
                    SELECT 1 FROM pg_auth_members m
                    JOIN pg_roles granted ON granted.oid=m.roleid
                    JOIN pg_roles member_role ON member_role.oid=m.member
                    WHERE granted.rolname=ANY(ARRAY[
                        {','.join(repr(role) for role in ISSUANCE_ROLES)}])
                       OR member_role.rolname=ANY(ARRAY[
                        {','.join(repr(role) for role in ISSUANCE_ROLES)}])
               ) OR NOT EXISTS (
                    SELECT 1 FROM pg_roles owner_role
                    CROSS JOIN pg_roles runtime_role
                    WHERE owner_role.rolname='{ISSUANCE_OWNER_ROLE}'
                      AND NOT owner_role.rolcanlogin
                      AND NOT owner_role.rolsuper
                      AND NOT owner_role.rolinherit
                      AND NOT owner_role.rolcreaterole
                      AND NOT owner_role.rolcreatedb
                      AND NOT owner_role.rolreplication
                      AND owner_role.rolbypassrls
                      AND runtime_role.rolname='{ISSUANCE_RUNTIME_ROLE}'
                      AND runtime_role.rolcanlogin
                      AND NOT runtime_role.rolsuper
                      AND NOT runtime_role.rolinherit
                      AND NOT runtime_role.rolcreaterole
                      AND NOT runtime_role.rolcreatedb
                      AND NOT runtime_role.rolreplication
                      AND NOT runtime_role.rolbypassrls
               ) THEN
                RAISE EXCEPTION USING ERRCODE='42501',
                    MESSAGE='closed-loop Evidence issuer principal is invalid';
            END IF;
            SELECT * INTO STRICT receipt FROM {quoted_schema}.{AUTHORITY_RECEIPTS}
             WHERE authority_receipt_id=p_authority_receipt_id;
            CASE receipt.purpose
              WHEN 'experiment' THEN
                expected_source := 'closed-loop-experiment-receipt';
                expected_contract := 'kjds-closed-loop-experiment-receipt-v1';
                expected_issuer := 'kjds-closed-loop-experiment-authority';
                expected_issuer_contract := 'kjds-closed-loop-experiment-authority-v1';
                expected_issuer_hash := 'f97fe473225e7ffc13f42e94f164f3cfc3fba028179e1b04864c09203a7576ea';
                expected_schema := 'a24df85fd76d9bebdd112c619ac8d171814323971f0f8aff162458667b0d1213';
              WHEN 'cost' THEN
                expected_source := 'closed-loop-cost-receipt';
                expected_contract := 'kjds-closed-loop-cost-receipt-v1';
                expected_issuer := 'kjds-closed-loop-cost-authority';
                expected_issuer_contract := 'kjds-closed-loop-cost-authority-v1';
                expected_issuer_hash := '26d5067a2eb437e757258fa60d072074771161025d3354e87d4710a26bb4602f';
                expected_schema := '298f97894b3742fc42e1c65ac1fd78384243e59f7be8c9f24c2e9174e8f6da68';
              WHEN 'business_outcome' THEN
                expected_source := 'closed-loop-business-outcome-receipt';
                expected_contract := 'kjds-closed-loop-business-outcome-receipt-v1';
                expected_issuer := 'kjds-closed-loop-business_outcome-authority';
                expected_issuer_contract := 'kjds-closed-loop-business_outcome-authority-v1';
                expected_issuer_hash := '707982da198bd289c13fbc7151ded979e0125672b7b341e5728079467147db6c';
                expected_schema := '8058a54faabd6781b147b96efeb5bc55172a5413fa444f0f1eea153da786b3c9';
              WHEN 'review_event' THEN
                expected_source := 'closed-loop-review-authority-receipt';
                expected_contract := 'kjds-closed-loop-review-authority-receipt-v1';
                expected_issuer := 'kjds-closed-loop-review-authority';
                expected_issuer_contract := 'kjds-closed-loop-review-authority-v1';
                expected_issuer_hash := 'd85428cb588631ff0afd0592b08d5c4bd372aed4abbd543c0fbb07f4c5a773e7';
                expected_schema := 'c79a43be77115a956ff2d996261e4f1223ab0468ae08bcb17c3656be1c37f111';
              ELSE
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop authority purpose is invalid';
            END CASE;
            content_sha256 := encode(sha256(p_content),'hex');
            metadata_sha256 := encode(
                sha256(convert_to(p_metadata::jsonb::text,'UTF8')),'hex'
            );
            payload := convert_from(p_content,'UTF8')::jsonb;
            IF jsonb_typeof(payload)<>'object'
               OR convert_from(p_content,'UTF8')<>
                    {quoted_schema}.kjds_cloe_canonical_json(payload)
               OR (SELECT count(*) FROM jsonb_object_keys(payload))<>23
                OR NOT payload ?& ARRAY[
                     'contract_id','purpose','attestation_ref',
                    'authority_receipt_id','issuer_id','issuer_contract_id',
                    'issuer_contract_version','issuer_contract_sha256',
                    'schema_sha256','issuer_actor_id','exact_scope','data_as_of',
                    'effective_at','effective_until','recorded_at','review_due_at',
                    'claims','claims_sha256','attestation_sha256',
                    'attestation_signature_sha256','payload_status',
                     'contains_customer_data','external_write_allowed']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(payload) item
                     WHERE (item.key IN (
                              'contract_id','purpose','attestation_ref',
                              'authority_receipt_id','issuer_id','issuer_contract_id',
                              'issuer_contract_version','issuer_contract_sha256',
                              'schema_sha256','issuer_actor_id','data_as_of',
                              'effective_at','effective_until','recorded_at',
                              'review_due_at','claims_sha256','attestation_sha256',
                              'attestation_signature_sha256','payload_status')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key IN (
                              'contains_customer_data','external_write_allowed')
                            AND jsonb_typeof(item.value)<>'boolean')
                        OR (item.key IN ('exact_scope','claims')
                            AND jsonb_typeof(item.value)<>'object'))
                OR jsonb_typeof(payload->'exact_scope')<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(payload->'exact_scope'))<>4
                OR NOT (payload->'exact_scope') ?& ARRAY[
                     'tenant_ref','entity_ref','store_ref',
                     'scope_grant_authority_sha256']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(payload->'exact_scope') item
                     WHERE jsonb_typeof(item.value)<>'string')
               OR jsonb_typeof(payload->'claims')<>'object'
               OR NOT kjds_cloe_claims_are_canonical(
                    payload->>'purpose',payload->'claims')
               OR NOT kjds_cloe_json_is_canonical_utc(payload->'data_as_of')
               OR NOT kjds_cloe_json_is_canonical_utc(payload->'effective_at')
               OR NOT kjds_cloe_json_is_canonical_utc(payload->'effective_until')
               OR NOT kjds_cloe_json_is_canonical_utc(payload->'recorded_at')
               OR NOT kjds_cloe_json_is_canonical_utc(payload->'review_due_at')
               OR jsonb_typeof(p_metadata)<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(p_metadata))<>24
                OR NOT p_metadata ?& ARRAY[
                    'contract_id','closed_loop_purpose',
                    'closed_loop_claims_sha256',
                    'closed_loop_attestation_sha256',
                    'closed_loop_attestation_signature_sha256',
                    'closed_loop_attestation_ref',
                    'closed_loop_authority_receipt_id','closed_loop_issuer_id',
                    'closed_loop_issuer_contract_id',
                    'closed_loop_issuer_contract_version',
                    'closed_loop_issuer_contract_sha256',
                    'closed_loop_schema_sha256','closed_loop_issuer_actor_id',
                    'closed_loop_data_as_of','closed_loop_recorded_at',
                    'closed_loop_review_due_at','closed_loop_claims',
                    'closed_loop_scope_binding_sha256','tenant_ref','entity_ref',
                     'store_ref','scope_grant_authority_sha256',
                     'retention_class','legal_hold']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(p_metadata) item
                     WHERE (item.key NOT IN ('closed_loop_claims','legal_hold')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key='closed_loop_claims'
                            AND jsonb_typeof(item.value)<>'object')
                        OR (item.key='legal_hold'
                            AND jsonb_typeof(item.value)<>'boolean')) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop authority Evidence schema is invalid';
            END IF;
            IF EXISTS (
                 SELECT 1 FROM jsonb_each(payload) item
                 WHERE item.value='null'::jsonb
               ) OR EXISTS (
                 SELECT 1 FROM jsonb_each(p_metadata) item
                 WHERE item.value='null'::jsonb
               ) OR payload->>'attestation_sha256' IS DISTINCT FROM encode(sha256(convert_to(
                 {quoted_schema}.kjds_cloe_canonical_json(
                    payload - ARRAY[
                      'attestation_sha256','attestation_signature_sha256',
                      'payload_status','contains_customer_data',
                      'external_write_allowed']::text[]
                 ),'UTF8')),'hex') THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop authority attestation binding is invalid';
            END IF;
            claims := payload->'claims';
            expected_claim_keys := CASE receipt.purpose
              WHEN 'experiment' THEN ARRAY[
                'agent_run_ref','experiment_ref','method','treatment_ref',
                'control_ref','sample_size','minimum_sample_size','metric_id',
                'metric_unit','metric_currency','window_start','window_end',
                'confidence_level_decimal','independent_review_passed',
                'causal_claim_allowed']::text[]
              WHEN 'cost' THEN ARRAY[
                'agent_run_ref','experiment_ref','outcome_ref','cost_ref',
                'amount_minor_units','currency','period_start','period_end',
                'allocation_method']::text[]
              WHEN 'business_outcome' THEN ARRAY[
                'agent_run_ref','outcome_ref','experiment_ref','metric_id',
                'metric_unit','metric_currency','method','sample_size',
                'interval_start','interval_end','value_decimal',
                'confidence_level_decimal','independent_review_passed',
                'causal_claim_allowed']::text[]
              WHEN 'review_event' THEN ARRAY[
                'bundle_id','event_type','reason_code','replacement_bundle_id',
                'requested_by_actor_id']::text[]
              ELSE ARRAY[]::text[] END;
            IF (SELECT count(*) FROM jsonb_object_keys(claims))<>
               cardinality(expected_claim_keys)
               OR NOT claims ?& expected_claim_keys
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(claims) item
                    WHERE item.value='null'::jsonb
                      AND NOT (
                        (receipt.purpose='experiment'
                         AND item.key IN ('control_ref','metric_currency'))
                        OR (receipt.purpose='business_outcome'
                            AND item.key='metric_currency')
                        OR (receipt.purpose='review_event'
                            AND item.key='replacement_bundle_id')
                       )
                ) OR (receipt.purpose='experiment' AND EXISTS (
                     SELECT 1 FROM jsonb_each(claims) item
                     WHERE (item.key IN (
                              'agent_run_ref','experiment_ref','method',
                              'treatment_ref','metric_id','metric_unit',
                              'window_start','window_end',
                              'confidence_level_decimal')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key IN ('control_ref','metric_currency')
                            AND jsonb_typeof(item.value) NOT IN ('null','string'))
                        OR (item.key IN ('sample_size','minimum_sample_size')
                            AND jsonb_typeof(item.value)<>'number')
                        OR (item.key IN (
                              'independent_review_passed','causal_claim_allowed')
                            AND jsonb_typeof(item.value)<>'boolean')
                )) OR (receipt.purpose='cost' AND EXISTS (
                     SELECT 1 FROM jsonb_each(claims) item
                     WHERE (item.key IN (
                              'agent_run_ref','experiment_ref','outcome_ref',
                              'cost_ref','currency','period_start','period_end',
                              'allocation_method')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key='amount_minor_units'
                            AND jsonb_typeof(item.value)<>'number')
                )) OR (receipt.purpose='business_outcome' AND EXISTS (
                     SELECT 1 FROM jsonb_each(claims) item
                     WHERE (item.key IN (
                              'agent_run_ref','outcome_ref','experiment_ref',
                              'metric_id','metric_unit','method','interval_start',
                              'interval_end','value_decimal',
                              'confidence_level_decimal')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key='metric_currency'
                            AND jsonb_typeof(item.value) NOT IN ('null','string'))
                        OR (item.key='sample_size'
                            AND jsonb_typeof(item.value)<>'number')
                        OR (item.key IN (
                              'independent_review_passed','causal_claim_allowed')
                            AND jsonb_typeof(item.value)<>'boolean')
                )) OR (receipt.purpose='review_event' AND EXISTS (
                     SELECT 1 FROM jsonb_each(claims) item
                     WHERE (item.key IN (
                              'bundle_id','event_type','reason_code',
                              'requested_by_actor_id')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key='replacement_bundle_id'
                            AND jsonb_typeof(item.value) NOT IN ('null','string'))
                )) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop authority claims schema is invalid';
            END IF;
            computed_claims_sha := encode(
                sha256(convert_to(claims::text,'UTF8')),'hex'
            );
            expected_scope_binding := encode(sha256(convert_to(
                '{{"entity_ref":' || to_jsonb(receipt.entity_ref)::text ||
                ',"scope_grant_authority_sha256":' ||
                    to_jsonb(receipt.scope_grant_authority_sha256)::text ||
                ',"store_ref":' || to_jsonb(receipt.store_ref)::text ||
                ',"tenant_ref":' || to_jsonb(receipt.tenant_ref)::text || '}}',
                'UTF8')),'hex');
            IF (receipt.purpose='experiment' AND (
                    claims->>'agent_run_ref' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'experiment_ref' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'method' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'treatment_ref' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR NOT (jsonb_typeof(claims->'control_ref')='null'
                            OR (jsonb_typeof(claims->'control_ref')='string'
                                AND claims->>'control_ref' ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'))
                    OR claims->>'treatment_ref'=claims->>'control_ref'
                    OR jsonb_typeof(claims->'sample_size')<>'number'
                    OR claims->>'sample_size' !~ '^[0-9]+$'
                    OR (claims->>'sample_size')::numeric NOT BETWEEN 1 AND 1000000000
                    OR jsonb_typeof(claims->'minimum_sample_size')<>'number'
                    OR claims->>'minimum_sample_size' !~ '^[0-9]+$'
                    OR (claims->>'minimum_sample_size')::numeric NOT BETWEEN 1 AND 1000000000
                    OR claims->>'metric_id' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'metric_unit' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR NOT ((claims->>'metric_unit'='minor_currency_units'
                             AND jsonb_typeof(claims->'metric_currency')='string'
                             AND claims->>'metric_currency' ~ '^[A-Z]{{3}}$')
                            OR (claims->>'metric_unit'<>'minor_currency_units'
                                AND jsonb_typeof(claims->'metric_currency')='null'))
                    OR jsonb_typeof(claims->'window_start')<>'string'
                    OR jsonb_typeof(claims->'window_end')<>'string'
                    OR claims->>'window_start' !~
                       '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}([.][0-9]{{6}})?[+]00:00$'
                    OR claims->>'window_end' !~
                       '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}([.][0-9]{{6}})?[+]00:00$'
                    OR (claims->>'window_start')::timestamptz >=
                       (claims->>'window_end')::timestamptz
                    OR jsonb_typeof(claims->'confidence_level_decimal')<>'string'
                    OR claims->>'confidence_level_decimal' !~
                       '^(0|[1-9][0-9]*)([.][0-9]+)?$'
                    OR (claims->>'confidence_level_decimal')::numeric<=0
                    OR (claims->>'confidence_level_decimal')::numeric>1
                    OR (claims->>'confidence_level_decimal')::numeric<>
                       trunc((claims->>'confidence_level_decimal')::numeric,6)
                    OR jsonb_typeof(claims->'independent_review_passed')<>'boolean'
                    OR jsonb_typeof(claims->'causal_claim_allowed')<>'boolean'
                    OR claims->'causal_claim_allowed'<>'false'::jsonb))
               OR (receipt.purpose='cost' AND (
                    claims->>'agent_run_ref' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'experiment_ref' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'outcome_ref' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'cost_ref' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR jsonb_typeof(claims->'amount_minor_units')<>'number'
                    OR claims->>'amount_minor_units' !~ '^[0-9]+$'
                    OR (claims->>'amount_minor_units')::numeric NOT BETWEEN 0 AND 1000000000000000000
                    OR jsonb_typeof(claims->'currency')<>'string'
                    OR claims->>'currency' !~ '^[A-Z]{{3}}$'
                    OR jsonb_typeof(claims->'period_start')<>'string'
                    OR jsonb_typeof(claims->'period_end')<>'string'
                    OR claims->>'period_start' !~
                       '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}([.][0-9]{{6}})?[+]00:00$'
                    OR claims->>'period_end' !~
                       '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}([.][0-9]{{6}})?[+]00:00$'
                    OR (claims->>'period_start')::timestamptz >=
                       (claims->>'period_end')::timestamptz
                    OR claims->>'allocation_method' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'))
               OR (receipt.purpose='business_outcome' AND (
                    claims->>'agent_run_ref' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'outcome_ref' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'experiment_ref' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'metric_id' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'metric_unit' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR NOT ((claims->>'metric_unit'='minor_currency_units'
                             AND jsonb_typeof(claims->'metric_currency')='string'
                             AND claims->>'metric_currency' ~ '^[A-Z]{{3}}$')
                            OR (claims->>'metric_unit'<>'minor_currency_units'
                                AND jsonb_typeof(claims->'metric_currency')='null'))
                    OR claims->>'method' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR jsonb_typeof(claims->'sample_size')<>'number'
                    OR claims->>'sample_size' !~ '^[0-9]+$'
                    OR (claims->>'sample_size')::numeric NOT BETWEEN 1 AND 1000000000
                    OR jsonb_typeof(claims->'interval_start')<>'string'
                    OR jsonb_typeof(claims->'interval_end')<>'string'
                    OR claims->>'interval_start' !~
                       '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}([.][0-9]{{6}})?[+]00:00$'
                    OR claims->>'interval_end' !~
                       '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}([.][0-9]{{6}})?[+]00:00$'
                    OR (claims->>'interval_start')::timestamptz >=
                       (claims->>'interval_end')::timestamptz
                    OR jsonb_typeof(claims->'value_decimal')<>'string'
                    OR claims->>'value_decimal' !~
                       '^-?(0|[1-9][0-9]*)([.][0-9]+)?$'
                    OR (claims->>'value_decimal')::numeric<>
                       trunc((claims->>'value_decimal')::numeric,12)
                    OR abs((claims->>'value_decimal')::numeric)>=1000000000000000000
                    OR jsonb_typeof(claims->'confidence_level_decimal')<>'string'
                    OR claims->>'confidence_level_decimal' !~
                       '^(0|[1-9][0-9]*)([.][0-9]+)?$'
                    OR (claims->>'confidence_level_decimal')::numeric<=0
                    OR (claims->>'confidence_level_decimal')::numeric>1
                    OR (claims->>'confidence_level_decimal')::numeric<>
                       trunc((claims->>'confidence_level_decimal')::numeric,6)
                    OR jsonb_typeof(claims->'independent_review_passed')<>'boolean'
                    OR jsonb_typeof(claims->'causal_claim_allowed')<>'boolean'
                    OR claims->'causal_claim_allowed'<>'false'::jsonb))
               OR (receipt.purpose='review_event' AND (
                    claims->>'bundle_id' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'event_type' NOT IN
                       ('review_requested','invalidated','revoked','superseded')
                    OR claims->>'reason_code' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'requested_by_actor_id' !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                    OR claims->>'requested_by_actor_id'=receipt.issuer_actor_id
                    OR NOT (jsonb_typeof(claims->'replacement_bundle_id')='null'
                            OR (jsonb_typeof(claims->'replacement_bundle_id')='string'
                                AND claims->>'replacement_bundle_id' ~
                                    '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'))
                    OR (claims->>'event_type'='superseded')<>
                       (jsonb_typeof(claims->'replacement_bundle_id')='string'))) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop authority claims values are invalid';
            END IF;
            IF receipt.evidence_id IS DISTINCT FROM p_evidence_id
               OR receipt.content_sha256 IS DISTINCT FROM content_sha256
               OR receipt.metadata_sha256 IS DISTINCT FROM metadata_sha256
               OR receipt.source IS DISTINCT FROM p_source
               OR p_source IS DISTINCT FROM expected_source
               OR receipt.source_ref IS DISTINCT FROM p_source_ref
               OR receipt.attestation_sha256 IS DISTINCT FROM p_attestation_sha256
               OR receipt.attestation_signature_sha256 IS DISTINCT FROM
                    p_attestation_signature_sha256
               OR receipt.issuer_id IS DISTINCT FROM expected_issuer
               OR receipt.issuer_contract_id IS DISTINCT FROM expected_issuer_contract
               OR receipt.issuer_contract_version IS DISTINCT FROM '1.0.0'
               OR receipt.issuer_contract_sha256 IS DISTINCT FROM expected_issuer_hash
               OR receipt.schema_sha256 IS DISTINCT FROM expected_schema
               OR receipt.effective_at IS DISTINCT FROM p_effective_at
               OR receipt.effective_until IS DISTINCT FROM p_effective_until
               OR receipt.recorded_at>receipt.data_as_of
               OR receipt.data_as_of>=receipt.review_due_at
               OR statement_timestamp()>=receipt.review_due_at
               OR receipt.review_due_at>receipt.effective_until
               OR p_filename<>(receipt.purpose || '-' || content_sha256 || '.json')
               OR payload->>'contract_id' IS DISTINCT FROM expected_contract
               OR payload->>'purpose' IS DISTINCT FROM receipt.purpose
               OR payload->>'authority_receipt_id' IS DISTINCT FROM receipt.authority_receipt_id
               OR payload->>'attestation_sha256' IS DISTINCT FROM receipt.attestation_sha256
               OR payload->>'attestation_signature_sha256' IS DISTINCT FROM
                    receipt.attestation_signature_sha256
               OR payload->>'issuer_id' IS DISTINCT FROM receipt.issuer_id
               OR payload->>'issuer_contract_id' IS DISTINCT FROM receipt.issuer_contract_id
               OR payload->>'issuer_contract_version' IS DISTINCT FROM
                    receipt.issuer_contract_version
               OR payload->>'issuer_contract_sha256' IS DISTINCT FROM
                    receipt.issuer_contract_sha256
               OR payload->>'schema_sha256' IS DISTINCT FROM receipt.schema_sha256
               OR payload->>'issuer_actor_id' IS DISTINCT FROM receipt.issuer_actor_id
               OR payload->>'claims_sha256' IS DISTINCT FROM computed_claims_sha
               OR payload->>'payload_status' IS DISTINCT FROM 'authority_projection_only'
               OR payload->'contains_customer_data' IS DISTINCT FROM 'false'::jsonb
               OR payload->'external_write_allowed' IS DISTINCT FROM 'false'::jsonb
               OR (receipt.purpose='review_event'
                   AND payload->'claims'->>'requested_by_actor_id'=
                       receipt.issuer_actor_id)
               OR payload->'exact_scope'->>'tenant_ref' IS DISTINCT FROM receipt.tenant_ref
               OR payload->'exact_scope'->>'entity_ref' IS DISTINCT FROM receipt.entity_ref
               OR payload->'exact_scope'->>'store_ref' IS DISTINCT FROM receipt.store_ref
               OR payload->'exact_scope'->>'scope_grant_authority_sha256' IS DISTINCT FROM
                    receipt.scope_grant_authority_sha256
               OR (payload->>'data_as_of')::timestamptz IS DISTINCT FROM receipt.data_as_of
               OR (payload->>'effective_at')::timestamptz IS DISTINCT FROM receipt.effective_at
               OR (payload->>'effective_until')::timestamptz IS DISTINCT FROM
                    receipt.effective_until
               OR (payload->>'recorded_at')::timestamptz IS DISTINCT FROM receipt.recorded_at
               OR (payload->>'review_due_at')::timestamptz IS DISTINCT FROM receipt.review_due_at
               OR p_metadata->>'contract_id' IS DISTINCT FROM expected_contract
               OR p_metadata->>'closed_loop_purpose' IS DISTINCT FROM receipt.purpose
               OR p_metadata->>'closed_loop_authority_receipt_id' IS DISTINCT FROM
                    receipt.authority_receipt_id
               OR p_metadata->>'closed_loop_attestation_sha256' IS DISTINCT FROM
                    receipt.attestation_sha256
               OR p_metadata->>'closed_loop_attestation_signature_sha256' IS DISTINCT FROM
                    receipt.attestation_signature_sha256
               OR p_metadata->>'closed_loop_issuer_id' IS DISTINCT FROM receipt.issuer_id
               OR p_metadata->>'closed_loop_issuer_contract_id' IS DISTINCT FROM
                    receipt.issuer_contract_id
               OR p_metadata->>'closed_loop_issuer_contract_version' IS DISTINCT FROM
                    receipt.issuer_contract_version
               OR p_metadata->>'closed_loop_issuer_contract_sha256' IS DISTINCT FROM
                    receipt.issuer_contract_sha256
               OR p_metadata->>'closed_loop_schema_sha256' IS DISTINCT FROM receipt.schema_sha256
               OR p_metadata->>'closed_loop_issuer_actor_id' IS DISTINCT FROM receipt.issuer_actor_id
               OR p_metadata->'closed_loop_claims' IS DISTINCT FROM claims
               OR p_metadata->>'closed_loop_claims_sha256' IS DISTINCT FROM computed_claims_sha
               OR p_metadata->>'closed_loop_scope_binding_sha256' IS DISTINCT FROM
                    expected_scope_binding
               OR p_metadata->>'closed_loop_attestation_ref' IS DISTINCT FROM
                    payload->>'attestation_ref'
               OR p_metadata->>'closed_loop_data_as_of' IS DISTINCT FROM
                    payload->>'data_as_of'
               OR p_metadata->>'closed_loop_recorded_at' IS DISTINCT FROM
                    payload->>'recorded_at'
               OR p_metadata->>'closed_loop_review_due_at' IS DISTINCT FROM
                    payload->>'review_due_at'
               OR p_metadata->>'retention_class' IS DISTINCT FROM 'compliance'
               OR p_metadata->'legal_hold' IS DISTINCT FROM 'false'::jsonb
               OR p_metadata->>'tenant_ref' IS DISTINCT FROM receipt.tenant_ref
               OR p_metadata->>'entity_ref' IS DISTINCT FROM receipt.entity_ref
               OR p_metadata->>'store_ref' IS DISTINCT FROM receipt.store_ref
               OR p_metadata->>'scope_grant_authority_sha256' IS DISTINCT FROM
                    receipt.scope_grant_authority_sha256
               OR p_source_ref<>(expected_source || '://' ||
                    expected_scope_binding || '/' || computed_claims_sha || '/' ||
                    content_sha256) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop authority receipt binding drifted';
            END IF;
            INSERT INTO {quoted_schema}.evidence_blobs
              (sha256,byte_size,content_bytes,created_at)
            VALUES (content_sha256,octet_length(p_content),p_content,
                    statement_timestamp())
            ON CONFLICT (sha256) DO NOTHING;
            IF NOT EXISTS (SELECT 1 FROM {quoted_schema}.evidence_blobs b
                           WHERE b.sha256=content_sha256
                             AND b.byte_size=octet_length(p_content)
                             AND b.content_bytes=p_content) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence blob drifted';
            END IF;
            INSERT INTO {quoted_schema}.evidence_records
              (id,blob_sha256,filename,content_type,source,source_ref,grade,
               effective_at,effective_until,recorded_at,created_by,metadata_json)
            VALUES (p_evidence_id,content_sha256,p_filename,'application/json',
                     p_source,p_source_ref,'A',p_effective_at,p_effective_until,
                    receipt.recorded_at,receipt.issuer_actor_id,p_metadata)
            ON CONFLICT DO NOTHING;
            SELECT * INTO STRICT evidence FROM {quoted_schema}.evidence_records
             WHERE id=p_evidence_id;
            IF evidence.blob_sha256<>content_sha256
               OR evidence.filename<>p_filename
               OR evidence.content_type<>'application/json'
               OR evidence.source<>p_source OR evidence.source_ref<>p_source_ref
               OR evidence.grade<>'A' OR evidence.effective_at<>p_effective_at
               OR evidence.effective_until<>p_effective_until
               OR evidence.recorded_at<>receipt.recorded_at
               OR evidence.created_by<>receipt.issuer_actor_id
               OR evidence.metadata_json::jsonb<>p_metadata::jsonb THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence replay drifted';
            END IF;
            INSERT INTO {quoted_schema}.{ISSUANCES}
              (evidence_id,authority_receipt_id,content_sha256,source,source_ref,
               attestation_sha256,attestation_signature_sha256)
            VALUES (evidence.id,receipt.authority_receipt_id,content_sha256,
                    p_source,p_source_ref,p_attestation_sha256,
                    p_attestation_signature_sha256)
            ON CONFLICT (evidence_id) DO NOTHING;
            SELECT * INTO STRICT issuance FROM {quoted_schema}.{ISSUANCES}
             WHERE evidence_id=evidence.id;
            IF issuance.authority_receipt_id<>receipt.authority_receipt_id
               OR issuance.content_sha256<>content_sha256
               OR issuance.source<>p_source OR issuance.source_ref<>p_source_ref
               OR issuance.attestation_sha256<>p_attestation_sha256
               OR issuance.attestation_signature_sha256<>
                    p_attestation_signature_sha256 THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop issuance replay drifted';
            END IF;
            RETURN evidence.id;
        EXCEPTION WHEN others THEN
            IF SQLSTATE IN ('23514','42501') THEN RAISE; END IF;
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='closed-loop Evidence issuance failed';
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_event_principal_is_current()
        RETURNS boolean LANGUAGE sql STABLE
        SET search_path=pg_catalog AS $$
          SELECT
            session_user=ANY(ARRAY['kjds_runtime','kjds_g1_runtime'])
            AND EXISTS (
              SELECT 1
              FROM pg_roles caller
              CROSS JOIN pg_roles event_owner
              WHERE caller.rolname=session_user
                AND caller.rolcanlogin
                AND NOT caller.rolsuper
                AND NOT caller.rolinherit
                AND NOT caller.rolcreaterole
                AND NOT caller.rolcreatedb
                AND NOT caller.rolreplication
                AND caller.rolbypassrls
                AND event_owner.rolname='{EVENT_ISSUANCE_OWNER_ROLE}'
                AND NOT event_owner.rolcanlogin
                AND NOT event_owner.rolsuper
                AND NOT event_owner.rolinherit
                AND NOT event_owner.rolcreaterole
                AND NOT event_owner.rolcreatedb
                AND NOT event_owner.rolreplication
                AND event_owner.rolbypassrls
            )
            AND NOT EXISTS (
              SELECT 1
              FROM pg_auth_members membership
              JOIN pg_roles granted ON granted.oid=membership.roleid
              JOIN pg_roles member_role ON member_role.oid=membership.member
              WHERE granted.rolname=ANY(ARRAY[
                {','.join(repr(role) for role in ISSUANCE_ROLES)}])
                 OR member_role.rolname=ANY(ARRAY[
                {','.join(repr(role) for role in ISSUANCE_ROLES)}])
            )
            AND NOT EXISTS (
              SELECT 1
              FROM unnest(ARRAY[
                {','.join(repr(role) for role in ISSUANCE_ROLES)}]) AS role_name
              WHERE pg_has_role(session_user,role_name,'SET')
            )
            AND has_table_privilege(
              session_user,'{quoted_schema}.{BUNDLES}','INSERT')
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_issue_event_evidence(
          p_evidence_id text, p_content bytea, p_filename text,
          p_source_ref text, p_effective_at timestamptz,
          p_recorded_at timestamptz, p_metadata jsonb
        ) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public AS $$
        DECLARE evidence {quoted_schema}.evidence_records%ROWTYPE;
        DECLARE payload jsonb;
        DECLARE content_sha256 text;
        DECLARE computed_event_sha256 text;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtext('kjds-cloe-0096-lifecycle'));
            IF current_user<>'{EVENT_ISSUANCE_OWNER_ROLE}'
               OR NOT {quoted_schema}.kjds_cloe_event_principal_is_current() THEN
                RAISE EXCEPTION USING ERRCODE='42501',
                    MESSAGE='closed-loop event Evidence issuer principal is invalid';
            END IF;
            payload := convert_from(p_content,'UTF8')::jsonb;
            content_sha256 := encode(sha256(p_content),'hex');
            IF jsonb_typeof(payload)<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(payload))<>17
               OR NOT payload ?& ARRAY[
                    'contract_id','bundle_id','event_index','event_type',
                    'reason_code','actor_id','request_sha256',
                    'previous_event_sha256','occurred_at','event_sha256',
                    'review_evidence_ref','replacement_bundle_id','payload_status',
                     'candidate_created','transition_allowed','promotion_allowed',
                     'external_write_allowed']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(payload) item
                     WHERE (item.key IN (
                              'contract_id','bundle_id','event_type','reason_code',
                              'actor_id','request_sha256','previous_event_sha256',
                              'occurred_at','event_sha256','payload_status')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key='event_index'
                            AND jsonb_typeof(item.value)<>'number')
                        OR (item.key IN (
                              'review_evidence_ref','replacement_bundle_id')
                            AND jsonb_typeof(item.value) NOT IN ('null','string'))
                        OR (item.key IN (
                              'candidate_created','transition_allowed',
                              'promotion_allowed','external_write_allowed')
                            AND jsonb_typeof(item.value)<>'boolean'))
               OR NOT {quoted_schema}.kjds_cloe_json_is_canonical_utc(
                    payload->'occurred_at')
               OR jsonb_typeof(p_metadata)<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(p_metadata))<>13
               OR NOT p_metadata ?& ARRAY[
                    'contract_id','bundle_id','event_id','event_type',
                    'event_sha256','review_evidence_ref','replacement_bundle_id',
                    'tenant_ref','entity_ref','store_ref',
                     'scope_grant_authority_sha256','retention_class',
                     'legal_hold']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(p_metadata) item
                     WHERE (item.key IN (
                              'contract_id','bundle_id','event_id','event_type',
                              'event_sha256','tenant_ref','entity_ref','store_ref',
                              'scope_grant_authority_sha256','retention_class')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key IN (
                              'review_evidence_ref','replacement_bundle_id')
                            AND jsonb_typeof(item.value) NOT IN ('null','string'))
                        OR (item.key='legal_hold'
                            AND jsonb_typeof(item.value)<>'boolean')) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop event Evidence issuance is invalid';
            END IF;
            IF EXISTS (
                 SELECT 1 FROM jsonb_each(payload) item
                 WHERE item.value='null'::jsonb
                   AND item.key NOT IN
                       ('review_evidence_ref','replacement_bundle_id')
               ) OR EXISTS (
                 SELECT 1 FROM jsonb_each(p_metadata) item
                 WHERE item.value='null'::jsonb
                   AND item.key NOT IN
                       ('review_evidence_ref','replacement_bundle_id')
               ) OR jsonb_typeof(payload->'reason_code')<>'string'
                  OR NOT (jsonb_typeof(payload->'review_evidence_ref')
                          IN ('null','string'))
                  OR NOT (jsonb_typeof(payload->'replacement_bundle_id')
                          IN ('null','string')) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop event Evidence issuance is invalid';
            END IF;
            computed_event_sha256 := encode(sha256(convert_to(concat_ws(chr(31),
                payload->>'bundle_id',payload->>'event_index',
                payload->>'event_type',payload->>'reason_code',
                payload->>'actor_id',payload->>'request_sha256',
                payload->>'previous_event_sha256',payload->>'occurred_at'
            ),'UTF8')),'hex');
            IF p_evidence_id<>(
                    'evd_' || substr(content_sha256,1,40))
               OR p_filename<>((p_metadata->>'event_id') || '.json')
               OR p_metadata->>'event_id' IS DISTINCT FROM
                     ('cloev_' || substr(computed_event_sha256,1,40))
               OR p_source_ref<>(
                    'closed-loop-evolution://' ||
                    (p_metadata->>'bundle_id') || '/' ||
                    (p_metadata->>'event_id'))
               OR payload->>'contract_id' IS DISTINCT FROM
                     'kjds-governed-closed-loop-evolution-event-v1'
               OR payload->>'bundle_id' IS DISTINCT FROM p_metadata->>'bundle_id'
               OR payload->>'event_type' IS DISTINCT FROM p_metadata->>'event_type'
               OR payload->>'event_sha256' IS DISTINCT FROM p_metadata->>'event_sha256'
               OR payload->>'event_sha256' IS DISTINCT FROM computed_event_sha256
               OR payload->>'review_evidence_ref'
                    IS DISTINCT FROM p_metadata->>'review_evidence_ref'
               OR payload->>'replacement_bundle_id'
                    IS DISTINCT FROM p_metadata->>'replacement_bundle_id'
               OR payload->>'payload_status' IS DISTINCT FROM 'hash_and_code_only'
               OR payload->'candidate_created' IS DISTINCT FROM 'false'::jsonb
               OR payload->'transition_allowed' IS DISTINCT FROM 'false'::jsonb
               OR payload->'promotion_allowed' IS DISTINCT FROM 'false'::jsonb
               OR payload->'external_write_allowed' IS DISTINCT FROM 'false'::jsonb
               OR p_metadata->>'contract_id' IS DISTINCT FROM
                     'kjds-governed-closed-loop-evolution-event-v1'
               OR p_metadata->>'scope_grant_authority_sha256' !~ '{HEX64}'
               OR p_metadata->>'tenant_ref' !~
                    '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
               OR p_metadata->>'entity_ref' !~
                    '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
               OR p_metadata->>'store_ref' !~
                    '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
               OR p_metadata->>'retention_class' IS DISTINCT FROM 'compliance'
               OR p_metadata->'legal_hold' IS DISTINCT FROM 'false'::jsonb
               OR (payload->>'occurred_at')::timestamptz<>p_effective_at
               OR p_effective_at<>p_recorded_at
               OR NOT EXISTS (
                    SELECT 1 FROM {quoted_schema}.{BUNDLES} root
                    WHERE root.bundle_id=p_metadata->>'bundle_id'
                      AND root.tenant_ref=p_metadata->>'tenant_ref'
                      AND root.entity_ref=p_metadata->>'entity_ref'
                      AND root.store_ref=p_metadata->>'store_ref'
                      AND root.scope_grant_authority_sha256=
                          p_metadata->>'scope_grant_authority_sha256'
                   ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop event Evidence issuance is invalid';
            END IF;
            INSERT INTO {quoted_schema}.evidence_blobs
              (sha256,byte_size,content_bytes,created_at)
            VALUES (content_sha256,octet_length(p_content),p_content,p_recorded_at)
            ON CONFLICT (sha256) DO NOTHING;
            IF NOT EXISTS (SELECT 1 FROM {quoted_schema}.evidence_blobs blob
                           WHERE blob.sha256=content_sha256
                             AND blob.byte_size=octet_length(p_content)
                             AND blob.content_bytes=p_content) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop event Evidence issuance is invalid';
            END IF;
            INSERT INTO {quoted_schema}.evidence_records
              (id,blob_sha256,filename,content_type,source,source_ref,grade,
               effective_at,effective_until,recorded_at,created_by,metadata_json)
            VALUES (p_evidence_id,content_sha256,p_filename,'application/json',
                    'governed-closed-loop-evolution',p_source_ref,'D',
                    p_effective_at,NULL,p_recorded_at,
                    'kjds-closed-loop-evolution',p_metadata)
            ON CONFLICT DO NOTHING;
            SELECT * INTO STRICT evidence FROM {quoted_schema}.evidence_records
             WHERE id=p_evidence_id;
            IF evidence.blob_sha256<>content_sha256
               OR evidence.filename<>p_filename
               OR evidence.content_type<>'application/json'
               OR evidence.source<>'governed-closed-loop-evolution'
               OR evidence.source_ref<>p_source_ref OR evidence.grade<>'D'
               OR evidence.effective_at<>p_effective_at
               OR evidence.effective_until IS NOT NULL
               OR evidence.recorded_at<>p_recorded_at
               OR evidence.created_by<>'kjds-closed-loop-evolution'
               OR evidence.metadata_json::jsonb<>p_metadata::jsonb THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop event Evidence issuance is invalid';
            END IF;
            RETURN evidence.id;
        EXCEPTION
        WHEN insufficient_privilege THEN
            RAISE EXCEPTION USING ERRCODE='42501',
                MESSAGE='closed-loop event Evidence issuer principal is invalid';
        WHEN check_violation THEN
            RAISE;
        WHEN others THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='closed-loop event Evidence issuance failed';
        END;
        $$
        """
    )
    op.execute(
        f"ALTER TABLE {quoted_schema}.{AUTHORITY_RECEIPTS} "
        f"OWNER TO {ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"ALTER TABLE {quoted_schema}.{ISSUANCES} OWNER TO {ISSUANCE_OWNER_ROLE}"
    )
    _grant_introduced_acl(connection, schema=schema)
    op.execute(
        f"GRANT SELECT ON {quoted_schema}.{AUTHORITY_RECEIPTS} TO "
        f"{ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"GRANT SELECT,INSERT ON {quoted_schema}.{ISSUANCES} "
        f"TO {ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"GRANT SELECT ON {quoted_schema}.{BUNDLES},{quoted_schema}.{EVENTS} "
        f"TO {ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"GRANT SELECT ON {quoted_schema}.{BUNDLES} TO "
        f"{EVENT_ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"REVOKE ALL ON {quoted_schema}.{AUTHORITY_RECEIPTS},"
        f"{quoted_schema}.{ISSUANCES} FROM PUBLIC"
    )
    op.execute(
        f"ALTER FUNCTION {quoted_schema}.kjds_cloe_register_authority_receipt(jsonb) "
        f"OWNER TO {ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION "
        f"{quoted_schema}.kjds_cloe_register_authority_receipt(jsonb) FROM PUBLIC"
    )
    for authority_role in ATTESTATION_ROLES.values():
        op.execute(
            f"GRANT EXECUTE ON FUNCTION "
            f"{quoted_schema}.kjds_cloe_register_authority_receipt(jsonb) "
            f"TO {authority_role}"
        )
    signature = (
        "(text,text,bytea,text,text,text,timestamptz,timestamptz,"
        "jsonb,text,text)"
    )
    op.execute(
        f"ALTER FUNCTION {quoted_schema}.kjds_cloe_issue_evidence{signature} "
        f"OWNER TO {ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {quoted_schema}.kjds_cloe_issue_evidence"
        f"{signature} FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION {quoted_schema}.kjds_cloe_issue_evidence"
        f"{signature} TO {ISSUANCE_RUNTIME_ROLE}"
    )
    event_signature = "(text,bytea,text,text,timestamptz,timestamptz,jsonb)"
    op.execute(
        f"ALTER FUNCTION {quoted_schema}.kjds_cloe_event_principal_is_current() "
        f"OWNER TO {EVENT_ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION "
        f"{quoted_schema}.kjds_cloe_event_principal_is_current() FROM PUBLIC"
    )
    op.execute(
        f"ALTER FUNCTION {quoted_schema}.kjds_cloe_issue_event_evidence"
        f"{event_signature} OWNER TO {EVENT_ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {quoted_schema}.kjds_cloe_issue_event_evidence"
        f"{event_signature} FROM PUBLIC"
    )
    for event_runtime_role in ("kjds_runtime", "kjds_g1_runtime"):
        if connection.scalar(
            sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=:role)"),
            {"role": event_runtime_role},
        ):
            op.execute(
                f"GRANT EXECUTE ON FUNCTION "
                f"{quoted_schema}.kjds_cloe_issue_event_evidence{event_signature} "
                f"TO {event_runtime_role}"
            )

    op.execute(
        """
        CREATE FUNCTION kjds_cloe_prevent_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION USING ERRCODE='55000',
                MESSAGE='governed closed-loop ledger is append-only';
        END;
        $$
        """
    )
    for table in (*TABLES, AUTHORITY_RECEIPTS, ISSUANCES):
        op.execute(
            f"CREATE TRIGGER trg_cloe_{table}_immutable BEFORE UPDATE OR DELETE "
            f"ON {table} FOR EACH ROW EXECUTE FUNCTION kjds_cloe_prevent_mutation()"
        )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_prevent_evidence_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='INSERT' THEN
                IF NEW.source IN ({AUTHORITY_SOURCES_SQL}) AND (
                    current_user<>'{ISSUANCE_OWNER_ROLE}'
                    OR session_user<>'{ISSUANCE_RUNTIME_ROLE}'
                    OR pg_has_role(session_user,'{ISSUANCE_OWNER_ROLE}','SET')
                    OR EXISTS (
                        SELECT 1 FROM pg_auth_members m
                        JOIN pg_roles granted ON granted.oid=m.roleid
                        JOIN pg_roles member_role ON member_role.oid=m.member
                        WHERE granted.rolname=ANY(ARRAY[
                            {','.join(repr(role) for role in ISSUANCE_ROLES)}])
                           OR member_role.rolname=ANY(ARRAY[
                            {','.join(repr(role) for role in ISSUANCE_ROLES)}])
                    )
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='42501',
                        MESSAGE='closed-loop Grade-A Evidence requires its issuer';
                END IF;
                IF NEW.source='governed-closed-loop-evolution' THEN
                    IF current_user<>'{EVENT_ISSUANCE_OWNER_ROLE}' THEN
                        RAISE EXCEPTION USING ERRCODE='42501',
                            MESSAGE='closed-loop event Evidence requires its issuer';
                    END IF;
                    IF NOT {quoted_schema}.kjds_cloe_event_principal_is_current() THEN
                        RAISE EXCEPTION USING ERRCODE='42501',
                            MESSAGE='closed-loop event Evidence requires its issuer';
                    END IF;
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.source IN ({SOURCES_SQL}) THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE='closed-loop Evidence is append-only';
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_cloe_evidence_immutable BEFORE INSERT OR UPDATE OR DELETE ON evidence_records "
        "FOR EACH ROW EXECUTE FUNCTION kjds_cloe_prevent_evidence_mutation()"
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_prevent_blob_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM evidence_records
                WHERE blob_sha256=OLD.sha256 AND source IN ({SOURCES_SQL})
            ) THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE='closed-loop Evidence blob is append-only';
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_cloe_blob_immutable BEFORE UPDATE OR DELETE "
        "ON evidence_blobs FOR EACH ROW EXECUTE FUNCTION "
        "kjds_cloe_prevent_blob_mutation()"
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_prevent_generic_lineage()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM evidence_records
                WHERE id=NEW.from_id AND source IN ({SOURCES_SQL})
            ) OR EXISTS (
                SELECT 1 FROM evidence_records
                WHERE NEW.to_type='evidence' AND id=NEW.to_id
                  AND source IN ({SOURCES_SQL})
            ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence lineage is ledger-owned';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_cloe_generic_lineage BEFORE INSERT OR UPDATE ON lineage_edges "
        "FOR EACH ROW EXECUTE FUNCTION kjds_cloe_prevent_generic_lineage()"
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_validator_principal_is_current()
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path=pg_catalog AS $$
          SELECT
            current_user='{ISSUANCE_OWNER_ROLE}'
            AND session_user=ANY(ARRAY['kjds_runtime','kjds_g1_runtime'])
            AND EXISTS (
              SELECT 1
              FROM pg_roles caller
              CROSS JOIN pg_roles owner_role
              WHERE caller.rolname=session_user
                AND caller.rolcanlogin AND NOT caller.rolsuper
                AND NOT caller.rolinherit AND NOT caller.rolcreaterole
                AND NOT caller.rolcreatedb AND NOT caller.rolreplication
                AND caller.rolbypassrls
                AND owner_role.rolname='{ISSUANCE_OWNER_ROLE}'
                AND NOT owner_role.rolcanlogin AND NOT owner_role.rolsuper
                AND NOT owner_role.rolinherit AND NOT owner_role.rolcreaterole
                AND NOT owner_role.rolcreatedb AND NOT owner_role.rolreplication
                AND owner_role.rolbypassrls
            )
            AND NOT EXISTS (
              SELECT 1
              FROM pg_auth_members membership
              JOIN pg_roles granted ON granted.oid=membership.roleid
              JOIN pg_roles member_role ON member_role.oid=membership.member
              WHERE granted.rolname=ANY(ARRAY[
                {','.join(repr(role) for role in ISSUANCE_ROLES)}])
                 OR member_role.rolname=ANY(ARRAY[
                {','.join(repr(role) for role in ISSUANCE_ROLES)}])
            )
            AND NOT EXISTS (
              SELECT 1
              FROM unnest(ARRAY[
                {','.join(repr(role) for role in ISSUANCE_ROLES)}]) role_name
              WHERE pg_has_role(session_user,role_name,'SET')
            )
        $$
        """
    )
    op.execute(
        f"ALTER FUNCTION {quoted_schema}.kjds_cloe_validator_principal_is_current() "
        f"OWNER TO {ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION "
        f"{quoted_schema}.kjds_cloe_validator_principal_is_current() FROM PUBLIC"
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_review_issuer_is_independent(
            p_bundle_id text,
            p_issuer_actor_id text
        )
        RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path=pg_catalog AS $$
          SELECT NOT EXISTS (
            SELECT 1 FROM {quoted_schema}.{LINKS} supporting
            WHERE supporting.bundle_id=p_bundle_id
              AND supporting.issuer_actor_id=p_issuer_actor_id
          )
        $$
        """
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION "
        f"{quoted_schema}.kjds_cloe_review_issuer_is_independent(text,text) "
        "FROM PUBLIC"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION "
        f"{quoted_schema}.kjds_cloe_review_issuer_is_independent(text,text) "
        f"TO {ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_validate_agent_run_contract(
            p_run_id text,
            p_tenant_ref text,
            p_entity_ref text,
            p_store_ref text,
            p_authority_sha256 text,
            p_data_as_of timestamptz,
            p_checked_at timestamptz,
            p_terminal_sha256 text
        )
        RETURNS void LANGUAGE plpgsql
        SET search_path=pg_catalog,{quoted_schema} AS $$
        DECLARE run_row agent_runtime_run_envelopes%ROWTYPE;
        DECLARE run_event agent_runtime_run_events%ROWTYPE;
        DECLARE evidence evidence_records%ROWTYPE;
        DECLARE blob_bytes bytea;
        DECLARE evidence_payload jsonb;
        DECLARE safe jsonb;
        DECLARE route_configs jsonb;
        DECLARE safe_text text;
        DECLARE cost_text text;
        DECLARE occurred_text text;
        DECLARE preimage text;
        DECLARE expected_content text;
        DECLARE expected_event_id text;
        DECLARE previous_type text;
        DECLARE previous_hash text := repeat('0',64);
        DECLARE previous_occurred_at timestamptz;
        DECLARE previous_reason text;
        DECLARE previous_adapter text;
        DECLARE previous_provider text;
        DECLARE previous_model text;
        DECLARE previous_config text;
        DECLARE previous_output text;
        DECLARE previous_eval text;
        DECLARE expected_index integer := 1;
        DECLARE attempt_no integer;
        DECLARE started_count integer := 0;
        DECLARE terminal_attempt_count integer := 0;
        DECLARE aggregate_input_tokens bigint := 0;
        DECLARE aggregate_output_tokens bigint := 0;
        DECLARE aggregate_latency_ms bigint := 0;
        DECLARE aggregate_cost numeric := 0;
        BEGIN
            SELECT * INTO run_row
            FROM agent_runtime_run_envelopes
            WHERE run_id=p_run_id
              AND tenant_ref=p_tenant_ref
              AND entity_ref=p_entity_ref
              AND store_ref=p_store_ref
              AND authority_sha256=p_authority_sha256;
            IF run_row.run_id IS NULL
               OR run_row.max_attempts<1 OR run_row.max_attempts>8 THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop AgentRun envelope is invalid';
            END IF;
            FOR run_event IN
                SELECT * FROM agent_runtime_run_events
                WHERE run_id=p_run_id ORDER BY event_index
            LOOP
                safe := run_event.safe_payload_json::jsonb;
                cost_text := rtrim(rtrim(run_event.cost_usd::text,'0'),'.');
                IF cost_text='' THEN cost_text := '0'; END IF;
                IF run_event.event_index<>expected_index
                   OR run_event.tenant_ref<>p_tenant_ref
                   OR run_event.entity_ref<>p_entity_ref
                   OR run_event.store_ref<>p_store_ref
                   OR run_event.authority_sha256<>p_authority_sha256
                   OR run_event.previous_event_sha256<>previous_hash
                   OR run_event.occurred_at>p_data_as_of
                   OR run_event.recorded_at>p_data_as_of
                   OR run_event.recorded_at<run_event.occurred_at
                   OR (previous_occurred_at IS NOT NULL
                       AND run_event.occurred_at<previous_occurred_at)
                   OR run_event.event_type NOT IN (
                       'run_started','route_selected','attempt_started',
                       'attempt_completed','attempt_denied','attempt_failed',
                       'eval_completed','run_succeeded','run_failed','run_denied',
                       'unknown_outcome')
                   OR run_event.previous_event_sha256 !~ '^[0-9a-f]{{64}}$'
                   OR run_event.event_sha256 !~ '^[0-9a-f]{{64}}$'
                   OR run_event.input_tokens<0 OR run_event.output_tokens<0
                   OR run_event.cost_usd<0 OR run_event.latency_ms<0
                   OR jsonb_typeof(safe)<>'object'
                   OR (run_event.reason_code IS NOT NULL AND
                       run_event.reason_code !~
                       '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$')
                   OR EXISTS (
                       SELECT 1 FROM unnest(ARRAY[
                           run_event.adapter_sha256,run_event.provider_sha256,
                           run_event.model_sha256,run_event.adapter_config_sha256,
                           run_event.output_sha256,run_event.eval_sha256
                       ]) digest WHERE digest IS NOT NULL
                           AND digest !~ '^[0-9a-f]{{64}}$'
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='closed-loop AgentRun event shape is invalid';
                END IF;
                IF previous_type IS NULL
                   AND run_event.event_type IS DISTINCT FROM 'run_started' THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='closed-loop AgentRun must start with run_started';
                END IF;
                IF NOT (
                    (previous_type IS NULL AND run_event.event_type='run_started') OR
                    (previous_type='run_started' AND run_event.event_type IN
                        ('route_selected','run_denied')) OR
                    (previous_type='route_selected' AND run_event.event_type IN
                        ('attempt_started','run_failed','unknown_outcome')) OR
                    (previous_type='attempt_started' AND run_event.event_type IN
                        ('attempt_completed','attempt_denied','attempt_failed',
                         'unknown_outcome')) OR
                    (previous_type='attempt_completed' AND run_event.event_type IN
                        ('eval_completed','unknown_outcome')) OR
                    (previous_type='attempt_denied' AND run_event.event_type IN
                        ('run_denied','unknown_outcome')) OR
                    (previous_type='attempt_failed' AND run_event.event_type IN
                        ('attempt_started','run_failed','unknown_outcome')) OR
                    (previous_type='eval_completed' AND run_event.event_type IN
                        ('run_succeeded','unknown_outcome'))
                ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='closed-loop AgentRun transition is invalid';
                END IF;

                CASE run_event.event_type
                WHEN 'run_started' THEN
                    IF safe<>'{{}}'::jsonb OR run_event.reason_code IS NOT NULL
                       OR run_event.adapter_sha256 IS NOT NULL
                       OR run_event.provider_sha256 IS NOT NULL
                       OR run_event.model_sha256 IS NOT NULL
                       OR run_event.adapter_config_sha256 IS NOT NULL
                       OR run_event.output_sha256 IS NOT NULL
                       OR run_event.eval_sha256 IS NOT NULL
                       OR run_event.input_tokens<>0 OR run_event.output_tokens<>0
                       OR run_event.cost_usd<>0 OR run_event.latency_ms<>0 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='closed-loop AgentRun start contract is invalid';
                    END IF;
                    safe_text := '{{}}';
                WHEN 'route_selected' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(safe))<>2
                       OR NOT safe ?& ARRAY[
                           'adapter_count','adapter_config_sha256']::text[]
                       OR jsonb_typeof(safe->'adapter_count')<>'number'
                       OR safe->>'adapter_count' !~ '^[1-9][0-9]*$'
                       OR (safe->>'adapter_count')::integer>run_row.max_attempts
                       OR jsonb_typeof(safe->'adapter_config_sha256')<>'array'
                       OR jsonb_array_length(safe->'adapter_config_sha256')<>
                          (safe->>'adapter_count')::integer
                       OR EXISTS (SELECT 1 FROM jsonb_array_elements(
                            safe->'adapter_config_sha256') item
                            WHERE jsonb_typeof(item)<>'string'
                               OR item#>>'{{}}' !~ '^[0-9a-f]{{64}}$')
                       OR run_event.reason_code IS NOT NULL
                       OR run_event.adapter_sha256 IS NOT NULL
                       OR run_event.provider_sha256 IS NOT NULL
                       OR run_event.model_sha256 IS NOT NULL
                       OR run_event.adapter_config_sha256 IS NOT NULL
                       OR run_event.output_sha256 IS NOT NULL
                       OR run_event.eval_sha256 IS NOT NULL
                       OR run_event.input_tokens<>0 OR run_event.output_tokens<>0
                       OR run_event.cost_usd<>0 OR run_event.latency_ms<>0 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='closed-loop AgentRun route contract is invalid';
                    END IF;
                    route_configs := safe->'adapter_config_sha256';
                    safe_text := '{{"adapter_config_sha256":' ||
                        replace(route_configs::text,', ', ',') ||
                        ',"adapter_count":' || (safe->'adapter_count')::text || '}}';
                WHEN 'attempt_started' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(safe))<>1
                       OR NOT safe ? 'attempt'
                       OR jsonb_typeof(safe->'attempt')<>'number'
                       OR safe->>'attempt' !~ '^[1-9][0-9]*$'
                       OR (safe->>'attempt')::integer<>started_count+1
                       OR (safe->>'attempt')::integer>run_row.max_attempts
                       OR route_configs IS NULL
                       OR route_configs->>((safe->>'attempt')::integer-1)
                          IS DISTINCT FROM run_event.adapter_config_sha256
                       OR run_event.reason_code IS NOT NULL
                       OR run_event.adapter_sha256 IS NULL
                       OR run_event.provider_sha256 IS NULL
                       OR run_event.model_sha256 IS NULL
                       OR run_event.adapter_config_sha256 IS NULL
                       OR run_event.output_sha256 IS NOT NULL
                       OR run_event.eval_sha256 IS NOT NULL
                       OR run_event.input_tokens<>0 OR run_event.output_tokens<>0
                       OR run_event.cost_usd<>0 OR run_event.latency_ms<>0 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='closed-loop AgentRun attempt start is invalid';
                    END IF;
                    attempt_no := (safe->>'attempt')::integer;
                    started_count := started_count+1;
                    safe_text := '{{"attempt":' || attempt_no::text || '}}';
                WHEN 'attempt_completed','attempt_denied','attempt_failed' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(safe))<>1
                       OR NOT safe ? 'attempt'
                       OR jsonb_typeof(safe->'attempt')<>'number'
                       OR safe->>'attempt' !~ '^[1-9][0-9]*$'
                       OR (safe->>'attempt')::integer<>started_count
                       OR previous_type<>'attempt_started'
                       OR run_event.adapter_sha256 IS NULL
                       OR run_event.provider_sha256 IS NULL
                       OR run_event.model_sha256 IS NULL
                       OR run_event.adapter_config_sha256 IS NULL
                       OR run_event.adapter_sha256<>previous_adapter
                       OR run_event.provider_sha256<>previous_provider
                       OR run_event.adapter_config_sha256<>previous_config
                       OR (run_event.event_type='attempt_completed' AND
                           (run_event.reason_code IS NOT NULL
                            OR run_event.output_sha256 IS NULL))
                       OR (run_event.event_type IN
                           ('attempt_denied','attempt_failed') AND
                           (run_event.reason_code IS NULL
                            OR run_event.output_sha256 IS NOT NULL))
                       OR run_event.eval_sha256 IS NOT NULL THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='closed-loop AgentRun attempt result is invalid';
                    END IF;
                    attempt_no := (safe->>'attempt')::integer;
                    terminal_attempt_count := terminal_attempt_count+1;
                    aggregate_input_tokens := aggregate_input_tokens+
                        run_event.input_tokens;
                    aggregate_output_tokens := aggregate_output_tokens+
                        run_event.output_tokens;
                    aggregate_latency_ms := aggregate_latency_ms+
                        run_event.latency_ms;
                    aggregate_cost := aggregate_cost+run_event.cost_usd;
                    safe_text := '{{"attempt":' || attempt_no::text || '}}';
                WHEN 'eval_completed' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(safe))<>2
                       OR NOT safe ?& ARRAY['passed','assertion_count']::text[]
                       OR jsonb_typeof(safe->'passed')<>'boolean'
                       OR jsonb_typeof(safe->'assertion_count')<>'number'
                       OR safe->>'assertion_count' !~ '^(0|[1-9][0-9]*)$'
                       OR previous_type<>'attempt_completed'
                       OR run_event.reason_code IS NOT NULL
                       OR run_event.adapter_sha256 IS NULL
                       OR run_event.provider_sha256 IS NULL
                       OR run_event.model_sha256 IS NULL
                       OR run_event.adapter_config_sha256 IS NULL
                       OR run_event.output_sha256 IS NULL
                       OR run_event.eval_sha256 IS NULL
                       OR run_event.adapter_sha256<>previous_adapter
                       OR run_event.provider_sha256<>previous_provider
                       OR run_event.model_sha256<>previous_model
                       OR run_event.adapter_config_sha256<>previous_config
                       OR run_event.output_sha256<>previous_output
                       OR run_event.input_tokens<>0 OR run_event.output_tokens<>0
                       OR run_event.cost_usd<>0 OR run_event.latency_ms<>0 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='closed-loop AgentRun evaluation is invalid';
                    END IF;
                    safe_text := '{{"assertion_count":' ||
                        (safe->'assertion_count')::text || ',"passed":' ||
                        (safe->'passed')::text || '}}';
                WHEN 'run_succeeded' THEN
                    IF (SELECT count(*) FROM jsonb_object_keys(safe))<>1
                       OR NOT safe ? 'attempt_count'
                       OR jsonb_typeof(safe->'attempt_count')<>'number'
                       OR safe->>'attempt_count' !~ '^[1-9][0-9]*$'
                       OR (safe->>'attempt_count')::integer<>started_count
                       OR terminal_attempt_count<>started_count
                       OR previous_type<>'eval_completed'
                       OR run_event.reason_code IS NOT NULL
                       OR run_event.adapter_sha256 IS NOT NULL
                       OR run_event.provider_sha256 IS NOT NULL
                       OR run_event.model_sha256 IS NOT NULL
                       OR run_event.adapter_config_sha256 IS NOT NULL
                       OR run_event.output_sha256 IS NULL
                       OR run_event.eval_sha256 IS NULL
                       OR run_event.output_sha256<>previous_output
                       OR run_event.eval_sha256<>previous_eval
                       OR run_event.input_tokens<>aggregate_input_tokens
                       OR run_event.output_tokens<>aggregate_output_tokens
                       OR run_event.cost_usd<>aggregate_cost
                       OR run_event.latency_ms<>aggregate_latency_ms THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='closed-loop AgentRun success is invalid';
                    END IF;
                    safe_text := '{{"attempt_count":' ||
                        (safe->'attempt_count')::text || '}}';
                WHEN 'run_failed' THEN
                    IF safe<>'{{}}'::jsonb
                       OR run_event.reason_code IS DISTINCT FROM
                          'all_adapters_failed'
                       OR run_event.adapter_sha256 IS NOT NULL
                       OR run_event.provider_sha256 IS NOT NULL
                       OR run_event.model_sha256 IS NOT NULL
                       OR run_event.adapter_config_sha256 IS NOT NULL
                       OR run_event.output_sha256 IS NOT NULL
                       OR run_event.eval_sha256 IS NOT NULL
                       OR run_event.input_tokens<>0 OR run_event.output_tokens<>0
                       OR run_event.latency_ms<>0
                       OR run_event.cost_usd<>aggregate_cost
                       OR terminal_attempt_count<>started_count THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='closed-loop AgentRun failure is invalid';
                    END IF;
                    safe_text := '{{}}';
                WHEN 'run_denied' THEN
                    IF safe<>'{{}}'::jsonb OR run_event.reason_code IS NULL
                       OR run_event.adapter_sha256 IS NOT NULL
                       OR run_event.provider_sha256 IS NOT NULL
                       OR run_event.model_sha256 IS NOT NULL
                       OR run_event.adapter_config_sha256 IS NOT NULL
                       OR run_event.output_sha256 IS NOT NULL
                       OR run_event.eval_sha256 IS NOT NULL
                       OR run_event.input_tokens<>0 OR run_event.output_tokens<>0
                       OR run_event.cost_usd<>0 OR run_event.latency_ms<>0
                       OR (previous_type='attempt_denied' AND
                           run_event.reason_code IS DISTINCT FROM
                           previous_reason) THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='closed-loop AgentRun denial is invalid';
                    END IF;
                    safe_text := '{{}}';
                WHEN 'unknown_outcome' THEN
                    IF safe<>'{{}}'::jsonb OR run_event.reason_code IS NULL
                       OR run_event.reason_code NOT IN
                        ('provider_outcome_not_persisted',
                         'provider_outcome_not_terminal')
                       OR run_event.adapter_sha256 IS NOT NULL
                       OR run_event.provider_sha256 IS NOT NULL
                       OR run_event.model_sha256 IS NOT NULL
                       OR run_event.adapter_config_sha256 IS NOT NULL
                       OR run_event.output_sha256 IS NOT NULL
                       OR run_event.eval_sha256 IS NOT NULL
                       OR run_event.input_tokens<>0 OR run_event.output_tokens<>0
                       OR run_event.cost_usd<>0 OR run_event.latency_ms<>0 THEN
                        RAISE EXCEPTION USING ERRCODE='23514',
                            MESSAGE='closed-loop AgentRun unknown outcome is invalid';
                    END IF;
                    safe_text := '{{}}';
                END CASE;

                SELECT * INTO evidence FROM evidence_records
                WHERE id=run_event.evidence_id;
                SELECT content_bytes INTO blob_bytes FROM evidence_blobs
                WHERE sha256=evidence.blob_sha256;
                IF evidence.id IS NULL OR blob_bytes IS NULL THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='closed-loop AgentRun Evidence is missing';
                END IF;
                evidence_payload := convert_from(blob_bytes,'UTF8')::jsonb;
                IF NOT kjds_cloe_agent_evidence_is_typed(
                    evidence_payload,evidence.metadata_json::jsonb) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='closed-loop AgentRun Evidence is invalid';
                END IF;
                occurred_text := evidence_payload->>'occurred_at';
                IF occurred_text IS NULL
                   OR occurred_text !~
                      '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}([.][0-9]{{6}})?[+]00:00$'
                   OR occurred_text::timestamptz<>run_event.occurred_at THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='closed-loop AgentRun event time is not canonical';
                END IF;
                preimage := '{{"adapter_config_sha256":' ||
                    coalesce(to_jsonb(run_event.adapter_config_sha256)::text,'null') ||
                    ',"adapter_sha256":' ||
                    coalesce(to_jsonb(run_event.adapter_sha256)::text,'null') ||
                    ',"cost_usd":' || to_jsonb(cost_text)::text ||
                    ',"eval_sha256":' ||
                    coalesce(to_jsonb(run_event.eval_sha256)::text,'null') ||
                    ',"event_index":' || run_event.event_index::text ||
                    ',"event_type":' || to_jsonb(run_event.event_type)::text ||
                    ',"input_tokens":' || run_event.input_tokens::text ||
                    ',"latency_ms":' || run_event.latency_ms::text ||
                    ',"model_sha256":' ||
                    coalesce(to_jsonb(run_event.model_sha256)::text,'null') ||
                    ',"occurred_at":' || to_jsonb(occurred_text)::text ||
                    ',"output_sha256":' ||
                    coalesce(to_jsonb(run_event.output_sha256)::text,'null') ||
                    ',"output_tokens":' || run_event.output_tokens::text ||
                    ',"previous_event_sha256":' ||
                    to_jsonb(run_event.previous_event_sha256)::text ||
                    ',"provider_sha256":' ||
                    coalesce(to_jsonb(run_event.provider_sha256)::text,'null') ||
                    ',"reason_code":' ||
                    coalesce(to_jsonb(run_event.reason_code)::text,'null') ||
                    ',"safe_payload":' || safe_text || '}}';
                IF encode(sha256(convert_to(preimage,'UTF8')),'hex')<>
                    run_event.event_sha256 THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='closed-loop AgentRun event hash is invalid';
                END IF;
                expected_event_id := 'agev_' || substr(encode(sha256(convert_to(
                    '{{"event_sha256":' || to_jsonb(run_event.event_sha256)::text ||
                    ',"run_id":' || to_jsonb(run_event.run_id)::text || '}}',
                    'UTF8')),'hex'),1,24);
                expected_content := '{{"adapter_config_sha256":' ||
                    coalesce(to_jsonb(run_event.adapter_config_sha256)::text,'null') ||
                    ',"adapter_sha256":' ||
                    coalesce(to_jsonb(run_event.adapter_sha256)::text,'null') ||
                    ',"contract_id":"kjds-governed-agent-run-evidence-v1"' ||
                    ',"cost_usd":' || to_jsonb(cost_text)::text ||
                    ',"eval_sha256":' ||
                    coalesce(to_jsonb(run_event.eval_sha256)::text,'null') ||
                    ',"event_id":' || to_jsonb(run_event.event_id)::text ||
                    ',"event_index":' || run_event.event_index::text ||
                    ',"event_sha256":' || to_jsonb(run_event.event_sha256)::text ||
                    ',"event_type":' || to_jsonb(run_event.event_type)::text ||
                    ',"external_write_allowed":' || 'false' ||
                    ',"formal_fact":' || 'false' ||
                    ',"input_tokens":' || run_event.input_tokens::text ||
                    ',"latency_ms":' || run_event.latency_ms::text ||
                    ',"model_sha256":' ||
                    coalesce(to_jsonb(run_event.model_sha256)::text,'null') ||
                    ',"occurred_at":' || to_jsonb(occurred_text)::text ||
                    ',"output_sha256":' ||
                    coalesce(to_jsonb(run_event.output_sha256)::text,'null') ||
                    ',"output_tokens":' || run_event.output_tokens::text ||
                    ',"payload_status":"not_retained"' ||
                    ',"previous_event_sha256":' ||
                    to_jsonb(run_event.previous_event_sha256)::text ||
                    ',"proposal_only":' || 'true' ||
                    ',"provider_sha256":' ||
                    coalesce(to_jsonb(run_event.provider_sha256)::text,'null') ||
                    ',"reason_code":' ||
                    coalesce(to_jsonb(run_event.reason_code)::text,'null') ||
                    ',"run_id":' || to_jsonb(run_event.run_id)::text ||
                    ',"safe_payload":' || safe_text || '}}';
                IF evidence.id IS NULL OR blob_bytes IS NULL
                   OR run_event.event_id<>expected_event_id
                   OR evidence.blob_sha256<>run_event.evidence_sha256
                   OR evidence.blob_sha256<>
                      encode(sha256(blob_bytes),'hex')
                   OR convert_from(blob_bytes,'UTF8')<>expected_content
                   OR evidence.filename<>run_event.event_id||'.json'
                   OR evidence.content_type<>'application/json'
                   OR evidence.source<>'governed-agent-run-evidence'
                   OR evidence.source_ref<>
                      'agent-run://'||run_event.run_id||'/'||run_event.event_id
                   OR evidence.grade<>'B'
                   OR evidence.created_by<>'kjds-agent-runtime'
                   OR evidence.effective_at<>run_event.occurred_at
                   OR evidence.effective_until IS NOT NULL
                   OR evidence.recorded_at>p_data_as_of
                   OR evidence.recorded_at<evidence.effective_at
                   OR evidence.effective_at>p_checked_at
                   OR jsonb_typeof(evidence.metadata_json::jsonb)<>'object'
                   OR (SELECT count(*) FROM jsonb_object_keys(
                        evidence.metadata_json::jsonb))<>11
                   OR NOT evidence.metadata_json::jsonb ?& ARRAY[
                        'contract_id','tenant_ref','entity_ref','store_ref',
                        'authority_sha256','run_id','event_id','event_type',
                        'event_sha256','retention_class','legal_hold']::text[]
                   OR EXISTS (
                        SELECT 1 FROM jsonb_each(
                            evidence.metadata_json::jsonb) item
                        WHERE item.value='null'::jsonb)
                   OR evidence.metadata_json->>'contract_id'<>
                      'kjds-governed-agent-run-evidence-v1'
                   OR evidence.metadata_json->>'tenant_ref'<>p_tenant_ref
                   OR evidence.metadata_json->>'entity_ref'<>p_entity_ref
                   OR evidence.metadata_json->>'store_ref'<>p_store_ref
                   OR evidence.metadata_json->>'authority_sha256'<>
                      p_authority_sha256
                   OR evidence.metadata_json->>'run_id'<>run_event.run_id
                   OR evidence.metadata_json->>'event_id'<>run_event.event_id
                   OR evidence.metadata_json->>'event_type'<>run_event.event_type
                   OR evidence.metadata_json->>'event_sha256'<>
                      run_event.event_sha256
                   OR evidence.metadata_json->>'retention_class'<>'security'
                    OR (evidence.metadata_json::jsonb)->'legal_hold'<>'false'::jsonb THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='closed-loop AgentRun Evidence is invalid';
                END IF;
                previous_type := run_event.event_type;
                previous_hash := run_event.event_sha256;
                previous_occurred_at := run_event.occurred_at;
                previous_reason := run_event.reason_code;
                previous_adapter := run_event.adapter_sha256;
                previous_provider := run_event.provider_sha256;
                previous_model := run_event.model_sha256;
                previous_config := run_event.adapter_config_sha256;
                previous_output := run_event.output_sha256;
                previous_eval := run_event.eval_sha256;
                expected_index := expected_index+1;
            END LOOP;
            IF expected_index=1 OR previous_type<>'run_succeeded'
               OR previous_hash<>p_terminal_sha256 THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop AgentRun terminal contract is invalid';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION kjds_cloe_validate_bundle()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE terminal_row agent_runtime_run_events%ROWTYPE;
        BEGIN
            IF jsonb_typeof(NEW.request_json::jsonb)<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(NEW.request_json::jsonb))<>11
                OR NOT NEW.request_json::jsonb ?& ARRAY[
                    'contract_id','contract_version','registry_sha256','scope',
                    'actor_id','data_as_of','agent_run_ref',
                     'experiment_evidence_ref','cost_evidence_ref',
                     'outcome_evidence_ref','idempotency_key']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(NEW.request_json::jsonb) item
                     WHERE (item.key<>'scope'
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key='scope'
                            AND jsonb_typeof(item.value)<>'object'))
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(NEW.request_json::jsonb) item
                    WHERE item.value='null'::jsonb)
               OR jsonb_typeof(NEW.request_json::jsonb->'scope')<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(
                    NEW.request_json::jsonb->'scope'))<>4
                OR NOT (NEW.request_json::jsonb->'scope') ?& ARRAY[
                     'tenant_ref','entity_ref','store_ref',
                     'scope_grant_authority_sha256']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(
                         NEW.request_json::jsonb->'scope') item
                     WHERE jsonb_typeof(item.value)<>'string')
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(
                        NEW.request_json::jsonb->'scope') item
                    WHERE item.value='null'::jsonb)
               OR NOT kjds_cloe_json_is_canonical_utc(
                    NEW.request_json::jsonb->'data_as_of')
               OR jsonb_typeof(NEW.bundle_json::jsonb)<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(NEW.bundle_json::jsonb))<>16
                OR NOT NEW.bundle_json::jsonb ?& ARRAY[
                    'contract_id','contract_version','registry_sha256','scope',
                    'actor_id','data_as_of','agent_run_ref',
                    'experiment_evidence_ref','cost_evidence_ref',
                    'outcome_evidence_ref','idempotency_key',
                     'agent_run_terminal_event_sha256','supporting','effective_at',
                     'review_due_at','causal_claim_allowed']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(NEW.bundle_json::jsonb) item
                     WHERE (item.key IN ('scope','supporting')
                            AND jsonb_typeof(item.value)<>'object')
                        OR (item.key='causal_claim_allowed'
                            AND jsonb_typeof(item.value)<>'boolean')
                        OR (item.key NOT IN (
                              'scope','supporting','causal_claim_allowed')
                            AND jsonb_typeof(item.value)<>'string'))
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(NEW.bundle_json::jsonb) item
                    WHERE item.value='null'::jsonb)
               OR jsonb_typeof(NEW.bundle_json::jsonb->'causal_claim_allowed')<>'boolean'
               OR NEW.bundle_json::jsonb->'causal_claim_allowed'<>'false'::jsonb
               OR jsonb_typeof(NEW.bundle_json::jsonb->'scope')<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(
                    NEW.bundle_json::jsonb->'scope'))<>4
                OR NOT (NEW.bundle_json::jsonb->'scope') ?& ARRAY[
                     'tenant_ref','entity_ref','store_ref',
                     'scope_grant_authority_sha256']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(
                         NEW.bundle_json::jsonb->'scope') item
                     WHERE jsonb_typeof(item.value)<>'string')
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(
                        NEW.bundle_json::jsonb->'scope') item
                    WHERE item.value='null'::jsonb)
               OR NOT kjds_cloe_json_is_canonical_utc(
                    NEW.bundle_json::jsonb->'data_as_of')
               OR NOT kjds_cloe_json_is_canonical_utc(
                    NEW.bundle_json::jsonb->'effective_at')
               OR NOT kjds_cloe_json_is_canonical_utc(
                    NEW.bundle_json::jsonb->'review_due_at')
               OR jsonb_typeof(NEW.bundle_json::jsonb->'supporting')<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(
                    NEW.bundle_json::jsonb->'supporting'))<>3
               OR NOT (NEW.bundle_json::jsonb->'supporting') ?& ARRAY[
                    'experiment','cost','business_outcome']::text[]
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(NEW.bundle_json::jsonb->'supporting') item
                    WHERE jsonb_typeof(item.value)<>'object'
                       OR (SELECT count(*) FROM jsonb_object_keys(item.value))<>4
                        OR NOT item.value ?& ARRAY[
                             'evidence_id','evidence_sha256','claims_sha256',
                             'issuer_actor_id']::text[]
                        OR EXISTS (
                             SELECT 1 FROM jsonb_each(item.value) field
                             WHERE field.value='null'::jsonb
                                OR jsonb_typeof(field.value)<>'string')
               ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop bundle JSON schema is invalid';
            END IF;
            IF NEW.contract_id IS DISTINCT FROM 'kjds-governed-closed-loop-evolution-v1'
               OR NEW.contract_version IS DISTINCT FROM '1.0.0'
               OR NEW.registry_sha256 IS DISTINCT FROM
                     '3b46a8730ab6cf32eed49793c5c4d04889dd412a048c226f2a13de96599b022d'
               OR NEW.bundle_id IS DISTINCT FROM ('clob_' || substr(NEW.bundle_sha256,1,40))
               OR NEW.request_sha256 IS DISTINCT FROM encode(
                     sha256(convert_to(NEW.request_json::jsonb::text,'UTF8')),'hex'
                )
               OR NEW.bundle_sha256 IS DISTINCT FROM encode(
                     sha256(convert_to(NEW.bundle_json::jsonb::text,'UTF8')),'hex'
                )
               OR NEW.idempotency_sha256 IS DISTINCT FROM encode(sha256(convert_to(
                     NEW.request_json::jsonb->>'idempotency_key','UTF8')),'hex')
                OR NEW.actor_id !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$'
               OR NEW.request_json::jsonb->>'idempotency_key'
                     !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$'
               OR NEW.request_json::jsonb->>'contract_id' IS DISTINCT FROM NEW.contract_id
               OR NEW.request_json::jsonb->>'contract_version' IS DISTINCT FROM NEW.contract_version
               OR NEW.request_json::jsonb->>'registry_sha256' IS DISTINCT FROM NEW.registry_sha256
               OR NEW.request_json::jsonb->>'actor_id' IS DISTINCT FROM NEW.actor_id
               OR NEW.request_json::jsonb->>'agent_run_ref' IS DISTINCT FROM NEW.agent_run_ref
               OR NEW.request_json::jsonb->'scope'->>'tenant_ref' IS DISTINCT FROM NEW.tenant_ref
               OR NEW.request_json::jsonb->'scope'->>'entity_ref' IS DISTINCT FROM NEW.entity_ref
               OR NEW.request_json::jsonb->'scope'->>'store_ref' IS DISTINCT FROM NEW.store_ref
               OR NEW.request_json::jsonb->'scope'->>'scope_grant_authority_sha256'
                    IS DISTINCT FROM NEW.scope_grant_authority_sha256
               OR (NEW.bundle_json::jsonb - ARRAY[
                    'agent_run_terminal_event_sha256','supporting','effective_at',
                    'review_due_at','causal_claim_allowed']::text[])
                    IS DISTINCT FROM NEW.request_json::jsonb
               OR (NEW.request_json::jsonb->>'data_as_of')::timestamptz
                    <>NEW.data_as_of
               OR NEW.bundle_json::jsonb->>'agent_run_terminal_event_sha256'
                    IS DISTINCT FROM NEW.agent_run_terminal_event_sha256
               OR (NEW.bundle_json::jsonb->>'effective_at')::timestamptz
                    <>NEW.effective_at
               OR (NEW.bundle_json::jsonb->>'review_due_at')::timestamptz
                    <>NEW.review_due_at
               OR NEW.recorded_at <> NEW.authority_checked_at
               OR NEW.data_as_of > NEW.authority_checked_at
               OR NEW.experiment_window_start >= NEW.experiment_window_end
               OR NEW.cost_period_start >= NEW.cost_period_end
               OR NEW.outcome_interval_start >= NEW.outcome_interval_end
               OR NEW.experiment_window_end > NEW.data_as_of
               OR NEW.cost_period_end > NEW.data_as_of
               OR NEW.outcome_interval_end > NEW.data_as_of THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop bundle contract is invalid';
            END IF;
            PERFORM kjds_cloe_validate_agent_run_contract(
                NEW.agent_run_ref,NEW.tenant_ref,NEW.entity_ref,NEW.store_ref,
                NEW.scope_grant_authority_sha256,NEW.data_as_of,
                NEW.authority_checked_at,NEW.agent_run_terminal_event_sha256
            );
            SELECT * INTO terminal_row
            FROM agent_runtime_run_events
            WHERE run_id=NEW.agent_run_ref
              AND event_sha256=NEW.agent_run_terminal_event_sha256;
            IF terminal_row.event_id IS NULL
               OR terminal_row.event_type <> 'run_succeeded'
               OR terminal_row.tenant_ref <> NEW.tenant_ref
               OR terminal_row.entity_ref <> NEW.entity_ref
               OR terminal_row.store_ref <> NEW.store_ref
               OR terminal_row.authority_sha256 <> NEW.scope_grant_authority_sha256
               OR terminal_row.occurred_at > NEW.data_as_of
               OR EXISTS (
                    SELECT 1 FROM agent_runtime_run_events later
                    WHERE later.run_id=NEW.agent_run_ref
                      AND later.event_index > terminal_row.event_index
               )
               OR NOT EXISTS (
                    SELECT 1 FROM evidence_records ev
                    WHERE ev.id=terminal_row.evidence_id
                      AND ev.blob_sha256=terminal_row.evidence_sha256
                     AND ev.source='governed-agent-run-evidence'
                     AND ev.metadata_json->>'event_sha256'=terminal_row.event_sha256
                     AND ev.effective_at<=NEW.authority_checked_at
                     AND (ev.effective_until IS NULL
                          OR ev.effective_until>NEW.authority_checked_at)
               ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop AgentRun terminal receipt is invalid';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER trg_cloe_bundle_contract BEFORE INSERT ON {BUNDLES} "
        "FOR EACH ROW EXECUTE FUNCTION kjds_cloe_validate_bundle()"
    )

    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_validate_link()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,{quoted_schema} AS $$
        DECLARE ev evidence_records%ROWTYPE;
        DECLARE blob evidence_blobs%ROWTYPE;
        DECLARE payload jsonb;
        DECLARE expected_source text;
        DECLARE expected_contract text;
        DECLARE expected_issuer text;
        DECLARE expected_issuer_contract text;
        DECLARE expected_issuer_hash text;
        DECLARE expected_schema text;
        DECLARE computed_claims_sha text;
        DECLARE computed_link_sha text;
        DECLARE expected_scope_binding text;
        DECLARE expected_claim_keys text[];
        BEGIN
            IF NOT kjds_cloe_validator_principal_is_current() THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            SELECT * INTO ev FROM evidence_records WHERE id=NEW.evidence_id;
            SELECT * INTO blob FROM evidence_blobs
            WHERE sha256=NEW.evidence_sha256;
            payload := convert_from(blob.content_bytes,'UTF8')::jsonb;
            expected_source := CASE NEW.purpose
                WHEN 'experiment' THEN 'closed-loop-experiment-receipt'
                WHEN 'cost' THEN 'closed-loop-cost-receipt'
                WHEN 'business_outcome' THEN 'closed-loop-business-outcome-receipt'
                ELSE NULL END;
            expected_contract := CASE NEW.purpose
                WHEN 'experiment' THEN 'kjds-closed-loop-experiment-receipt-v1'
                WHEN 'cost' THEN 'kjds-closed-loop-cost-receipt-v1'
                WHEN 'business_outcome' THEN 'kjds-closed-loop-business-outcome-receipt-v1'
                ELSE NULL END;
            expected_issuer := CASE NEW.purpose
                WHEN 'experiment' THEN 'kjds-closed-loop-experiment-authority'
                WHEN 'cost' THEN 'kjds-closed-loop-cost-authority'
                WHEN 'business_outcome' THEN 'kjds-closed-loop-business_outcome-authority'
                ELSE NULL END;
            expected_issuer_contract := CASE NEW.purpose
                WHEN 'experiment' THEN 'kjds-closed-loop-experiment-authority-v1'
                WHEN 'cost' THEN 'kjds-closed-loop-cost-authority-v1'
                WHEN 'business_outcome' THEN 'kjds-closed-loop-business_outcome-authority-v1'
                ELSE NULL END;
            expected_issuer_hash := CASE NEW.purpose
                WHEN 'experiment' THEN 'f97fe473225e7ffc13f42e94f164f3cfc3fba028179e1b04864c09203a7576ea'
                WHEN 'cost' THEN '26d5067a2eb437e757258fa60d072074771161025d3354e87d4710a26bb4602f'
                WHEN 'business_outcome' THEN '707982da198bd289c13fbc7151ded979e0125672b7b341e5728079467147db6c'
                ELSE NULL END;
            expected_schema := CASE NEW.purpose
                WHEN 'experiment' THEN 'a24df85fd76d9bebdd112c619ac8d171814323971f0f8aff162458667b0d1213'
                WHEN 'cost' THEN '298f97894b3742fc42e1c65ac1fd78384243e59f7be8c9f24c2e9174e8f6da68'
                WHEN 'business_outcome' THEN '8058a54faabd6781b147b96efeb5bc55172a5413fa444f0f1eea153da786b3c9'
                ELSE NULL END;
            expected_claim_keys := CASE NEW.purpose
              WHEN 'experiment' THEN ARRAY[
                'agent_run_ref','experiment_ref','method','treatment_ref',
                'control_ref','sample_size','minimum_sample_size','metric_id',
                'metric_unit','metric_currency','window_start','window_end',
                'confidence_level_decimal','independent_review_passed',
                'causal_claim_allowed']::text[]
              WHEN 'cost' THEN ARRAY[
                'agent_run_ref','experiment_ref','outcome_ref','cost_ref',
                'amount_minor_units','currency','period_start','period_end',
                'allocation_method']::text[]
              WHEN 'business_outcome' THEN ARRAY[
                'agent_run_ref','outcome_ref','experiment_ref','metric_id',
                'metric_unit','metric_currency','method','sample_size',
                'interval_start','interval_end','value_decimal',
                'confidence_level_decimal','independent_review_passed',
                'causal_claim_allowed']::text[]
              ELSE ARRAY[]::text[] END;
            computed_claims_sha := encode(
                sha256(convert_to((payload->'claims')::text,'UTF8')), 'hex'
            );
            computed_link_sha := encode(sha256(convert_to(concat_ws(chr(31),
                NEW.bundle_id,NEW.purpose,NEW.evidence_id,NEW.evidence_sha256,
                NEW.claims_sha256,NEW.issuer_actor_id,NEW.tenant_ref,
                NEW.entity_ref,NEW.store_ref,NEW.scope_grant_authority_sha256
            ),'UTF8')),'hex');
            expected_scope_binding := encode(sha256(convert_to(
                '{{"entity_ref":' || to_jsonb(NEW.entity_ref)::text ||
                ',"scope_grant_authority_sha256":' ||
                    to_jsonb(NEW.scope_grant_authority_sha256)::text ||
                ',"store_ref":' || to_jsonb(NEW.store_ref)::text ||
                ',"tenant_ref":' || to_jsonb(NEW.tenant_ref)::text || '}}',
                'UTF8')),'hex');
            IF computed_claims_sha<>NEW.claims_sha256 THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF computed_link_sha<>NEW.link_sha256 THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF ev.id IS NULL OR payload IS NULL OR blob.sha256 IS NULL
               OR ev.blob_sha256<>NEW.evidence_sha256
               OR blob.byte_size<>octet_length(blob.content_bytes)
               OR encode(sha256(blob.content_bytes),'hex')<>NEW.evidence_sha256
               OR convert_from(blob.content_bytes,'UTF8')<>
                    kjds_cloe_canonical_json(payload) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF (SELECT count(*) FROM jsonb_object_keys(payload))<>23
               OR (SELECT count(*) FROM jsonb_object_keys(ev.metadata_json::jsonb))<>24 THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF jsonb_typeof(payload)<>'object'
               OR NOT payload ?& ARRAY[
                    'contract_id','purpose','attestation_ref',
                    'authority_receipt_id','issuer_id','issuer_contract_id',
                    'issuer_contract_version','issuer_contract_sha256',
                    'schema_sha256','issuer_actor_id','exact_scope','data_as_of',
                    'effective_at','effective_until','recorded_at','review_due_at',
                    'claims','claims_sha256','attestation_sha256',
                    'attestation_signature_sha256','payload_status',
                     'contains_customer_data','external_write_allowed']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(payload) item
                     WHERE (item.key IN (
                              'contract_id','purpose','attestation_ref',
                              'authority_receipt_id','issuer_id','issuer_contract_id',
                              'issuer_contract_version','issuer_contract_sha256',
                              'schema_sha256','issuer_actor_id','data_as_of',
                              'effective_at','effective_until','recorded_at',
                              'review_due_at','claims_sha256','attestation_sha256',
                              'attestation_signature_sha256','payload_status')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key IN (
                              'contains_customer_data','external_write_allowed')
                            AND jsonb_typeof(item.value)<>'boolean')
                        OR (item.key IN ('exact_scope','claims')
                            AND jsonb_typeof(item.value)<>'object'))
                OR jsonb_typeof(payload->'exact_scope')<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(payload->'exact_scope'))<>4
                OR NOT (payload->'exact_scope') ?& ARRAY[
                     'tenant_ref','entity_ref','store_ref',
                     'scope_grant_authority_sha256']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(payload->'exact_scope') item
                     WHERE jsonb_typeof(item.value)<>'string')
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(payload) item
                    WHERE item.value='null'::jsonb)
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(payload->'exact_scope') item
                    WHERE item.value='null'::jsonb) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF jsonb_typeof(payload->'claims')<>'object'
               OR NOT kjds_cloe_claims_are_canonical(
                    NEW.purpose,payload->'claims')
               OR (SELECT count(*) FROM jsonb_object_keys(payload->'claims'))<>
                    cardinality(expected_claim_keys)
               OR NOT (payload->'claims') ?& expected_claim_keys
                OR (NEW.purpose IN ('experiment','business_outcome')
                   AND payload->'claims'->'causal_claim_allowed'
                       IS DISTINCT FROM 'false'::jsonb)
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(payload->'claims') item
                    WHERE item.value='null'::jsonb
                      AND NOT (
                        (NEW.purpose='experiment'
                         AND item.key IN ('control_ref','metric_currency'))
                        OR (NEW.purpose='business_outcome'
                            AND item.key='metric_currency')
                       )
                ) OR (NEW.purpose='experiment' AND EXISTS (
                     SELECT 1 FROM jsonb_each(payload->'claims') item
                     WHERE (item.key IN (
                              'agent_run_ref','experiment_ref','method',
                              'treatment_ref','metric_id','metric_unit',
                              'window_start','window_end',
                              'confidence_level_decimal')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key IN ('control_ref','metric_currency')
                            AND jsonb_typeof(item.value) NOT IN ('null','string'))
                        OR (item.key IN ('sample_size','minimum_sample_size')
                            AND jsonb_typeof(item.value)<>'number')
                        OR (item.key IN (
                              'independent_review_passed','causal_claim_allowed')
                            AND jsonb_typeof(item.value)<>'boolean')
                )) OR (NEW.purpose='cost' AND EXISTS (
                     SELECT 1 FROM jsonb_each(payload->'claims') item
                     WHERE (item.key IN (
                              'agent_run_ref','experiment_ref','outcome_ref',
                              'cost_ref','currency','period_start','period_end',
                              'allocation_method')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key='amount_minor_units'
                            AND jsonb_typeof(item.value)<>'number')
                )) OR (NEW.purpose='business_outcome' AND EXISTS (
                     SELECT 1 FROM jsonb_each(payload->'claims') item
                     WHERE (item.key IN (
                              'agent_run_ref','outcome_ref','experiment_ref',
                              'metric_id','metric_unit','method','interval_start',
                              'interval_end','value_decimal',
                              'confidence_level_decimal')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key='metric_currency'
                            AND jsonb_typeof(item.value) NOT IN ('null','string'))
                        OR (item.key='sample_size'
                            AND jsonb_typeof(item.value)<>'number')
                        OR (item.key IN (
                              'independent_review_passed','causal_claim_allowed')
                            AND jsonb_typeof(item.value)<>'boolean')
                ))
                THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF jsonb_typeof(ev.metadata_json::jsonb)<>'object'
                OR NOT (ev.metadata_json::jsonb) ?& ARRAY[
                    'contract_id','closed_loop_purpose',
                    'closed_loop_claims_sha256',
                    'closed_loop_attestation_sha256',
                    'closed_loop_attestation_signature_sha256',
                    'closed_loop_attestation_ref',
                    'closed_loop_authority_receipt_id','closed_loop_issuer_id',
                    'closed_loop_issuer_contract_id',
                    'closed_loop_issuer_contract_version',
                    'closed_loop_issuer_contract_sha256',
                    'closed_loop_schema_sha256','closed_loop_issuer_actor_id',
                    'closed_loop_data_as_of','closed_loop_recorded_at',
                    'closed_loop_review_due_at','closed_loop_claims',
                    'closed_loop_scope_binding_sha256','tenant_ref','entity_ref',
                     'store_ref','scope_grant_authority_sha256',
                     'retention_class','legal_hold']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(ev.metadata_json::jsonb) item
                     WHERE (item.key NOT IN ('closed_loop_claims','legal_hold')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key='closed_loop_claims'
                            AND jsonb_typeof(item.value)<>'object')
                        OR (item.key='legal_hold'
                            AND jsonb_typeof(item.value)<>'boolean'))
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(ev.metadata_json::jsonb) item
                    WHERE item.value='null'::jsonb) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM {ISSUANCES} issuance
                JOIN {AUTHORITY_RECEIPTS} receipt
                  ON receipt.authority_receipt_id=issuance.authority_receipt_id
                WHERE issuance.evidence_id=NEW.evidence_id
                  AND receipt.recorded_at=NEW.evidence_recorded_at
                  AND receipt.review_due_at=NEW.evidence_review_due_at
                  AND receipt.effective_at=NEW.evidence_effective_at
                  AND receipt.effective_until=NEW.evidence_effective_until
            ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF NEW.link_id IS DISTINCT FROM ('clol_' || substr(NEW.link_sha256,1,40))
               OR ev.source IS DISTINCT FROM expected_source
               OR NEW.evidence_source IS DISTINCT FROM expected_source
               OR ev.grade IS DISTINCT FROM 'A' OR NEW.evidence_grade IS DISTINCT FROM 'A'
               OR ev.source_ref IS DISTINCT FROM NEW.evidence_source_ref
               OR ev.effective_at IS DISTINCT FROM NEW.evidence_effective_at
               OR ev.effective_until IS DISTINCT FROM NEW.evidence_effective_until
               OR ev.recorded_at IS DISTINCT FROM NEW.evidence_recorded_at
               OR ev.created_by IS DISTINCT FROM NEW.issuer_actor_id
               OR ev.filename IS DISTINCT FROM (NEW.purpose || '-' || NEW.evidence_sha256 || '.json')
               OR ev.content_type IS DISTINCT FROM 'application/json' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF payload->>'contract_id' IS DISTINCT FROM expected_contract
               OR payload->>'purpose' IS DISTINCT FROM NEW.purpose
               OR payload->>'issuer_id' IS DISTINCT FROM expected_issuer
               OR payload->>'issuer_contract_id' IS DISTINCT FROM expected_issuer_contract
               OR payload->>'issuer_contract_version' IS DISTINCT FROM '1.0.0'
               OR payload->>'issuer_contract_sha256' IS DISTINCT FROM expected_issuer_hash
               OR payload->>'schema_sha256' IS DISTINCT FROM expected_schema
               OR payload->>'payload_status' IS DISTINCT FROM 'authority_projection_only'
               OR payload->'contains_customer_data' IS DISTINCT FROM 'false'::jsonb
               OR payload->'external_write_allowed' IS DISTINCT FROM 'false'::jsonb
               OR payload->>'claims_sha256' IS DISTINCT FROM NEW.claims_sha256
               OR payload->>'issuer_actor_id' IS DISTINCT FROM NEW.issuer_actor_id
               OR NOT kjds_cloe_json_is_canonical_utc(payload->'data_as_of')
               OR NOT kjds_cloe_json_is_canonical_utc(payload->'effective_at')
               OR NOT kjds_cloe_json_is_canonical_utc(payload->'effective_until')
               OR NOT kjds_cloe_json_is_canonical_utc(payload->'recorded_at')
               OR NOT kjds_cloe_json_is_canonical_utc(payload->'review_due_at')
               OR (payload->>'effective_at')::timestamptz <> NEW.evidence_effective_at
               OR (payload->>'effective_until')::timestamptz <> NEW.evidence_effective_until
               OR (payload->>'recorded_at')::timestamptz <> NEW.evidence_recorded_at
               OR (payload->>'review_due_at')::timestamptz <> NEW.evidence_review_due_at
               OR payload->'exact_scope'->>'tenant_ref' IS DISTINCT FROM NEW.tenant_ref
               OR payload->'exact_scope'->>'entity_ref' IS DISTINCT FROM NEW.entity_ref
               OR payload->'exact_scope'->>'store_ref' IS DISTINCT FROM NEW.store_ref
               OR payload->'exact_scope'->>'scope_grant_authority_sha256'
                    IS DISTINCT FROM NEW.scope_grant_authority_sha256 THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF payload->>'attestation_sha256'<>encode(sha256(convert_to(
                 kjds_cloe_canonical_json(payload - ARRAY[
                   'attestation_sha256','attestation_signature_sha256',
                   'payload_status','contains_customer_data',
                   'external_write_allowed']::text[]),'UTF8')),'hex') THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF ev.metadata_json->>'closed_loop_purpose' <> NEW.purpose
               OR ev.metadata_json->>'contract_id' <> expected_contract
               OR (ev.metadata_json::jsonb)->'closed_loop_claims'<>payload->'claims'
               OR ev.metadata_json->>'closed_loop_claims_sha256' <> NEW.claims_sha256
               OR ev.metadata_json->>'closed_loop_issuer_actor_id' <> NEW.issuer_actor_id
               OR (ev.metadata_json->>'closed_loop_recorded_at')::timestamptz
                    <> NEW.evidence_recorded_at
               OR (ev.metadata_json->>'closed_loop_review_due_at')::timestamptz
                    <> NEW.evidence_review_due_at
               OR ev.metadata_json->>'tenant_ref' <> NEW.tenant_ref
               OR ev.metadata_json->>'entity_ref' <> NEW.entity_ref
               OR ev.metadata_json->>'store_ref' <> NEW.store_ref
               OR ev.metadata_json->>'scope_grant_authority_sha256'
                    <> NEW.scope_grant_authority_sha256 THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF ev.metadata_json->>'closed_loop_authority_receipt_id'
                    IS DISTINCT FROM payload->>'authority_receipt_id'
               OR ev.metadata_json->>'closed_loop_attestation_ref'
                    IS DISTINCT FROM payload->>'attestation_ref'
               OR ev.metadata_json->>'closed_loop_attestation_sha256'
                    IS DISTINCT FROM payload->>'attestation_sha256'
               OR ev.metadata_json->>'closed_loop_attestation_signature_sha256'
                    IS DISTINCT FROM payload->>'attestation_signature_sha256'
               OR ev.metadata_json->>'closed_loop_issuer_id'
                    IS DISTINCT FROM payload->>'issuer_id'
               OR ev.metadata_json->>'closed_loop_issuer_contract_id'
                    IS DISTINCT FROM payload->>'issuer_contract_id'
               OR ev.metadata_json->>'closed_loop_issuer_contract_version'
                    IS DISTINCT FROM payload->>'issuer_contract_version'
               OR ev.metadata_json->>'closed_loop_issuer_contract_sha256'
                    IS DISTINCT FROM payload->>'issuer_contract_sha256'
               OR ev.metadata_json->>'closed_loop_schema_sha256'
                    IS DISTINCT FROM payload->>'schema_sha256'
               OR ev.metadata_json->>'closed_loop_data_as_of'
                    IS DISTINCT FROM payload->>'data_as_of' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF ev.metadata_json->>'closed_loop_scope_binding_sha256'
                    IS DISTINCT FROM expected_scope_binding THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF NEW.evidence_source_ref IS DISTINCT FROM concat(
                expected_source,'://',expected_scope_binding,'/',
                NEW.claims_sha256,'/',NEW.evidence_sha256
            ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF ev.metadata_json->>'retention_class' <> 'compliance' THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF (ev.metadata_json::jsonb)->'legal_hold' <> 'false'::jsonb THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM {ISSUANCES} issuance
                JOIN {AUTHORITY_RECEIPTS} receipt
                  ON receipt.authority_receipt_id=issuance.authority_receipt_id
                WHERE issuance.evidence_id=NEW.evidence_id
                  AND issuance.authority_receipt_id=
                      payload->>'authority_receipt_id'
                  AND issuance.content_sha256=NEW.evidence_sha256
                  AND issuance.source=NEW.evidence_source
                  AND issuance.source_ref=NEW.evidence_source_ref
                  AND issuance.attestation_sha256=payload->>'attestation_sha256'
                  AND issuance.attestation_signature_sha256=
                      payload->>'attestation_signature_sha256'
                  AND receipt.purpose=NEW.purpose
                  AND receipt.evidence_id=NEW.evidence_id
                  AND receipt.content_sha256=NEW.evidence_sha256
                  AND receipt.metadata_sha256=encode(sha256(convert_to(
                      ev.metadata_json::jsonb::text,'UTF8')),'hex')
                  AND receipt.source=NEW.evidence_source
                  AND receipt.source_ref=NEW.evidence_source_ref
                  AND receipt.attestation_sha256=
                      payload->>'attestation_sha256'
                  AND receipt.attestation_signature_sha256=
                      payload->>'attestation_signature_sha256'
                  AND receipt.issuer_id=payload->>'issuer_id'
                  AND receipt.issuer_id=expected_issuer
                  AND receipt.issuer_contract_id=
                      payload->>'issuer_contract_id'
                  AND receipt.issuer_contract_id=expected_issuer_contract
                  AND receipt.issuer_contract_version=
                      payload->>'issuer_contract_version'
                  AND receipt.issuer_contract_version='1.0.0'
                  AND receipt.issuer_contract_sha256=
                      payload->>'issuer_contract_sha256'
                  AND receipt.issuer_contract_sha256=expected_issuer_hash
                  AND receipt.schema_sha256=payload->>'schema_sha256'
                  AND receipt.schema_sha256=expected_schema
                  AND receipt.data_as_of=(payload->>'data_as_of')::timestamptz
                  AND receipt.issuer_actor_id=NEW.issuer_actor_id
                  AND receipt.tenant_ref=NEW.tenant_ref
                  AND receipt.entity_ref=NEW.entity_ref
                  AND receipt.store_ref=NEW.store_ref
                  AND receipt.scope_grant_authority_sha256=
                      NEW.scope_grant_authority_sha256
                  AND receipt.recorded_at=NEW.evidence_recorded_at
                  AND receipt.review_due_at=NEW.evidence_review_due_at
                  AND receipt.effective_at=NEW.evidence_effective_at
                  AND receipt.effective_until=NEW.evidence_effective_until
            ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence link binding is invalid';
            END IF;
            RETURN NEW;
        EXCEPTION WHEN others THEN
            IF SQLSTATE='23514' THEN RAISE; END IF;
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='closed-loop Evidence link binding is invalid';
        END;
        $$
        """
    )
    op.execute(
        f"ALTER FUNCTION {quoted_schema}.kjds_cloe_validate_link() "
        f"OWNER TO {ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {quoted_schema}.kjds_cloe_validate_link() "
        "FROM PUBLIC"
    )
    op.execute(
        f"CREATE TRIGGER trg_cloe_link_contract BEFORE INSERT ON {LINKS} "
        "FOR EACH ROW EXECUTE FUNCTION kjds_cloe_validate_link()"
    )
    op.execute(
        f"CREATE CONSTRAINT TRIGGER trg_cloe_link_contract_deferred "
        f"AFTER INSERT ON {LINKS} DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION kjds_cloe_validate_link()"
    )

    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_validate_event()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,{quoted_schema} AS $$
        DECLARE previous_row {EVENTS}%ROWTYPE;
        DECLARE ev evidence_records%ROWTYPE;
        DECLARE review_ev evidence_records%ROWTYPE;
        DECLARE review_blob evidence_blobs%ROWTYPE;
        DECLARE payload jsonb;
        DECLARE review_payload jsonb;
        DECLARE computed_sha text;
        DECLARE review_claims_sha text;
        DECLARE review_scope_binding text;
        BEGIN
            IF NOT kjds_cloe_validator_principal_is_current() THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop event binding is invalid';
            END IF;
            SELECT * INTO previous_row FROM {EVENTS}
            WHERE bundle_id=NEW.bundle_id AND event_index<NEW.event_index
            ORDER BY event_index DESC LIMIT 1;
            SELECT * INTO ev FROM evidence_records WHERE id=NEW.evidence_id;
            SELECT convert_from(content_bytes,'UTF8')::jsonb INTO payload
            FROM evidence_blobs WHERE sha256=NEW.evidence_sha256;
            IF NEW.review_evidence_id IS NOT NULL THEN
                SELECT * INTO review_ev FROM evidence_records
                WHERE id=NEW.review_evidence_id;
                SELECT * INTO review_blob FROM evidence_blobs
                WHERE sha256=NEW.review_evidence_sha256;
                review_payload := convert_from(review_blob.content_bytes,'UTF8')::jsonb;
                review_claims_sha := encode(sha256(convert_to(
                    (review_payload->'claims')::text,'UTF8')),'hex');
                review_scope_binding := encode(sha256(convert_to(
                    '{{"entity_ref":' || to_jsonb(NEW.entity_ref)::text ||
                    ',"scope_grant_authority_sha256":' ||
                        to_jsonb(NEW.scope_grant_authority_sha256)::text ||
                    ',"store_ref":' || to_jsonb(NEW.store_ref)::text ||
                    ',"tenant_ref":' || to_jsonb(NEW.tenant_ref)::text || '}}',
                    'UTF8')),'hex');
            END IF;
            IF jsonb_typeof(NEW.request_json::jsonb)<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(NEW.request_json::jsonb))<>8
                OR NOT NEW.request_json::jsonb ?& ARRAY[
                     'bundle_id','event_type','reason_code','actor_id',
                     'review_evidence_ref','replacement_bundle_id',
                     'idempotency_key','scope']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(NEW.request_json::jsonb) item
                     WHERE (item.key IN (
                              'bundle_id','event_type','reason_code','actor_id',
                              'idempotency_key')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key IN (
                              'review_evidence_ref','replacement_bundle_id')
                            AND jsonb_typeof(item.value) NOT IN ('null','string'))
                        OR (item.key='scope'
                            AND jsonb_typeof(item.value)<>'object'))
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(NEW.request_json::jsonb) item
                    WHERE item.value='null'::jsonb
                      AND item.key NOT IN
                          ('review_evidence_ref','replacement_bundle_id'))
               OR jsonb_typeof(NEW.request_json::jsonb->'reason_code')<>'string'
               OR NOT (jsonb_typeof(
                    NEW.request_json::jsonb->'review_evidence_ref')
                    IN ('null','string'))
               OR NOT (jsonb_typeof(
                    NEW.request_json::jsonb->'replacement_bundle_id')
                    IN ('null','string'))
               OR jsonb_typeof(NEW.request_json::jsonb->'scope')<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(
                    NEW.request_json::jsonb->'scope'))<>4
                OR NOT (NEW.request_json::jsonb->'scope') ?& ARRAY[
                     'tenant_ref','entity_ref','store_ref',
                     'scope_grant_authority_sha256']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(
                         NEW.request_json::jsonb->'scope') item
                     WHERE jsonb_typeof(item.value)<>'string')
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(
                        NEW.request_json::jsonb->'scope') item
                    WHERE item.value='null'::jsonb)
               OR jsonb_typeof(payload)<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(payload))<>17
                OR NOT payload ?& ARRAY[
                    'contract_id','bundle_id','event_index','event_type',
                    'reason_code','actor_id','request_sha256',
                    'previous_event_sha256','occurred_at','event_sha256',
                    'review_evidence_ref','replacement_bundle_id','payload_status',
                     'candidate_created','transition_allowed','promotion_allowed',
                     'external_write_allowed']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(payload) item
                     WHERE (item.key IN (
                              'contract_id','bundle_id','event_type','reason_code',
                              'actor_id','request_sha256','previous_event_sha256',
                              'occurred_at','event_sha256','payload_status')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key='event_index'
                            AND jsonb_typeof(item.value)<>'number')
                        OR (item.key IN (
                              'review_evidence_ref','replacement_bundle_id')
                            AND jsonb_typeof(item.value) NOT IN ('null','string'))
                        OR (item.key IN (
                              'candidate_created','transition_allowed',
                              'promotion_allowed','external_write_allowed')
                            AND jsonb_typeof(item.value)<>'boolean'))
               OR NOT kjds_cloe_json_is_canonical_utc(payload->'occurred_at')
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(payload) item
                    WHERE item.value='null'::jsonb
                      AND item.key NOT IN
                          ('review_evidence_ref','replacement_bundle_id'))
               OR jsonb_typeof(payload->'reason_code')<>'string'
               OR NOT (jsonb_typeof(payload->'review_evidence_ref')
                       IN ('null','string'))
               OR NOT (jsonb_typeof(payload->'replacement_bundle_id')
                       IN ('null','string'))
               OR ev.id IS NULL
               OR jsonb_typeof(ev.metadata_json::jsonb)<>'object'
               OR (SELECT count(*) FROM jsonb_object_keys(ev.metadata_json::jsonb))<>13
                OR NOT (ev.metadata_json::jsonb) ?& ARRAY[
                    'contract_id','bundle_id','event_id','event_type',
                    'event_sha256','review_evidence_ref','replacement_bundle_id',
                    'tenant_ref','entity_ref','store_ref',
                     'scope_grant_authority_sha256','retention_class',
                     'legal_hold']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(ev.metadata_json::jsonb) item
                     WHERE (item.key IN (
                              'contract_id','bundle_id','event_id','event_type',
                              'event_sha256','tenant_ref','entity_ref','store_ref',
                              'scope_grant_authority_sha256','retention_class')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key IN (
                              'review_evidence_ref','replacement_bundle_id')
                            AND jsonb_typeof(item.value) NOT IN ('null','string'))
                        OR (item.key='legal_hold'
                            AND jsonb_typeof(item.value)<>'boolean'))
               OR EXISTS (
                    SELECT 1 FROM jsonb_each(ev.metadata_json::jsonb) item
                    WHERE item.value='null'::jsonb
                      AND item.key NOT IN
                          ('review_evidence_ref','replacement_bundle_id'))
               OR NOT (jsonb_typeof(
                    ev.metadata_json::jsonb->'review_evidence_ref')
                    IN ('null','string'))
               OR NOT (jsonb_typeof(
                    ev.metadata_json::jsonb->'replacement_bundle_id')
                    IN ('null','string')) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop event JSON schema is invalid';
            END IF;
            computed_sha := encode(sha256(convert_to(concat_ws(chr(31),
                NEW.bundle_id,NEW.event_index::text,NEW.event_type,NEW.reason_code,
                NEW.actor_id,NEW.request_sha256,NEW.previous_event_sha256,
                payload->>'occurred_at'
            ),'UTF8')),'hex');
            IF previous_row.event_id IS NULL THEN
                IF NEW.event_index<>1 OR NEW.event_type<>'bundle_recorded'
                   OR NEW.previous_event_sha256<>repeat('0',64) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='invalid closed-loop initial event';
                END IF;
            ELSE
                IF NEW.event_index<>previous_row.event_index+1
                   OR NEW.previous_event_sha256<>previous_row.event_sha256
                   OR NEW.occurred_at<previous_row.occurred_at
                   OR NOT (
                    previous_row.event_type IN ('bundle_recorded','review_requested')
                    AND NEW.event_type IN
                        ('review_requested','invalidated','revoked','superseded')
                   ) THEN
                    RAISE EXCEPTION USING ERRCODE='23514',
                        MESSAGE='invalid closed-loop event transition';
                END IF;
            END IF;
            IF ev.id IS NULL OR payload IS NULL
               OR NEW.event_id <> ('cloev_' || substr(NEW.event_sha256,1,40))
               OR NEW.request_sha256<>encode(
                    sha256(convert_to(NEW.request_json::jsonb::text,'UTF8')),'hex')
               OR NEW.idempotency_sha256<>encode(sha256(convert_to(
                    NEW.request_json::jsonb->>'idempotency_key','UTF8')),'hex')
                OR NEW.actor_id !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
                OR NEW.reason_code !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
               OR NEW.request_json::jsonb->>'idempotency_key'
                     !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{{0,159}}$'
               OR NEW.request_json::jsonb->>'bundle_id' IS DISTINCT FROM NEW.bundle_id
               OR NEW.request_json::jsonb->>'event_type' IS DISTINCT FROM NEW.event_type
               OR NEW.request_json::jsonb->>'reason_code' IS DISTINCT FROM NEW.reason_code
               OR NEW.request_json::jsonb->>'actor_id' IS DISTINCT FROM NEW.actor_id
               OR NEW.request_json::jsonb->'scope'->>'tenant_ref' IS DISTINCT FROM NEW.tenant_ref
               OR NEW.request_json::jsonb->'scope'->>'entity_ref' IS DISTINCT FROM NEW.entity_ref
               OR NEW.request_json::jsonb->'scope'->>'store_ref' IS DISTINCT FROM NEW.store_ref
                OR NEW.request_json::jsonb->'scope'->>'scope_grant_authority_sha256'
                     IS DISTINCT FROM NEW.scope_grant_authority_sha256
               OR NEW.request_json::jsonb->>'review_evidence_ref'
                    IS DISTINCT FROM NEW.review_evidence_id
               OR NEW.request_json::jsonb->>'replacement_bundle_id'
                    IS DISTINCT FROM NEW.replacement_bundle_id
               OR ev.source<>'governed-closed-loop-evolution'
               OR ev.grade<>'D'
               OR NEW.evidence_source<>ev.source
               OR NEW.evidence_grade<>ev.grade
               OR NEW.evidence_source_ref<>ev.source_ref
               OR ev.source_ref<>(
                    'closed-loop-evolution://' || NEW.bundle_id || '/' || NEW.event_id)
               OR ev.metadata_json->>'bundle_id' IS DISTINCT FROM NEW.bundle_id
               OR ev.metadata_json->>'event_id' IS DISTINCT FROM NEW.event_id
               OR ev.metadata_json->>'event_sha256' IS DISTINCT FROM NEW.event_sha256
               OR ev.metadata_json->>'contract_id' IS DISTINCT FROM
                     'kjds-governed-closed-loop-evolution-event-v1'
               OR ev.metadata_json->>'event_type' IS DISTINCT FROM NEW.event_type
               OR ev.metadata_json->>'review_evidence_ref'
                    IS DISTINCT FROM NEW.review_evidence_id
               OR ev.metadata_json->>'replacement_bundle_id'
                    IS DISTINCT FROM NEW.replacement_bundle_id
               OR ev.metadata_json->>'retention_class' IS DISTINCT FROM 'compliance'
               OR (ev.metadata_json::jsonb)->'legal_hold' IS DISTINCT FROM 'false'::jsonb
               OR ev.metadata_json->>'tenant_ref' IS DISTINCT FROM NEW.tenant_ref
               OR ev.metadata_json->>'entity_ref' IS DISTINCT FROM NEW.entity_ref
               OR ev.metadata_json->>'store_ref' IS DISTINCT FROM NEW.store_ref
               OR ev.metadata_json->>'scope_grant_authority_sha256' IS DISTINCT FROM
                     NEW.scope_grant_authority_sha256
               OR ev.effective_at<>NEW.occurred_at
               OR ev.recorded_at<>NEW.recorded_at
               OR NEW.occurred_at>NEW.recorded_at
               OR payload->>'contract_id' IS DISTINCT FROM 'kjds-governed-closed-loop-evolution-event-v1'
               OR payload->>'bundle_id' IS DISTINCT FROM NEW.bundle_id
               OR (payload->>'event_index')::integer<>NEW.event_index
               OR payload->>'event_type' IS DISTINCT FROM NEW.event_type
               OR payload->>'reason_code' IS DISTINCT FROM NEW.reason_code
               OR payload->>'actor_id' IS DISTINCT FROM NEW.actor_id
               OR payload->>'request_sha256' IS DISTINCT FROM NEW.request_sha256
               OR payload->>'previous_event_sha256' IS DISTINCT FROM NEW.previous_event_sha256
               OR (payload->>'occurred_at')::timestamptz<>NEW.occurred_at
               OR payload->>'event_sha256' IS DISTINCT FROM NEW.event_sha256
               OR payload->>'review_evidence_ref'
                    IS DISTINCT FROM NEW.review_evidence_id
               OR payload->>'replacement_bundle_id'
                    IS DISTINCT FROM NEW.replacement_bundle_id
               OR payload->>'payload_status' IS DISTINCT FROM 'hash_and_code_only'
               OR payload->'candidate_created' IS DISTINCT FROM 'false'::jsonb
               OR payload->'transition_allowed' IS DISTINCT FROM 'false'::jsonb
               OR payload->'promotion_allowed' IS DISTINCT FROM 'false'::jsonb
               OR payload->'external_write_allowed' IS DISTINCT FROM 'false'::jsonb
               OR computed_sha<>NEW.event_sha256 THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop event Evidence is invalid';
            END IF;
            IF NEW.event_type<>'bundle_recorded' AND (
               review_ev.id IS NULL OR review_payload IS NULL
               OR jsonb_typeof(review_payload)<>'object'
                   OR (SELECT count(*) FROM jsonb_object_keys(review_payload))<>23
                OR NOT review_payload ?& ARRAY[
                    'contract_id','purpose','attestation_ref',
                    'authority_receipt_id','issuer_id','issuer_contract_id',
                    'issuer_contract_version','issuer_contract_sha256',
                    'schema_sha256','issuer_actor_id','exact_scope','data_as_of',
                    'effective_at','effective_until','recorded_at','review_due_at',
                    'claims','claims_sha256','attestation_sha256',
                    'attestation_signature_sha256','payload_status',
                     'contains_customer_data','external_write_allowed']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(review_payload) item
                     WHERE (item.key IN (
                              'contract_id','purpose','attestation_ref',
                              'authority_receipt_id','issuer_id','issuer_contract_id',
                              'issuer_contract_version','issuer_contract_sha256',
                              'schema_sha256','issuer_actor_id','data_as_of',
                              'effective_at','effective_until','recorded_at',
                              'review_due_at','claims_sha256','attestation_sha256',
                              'attestation_signature_sha256','payload_status')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key IN (
                              'contains_customer_data','external_write_allowed')
                            AND jsonb_typeof(item.value)<>'boolean')
                        OR (item.key IN ('exact_scope','claims')
                            AND jsonb_typeof(item.value)<>'object'))
                OR jsonb_typeof(review_payload->'exact_scope')<>'object'
                   OR (SELECT count(*) FROM jsonb_object_keys(
                        review_payload->'exact_scope'))<>4
                OR NOT (review_payload->'exact_scope') ?& ARRAY[
                     'tenant_ref','entity_ref','store_ref',
                     'scope_grant_authority_sha256']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(review_payload->'exact_scope') item
                     WHERE jsonb_typeof(item.value)<>'string')
               OR jsonb_typeof(review_payload->'claims')<>'object'
               OR NOT kjds_cloe_claims_are_canonical(
                    'review_event',review_payload->'claims')
                   OR (SELECT count(*) FROM jsonb_object_keys(
                        review_payload->'claims'))<>5
                OR NOT (review_payload->'claims') ?& ARRAY[
                     'bundle_id','event_type','reason_code','replacement_bundle_id',
                     'requested_by_actor_id']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(review_payload->'claims') item
                     WHERE (item.key IN (
                              'bundle_id','event_type','reason_code',
                              'requested_by_actor_id')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key='replacement_bundle_id'
                            AND jsonb_typeof(item.value) NOT IN ('null','string')))
               OR jsonb_typeof(review_ev.metadata_json::jsonb)<>'object'
                   OR (SELECT count(*) FROM jsonb_object_keys(
                         review_ev.metadata_json::jsonb))<>24
                OR NOT (review_ev.metadata_json::jsonb) ?& ARRAY[
                    'contract_id','closed_loop_purpose',
                    'closed_loop_claims_sha256',
                    'closed_loop_attestation_sha256',
                    'closed_loop_attestation_signature_sha256',
                    'closed_loop_attestation_ref',
                    'closed_loop_authority_receipt_id','closed_loop_issuer_id',
                    'closed_loop_issuer_contract_id',
                    'closed_loop_issuer_contract_version',
                    'closed_loop_issuer_contract_sha256',
                    'closed_loop_schema_sha256','closed_loop_issuer_actor_id',
                    'closed_loop_data_as_of','closed_loop_recorded_at',
                    'closed_loop_review_due_at','closed_loop_claims',
                    'closed_loop_scope_binding_sha256','tenant_ref','entity_ref',
                     'store_ref','scope_grant_authority_sha256',
                     'retention_class','legal_hold']::text[]
                OR EXISTS (
                     SELECT 1 FROM jsonb_each(review_ev.metadata_json::jsonb) item
                     WHERE (item.key NOT IN ('closed_loop_claims','legal_hold')
                            AND jsonb_typeof(item.value)<>'string')
                        OR (item.key='closed_loop_claims'
                            AND jsonb_typeof(item.value)<>'object')
                        OR (item.key='legal_hold'
                            AND jsonb_typeof(item.value)<>'boolean'))
               OR NEW.review_evidence_source IS DISTINCT FROM 'closed-loop-review-authority-receipt'
               OR review_blob.sha256 IS NULL
               OR review_blob.byte_size<>octet_length(review_blob.content_bytes)
               OR encode(sha256(review_blob.content_bytes),'hex')<>
                    NEW.review_evidence_sha256
               OR convert_from(review_blob.content_bytes,'UTF8')<>
                    kjds_cloe_canonical_json(review_payload)
               OR review_ev.source IS DISTINCT FROM NEW.review_evidence_source
               OR review_ev.source_ref IS DISTINCT FROM NEW.review_evidence_source_ref
               OR review_ev.blob_sha256 IS DISTINCT FROM NEW.review_evidence_sha256
               OR review_ev.grade IS DISTINCT FROM 'A'
               OR NEW.review_evidence_grade IS DISTINCT FROM 'A'
               OR review_ev.effective_at IS DISTINCT FROM NEW.review_evidence_effective_at
               OR review_ev.effective_until IS DISTINCT FROM
                    (review_payload->>'effective_until')::timestamptz
               OR review_ev.recorded_at IS DISTINCT FROM
                    (review_payload->>'recorded_at')::timestamptz
               OR review_ev.created_by IS DISTINCT FROM review_payload->>'issuer_actor_id'
               OR review_ev.filename IS DISTINCT FROM (
                    'review_event-' || NEW.review_evidence_sha256 || '.json')
               OR review_ev.content_type IS DISTINCT FROM 'application/json'
               OR review_payload->>'contract_id' IS DISTINCT FROM
                     'kjds-closed-loop-review-authority-receipt-v1'
               OR review_payload->>'purpose' IS DISTINCT FROM 'review_event'
               OR review_payload->>'issuer_id' IS DISTINCT FROM 'kjds-closed-loop-review-authority'
               OR review_payload->>'issuer_contract_id' IS DISTINCT FROM
                     'kjds-closed-loop-review-authority-v1'
               OR review_payload->>'issuer_contract_version' IS DISTINCT FROM '1.0.0'
               OR review_payload->>'issuer_contract_sha256' IS DISTINCT FROM
                     'd85428cb588631ff0afd0592b08d5c4bd372aed4abbd543c0fbb07f4c5a773e7'
               OR review_payload->>'schema_sha256' IS DISTINCT FROM
                     'c79a43be77115a956ff2d996261e4f1223ab0468ae08bcb17c3656be1c37f111'
               OR review_payload->>'attestation_sha256' IS DISTINCT FROM
                     NEW.review_attestation_sha256
               OR NOT kjds_cloe_json_is_canonical_utc(
                    review_payload->'data_as_of')
               OR NOT kjds_cloe_json_is_canonical_utc(
                    review_payload->'effective_at')
               OR NOT kjds_cloe_json_is_canonical_utc(
                    review_payload->'effective_until')
               OR NOT kjds_cloe_json_is_canonical_utc(
                    review_payload->'recorded_at')
               OR NOT kjds_cloe_json_is_canonical_utc(
                    review_payload->'review_due_at')
               OR review_payload->>'attestation_sha256' IS DISTINCT FROM encode(sha256(convert_to(
                    kjds_cloe_canonical_json(review_payload - ARRAY[
                      'attestation_sha256','attestation_signature_sha256',
                      'payload_status','contains_customer_data',
                      'external_write_allowed']::text[]),'UTF8')),'hex')
               OR review_payload->>'claims_sha256' IS DISTINCT FROM review_claims_sha
               OR review_payload->>'payload_status' IS DISTINCT FROM 'authority_projection_only'
               OR review_payload->'contains_customer_data' IS DISTINCT FROM 'false'::jsonb
               OR review_payload->'external_write_allowed' IS DISTINCT FROM 'false'::jsonb
               OR (review_ev.metadata_json::jsonb)->'closed_loop_claims' IS DISTINCT FROM
                     review_payload->'claims'
               OR review_ev.metadata_json->>'contract_id' IS DISTINCT FROM
                    review_payload->>'contract_id'
               OR review_ev.metadata_json->>'closed_loop_purpose' IS DISTINCT FROM 'review_event'
               OR review_ev.metadata_json->>'closed_loop_claims_sha256' IS DISTINCT FROM
                    review_claims_sha
               OR review_ev.metadata_json->>'closed_loop_attestation_sha256' IS DISTINCT FROM
                    review_payload->>'attestation_sha256'
               OR review_ev.metadata_json->>
                    'closed_loop_attestation_signature_sha256' IS DISTINCT FROM
                    review_payload->>'attestation_signature_sha256'
               OR review_ev.metadata_json->>'closed_loop_attestation_ref' IS DISTINCT FROM
                    review_payload->>'attestation_ref'
               OR review_ev.metadata_json->>'closed_loop_authority_receipt_id' IS DISTINCT FROM
                    review_payload->>'authority_receipt_id'
               OR review_ev.metadata_json->>'closed_loop_issuer_id' IS DISTINCT FROM
                    review_payload->>'issuer_id'
               OR review_ev.metadata_json->>'closed_loop_issuer_contract_id' IS DISTINCT FROM
                    review_payload->>'issuer_contract_id'
               OR review_ev.metadata_json->>'closed_loop_issuer_contract_version' IS DISTINCT FROM
                    review_payload->>'issuer_contract_version'
               OR review_ev.metadata_json->>'closed_loop_issuer_contract_sha256' IS DISTINCT FROM
                    review_payload->>'issuer_contract_sha256'
               OR review_ev.metadata_json->>'closed_loop_schema_sha256' IS DISTINCT FROM
                    review_payload->>'schema_sha256'
               OR review_ev.metadata_json->>'closed_loop_issuer_actor_id' IS DISTINCT FROM
                    review_payload->>'issuer_actor_id'
               OR review_ev.metadata_json->>'closed_loop_data_as_of' IS DISTINCT FROM
                    review_payload->>'data_as_of'
               OR review_ev.metadata_json->>'closed_loop_recorded_at' IS DISTINCT FROM
                    review_payload->>'recorded_at'
               OR review_ev.metadata_json->>'closed_loop_review_due_at' IS DISTINCT FROM
                    review_payload->>'review_due_at'
               OR review_ev.metadata_json->>'closed_loop_scope_binding_sha256' IS DISTINCT FROM
                    review_scope_binding
               OR review_ev.metadata_json->>'tenant_ref' IS DISTINCT FROM NEW.tenant_ref
               OR review_ev.metadata_json->>'entity_ref' IS DISTINCT FROM NEW.entity_ref
               OR review_ev.metadata_json->>'store_ref' IS DISTINCT FROM NEW.store_ref
               OR review_ev.metadata_json->>'scope_grant_authority_sha256' IS DISTINCT FROM
                    NEW.scope_grant_authority_sha256
               OR review_ev.metadata_json->>'retention_class' IS DISTINCT FROM 'compliance'
               OR (review_ev.metadata_json::jsonb)->'legal_hold' IS DISTINCT FROM 'false'::jsonb
               OR review_payload->'claims'->>'bundle_id' IS DISTINCT FROM NEW.bundle_id
               OR review_payload->'claims'->>'event_type' IS DISTINCT FROM NEW.event_type
               OR review_payload->'claims'->>'reason_code' IS DISTINCT FROM NEW.reason_code
               OR review_payload->'claims'->>'requested_by_actor_id' IS DISTINCT FROM NEW.actor_id
               OR review_payload->'claims'->>'replacement_bundle_id'
                    IS DISTINCT FROM NEW.replacement_bundle_id
               OR review_payload->'exact_scope'->>'tenant_ref' IS DISTINCT FROM NEW.tenant_ref
               OR review_payload->'exact_scope'->>'entity_ref' IS DISTINCT FROM NEW.entity_ref
               OR review_payload->'exact_scope'->>'store_ref' IS DISTINCT FROM NEW.store_ref
               OR review_payload->'exact_scope'->>'scope_grant_authority_sha256'
                    IS DISTINCT FROM NEW.scope_grant_authority_sha256
               OR NEW.review_evidence_source_ref IS DISTINCT FROM (
                    'closed-loop-review-authority-receipt://' ||
                    review_scope_binding || '/' || review_claims_sha || '/' ||
                    NEW.review_evidence_sha256)
               OR (review_payload->>'effective_at')::timestamptz>
                    NEW.occurred_at
                OR (review_payload->>'recorded_at')::timestamptz>
                     NEW.occurred_at
                 OR (review_payload->>'data_as_of')::timestamptz IS DISTINCT FROM
                      NEW.occurred_at
                OR NEW.occurred_at>=(review_payload->>'review_due_at')::timestamptz
               OR (review_payload->>'review_due_at')::timestamptz>
                    (review_payload->>'effective_until')::timestamptz
               OR NOT EXISTS (
                    SELECT 1 FROM {ISSUANCES} issuance
                    JOIN {AUTHORITY_RECEIPTS} receipt
                      ON receipt.authority_receipt_id=issuance.authority_receipt_id
                    WHERE issuance.evidence_id=NEW.review_evidence_id
                      AND issuance.authority_receipt_id=
                          review_payload->>'authority_receipt_id'
                      AND issuance.content_sha256=NEW.review_evidence_sha256
                      AND issuance.source=NEW.review_evidence_source
                      AND issuance.source_ref=NEW.review_evidence_source_ref
                      AND issuance.attestation_sha256=
                          review_payload->>'attestation_sha256'
                      AND issuance.attestation_signature_sha256=
                          review_payload->>'attestation_signature_sha256'
                      AND receipt.purpose='review_event'
                      AND receipt.evidence_id=NEW.review_evidence_id
                      AND receipt.content_sha256=NEW.review_evidence_sha256
                      AND receipt.metadata_sha256=encode(sha256(convert_to(
                          review_ev.metadata_json::jsonb::text,'UTF8')),'hex')
                      AND receipt.source=NEW.review_evidence_source
                      AND receipt.source_ref=NEW.review_evidence_source_ref
                      AND receipt.attestation_sha256=
                          review_payload->>'attestation_sha256'
                      AND receipt.attestation_signature_sha256=
                          review_payload->>'attestation_signature_sha256'
                      AND receipt.issuer_id=review_payload->>'issuer_id'
                      AND receipt.issuer_id='kjds-closed-loop-review-authority'
                      AND receipt.issuer_contract_id=
                          review_payload->>'issuer_contract_id'
                      AND receipt.issuer_contract_id=
                          'kjds-closed-loop-review-authority-v1'
                      AND receipt.issuer_contract_version=
                          review_payload->>'issuer_contract_version'
                      AND receipt.issuer_contract_version='1.0.0'
                      AND receipt.issuer_contract_sha256=
                          review_payload->>'issuer_contract_sha256'
                      AND receipt.issuer_contract_sha256=
                          'd85428cb588631ff0afd0592b08d5c4bd372aed4abbd543c0fbb07f4c5a773e7'
                      AND receipt.schema_sha256=
                          review_payload->>'schema_sha256'
                      AND receipt.schema_sha256=
                          'c79a43be77115a956ff2d996261e4f1223ab0468ae08bcb17c3656be1c37f111'
                      AND receipt.issuer_actor_id=
                          review_payload->>'issuer_actor_id'
                      AND receipt.tenant_ref=NEW.tenant_ref
                      AND receipt.entity_ref=NEW.entity_ref
                      AND receipt.store_ref=NEW.store_ref
                       AND receipt.scope_grant_authority_sha256=
                           NEW.scope_grant_authority_sha256
                       AND receipt.issuer_actor_id<>NEW.actor_id
                       AND receipt.issuer_actor_id<>
                           (SELECT root.actor_id FROM {BUNDLES} root
                            WHERE root.bundle_id=NEW.bundle_id)
                       AND receipt.data_as_of=
                           (review_payload->>'data_as_of')::timestamptz
                       AND receipt.effective_at=review_ev.effective_at
                       AND receipt.effective_until=review_ev.effective_until
                       AND receipt.recorded_at=review_ev.recorded_at
                       AND receipt.review_due_at=
                           (review_payload->>'review_due_at')::timestamptz
                       AND kjds_cloe_review_issuer_is_independent(
                           NEW.bundle_id,receipt.issuer_actor_id)
                )) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop review authority is invalid';
            END IF;
            IF NEW.event_type='superseded' AND NOT EXISTS (
                SELECT 1 FROM {BUNDLES} replacement
                WHERE replacement.bundle_id=NEW.replacement_bundle_id
                  AND replacement.tenant_ref=NEW.tenant_ref
                  AND replacement.entity_ref=NEW.entity_ref
                  AND replacement.store_ref=NEW.store_ref
                  AND replacement.scope_grant_authority_sha256=
                      NEW.scope_grant_authority_sha256
                  AND replacement.review_due_at>NEW.occurred_at
                  AND NOT EXISTS (
                      SELECT 1 FROM {EVENTS} replacement_event
                      WHERE replacement_event.bundle_id=replacement.bundle_id
                        AND replacement_event.event_type IN
                            ('review_requested','invalidated','revoked','superseded')
                  )
            ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop replacement bundle is invalid';
            END IF;
            RETURN NEW;
        EXCEPTION
        WHEN check_violation THEN
            RAISE;
        WHEN others THEN
            RAISE EXCEPTION USING ERRCODE='23514',
                MESSAGE='closed-loop event binding is invalid';
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER trg_cloe_event_contract BEFORE INSERT ON {EVENTS} "
        "FOR EACH ROW EXECUTE FUNCTION kjds_cloe_validate_event()"
    )
    op.execute(
        f"CREATE CONSTRAINT TRIGGER trg_cloe_event_contract_deferred "
        f"AFTER INSERT ON {EVENTS} DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION kjds_cloe_validate_event()"
    )
    op.execute(
        f"ALTER FUNCTION {quoted_schema}.kjds_cloe_validate_event() "
        f"OWNER TO {ISSUANCE_OWNER_ROLE}"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION {quoted_schema}.kjds_cloe_validate_event() "
        "FROM PUBLIC"
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_event_evidence_conservation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.source<>'governed-closed-loop-evolution' THEN
                RETURN NULL;
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM {EVENTS} event
                JOIN {BUNDLES} root ON root.bundle_id=event.bundle_id
                JOIN evidence_blobs blob ON blob.sha256=NEW.blob_sha256
                WHERE event.evidence_id=NEW.id
                  AND event.evidence_sha256=NEW.blob_sha256
                  AND event.evidence_source=NEW.source
                  AND event.evidence_source_ref=NEW.source_ref
                  AND event.evidence_grade=NEW.grade
                  AND event.evidence_effective_at=NEW.effective_at
                  AND event.recorded_at=NEW.recorded_at
                  AND event.bundle_id=NEW.metadata_json->>'bundle_id'
                  AND event.event_id=NEW.metadata_json->>'event_id'
                  AND event.event_sha256=NEW.metadata_json->>'event_sha256'
                  AND event.tenant_ref=NEW.metadata_json->>'tenant_ref'
                  AND event.entity_ref=NEW.metadata_json->>'entity_ref'
                  AND event.store_ref=NEW.metadata_json->>'store_ref'
                  AND event.scope_grant_authority_sha256=
                      NEW.metadata_json->>'scope_grant_authority_sha256'
                  AND root.tenant_ref=event.tenant_ref
                  AND root.entity_ref=event.entity_ref
                  AND root.store_ref=event.store_ref
                  AND root.scope_grant_authority_sha256=
                      event.scope_grant_authority_sha256
                  AND NEW.source_ref=(
                      'closed-loop-evolution://' || event.bundle_id || '/' ||
                      event.event_id)
                  AND blob.byte_size=octet_length(blob.content_bytes)
                  AND encode(sha256(blob.content_bytes),'hex')=NEW.blob_sha256
            ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop event Evidence has no exact ledger event';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_cloe_event_evidence_conservation "
        "AFTER INSERT ON evidence_records DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW WHEN (NEW.source='governed-closed-loop-evolution') "
        "EXECUTE FUNCTION kjds_cloe_event_evidence_conservation()"
    )
    op.execute(
        f"""
        CREATE FUNCTION kjds_cloe_conservation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE target_bundle text;
        DECLARE root {BUNDLES}%ROWTYPE;
        DECLARE experiment jsonb;
        DECLARE cost jsonb;
        DECLARE outcome jsonb;
        DECLARE link_count integer;
        DECLARE evidence_count integer;
        DECLARE issuer_count integer;
        DECLARE event_count integer;
        BEGIN
            target_bundle := COALESCE(NEW.bundle_id, OLD.bundle_id);
            SELECT * INTO root FROM {BUNDLES} WHERE bundle_id=target_bundle;
            IF root.bundle_id IS NULL THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence conservation failed';
            END IF;
            PERFORM kjds_cloe_validate_agent_run_contract(
                root.agent_run_ref,root.tenant_ref,root.entity_ref,root.store_ref,
                root.scope_grant_authority_sha256,root.data_as_of,
                root.authority_checked_at,root.agent_run_terminal_event_sha256
            );
            SELECT count(*),count(DISTINCT evidence_id),count(DISTINCT issuer_actor_id)
            INTO link_count,evidence_count,issuer_count FROM {LINKS}
            WHERE bundle_id=target_bundle;
            IF link_count<>3 OR evidence_count<>3 OR issuer_count<>3
               OR (SELECT count(DISTINCT purpose) FROM {LINKS}
                   WHERE bundle_id=target_bundle)<>3
               OR EXISTS (
                   SELECT 1 FROM {LINKS} supporting
                   WHERE supporting.bundle_id=target_bundle
                     AND supporting.issuer_actor_id=root.actor_id
               ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop Evidence conservation failed';
            END IF;
            SELECT convert_from(blob.content_bytes,'UTF8')::jsonb INTO experiment
            FROM {LINKS} link JOIN evidence_blobs blob
              ON blob.sha256=link.evidence_sha256
            WHERE link.bundle_id=target_bundle AND link.purpose='experiment';
            SELECT convert_from(blob.content_bytes,'UTF8')::jsonb INTO cost
            FROM {LINKS} link JOIN evidence_blobs blob
              ON blob.sha256=link.evidence_sha256
            WHERE link.bundle_id=target_bundle AND link.purpose='cost';
            SELECT convert_from(blob.content_bytes,'UTF8')::jsonb INTO outcome
            FROM {LINKS} link JOIN evidence_blobs blob
              ON blob.sha256=link.evidence_sha256
            WHERE link.bundle_id=target_bundle AND link.purpose='business_outcome';
            IF EXISTS (
                 SELECT 1 FROM (VALUES
                   ('experiment',experiment),
                   ('cost',cost),
                   ('business_outcome',outcome)
                 ) authority(purpose,payload)
                 WHERE NOT kjds_cloe_claims_are_canonical(
                           authority.purpose,authority.payload->'claims')
                    OR NOT kjds_cloe_json_is_canonical_utc(
                           authority.payload->'data_as_of')
                    OR NOT kjds_cloe_json_is_canonical_utc(
                           authority.payload->'effective_at')
                    OR NOT kjds_cloe_json_is_canonical_utc(
                           authority.payload->'effective_until')
                    OR NOT kjds_cloe_json_is_canonical_utc(
                           authority.payload->'recorded_at')
                    OR NOT kjds_cloe_json_is_canonical_utc(
                           authority.payload->'review_due_at')
               )
               OR experiment->>'data_as_of'<>outcome->>'data_as_of'
               OR experiment->>'data_as_of'<>cost->>'data_as_of'
               OR experiment->'claims'->'causal_claim_allowed'<>'false'::jsonb
               OR outcome->'claims'->'causal_claim_allowed'<>'false'::jsonb
               OR (experiment->>'data_as_of')::timestamptz<>root.data_as_of
               OR experiment->'claims'->>'agent_run_ref'<>root.agent_run_ref
               OR cost->'claims'->>'agent_run_ref'<>root.agent_run_ref
               OR outcome->'claims'->>'agent_run_ref'<>root.agent_run_ref
               OR experiment->'claims'->>'experiment_ref'<>root.experiment_ref
               OR cost->'claims'->>'experiment_ref'<>root.experiment_ref
               OR outcome->'claims'->>'experiment_ref'<>root.experiment_ref
               OR cost->'claims'->>'outcome_ref'<>root.outcome_ref
               OR outcome->'claims'->>'outcome_ref'<>root.outcome_ref
               OR experiment->'claims'->>'method'<>root.experiment_method
               OR outcome->'claims'->>'method'<>root.experiment_method
               OR experiment->'claims'->>'metric_id'<>root.metric_id
               OR outcome->'claims'->>'metric_id'<>root.metric_id
               OR experiment->'claims'->>'metric_unit'<>root.metric_unit
               OR outcome->'claims'->>'metric_unit'<>root.metric_unit
               OR experiment->'claims'->>'metric_currency'
                    IS DISTINCT FROM root.metric_currency
               OR outcome->'claims'->>'metric_currency'
                    IS DISTINCT FROM root.metric_currency
               OR (root.metric_unit='minor_currency_units'
                   AND root.metric_currency<>root.cost_currency)
               OR (experiment->'claims'->>'sample_size')::integer<>root.sample_size
               OR (outcome->'claims'->>'sample_size')::integer<>root.sample_size
               OR (experiment->'claims'->>'minimum_sample_size')::integer
                    <>root.minimum_sample_size
               OR (experiment->'claims'->>'confidence_level_decimal')::numeric
                    <>root.experiment_confidence_level
               OR (experiment->'claims'->>'independent_review_passed')::boolean
                    IS DISTINCT FROM root.experiment_independent_review_passed
               OR experiment->'claims'->>'treatment_ref'<>root.treatment_ref
               OR experiment->'claims'->>'control_ref' IS DISTINCT FROM root.control_ref
               OR (experiment->'claims'->>'window_start')::timestamptz
                    <>root.experiment_window_start
               OR (experiment->'claims'->>'window_end')::timestamptz
                    <>root.experiment_window_end
               OR cost->'claims'->>'cost_ref'<>root.cost_ref
               OR (cost->'claims'->>'amount_minor_units')::bigint
                    <>root.cost_amount_minor_units
               OR cost->'claims'->>'currency'<>root.cost_currency
               OR cost->'claims'->>'allocation_method'<>root.cost_allocation_method
               OR (cost->'claims'->>'period_start')::timestamptz
                    <>root.cost_period_start
               OR (cost->'claims'->>'period_end')::timestamptz
                    <>root.cost_period_end
               OR outcome->'claims'->>'outcome_ref'<>root.outcome_ref
               OR (outcome->'claims'->>'value_decimal')::numeric
                    <>root.outcome_value_decimal
               OR (outcome->'claims'->>'confidence_level_decimal')::numeric
                    <>root.outcome_confidence_level
               OR (outcome->'claims'->>'independent_review_passed')::boolean
                    IS DISTINCT FROM root.outcome_independent_review_passed
               OR (outcome->'claims'->>'interval_start')::timestamptz
                    <>root.outcome_interval_start
               OR (outcome->'claims'->>'interval_end')::timestamptz
                    <>root.outcome_interval_end
               OR root.request_json::jsonb->>'experiment_evidence_ref'<>
                    (SELECT evidence_id FROM {LINKS}
                     WHERE bundle_id=target_bundle AND purpose='experiment')
               OR root.request_json::jsonb->>'cost_evidence_ref'<>
                    (SELECT evidence_id FROM {LINKS}
                     WHERE bundle_id=target_bundle AND purpose='cost')
               OR root.request_json::jsonb->>'outcome_evidence_ref'<>
                    (SELECT evidence_id FROM {LINKS}
                     WHERE bundle_id=target_bundle AND purpose='business_outcome')
               OR root.bundle_json::jsonb->'supporting'->'experiment'->>'evidence_sha256'<>
                    (SELECT evidence_sha256 FROM {LINKS}
                     WHERE bundle_id=target_bundle AND purpose='experiment')
               OR root.bundle_json::jsonb->'supporting'->'cost'->>'evidence_sha256'<>
                    (SELECT evidence_sha256 FROM {LINKS}
                     WHERE bundle_id=target_bundle AND purpose='cost')
               OR root.bundle_json::jsonb->'supporting'->'business_outcome'->>'evidence_sha256'<>
                    (SELECT evidence_sha256 FROM {LINKS}
                     WHERE bundle_id=target_bundle AND purpose='business_outcome')
               OR root.bundle_json::jsonb->'supporting'->'experiment'<>
                    (SELECT jsonb_build_object(
                        'evidence_id',evidence_id,'evidence_sha256',evidence_sha256,
                        'claims_sha256',claims_sha256,'issuer_actor_id',issuer_actor_id)
                     FROM {LINKS} WHERE bundle_id=target_bundle AND purpose='experiment')
               OR root.bundle_json::jsonb->'supporting'->'cost'<>
                    (SELECT jsonb_build_object(
                        'evidence_id',evidence_id,'evidence_sha256',evidence_sha256,
                        'claims_sha256',claims_sha256,'issuer_actor_id',issuer_actor_id)
                     FROM {LINKS} WHERE bundle_id=target_bundle AND purpose='cost')
               OR root.bundle_json::jsonb->'supporting'->'business_outcome'<>
                    (SELECT jsonb_build_object(
                        'evidence_id',evidence_id,'evidence_sha256',evidence_sha256,
                        'claims_sha256',claims_sha256,'issuer_actor_id',issuer_actor_id)
                     FROM {LINKS} WHERE bundle_id=target_bundle
                       AND purpose='business_outcome')
               OR root.bundle_json::jsonb->'causal_claim_allowed'<>'false'::jsonb
               OR root.bundle_json::jsonb->'causal_claim_allowed'
                    IS DISTINCT FROM to_jsonb(root.causal_claim_allowed)
               OR root.causal_claim_allowed IS DISTINCT FROM FALSE
               OR root.effective_at<>(SELECT max(evidence_effective_at) FROM {LINKS}
                    WHERE bundle_id=target_bundle)
               OR root.review_due_at<>(SELECT min(evidence_review_due_at) FROM {LINKS}
                    WHERE bundle_id=target_bundle)
               OR root.authority_checked_at>=(
                    SELECT min(evidence_review_due_at) FROM {LINKS}
                    WHERE bundle_id=target_bundle)
               OR root.authority_checked_at>=(
                    SELECT min(evidence_effective_until) FROM {LINKS}
                    WHERE bundle_id=target_bundle)
               OR EXISTS (
                    SELECT 1 FROM {LINKS} current_link
                    WHERE current_link.bundle_id=target_bundle
                      AND (current_link.evidence_effective_at>root.authority_checked_at
                           OR current_link.evidence_recorded_at>root.data_as_of)
               )
               OR EXISTS (
                    SELECT 1
                    FROM agent_runtime_run_events run_event
                    LEFT JOIN evidence_records run_evidence
                      ON run_evidence.id=run_event.evidence_id
                    LEFT JOIN evidence_blobs run_blob
                      ON run_blob.sha256=run_evidence.blob_sha256
                    WHERE run_event.run_id=root.agent_run_ref
                      AND (
                        run_evidence.id IS NULL
                        OR run_blob.sha256 IS NULL
                        OR NOT kjds_cloe_agent_evidence_is_typed(
                            convert_from(run_blob.content_bytes,'UTF8')::jsonb,
                            run_evidence.metadata_json::jsonb)
                        OR run_evidence.blob_sha256<>run_event.evidence_sha256
                        OR encode(sha256(run_blob.content_bytes),'hex')<>
                            run_event.evidence_sha256
                        OR run_evidence.source IS DISTINCT FROM
                            'governed-agent-run-evidence'
                        OR run_evidence.grade IS DISTINCT FROM 'B'
                        OR run_evidence.source_ref IS DISTINCT FROM
                            'agent-run://'||run_event.run_id||'/'||run_event.event_id
                        OR run_evidence.metadata_json->>'tenant_ref' IS DISTINCT FROM
                            root.tenant_ref
                        OR run_evidence.metadata_json->>'contract_id'
                            IS DISTINCT FROM
                            'kjds-governed-agent-run-evidence-v1'
                        OR run_evidence.metadata_json->>'entity_ref' IS DISTINCT FROM
                            root.entity_ref
                        OR run_evidence.metadata_json->>'store_ref' IS DISTINCT FROM
                            root.store_ref
                        OR run_evidence.metadata_json->>'authority_sha256'
                            IS DISTINCT FROM
                            root.scope_grant_authority_sha256
                        OR run_evidence.metadata_json->>'run_id' IS DISTINCT FROM
                            run_event.run_id
                        OR run_evidence.metadata_json->>'event_id' IS DISTINCT FROM
                            run_event.event_id
                        OR run_evidence.metadata_json->>'event_type' IS DISTINCT FROM
                            run_event.event_type
                        OR run_evidence.metadata_json->>'event_sha256'
                            IS DISTINCT FROM
                            run_event.event_sha256
                        OR (SELECT count(*) FROM jsonb_object_keys(
                            run_evidence.metadata_json::jsonb
                        ))<>11
                        OR NOT ((run_evidence.metadata_json::jsonb) ?& ARRAY[
                            'contract_id','tenant_ref','entity_ref','store_ref',
                            'authority_sha256','run_id','event_id','event_type',
                            'event_sha256','retention_class','legal_hold'
                        ])
                        OR run_evidence.metadata_json->>'retention_class'
                            IS DISTINCT FROM 'security'
                        OR (run_evidence.metadata_json::jsonb)->'legal_hold'
                            IS DISTINCT FROM 'false'::jsonb
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'contract_id' IS DISTINCT FROM
                            'kjds-governed-agent-run-evidence-v1'
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'run_id' IS DISTINCT FROM run_event.run_id
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'event_id' IS DISTINCT FROM run_event.event_id
                        OR (SELECT count(*) FROM jsonb_object_keys(
                            convert_from(run_blob.content_bytes,'UTF8')::jsonb
                        ))<>24
                        OR NOT (
                            convert_from(run_blob.content_bytes,'UTF8')::jsonb
                            ?& ARRAY[
                              'contract_id','run_id','event_id','event_index',
                              'event_type','reason_code','adapter_sha256',
                              'provider_sha256','model_sha256',
                              'adapter_config_sha256','output_sha256','eval_sha256',
                              'input_tokens','output_tokens','cost_usd','latency_ms',
                              'safe_payload','previous_event_sha256','occurred_at',
                              'event_sha256','payload_status','proposal_only',
                              'formal_fact','external_write_allowed'
                            ]
                        )
                        OR (convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'event_index')::integer IS DISTINCT FROM
                            run_event.event_index
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'event_type' IS DISTINCT FROM run_event.event_type
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'reason_code' IS DISTINCT FROM run_event.reason_code
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'adapter_sha256' IS DISTINCT FROM
                            run_event.adapter_sha256
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'provider_sha256' IS DISTINCT FROM
                            run_event.provider_sha256
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'model_sha256' IS DISTINCT FROM run_event.model_sha256
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'adapter_config_sha256' IS DISTINCT FROM
                            run_event.adapter_config_sha256
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'output_sha256' IS DISTINCT FROM run_event.output_sha256
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'eval_sha256' IS DISTINCT FROM run_event.eval_sha256
                        OR (convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'input_tokens')::integer IS DISTINCT FROM
                            run_event.input_tokens
                        OR (convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'output_tokens')::integer IS DISTINCT FROM
                            run_event.output_tokens
                        OR (convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'latency_ms')::integer IS DISTINCT FROM
                            run_event.latency_ms
                        OR (convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'cost_usd')::numeric IS DISTINCT FROM
                            run_event.cost_usd
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'previous_event_sha256' IS DISTINCT FROM
                            run_event.previous_event_sha256
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'event_sha256' IS DISTINCT FROM run_event.event_sha256
                        OR (convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'occurred_at')::timestamptz IS DISTINCT FROM
                            run_event.occurred_at
                        OR (convert_from(run_blob.content_bytes,'UTF8')::jsonb->
                            'safe_payload') IS DISTINCT FROM
                            run_event.safe_payload_json::jsonb
                        OR (convert_from(run_blob.content_bytes,'UTF8')::jsonb->
                            'proposal_only') IS DISTINCT FROM 'true'::jsonb
                        OR convert_from(run_blob.content_bytes,'UTF8')::jsonb->>
                            'payload_status' IS DISTINCT FROM 'not_retained'
                        OR (convert_from(run_blob.content_bytes,'UTF8')::jsonb->
                            'formal_fact') IS DISTINCT FROM 'false'::jsonb
                        OR (convert_from(run_blob.content_bytes,'UTF8')::jsonb->
                            'external_write_allowed') IS DISTINCT FROM 'false'::jsonb
                        OR run_event.tenant_ref<>root.tenant_ref
                        OR run_event.entity_ref<>root.entity_ref
                        OR run_event.store_ref<>root.store_ref
                        OR run_event.authority_sha256<>
                            root.scope_grant_authority_sha256
                        OR run_event.occurred_at>root.data_as_of
                        OR run_event.recorded_at>root.data_as_of
                        OR run_evidence.effective_at>run_evidence.recorded_at
                        OR run_evidence.effective_at>root.data_as_of
                        OR run_evidence.recorded_at>root.data_as_of
                        OR run_evidence.effective_at>root.authority_checked_at
                        OR (run_evidence.effective_until IS NOT NULL
                            AND run_evidence.effective_until<=root.authority_checked_at)
                      )
               )
               OR NOT EXISTS (
                    SELECT 1 FROM agent_runtime_run_events terminal
                    WHERE terminal.run_id=root.agent_run_ref
                      AND terminal.event_sha256=
                          root.agent_run_terminal_event_sha256
                      AND terminal.event_type='run_succeeded'
                      AND NOT EXISTS (
                          SELECT 1 FROM agent_runtime_run_events later
                          WHERE later.run_id=terminal.run_id
                            AND later.event_index>terminal.event_index
                      )
               ) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop bundle and Evidence claims drifted';
            END IF;
            SELECT count(*) INTO event_count FROM {EVENTS}
            WHERE bundle_id=target_bundle;
            IF event_count<1
               OR NOT EXISTS (SELECT 1 FROM {EVENTS}
                    WHERE bundle_id=target_bundle AND event_index=1
                      AND event_type='bundle_recorded'
                      AND actor_id=root.actor_id
                      AND reason_code='independent_authorities_verified'
                      AND idempotency_sha256=root.idempotency_sha256
                      AND request_json::jsonb->>'idempotency_key'=
                          root.request_json::jsonb->>'idempotency_key'
                      AND occurred_at=root.recorded_at
                      AND recorded_at=root.recorded_at
                      AND recorded_at=root.authority_checked_at) THEN
                RAISE EXCEPTION USING ERRCODE='23514',
                    MESSAGE='closed-loop event conservation failed';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    for table, suffix in ((BUNDLES, "bundle"), (LINKS, "link"), (EVENTS, "event")):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_cloe_{suffix}_conservation "
            f"AFTER INSERT OR UPDATE OR DELETE ON {table} "
            "DEFERRABLE INITIALLY DEFERRED "
            "FOR EACH ROW EXECUTE FUNCTION kjds_cloe_conservation()"
        )


def downgrade() -> None:
    op.execute("SELECT pg_advisory_xact_lock(hashtext('kjds-cloe-0096-lifecycle'))")
    connection = op.get_bind()
    schema = str(connection.scalar(sa.text("SELECT current_schema()")))
    op.execute(
        "LOCK TABLE agent_runtime_run_events, evidence_blobs, evidence_records, lineage_edges, "
        f"{ACL_RECEIPTS}, {AUTHORITY_RECEIPTS}, {ISSUANCES}, "
        f"{BUNDLES}, {LINKS}, {EVENTS} "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if _issuance_role_contract_status(connection) is not None:
        _raise_acl_downgrade_blocked(connection, "roles")
    acl_receipts = _validated_acl_receipts(connection, schema=schema)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM {BUNDLES})
               OR EXISTS (SELECT 1 FROM {LINKS})
               OR EXISTS (SELECT 1 FROM {EVENTS})
               OR EXISTS (SELECT 1 FROM {AUTHORITY_RECEIPTS})
               OR EXISTS (SELECT 1 FROM {ISSUANCES})
               OR EXISTS (
                    SELECT 1 FROM evidence_records WHERE source IN ({SOURCES_SQL})
               ) THEN
                RAISE EXCEPTION USING ERRCODE='55000',
                    MESSAGE='0096 downgrade blocked: closed-loop Evidence exists';
            END IF;
        END;
        $$
        """
    )
    _restore_acl_baseline(connection, schema=schema, rows=acl_receipts)
    for table, suffix in reversed(
        ((BUNDLES, "bundle"), (LINKS, "link"), (EVENTS, "event"))
    ):
        op.execute(f"DROP TRIGGER trg_cloe_{suffix}_conservation ON {table}")
    op.execute("DROP FUNCTION kjds_cloe_conservation()")
    op.execute(
        "DROP TRIGGER trg_cloe_event_evidence_conservation ON evidence_records"
    )
    op.execute("DROP FUNCTION kjds_cloe_event_evidence_conservation()")
    op.execute(f"DROP TRIGGER trg_cloe_event_contract_deferred ON {EVENTS}")
    op.execute(f"DROP TRIGGER trg_cloe_event_contract ON {EVENTS}")
    op.execute("DROP FUNCTION kjds_cloe_validate_event()")
    op.execute("DROP FUNCTION kjds_cloe_review_issuer_is_independent(text,text)")
    op.execute(f"DROP TRIGGER trg_cloe_link_contract_deferred ON {LINKS}")
    op.execute(f"DROP TRIGGER trg_cloe_link_contract ON {LINKS}")
    op.execute("DROP FUNCTION kjds_cloe_validate_link()")
    op.execute("DROP FUNCTION kjds_cloe_validator_principal_is_current()")
    op.execute(f"DROP TRIGGER trg_cloe_bundle_contract ON {BUNDLES}")
    op.execute("DROP FUNCTION kjds_cloe_validate_bundle()")
    op.execute(
        "DROP FUNCTION kjds_cloe_validate_agent_run_contract("
        "text,text,text,text,text,timestamptz,timestamptz,text)"
    )
    op.execute("DROP TRIGGER trg_cloe_blob_immutable ON evidence_blobs")
    op.execute("DROP FUNCTION kjds_cloe_prevent_blob_mutation()")
    op.execute("DROP TRIGGER trg_cloe_evidence_immutable ON evidence_records")
    op.execute("DROP FUNCTION kjds_cloe_prevent_evidence_mutation()")
    op.execute(
        "DROP FUNCTION kjds_cloe_issue_event_evidence("
        "text,bytea,text,text,timestamptz,timestamptz,jsonb)"
    )
    op.execute("DROP FUNCTION kjds_cloe_event_principal_is_current()")
    op.execute(
        "DROP FUNCTION kjds_cloe_issue_evidence("
        "text,text,bytea,text,text,text,timestamptz,timestamptz,jsonb,text,text)"
    )
    op.execute("DROP FUNCTION kjds_cloe_canonical_json(jsonb)")
    op.execute("DROP FUNCTION kjds_cloe_register_authority_receipt(jsonb)")
    op.execute("DROP FUNCTION kjds_cloe_agent_evidence_is_typed(jsonb,jsonb)")
    op.execute("DROP FUNCTION kjds_cloe_claims_are_canonical(text,jsonb)")
    op.execute(
        "DROP FUNCTION kjds_cloe_json_is_canonical_decimal(jsonb,integer,integer)"
    )
    op.execute("DROP FUNCTION kjds_cloe_json_is_canonical_utc(jsonb)")
    op.execute("DROP TRIGGER trg_cloe_generic_lineage ON lineage_edges")
    op.execute("DROP FUNCTION kjds_cloe_prevent_generic_lineage()")
    for table in reversed((*TABLES, AUTHORITY_RECEIPTS, ISSUANCES)):
        op.execute(f"DROP TRIGGER trg_cloe_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION kjds_cloe_prevent_mutation()")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_table(ISSUANCES)
    op.drop_table(AUTHORITY_RECEIPTS)
    op.drop_index(
        "uq_closed_loop_authority_evidence_source_ref",
        table_name="evidence_records",
    )
    op.drop_table(ACL_RECEIPTS)
    op.execute("DROP FUNCTION kjds_cloe_prevent_acl_receipt_mutation()")
