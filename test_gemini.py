import google.generativeai as genai
import os

# Masukkan API Key Gemini kamu di sini
GEMINI_API_KEY = "AIzaSyBQgKMz6ZyWnYyN0xjEdWRefbpNsuRir4Q" # <-- PASTE KODE API KEY KAMU DI SINI

# Konfigurasi Library
genai.configure(api_key=GEMINI_API_KEY)

def sapa_gemini():
    try:
        # Memilih model (gemini-1.5-flash adalah model yang cepat dan gratis/murah)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        print("Sedang mengirim pesan ke Gemini...")
        
        # Mengirim pesan
        response = model.generate_content("Halo, perkenalkan dirimu secara singkat sebagai asisten WhatsApp.")
        
        # Menampilkan jawaban
        print("\nJawaban Gemini:")
        print(response.text)
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    sapa_gemini()