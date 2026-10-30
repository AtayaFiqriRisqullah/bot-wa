import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

import gspread
import requests
from google.auth.exceptions import TransportError
from gspread.exceptions import APIError, WorksheetNotFound
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
BARIS_AWAL = 36     # baris data pertama tabel pengeluaran (baris 35 = TOTAL)
BARIS_AKHIR = 500   # batas bawah saat membaca data
BARIS_TOTAL = BARIS_AWAL - 1   # baris TOTAL tiap tabel pengeluaran, dibaca oleh /rekap

# Tabel Pemasukan (kolom B-D: Source/Date/Nilai).
PEMASUKAN_BARIS_AWAL = 10    # baris 9 = "Sisa Bulanan", jangan ditimpa
PEMASUKAN_BARIS_AKHIR = 31   # batas rumus saldo BNI (B10:B31)

# Tabel Pemasukan Bank (kolom T-V: Source/Date/Nilai).
PEMASUKAN_BANK_BARIS_AWAL = 10
PEMASUKAN_BANK_BARIS_AKHIR = 31

# Dua blok angka yang dibaca /saldo: label di kolom kiri, nilai di kolom kanan.
# Kalau tabelnya bergeser, cukup ubah dua baris ini.
RENTANG_HASIL_AKHIR = 'G9:H12'   # Pemasukan, Pengeluaran, Sisa Uang
RENTANG_SALDO_BANK = 'K9:L12'    # Total, BNI, Mandiri

# Riwayat catatan untuk /undo. Disimpan di file supaya tetap ada
# walaupun bot dimatikan, dan hanya menyimpan RIWAYAT_MAKS catatan terakhir.
RIWAYAT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'riwayat.json')
RIWAYAT_MAKS = 20

# Status kecil yang harus selamat dari restart bot. Sekarang isinya tanggal terakhir
# pengingat "belum catat pengeluaran" dicek, supaya tidak terkirim dua kali sehari.
STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'status.json')

# Pengaturan yang diubah lewat chat (daftar pintasan dan batas bulanan per kategori).
PENGATURAN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pengaturan.json')

# Daftar /deadline beserta tingkat pengingat yang sudah terkirim untuk masing-masing.
DEADLINE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deadline.json')

# Gangguan jaringan sesaat: koneksi di-reset, sinyal HP pindah, timeout, dan sejenisnya.
# Panggilan ke Google yang gagal karena ini aman diulang, sebab semua panggilan di file
# ini idempotent (membaca, menulis ke rentang yang sama persis, atau mengosongkan rentang),
# jadi mengulangnya tidak membuat catatan dobel.
GAGAL_JARINGAN = (TransportError, requests.exceptions.RequestException,
                  ConnectionError, TimeoutError)
JEDA_ULANG = (1, 2, 4)    # detik menunggu sebelum percobaan ke-2, ke-3, dan ke-4


def _layak_diulang(e):
    if isinstance(e, APIError):               # error dari server Google: ulangi hanya kalau 5xx
        return e.response.status_code in (500, 502, 503, 504)
    return isinstance(e, GAGAL_JARINGAN)


def _coba(fungsi, *args, **kwargs):
    """Jalankan satu panggilan ke Google; kalau gagal karena jaringan, ulangi."""
    for jeda in JEDA_ULANG:
        try:
            return fungsi(*args, **kwargs)
        except (APIError,) + GAGAL_JARINGAN as e:
            if not _layak_diulang(e):
                raise
            print('[jaringan] ' + type(e).__name__ + ', mengulang dalam ' + str(jeda) + ' detik')
            time.sleep(jeda)
    return fungsi(*args, **kwargs)            # percobaan terakhir: kalau gagal lagi, errornya naik


class _WsAman:
    """Pembungkus worksheet: setiap panggilan ke Google (col_values, update, get, ...)
    otomatis lewat _coba. Atribut biasa seperti .title diteruskan apa adanya."""

    def __init__(self, ws):
        self._ws = ws

    def __getattr__(self, nama):
        atribut = getattr(self._ws, nama)
        if not callable(atribut):
            return atribut

        def panggil(*args, **kwargs):
            return _coba(atribut, *args, **kwargs)
        return panggil


