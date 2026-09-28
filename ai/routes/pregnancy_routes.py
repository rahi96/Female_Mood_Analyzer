"""Pregnancy & Postpartum API routes."""

from fastapi import APIRouter, Query
from ai.services.pregnancy_service import (
    pregnancy_summary,
    postpartum_recovery,
    support_insights
)

router = APIRouter()


@router.get("/pregnancy/summary")
async def get_pregnancy_summary(user_id: int = Query(..., ge=1, description="User ID")):
    """
    **Pregnancy Summary & Status**
    
    Get current pregnancy status, week, trimester, and relevant alerts.
    
    **Parameters:**
    - `user_id` (int, required): User identifier
    
    **Response includes:**
    - Current pregnancy week (0-40)
    - Current trimester (First/Second/Third)
    - Due date calculation
    - Days until due
    - Health status
    - Pregnancy alerts
    
    **Example:**
    ```
    GET /api/v1/pregnancy/summary?user_id=2
    ```
    
    **Response (200 OK):**
    ```json
    {
      "is_pregnant": true,
      "current_week": 24,
      "current_trimester": "Second",
      "due_date": "2026-12-20",
      "days_until_due": 88,
      "health_status": "good",
      "alerts": [...]
    }
    ```
    """
    return pregnancy_summary(user_id)


@router.get("/support/insights")
async def get_support_insights(
    user_id: int = Query(..., ge=1, description="User ID")
):
    """
    **Personalized Support Insights**
    
    Generate context-aware insights based on user's current life stage:
    - Pregnant users: Baby development, body changes, emotional support
    - Postpartum users: Recovery progress, mental health, activity guidance
    - Users with loss: Empathetic grief support and healing resources
    
    **Parameters:**
    - `user_id` (int, required): User identifier
    
    **Intelligence:**
    Automatically detects user phase and delivers personalized insights:
    - Insights adapt to pregnancy week
    - Recovery insights match postpartum recovery stage
    - Loss phase activates empathetic, grief-centered content
    
    **Example:**
    ```
    GET /api/v1/support/insights?user_id=16
    ```
    
    **Response (200 OK - Postpartum):**
    ```json
    {
      "user_id": 16,
      "phase": "postpartum",
      "week": 6,
      "insights": [
        {
          "type": "recovery_progress",
          "category": "physical",
          "title": "Your Healing Journey",
          "content": "Your body has healed 80% - this is excellent progress at week 6...",
          "sentiment": "positive",
          "priority": "high"
        },
        {
          "type": "mental_wellness",
          "category": "emotional",
          "title": "Your Mental Health",
          "content": "At week 6, your hormones are settling down...",
          "sentiment": "supportive",
          "priority": "high"
        },
        {
          "type": "practical_advice",
          "category": "activity",
          "title": "Activity & Exercise",
          "content": "Week 6 is a good time to gradually return to normal activities...",
          "sentiment": "neutral",
          "priority": "medium"
        }
      ],
      "generated_at": "2026-09-28"
    }
    ```
    
    **Response (200 OK - Pregnancy):**
    ```json
    {
      "user_id": 2,
      "phase": "pregnancy",
      "week": 24,
      "insights": [
        {"type": "baby_development", "content": "Your baby is now 24 weeks old..."},
        {"type": "body_changes", "content": "You should be showing now..."},
        {"type": "emotional_support", "content": "At week 24, it's natural to feel..."}
      ],
      "generated_at": "2026-09-28"
    }
    ```
    
    **Response (200 OK - Loss/Miscarriage):**
    ```json
    {
      "user_id": 8,
      "phase": "loss",
      "loss_type": "miscarriage",
      "insights": [
        {
          "type": "grief_support",
          "content": "We're deeply sorry for your loss. Your grief is completely valid...",
          "sentiment": "empathetic",
          "priority": "critical"
        },
        {"type": "healing_guidance", "content": "Grief is not linear..."},
        {"type": "physical_care", "content": "Your body needs time to heal..."}
      ],
      "generated_at": "2026-09-28"
    }
    ```
    """
    return support_insights(user_id)


@router.get("/postpartum/recovery")
async def get_postpartum_recovery(user_id: int = Query(..., ge=1, description="User ID")):
    """
    **Postpartum Recovery Status**
    
    Get comprehensive postpartum recovery overview including:
    - Physical recovery metrics
    - Mental health assessment
    - Activity level recommendations
    - Sleep quality
    - Postpartum alerts
    
    **Parameters:**
    - `user_id` (int, required): User identifier
    
    **Response includes:**
    - Postpartum week (0-12)
    - Delivery method
    - Recovery metrics (physical recovery %, bleeding level, pelvic floor status)
    - Mental health (mood stability, anxiety, depression screening)
    - Activity level
    - Sleep hours
    - Postpartum alerts
    
    **Example:**
    ```
    GET /api/v1/postpartum/recovery?user_id=2
    ```
    
    **Response (200 OK):**
    ```json
    {
      "postpartum_week": 6,
      "delivery_method": "vaginal",
      "recovery_metrics": {
        "physical_recovery_percent": 72,
        "bleeding_level": "light",
        "pelvic_floor_status": "healing"
      },
      "mental_health": {
        "mood_stability": 65,
        "anxiety_level": 3,
        "depression_screening": "low_risk"
      },
      "activity_level": "moderate",
      "sleep_hours": 4.5,
      "postpartum_alerts": [...]
    }
    ```
    """
    return postpartum_recovery(user_id)



