"""Repository-root-relative paths for pipeline CLIs."""

from pathlib import Path

_PIPELINES_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _PIPELINES_DIR.parent
REPO_ROOT = _TOOLS_DIR.parent

DATA_DIR = REPO_ROOT / "data"
CATALOG_DIR = DATA_DIR / "catalog"
PRODUCT_IMAGES_DIR = CATALOG_DIR / "product_images"
SOURCE_IMAGES_DIR = DATA_DIR / "images"
OCR_OUTPUTS_DIR = DATA_DIR / "ocr_outputs"
MANGLE_FACTS_DIR = DATA_DIR / "mangle_facts"
MANGLE_SOURCE_DIR = DATA_DIR / "mangle"  # checked-in .mangle query/analysis files
DOCS_DIR = REPO_ROOT / "docs"

EMBED_NPY_PATH = CATALOG_DIR / "product_embeddings.npy"
EMBED_INDEX_PATH = CATALOG_DIR / "product_embedding_index.json"
PRODUCT_CATALOG_MANGLE = MANGLE_FACTS_DIR / "product_catalog.mangle"
SHOPIFY_AUTH_FILE = REPO_ROOT / ".shopify_auth.json"

MG_BINARY = _TOOLS_DIR / "mangle" / "bin" / "mg"
