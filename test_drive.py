import os.path
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Konfigurasi
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'credentials.json'

def cek_koneksi_drive():
    creds = None
    
    # 1. Autentikasi menggunakan file JSON
    try:
        creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        
        # 2. Membangun layanan Drive
        service = build('drive', 'v3', credentials=creds)

        # 3. Mencoba mengambil daftar file (untuk tes)
        # Kita cari file di folder mana saja yang si Robot punya akses
        results = service.files().list(
            pageSize=10, fields="nextPageToken, files(id, name)").execute()
        items = results.get('files', [])

        if not items:
            print('Koneksi Berhasil! Tapi tidak ada file ditemukan.')
            print('Coba upload manual satu file ke folder "Upload Dari WA" untuk tes.')
        else:
            print('Koneksi Berhasil! Berikut file yang terlihat oleh Robot:')
            for item in items:
                print(f"- {item['name']} (ID: {item['id']})")

    except Exception as e:
        print(f"Terjadi error: {e}")

if __name__ == '__main__':
    cek_koneksi_drive()