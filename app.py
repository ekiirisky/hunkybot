from flask import Flask, request, jsonify
from google import genai
from google.oauth2.credentials import Credentials  # <--- Ganti import ini
from google.auth.transport.requests import Request # <--- Tambah ini
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv # <--- Import baru
import datetime
import json
import os

# ================= K O N F I G U R A S I =================

# 1. API KEYS & IDs (WAJIB DIISI)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PARENT_FOLDER_ID = os.getenv("PARENT_FOLDER_ID")
ID_KALENDER_KAMU = os.getenv("ID_KALENDER_KAMU")

# Daftar Panggil Hunky (Termasuk ID unik yang tadi kamu temukan)
BOT_TRIGGERS = [
    "hunky", "@hunky", "bot", "ai", 
    "@628816883610",    # Nomor Bot
    "@262779135115377" # ID Unik Grup
]

# Config Google Service
SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/drive']

# Inisialisasi
client = genai.Client(api_key=GEMINI_API_KEY)
app = Flask(__name__)

# ================= F U N G S I   B A N T U A N =================

def get_google_service(service_name, version):
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return build(service_name, version, credentials=creds)
    except Exception as e:
        print(f"❌ Error connect Google: {e}")
        return None

# --- 1. FUNGSI UPLOAD DRIVE ---
def get_google_service(service_name, version):
    """
    Koneksi menggunakan OAuth User (token.json)
    Agar tidak kena limit storage quota 0 bytes.
    """
    creds = None
    try:
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
        # Refresh token otomatis jika expired
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                print("❌ Token kadaluarsa dan tidak bisa di-refresh. Jalankan setup_token.py lagi.")
                return None

        return build(service_name, version, credentials=creds)

    except Exception as e:
        print(f"❌ Error connect Google: {e}")
        return None
    
def upload_ke_drive(file_path, mime_type):
    service = get_google_service('drive', 'v3')
    if not service: return "Gagal koneksi Drive."

    try:
        nama_file = os.path.basename(file_path)
        print(f"⬆️ Sedang upload {nama_file} ke Drive...")

        file_metadata = {
            'name': nama_file,
            'parents': [PARENT_FOLDER_ID]
        }
        
        media = MediaFileUpload(file_path, mimetype=mime_type)
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        # Hapus file sementara di laptop
        if os.path.exists(file_path):
            os.remove(file_path)
        
        return f"✅ Beres Bos! File berhasil diamankan di Drive.\n📂 Link: {file.get('webViewLink')}"

    except Exception as e:
        return f"Gagal upload ke Drive: {e}"

# --- 2. FUNGSI CALENDAR ---
def tambah_jadwal_calendar(judul, waktu_str):
    print(f"🗓️ Hunky mencoba membuat jadwal: {judul} pada {waktu_str}")
    
    service = get_google_service('calendar', 'v3')
    if not service: return "Gagal connect ke Google Calendar."

    try:
        start_time = datetime.datetime.strptime(waktu_str, "%Y-%m-%d %H:%M")
        end_time = start_time + datetime.timedelta(hours=1)

        event = {
            'summary': judul,
            'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Asia/Jakarta'},
            'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Asia/Jakarta'},
        }

        # Masukkan ke email pribadimu
        service.events().insert(calendarId=ID_KALENDER_KAMU, body=event).execute()
        return f"✅ Siap! Jadwal '{judul}' sudah Hunky catat untuk {waktu_str}."
    except Exception as e:
        return f"Gagal simpan ke kalender. Error: {e}"

# --- 3. FUNGSI OTAK GEMINI ---
def tanya_gemini(pesan_user):
    sekarang = datetime.datetime.now()
    info_waktu = sekarang.strftime("%A, %Y-%m-%d %H:%M")

    # Knowledge Base 2026
    data_penting_2026 = """
    DAFTAR HARI PENTING 2026:
    - Awal Puasa (1 Ramadhan 1447 H): ~18 Februari 2026.
    - Idul Fitri (1 Syawal 1447 H): ~20 Maret 2026.
    - Idul Adha (10 Dzulhijjah 1447 H): ~27 Mei 2026.
    - Tahun Baru Islam: ~16 Juni 2026.
    - HUT RI: 17 Agustus 2026.
    """

    system_instruction = f"""
    Namamu adalah HUNKY. Asisten pribadi yang cerdas, ramah, dan sigap.
    
    WAKTU SAAT INI: {info_waktu}
    INFO TAMBAHAN: {data_penting_2026}

    ATURAN:
    1. Jika diminta jadwal, output JSON: {{"action": "calendar", "title": "...", "time": "YYYY-MM-DD HH:MM"}}
    2. Jika user kirim file/gambar, itu akan ditangani sistem lain, kamu cukup komentar "File sudah saya terima".
    3. Jawab sopan dan santai.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash-lite',
            contents=f"{system_instruction}\n\nUser: {pesan_user}"
        )
        return response.text
    except Exception as e:
        return f"Error AI: {str(e)}"

# ================= R O U T E   U T A M A =================

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    sender = data.get('sender')
    message = data.get('message')
    file_path = data.get('file_path') # Menangkap data file
    mime_type = data.get('mime_type')

    print(f"\n📩 Pesan dari {sender}: {message}")
    if file_path: print(f"📎 Ada lampiran file: {file_path}")

    # --- A. LOGIKA UPLOAD (PRIORITAS UTAMA) ---
    if file_path:
        balasan = upload_ke_drive(file_path, mime_type)
        return jsonify({"reply": balasan})

    # --- B. LOGIKA FILTER TEXT ---
    is_group = "@g.us" in sender
    should_respond = False
    
    if not is_group:
        should_respond = True
        print("   -> Chat Personal")
    elif is_group:
        # Cek trigger
        if any(trigger in str(message).lower() for trigger in BOT_TRIGGERS):
            should_respond = True
            print("   -> ✅ Terpanggil di Grup!")
        else:
            print("   -> ❌ Diabaikan")
    
    if not should_respond:
        return jsonify({"status": "ignored"})

    # --- C. PROSES AI & CALENDAR ---
    if not message: message = "Halo Hunky" # Jaga-jaga pesan kosong

    # 1. Tanya Gemini
    jawaban_ai = tanya_gemini(message)
    balasan_final = jawaban_ai

    # 2. Cek JSON Calendar
    clean_json = jawaban_ai.replace("```json", "").replace("```", "").strip()
    if '{"action": "calendar"' in clean_json:
        try:
            data_cal = json.loads(clean_json)
            balasan_final = tambah_jadwal_calendar(data_cal.get('title'), data_cal.get('time'))
        except:
            balasan_final = "Hunky bingung format tanggalnya. Coba ulangi lagi."

    return jsonify({"reply": balasan_final})

if __name__ == "__main__":
    app.run(port=5000, debug=True)