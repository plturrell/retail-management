from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict

# Local imports
from app.services.gemini_strategist import get_dynamic_pricing_strategy, PricingStrategyUpdate

router = APIRouter(
    prefix="/strategy",
    tags=["Pricing Strategy"],
)

class PricingContext(BaseModel):
    store_name: str
    current_discount: float
    cogs_sgd: float
    target_margin: float
    sales_velocity: str = "moderate"

@router.post("/dynamic_pricing", response_model=PricingStrategyUpdate)
async def evaluate_dynamic_pricing(context: PricingContext):
    """
    Triggers Gemini to evaluate if the Mangle Datalog pricing logic parameters 
    should be overridden based on current constraints and market conditions.
    """
    # In a full deployment, this would first execute the Mangle POS binary 
    # natively to fetch the live cogs_sgd instead of accepting via POST.
    
    strategy = await get_dynamic_pricing_strategy(
        store_name=context.store_name,
        current_discount=context.current_discount,
        cogs_sgd=context.cogs_sgd,
        target_margin=context.target_margin,
        recent_sales_velocity=context.sales_velocity
    )
    
    if strategy.action == "APPROVE" and strategy.recommended_margin < context.target_margin:
        # Here we would typically write the new rule into the .mangle database logic via a file write
        # Then we queue an alert for the human-in-the-loop to confirm execution.
        pass
        
    return strategy
