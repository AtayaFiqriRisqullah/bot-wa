"""Catatan cepat ke Google Docs.

Setiap catatan ditambahkan di akhir dokumen sebagai satu blok berstempel waktu:

    27/10/2026 23:51 — isi catatan
      baris lanjutan (kalau catatannya beberapa baris)

Dokumennya harus dibagikan ke akun layanan bot sebagai Editor, dan Google Docs API
harus aktif di proyek Google Cloud yang sama dengan Sheets dan Calendar.
"""
import re
import time

import httplib2
from google.auth.exceptions import TransportError
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google_akses import muat_kunci

try:
    from config import CATATAN_DOC_ID
except ImportError:                # belum diisi di config.py
    CATATAN_DOC_ID = None

MAKS_CATATAN = 5000                # karakter per catatan
POLA_ENTRI = re.compile(r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2} — ')

_cred = service_account.Credentials.from_service_account_info(
    muat_kunci(), scopes=['https://www.googleapis.com/auth/documents'])
_layanan = build('docs', 'v1', credentials=_cred)

# Gangguan jaringan sesaat (koneksi di-reset, SSL putus di tengah jalan, timeout, dsb.).
GAGAL_CATATAN = (OSError, httplib2.HttpLib2Error, TransportError)
JEDA_ULANG = (1, 2, 4)    # detik menunggu sebelum percobaan ke-2, ke-3, dan ke-4


class CatatanGagal(Exception):
    """Catatan tidak bisa disimpan atau dibaca. Isi pesannya berupa alasan yang jelas."""


def _layak_diulang(e):
    if isinstance(e, HttpError):               # error dari server Google: ulangi hanya kalau 5xx
        return e.resp.status in (500, 502, 503, 504)
    return True


def _coba(fungsi, sudah_masuk=None):
    """Jalankan fungsi() (satu panggilan ke Google Docs) dan ulangi kalau gagal karena jaringan.

    `sudah_masuk` dipakai untuk penulisan: kalau koneksi putus setelah permintaan sampai
    ke Google, penulisan bisa saja sudah berhasil. Sebelum mengulang, sudah_masuk() dicek
    dulu; kalau True, penulisan dianggap selesai (catatan tidak dobel).
    """
    for percobaan, jeda in enumerate((0,) + JEDA_ULANG):
        time.sleep(jeda)
        if percobaan > 0 and sudah_masuk is not None:
            try:
                if sudah_masuk():
                    return None
            except (HttpError,) + GAGAL_CATATAN:
                pass                           # belum bisa memastikan; coba tulis lagi
        try:
            return fungsi()
        except (HttpError,) + GAGAL_CATATAN as e:
            if not _layak_diulang(e) or percobaan == len(JEDA_ULANG):
                raise
            print('[catatan] ' + type(e).__name__ + ', mengulang dalam ' +
                  str(JEDA_ULANG[percobaan]) + ' detik')


def _alasan_http(e):
    """HttpError yang tidak layak diulang -> alasan yang mudah dipahami, atau None."""
    status = e.resp.status
    pesan = str(e).lower()
    if status == 403 and ('has not been used' in pesan or 'disabled' in pesan
                          or 'accessnotconfigured' in pesan):
        return ('Google Docs API belum diaktifkan di proyek Google Cloud '
                '(APIs & Services > Library > Google Docs API > Enable)')
    if status == 403:
        return 'akun layanan bot belum menjadi Editor di dokumen itu; bagikan dokumennya ke emailnya'
    if status == 404:
        return ('dokumen tidak ditemukan; cek CATATAN_DOC_ID di config.py dan pastikan '
                'dokumennya dibagikan ke akun layanan bot')
    return None


def _panggil(fungsi, sudah_masuk=None):
    if not CATATAN_DOC_ID:
        raise CatatanGagal('CATATAN_DOC_ID belum diisi di config.py')
    try:
        return _coba(fungsi, sudah_masuk)
    except HttpError as e:
        alasan = _alasan_http(e)
        if alasan:
            raise CatatanGagal(alasan) from e
        raise


def _baca_paragraf():
    """Teks tiap paragraf dokumen, berurutan (tanpa karakter baris baru di ujung)."""
    dokumen = _layanan.documents().get(
        documentId=CATATAN_DOC_ID,
        fields='body(content(paragraph(elements(textRun(content)))))').execute()
    hasil = []
    for bagian in dokumen.get('body', {}).get('content', []):
        paragraf = bagian.get('paragraph')
        if not paragraf:
            continue                           # tabel, pemisah bagian, dsb.
        teks = ''.join(e.get('textRun', {}).get('content', '')
                       for e in paragraf.get('elements', []))
        hasil.append(teks.rstrip('\n'))
    return hasil


def tambah_catatan(teks, waktu):
    """Tambahkan catatan di akhir dokumen. `waktu` = datetime (WIB) untuk stempel waktunya."""
    baris = [b.strip() for b in teks.strip().splitlines() if b.strip()]
    if not baris:
        raise CatatanGagal('catatannya kosong')
    blok = ([waktu.strftime('%d/%m/%Y %H:%M') + ' — ' + baris[0]] +
            ['  ' + b for b in baris[1:]])
    # Teks diawali baris baru dan tanpa baris baru di ujung: insertText di akhir dokumen
    # menyisip sebelum paragraf terakhir, jadi catatan jadi paragraf baru dan tidak
    # menempel ke judul atau catatan sebelumnya.
    isi = {'requests': [{'insertText': {'endOfSegmentLocation': {'segmentId': ''},
                                        'text': '\n' + '\n'.join(blok)}}]}

    def sudah_masuk():
        paragraf = _baca_paragraf()
        ekor = paragraf[-(len(blok) + 3):]
        return any(ekor[i:i + len(blok)] == blok for i in range(len(ekor) - len(blok) + 1))

    _panggil(lambda: _layanan.documents().batchUpdate(
        documentId=CATATAN_DOC_ID, body=isi).execute(), sudah_masuk)


def ambil_entri():
    """Semua catatan di dokumen, dari yang paling lama: ['27/10/2026 23:51 — isi', ...].
    Baris yang bukan catatan (misalnya judul dokumen di atas catatan pertama) dilewati;
    baris lanjutan menempel ke catatan sebelumnya."""
    entri = []
    for paragraf in _panggil(_baca_paragraf):
        if POLA_ENTRI.match(paragraf):
            entri.append(paragraf)
        elif entri and paragraf.strip():
            entri[-1] += '\n' + paragraf.strip()
    return entri