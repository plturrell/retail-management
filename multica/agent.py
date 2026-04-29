import json
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from snowflake.snowpark.session import Session
from openai import OpenAI

logger = logging.getLogger("multica.agent")

# We default to deepseek-reasoner to leverage 'Thinking Mode' for complex inventory analysis.
DEFAULT_MODEL = "deepseek-reasoner"

class AgentResponse(BaseModel):
    model: str
    response: str
    parsed_json: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class MulticaAgent:
    """The central 'Genius' agent runtime utilizing DeepSeek Reasoner natively.
    
    This class runs inside an SPCS container and securely pulls the DEEPSEEK_API_KEY
    to reach api.deepseek.com via External Network Access.
    """
    
    def __init__(self, session: Session):
        self.session = session
        
    def query_reasoner(self, prompt: str, model: str = DEFAULT_MODEL) -> AgentResponse:
        """Invokes a DeepSeek LLM completion."""
        import os
        try:
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            if not api_key:
                logger.warning("DEEPSEEK_API_KEY not found in environment. Please map SPCS secret.")
                
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com",
            )
            
            logger.info("Invoking DeepSeek model: %s", model)
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=8192,
            )
            
            response_text = response.choices[0].message.content or ""
            
            # Attempt to parse json if the prompt asked for it (ignores <think> block)
            parsed = None
            if "{" in response_text and "}" in response_text:
                try:
                    start_idx = response_text.find("{")
                    end_idx = response_text.rfind("}") + 1
                    json_str = response_text[start_idx:end_idx]
                    parsed = json.loads(json_str)
                except json.JSONDecodeError:
                    pass
                    
            return AgentResponse(model=model, response=response_text, parsed_json=parsed)
        except Exception as e:
            logger.error("DeepSeek execution failed: %s", str(e))
            return AgentResponse(model=model, response="", error=str(e))

    def evaluate_inventory_health(self, store_id: str, low_stock_threshold: int = 5, recent_transactions: Optional[str] = None) -> AgentResponse:
        """Analyzes active inventory locally within Snowflake to find anomalies or issues.
        Optionally accepts recent TiDB real-time ledger transactions for up-to-the-second context."""
        
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
            return AgentResponse(
                model=DEFAULT_MODEL, 
                response="No critical low-stock items detected for this store.",
                parsed_json={"status": "healthy", "critical_skus": []}
            )
            
        inventory_context = df.to_json(orient='records')
        
        # Format recent transactions if provided
        tidb_context = ""
        if recent_transactions:
            tidb_context = f"\nRecent Real-Time Transactions (TiDB Ledger):\n{recent_transactions}\n"
        
        # 2. Invoke DeepSeek for Cognitive Analysis
        prompt = f"""
        You are 'Multica', the autonomous retail management AI agent.
        Review the following low-stock items for store {store_id}.
        
        Data:
        {inventory_context}
        {tidb_context}
        Think deeply about the implications of these low-stock items. Identify which items are most critical to replenish immediately.
        After your <think> block, return ONLY a JSON response in the following format:
        {{
            "status": "critical" | "warning",
            "summary": "1-2 sentence explanation",
            "priority_replenishments": ["SKU_CODE_1", "SKU_CODE_2"]
        }}
        """
        
        return self.query_reasoner(prompt)