_akun = gspread.service_account_from_dict(muat_kunci())
_buku = _coba(_akun.open_by_key, SHEET_ID)
_kunci_riwayat = threading.Lock()
_kunci_status = threading.Lock()
_kunci_pengaturan = threading.Lock()
_kunci_deadline = threading.Lock()


class TabTidakAda(Exception):
    """Dilempar kalau ada tab yang tidak ditemukan di spreadsheet."""


class TabelPenuh(Exception):
    """Dilempar kalau sebuah tabel sudah terisi sampai baris terakhir yang dihitung rumus.
    Isi pesannya adalah nama tabelnya, misalnya 'Pemasukan'."""


class RiwayatBerubah(Exception):
    """Dilempar kalau isi sel sudah tidak sama dengan yang ditulis bot,
    jadi /undo tidak berani menghapusnya. Isi pesannya adalah ringkasan catatannya."""


def sekarang():
    return datetime.now(WIB)


def _tanggal(tanggal=None):
    """Teks 'YYYY-MM-DD' untuk `tanggal` (date), atau untuk hari ini kalau kosong."""
    return (tanggal or sekarang().date()).strftime('%Y-%m-%d')


def _tab(nama):
    try:
        return _WsAman(_coba(_buku.worksheet, nama))
    except WorksheetNotFound:
        raise TabTidakAda(nama)


def _tab_bulan():
    """Tab untuk bulan berjalan, misalnya 'Oktober'."""
    return _tab(BULAN[sekarang().month - 1])


def _tab_untuk(tanggal=None):
    """Tab bulan dari `tanggal` (date); kosong berarti bulan berjalan.
    Nama tab hanya berisi bulan tanpa tahun, jadi tahun tidak ikut menentukan tab."""
    if tanggal is None:
        return _tab_bulan()
    return _tab(BULAN[tanggal.month - 1])


def _baris_kosong(ws, kolom):
    """Cari baris pertama yang masih kosong di kolom nama barang."""
    nomor_kolom = a1_to_rowcol(kolom + '1')[1]
    isi = ws.col_values(nomor_kolom)      # isi kolom; indeks 0 = baris 1
    baris = BARIS_AWAL
    while baris <= len(isi) and isi[baris - 1].strip() != '':
        baris += 1
    return baris


def _catat_jejak(jejak, ws, rentang, nama, nominal):
    """Kalau pemanggil menyiapkan daftar jejak, catat apa yang baru ditulis
    (dipakai /undo untuk tahu sel mana yang harus dikosongkan)."""
    if jejak is not None:
        jejak.append({'tab': ws.title, 'rentang': rentang,
                      'nama': str(nama), 'nominal': nominal})


def simpan_pengeluaran(kategori, nama, nominal, jejak=None, tanggal=None):
    """Tulis satu pengeluaran ke tabel kategori.

    `tanggal` (date) kosong berarti hari ini, di tab bulan ini. Kalau diisi, tanggal
    itu yang ditulis dan barisnya masuk ke tab bulan dari tanggal tersebut.

    Mengembalikan (nama tab, nomor baris) supaya bisa dilaporkan ke pengguna.
    """
    ws = _tab_untuk(tanggal)
    kolom_awal, kolom_akhir = KATEGORI[kategori]
    baris = _baris_kosong(ws, kolom_awal)
    nama_tulis = nama
    if nama and nama[0] in '=+-@':
        nama_tulis = "'" + nama     # cegah teks dibaca sebagai rumus
    rentang = f'{kolom_awal}{baris}:{kolom_akhir}{baris}'
    # raw=False: tanggal '2026-10-13' dibaca Sheets sebagai tanggal asli,
    # dan formatnya mengikuti format sel (misalnya 13/10/2026).
    ws.update(range_name=rentang,
              values=[[nama_tulis, _tanggal(tanggal), nominal]], raw=False)
    _catat_jejak(jejak, ws, rentang, nama, nominal)
    return ws.title, baris


