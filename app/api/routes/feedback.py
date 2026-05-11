from fastapi import APIRouter

from app.api.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.feedback.service import FeedbackService


router = APIRouter()


@router.post("", response_model=FeedbackResponse)
def create_feedback(payload: FeedbackRequest) -> FeedbackResponse:
    return FeedbackService().record(payload)
