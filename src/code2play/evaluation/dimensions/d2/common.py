from __future__ import annotations

from pathlib import Path
from typing import Any

from code2play.execution.candidate_project import CandidateProject

from .base import FunctionalityResult
from .protocol_evaluator import evaluate_protocol_functionality


def evaluate_dimension2(
    game_id: str,
    project: CandidateProject | Path | str,
    runtime_signals: dict[str, bool] | None = None,
    spec_path: Path | str | None = None,
    sample_manifest: dict[str, Any] | None = None,
    judge: Any | None = None,
) -> FunctionalityResult:
    """Evaluate functionality through the formal protocol-v4 evidence path."""
    del game_id, runtime_signals
    if spec_path is None:
        raise ValueError("Formal D2 evaluation requires spec_path")
    if sample_manifest is None:
        raise ValueError("Formal functionality evaluation requires a protocol-v4 sample manifest")
    if judge is None:
        raise ValueError("Formal D2 evaluation requires an evaluator-side judge")
    return evaluate_protocol_functionality(
        project=(
            project
            if isinstance(project, CandidateProject)
            else CandidateProject(project)
        ),
        spec_path=Path(spec_path),
        sample_manifest=sample_manifest,
        judge=judge,
    )
