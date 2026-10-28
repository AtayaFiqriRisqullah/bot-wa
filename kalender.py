import time
from datetime import datetime, timedelta, timezone

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import CALENDAR_ID
from google_akses import muat_kunci

try:
    from config import TUGAS_KUNCI, TUGAS_URL
except ImportError:                # belum diisi di config.py: /todo tetap membuat acara
    TUGAS_KUNCI = TUGAS_URL = None

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


class TugasGagal(Exception):
    """Tugas Google Tasks tidak berhasil dibuat. Isi pesannya berupa alasan singkat."""


def tambah_tugas(judul, tanggal, catatan=''):
    """Buat tugas di Google Tasks dengan deadline pada `tanggal` (date).

    Google Tasks hanya menyimpan tanggal deadline, tanpa jam, jadi jamnya ditulis di
    `catatan`. Tugas dibuat lewat Apps Script milikmu sendiri (lihat tugas.gs), karena
    akun layanan bot tidak bisa menulis ke daftar tugas akun pribadi. Aman diulang:
    Apps Script melewati tugas yang judul dan tanggalnya sudah ada.
    """
    if not TUGAS_URL or not TUGAS_KUNCI:
        raise TugasGagal('TUGAS_URL dan TUGAS_KUNCI belum diisi di config.py')
    isi = {'kunci': TUGAS_KUNCI, 'judul': judul,
           'tanggal': tanggal.isoformat(), 'catatan': catatan}
    kegagalan = None
    for jeda in (0, 2, 4):                 # tiga percobaan kalau koneksi bermasalah
        time.sleep(jeda)
        try:
            r = requests.post(TUGAS_URL, json=isi, timeout=15)
        except (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema,
                requests.exceptions.InvalidSchema):
            raise TugasGagal('TUGAS_URL di config.py tidak valid')
        except requests.exceptions.RequestException as e:
            kegagalan = e
            continue
        try:
            hasil = r.json()
        except ValueError:
            raise TugasGagal('balasan Apps Script bukan JSON; pastikan akses deployment '
                             '"Anyone" dan URL-nya berakhiran /exec')
        if not isinstance(hasil, dict):
            raise TugasGagal('balasan Apps Script tidak dikenali')
        if not hasil.get('ok'):
            raise TugasGagal(str(hasil.get('galat', 'ditolak Apps Script')))
        return
    raise TugasGagal('koneksi ke Apps Script gagal (' + type(kegagalan).__name__ + ')')