import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from snowflake.snowpark.session import Session

from agent import MulticaAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("multica.api")

# Global variables for Snowpark session and Agent
snowpark_session: Session = None
agent: MulticaAgent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global snowpark_session, agent
    logger.info("Initializing Multica SPCS Service...")
    
    try:
        # Inside SPCS, we can initialize a session seamlessly with get_active_session()
        # This securely binds to the warehouse defined in the setup.sql
        from snowflake.snowpark.context import get_active_session
        snowpark_session = get_active_session()
        agent = MulticaAgent(snowpark_session)
        logger.info("Successfully bound to Snowflake context.")
    except Exception as e:
        logger.warning(
            "Failed to get active Snowflake session. "
            "If running locally for testing, ensure SNOWFLAKE credentials are set. Error: %s",
            str(e)
        )
        
    yield
    
    if snowpark_session:
        snowpark_session.close()

app = FastAPI(title="Multica AI Platform", lifespan=lifespan)


class InventoryHealthRequest(BaseModel):
    store_id: str
    low_stock_threshold: int = 5


@app.get("/health")
def health_check():
    """Liveness probe for SPCS Service."""
    status = "healthy" if snowpark_session else "degraded (no snowpark session)"
    return {"status": status}


@app.post("/api/v1/analyze/inventory")
async def analyze_inventory(req: InventoryHealthRequest):
    """Trigger the 'Genius' layer for inventory analysis."""
    if not agent:
        raise HTTPException(
            status_code=503, 
            detail="Snowpark agent is not initialized. Ensure container is running in SPCS."
        )
        
    try:
        result = agent.evaluate_inventory_health(req.store_id, req.low_stock_threshold)
        if result.error:
            raise HTTPException(status_code=500, detail=result.error)
            
        return {
            "model_used": result.model,
            "raw_text": result.response,
            "payload": result.parsed_json
        }
    except Exception as e:
        logger.error("Analysis failed: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))
