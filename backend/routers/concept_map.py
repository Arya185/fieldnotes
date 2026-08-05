from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from backend.auth.dependencies import get_current_user
from backend.auth.models import AuthenticatedUser
from backend.auth.security import assert_workspace_access
from backend.db import connect_sqlite
from backend.indexer.workspace_manager import workspace_manager
from backend.models import ConceptMapEdge, ConceptMapNode, ConceptMapResponse, GenerateConceptMapRequest
from backend.services.concept_map import build_concept_map
from backend.storage import create_artifact

router = APIRouter()

WORKSPACE_ROLES = ["owner", "teacher", "student", "viewer"]


@router.post("/concept-map/generate")
def post_generate_concept_map(
    payload: GenerateConceptMapRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> ConceptMapResponse:
    """Build (and refresh) the concept map for one workspace from its concept log."""

    workspace = workspace_manager.get(payload.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Unknown workspace_id")
    assert_workspace_access(
        payload.workspace_id, current_user, workspace_manager._repository, WORKSPACE_ROLES
    )

    connection = connect_sqlite(workspace.db_path)
    try:
        graph = build_concept_map(connection)
        if not graph["nodes"]:
            raise HTTPException(
                status_code=422,
                detail="No concepts logged yet. Ask a question or run a quiz first.",
            )
        artifact_card = create_artifact(
            connection,
            workspace.artifacts_dir,
            kind="explainer",
            title="Concept map",
            answer_id=f"concept_map_{uuid4().hex[:8]}",
            payload_text=json.dumps(graph),
        )
        connection.commit()
    finally:
        connection.close()

    return ConceptMapResponse(
        nodes=[ConceptMapNode(**node) for node in graph["nodes"]],
        edges=[ConceptMapEdge(**edge) for edge in graph["edges"]],
        artifact_id=artifact_card.id,
    )
