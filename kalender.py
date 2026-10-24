from datetime import datetime, timedelta, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import CALENDAR_ID
from google_akses import muat_kunci

WIB = timezone(timedelta(hours=7))
_cred = service_account.Credentials.from_service_account_info(
    muat_kunci(), scopes=['https://www.googleapis.com/auth/calendar'])
_layanan = build('calendar', 'v3', credentials=_cred)


def tambah_event(judul, mulai):
    selesai = mulai + timedelta(hours=1)
    isi = {
        'summary': judul,
        'start': {'dateTime': mulai.isoformat(), 'timeZone': 'Asia/Jakarta'},
        'end': {'dateTime': selesai.isoformat(), 'timeZone': 'Asia/Jakarta'},
    }
    _layanan.events().insert(calendarId=CALENDAR_ID, body=isi).execute()


def event_hari_ini():
    awal = datetime.now(WIB).replace(hour=0, minute=0, second=0, microsecond=0)
    akhir = awal + timedelta(days=1)
    hasil = _layanan.events().list(
        calendarId=CALENDAR_ID, timeMin=awal.isoformat(), timeMax=akhir.isoformat(),
        singleEvents=True, orderBy='startTime').execute()
    daftar = []
    for e in hasil.get('items', []):
        mulai = e['start'].get('dateTime')
        jam = mulai[11:16] if mulai else 'seharian'
        daftar.append((jam, e.get('summary', '(tanpa judul)')))
    return daftar