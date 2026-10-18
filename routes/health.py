from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Health check")
def health() -> dict[str, str]:
    """Returns `ok` when the app is running. Not rate limited."""
    return {"status": "ok"}