def _tulis_ke_tabel(ws, kolom_awal, kolom_akhir, baris_awal, baris_akhir,
                    nama_tabel, nama, nominal, jejak, tanggal=None):
    """Isi baris kosong pertama di tabel (nama / tanggal / nominal).
    `tanggal` (date) kosong berarti hari ini."""
    nomor_kolom = a1_to_rowcol(kolom_awal + '1')[1]
    isi = ws.col_values(nomor_kolom)      # indeks 0 = baris 1; sel kosong = ''
    for baris in range(baris_awal, baris_akhir + 1):
        if baris > len(isi) or isi[baris - 1].strip() == '':
            break
    else:
        raise TabelPenuh(nama_tabel)
    rentang = f'{kolom_awal}{baris}:{kolom_akhir}{baris}'
    ws.update(range_name=rentang,
              values=[[nama, _tanggal(tanggal), nominal]], raw=False)
    _catat_jejak(jejak, ws, rentang, nama, nominal)
    return baris


def simpan_pemasukan(sumber, nominal, jejak=None, tanggal=None):
    """Tulis satu baris ke tabel Pemasukan (B-D). `tanggal` (date) kosong berarti
    hari ini di tab bulan ini; kalau diisi, tab dan tanggalnya mengikuti tanggal itu.

    Mengembalikan (nama tab, nomor baris).
    """
    ws = _tab_untuk(tanggal)                     # melempar TabTidakAda kalau tab belum ada
    baris = _tulis_ke_tabel(ws, 'B', 'D', PEMASUKAN_BARIS_AWAL, PEMASUKAN_BARIS_AKHIR,
                            'Pemasukan', sumber, nominal, jejak, tanggal=tanggal)
    return ws.title, baris


def simpan_pemasukan_bank(bank, nominal, jejak=None):
    """Tulis satu baris ke tabel Pemasukan Bank (T-V), misalnya bank='BNI'.

    Mengembalikan (nama tab, nomor baris).
    """
    ws = _tab_bulan()
    baris = _tulis_ke_tabel(ws, 'T', 'V', PEMASUKAN_BANK_BARIS_AWAL, PEMASUKAN_BANK_BARIS_AKHIR,
                            'Pemasukan Bank', bank, nominal, jejak)
    return ws.title, baris


def ambil_saldo():
    """Baca angka ringkasan dari tab bulan ini.

    Mengembalikan (nama tab, {label: nilai}), misalnya
    {'Pemasukan': 2054700, 'Sisa Uang': 235000, 'BNI': 808489, 'Mandiri': 21286, ...}.
    """
    ws = _tab_bulan()
    blok = ws.batch_get([RENTANG_HASIL_AKHIR, RENTANG_SALDO_BANK],
                        value_render_option='UNFORMATTED_VALUE')
    hasil = {}
    for isi in blok:
        for baris in isi:
            # hanya baris "label | angka"; baris judul ("Total | Nilai") terlewati
            if len(baris) >= 2 and isinstance(baris[1], (int, float)):
                hasil[str(baris[0]).strip()] = baris[1]
    return ws.title, hasil


def _tanggal_dari_sel(sel):
    """Isi sel tanggal -> date, atau None kalau tidak terbaca.

    Sel bisa berisi angka (kalau berformat tanggal, Google Sheets menyimpannya sebagai jumlah
    hari sejak 30/12/1899) atau teks seperti '2026-10-30' dan '30/10/2026' (kalau kolomnya
    berformat teks biasa, tanggal yang ditulis bot tetap berupa teks). Keduanya dikenali.
    """
    if isinstance(sel, bool):
        return None
    if isinstance(sel, (int, float)):
        try:
            return date(1899, 12, 30) + timedelta(days=int(sel))
        except (OverflowError, ValueError):
            return None
    if isinstance(sel, str):
        for pola in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                return datetime.strptime(sel.strip(), pola).date()
            except ValueError:
                pass
    return None


def ambil_pengeluaran_hari_ini():
    """Daftar (kategori, nama barang, nilai) untuk hari ini dari semua tabel."""
    ws = _tab_bulan()
    rentang = [f'{a}{BARIS_AWAL}:{b}{BARIS_AKHIR}' for a, b in KATEGORI.values()]
    hasil = ws.batch_get(rentang, value_render_option='UNFORMATTED_VALUE')
    hari_ini = sekarang().date()
    daftar = []
    for kategori, blok in zip(KATEGORI, hasil):
        for baris in blok:
            nama, tgl, nilai = (list(baris) + ['', '', ''])[:3]
            if _tanggal_dari_sel(tgl) != hari_ini:
                continue      # baris kosong, bukan hari ini, atau bukan tanggal
            try:
                daftar.append((kategori, str(nama), int(float(nilai))))
            except (TypeError, ValueError):
                continue
    return daftar


