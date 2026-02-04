import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Konfigurasi
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'credentials.json'

def cek_koneksi_calendar():
    try:
        creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=SCOPES)

        service = build('calendar', 'v3', credentials=creds)

        # Ambil waktu sekarang (format UTC)
        now = datetime.datetime.utcnow().isoformat() + 'Z' 
        
        print('Mengambil 5 event kalender mendatang...')
        
        # Request ke API Calendar (mengambil 'primary' calendar user)
        events_result = service.events().list(calendarId='primary', timeMin=now,
                                              maxResults=5, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])

        if not events:
            print('Koneksi Berhasil! Tapi tidak ada jadwal meeting mendatang.')
        else:
            print('Koneksi Berhasil! Ini jadwalmu:')
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                print(f"- {start}: {event['summary']}")

    except Exception as e:
        print(f"Terjadi error: {e}")

if __name__ == '__main__':
    cek_koneksi_calendar()