import time
from datetime import datetime, timedelta, timezone

import httplib2
import requests
from google.auth.exceptions import TransportError
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

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

# Gangguan jaringan sesaat (koneksi di-reset, SSL putus di tengah jalan, timeout, dsb.).
# OSError mencakup ssl.SSLError, ConnectionError, dan timeout soket.
GAGAL_KALENDER = (OSError, httplib2.HttpLib2Error, TransportError)
JEDA_ULANG = (1, 2, 4)    # detik menunggu sebelum percobaan ke-2, ke-3, dan ke-4


def _layak_diulang(e):
    if isinstance(e, HttpError):               # error dari server Google: ulangi hanya kalau 5xx
        return e.resp.status in (500, 502, 503, 504)
    return True


def _coba(fungsi, sudah_masuk=None, cek_dulu=False):
    """Jalankan fungsi() (satu panggilan ke Google Calendar) dan ulangi kalau gagal karena jaringan.

    `sudah_masuk` dipakai untuk panggilan yang menulis: kalau koneksi putus setelah
    permintaan sampai ke Google, penulisan bisa saja sudah berhasil. Sebelum mengulang,
    sudah_masuk() dicek dulu; kalau True, penulisan dianggap selesai (tidak dobel).
    Dengan cek_dulu=True pengecekan itu dilakukan juga sebelum percobaan pertama, jadi
    perintah yang dikirim ulang pengguna tidak membuat acara kembar.
    """
    for percobaan, jeda in enumerate((0,) + JEDA_ULANG):
        time.sleep(jeda)
        if sudah_masuk is not None and (percobaan > 0 or cek_dulu):
            try:
                if sudah_masuk():
                    return None
            except (HttpError,) + GAGAL_KALENDER:
                pass                           # belum bisa memastikan; coba tulis lagi
        try:
            return fungsi()
        except (HttpError,) + GAGAL_KALENDER as e:
            if not _layak_diulang(e) or percobaan == len(JEDA_ULANG):
                raise
            print('[kalender] ' + type(e).__name__ + ', mengulang dalam ' +
                  str(JEDA_ULANG[percobaan]) + ' detik')


def _ada_acara(judul, awal, akhir, cocok):
    """True kalau di rentang waktu [awal, akhir) sudah ada acara berjudul `judul` yang
    waktu mulainya lolos fungsi cocok(start)."""
    hasil = _layanan.events().list(
        calendarId=CALENDAR_ID, timeMin=awal.isoformat(), timeMax=akhir.isoformat(),
        q=judul, singleEvents=True, maxResults=20).execute()
    return any(e.get('summary') == judul and cocok(e.get('start', {}))
               for e in hasil.get('items', []))


def tambah_event(judul, mulai):
    selesai = mulai + timedelta(hours=1)
    isi = {
        'summary': judul,
        'start': {'dateTime': mulai.isoformat(), 'timeZone': 'Asia/Jakarta'},
        'end': {'dateTime': selesai.isoformat(), 'timeZone': 'Asia/Jakarta'},
    }

    def sama_mulai(start):
        return bool(start.get('dateTime')) and datetime.fromisoformat(start['dateTime']) == mulai

    _coba(lambda: _layanan.events().insert(calendarId=CALENDAR_ID, body=isi).execute(),
          sudah_masuk=lambda: _ada_acara(judul, mulai - timedelta(minutes=1), selesai, sama_mulai),
          cek_dulu=True)


def tambah_penanda_deadline(judul, tanggal):
    """Acara seharian berwarna merah berjudul "Due: judul" pada `tanggal` (date).

    Ini acara kalender biasa yang meniru tampilan deadline di Google Tasks. Isian
    Deadline yang asli tidak bisa dibuat lewat API, dan Calendar API tidak punya jenis
    acara "tugas".
    """
    isi = {
        'summary': 'Due: ' + judul,
        'start': {'date': tanggal.isoformat()},
        'end': {'date': (tanggal + timedelta(days=1)).isoformat()},   # akhir acara seharian eksklusif
        'colorId': '11',                  # merah (Tomato)
        'transparency': 'transparent',    # tampil "free", tidak menandai waktu sibuk
    }
    awal_hari = datetime(tanggal.year, tanggal.month, tanggal.day, tzinfo=WIB)

    def sama_tanggal(start):
        return start.get('date') == tanggal.isoformat()

    _coba(lambda: _layanan.events().insert(calendarId=CALENDAR_ID, body=isi).execute(),
          sudah_masuk=lambda: _ada_acara(isi['summary'], awal_hari,
                                         awal_hari + timedelta(days=1), sama_tanggal),
          cek_dulu=True)


def event_hari_ini():
    awal = datetime.now(WIB).replace(hour=0, minute=0, second=0, microsecond=0)
    akhir = awal + timedelta(days=1)
    hasil = _coba(lambda: _layanan.events().list(
        calendarId=CALENDAR_ID, timeMin=awal.isoformat(), timeMax=akhir.isoformat(),
        singleEvents=True, orderBy='startTime').execute())
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