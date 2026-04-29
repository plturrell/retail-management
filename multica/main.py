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

class VaultDocumentIngestRequest(BaseModel):
    document_id: str
    payload: dict


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

@app.post("/api/v1/ingest/vault-document")
async def ingest_vault_document(req: VaultDocumentIngestRequest):
    """Ingest reviewed vault document JSON into Snowflake"""
    if not snowpark_session:
        # Note: Depending on where this is hosted, we might just log and return success for testing
        logger.error("No snowpark session. Assuming testing environment.")
        return {"status": "success", "message": f"Simulated Snowflake insert for {req.document_id}", "records": len(req.payload.get('data', []))}
        
    try:
        # Depending on type (sales vs stock), write to correct snowflake table
        doc_type = req.payload.get("type")
        data = req.payload.get("data", [])
        
        if not data:
            return {"status": "skipped", "message": "No data found to ingest"}
            
        import pandas as pd
        df = pd.DataFrame(data)
        df["SRC_DOCUMENT_ID"] = req.document_id
        
        table_name = "STG_SALES_LEDGER" if doc_type == "sales" else "STG_STOCK_CHECK"
        
        # Write to snowflake table
        snowpark_df = snowpark_session.create_dataframe(df)
        snowpark_df.write.mode("append").save_as_table(table_name)
        
        logger.info(f"Ingested {len(data)} records to {table_name} for document {req.document_id}")
        return {"status": "success", "records_inserted": len(data), "table": table_name}
    except Exception as e:
        logger.error("Ingestion failed: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Failed to ingest to Snowflake: {e}")

class MergeRequest(BaseModel):
    table_type: str # 'sales' or 'stock'

@app.post("/api/v1/trigger/stage-merge")
async def trigger_stage_merge(req: MergeRequest):
    """Merges data from Staging Vault tables into core Fact tables"""
    if not snowpark_session:
        # Note: If no snowpark session is available, we simulate success for local routing
        logger.info("Simulating merge since no Snowpark session is active.")
        return {"status": "success", "message": f"Simulated Snowflake FACT merge for {req.table_type}"}

    try:
        if req.table_type == "sales":
            # Generalized MERGE logic into FACT_SALES
            merge_sql = """
            MERGE INTO FACT_SALES target
            USING STG_SALES_LEDGER source
            ON target.SRC_DOCUMENT_ID = source.SRC_DOCUMENT_ID
            WHEN NOT MATCHED THEN INSERT 
            (DOCUMENT_ID, DATE_ISO, SALESPERSON, ENTRY_TOTAL, QTY, AMOUNT, MATERIAL_CODE, DESCRIPTION)
            VALUES (source.SRC_DOCUMENT_ID, source.date_iso, source.salesperson, source.entry_total, source.qty, source.amount, source.material_code, source.description)
            """
        elif req.table_type == "stock":
            # Generalized MERGE logic into FACT_STOCK_CHECK
            merge_sql = """
            MERGE INTO FACT_STOCK_CHECK target
            USING STG_STOCK_CHECK source
            ON target.PRODUCT_CODE = source.PRODUCT_CODE
            WHEN MATCHED THEN UPDATE SET QTY_CHECKED = source.qty, LAST_CHECKED_DATE = source.check_date
            WHEN NOT MATCHED THEN INSERT
            (PRODUCT_CODE, PRODUCT_NAME, QTY_CHECKED, LOCATION, LAST_CHECKED_DATE, CONDITION)
            VALUES (source.product_code, source.product_name, source.qty, source.location, source.check_date, source.condition)
            """
        else:
            raise HTTPException(status_code=400, detail="Invalid table_type. Use 'sales' or 'stock'.")

        snowpark_session.sql(merge_sql).collect()
        
        # We could also truncate/consume the STG table here
        snowpark_session.sql(f"TRUNCATE TABLE STG_{'SALES_LEDGER' if req.table_type == 'sales' else 'STOCK_CHECK'}").collect()
        
        return {"status": "success", "message": f"Successfully merged STG mapped to {req.table_type} FACT table."}
    except Exception as e:
        logger.error("Merge trigger failed: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Snowflake Merge execution failed: {e}")
