import os
import re
import ast
import json
import base64
import requests
import argparse
import webbrowser
import urllib.parse
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Config ────────────────────────────────────────────────────────────────────
CATALOG_FILE      = "/Users/user/Documents/retailmanagement/mangle_facts/product_catalog.mangle"
POS_ORDERS_FILE   = "/Users/user/Documents/retailmanagement/mangle_facts/pos_orders.mangle"
IMAGES_DIR        = "/Users/user/Documents/retailmanagement/product_images"
SHOPIFY_SYNC_FILE = "/Users/user/Documents/retailmanagement/mangle_facts/shopify_sync.mangle"
AUTH_CACHE_FILE   = "/Users/user/Documents/retailmanagement/.shopify_auth.json"

SHOPIFY_API_VERSION = "2024-01"
LOCAL_PORT = 5000
REDIRECT_URI = f"http://localhost:{LOCAL_PORT}/auth/callback"

_auth_code = None

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def do_GET(self):
        global _auth_code
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path == '/auth/callback':
            qs = urllib.parse.parse_qs(parsed_url.query)
            if 'code' in qs:
                _auth_code = qs['code'][0]
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"<html><body><h1 style='color:green;'>Success!</h1><p>Authentication successful. You can close this window and return to your terminal.</p></body></html>")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"No code parameter found in callback.")

def perform_oauth_handshake(store, client_id, client_secret):
    global _auth_code
    _auth_code = None
    server = HTTPServer(('localhost', LOCAL_PORT), OAuthCallbackHandler)
    auth_url = f"https://{store}/admin/oauth/authorize?client_id={client_id}&scope=read_products,write_products&redirect_uri={REDIRECT_URI}"
    
    print("\n" + "="*60)
    print("  Shopify Partner App Authentication Required")
    print("="*60)
    print(f"I am attempting to open your browser to securely authorize:")
    print(f"URL: {auth_url}\n")
    
    webbrowser.open(auth_url)
    print("Waiting for you to click 'Install' in your browser...")
    
    while _auth_code is None:
        server.handle_request()
        
    print("Authorization code received! Exchanging for token...")
    exchange_url = f"https://{store}/admin/oauth/access_token"
    res = requests.post(exchange_url, json={"client_id": client_id, "client_secret": client_secret, "code": _auth_code})
    
    if res.status_code == 200:
        token = res.json().get('access_token')
        print("Success! Got permanent API Access Token.")
        cache = {}
        if os.path.exists(AUTH_CACHE_FILE):
            with open(AUTH_CACHE_FILE, 'r') as f: cache = json.load(f)
        cache[store] = {"access_token": token}
        with open(AUTH_CACHE_FILE, 'w') as f: json.dump(cache, f)
        return token
    else:
        print(f"Failed to exchange token: {res.text}")
        return None

def get_access_token(store, client_id, client_secret):
    store = store.replace("https://", "").replace("http://", "").strip("/")
    if os.path.exists(AUTH_CACHE_FILE):
        with open(AUTH_CACHE_FILE, 'r') as f:
            cache = json.load(f)
            if store in cache and "access_token" in cache[store]:
                print(f"Using cached authentication token for {store}")
                return cache[store]["access_token"], store
                
    if not client_id or not client_secret:
        return None, store
    return perform_oauth_handshake(store, client_id, client_secret)

# ── Processing logic ─────────────────────────────────────────────────────────

def get_shopify_headers(token): return {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
def get_shopify_url(store_url, endpoint): return f"https://{store_url}/admin/api/{SHOPIFY_API_VERSION}/{endpoint}"

def pull_from_shopify(store_url, token, dry_run=False):
    print("Pulling FULL Administrative catalog from Shopify...")
    
    headers = get_shopify_headers(token)
    url = get_shopify_url(store_url, "products.json?limit=250")
    
    all_products = []
    while url:
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            return print(f"Error accessing admin store: {resp.status_code} - {resp.text}")
            
        json_data = resp.json()
        fetched = json_data.get('products', [])
        all_products.extend(fetched)
        print(f"  ...Fetched chunk of {len(fetched)} products")
        
        # Check for pagination
        link_header = resp.headers.get('Link')
        url = None
        if link_header:
            links = link_header.split(',')
            for link in links:
                if 'rel="next"' in link:
                    url = link[link.find('<')+1 : link.find('>')]
                    
    print(f"Found {len(all_products)} total products on Shopify across all pages.")
    if dry_run: return print("[DRY RUN] Will not write local files.")

    os.makedirs(IMAGES_DIR, exist_ok=True)
    with open(SHOPIFY_SYNC_FILE, "w", encoding="utf-8") as f:
        f.write("# Shopify synchronized products (Full Admin Extraction)\n# Schema: shopify_product(id, sku, title, price, tags, image_filename).\n\n")
        for p in all_products:
            # Handle images (use first product image as fallback for all variants)
            image_filename = "none"
            if p.get('images') and len(p['images']) > 0 and p['images'][0].get('src'):
                clean_filename = p['images'][0]['src'].split('/')[-1].split('?')[0]
                image_filename = f"SHOPIFY_{clean_filename}"
                local_img_path = Path(IMAGES_DIR) / image_filename
                if not local_img_path.exists():
                    try:
                        print(f"Downloading {image_filename}...")
                        with open(local_img_path, 'wb') as img_f:
                            img_f.write(requests.get(p['images'][0]['src']).content)
                    except Exception as e:
                        pass
            
            title_clean = p.get("title", "").replace('"', '\\"') if p.get("title") else ""
            tags = ",".join(p.get("tags", [])) if isinstance(p.get("tags"), list) else p.get("tags", "")
            
            # Loop over every variant!
            variants = p.get('variants', [])
            if not variants:
                # Fallback if somehow literally 0 variants exist
                f.write(f'shopify_product("{p.get("id")}", "SHP-{p.get("id")}", "{title_clean}", 0.0, "{tags}", "{image_filename}").\n')
                
            for v in variants:
                v_sku = v.get('sku') or f"SHP-{v.get('id')}"
                v_price = v.get('price') or "0.0"
                # If variant has a specific title (like "Small" or "Blue"), append it to the main title
                v_title = title_clean
                if v.get('title') and v.get('title') != "Default Title":
                    v_title = f"{title_clean} - {v.get('title')}".replace('"', '\\"')
                    
                f.write(f'shopify_product("{p.get("id")}", "{v_sku}", "{v_title}", {v_price}, "{tags}", "{image_filename}").\n')

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pull", action="store_true", help="Migrate Shopify products DOWN to local App")
    parser.add_argument("--shop", type=str, required=True, help="Your Shopify Store URL")
    args = parser.parse_args()
        
    client_id = os.environ.get("SHOPIFY_CLIENT_ID")
    client_secret = os.environ.get("SHOPIFY_SECRET")
    
    if not client_id or not client_secret:
        print("ERROR: Missing Client ID and Secret in environment variables.")
        return
        
    token, pure_store = get_access_token(args.shop, client_id, client_secret)
    if not token:
        print("\nCould not obtain authentication.")
        return
        
    if args.pull: pull_from_shopify(pure_store, token)

if __name__ == "__main__":
    main()
