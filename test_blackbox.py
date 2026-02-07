import requests
import os
import json
from dotenv import load_dotenv

# Load file .env
load_dotenv()

def test_koneksi():
    print("🚀 Memulai Test Koneksi Blackbox...")

    # 1. Ambil Variabel
    url = os.getenv("BLACKBOX_API_URL")
    api_key = os.getenv("BLACKBOX_API_KEY")

    # Debugging: Cek apakah variabel terbaca
    if not url or not api_key:
        print("❌ ERROR: URL atau API Key tidak terbaca dari .env")
        print(f"   URL: {url}")
        print(f"   KEY: {api_key}")
        return

    # 2. Siapkan Header & Payload sesuai Dokumentasi
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = {
        "messages": [
            {
                "role": "user", 
                "content": "Halo Blackbox, apa kabar? Jawab singkat saja."
            }
        ],
        "model": "blackboxai/deepseek/deepseek-chat-v3.1", # Model default mereka
        "max_tokens": 100
    }

    try:
        # 3. Kirim Request
        print(f"📡 Menghubungi: {url}")
        response = requests.post(url, headers=headers, json=payload)

        # 4. Cek Hasil
        print(f"✅ Status Code: {response.status_code}")
        
        if response.status_code == 200:
            print("🎉 BERHASIL!")
            print("--- Respon Asli ---")
            print(response.text)
            
            # Coba parsing JSON kalau bisa
            try:
                data = response.json()
                print("\n--- Isi Pesan ---")
                # Struktur Blackbox biasanya mirip OpenAI atau langsung 'content'
                # Kita coba cari kontennya
                print(data) 
            except:
                print("Respon bukan JSON standar, tapi teks sudah diterima.")
        else:
            print("❌ GAGAL!")
            print(f"Error Message: {response.text}")

    except Exception as e:
        print(f"❌ ERROR SYSTEM: {e}")
if __name__ == "__main__":
    test_koneksi()