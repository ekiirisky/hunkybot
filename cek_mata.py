from google.oauth2 import service_account
from googleapiclient.discovery import build

# Masukkan ID FOLDER kamu (Cek lagi di URL Browser)
ID_YANG_MAU_DICEK = "15vLisIqTaBk74laFS" # <--- Pastikan ID ini benar

SERVICE_ACCOUNT_FILE = 'credentials.json'
SCOPES = ['https://www.googleapis.com/auth/drive']

def cek():
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        service = build('drive', 'v3', credentials=creds)
        
        # Coba ambil info folder
        folder = service.files().get(fileId=ID_YANG_MAU_DICEK, fields="id, name").execute()
        print(f"✅ SUKSES! Robot melihat folder: {folder.get('name')}")
        
    except Exception as e:
        print("❌ GAGAL. Pesan Error Asli:")
        print(e)
        print("\nSARAN:")
        if "404" in str(e):
            print("1. ID Folder SALAH/TIPO.")
            print("2. Atau Robot belum di-invite sebagai EDITOR di folder itu.")

cek()