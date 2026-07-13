"""
One-time script to upload existing trained model files to Supabase Storage.
Run this from the project root:
    python scripts/upload_models_to_storage.py --service-key YOUR_SERVICE_ROLE_KEY
"""
import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / "api" / ".env")

parser = argparse.ArgumentParser()
parser.add_argument("--service-key", required=True,
                    help="Supabase service_role key (bypasses RLS). "
                         "Find it at: Dashboard → Settings → API → service_role")
args = parser.parse_args()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = args.service_key  # Use service_role key to bypass RLS
STORAGE_BUCKET = "models"

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL must be set in api/.env")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Step 1: Create bucket if it doesn't exist ---
print("Creating storage bucket (safe to ignore 'already exists' errors)...")
try:
    sb.storage.create_bucket(
        STORAGE_BUCKET,
        options={"public": False, "file_size_limit": 524288000}
    )
    print(f"  Created bucket: '{STORAGE_BUCKET}'")
except Exception as e:
    err_str = str(e).lower()
    if "already exists" in err_str or "duplicate" in err_str:
        print(f"  Bucket '{STORAGE_BUCKET}' already exists — OK.")
    else:
        print(f"  Bucket creation note: {e} (continuing anyway...)")

# --- Step 2: Upload all .zip and .json files from saved_models ---
saved_models_dir = Path(__file__).resolve().parents[1] / "engine" / "saved_models"
files = list(saved_models_dir.glob("*.zip")) + list(saved_models_dir.glob("*.json"))

if not files:
    print(f"No model files found in {saved_models_dir}")
    sys.exit(0)

print(f"\nUploading {len(files)} file(s) from {saved_models_dir}...")
for filepath in files:
    filename = filepath.name
    print(f"  Uploading: {filename} ({filepath.stat().st_size / 1024:.1f} KB)...", end=" ")
    try:
        with open(filepath, "rb") as f:
            file_bytes = f.read()
        # Remove old version first
        try:
            sb.storage.from_(STORAGE_BUCKET).remove([filename])
        except Exception:
            pass
        sb.storage.from_(STORAGE_BUCKET).upload(
            path=filename,
            file=file_bytes,
            file_options={"content-type": "application/octet-stream"}
        )
        print("OK")
    except Exception as e:
        print(f"FAILED: {e}")

print("\nDone! All models are now in Supabase Storage.")
print("Render will download them automatically when you click Deploy Strategy.")
