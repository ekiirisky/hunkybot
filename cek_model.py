from google import genai
import os

# --- GANTI API KEY ---
GEMINI_API_KEY = "AIzaSyBQgKMz6ZyWnYyN0xjEdWRefbpNsuRir4Q" 

client = genai.Client(api_key=GEMINI_API_KEY)

print("🔍 Sedang mencari model...")
print("-" * 30)

try:
    # Ambil semua model dan print namanya saja
    for m in client.models.list():
        # Kita print nama modelnya langsung
        print(f"✅ {m.name}")

    print("-" * 30)
    print("Pilihlah salah satu yang ada tulisan 'gemini' dan 'flash'.")

except Exception as e:
    print(f"❌ Error: {e}")