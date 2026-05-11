from uuid import uuid4

from app.api.schemas.feedback import FeedbackRequest, FeedbackResponse


class FeedbackService:
    def record(self, feedback: FeedbackRequest) -> FeedbackResponse:
        _ = feedback
        return FeedbackResponse(
            feedback_id=str(uuid4()),
            accepted=True,
            status="accepted",
            storage="pending_persistence",
        )