def nama_bulan(mundur=0):
    """Nama tab bulan berjalan. mundur=1 berarti bulan lalu."""
    return BULAN[(sekarang().month - 1 - mundur) % 12]


def _angka(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def ambil_total_kategori(nama_tab):
    """Total tiap tabel pengeluaran di tab `nama_tab`, dibaca dari baris TOTAL.

    Mengembalikan {'Jajan': 420000, 'Alat': 0, ...}. Kalau sel TOTAL kosong atau
    bukan angka, totalnya dijumlahkan dari baris datanya.
    Melempar TabTidakAda kalau tabnya tidak ada.
    """
    ws = _tab(nama_tab)
    rentang = [f'{b}{BARIS_TOTAL}:{b}{BARIS_AKHIR}' for _, b in KATEGORI.values()]
    hasil = ws.batch_get(rentang, value_render_option='UNFORMATTED_VALUE')
    total = {}
    for kategori, blok in zip(KATEGORI, hasil):
        # satu nilai per baris; elemen pertama = baris TOTAL
        sel = [baris[0] if baris else '' for baris in blok]
        if sel and _angka(sel[0]):
            nilai = sel[0]
        else:
            nilai = sum(x for x in sel[1:] if _angka(x))
        total[kategori] = int(round(nilai))
    return total


# ---------------------------------------------------------------------------
# Status pengingat
# ---------------------------------------------------------------------------

def _baca_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _baca_status():
    return _baca_json(STATUS_FILE)


def pengingat_sudah_dicek(tanggal):
    """True kalau pengingat pengeluaran untuk `tanggal` ('2026-10-24') sudah ditangani."""
    with _kunci_status:
        return _baca_status().get('pengingat_pengeluaran') == tanggal


def tandai_pengingat_dicek(tanggal):
    with _kunci_status:
        status = _baca_status()
        status['pengingat_pengeluaran'] = tanggal
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False, indent=1)


def status_sudah(kunci, tanggal):
    """True kalau status `kunci` (misalnya 'pesan_pagi') sudah ditandai untuk `tanggal`."""
    with _kunci_status:
        return _baca_status().get(kunci) == tanggal


def status_tandai(kunci, tanggal):
    with _kunci_status:
        status = _baca_status()
        status[kunci] = tanggal
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------
# Daftar deadline
# ---------------------------------------------------------------------------

def baca_deadline():
    """Daftar deadline: [{'judul': ..., 'waktu': '2026-10-30T23:59:00+07:00',
    'terkirim': ['h3']}, ...]. Hanya untuk dibaca; ubah lewat ubah_deadline."""
    with _kunci_deadline:
        return list(_baca_json(DEADLINE_FILE).get('daftar', []))


