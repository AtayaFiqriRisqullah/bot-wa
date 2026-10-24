from datetime import date, datetime, timedelta, timezone

import gspread
from gspread.exceptions import WorksheetNotFound
from gspread.utils import a1_to_rowcol

from config import SHEET_ID
from google_akses import muat_kunci

WIB = timezone(timedelta(hours=7))

# Nama tab bulan di spreadsheet. Harus sama persis dengan nama tab
# (di spreadsheetmu: Agustus, September, Oktober, dst).
BULAN = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli',
         'Agustus', 'September', 'Oktober', 'November', 'Desember']

# Posisi tabel pengeluaran di tab bulanan.
# Nama tabel -> (kolom nama barang, kolom nilai). Kolom Date ada di tengahnya.
KATEGORI = {
    'Jajan': ('B', 'D'),
    'Alat': ('G', 'I'),
    'Mingguan&Bulanan': ('K', 'M'),
    'Hiburan': ('P', 'R'),
}
BARIS_AWAL = 27     # baris data pertama (baris 26 = TOTAL)
BARIS_AKHIR = 500   # batas bawah saat membaca data

_akun = gspread.service_account_from_dict(muat_kunci())
_buku = _akun.open_by_key(SHEET_ID)


class TabTidakAda(Exception):
    """Dilempar kalau ada tab yang tidak ditemukan di spreadsheet."""


def sekarang():
    return datetime.now(WIB)


def _tanggal():
    return sekarang().strftime('%Y-%m-%d')


def _tab(nama):
    try:
        return _buku.worksheet(nama)
    except WorksheetNotFound:
        raise TabTidakAda(nama)


def _tab_bulan():
    """Tab untuk bulan berjalan, misalnya 'Oktober'."""
    return _tab(BULAN[sekarang().month - 1])


def _baris_kosong(ws, kolom):
    """Cari baris pertama yang masih kosong di kolom nama barang."""
    nomor_kolom = a1_to_rowcol(kolom + '1')[1]
    isi = ws.col_values(nomor_kolom)      # isi kolom; indeks 0 = baris 1
    baris = BARIS_AWAL
    while baris <= len(isi) and isi[baris - 1].strip() != '':
        baris += 1
    return baris


def simpan_pengeluaran(kategori, nama, nominal):
    """Tulis satu pengeluaran ke tabel kategori di tab bulan ini.

    Mengembalikan (nama tab, nomor baris) supaya bisa dilaporkan ke pengguna.
    """
    ws = _tab_bulan()
    kolom_awal, kolom_akhir = KATEGORI[kategori]
    baris = _baris_kosong(ws, kolom_awal)
    if nama and nama[0] in '=+-@':
        nama = "'" + nama     # cegah teks dibaca sebagai rumus
    # raw=False: tanggal '2026-10-13' dibaca Sheets sebagai tanggal asli,
    # dan formatnya mengikuti format sel (misalnya 13/10/2026).
    ws.update(range_name=f'{kolom_awal}{baris}:{kolom_akhir}{baris}',
              values=[[nama, _tanggal(), nominal]], raw=False)
    return ws.title, baris


def ambil_pengeluaran_hari_ini():
    """Daftar (kategori, nama barang, nilai) untuk hari ini dari semua tabel."""
    ws = _tab_bulan()
    rentang = [f'{a}{BARIS_AWAL}:{b}{BARIS_AKHIR}' for a, b in KATEGORI.values()]
    hasil = ws.batch_get(rentang, value_render_option='UNFORMATTED_VALUE')
    # Di Google Sheets, tanggal disimpan sebagai jumlah hari sejak 30/12/1899.
    hari_ini = (sekarang().date() - date(1899, 12, 30)).days
    daftar = []
    for kategori, blok in zip(KATEGORI, hasil):
        for baris in blok:
            nama, tgl, nilai = (list(baris) + ['', '', ''])[:3]
            try:
                if int(float(tgl)) == hari_ini:
                    daftar.append((kategori, str(nama), int(float(nilai))))
            except (TypeError, ValueError):
                continue      # baris kosong atau bukan tanggal
    return daftar

# Tempel potongan ini ke penyimpanan.py (di bawah simpan_pengeluaran).
# Diasumsikan penyimpanan.py memakai gspread. Kalau beda, kirim isi
# penyimpanan.py supaya bisa disesuaikan persis.
 
PEMASUKAN_BARIS_AWAL = 10    # baris 9 = "Sisa Bulanan", jangan ditimpa
PEMASUKAN_BARIS_AKHIR = 31   # batas rumus L11 (B10:B31)
 
 
class TabelPenuh(Exception):
    """Tabel Pemasukan sudah terisi sampai baris terakhir yang dihitung rumus."""
 
 
def simpan_pemasukan(sumber, nominal):
    """Isi baris kosong pertama di tabel Pemasukan (kolom B-D) pada tab bulan ini.
    Mengembalikan (nama_tab, nomor_baris)."""
 
    # GANTI baris ini dengan cara simpan_pengeluaran mengambil tab bulan ini
    # (fungsi/baris yang sama yang melempar TabTidakAda kalau tab belum ada).
    ws = simpan_pengeluaran()
 
    kolom_b = ws.col_values(2)   # isi kolom B (Source) dari baris 1; sel kosong = ''
    for baris in range(PEMASUKAN_BARIS_AWAL, PEMASUKAN_BARIS_AKHIR + 1):
        if baris > len(kolom_b) or not kolom_b[baris - 1].strip():
            break
    else:
        raise TabelPenuh()
 
    tanggal = sekarang().date().isoformat()   # contoh: 2026-10-24
    ws.update(range_name='B' + str(baris) + ':D' + str(baris),
              values=[[sumber, tanggal, nominal]],
              value_input_option='RAW')       # RAW: tanggal tetap teks, nominal tetap angka
    return ws.title, baris
