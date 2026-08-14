from __future__ import annotations

import json

from apps.control_plane.database import create_database_engine
from apps.control_plane.operating_gate_bootstrap import (
    G1_ADMIN_ACTOR_ID,
    G1_OPERATING_SUBJECT_ACTOR_ID,
    bootstrap_operating_gate,
    require_g1_database,
)
from apps.control_plane.security import ApiKeyAuthenticator


def main() -> None:
    engine = create_database_engine()
    revision = require_g1_database(engine)
    authenticator = ApiKeyAuthenticator.from_environment()
    result = bootstrap_operating_gate(
        engine=engine,
        admin=authenticator.resolve_actor(G1_ADMIN_ACTOR_ID),
        operating_subject=authenticator.resolve_actor(
            G1_OPERATING_SUBJECT_ACTOR_ID
        ),
    )
    print(json.dumps({**result, "database_revision": revision}, sort_keys=True))


if __name__ == "__main__":
    main()
