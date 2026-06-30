from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class EstimatorResearchError(RuntimeError):
    """Safe, user-facing representation of an upstream estimator failure."""

    code: str
    message: str
    stage: str
    request_id: str
    http_status: int = 502

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.message)

    def as_detail(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "stage": self.stage,
            "request_id": self.request_id,
        }
