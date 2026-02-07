from flask import Flask, request, jsonify
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from duckduckgo_search import DDGS
import requests
import json
import os
import re
import ast

# ================= K O N F I G U R A S I =================

load_dotenv()
BLACKBOX_API_URL = os.getenv("BLACKBOX_API_URL")
BLACKBOX_API_KEY = os.getenv("BLACKBOX_API_KEY")
PARENT_FOLDER_ID = os.getenv("PARENT_FOLDER_ID") # Pastikan ID di .env sudah benar!
ID_KALENDER_KAMU = os.getenv("ID_KALENDER_KAMU")
DB_FILE = 'jadwal_meeting.json'

BOT_TRIGGERS = [
    "hunky", "@hunky", "bot", "ai", 
    "@628816883610", "@262779135115377", 
    "tolong", "catat", "cari", "simpan", "ingatkan", "jadwal", "meeting"
]

SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/drive']

app = Flask(__name__)

# ================= F U N G S I   H E L P E R =================

def get_google_service(service_name, version):
    creds = None
    try:
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else: return None
        return build(service_name, version, credentials=creds)
    except: return None

def format_tanggal_indo(tgl_str):
    try:
        dt = datetime.strptime(tgl_str, "%Y-%m-%d")
        days = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
        months = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
        return f"{days[dt.weekday()]}, {dt.day} {months[dt.month]} {dt.year}"
    except: return tgl_str

# --- FITUR 1: WEB SEARCH ---
def cari_di_internet(query):
    print(f"🌍 Searching: {query}...")
    try:
        results = DDGS().text(query, max_results=3)
        if not results: return "Tidak ada info terkini."
        summary = ""
        for res in results:
            summary += f"- {res['title']}: {res['body']}\n"
        return summary
    except Exception as e: return f"Gagal searching: {e}"

# --- FITUR 2: UPLOAD DRIVE (RESTRICTED TO FOLDER) ---
def upload_ke_drive(file_path, mime_type, custom_name=None):
    service = get_google_service('drive', 'v3')
    if not service: return "❌ Gagal koneksi Drive."
    try:
        final_name = os.path.basename(file_path)
        if custom_name:
            clean_name = "".join([c for c in custom_name if c.isalnum() or c in (' ', '-', '_')]).strip()
            ext = os.path.splitext(file_path)[1]
            if not clean_name.endswith(ext): clean_name += ext
            final_name = clean_name

        # Upload Spesifik ke PARENT_FOLDER_ID
        file_metadata = {'name': final_name, 'parents': [PARENT_FOLDER_ID]}
        media = MediaFileUpload(file_path, mimetype=mime_type)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        
        if os.path.exists(file_path): os.remove(file_path)
        return f"✅ **File Disimpan!**\n📂 {final_name}\n🔗 {file.get('webViewLink')}"
    except Exception as e: return f"❌ Gagal upload: {e}"

# --- FITUR 3: CARI FILE (RESTRICTED TO FOLDER) ---
def cari_file_di_drive(keyword):
    service = get_google_service('drive', 'v3')
    if not service: return "❌ Gagal koneksi Drive."
    try:
        # QUERY DIPERKETAT: Hanya cari di dalam folder PARENT_FOLDER_ID
        query = f"name contains '{keyword}' and '{PARENT_FOLDER_ID}' in parents and trashed = false"
        
        results = service.files().list(q=query, pageSize=5, fields="files(name, webViewLink)", orderBy="createdTime desc").execute()
        items = results.get('files', [])
        
        if not items: return f"⚠️ File *'{keyword}'* tidak ditemukan di dalam Folder Kerja Hunky."
        
        balasan = f"📂 **Hasil Pencarian '{keyword}':**\n"
        for item in items:
            balasan += f"\n📄 {item['name']}\n🔗 {item['webViewLink']}\n"
        return balasan
    except Exception as e: return f"❌ Error cari file: {e}"

