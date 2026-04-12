import json
import logging
from google import genai
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)

class PricingStrategyUpdate(BaseModel):
    store_name: str
    recommended_discount_rate: float
    recommended_margin: float
    reasoning: str
    action: str  # "APPROVE", "HOLD", "ALERT"

async def get_dynamic_pricing_strategy(
    store_name: str, 
    current_discount: float, 
    cogs_sgd: float, 
    target_margin: float,
    recent_sales_velocity: str = "moderate"
) -> PricingStrategyUpdate:
    """
    Invokes Gemini 2.0 to evaluate if current margin parameters need dynamic overrides.
    Returns structured JSON ensuring strict compliance to retail schema constraints.
    """
    try:
        # Initialize GenAI Client (Requires GEMINI_API_KEY env var)
        client = genai.Client()

        prompt = f"""
        You are an elite automated retail pricing strategist for Singaporean Jewelry.
        We operate a {store_name} store.
        
        CURRENT CONTEXT:
        - Base Production Cost: ${cogs_sgd:.2f} SGD
        - Current Discount Rate: {current_discount * 100}%
        - Target Dividend Margin: {target_margin * 100}%
        - Sales Velocity: {recent_sales_velocity}
        
        Given current macro-economic factors (like the 9% GST in SG) and consumer discretionary spending,
        should we adjust the discount rate or the target margin to optimize absolute gross profit? 
        
        Respond ONLY with a JSON object matching this schema:
        {{
            "store_name": "{store_name}",
            "recommended_discount_rate": float (e.g. 0.15 for 15%),
            "recommended_margin": float (e.g. 0.30 for 30%),
            "reasoning": "string explaining exactly why",
            "action": "APPROVE" or "HOLD"
        }}
        """

        # Using structured outputs for strict programmatic injection
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        
        # Parse output safely
        text_content = response.text.strip()
        if text_content.startswith('```json'):
            text_content = text_content[7:-3]
            
        result = json.loads(text_content.strip())
        return PricingStrategyUpdate(**result)

    except Exception as e:
        logger.error(f"Gemini API evaluation failed: {e}")
        # Fallback to current parameters
        return PricingStrategyUpdate(
            store_name=store_name,
            recommended_discount_rate=current_discount,
            recommended_margin=target_margin,
            reasoning=f"Fallback due to AI error: {e}",
            action="HOLD"
        )
