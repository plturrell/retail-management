#!/usr/bin/env python3
"""
Pipeline script to ingest local vector catalogs and mangle facts into Snowflake.
"""

import sys
import os
import json
import logging
import argparse
from pathlib import Path

# Add repo root to sys.path mapped to the exact relative depth
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.pipelines import paths

# Attempt to load dotenv for local environments
try:
    from dotenv import load_dotenv
    load_dotenv(paths.REPO_ROOT / "backend" / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def get_snowflake_connection():
    try:
        import snowflake.connector
    except ImportError:
        logger.error("snowflake-connector-python is not installed.")
        logger.error("Install it with: pip install snowflake-connector-python[pandas]")
        sys.exit(1)

    account = os.getenv("SNOWFLAKE_ACCOUNT")
    user = os.getenv("SNOWFLAKE_USER")
    password = os.getenv("SNOWFLAKE_PASSWORD")
    database = os.getenv("SNOWFLAKE_DATABASE")
    schema = os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC")
    warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")

    if not all([account, user, password, database]):
        logger.error("Missing required Snowflake environment variables: "
                     "SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD, SNOWFLAKE_DATABASE")
        sys.exit(1)

    logger.info(f"Connecting to Snowflake account {account}...")
    ctx = snowflake.connector.connect(
        user=user,
        password=password,
        account=account,
        warehouse=warehouse,
        database=database,
        schema=schema
    )
    return ctx

def ingest_mangle_facts(ctx):
    """
    Reads all .mangle files in the facts directory and uploads them as records.
    """
    logger.info("Ingesting Mangle facts...")
    facts_dir = paths.MANGLE_FACTS_DIR
    if not facts_dir.exists():
        logger.warning(f"Mangle facts dir does not exist: {facts_dir}")
        return

    cursor = ctx.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS MANGLE_FACTS (
            FILENAME VARCHAR,
            CONTENT STRING,
            UPLOADED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
        )
    """)
    
    count = 0
    for mangle_file in facts_dir.glob("*.mangle"):
        with open(mangle_file, "r") as f:
            content = f.read()
            cursor.execute(
                "INSERT INTO MANGLE_FACTS (FILENAME, CONTENT) VALUES (%s, %s)",
                (mangle_file.name, content)
            )
            count += 1
    logger.info(f"Successfully ingested {count} Mangle facts.")

def ingest_catalog_vectors(ctx):
    """
    Reads product_embedding_index.json and product_embeddings.npy.
    Uploads them into a Snowflake table with VECTOR data type support.
    """
    logger.info("Ingesting Catalog Vectors...")
    try:
        import numpy as np
    except ImportError:
        logger.error("numpy is not installed. Required for vector ingestion.")
        return

    index_path = paths.EMBED_INDEX_PATH
    npy_path = paths.EMBED_NPY_PATH

    if not index_path.exists() or not npy_path.exists():
        logger.warning("Catalog embeddings files do not exist.")
        return

    with open(index_path, "r") as f:
        embedding_index = json.load(f)
    
    embeddings = np.load(npy_path)

    if len(embedding_index) != embeddings.shape[0]:
        logger.error("Mismatch between embedding index length and numpy array shape.")
        return

    cursor = ctx.cursor()
    dimension = embeddings.shape[1]
    
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS PRODUCT_CATALOG_VECTORS (
            PRODUCT_ID VARCHAR,
            TEXT_REPRESENTATION STRING,
            EMBEDDING VECTOR(FLOAT, {dimension})
        )
    """)

    insert_query = f"""
        INSERT INTO PRODUCT_CATALOG_VECTORS (PRODUCT_ID, TEXT_REPRESENTATION, EMBEDDING) 
        SELECT %s, %s, PARSE_JSON(%s)::VECTOR(FLOAT, {dimension})
    """

    count = 0
    for i, meta in enumerate(embedding_index):
        # Extract metadata properly based on the assumed structure
        product_id = meta.get("id", f"prod_{i}") if isinstance(meta, dict) else str(meta)
        text_rep = meta.get("text", "") if isinstance(meta, dict) else ""
        vector_json = json.dumps(embeddings[i].tolist())
        
        cursor.execute(insert_query, (product_id, text_rep, vector_json))
        count += 1
    
    logger.info(f"Successfully ingested {count} product vectors.")

def main():
    parser = argparse.ArgumentParser(description="Snowflake Data Ingestion Script")
    parser.add_argument("--facts", action="store_true", help="Ingest mangle facts")
    parser.add_argument("--vectors", action="store_true", help="Ingest catalog vectors")
    parser.add_argument("--all", action="store_true", help="Ingest all available data")
    
    args = parser.parse_args()
    
    if not any([args.facts, args.vectors, args.all]):
        parser.print_help()
        sys.exit(1)

    ctx = get_snowflake_connection()
    try:
        if args.facts or args.all:
            ingest_mangle_facts(ctx)
        
        if args.vectors or args.all:
            ingest_catalog_vectors(ctx)
            
    finally:
        ctx.close()
        logger.info("Closed Snowflake connection.")

if __name__ == "__main__":
    main()
