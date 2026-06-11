from app.api.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.db.operational import OperationalRepository
from app.db.runtime import DatabaseRuntime


class FeedbackService:
    def __init__(self, runtime: DatabaseRuntime | None = None) -> None:
        self.runtime = runtime

    def record(self, feedback: FeedbackRequest) -> FeedbackResponse:
        if self.runtime is None:
            from uuid import uuid4

            return FeedbackResponse(
                feedback_id=str(uuid4()),
                accepted=True,
                status="accepted",
                storage="pending_persistence",
            )
        return OperationalRepository(self.runtime).record_feedback(feedback)
