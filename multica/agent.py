import json
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from snowflake.snowpark.session import Session
import snowflake.cortex as cortex

logger = logging.getLogger("multica.agent")

# We default to mistral-large as it is highly capable for analytical tasks 
# natively within Snowflake Cortex.
DEFAULT_MODEL = "mistral-large"

class CortexResponse(BaseModel):
    model: str
    response: str
    parsed_json: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class MulticaAgent:
    """The central 'Genius' agent runtime utilizing Snowflake Cortex natively.
    
    This class is intended to run inside an SPCS container, giving it direct
    secure access to the Snowflake execution environment.
    """
    
    def __init__(self, session: Session):
        self.session = session
        
    def query_cortex(self, prompt: str, model: str = DEFAULT_MODEL) -> CortexResponse:
        """Invokes a Snowflake Cortex LLM completion."""
        try:
            logger.info("Invoking Cortex model: %s", model)
            # Cortex execution natively routes within the Snowflake parameter boundary
            response_text = cortex.Complete(model, prompt, session=self.session)
            
            # Attempt to parse json if the prompt asked for it
            parsed = None
            if "{" in response_text and "}" in response_text:
                try:
                    start_idx = response_text.find("{")
                    end_idx = response_text.rfind("}") + 1
                    json_str = response_text[start_idx:end_idx]
                    parsed = json.loads(json_str)
                except json.JSONDecodeError:
                    pass
                    
            return CortexResponse(model=model, response=response_text, parsed_json=parsed)
        except Exception as e:
            logger.error("Cortex execution failed: %s", str(e))
            return CortexResponse(model=model, response="", error=str(e))

    def evaluate_inventory_health(self, store_id: str, low_stock_threshold: int = 5) -> CortexResponse:
        """Analyzes active inventory locally within Snowflake to find anomalies or issues."""
        
        # 1. Pull localized data securely
        # Instead of pushing data over the wire via REST, the agent pulls it directly
        # from the adjacent compute cluster.
        query = f"""
            SELECT S.SKU_CODE, S.DESCRIPTION, I.QTY_ON_HAND
            FROM RETAILMANAGEMENT.PUBLIC.INVENTORY I
            JOIN RETAILMANAGEMENT.PUBLIC.SKUS S ON I.SKU_ID = S.ID
            WHERE I.STORE_ID = '{store_id}' AND I.QTY_ON_HAND <= {low_stock_threshold}
            ORDER BY I.QTY_ON_HAND ASC
            LIMIT 20
        """
        
        df = self.session.sql(query).to_pandas()
        if df.empty:
            return CortexResponse(
                model=DEFAULT_MODEL, 
                response="No critical low-stock items detected for this store.",
                parsed_json={"status": "healthy", "critical_skus": []}
            )
            
        inventory_context = df.to_json(orient='records')
        
        # 2. Invoke Cortex for Cognitive Analysis
        prompt = f"""
        You are 'Multica', the autonomous retail management AI agent.
        Review the following low-stock items for store {store_id}.
        
        Data:
        {inventory_context}
        
        Analyze the risk. Identify which items are most critical to replenish immediately.
        Return ONLY a JSON response in the following format:
        {{
            "status": "critical" | "warning",
            "summary": "1-2 sentence explanation",
            "priority_replenishments": ["SKU_CODE_1", "SKU_CODE_2"]
        }}
        """
        
        return self.query_cortex(prompt)