def kelola_database_jadwal(aksi, data_baru=None):
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, 'w') as f: json.dump([], f)
    with open(DB_FILE, 'r') as f:
        try: jadwal_list = json.load(f)
        except: jadwal_list = []

    if aksi == "tambah" and data_baru:
        jadwal_list.append(data_baru)
        jadwal_list.sort(key=lambda x: (x.get('Date', '9999-12-31'), x.get('Time', '23:59')))
        with open(DB_FILE, 'w') as f: json.dump(jadwal_list, f, indent=4)
        return jadwal_list
    elif aksi == "lihat":
        jadwal_list.sort(key=lambda x: (x.get('Date', '9999-12-31'), x.get('Time', '23:59')))
        return jadwal_list
    elif aksi == "reset":
        with open(DB_FILE, 'w') as f: json.dump([], f)
        return []

# ================= S C H E D U L E R =================

def cek_reminder_otomatis():
    waktu_sekarang = datetime.now(timezone.utc) + timedelta(hours=7)
    jadwal_list = kelola_database_jadwal("lihat")
    updated_list = []
    perlu_simpan = False

    for item in jadwal_list:
        if item.get('reminded', False):
            updated_list.append(item)
            continue
        try:
            tgl = item.get('Date')
            jam = item.get('Time')
            if not tgl or not jam: 
                updated_list.append(item)
                continue
            jam = jam.replace('.', ':')
            waktu_meeting = datetime.strptime(f"{tgl} {jam}", "%Y-%m-%d %H:%M")
            selisih = waktu_meeting - waktu_sekarang.replace(tzinfo=None)
            menit_sisa = selisih.total_seconds() / 60

            if 0 < menit_sisa <= 5:
                print(f"\n🔔 REMINDER: {item.get('Topic')}")
                target = item.get('GroupId')
                if target:
                    pesan = f"⏰ *REMINDER MEETING {int(menit_sisa)} MENIT LAGI!*\n📝 {item.get('Topic')}\n🔗 {item.get('Link')}"
                    try: requests.post("http://127.0.0.1:3000/send-message", json={"target_id": target, "message": pesan})
                    except: pass
                item['reminded'] = True
                perlu_simpan = True
        except: pass
        updated_list.append(item)

    if perlu_simpan:
        with open(DB_FILE, 'w') as f: json.dump(updated_list, f, indent=4)

scheduler = BackgroundScheduler()
scheduler.add_job(func=cek_reminder_otomatis, trigger="interval", minutes=1)
scheduler.start()

# ================= O T A K   A I =================

def tanya_blackbox(pesan_user, konteks_tambahan=""):
    waktu_sekarang = datetime.now(timezone.utc) + timedelta(hours=7)
    info_waktu = waktu_sekarang.strftime("%A, %Y-%m-%d Jam %H:%M WIB")
    
    jadwal_str = json.dumps(kelola_database_jadwal("lihat"), indent=2)

    system_instruction = f"""
    Kamu adalah HUNKY, asisten AI.
    INFO: Waktu {info_waktu}.
    DATABASE MEETING: {jadwal_str}
    KONTEKS TAMBAHAN: {konteks_tambahan}
    
    ATURAN: JSON DOUBLE QUOTES UNTUK AKSI.
    TUGAS:
    1. NOTE MEETING -> JSON {{"action": "save_meeting", "data": {{...}}}}
    2. CARI FILE -> JSON {{"action": "search_file", "keyword": "..."}}
    3. CARI INTERNET -> JSON {{"action": "web_search", "keyword": "..."}}
    4. LIHAT JADWAL -> JSON {{"action": "search_meeting", "date": "YYYY-MM-DD"}}
    5. CHAT BIASA -> Teks biasa.
    """

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BLACKBOX_API_KEY}"
    }
    
    # Model yang sudah kamu konfirmasi valid
    MODEL_VALID = "blackboxai/deepseek/deepseek-chat-v3.1" 

    payload = {
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": pesan_user}
        ],
        "model": MODEL_VALID, 
        "clickedAnswer2": False, 
        "clickedAnswer3": False
    }

    try:
        response = requests.post(BLACKBOX_API_URL, headers=headers, json=payload)
        if response.status_code == 200:
            hasil = response.json()
            return hasil.get('choices', [{}])[0].get('message', {}).get('content', '') or hasil.get('response', '') or str(hasil)
        return f"Error API Blackbox: {response.status_code} - {response.text}"
    except Exception as e: return f"Error Koneksi: {e}"

