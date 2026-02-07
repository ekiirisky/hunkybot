import requests
import os
from dotenv import load_dotenv

load_dotenv()

def cek_daftar_model():
    # Endpoint untuk melihat daftar model
    # Kita coba beberapa variasi URL karena dokumentasi kadang berubah
    urls_to_try = [
        "https://api.blackbox.ai/api/models",
        "https://api.blackbox.ai/v1/models"
    ]
    
    api_key = os.getenv("BLACKBOX_API_KEY")
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    print("🔍 Sedang mengecek daftar model...")

    for url in urls_to_try:
        try:
            print(f"👉 Mencoba URL: {url}")
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                print("✅ BERHASIL! Daftar Model ditemukan:")
                data = response.json()
                print(data)
                return # Berhenti jika sudah ketemu
            else:
                print(f"❌ Gagal di URL ini ({response.status_code})")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    cek_daftar_model()