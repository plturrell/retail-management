import os
import json
import time
from pathlib import Path

from google import genai

# Configuration
IMAGES_DIR = "/Users/user/Documents/retailmanagement/images"
OUTPUT_DIR = "/Users/user/Documents/retailmanagement/ocr_outputs"

# System Prompt instructing Gemini precisely on how to perform the extraction
PROMPT = """You are an expert OCR and data-entry AI.
Analyze the provided image and extract all relevant text, forms, entities, and metadata.
Output your extraction strictly as a JSON object. Ensure tables are formatted as arrays of objects.
Do not wrap your result in markdown block quotes. Provide ONLY the raw JSON string."""

def get_mime_type(file_path):
    ext = file_path.suffix.lower()
    if ext == ".png": return "image/png"
    if ext in [".jpeg", ".jpg"]: return "image/jpeg"
    if ext == ".pdf": return "application/pdf"
    return "image/png"

def process_file(file_path: Path, client):
    print(f"Processing: {file_path.name}")
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        mime_type = get_mime_type(file_path)

        # Retry up to 3 times with exponential backoff for quota/rate errors
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        genai.types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                        PROMPT,
                    ],
                    config=genai.types.GenerateContentConfig(
                        response_mime_type="application/json",
                    ),
                )
                break
            except Exception as retry_err:
                if "429" in str(retry_err) and attempt < 2:
                    wait = (attempt + 1) * 30
                    print(f"  Rate limited. Waiting {wait}s before retry {attempt + 2}/3...")
                    time.sleep(wait)
                else:
                    raise

        raw_text = response.text

        # Save raw JSON
        out_file = Path(OUTPUT_DIR) / f"{file_path.stem}.json"
        with open(out_file, "w") as f:
            try:
               parsed = json.loads(raw_text)
               json.dump(parsed, f, indent=2)
            except json.JSONDecodeError:
               f.write(raw_text)

        print(f"  -> Saved output to {out_file.name}")

    except Exception as e:
        print(f"Error processing {file_path.name}: {e}")

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable not found!")
        print("")
        print("Get your key from your GCP project (project-b41c0c0d-6eea-4e9d-a78):")
        print("  https://console.cloud.google.com/apis/credentials?project=project-b41c0c0d-6eea-4e9d-a78")
        print("")
        print("Or from AI Studio: https://aistudio.google.com/app/apikey")
        print("")
        print("Then run: export GEMINI_API_KEY='your_key'")
        return

    try:
        client = genai.Client(api_key=api_key)
        print(f"Google GenAI client initialized. Target: {IMAGES_DIR}")
    except Exception as e:
        print(f"Could not initialize GenAI client. Error: {e}")
        return

    images_path = Path(IMAGES_DIR)

    # Process supported files
    for file_path in sorted(images_path.iterdir()):
        if file_path.is_file() and file_path.suffix.lower() in [".png", ".jpg", ".jpeg", ".pdf"]:
            process_file(file_path, client)
            time.sleep(2)  # small delay between files to avoid rate-limit burst

if __name__ == "__main__":
    main()
