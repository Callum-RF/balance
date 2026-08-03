from fastapi import APIRouter

from backend.nutrient_info import NUTRIENT_INFO, CAFFEINE_LIKE_SUBSTANCES

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/nutrients")
def nutrient_reference():
    return NUTRIENT_INFO


@router.get("/caffeine-like")
def caffeine_like_reference():
    return CAFFEINE_LIKE_SUBSTANCES
