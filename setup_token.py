import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Jika kamu mengubah scope, hapus file token.json dulu.
SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/drive']

def main():
    creds = None
    # File token.json menyimpan akses dan refresh tokens user.
    # File ini dibuat otomatis saat login pertama kali sukses.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # Jika tidak ada token valid, minta user login.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Simpan token untuk pemakaian selanjutnya
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            print("✅ BERHASIL! File 'token.json' sudah dibuat.")
            print("Sekarang kamu bisa jalankan app.py tanpa error kuota.")

if __name__ == '__main__':
    main()