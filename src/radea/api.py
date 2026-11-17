"""Public Python facade. No Click dependency, stdout capture or monkeypatch required."""

from radea.core.config import Config
from radea.core.models import AnalysisRequest, ModelClient, Result
from radea.core.service import AnalysisService

__all__ = ["AnalysisRequest", "AnalysisService", "Config", "ModelClient", "analyze"]


def analyze(
    request: AnalysisRequest, *, config: Config | None = None, model: ModelClient | None = None
) -> Result:
    """Return a guarded draft result; failures are explicit result['error'] values."""
    return AnalysisService(config, model).analyze(request)