def ubah_deadline(ubah):
    """Baca daftar deadline, jalankan ubah(daftar) (boleh mengubah daftar di tempat),
    lalu simpan kalau isinya berubah. Mengembalikan apa yang dikembalikan ubah().
    Ditulis ke file sementara dulu lalu ditukar, supaya file tidak rusak kalau bot mati."""
    with _kunci_deadline:
        data = _baca_json(DEADLINE_FILE)
        daftar = data.get('daftar', [])
        sebelum = json.dumps(daftar, ensure_ascii=False, sort_keys=True)
        hasil = ubah(daftar)
        if json.dumps(daftar, ensure_ascii=False, sort_keys=True) != sebelum:
            data['daftar'] = daftar
            sementara = DEADLINE_FILE + '.tmp'
            with open(sementara, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(sementara, DEADLINE_FILE)
        return hasil


# ---------------------------------------------------------------------------
# Pengaturan yang diubah lewat chat
# ---------------------------------------------------------------------------

def baca_pengaturan(kunci):
    """Nilai pengaturan `kunci` ('pintasan' atau 'batas'), atau None kalau belum
    pernah disimpan."""
    with _kunci_pengaturan:
        return _baca_json(PENGATURAN_FILE).get(kunci)


def tulis_pengaturan(kunci, nilai):
    """Simpan `nilai` untuk `kunci`, pengaturan lain tidak disentuh. Ditulis ke file
    sementara dulu lalu ditukar, supaya file tidak rusak kalau bot mati di tengah."""
    with _kunci_pengaturan:
        data = _baca_json(PENGATURAN_FILE)
        data[kunci] = nilai
        sementara = PENGATURAN_FILE + '.tmp'
        with open(sementara, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(sementara, PENGATURAN_FILE)


# ---------------------------------------------------------------------------
# Riwayat untuk /undo
# ---------------------------------------------------------------------------

def _baca_riwayat():
    try:
        with open(RIWAYAT_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _tulis_riwayat(daftar):
    with open(RIWAYAT_FILE, 'w', encoding='utf-8') as f:
        json.dump(daftar[-RIWAYAT_MAKS:], f, ensure_ascii=False, indent=1)


def simpan_riwayat(ringkasan, jejak):
    """Simpan satu catatan (bisa terdiri dari beberapa sel) supaya bisa dibatalkan."""
    with _kunci_riwayat:
        daftar = _baca_riwayat()
        daftar.append({'waktu': sekarang().isoformat(timespec='seconds'),
                       'ringkasan': ringkasan,
                       'tulisan': jejak})
        _tulis_riwayat(daftar)


def ambil_riwayat(jumlah):
    """`jumlah` catatan terakhir, yang terbaru di depan: [{'waktu', 'ringkasan', 'tulisan'}].
    Urutannya sama dengan urutan /undo membatalkan."""
    with _kunci_riwayat:
        daftar = _baca_riwayat()
    return daftar[::-1][:jumlah]


def _sel_masih_sama(ws, tulisan):
    """True kalau isi sel masih sama dengan yang ditulis bot (nama dan nominal)."""
    sel = ws.get(tulisan['rentang'], value_render_option='UNFORMATTED_VALUE')
    nilai = list(sel[0]) if sel else []
    if len(nilai) < 3:
        return False
    try:
        # tanda ' di depan hanya penanda "ini teks" dari simpan_pengeluaran, abaikan saat membandingkan
        nama_sel = str(nilai[0]).strip().lstrip("'").lower()
        nama_tulis = tulisan['nama'].strip().lstrip("'").lower()
        return nama_sel == nama_tulis and float(nilai[2]) == float(tulisan['nominal'])
    except (TypeError, ValueError):
        return False


def _sel_kosong(ws, tulisan):
    sel = ws.get(tulisan['rentang'], value_render_option='UNFORMATTED_VALUE')
    return not any(str(x).strip() for baris in sel for x in baris)


def batalkan_terakhir():
    """Kosongkan sel-sel dari catatan terakhir.

    Mengembalikan (ringkasan, waktu) catatan yang dibatalkan, atau None kalau
    riwayat kosong. Melempar RiwayatBerubah kalau isi sel sudah berbeda dari yang
    ditulis bot (misalnya kamu sudah mengeditnya); catatan itu tetap dikeluarkan
    dari riwayat, tapi selnya tidak disentuh.
    """
    with _kunci_riwayat:
        daftar = _baca_riwayat()
        if not daftar:
            return None
        entri = daftar[-1]

        # Cek semuanya dulu; hapus hanya kalau semua sel aman.
        yang_dihapus = []
        aman = True
        for t in entri['tulisan']:
            ws = _tab(t['tab'])
            if _sel_kosong(ws, t):
                continue                  # sudah dikosongkan manual
            if _sel_masih_sama(ws, t):
                yang_dihapus.append((ws, t['rentang']))
            else:
                aman = False
                break

        if aman:
            for ws, rentang in yang_dihapus:
                ws.batch_clear([rentang])     # hanya isi, format sel tetap

        _tulis_riwayat(daftar[:-1])           # keluarkan dari riwayat
        if not aman:
            raise RiwayatBerubah(entri['ringkasan'])
        return entri['ringkasan'], entri['waktu']