# ================= R O U T E   U T A M A =================

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    sender = data.get('sender')
    message = data.get('message') or ""
    file_path = data.get('file_path')
    mime_type = data.get('mime_type')
    
    print(f"\n📩 Pesan: {message} | Sender: {sender} | File: {file_path}")

    is_group = "@g.us" in sender
    is_triggered = not is_group
    if is_group:
        for t in BOT_TRIGGERS:
            if t.lower() in message.lower():
                is_triggered = True; break
    
    # LOGIKA FILE
    if file_path:
        msg_lower = message.lower()
        keyword_simpan = any(w in msg_lower for w in ["simpan", "upload", "taruh"])
        
        if is_triggered and keyword_simpan:
            nama_file = message.replace("@hunky","").replace("simpan","").strip() or "File Upload"
            balasan = upload_ke_drive(file_path, mime_type, custom_name=nama_file)
            return jsonify({"reply": balasan})
        else:
            if os.path.exists(file_path): os.remove(file_path)
            return jsonify({"status": "ignored_file"})

    # LOGIKA TEXT
    if not is_triggered: return jsonify({"status": "ignored_text"})

    konteks_internet = "" 
    jawaban_ai = tanya_blackbox(message, konteks_internet)
    balasan_final = jawaban_ai 
    
    match = re.search(r'\{.*\}', jawaban_ai, re.DOTALL)
    if match:
        try:
            json_str = match.group(0)
            data_json = json.loads(json_str)
            action = data_json.get('action')
            
            if action == 'save_meeting':
                meeting_data = data_json.get('data')
                meeting_data['GroupId'] = sender
                meeting_data['reminded'] = False
                kelola_database_jadwal("tambah", meeting_data)
                
                jadwal_terbaru = kelola_database_jadwal("lihat")
                balasan_final = "✅ **Jadwal Meeting Tersimpan!**\n\n**Jadwal Meeting**"
                current_date = ""
                for item in jadwal_terbaru:
                    item_date = item.get('Date', '-')
                    if item_date != current_date:
                        balasan_final += f"\n\n**{format_tanggal_indo(item_date)}**\n"
                        current_date = item_date
                    balasan_final += f"\nTime : {item.get('Time')} WIB"
                    balasan_final += f"\nTopic : {item.get('Topic')}"
                    balasan_final += f"\nTempat : {item.get('Location')}"
                    balasan_final += f"\nLink : {item.get('Link')}\n"

            elif action == 'search_meeting':
                target_date = data_json.get('date') 
                all_jadwal = kelola_database_jadwal("lihat")
                hasil_filter = [m for m in all_jadwal if m.get('Date') == target_date]
                
                if not hasil_filter:
                    balasan_final = f"📅 Tidak ada jadwal meeting pada **{format_tanggal_indo(target_date)}**."
                else:
                    balasan_final = f"📅 **Jadwal Meeting: {format_tanggal_indo(target_date)}**\n"
                    for item in hasil_filter:
                        balasan_final += f"\n🕒 {item.get('Time')} WIB"
                        balasan_final += f"\n📝 {item.get('Topic')}"
                        balasan_final += f"\n📍 {item.get('Location', '-')}"
                        balasan_final += f"\n🔗 {item.get('Link', '-')}\n"

            elif action == 'search_file':
                balasan_final = cari_file_di_drive(data_json.get('keyword'))

            elif action == 'web_search':
                keyword = data_json.get('keyword')
                hasil_cari = cari_di_internet(keyword)
                balasan_final = tanya_blackbox(f"User tanya: {message}", f"Fakta Internet: {hasil_cari}")

            elif action == 'reset_schedule':
                kelola_database_jadwal("reset")
                balasan_final = "🗑️ Database Direset."

        except Exception as e: print(f"Error Action: {e}")

    return jsonify({"reply": balasan_final})

if __name__ == "__main__":
    app.run(port=5000, debug=True)