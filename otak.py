import calendar
import re
import traceback
from datetime import date, datetime, time, timedelta

try:
    import requests
except ImportError:
    requests = None

import config
from ai_input import (InputAIGagal, analisis_struk, parse_bahasa_natural_ai,
                      parse_bahasa_natural_lokal, transkrip_audio)
from catatan import MAKS_CATATAN, CatatanGagal, ambil_entri, tambah_catatan
from grafik import GrafikGagal, buat_grafik_bulanan, buat_grafik_mingguan
from kalender import (GAGAL_KALENDER, TugasGagal, event_hari_ini, hapus_event,
                      tambah_event, tambah_penanda_deadline, tambah_tugas)
from penyimpanan import (BULAN, GAGAL_JARINGAN, RIWAYAT_MAKS, WIB, RiwayatBerubah,
                         TabelPenuh, TabTidakAda,
                         ambil_konfirmasi, ambil_pengeluaran_hari_ini, ambil_riwayat,
                         ambil_saldo, ambil_semua_pengeluaran, ambil_total_kategori,
                         baca_deadline, baca_pengaturan, baca_pengingat_cepat,
                         baca_tagihan, batalkan_terakhir, hapus_konfirmasi,
                         nama_bulan, pengingat_sudah_dicek, sekarang,
                         simpan_konfirmasi, simpan_pemasukan, simpan_pemasukan_bank,
                         simpan_pengeluaran, simpan_riwayat, simpan_transfer,
                         status_sudah, status_tandai, tambah_pemasukan,
                         tandai_pengingat_dicek, tulis_pengaturan, ubah_deadline,
                         ubah_pengingat_cepat, ubah_tagihan)

# Kata kategori yang boleh diketik -> nama tabel di spreadsheet
KATEGORI_ALIAS = {
    'jajan': 'Jajan',
    'alat': 'Alat',
    'mingguan': 'Mingguan&Bulanan',
    'bulanan': 'Mingguan&Bulanan',
    'hiburan': 'Hiburan',
}

# Bank yang boleh diketik di /topup, /in, /qris, /tarik -> nama yang ditulis di sheet
BANK_ALIAS = {
    'bni': 'BNI',
    'mandiri': 'Mandiri',
}

# Dompet untuk /transfer (BNI, Mandiri, Tunai)
DOMPET_ALIAS = {
    'bni': 'BNI',
    'mandiri': 'Mandiri',
    'tunai': 'Tunai',
    'cash': 'Tunai',
    'dompet': 'Tunai',
}

# Pintasan barang langganan: ketik "galon", /out galon, atau /qris kopi 22rb (harga ditimpa).
# nama pintasan -> (nama tabel kategori, nama yang ditulis di sheet, harga biasa)
# Ini HANYA nilai awal. Begitu kamu mengubah pintasan lewat /pintasan, daftarnya
# disimpan di pengaturan.json dan dict ini tidak dipakai lagi. Kalau harganya
# None, pintasan itu hanya jalan kalau nominalnya diketik sendiri.
PINTASAN_AWAL = {
    'galon': ('Mingguan&Bulanan', 'Galon', None),
    'kopi': ('Jajan', 'Kopi', None),
    'tempe': ('Jajan', 'Tempe', None),
    'billiard': ('Hiburan', 'Billiard', None),
}

# Kata yang tidak boleh jadi nama pintasan (dipakai di awal pesan tanpa perintah / konfirmasi).
NAMA_TERLARANG = {'hapus', 'qris', 'out', 'kemarin', 'ya', 'batal', 'gabung', 'in', 'masuk', 'tf'}

# Tanggal untuk mencatat pengeluaran yang terlewat: "/out kemarin 13rb lotek" atau
# "/out 22/10 13rb lotek" (tanggal/bulan, tahun ini). Tidak boleh di masa depan.
POLA_TANGGAL = re.compile(r'^(\d{1,2})/(\d{1,2})$')

# Jumlah catatan yang ditampilkan /riwayat kalau tidak diberi angka.
RIWAYAT_TAMPIL = 5

# Pengingat "belum catat pengeluaran": dikirim sekali sehari, mulai jam ini (WIB).
JAM_PENGINGAT = 20

# Rekap pengeluaran harian: dikirim sekali sehari, mulai jam ini (WIB).
# /malam menampilkannya kapan saja.
JAM_REKAP = 21

# Peringatan batas bulanan mulai muncul saat pengeluaran satu kategori mencapai
# sekian persen dari batasnya (lihat /batas).
AMBANG_PERINGATAN = 0.8

# Pesan tanpa perintah ("13rb lotek"): nominal di bawah ini dianggap salah ketik
# (misalnya "2 galon" terbaca Rp2) dan tidak dicatat.
NOMINAL_MINIMAL_BEBAS = 1000

# Batas jumlah baris dalam satu pesan, supaya tidak melewati kuota Google Sheets.
MAKS_BARIS = 10

# Masa berlaku draft konfirmasi hasil scan struk / voice note (menit).
KONFIRMASI_KADALUARSA_MENIT = 15

# Pengingat deadline (/deadline). Tiap tingkat dikirim sekali:
#   ('h3', 'hari', 3) = pagi hari (jam JAM_PENGINGAT_HARI) pada 3 hari sebelum tanggal deadline
#   ('j3', 'jam', 3)  = tepat 3 jam sebelum waktu deadline
# Tingkat yang waktunya sudah lewat saat deadline dibuat tidak dikirim.
TINGKAT_DEADLINE = (('h3', 'hari', 3), ('h1', 'hari', 1), ('j3', 'jam', 3))
JAM_PENGINGAT_HARI = 8
MAKS_JUDUL_DEADLINE = 100

# Pesan pagi: dikirim sekali sehari antara JAM_PAGI dan JAM_PAGI_BATAS (WIB). Kalau bot
# baru hidup setelah JAM_PAGI_BATAS, pesan hari itu dilewati. /pagi menampilkannya kapan saja.
JAM_PAGI = 7
JAM_PAGI_BATAS = 12
LOKASI_CUACA = ('Yogyakarta', -7.80, 110.37)      # nama, lintang, bujur
JUMLAH_DEADLINE_PAGI = 3

NAMA_HARI = ('Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu')
HARI_PENDEK = ('Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min')
HARI_KATA = {'senin': 0, 'selasa': 1, 'rabu': 2, 'kamis': 3, 'jumat': 4, "jum'at": 4,
             'sabtu': 5, 'minggu': 6, 'ahad': 6}

# Kode cuaca WMO dari Open-Meteo -> (deskripsi, ikon).
CUACA_WMO = {
    0: ('cerah', '☀️'), 1: ('cerah berawan', '🌤️'), 2: ('berawan sebagian', '⛅'),
    3: ('mendung', '☁️'), 45: ('berkabut', '🌫️'), 48: ('berkabut', '🌫️'),
    51: ('gerimis ringan', '🌦️'), 53: ('gerimis', '🌦️'), 55: ('gerimis lebat', '🌦️'),
    56: ('gerimis dingin', '🌦️'), 57: ('gerimis dingin', '🌦️'),
    61: ('hujan ringan', '🌧️'), 63: ('hujan sedang', '🌧️'), 65: ('hujan lebat', '🌧️'),
    66: ('hujan dingin', '🌧️'), 67: ('hujan dingin', '🌧️'),
    80: ('hujan lokal ringan', '🌦️'), 81: ('hujan lokal', '🌧️'),
    82: ('hujan lokal deras', '🌧️'),
    95: ('badai petir', '⛈️'), 96: ('badai petir dan hujan es', '⛈️'),
    99: ('badai petir dan hujan es', '⛈️'),
}

PETUNJUK_DEADLINE = ('Tambah: /deadline <judul> <tanggal> <jam> [--lokal]\n'
                     'Contoh: /deadline DML 3 jumat 23:59\n'
                     'Tanggal: hariini, besok, lusa, nama hari (jumat), atau 30/10 (30/10/2026)\n'
                     'Lihat: /deadline\n'
                     'Selesai: /deadline selesai <nomor atau judul>\n'
                     'Sinkron ke kalender: /deadline sinkron')

PETUNJUK_INGATKAN = ('Tambah: /ingatkan <waktu> <pesan>\n'
                     'Contoh:\n'
                     '• /ingatkan 30m angkat jemuran\n'
                     '• /ingatkan 1j30m minum obat\n'
                     '• /ingatkan 21:00 matikan kompor\n'
                     '• /ingatkan besok 09:00 bayar kos\n'
                     'Lihat: /ingatkan\n'
                     'Hapus: /ingatkan hapus <nomor atau kata>')

PETUNJUK_TAGIHAN = ('Tambah: /tagihan tambah <tgl 1-31> <nominal> [kategori] [qris|qris_mandiri|tunai] [auto] <nama>\n'
                    'Contoh: /tagihan tambah 1 800rb bulanan qris Kos\n'
                    'Bayar: /tagihan bayar <nomor atau nama> [nominal_beda]\n'
                    'Hapus: /tagihan hapus <nomor atau nama>')

# Nama sumber yang ditulis di tabel Pemasukan.
# Rumus saldo BNI (sel L11) & Mandiri (sel L12) mencari kata "BNI" / "Mandiri",
# jadi kata tersebut harus tetap ada.
SUMBER_QRIS = 'QRIS BNI'
SUMBER_TARIK = 'Tarik Uang BNI'
SUMBER_QRIS_BANK = {
    'BNI': 'QRIS BNI',
    'Mandiri': 'QRIS Mandiri',
}
SUMBER_TARIK_BANK = {
    'BNI': 'Tarik Uang BNI',
    'Mandiri': 'Tarik Uang Mandiri',
}

NOMINAL_TAK_TERBACA = 'Nominal tidak terbaca. Contoh: 25000, 25.000, 25rb, atau 1,5jt'

PETUNJUK_PINTASAN = ('Tambah/ubah: /pintasan <nama> <harga> [kategori] [nama di sheet]\n'
                     'Hapus: /pintasan hapus <nama>')
PETUNJUK_BATAS = ('Atur: /batas <kategori> <nominal>  (kategori: jajan, alat, mingguan, bulanan, hiburan)\n'
                  'Hapus: /batas hapus <kategori>')

def rupiah(angka):
    tanda = '-' if angka < 0 else ''
    return tanda + 'Rp' + f'{abs(angka):,}'.replace(',', '.')

def baca_nominal(teks):
    """'25000', '25.000', '25rb', '25k', '1,5jt', '1.5jt' -> int"""
    t = teks.strip().lower()
    if t.startswith('rp'):
        t = t[2:].lstrip('.')
    pengali = 1
    if t.endswith('jt'):
        pengali, t = 1_000_000, t[:-2]
    elif t.endswith('rb'):
        pengali, t = 1_000, t[:-2]
    elif t.endswith('k'):
        pengali, t = 1_000, t[:-1]
    if pengali > 1:
        if ',' in t and '.' not in t:
            return int(round(float(t.replace(',', '.')) * pengali))
        if re.fullmatch(r'\d+\.\d{1,2}', t):
            return int(round(float(t) * pengali))
    t = t.replace('.', '').replace(',', '')
    return int(t) * pengali


def kata_tanggal(kata):
    """True kalau `kata` berbentuk penanda tanggal: 'kemarin' atau '22/10'."""
    kata = kata.lower()
    return kata == 'kemarin' or bool(POLA_TANGGAL.match(kata))


def baca_tanggal_lalu(kata):
    """'kemarin' atau '22/10' -> date. Melempar ValueError berisi pesan untuk
    pengguna kalau tanggalnya tidak ada atau belum terjadi.
    (Beda dengan baca_tanggal di bawah, yang untuk /todo dan melihat ke depan.)"""
    hari_ini = sekarang().date()
    kata = kata.lower()
    if kata == 'kemarin':
        return hari_ini - timedelta(days=1)
    cocok = POLA_TANGGAL.match(kata)
    tgl = None
    if cocok:
        try:
            tgl = date(hari_ini.year, int(cocok.group(2)), int(cocok.group(1)))
        except ValueError:                  # misalnya 30/2
            pass
    if tgl is None:
        raise ValueError('Tanggal ' + kata + ' tidak valid. Contoh: /out 22/10 13rb lotek')
    if tgl > hari_ini:
        raise ValueError('Tanggal ' + kata + ' belum terjadi, jadi belum dicatat. '
                         'Pengeluaran hanya bisa dicatat untuk hari ini atau hari yang sudah lewat.')
    return tgl


def daftar_pintasan():
    """{'galon': (kategori, nama, harga)}. Dibaca dari pengaturan.json; sebelum
    pernah diubah lewat /pintasan, dipakai PINTASAN_AWAL."""
    data = baca_pengaturan('pintasan')
    if data is None:
        data = PINTASAN_AWAL
    return {kunci: tuple(isi) for kunci, isi in data.items()}


def baca_batas():
    """{'Jajan': 500000} -- batas bulanan per nama tabel kategori."""
    data = baca_pengaturan('batas') or {}
    return {kategori: int(nilai) for kategori, nilai in data.items()}


def baca_pintasan(bagian, nama_perintah, daftar):
    """['galon'] atau ['galon', '22rb'] -> (kategori, nama, nominal).
    Kalau tidak bisa diproses, mengembalikan teks pesan untuk pengguna."""
    kunci = bagian[0].lower()
    kategori, nama, harga = daftar[kunci]
    if len(bagian) > 2:
        return ('Format pintasan: ' + nama_perintah + ' ' + kunci +
                ' [nominal kalau harganya beda]')
    if len(bagian) == 2:
        try:
            return kategori, nama, baca_nominal(bagian[1])
        except ValueError:
            return NOMINAL_TAK_TERBACA
    if harga is None:
        return ('Harga ' + kunci + ' belum diisi. Isi dengan: /pintasan ' + kunci + ' <harga>\n'
                'atau ketik nominalnya sekarang: ' + nama_perintah + ' ' + kunci + ' <nominal>')
    return kategori, nama, harga


def baca_pengeluaran_biasa(bagian, nama_perintah, daftar):
    """['13rb', 'jajan', 'lotek'] -> (kategori, nama, nominal).
    Kalau tidak bisa diproses, mengembalikan teks pesan untuk pengguna."""
    if len(bagian) < 2:
        pesan = ('Format: ' + nama_perintah + ' <nominal> [kategori] <nama barang>\n'
                 'Kategori: jajan (otomatis), alat, mingguan, bulanan, hiburan\n'
                 'Contoh: ' + nama_perintah + ' 13rb jajan lotek\n'
                 'Hari lain: ' + nama_perintah + ' kemarin 13rb lotek, atau ' +
                 nama_perintah + ' 22/10 13rb lotek')
        if daftar:
            pesan += ('\nPintasan: ' + ', '.join(daftar) +
                      ' (contoh: ' + nama_perintah + ' ' + next(iter(daftar)) + ')')
        return pesan
    try:
        nominal = baca_nominal(bagian[0])
    except ValueError:
        return NOMINAL_TAK_TERBACA

    sisa = bagian[1:]
    kategori = 'Jajan'                      # kalau kategori tidak ditulis
    if sisa[0].lower() in KATEGORI_ALIAS:
        kategori = KATEGORI_ALIAS[sisa[0].lower()]
        sisa = sisa[1:]
        if not sisa:
            return 'Tulis nama barangnya. Contoh: ' + nama_perintah + ' 65rb alat teko listrik'
    return kategori, ' '.join(sisa), nominal


def _mengandung_bank_terlarang(teks, bank_diizinkan=None):
    """True jika `teks` mengandung nama bank ('bni'/'mandiri') selain `bank_diizinkan`.
    Mencegah rumus SUMIF("*BNI*") / SUMIF("*Mandiri*") di spreadsheet terhitung keliru."""
    low = (teks or '').lower()
    for alias, nama_bank in BANK_ALIAS.items():
        if bank_diizinkan and nama_bank == bank_diizinkan:
            continue
        if alias in low:
            return nama_bank
    return None


def _baca_nama_tab_bulan(kata):
    """'oktober' -> 'Oktober', atau None kalau bukan nama bulan."""
    low = kata.strip().lower()
    for b in BULAN:
        if b.lower() == low:
            return b
    return None


def catat_pengeluaran(argumen, nama_perintah, lewat_qris, nominal_minimal=0):
    """Dipakai bersama oleh /out, /qris, dan pesan tanpa perintah.
    Kalau lewat_qris True, selain mencatat pengeluaran, bot juga menambahkan nominalnya
    ke baris 'QRIS BNI' (atau 'QRIS Mandiri' kalau ditulis /qris mandiri ...) di tabel
    Pemasukan (satu baris per sumber per bulan).

    Pengeluaran bisa untuk hari lain: tanggalnya ('kemarin' atau '22/10') ditulis paling
    depan, sebelum nominal atau nama pintasan.

    Mengembalikan (pesan, kategori). kategori None artinya baris sisa uang dan peringatan
    batas tidak perlu ditampilkan: tidak ada yang dicatat, atau yang dicatat masuk ke
    bulan lain (sisa uang dan batas yang ditampilkan selalu milik bulan berjalan)."""
    bagian = argumen.split()
    hari_ini = sekarang().date()
    tanggal = None                          # None = hari ini
    bank_qris = 'BNI'

    # Izinkan urutan "/qris mandiri kemarin 13rb kopi" maupun "/qris kemarin mandiri 13rb kopi"
    for _ in range(2):
        if lewat_qris and bagian and bagian[0].lower() in BANK_ALIAS:
            bank_qris = BANK_ALIAS[bagian[0].lower()]
            bagian = bagian[1:]
        elif bagian and kata_tanggal(bagian[0]) and tanggal is None:
            try:
                tanggal = baca_tanggal_lalu(bagian[0])
            except ValueError as e:
                return str(e), None
            bagian = bagian[1:]
            if tanggal == hari_ini:
                tanggal = None
        else:
            break

    daftar = daftar_pintasan()
    dari_pintasan = bool(bagian) and bagian[0].lower() in daftar
    if dari_pintasan:
        hasil = baca_pintasan(bagian, nama_perintah, daftar)
    else:
        hasil = baca_pengeluaran_biasa(bagian, nama_perintah, daftar)
    if isinstance(hasil, str):              # pesan salah format
        return hasil, None
    kategori, nama, nominal = hasil

    if nominal <= 0:
        return 'Nominal harus lebih dari 0.', None

    # Harga tersimpan milik pintasan tidak diperiksa; yang diketik pengguna diperiksa.
    harga_tersimpan = dari_pintasan and len(bagian) == 1
    if not harga_tersimpan and nominal < nominal_minimal:
        return ('Nominal ' + rupiah(nominal) + ' kelihatannya terlalu kecil, jadi belum dicatat. '
                'Tulis 2rb untuk Rp2.000, atau pakai /out kalau memang segitu.'), None

    sumber_qris = SUMBER_QRIS_BANK[bank_qris]

    # Pemasukan ditulis lebih dulu: kalau tab bulan belum ada atau tabel
    # Pemasukan penuh, errornya muncul sebelum ada yang tertulis setengah-setengah.
    # "jejak" mencatat sel yang ditulis supaya bisa dibatalkan dengan /undo.
    jejak = []
    baris_qris = total_qris = None
    awalan_qris = (sumber_qris + ' ') if lewat_qris else ''
    ringkasan = awalan_qris + kategori + ' ' + nama + ' ' + rupiah(nominal)
    if tanggal:
        ringkasan += ' untuk ' + tanggal.strftime('%d/%m')
    try:
        if lewat_qris:
            _, baris_qris, total_qris = tambah_pemasukan(sumber_qris, nominal, jejak=jejak,
                                                         tanggal=tanggal)
        tab, baris = simpan_pengeluaran(kategori, nama, nominal, jejak=jejak, tanggal=tanggal)
    finally:
        if jejak:                           # tetap tercatat walau penulisan kedua gagal
            simpan_riwayat(ringkasan, jejak)

    pesan = ('✅ ' + kategori + ': ' + nama + ' ' + rupiah(nominal) +
             (' untuk ' + tanggal.strftime('%d/%m/%Y') if tanggal else '') +
             ' (tab ' + tab + ', baris ' + str(baris) + ')')
    if lewat_qris:
        pesan += ('\n💳 ' + sumber_qris + ' +' + rupiah(nominal) + ' (total ' + rupiah(total_qris) +
                  ', Pemasukan baris ' + str(baris_qris) + ')')
    if tanggal and (tanggal.year, tanggal.month) != (hari_ini.year, hari_ini.month):
        return pesan, None                  # bulan lain: sisa uang dan batas bulan ini tidak berubah
    return pesan, kategori


def info_sisa(kategori=(), bank=None):
    """Baris tambahan di akhir balasan pencatatan: sisa uang (atau saldo bank kalau
    `bank` diisi), plus peringatan kalau kategori yang baru ditulis sudah dekat atau
    melewati batas bulanannya (lihat /batas).

    Catatannya sudah tersimpan saat fungsi ini dipanggil, jadi gagal membaca sheet
    tidak boleh terlihat seperti gagal mencatat: kalau error, barisnya dilewati."""
    baris = []
    try:
        _, angka = ambil_saldo()
        label = bank or 'Sisa Uang'
        if label in angka:
            judul = 'Saldo ' + bank if bank else 'Sisa uang'
            baris.append('💰 ' + judul + ': ' + rupiah(int(round(angka[label]))))
    except Exception:
        traceback.print_exc()

    batas = baca_batas()
    kena = sorted(k for k in kategori if k in batas)
    if kena:
        try:
            total = ambil_total_kategori(nama_bulan())
            for k in kena:
                if total[k] > batas[k]:
                    baris.append('🚨 ' + k + ' melewati batas: ' + rupiah(total[k]) + ' dari ' +
                                 rupiah(batas[k]) + ' (lebih ' + rupiah(total[k] - batas[k]) + ')')
                elif total[k] >= batas[k] * AMBANG_PERINGATAN:
                    baris.append('⚠️ ' + k + ' sudah ' + str(int(total[k] * 100 / batas[k])) +
                                 '% dari batas (' + rupiah(total[k]) + ' / ' + rupiah(batas[k]) + ')')
        except Exception:
            traceback.print_exc()
    return ''.join('\n' + b for b in baris)


def _info_saldo_dompet(*dompet):
    """Tampilkan ringkasan saldo beberapa dompet sekaligus setelah transfer."""
    try:
        _, angka = ambil_saldo()
    except Exception:
        traceback.print_exc()
        return ''
    peta = {'Tunai': 'Sisa Uang', 'BNI': 'BNI', 'Mandiri': 'Mandiri'}
    bagian = []
    for d in dompet:
        kunci = peta.get(d, d)
        if kunci in angka:
            bagian.append(d + ' ' + rupiah(int(round(angka[kunci]))))
    return ('\n💰 ' + ' · '.join(bagian)) if bagian else ''


def catat_dan_lapor(argumen, nama_perintah, lewat_qris, nominal_minimal=0, kategori_banyak=None):
    """catat_pengeluaran + baris sisa uang / peringatan batas di akhir balasan.
    Kalau kategori_banyak (set) diberikan, baris tambahan tidak ditempel di sini:
    kategorinya dikumpulkan, dan pemanggil menampilkannya sekali di akhir pesan."""
    pesan, kategori = catat_pengeluaran(argumen, nama_perintah, lewat_qris, nominal_minimal)
    if kategori is None:
        return pesan
    if kategori_banyak is not None:
        kategori_banyak.add(kategori)
        return pesan
    return pesan + info_sisa([kategori])


def perintah_out(argumen, kategori_banyak=None):
    return catat_dan_lapor(argumen, '/out', False, kategori_banyak=kategori_banyak)


def perintah_qris(argumen, kategori_banyak=None):
    return catat_dan_lapor(argumen, '/qris', True, kategori_banyak=kategori_banyak)


def perintah_tarik(argumen):
    """/tarik [bni|mandiri] <nominal> -> baris 'Tarik Uang BNI/Mandiri' di tabel Pemasukan."""
    bagian = argumen.split()
    bank = 'BNI'
    if len(bagian) == 2 and bagian[0].lower() in BANK_ALIAS:
        bank = BANK_ALIAS[bagian[0].lower()]
        bagian = bagian[1:]
    if len(bagian) != 1:
        return 'Format: /tarik [bni|mandiri] <nominal>\nContoh: /tarik 250rb atau /tarik mandiri 100rb'
    try:
        nominal = baca_nominal(bagian[0])
    except ValueError:
        return NOMINAL_TAK_TERBACA
    if nominal <= 0:
        return 'Nominal harus lebih dari 0.'
    sumber = SUMBER_TARIK_BANK[bank]
    jejak = []
    tab, baris = simpan_pemasukan(sumber, nominal, jejak=jejak)
    simpan_riwayat('Tarik tunai ' + bank + ' ' + rupiah(nominal), jejak)
    return ('🏧 ' + sumber + ' ' + rupiah(nominal) +
            ' dicatat di Pemasukan (tab ' + tab + ', baris ' + str(baris) + ')' +
            _info_saldo_dompet('Tunai', bank))


def perintah_topup(argumen):
    """/topup <bni|mandiri> <nominal> [keterangan] -> baris di tabel Pemasukan Bank."""
    bagian = argumen.split()
    if len(bagian) < 2 or bagian[0].lower() not in BANK_ALIAS:
        return ('Format: /topup <bni|mandiri> <nominal> [keterangan]\n'
                'Contoh: /topup bni 1jt  atau  /topup bni 1jt kiriman')
    bank = BANK_ALIAS[bagian[0].lower()]
    try:
        nominal = baca_nominal(bagian[1])
    except ValueError:
        return NOMINAL_TAK_TERBACA
    if nominal <= 0:
        return 'Nominal harus lebih dari 0.'
    keterangan = ' '.join(bagian[2:]).strip()
    bank_lain = _mengandung_bank_terlarang(keterangan, bank_diizinkan=bank)
    if bank_lain:
        return ('Keterangan tidak boleh mengandung kata "' + bank_lain +
                '" agar rumus saldo bank di spreadsheet tidak terhitung ganda.')
    label = (bank + ' - ' + keterangan) if keterangan else bank
    jejak = []
    tab, baris = simpan_pemasukan_bank(label, nominal, jejak=jejak)
    simpan_riwayat('Top up ' + label + ' ' + rupiah(nominal), jejak)
    return ('🏦 Top up ' + label + ' ' + rupiah(nominal) +
            ' dicatat di Pemasukan Bank (tab ' + tab + ', baris ' + str(baris) + ')' +
            info_sisa(bank=bank))


def perintah_in(argumen):
    """/in [tanggal] <nominal> <sumber>  (pemasukan tunai di tabel Pemasukan)
    /in [tanggal] <bni|mandiri> <nominal> [keterangan]  (pemasukan bank di Pemasukan Bank)"""
    bagian = argumen.split()
    hari_ini = sekarang().date()
    tanggal = None
    if bagian and kata_tanggal(bagian[0]):
        try:
            tanggal = baca_tanggal_lalu(bagian[0])
        except ValueError as e:
            return str(e)
        bagian = bagian[1:]
        if tanggal == hari_ini:
            tanggal = None

    if not bagian:
        return ('Format pemasukan:\n'
                '• Tunai: /in [kemarin|22/10] <nominal> <sumber>\n'
                '  Contoh: /in 200rb uang saku\n'
                '• Bank: /in [kemarin|22/10] <bni|mandiri> <nominal> [keterangan]\n'
                '  Contoh: /in bni 1jt gaji')

    # Pemasukan ke rekening bank
    if bagian[0].lower() in BANK_ALIAS:
        if len(bagian) < 2:
            return 'Format: /in <bni|mandiri> <nominal> [keterangan]\nContoh: /in bni 1jt gaji'
        bank = BANK_ALIAS[bagian[0].lower()]
        try:
            nominal = baca_nominal(bagian[1])
        except ValueError:
            return NOMINAL_TAK_TERBACA
        if nominal <= 0:
            return 'Nominal harus lebih dari 0.'
        keterangan = ' '.join(bagian[2:]).strip()
        bank_lain = _mengandung_bank_terlarang(keterangan, bank_diizinkan=bank)
        if bank_lain:
            return ('Keterangan tidak boleh mengandung kata "' + bank_lain +
                    '" agar rumus saldo bank di spreadsheet tidak terhitung ganda.')
        label = (bank + ' - ' + keterangan) if keterangan else bank
        jejak = []
        tab, baris = simpan_pemasukan_bank(label, nominal, jejak=jejak, tanggal=tanggal)
        ringkasan = 'Pemasukan ' + label + ' ' + rupiah(nominal)
        if tanggal:
            ringkasan += ' untuk ' + tanggal.strftime('%d/%m')
        simpan_riwayat(ringkasan, jejak)
        pesan = ('💵 Pemasukan bank: ' + label + ' ' + rupiah(nominal) +
                 (' untuk ' + tanggal.strftime('%d/%m/%Y') if tanggal else '') +
                 ' (tab ' + tab + ', baris ' + str(baris) + ')')
        if tanggal and (tanggal.year, tanggal.month) != (hari_ini.year, hari_ini.month):
            return pesan
        return pesan + info_sisa(bank=bank)

    # Opsional kata 'tunai'/'cash' di depan
    if bagian[0].lower() in ('tunai', 'cash', 'dompet'):
        bagian = bagian[1:]
    if len(bagian) < 2:
        return 'Format: /in <nominal> <sumber>\nContoh: /in 200rb uang saku'
    try:
        nominal = baca_nominal(bagian[0])
    except ValueError:
        return NOMINAL_TAK_TERBACA
    if nominal <= 0:
        return 'Nominal harus lebih dari 0.'
    sumber = ' '.join(bagian[1:]).strip()
    bank_kena = _mengandung_bank_terlarang(sumber)
    if bank_kena:
        return ('Sumber pemasukan tunai tidak boleh mengandung kata "' + bank_kena +
                '", karena rumus saldo ' + bank_kena + ' di spreadsheet akan menguranginya.\n'
                'Kalau uang masuk ke rekening ' + bank_kena + ', pakai: /in ' +
                bank_kena.lower() + ' ' + str(nominal) + ' <keterangan>')
    jejak = []
    tab, baris = simpan_pemasukan(sumber, nominal, jejak=jejak, tanggal=tanggal)
    ringkasan = 'Pemasukan tunai ' + sumber + ' ' + rupiah(nominal)
    if tanggal:
        ringkasan += ' untuk ' + tanggal.strftime('%d/%m')
    simpan_riwayat(ringkasan, jejak)
    pesan = ('💵 Pemasukan tunai: ' + sumber + ' ' + rupiah(nominal) +
             (' untuk ' + tanggal.strftime('%d/%m/%Y') if tanggal else '') +
             ' (tab ' + tab + ', baris ' + str(baris) + ')')
    if tanggal and (tanggal.year, tanggal.month) != (hari_ini.year, hari_ini.month):
        return pesan
    return pesan + info_sisa()


def perintah_transfer(argumen):
    """/transfer [tanggal] <asal> <tujuan> <nominal> [catatan]
    Dompet: bni, mandiri, tunai (alias: cash, dompet)."""
    bagian = argumen.split()
    hari_ini = sekarang().date()
    tanggal = None
    if bagian and kata_tanggal(bagian[0]):
        try:
            tanggal = baca_tanggal_lalu(bagian[0])
        except ValueError as e:
            return str(e)
        bagian = bagian[1:]
        if tanggal == hari_ini:
            tanggal = None

    if len(bagian) < 3 or bagian[0].lower() not in DOMPET_ALIAS or bagian[1].lower() not in DOMPET_ALIAS:
        return ('Format: /transfer <asal> <tujuan> <nominal> [catatan]\n'
                'Dompet: bni, mandiri, tunai\n'
                'Contoh:\n'
                '• /transfer bni mandiri 200rb\n'
                '• /transfer tunai bni 300rb\n'
                '• /transfer mandiri tunai 100rb')

    asal = DOMPET_ALIAS[bagian[0].lower()]
    tujuan = DOMPET_ALIAS[bagian[1].lower()]
    if asal == tujuan:
        return 'Dompet asal dan tujuan tidak boleh sama (' + asal + ').'
    try:
        nominal = baca_nominal(bagian[2])
    except ValueError:
        return NOMINAL_TAK_TERBACA
    if nominal <= 0:
        return 'Nominal harus lebih dari 0.'
    catatan = ' '.join(bagian[3:]).strip()
    bank_kena = _mengandung_bank_terlarang(catatan)
    if bank_kena:
        return ('Catatan transfer tidak boleh mengandung kata "' + bank_kena +
                '" agar rumus saldo bank di spreadsheet tetap akurat.')

    jejak = []
    ringkasan = 'Transfer ' + asal + ' → ' + tujuan + ' ' + rupiah(nominal)
    if tanggal:
        ringkasan += ' untuk ' + tanggal.strftime('%d/%m')
    try:
        tab, baris_tercatat = simpan_transfer(
            asal, tujuan, nominal, catatan=catatan, jejak=jejak, tanggal=tanggal)
    finally:
        if jejak:
            simpan_riwayat(ringkasan, jejak)

    detail = [f'• {tabel} baris {no}: {label} ({rupiah(val)})'
              for tabel, no, label, val in baris_tercatat]
    pesan = ('🔄 Transfer ' + asal + ' → ' + tujuan + ' ' + rupiah(nominal) +
             (' untuk ' + tanggal.strftime('%d/%m/%Y') if tanggal else '') +
             ' (tab ' + tab + ')\n' + '\n'.join(detail))
    if tanggal and (tanggal.year, tanggal.month) != (hari_ini.year, hari_ini.month):
        return pesan
    return pesan + _info_saldo_dompet(asal, tujuan)


def perintah_cari_transaksi(argumen):
    """/cari_transaksi <kata kunci> [bulan] -> cari pengeluaran di spreadsheet & hitung totalnya."""
    bagian = argumen.split()
    if not bagian:
        return ('Format: /cari_transaksi <kata kunci> [nama bulan]\n'
                'Contoh:\n'
                '• /cari_transaksi kopi\n'
                '• /cari_transaksi shopeefood november\n'
                '• /cari_transaksi laundry oktober')

    nama_tab = nama_bulan()
    if len(bagian) >= 2:
        bulan_akhir = _baca_nama_tab_bulan(bagian[-1])
        if bulan_akhir is not None:
            nama_tab = bulan_akhir
            bagian = bagian[:-1]

    kata = [k.lower() for k in bagian]
    semua = ambil_semua_pengeluaran(nama_tab)
    cocok = [
        item for item in semua
        if all(k in (item[1] + ' ' + item[0]).lower() for k in kata)
    ]
    if not cocok:
        return f'🔎 Tidak ditemukan transaksi "{ " ".join(bagian) }" di tab {nama_tab}.'

    cocok.sort(key=lambda x: (x[2] or date.min, x[4]), reverse=True)
    total_nilai = sum(x[3] for x in cocok)
    tampil = cocok[:20]

    baris = [
        f'🔎 Hasil "{ " ".join(bagian) }" di tab {nama_tab}',
        f'Ditemukan {len(cocok)} transaksi · Total: {rupiah(total_nilai)}',
    ]
    for kat, nama, tgl, nilai, _ in tampil:
        tgl_str = tgl.strftime('%d/%m') if tgl else '--/--'
        baris.append(f'• {tgl_str} | {kat}: {nama} {rupiah(nilai)}')
    if len(cocok) > len(tampil):
        baris.append(f'… dan {len(cocok) - len(tampil)} transaksi lainnya.')
    return '\n'.join(baris)


def perintah_grafik(argumen):
    """/grafik [mingguan|nama_bulan] -> kirim gambar grafik ringkasan pengeluaran."""
    sisa = argumen.strip().lower()
    kini = sekarang()
    tab_ini = nama_bulan()

    if sisa in ('mingguan', 'minggu', '7hari', '7', 'pekan'):
        transaksi = ambil_semua_pengeluaran(tab_ini)
        # Kalau awal bulan (< tanggal 7), gabungkan bulan lalu bila tabnya tersedia
        if kini.day < 7:
            try:
                transaksi = ambil_semua_pengeluaran(nama_bulan(1)) + transaksi
            except TabTidakAda:
                pass
        caption, gambar_b64 = buat_grafik_mingguan(transaksi, kini=kini)
        return {'teks': caption, 'gambar_base64': gambar_b64, 'caption': caption}

    nama_tab = tab_ini
    if sisa:
        bulan_cari = _baca_nama_tab_bulan(sisa)
        if bulan_cari is None:
            return ('Format: /grafik [mingguan | nama_bulan]\n'
                    'Contoh: /grafik, /grafik mingguan, atau /grafik oktober')
        nama_tab = bulan_cari

    total = ambil_total_kategori(nama_tab)
    transaksi = ambil_semua_pengeluaran(nama_tab)
    batas = baca_batas() if nama_tab == tab_ini else {}
    caption, gambar_b64 = buat_grafik_bulanan(
        nama_tab, total, transaksi, batas=batas, kini=kini, tab_bulan_ini=(nama_tab == tab_ini))
    return {'teks': caption, 'gambar_base64': gambar_b64, 'caption': caption}


# ---------------------------------------------------------------------------
# Tagihan / pengeluaran rutin bulanan (/tagihan)
# ---------------------------------------------------------------------------

def _format_metode_tagihan(metode):
    if metode == 'qris_mandiri':
        return 'QRIS Mandiri'
    if metode == 'qris_bni':
        return 'QRIS BNI'
    return 'Tunai'


def _tanggal_jatuh_tempo_bulan(tgl_tagihan, tahun, bulan):
    maks_hari = calendar.monthrange(tahun, bulan)[1]
    return min(max(1, int(tgl_tagihan)), maks_hari)


def _daftar_tagihan():
    daftar = baca_tagihan()
    if not daftar:
        return 'Belum ada tagihan rutin.\n' + PETUNJUK_TAGIHAN
    bulan_ini = sekarang().strftime('%Y-%m')
    urutan = sorted(daftar, key=lambda t: (t.get('tanggal', 1), t.get('nama', '').lower()))
    total_rutin = sum(int(t.get('nominal', 0)) for t in urutan)
    baris = [f'🔁 Tagihan Rutin Bulanan ({len(urutan)}) · Total {rupiah(total_rutin)}/bln']
    for no, t in enumerate(urutan, 1):
        lunas = t.get('terakhir_dibayar') == bulan_ini
        ikon = '✅' if lunas else '⏳'
        mode = ' [auto]' if t.get('auto') else ''
        baris.append(
            f'{no}. {ikon} Tgl {t["tanggal"]}: {t["nama"]} {rupiah(t["nominal"])} '
            f'({t["kategori"]}, {_format_metode_tagihan(t.get("metode", "tunai"))}{mode})'
        )
    baris.append('Bayar: /tagihan bayar <nomor/nama> · Hapus: /tagihan hapus <nomor/nama>')
    return '\n'.join(baris)


def _cari_entri_tagihan(kunci, daftar_urut):
    kunci = kunci.strip()
    if not kunci:
        return None, 'Tulis nomor atau nama tagihan. Lihat daftar: /tagihan'
    if kunci.isdigit():
        no = int(kunci)
        if not 1 <= no <= len(daftar_urut):
            return None, f'Nomor {kunci} tidak ada. Lihat /tagihan'
        return daftar_urut[no - 1], None
    cocok = [t for t in daftar_urut if kunci.lower() in t.get('nama', '').lower()]
    persis = [t for t in cocok if t.get('nama', '').lower() == kunci.lower()]
    if len(persis) == 1:
        cocok = persis
    if not cocok:
        return None, f'Tagihan "{kunci}" tidak ditemukan. Lihat /tagihan'
    if len(cocok) > 1:
        baris = ['Ada beberapa tagihan yang cocok. Tulis lebih lengkap:']
        baris += ['• ' + t['nama'] for t in cocok]
        return None, '\n'.join(baris)
    return cocok[0], None


def _tambah_tagihan(bagian):
    """Parse [<tgl 1-31>, <nominal>, ...opsi..., <nama...>] lalu simpan ke tagihan.json."""
    if len(bagian) < 3 or not bagian[0].isdigit():
        return 'Format salah.\n' + PETUNJUK_TAGIHAN
    tgl = int(bagian[0])
    if not 1 <= tgl <= 31:
        return 'Tanggal tagihan harus antara 1 sampai 31.'
    try:
        nominal = baca_nominal(bagian[1])
    except ValueError:
        return NOMINAL_TAK_TERBACA
    if nominal <= 0:
        return 'Nominal harus lebih dari 0.'

    kategori = 'Mingguan&Bulanan'
    metode = 'tunai'
    auto = False
    sisa = bagian[2:]
    while sisa:
        tok = sisa[0].lower()
        if tok in KATEGORI_ALIAS:
            kategori = KATEGORI_ALIAS[tok]
            sisa = sisa[1:]
        elif tok in ('qris', 'qris_bni'):
            metode = 'qris_bni'
            sisa = sisa[1:]
            if sisa and sisa[0].lower() in BANK_ALIAS:
                metode = 'qris_mandiri' if sisa[0].lower() == 'mandiri' else 'qris_bni'
                sisa = sisa[1:]
        elif tok == 'qris_mandiri':
            metode = 'qris_mandiri'
            sisa = sisa[1:]
        elif tok in ('tunai', 'cash'):
            metode = 'tunai'
            sisa = sisa[1:]
        elif tok in ('auto', 'otomatis'):
            auto = True
            sisa = sisa[1:]
        else:
            break

    nama = ' '.join(sisa).strip()
    if not nama:
        return 'Tulis nama tagihannya.\n' + PETUNJUK_TAGIHAN

    entri = {
        'nama': nama,
        'nominal': nominal,
        'kategori': kategori,
        'tanggal': tgl,
        'metode': metode,
        'auto': auto,
        'terakhir_dibayar': None,
        'terakhir_diingatkan': None,
    }

    def simpan(daftar):
        for i, t in enumerate(daftar):
            if t.get('nama', '').lower() == nama.lower():
                entri['terakhir_dibayar'] = t.get('terakhir_dibayar')
                entri['terakhir_diingatkan'] = t.get('terakhir_diingatkan')
                daftar[i] = entri
                return 'diubah'
        daftar.append(entri)
        return 'ditambah'

    aksi = ubah_tagihan(simpan)
    mode_teks = 'otomatis dicatat' if auto else 'diingatkan'
    return (f'🔁 Tagihan rutin {aksi}: {nama} {rupiah(nominal)}\n'
            f'📅 Setiap tanggal {tgl} · {kategori} · {_format_metode_tagihan(metode)} ({mode_teks})')


def _catat_bayar_tagihan(tagihan, nominal_override=None):
    nominal = nominal_override if nominal_override is not None else int(tagihan['nominal'])
    kat_alias = next((a for a, k in KATEGORI_ALIAS.items() if k == tagihan['kategori']), 'bulanan')
    metode = tagihan.get('metode', 'tunai')
    if metode == 'qris_mandiri':
        arg = f'mandiri {nominal} {kat_alias} {tagihan["nama"]}'
        pesan, kategori = catat_pengeluaran(arg, '/qris', True)
    elif metode == 'qris_bni':
        arg = f'{nominal} {kat_alias} {tagihan["nama"]}'
        pesan, kategori = catat_pengeluaran(arg, '/qris', True)
    else:
        arg = f'{nominal} {kat_alias} {tagihan["nama"]}'
        pesan, kategori = catat_pengeluaran(arg, '/out', False)
    return pesan, kategori


def perintah_tagihan(argumen):
    """/tagihan | /tagihan tambah ... | /tagihan bayar <no/nama> [nominal] | /tagihan hapus <no/nama>"""
    bagian = argumen.split()
    if not bagian:
        return _daftar_tagihan()

    sub = bagian[0].lower()
    if sub == 'tambah':
        return _tambah_tagihan(bagian[1:])
    if sub.isdigit():
        return _tambah_tagihan(bagian)

    urutan = sorted(baca_tagihan(), key=lambda t: (t.get('tanggal', 1), t.get('nama', '').lower()))

    if sub in ('hapus', 'batal'):
        terpilih, galat = _cari_entri_tagihan(' '.join(bagian[1:]), urutan)
        if galat:
            return galat

        def hapus(daftar):
            for i, t in enumerate(daftar):
                if t.get('nama', '').lower() == terpilih['nama'].lower():
                    del daftar[i]
                    return True
            return False

        ubah_tagihan(hapus)
        return '🗑️ Tagihan rutin dihapus: ' + terpilih['nama']

    if sub == 'bayar':
        if len(bagian) < 2:
            return 'Format: /tagihan bayar <nomor atau nama> [nominal_beda]'
        nominal_override = None
        kunci_bagian = bagian[1:]
        if len(kunci_bagian) >= 2:
            try:
                kandidat = baca_nominal(kunci_bagian[-1])
                if kandidat > 0:
                    nominal_override = kandidat
                    kunci_bagian = kunci_bagian[:-1]
            except ValueError:
                pass
        terpilih, galat = _cari_entri_tagihan(' '.join(kunci_bagian), urutan)
        if galat:
            return galat
        pesan, kategori = _catat_bayar_tagihan(terpilih, nominal_override=nominal_override)
        if kategori is None:
            return pesan
        bulan_ini = sekarang().strftime('%Y-%m')

        def tandai(daftar):
            for t in daftar:
                if t.get('nama', '').lower() == terpilih['nama'].lower():
                    t['terakhir_dibayar'] = bulan_ini
                    t['terakhir_diingatkan'] = bulan_ini
                    break

        ubah_tagihan(tandai)
        return '🔁 Tagihan dibayar:\n' + pesan + info_sisa([kategori])

    return 'Format tidak dikenal.\n' + PETUNJUK_TAGIHAN


def pengingat_tagihan():
    """Untuk penjadwal: ingatkan atau otomatis catat tagihan rutin yang jatuh tempo bulan ini."""
    kini = sekarang()
    if kini.hour < JAM_PENGINGAT_HARI:
        return None
    bulan_ini = kini.strftime('%Y-%m')
    hari_ini = kini.strftime('%Y-%m-%d')
    daftar = baca_tagihan()
    if not daftar:
        return None

    pesan_keluar = []
    diubah_bayar = set()
    diubah_ingat = set()

    for t in daftar:
        if t.get('terakhir_dibayar') == bulan_ini:
            continue
        jatuh_tempo = _tanggal_jatuh_tempo_bulan(t.get('tanggal', 1), kini.year, kini.month)
        if kini.day < jatuh_tempo:
            continue
        nama = t.get('nama', '')
        if t.get('auto'):
            if t.get('terakhir_gagal_auto') == hari_ini:
                continue
            try:
                pesan_catat, kat = _catat_bayar_tagihan(t)
            except Exception as e:
                traceback.print_exc()
                # Tandai gagal hari ini agar tidak spam error tiap menit
                pesan_keluar.append(
                    f'⚠️ Tagihan otomatis "{nama}" belum bisa dicatat ({type(e).__name__}). '
                    f'Catat manual dengan /tagihan bayar {nama}'
                )

                def tandai_gagal(isi, target=nama):
                    for item in isi:
                        if item.get('nama', '').lower() == target.lower():
                            item['terakhir_gagal_auto'] = hari_ini
                            break

                ubah_tagihan(tandai_gagal)
                continue
            if kat is not None:
                diubah_bayar.add(nama.lower())
                pesan_keluar.append('🔁 Tagihan otomatis dicatat:\n' + pesan_catat + info_sisa([kat]))
        else:
            if t.get('terakhir_diingatkan') == bulan_ini:
                continue
            diubah_ingat.add(nama.lower())
            pesan_keluar.append(
                f'💳 Pengingat tagihan rutin (tgl {t["tanggal"]}): '
                f'{nama} {rupiah(t["nominal"])} ({t["kategori"]}, '
                f'{_format_metode_tagihan(t.get("metode", "tunai"))})\n'
                f'Ketik /tagihan bayar {nama} untuk langsung mencatat.'
            )

    if diubah_bayar or diubah_ingat:
        def perbarui(isi):
            for item in isi:
                nm = item.get('nama', '').lower()
                if nm in diubah_bayar:
                    item['terakhir_dibayar'] = bulan_ini
                    item['terakhir_diingatkan'] = bulan_ini
                elif nm in diubah_ingat:
                    item['terakhir_diingatkan'] = bulan_ini

        ubah_tagihan(perbarui)

    return '\n\n'.join(pesan_keluar) if pesan_keluar else None


def perintah_saldo(argumen):
    """/saldo -> sisa uang dan saldo bank, dibaca dari hasil rumus di spreadsheet."""
    tab, angka = ambil_saldo()
    bagian_saldo = ('Sisa Uang', 'BNI', 'Mandiri')
    baris = []
    for label in bagian_saldo:
        if label in angka:
            baris.append(label + ': ' + rupiah(int(round(angka[label]))))
    # Total saldo = uang tunai + semua rekening. Hanya ditampilkan kalau ketiganya terbaca,
    # supaya totalnya tidak menyesatkan kalau ada satu angka yang tidak ketemu di sheet.
    if all(label in angka for label in bagian_saldo):
        total = sum(int(round(angka[label])) for label in bagian_saldo)
        baris.append('Total saldo: ' + rupiah(total))
    if 'Pengeluaran' in angka:
        baris.append('Pengeluaran bulan ini: ' + rupiah(int(round(angka['Pengeluaran']))))
    if not baris:
        return ('Angka saldo tidak ditemukan di tab ' + tab + '. '
                'Cek posisi tabel Hasil Akhir dan Sisa Saldo Bank '
                '(RENTANG_HASIL_AKHIR dan RENTANG_SALDO_BANK di penyimpanan.py).')
    return '💰 Saldo (tab ' + tab + ')\n' + '\n'.join(baris)


def teks_selisih(angka):
    if angka == 0:
        return 'sama'
    return ('+' if angka > 0 else '-') + rupiah(abs(angka))


def perintah_rekap(argumen):
    """/rekap -> total per kategori bulan ini (baris TOTAL di sheet) dan selisihnya
    dengan bulan lalu."""
    tab_ini = nama_bulan()
    tab_lalu = nama_bulan(1)
    ini = ambil_total_kategori(tab_ini)           # TabTidakAda ditangani proses_pesan
    try:
        lalu = ambil_total_kategori(tab_lalu)
    except TabTidakAda:
        lalu = None                               # bulan lalu belum ada, lewati perbandingan

    baris = ['📊 Rekap ' + tab_ini]
    for kategori, nilai in ini.items():
        teks = kategori + ': ' + rupiah(nilai)
        if lalu is not None:
            teks += ' (' + teks_selisih(nilai - lalu[kategori]) + ')'
        baris.append(teks)

    total_ini = sum(ini.values())
    teks = 'Total: ' + rupiah(total_ini)
    if lalu is None:
        baris.append(teks)
        baris.append('')
        baris.append('Tab ' + tab_lalu + ' belum ada, jadi belum ada perbandingan.')
    else:
        total_lalu = sum(lalu.values())
        baris.append(teks + ' (' + teks_selisih(total_ini - total_lalu) + ')')
        baris.append('')
        baris.append('Tanda +/- = selisih dengan ' + tab_lalu + ' (total ' + rupiah(total_lalu) + '). '
                     + tab_ini + ' baru berjalan sampai tanggal ' + str(sekarang().day) +
                     ', ' + tab_lalu + ' sudah satu bulan penuh.')
    return '\n'.join(baris)


def teks_pintasan(kunci, isi):
    kategori, nama, harga = isi
    return kunci + ' → ' + nama + ', ' + kategori + ', ' + (rupiah(harga) if harga else 'harga belum diisi')


def perintah_pintasan(argumen):
    """/pintasan                          -> daftar pintasan sekarang
    /pintasan galon 20rb mingguan Air Galon -> tambah atau ubah
    /pintasan hapus galon                -> hapus"""
    bagian = argumen.split()
    daftar = daftar_pintasan()

    if not bagian:
        if not daftar:
            return 'Belum ada pintasan.\n' + PETUNJUK_PINTASAN
        baris = ['📌 Pintasan (' + str(len(daftar)) + ')']
        baris += [teks_pintasan(k, v) for k, v in daftar.items()]
        baris += ['',
                  'Pakai: ketik namanya saja (galon), atau /out galon, /qris galon [nominal]',
                  PETUNJUK_PINTASAN]
        return '\n'.join(baris)

    kunci = bagian[0].lower()
    if kunci == 'hapus':
        if len(bagian) != 2:
            return 'Format: /pintasan hapus <nama>'
        kunci = bagian[1].lower()
        if kunci not in daftar:
            return 'Pintasan ' + kunci + ' tidak ada. Lihat daftarnya: /pintasan'
        del daftar[kunci]
        tulis_pengaturan('pintasan', daftar)
        return '🗑️ Pintasan ' + kunci + ' dihapus.'

    if len(bagian) == 1:
        if kunci in daftar:
            return '📌 ' + teks_pintasan(kunci, daftar[kunci])
        return 'Format:\n' + PETUNJUK_PINTASAN
    if not kunci.isalnum() or kunci[0].isdigit() or kunci in NAMA_TERLARANG:
        return ('Nama pintasan harus satu kata (huruf atau angka, tidak diawali angka) dan bukan ' +
                ', '.join(sorted(NAMA_TERLARANG)) + '.\n' + PETUNJUK_PINTASAN)
    try:
        harga = baca_nominal(bagian[1])
    except ValueError:
        return NOMINAL_TAK_TERBACA
    if harga <= 0:
        return 'Harga harus lebih dari 0.'

    lama = daftar.get(kunci)
    kategori = lama[0] if lama else 'Jajan'
    sisa = bagian[2:]
    if sisa and sisa[0].lower() in KATEGORI_ALIAS:
        kategori = KATEGORI_ALIAS[sisa[0].lower()]
        sisa = sisa[1:]
    if sisa:
        nama = ' '.join(sisa)
    else:
        nama = lama[1] if lama else kunci.capitalize()

    daftar[kunci] = (kategori, nama, harga)
    tulis_pengaturan('pintasan', daftar)
    return '📌 ' + teks_pintasan(kunci, daftar[kunci]) + (' (diubah)' if lama else ' (ditambah)')


def perintah_batas(argumen):
    """/batas                -> batas bulanan dan pemakaian bulan ini
    /batas jajan 500rb       -> atur batas
    /batas hapus jajan       -> hapus batas"""
    bagian = argumen.split()
    batas = baca_batas()

    if not bagian:
        if not batas:
            return 'Belum ada batas bulanan.\n' + PETUNJUK_BATAS
        try:
            total = ambil_total_kategori(nama_bulan())
        except Exception:
            traceback.print_exc()
            total = {}
        baris = ['🎯 Batas bulanan']
        for kategori, nilai in batas.items():
            if kategori in total:
                baris.append(kategori + ': ' + rupiah(total[kategori]) + ' dari ' + rupiah(nilai) +
                             ' (' + str(int(total[kategori] * 100 / nilai)) + '%)')
            else:
                baris.append(kategori + ': ' + rupiah(nilai))
        baris += ['',
                  'Peringatan muncul di balasan pencatatan mulai ' +
                  str(round(AMBANG_PERINGATAN * 100)) + '%.',
                  PETUNJUK_BATAS]
        return '\n'.join(baris)

    if bagian[0].lower() == 'hapus':
        if len(bagian) != 2 or bagian[1].lower() not in KATEGORI_ALIAS:
            return 'Format: /batas hapus <kategori>'
        kategori = KATEGORI_ALIAS[bagian[1].lower()]
        if kategori not in batas:
            return 'Batas ' + kategori + ' memang belum ada.'
        del batas[kategori]
        tulis_pengaturan('batas', batas)
        return '🗑️ Batas ' + kategori + ' dihapus.'

    if len(bagian) != 2 or bagian[0].lower() not in KATEGORI_ALIAS:
        return 'Format:\n' + PETUNJUK_BATAS
    kategori = KATEGORI_ALIAS[bagian[0].lower()]
    try:
        nominal = baca_nominal(bagian[1])
    except ValueError:
        return NOMINAL_TAK_TERBACA
    if nominal <= 0:
        return 'Nominal harus lebih dari 0.'
    batas[kategori] = nominal
    tulis_pengaturan('batas', batas)
    return ('🎯 Batas ' + kategori + ' per bulan: ' + rupiah(nominal) +
            ' (peringatan mulai ' + str(round(AMBANG_PERINGATAN * 100)) + '%)')


def perintah_undo(argumen):
    """/undo -> batalkan catatan terakhir (bisa diulang untuk catatan sebelumnya)."""
    try:
        hasil = batalkan_terakhir()
    except RiwayatBerubah as e:
        return ('Catatan terakhir (' + str(e) + ') sudah berbeda dari yang kutulis, '
                'jadi tidak kuhapus. Cek dan hapus manual di spreadsheet.')
    if hasil is None:
        return 'Tidak ada catatan yang bisa dibatalkan.'
    ringkasan, waktu = hasil
    kapan = datetime.fromisoformat(waktu).strftime('%d/%m %H:%M')
    return '↩️ Dibatalkan: ' + ringkasan + ' (dicatat ' + kapan + ')'


def perintah_hariini(argumen):
    """/hariini -> semua pengeluaran bertanggal hari ini beserta totalnya
    (untuk mengecek "tadi sudah kecatat belum?")."""
    daftar = ambil_pengeluaran_hari_ini()          # TabTidakAda ditangani proses_pesan
    tanggal = sekarang().strftime('%d/%m')
    if not daftar:
        return '📋 Belum ada pengeluaran yang tercatat hari ini (' + tanggal + ').'
    baris = ['📋 Pengeluaran hari ini (' + tanggal + ')']
    for kategori, nama, nilai in daftar:
        baris.append('• ' + kategori + ': ' + nama + ' ' + rupiah(nilai))
    baris.append('Total: ' + rupiah(sum(nilai for _, _, nilai in daftar)))
    return '\n'.join(baris)


def perintah_riwayat(argumen):
    """/riwayat [jumlah] -> catatan terakhir, yang terbaru di atas. Urutannya sama dengan
    urutan /undo membatalkan, jadi baris nomor 1 adalah yang akan dihapus /undo."""
    teks = argumen.strip()
    jumlah = RIWAYAT_TAMPIL
    if teks:
        if not teks.isdigit() or int(teks) < 1:
            return ('Format: /riwayat [jumlah]\n'
                    'Contoh: /riwayat 10 (maksimal ' + str(RIWAYAT_MAKS) + ')')
        jumlah = min(int(teks), RIWAYAT_MAKS)
    daftar = ambil_riwayat(jumlah)
    if not daftar:
        return 'Riwayat kosong, tidak ada catatan yang bisa dibatalkan.'
    baris = ['🕘 ' + str(len(daftar)) + ' catatan terakhir (nomor 1 = yang dibatalkan /undo berikutnya)']
    for nomor, entri in enumerate(daftar, 1):
        kapan = datetime.fromisoformat(entri['waktu']).strftime('%d/%m %H:%M')
        baris.append(str(nomor) + '. ' + entri['ringkasan'] + ' (dicatat ' + kapan + ')')
    return '\n'.join(baris)


def baca_tanggal(kata):
    hari_ini = sekarang().date()
    kata = kata.lower()
    if kata == 'hariini':
        return hari_ini
    if kata == 'besok':
        return hari_ini + timedelta(days=1)
    if kata == 'lusa':
        return hari_ini + timedelta(days=2)
    hari, bulan = kata.split('/')[:2]          # contoh: 14/10
    tgl = hari_ini.replace(month=int(bulan), day=int(hari))
    if tgl < hari_ini:                         # sudah lewat, berarti tahun depan
        tgl = tgl.replace(year=tgl.year + 1)
    return tgl


def buat_tugas(judul, mulai):
    """Buat tugas Google Tasks dengan deadline di tanggal `mulai`. Google Tasks hanya
    menyimpan tanggal, jadi jamnya ditulis di catatan tugas. Kalau gagal, acara kalender
    yang sudah dibuat tidak terpengaruh; hasilnya berupa baris tambahan untuk balasan."""
    try:
        tambah_tugas(judul, mulai.date(), 'Deadline pukul ' + mulai.strftime('%H:%M') + ' WIB')
    except TugasGagal as e:
        return '\n⚠️ Tugas di Google Tasks belum dibuat: ' + str(e)
    except Exception as e:
        traceback.print_exc()
        return '\n⚠️ Tugas di Google Tasks belum dibuat (' + type(e).__name__ + ')'
    return '\n✅ Tugas dengan deadline ' + mulai.strftime('%d/%m/%Y') + ' dibuat di Google Tasks'


def buat_penanda(judul, mulai):
    """Penanda merah "Due: judul" seharian di tanggal deadline. Ini acara kalender biasa
    yang meniru tampilan deadline di Google Tasks (isian Deadline yang asli tidak bisa
    dibuat lewat API). Kalau gagal, acara dan tugasnya tidak terpengaruh."""
    try:
        tambah_penanda_deadline(judul, mulai.date())
    except Exception as e:
        traceback.print_exc()
        return '\n⚠️ Penanda merah belum dibuat (' + type(e).__name__ + ')'
    return '\n🔴 Penanda merah "Due: ' + judul + '" dibuat di kalender'


def perintah_todo(argumen):
    bagian = argumen.split(maxsplit=2)
    if len(bagian) < 3:
        return 'Format: /todo <hariini|besok|lusa|14/10> <jam> <judul>\nContoh: /todo besok 15:00 kumpul DML'
    try:
        tanggal = baca_tanggal(bagian[0])
        jam, menit = bagian[1].replace('.', ':').split(':')
        mulai = datetime(tanggal.year, tanggal.month, tanggal.day,
                         int(jam), int(menit), tzinfo=WIB)
    except ValueError:
        return 'Tanggal atau jam tidak terbaca. Contoh: /todo besok 15:00 kumpul DML'
    tambah_event(bagian[2], mulai)
    waktu = mulai.strftime('%d/%m/%Y %H:%M')
    return ('📅 Ditambahkan: ' + bagian[2] + ' (' + waktu + ')' + buat_tugas(bagian[2], mulai) +
            buat_penanda(bagian[2], mulai))


# ---------------------------------------------------------------------------
# /deadline dan pengingatnya
# ---------------------------------------------------------------------------

def baca_jam(kata):
    """'23:59' atau '23.59' -> time. None kalau tidak terbaca."""
    cocok = re.fullmatch(r'(\d{1,2})[:.](\d{2})', kata)
    if not cocok:
        return None
    jam, menit = int(cocok.group(1)), int(cocok.group(2))
    if jam > 23 or menit > 59:
        return None
    return time(jam, menit)


def baca_tanggal_deadline(kata):
    """'hariini', 'besok', 'lusa', nama hari ('jumat' = Jumat terdekat, bisa hari ini),
    '30/10' atau '30/10/2026' -> date. None kalau tidak terbaca."""
    hari_ini = sekarang().date()
    kata = kata.lower()
    if kata == 'hariini':
        return hari_ini
    if kata == 'besok':
        return hari_ini + timedelta(days=1)
    if kata == 'lusa':
        return hari_ini + timedelta(days=2)
    if kata in HARI_KATA:
        return hari_ini + timedelta(days=(HARI_KATA[kata] - hari_ini.weekday()) % 7)
    cocok = re.fullmatch(r'(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?', kata)
    if not cocok:
        return None
    hari, bulan, tahun = int(cocok.group(1)), int(cocok.group(2)), cocok.group(3)
    try:
        if tahun:
            tahun = int(tahun)
            return date(tahun + 2000 if tahun < 100 else tahun, bulan, hari)
        tanggal = date(hari_ini.year, bulan, hari)
        if tanggal < hari_ini:                  # sudah lewat tahun ini, berarti tahun depan
            tanggal = date(hari_ini.year + 1, bulan, hari)
        return tanggal
    except ValueError:
        return None


def baca_deadline_dari_teks(argumen):
    """'DML 3 jumat 23:59' atau 'jumat 23:59 DML 3' -> (judul, kata tanggal, jam), atau None."""
    bagian = argumen.split()
    if len(bagian) < 3:
        return None
    jam = baca_jam(bagian[-1])
    if jam is not None and baca_tanggal_deadline(bagian[-2]) is not None:
        return ' '.join(bagian[:-2]), bagian[-2], jam
    jam = baca_jam(bagian[1])
    if jam is not None and baca_tanggal_deadline(bagian[0]) is not None:
        return ' '.join(bagian[2:]), bagian[0], jam
    return None


def waktu_kirim(tingkat, waktu):
    """Kapan pengingat `tingkat` dikirim untuk deadline pada `waktu`."""
    _, jenis, jumlah = tingkat
    if jenis == 'hari':
        return datetime.combine(waktu.date() - timedelta(days=jumlah),
                                time(JAM_PENGINGAT_HARI, 0), tzinfo=WIB)
    return waktu - timedelta(hours=jumlah)


def teks_waktu(waktu):
    """'Jum 30/10 23:59' (tahunnya ikut ditulis kalau bukan tahun ini)."""
    waktu = waktu.astimezone(WIB)
    format_tanggal = '%d/%m' if waktu.year == sekarang().year else '%d/%m/%Y'
    return HARI_PENDEK[waktu.weekday()] + ' ' + waktu.strftime(format_tanggal + ' %H:%M')


def teks_sisa(waktu, kini):
    """Sisa waktu sampai `waktu`: '45 menit lagi', '5 jam 20 menit lagi', '4 hari lagi'."""
    menit_total = int((waktu - kini).total_seconds() // 60)
    if menit_total < 1:
        return 'sekarang'
    if menit_total < 60:
        return str(menit_total) + ' menit lagi'
    if menit_total < 24 * 60:
        jam, menit = divmod(menit_total, 60)
        return str(jam) + ' jam' + (' ' + str(menit) + ' menit' if menit else '') + ' lagi'
    hari, sisa_menit = divmod(menit_total, 24 * 60)
    jam = sisa_menit // 60
    return str(hari) + ' hari' + (' ' + str(jam) + ' jam' if jam and hari < 3 else '') + ' lagi'


def deadline_mendatang():
    """Deadline yang belum lewat, dari yang paling dekat: [(waktu, entri), ...]."""
    kini = sekarang()
    hasil = []
    for d in baca_deadline():
        try:
            waktu = datetime.fromisoformat(d['waktu'])
            judul = d['judul']
        except (KeyError, ValueError, TypeError):
            continue                                # entri rusak dilewati
        if waktu > kini and judul:
            hasil.append((waktu, d))
    hasil.sort(key=lambda pasangan: pasangan[0])
    return hasil


def daftar_deadline():
    daftar = deadline_mendatang()
    if not daftar:
        return 'Belum ada deadline.\n' + PETUNJUK_DEADLINE
    kini = sekarang()
    baris = ['⏳ Deadline (' + str(len(daftar)) + ')']
    for nomor, (waktu, d) in enumerate(daftar, 1):
        baris.append(str(nomor) + '. ' + d['judul'] + ' — ' + teks_waktu(waktu) +
                     ' (' + teks_sisa(waktu, kini) + ')')
    baris.append('Selesai: /deadline selesai <nomor atau judul>')
    return '\n'.join(baris)


def _sinkron_deadline_kalender(judul, waktu):
    """Buat penanda merah 'Due: <judul>' + acara pengingat 30 menit di Google Calendar.
    Mengembalikan (list_event_ids, baris_status_atau_None). Tidak melempar error ke pemanggil."""
    if not config.DEADLINE_KE_KALENDER or not config.CALENDAR_ID:
        return [], None
    event_ids = []
    deskripsi = 'Deadline pukul ' + waktu.strftime('%H:%M') + ' WIB (dibuat dari /deadline Bot WA)'
    try:
        id_penanda = tambah_penanda_deadline(judul, waktu.date(), deskripsi=deskripsi)
        if id_penanda:
            event_ids.append(id_penanda)
        # Acara 30 menit yang berakhir tepat pada waktu deadline (tanpa menyeberang hari sebelumnya)
        mulai_acara = waktu - timedelta(minutes=30)
        if mulai_acara.date() != waktu.date():
            mulai_acara = waktu
        id_acara = tambah_event(
            '⏰ Deadline: ' + judul, mulai_acara,
            durasi_menit=30, warna_id='11', deskripsi=deskripsi)
        if id_acara:
            event_ids.append(id_acara)
    except Exception as e:
        traceback.print_exc()
        if event_ids:
            return event_ids, '📅 Tersinkron sebagian ke Google Calendar (' + type(e).__name__ + ')'
        return [], '⚠️ Belum tersinkron ke Google Calendar (' + type(e).__name__ + ')'
    return event_ids, '📅 Tersinkron ke Google Calendar (penanda merah + acara)'


def tambah_deadline(argumen):
    bagian_raw = argumen.split()
    hanya_lokal = False
    bagian_bersih = []
    for tok in bagian_raw:
        if tok.lower() in ('--lokal', 'lokal', '--tanpa-kalender'):
            hanya_lokal = True
        else:
            bagian_bersih.append(tok)
    arg_bersih = ' '.join(bagian_bersih)

    hasil = baca_deadline_dari_teks(arg_bersih)
    if hasil is None:
        return 'Format deadline tidak terbaca.\n' + PETUNJUK_DEADLINE
    judul, kata_tanggal, jam = hasil
    judul = judul[:MAKS_JUDUL_DEADLINE]
    kini = sekarang()
    waktu = datetime.combine(baca_tanggal_deadline(kata_tanggal), jam, tzinfo=WIB)
    if waktu <= kini:
        if kata_tanggal.lower() not in HARI_KATA:
            return 'Waktu itu (' + teks_waktu(waktu) + ') sudah lewat. Cek tanggal dan jamnya.'
        waktu += timedelta(days=7)           # "jumat" setelah jam Jumat lewat = Jumat depan

    # Tingkat pengingat yang waktunya sudah lewat langsung dianggap terkirim.
    terkirim = [t[0] for t in TINGKAT_DEADLINE if waktu_kirim(t, waktu) <= kini]
    entri = {
        'judul': judul,
        'waktu': waktu.isoformat(timespec='seconds'),
        'terkirim': terkirim,
        'calendar_event_ids': [],
    }

    def tambah(daftar):
        if any(d.get('judul', '').lower() == judul.lower() and d.get('waktu') == entri['waktu']
               for d in daftar):
            return False
        daftar.append(entri)
        return True

    if not ubah_deadline(tambah):
        return 'Deadline itu sudah ada: ' + judul + ' (' + teks_waktu(waktu) + ')'

    status_cal = None
    if not hanya_lokal:
        event_ids, status_cal = _sinkron_deadline_kalender(judul, waktu)
        if event_ids:
            def simpan_ids(daftar):
                for d in daftar:
                    if d.get('judul') == judul and d.get('waktu') == entri['waktu']:
                        d['calendar_event_ids'] = event_ids
                        break

            ubah_deadline(simpan_ids)

    akan = [teks_waktu(waktu_kirim(t, waktu)) for t in TINGKAT_DEADLINE if t[0] not in terkirim]
    baris = ['✅ Deadline dicatat: ' + judul,
             '📌 ' + teks_waktu(waktu) + ' (' + teks_sisa(waktu, kini) + ')']
    if akan:
        baris.append('🔔 Pengingat: ' + ' · '.join(akan))
    else:
        baris.append('🔔 Tidak ada pengingat tersisa, deadline-nya sudah terlalu dekat.')
    if status_cal:
        baris.append(status_cal)
    return '\n'.join(baris)


def selesaikan_deadline(kunci):
    kunci = kunci.strip()
    if not kunci:
        return 'Format: /deadline selesai <nomor atau judul>\nLihat nomornya dengan /deadline'
    daftar = deadline_mendatang()
    if kunci.isdigit():
        nomor = int(kunci)
        if not 1 <= nomor <= len(daftar):
            return 'Nomor ' + kunci + ' tidak ada. Lihat daftar dengan /deadline'
        cocok = [daftar[nomor - 1]]
    else:
        cocok = [p for p in daftar if kunci.lower() in p[1]['judul'].lower()]
        persis = [p for p in cocok if p[1]['judul'].lower() == kunci.lower()]
        if len(persis) == 1:
            cocok = persis
        if not cocok:
            return 'Tidak ada deadline yang judulnya mengandung "' + kunci + '". Lihat /deadline'
        if len(cocok) > 1:
            baris = ['Ada ' + str(len(cocok)) + ' deadline yang cocok. Tulis judulnya lebih lengkap:']
            baris += ['• ' + p[1]['judul'] + ' (' + teks_waktu(p[0]) + ')' for p in cocok]
            return '\n'.join(baris)
    _, terpilih = cocok[0]

    def hapus(isi):
        for i, d in enumerate(isi):
            if d.get('judul') == terpilih['judul'] and d.get('waktu') == terpilih['waktu']:
                del isi[i]
                return True
        return False

    ubah_deadline(hapus)

    event_ids = terpilih.get('calendar_event_ids') or []
    terhapus_cal = 0
    for eid in event_ids:
        try:
            if hapus_event(eid):
                terhapus_cal += 1
        except Exception:
            traceback.print_exc()

    pesan = '✅ Deadline selesai: ' + terpilih['judul']
    if terhapus_cal:
        pesan += '\n📅 Penanda di Google Calendar ikut dihapus.'
    return pesan


def sinkron_semua_deadline():
    """Sinkronkan semua deadline mendatang yang belum punya event di Google Calendar."""
    if not config.CALENDAR_ID:
        return 'CALENDAR_ID belum diisi di file .env.'
    daftar = deadline_mendatang()
    if not daftar:
        return 'Belum ada deadline aktif untuk disinkronkan.'
    berhasil = 0
    gagal = 0
    for waktu, d in daftar:
        if d.get('calendar_event_ids'):
            continue
        ids, _ = _sinkron_deadline_kalender(d['judul'], waktu)
        if ids:
            berhasil += 1

            def simpan_ids(isi, judul=d['judul'], w=d['waktu'], eids=ids):
                for item in isi:
                    if item.get('judul') == judul and item.get('waktu') == w:
                        item['calendar_event_ids'] = eids
                        break

            ubah_deadline(simpan_ids)
        else:
            gagal += 1
    if berhasil == 0 and gagal == 0:
        return '📅 Semua deadline aktif sudah tersinkron ke Google Calendar.'
    pesan = f'📅 Sinkronisasi selesai: {berhasil} deadline ditambahkan ke Google Calendar.'
    if gagal:
        pesan += f' ({gagal} gagal, cek log terminal)'
    return pesan


def perintah_deadline(argumen):
    """/deadline DML 3 jumat 23:59 | /deadline | /deadline selesai <no/judul> | /deadline sinkron"""
    bagian = argumen.split()
    if not bagian:
        return daftar_deadline()
    sub = bagian[0].lower()
    if sub in ('selesai', 'hapus', 'batal'):
        return selesaikan_deadline(' '.join(bagian[1:]))
    if sub in ('sinkron', 'sync'):
        return sinkron_semua_deadline()
    return tambah_deadline(argumen)


def teks_pengingat_deadline(d, waktu, tingkat, kini):
    ikon = '🚨' if tingkat[1] == 'jam' else '⏳'
    terlambat = kini - waktu_kirim(tingkat, waktu) > timedelta(hours=3)   # bot sempat mati
    if tingkat[1] == 'hari' and not terlambat:
        sisa = 'besok' if tingkat[2] == 1 else str(tingkat[2]) + ' hari lagi'
    else:
        sisa = teks_sisa(waktu, kini)
    return (ikon + ' Deadline ' + d['judul'] + ': ' + sisa + ' (' + teks_waktu(waktu) + ')\n'
            'Kalau sudah selesai: /deadline selesai ' + d['judul'])


def pengingat_deadline():
    """Untuk penjadwal: teks pengingat deadline yang jatuh tempo sekarang, atau None.
    Tiap tingkat hanya dikirim sekali. Kalau beberapa tingkat sekaligus jatuh tempo
    (misalnya bot sempat mati), hanya yang paling mendesak yang dikirim. Deadline yang
    sudah lewat dibuang dari daftar."""
    kini = sekarang()

    def periksa(daftar):
        pesan = []
        daftar[:] = [d for d in daftar if _belum_lewat(d, kini)]
        for d in daftar:
            waktu = datetime.fromisoformat(d['waktu'])
            terkirim = d.setdefault('terkirim', [])
            jatuh = [t for t in TINGKAT_DEADLINE
                     if t[0] not in terkirim and waktu_kirim(t, waktu) <= kini]
            if not jatuh:
                continue
            terkirim.extend(t[0] for t in jatuh)
            mendesak = max(jatuh, key=lambda t: waktu_kirim(t, waktu))
            pesan.append(teks_pengingat_deadline(d, waktu, mendesak, kini))
        return pesan

    pesan = ubah_deadline(periksa)
    return '\n\n'.join(pesan) if pesan else None


def _belum_lewat(d, kini):
    try:
        return datetime.fromisoformat(d['waktu']) > kini
    except (KeyError, ValueError, TypeError):
        return False                                # entri rusak ikut dibuang


# ---------------------------------------------------------------------------
# Pengingat cepat sekali jalan (/ingatkan)
# ---------------------------------------------------------------------------

def _baca_durasi_relatif(kata):
    """'30m', '2j', '2jam', '45menit', '1j30m' -> timedelta, atau None."""
    k = kata.strip().lower()
    m = re.fullmatch(r'(?:(\d+)(?:jam|j))?(?:(\d+)(?:menit|mnt|m))?', k)
    if not m or (not m.group(1) and not m.group(2)):
        return None
    jam = int(m.group(1) or 0)
    menit = int(m.group(2) or 0)
    total = jam * 60 + menit
    if total < 1 or total > 60 * 24 * 30:
        return None
    return timedelta(minutes=total)


def pengingat_cepat_aktif():
    """Pengingat cepat yang belum jatuh tempo, urut paling dekat: [(waktu, entri), ...]."""
    kini = sekarang()
    hasil = []
    for item in baca_pengingat_cepat():
        try:
            waktu = datetime.fromisoformat(item['waktu'])
            pesan = item['pesan']
        except (KeyError, ValueError, TypeError):
            continue
        if waktu > kini and pesan:
            hasil.append((waktu, item))
    hasil.sort(key=lambda x: x[0])
    return hasil


def perintah_ingatkan(argumen):
    """/ingatkan 30m angkat jemuran | /ingatkan 21:00 matikan kompor | /ingatkan | /ingatkan hapus <no/kata>"""
    bagian = argumen.split()
    if not bagian:
        daftar = pengingat_cepat_aktif()
        if not daftar:
            return 'Belum ada pengingat cepat.\n' + PETUNJUK_INGATKAN
        kini = sekarang()
        baris = [f'⏰ Pengingat aktif ({len(daftar)})']
        for no, (waktu, item) in enumerate(daftar, 1):
            baris.append(f'{no}. {item["pesan"]} — {teks_waktu(waktu)} ({teks_sisa(waktu, kini)})')
        baris.append('Hapus: /ingatkan hapus <nomor atau kata>')
        return '\n'.join(baris)

    sub = bagian[0].lower()
    if sub in ('hapus', 'batal', 'selesai'):
        kunci = ' '.join(bagian[1:]).strip()
        if not kunci:
            return 'Format: /ingatkan hapus <nomor atau kata>\nLihat nomornya dengan /ingatkan'
        daftar = pengingat_cepat_aktif()
        if kunci.isdigit():
            no = int(kunci)
            if not 1 <= no <= len(daftar):
                return f'Nomor {kunci} tidak ada. Lihat /ingatkan'
            cocok = [daftar[no - 1]]
        else:
            cocok = [p for p in daftar if kunci.lower() in p[1]['pesan'].lower()]
            if not cocok:
                return f'Tidak ada pengingat yang mengandung "{kunci}". Lihat /ingatkan'
            if len(cocok) > 1:
                baris = ['Ada beberapa pengingat yang cocok, pakai nomor dari /ingatkan:']
                baris += [f'• {p[1]["pesan"]} ({teks_waktu(p[0])})' for p in cocok]
                return '\n'.join(baris)
        _, terpilih = cocok[0]

        def hapus(isi):
            for i, item in enumerate(isi):
                if item.get('pesan') == terpilih['pesan'] and item.get('waktu') == terpilih['waktu']:
                    del isi[i]
                    return True
            return False

        ubah_pengingat_cepat(hapus)
        return '🗑️ Pengingat dihapus: ' + terpilih['pesan']

    kini = sekarang()
    waktu = None
    pesan_list = None

    # 1. Durasi relatif: /ingatkan 30m angkat jemuran
    durasi = _baca_durasi_relatif(bagian[0])
    if durasi is not None and len(bagian) >= 2:
        waktu = (kini + durasi).replace(second=0, microsecond=0)
        if waktu <= kini:
            waktu = kini + durasi
        pesan_list = bagian[1:]
    # 2. Jam saja: /ingatkan 21:00 matikan kompor (hari ini, atau besok jika jam sudah lewat)
    elif baca_jam(bagian[0]) is not None and len(bagian) >= 2:
        jam_obj = baca_jam(bagian[0])
        waktu = datetime.combine(kini.date(), jam_obj, tzinfo=WIB)
        if waktu <= kini:
            waktu += timedelta(days=1)
        pesan_list = bagian[1:]
    # 3. Tanggal/hari + jam: /ingatkan besok 09:00 bayar kos
    elif (len(bagian) >= 3 and baca_tanggal_deadline(bagian[0]) is not None
          and baca_jam(bagian[1]) is not None):
        tgl = baca_tanggal_deadline(bagian[0])
        jam_obj = baca_jam(bagian[1])
        waktu = datetime.combine(tgl, jam_obj, tzinfo=WIB)
        if waktu <= kini:
            if bagian[0].lower() in HARI_KATA:
                waktu += timedelta(days=7)
            else:
                return f'Waktu itu ({teks_waktu(waktu)}) sudah lewat. Cek tanggal dan jamnya.'
        pesan_list = bagian[2:]

    if waktu is None or not pesan_list:
        return 'Format pengingat tidak terbaca.\n' + PETUNJUK_INGATKAN

    pesan = ' '.join(pesan_list).strip()[:200]
    entri = {'pesan': pesan, 'waktu': waktu.isoformat(timespec='seconds')}

    def tambah(daftar):
        daftar.append(entri)
        return True

    ubah_pengingat_cepat(tambah)
    return (f'⏰ Pengingat disimpan: {pesan}\n'
            f'📌 {teks_waktu(waktu)} ({teks_sisa(waktu, kini)})')


def pengingat_cepat():
    """Untuk penjadwal: kirim & hapus pengingat cepat (/ingatkan) yang sudah jatuh tempo."""
    kini = sekarang()

    def periksa(daftar):
        jatuh = []
        sisa = []
        for item in daftar:
            try:
                waktu = datetime.fromisoformat(item['waktu'])
                pesan = item['pesan']
            except (KeyError, ValueError, TypeError):
                continue
            if waktu <= kini:
                jatuh.append((waktu, pesan))
            else:
                sisa.append(item)
        daftar[:] = sisa
        return jatuh

    jatuh = ubah_pengingat_cepat(periksa)
    if not jatuh:
        return None
    jatuh.sort(key=lambda x: x[0])
    return '\n'.join(f'⏰ Pengingat: {pesan} ({waktu.astimezone(WIB).strftime("%H:%M")})'
                     for waktu, pesan in jatuh)


# ---------------------------------------------------------------------------
# Pesan pagi
# ---------------------------------------------------------------------------

def _ke_datetime(nilai):
    if isinstance(nilai, datetime):
        return nilai
    if isinstance(nilai, str) and len(nilai) > 10:      # "2026-10-26" saja = tanpa jam
        try:
            return datetime.fromisoformat(nilai)
        except ValueError:
            return None
    return None


def _awalan_jam(nilai):
    waktu = _ke_datetime(nilai)
    if waktu is None:
        return ''
    if waktu.tzinfo is not None:
        waktu = waktu.astimezone(WIB)
    return waktu.strftime('%H:%M') + ' '


def format_event(e):
    """Satu event dari kalender.event_hari_ini() -> 'HH:MM judul'. Mengenali event Google
    Calendar (dict dengan 'summary' dan 'start'), pasangan (judul, waktu) atau (waktu,
    judul), dan teks biasa. Bentuk lain ditampilkan apa adanya."""
    if isinstance(e, str):
        return e
    if isinstance(e, dict):
        judul = e.get('summary') or e.get('judul') or e.get('title') or '(tanpa judul)'
        mulai = e.get('start', e.get('mulai', e.get('waktu')))
        if isinstance(mulai, dict):
            if mulai.get('dateTime'):
                mulai = mulai['dateTime']
            else:                                   # event seharian hanya punya 'date'
                return '(seharian) ' + str(judul)
        return _awalan_jam(mulai) + str(judul)
    if isinstance(e, (tuple, list)) and len(e) >= 2:
        if isinstance(e[0], str) and re.fullmatch(r'\d{1,2}:\d{2}', e[0]):
            return e[0] + ' ' + str(e[1])               # bentuk dari kalender.event_hari_ini()
        if e[0] == 'seharian':
            return '(seharian) ' + str(e[1])
        if _ke_datetime(e[1]) is not None:
            return _awalan_jam(e[1]) + str(e[0])
        return _awalan_jam(e[0]) + str(e[1])
    return str(e)


def teks_agenda_hari_ini():
    try:
        daftar = list(event_hari_ini())
    except Exception:
        traceback.print_exc()
        return '📅 Agenda hari ini: tidak terbaca dari kalender.'
    if not daftar:
        return '📅 Agenda hari ini: kosong.'
    return '📅 Agenda hari ini:\n' + '\n'.join('• ' + format_event(e) for e in daftar)


def ambil_cuaca():
    """Ringkasan cuaca hari ini dari Open-Meteo (gratis, tanpa API key), atau None kalau gagal."""
    if requests is None:
        return None
    nama, lintang, bujur = LOKASI_CUACA
    try:
        r = requests.get('https://api.open-meteo.com/v1/forecast', timeout=10, params={
            'latitude': lintang, 'longitude': bujur, 'timezone': 'Asia/Jakarta',
            'forecast_days': 1,
            'daily': 'weather_code,temperature_2m_max,temperature_2m_min,'
                     'precipitation_probability_max'})
        r.raise_for_status()
        harian = r.json()['daily']
        kode = harian['weather_code'][0]
        suhu_min = harian['temperature_2m_min'][0]
        suhu_maks = harian['temperature_2m_max'][0]
        hujan = harian['precipitation_probability_max'][0]
    except (requests.exceptions.RequestException, KeyError, IndexError, TypeError, ValueError):
        traceback.print_exc()
        return None
    deskripsi, ikon = CUACA_WMO.get(kode, ('cuaca tidak diketahui', '🌡️'))
    teks = ikon + ' Cuaca ' + nama + ': ' + deskripsi
    if suhu_min is not None and suhu_maks is not None:
        teks += ', ' + str(round(suhu_min)) + '–' + str(round(suhu_maks)) + '°C'
    if hujan is not None:
        teks += ', peluang hujan ' + str(round(hujan)) + '%'
        if hujan >= 50:
            teks += ' (bawa payung)'
    return teks


def teks_deadline_pagi():
    daftar = deadline_mendatang()[:JUMLAH_DEADLINE_PAGI]
    if not daftar:
        return None
    kini = sekarang()
    baris = ['⏳ Deadline terdekat:']
    for waktu, d in daftar:
        baris.append('• ' + d['judul'] + ' — ' + teks_waktu(waktu) + ' (' + teks_sisa(waktu, kini) + ')')
    return '\n'.join(baris)


def teks_pengingat_pagi():
    kini = sekarang()
    hari_ini = [(w, i) for w, i in pengingat_cepat_aktif() if w.astimezone(WIB).date() == kini.date()]
    if not hari_ini:
        return None
    baris = ['⏰ Pengingat hari ini:']
    for waktu, item in hari_ini:
        baris.append('• ' + waktu.astimezone(WIB).strftime('%H:%M') + ' ' + item['pesan'])
    return '\n'.join(baris)


def teks_tagihan_pagi():
    kini = sekarang()
    bulan_ini = kini.strftime('%Y-%m')
    jatuh = []
    for t in baca_tagihan():
        if t.get('terakhir_dibayar') == bulan_ini:
            continue
        tgl_jt = _tanggal_jatuh_tempo_bulan(t.get('tanggal', 1), kini.year, kini.month)
        if kini.day <= tgl_jt <= kini.day + 1:
            kapan = 'hari ini' if tgl_jt == kini.day else 'besok'
            jatuh.append(f'• {t["nama"]} {rupiah(t["nominal"])} ({kapan})')
    if not jatuh:
        return None
    return '🔁 Tagihan mendekati jatuh tempo:\n' + '\n'.join(jatuh)


def teks_uang_pagi():
    try:
        tab, angka = ambil_saldo()
    except TabTidakAda as e:
        return ('💰 Saldo: tab bulan ' + str(e) + ' belum ada di spreadsheet '
                '(duplikat tab Template dulu).')
    except Exception:
        traceback.print_exc()
        return '💰 Saldo: tidak terbaca dari spreadsheet.'
    bagian_saldo = ('Sisa Uang', 'BNI', 'Mandiri')
    bagian = []
    if 'Sisa Uang' in angka:
        bagian.append('Sisa uang ' + rupiah(int(round(angka['Sisa Uang']))))
    if all(label in angka for label in bagian_saldo):
        bagian.append('Total saldo ' + rupiah(sum(int(round(angka[l])) for l in bagian_saldo)))
    if not bagian:
        return '💰 Saldo: angkanya tidak ditemukan di tab ' + tab + '.'
    return '💰 ' + ' · '.join(bagian)


def susun_pesan_pagi():
    """Pesan pagi lengkap. Tiap bagian diambil sendiri-sendiri: yang gagal diganti catatan
    singkat, bagian lain tetap tampil."""
    kini = sekarang()
    bagian = ['☀️ Selamat pagi! ' + NAMA_HARI[kini.weekday()] + ', ' + str(kini.day) + ' ' +
              BULAN[kini.month - 1] + ' ' + str(kini.year),
              teks_agenda_hari_ini(),
              ambil_cuaca() or '🌡️ Cuaca: tidak terbaca.']
    for ekstra in (teks_deadline_pagi(), teks_pengingat_pagi(), teks_tagihan_pagi()):
        if ekstra:
            bagian.append(ekstra)
    bagian.append(teks_uang_pagi())
    return '\n\n'.join(bagian)


def perintah_pagi(argumen):
    """/pagi -> pesan pagi sekarang juga (tidak mempengaruhi pengiriman otomatis)."""
    return susun_pesan_pagi()


def pengingat_pagi():
    """Untuk penjadwal: pesan pagi sekali sehari, antara JAM_PAGI dan JAM_PAGI_BATAS."""
    waktu = sekarang()
    if not JAM_PAGI <= waktu.hour < JAM_PAGI_BATAS:
        return None
    hari = waktu.strftime('%Y-%m-%d')
    if status_sudah('pesan_pagi', hari):
        return None
    teks = susun_pesan_pagi()
    status_tandai('pesan_pagi', hari)
    return teks


# ---------------------------------------------------------------------------
# Catatan cepat ke Google Docs
# ---------------------------------------------------------------------------

CATATAN_BAWAAN = 5          # /catatan tanpa angka
CATATAN_MAKS_TAMPIL = 15    # paling banyak catatan yang dikirim balik sekali jalan
CATATAN_MAKS_PANJANG = 300  # catatan yang lebih panjang dipotong saat ditampilkan


def format_daftar_catatan(judul, daftar):
    baris = [judul]
    for isi in daftar:
        if len(isi) > CATATAN_MAKS_PANJANG:
            isi = isi[:CATATAN_MAKS_PANJANG - 1].rstrip() + '…'
        baris.append(isi)
    return '\n\n'.join(baris)


def perintah_catat(argumen):
    """/catat <teks> (atau /ide <teks>) -> simpan ke Google Docs. Boleh beberapa baris."""
    teks = argumen.strip()
    if not teks:
        return ('Format: /catat <catatan>\n'
                'Contoh: /catat #game ide puzzle bentuk geometri\n'
                'Boleh beberapa baris. Lihat lagi dengan /catatan atau /cari <kata>')
    if len(teks) > MAKS_CATATAN:
        return ('Catatannya terlalu panjang (' + str(len(teks)) + ' karakter, maksimal ' +
                str(MAKS_CATATAN) + '). Belum ada yang disimpan.')
    tambah_catatan(teks, sekarang())
    baris_pertama = teks.splitlines()[0].strip()
    ringkas = baris_pertama if len(baris_pertama) <= 80 else baris_pertama[:79].rstrip() + '…'
    if len(teks.splitlines()) > 1:
        ringkas += ' …'
    return '📝 Tercatat: ' + ringkas


def perintah_catatan(argumen):
    """/catatan [jumlah] -> catatan terakhir (bawaan 5)."""
    sisa = argumen.strip()
    jumlah = CATATAN_BAWAAN
    if sisa:
        if not sisa.isdigit() or int(sisa) < 1:
            return 'Format: /catatan [jumlah]\nContoh: /catatan 10'
        jumlah = min(int(sisa), CATATAN_MAKS_TAMPIL)
    entri = ambil_entri()
    if not entri:
        return 'Belum ada catatan di dokumen. Mulai dengan /catat <ide>'
    terakhir = entri[-jumlah:]
    return format_daftar_catatan(
        '📝 Catatan terakhir (' + str(len(terakhir)) + ' dari ' + str(len(entri)) + ')', terakhir)


def perintah_cari(argumen):
    """/cari <kata> -> catatan yang memuat semua kata itu (huruf besar/kecil tidak dibedakan)."""
    kata = argumen.lower().split()
    if not kata:
        return 'Format: /cari <kata>\nContoh: /cari puzzle   (beberapa kata harus muncul semuanya)'
    cocok = [e for e in ambil_entri() if all(k in e.lower() for k in kata)]
    if not cocok:
        return 'Tidak ada catatan yang mengandung "' + ' '.join(kata) + '".'
    tampil = cocok[-CATATAN_MAKS_TAMPIL:]
    judul = '🔎 ' + str(len(cocok)) + ' catatan mengandung "' + ' '.join(kata) + '"'
    if len(tampil) < len(cocok):
        judul += ' (menampilkan ' + str(len(tampil)) + ' terbaru)'
    return format_daftar_catatan(judul, tampil)


def teks_bulan_ini():
    """Total pengeluaran bulan ini per kategori; kategori yang punya batas (/batas)
    ditampilkan beserta persentasenya. Melempar TabTidakAda kalau tabnya belum ada."""
    tab = nama_bulan()
    total = ambil_total_kategori(tab)
    batas = baca_batas()
    baris = ['📊 Bulan ini (' + tab + '): ' + rupiah(sum(total.values()))]
    for kategori, nilai in total.items():
        if nilai == 0 and kategori not in batas:
            continue
        teks = '• ' + kategori + ' ' + rupiah(nilai)
        if batas.get(kategori):
            teks += (' dari ' + rupiah(batas[kategori]) + ' (' +
                     str(int(nilai * 100 / batas[kategori])) + '%)')
            if nilai > batas[kategori]:
                teks += ' 🚨 melewati batas'
            elif nilai >= batas[kategori] * AMBANG_PERINGATAN:
                teks += ' ⚠️'
        baris.append(teks)
    return '\n'.join(baris)


def susun_rekap_harian():
    """Rekap pengeluaran hari ini: rincian per kategori, total hari ini, posisi bulan ini
    (beserta batasnya), dan sisa uang. Melempar TabTidakAda kalau tab bulannya belum ada."""
    kini = sekarang()
    daftar = ambil_pengeluaran_hari_ini()
    bagian = ['🌙 Rekap pengeluaran ' + NAMA_HARI[kini.weekday()] + ', ' + str(kini.day) + ' ' +
              BULAN[kini.month - 1] + ' ' + str(kini.year)]
    if daftar:
        per_kategori = {}
        for kategori, nama, nilai in daftar:
            per_kategori.setdefault(kategori, []).append((nama, nilai))
        baris = []
        for kategori, isi in per_kategori.items():
            baris.append(kategori + ' (' + rupiah(sum(n for _, n in isi)) + ')')
            baris += ['• ' + nama + ' ' + rupiah(nilai) for nama, nilai in isi]
        baris.append('Total hari ini: ' + rupiah(sum(n for _, _, n in daftar)))
        bagian.append('\n'.join(baris))
    else:
        bagian.append('Tidak ada pengeluaran yang tercatat hari ini.')
    bagian.append(teks_bulan_ini())
    bagian.append(teks_uang_pagi())
    return '\n\n'.join(bagian)


def perintah_malam(argumen):
    """/malam -> rekap pengeluaran hari ini sekarang juga (tidak mempengaruhi pengiriman otomatis)."""
    return susun_rekap_harian()


def perintah_bantuan(argumen):
    pintasan = ', '.join(daftar_pintasan()) or 'belum ada'
    return ('📚 Daftar Perintah Bot WA\n\n'
            '💸 Pengeluaran & Pemasukan:\n'
            '• /out [tgl] <nominal> [kat] <barang> (atau langsung: 13rb lotek)\n'
            '• /qris [mandiri] [tgl] <nominal> [kat] <barang>\n'
            '• /in [tgl] <nominal> <sumber>  |  /in <bni|mandiri> <nominal> [ket]\n'
            '• /transfer <asal> <tujuan> <nominal> (alias /tf; dompet: bni, mandiri, tunai)\n'
            '• /tarik [bni|mandiri] <nominal>\n'
            '• /topup <bni|mandiri> <nominal> [ket]\n'
            '• /pintasan (' + pintasan + ')\n'
            '• /batas (batas bulanan per kategori)\n'
            '• /tagihan (tagihan rutin bulanan, alias /rutin)\n\n'
            '📊 Laporan & Pencarian:\n'
            '• /saldo · /rekap · /hariini\n'
            '• /grafik [mingguan | nama_bulan]\n'
            '• /cari_transaksi <kata> [bulan]\n'
            '• /riwayat · /undo\n\n'
            '⏰ Produktivitas & Catatan:\n'
            '• /ingatkan <30m|21:00|besok 09:00> <pesan> (alias /remind)\n'
            '• /deadline <judul> <tgl> <jam> (otomatis sinkron ke Google Calendar)\n'
            '• /todo <tgl> <jam> <judul>\n'
            '• /pagi · /malam\n'
            '• /catat (alias /ide) · /catatan · /cari\n\n'
            '✨ Input Cerdas:\n'
            '• Kirim foto struk belanja untuk scan otomatis\n'
            '• Kirim voice note untuk catat/tanya lewat suara\n'
            '• Ketik kalimat santai (contoh: "tadi bayar parkir 5rb qris")')


PERINTAH = {
    '/out': perintah_out,
    '/qris': perintah_qris,
    '/in': perintah_in,
    '/masuk': perintah_in,
    '/transfer': perintah_transfer,
    '/tf': perintah_transfer,
    '/tarik': perintah_tarik,
    '/topup': perintah_topup,
    '/saldo': perintah_saldo,
    '/rekap': perintah_rekap,
    '/grafik': perintah_grafik,
    '/chart': perintah_grafik,
    '/cari_transaksi': perintah_cari_transaksi,
    '/caritransaksi': perintah_cari_transaksi,
    '/transaksi': perintah_cari_transaksi,
    '/tagihan': perintah_tagihan,
    '/rutin': perintah_tagihan,
    '/pintasan': perintah_pintasan,
    '/batas': perintah_batas,
    '/hariini': perintah_hariini,
    '/riwayat': perintah_riwayat,
    '/undo': perintah_undo,
    '/ingatkan': perintah_ingatkan,
    '/remind': perintah_ingatkan,
    '/deadline': perintah_deadline,
    '/pagi': perintah_pagi,
    '/malam': perintah_malam,
    '/catat': perintah_catat,
    '/ide': perintah_catat,
    '/catatan': perintah_catatan,
    '/cari': perintah_cari,
    '/todo': perintah_todo,
    '/bantuan': perintah_bantuan,
}

# Perintah hanya-baca (aman dijalankan langsung dari voice note tanpa perlu konfirmasi ya/batal).
_PERINTAH_BACA = {
    '/saldo', '/rekap', '/hariini', '/riwayat', '/grafik', '/chart',
    '/cari_transaksi', '/caritransaksi', '/transaksi', '/pagi', '/malam',
    '/catatan', '/cari', '/bantuan',
}


def pesan_kesalahan(e):
    """Exception dari sebuah perintah -> teks untuk pengguna. Harus dipanggil
    dari dalam blok except (supaya traceback-nya bisa dicetak)."""
    if isinstance(e, TabelPenuh):
        tabel = str(e) or 'Pemasukan'
        return ('Tabel ' + tabel + ' bulan ini sudah penuh (baris 10-31), jadi belum ada '
                'yang dicatat. Sisipkan baris kosong di dalam tabelnya '
                '(di antara baris 10 dan 31 supaya rumusnya ikut melebar), lalu kirim ulang.')
    if isinstance(e, TabTidakAda):
        nama = str(e)
        if nama == 'harian':
            return ('Tab harian belum ada di spreadsheet. Buat tab baru bernama harian '
                    '(baris 1, kolom A-C: tanggal, langkah, menit_layar).')
        return ('Tab bulan ' + nama + ' belum ada di spreadsheet. '
                'Duplikat tab Template, lalu ganti namanya menjadi ' + nama + '.')
    if isinstance(e, CatatanGagal):
        return '⚠️ Catatan belum tersimpan: ' + str(e)
    if isinstance(e, GrafikGagal):
        return '⚠️ Grafik tidak bisa dibuat: ' + str(e)
    if isinstance(e, InputAIGagal):
        return '⚠️ ' + str(e)
    traceback.print_exc()          # detail lengkap muncul di terminal Python
    if isinstance(e, GAGAL_JARINGAN + GAGAL_KALENDER):
        return ('📶 Koneksi ke Google terputus, padahal sudah dicoba ulang beberapa kali. '
                'Kalau tadi mencatat pengeluaran, cek dulu dengan /riwayat sebelum mengirim ulang, '
                'supaya tidak tercatat dua kali. /todo aman dikirim ulang: acara, tugas, dan '
                'penandanya tidak dibuat dobel. Untuk /catat, lihat dokumennya dulu sebelum kirim ulang.')
    return '⚠️ Error: ' + type(e).__name__ + ': ' + str(e)


def baca_pesan_bebas(baris):
    """Pesan tanpa '/': '13rb lotek', 'galon', 'qris 13rb lotek', 'qris mandiri 15rb kopi',
    'out 5rb es teh', 'kemarin 13rb lotek' -> (argumen untuk catat_pengeluaran, lewat_qris).
    None kalau pesannya tidak mirip pengeluaran. Kata pertama (setelah qris/out, bank opsional,
    dan tanggal, kalau ada) harus berupa nominal atau nama pintasan, jadi obrolan biasa
    tidak ikut tercatat."""
    bagian = baris.split()
    if not bagian:
        return None
    lewat_qris = False
    if bagian[0].lower() in ('qris', 'out'):
        lewat_qris = bagian[0].lower() == 'qris'
        bagian = bagian[1:]
        if not bagian:
            return None
    mulai = 0
    for _ in range(2):
        if mulai >= len(bagian):
            return None
        tok = bagian[mulai].lower()
        if lewat_qris and tok in BANK_ALIAS:
            mulai += 1
        elif kata_tanggal(tok):
            mulai += 1
        else:
            break
    if mulai >= len(bagian):
        return None
    pertama = bagian[mulai].lower()
    if pertama not in daftar_pintasan():
        try:
            baca_nominal(pertama)
        except ValueError:
            return None
    return ' '.join(bagian), lewat_qris


def _bungkus_hasil(hasil):
    """Normalisasi hasil fungsi perintah (str atau dict gambar) ke dict standar."""
    if isinstance(hasil, dict):
        return {
            'teks': hasil.get('teks', ''),
            'gambar_base64': hasil.get('gambar_base64'),
            'caption': hasil.get('caption') or hasil.get('teks', ''),
        }
    return {'teks': str(hasil), 'gambar_base64': None, 'caption': None}


def jalankan_baris(baris, kategori_banyak=None, izinkan_nlp=False):
    """Satu baris pesan -> teks balasan (atau dict gambar untuk /grafik).
    Exception sengaja tidak ditangkap di sini.
    kategori_banyak (set) hanya diisi kalau pesannya terdiri dari beberapa baris."""
    if baris.startswith('/'):
        perintah, argumen = (baris.split(None, 1) + [''])[:2]
        fungsi = PERINTAH.get(perintah.lower())
        if fungsi is None:
            return 'Perintah tidak dikenal. Coba: /bantuan'
        if kategori_banyak is not None:
            if fungsi not in (perintah_out, perintah_qris):
                return perintah.lower() + ' tidak bisa digabung dalam pesan beberapa baris. Kirim terpisah.'
            return fungsi(argumen, kategori_banyak=kategori_banyak)
        return fungsi(argumen)

    bebas = baca_pesan_bebas(baris)
    if bebas is not None:
        argumen, lewat_qris = bebas
        return catat_dan_lapor(argumen, '/qris' if lewat_qris else '/out', lewat_qris,
                               nominal_minimal=NOMINAL_MINIMAL_BEBAS,
                               kategori_banyak=kategori_banyak)

    if izinkan_nlp and kategori_banyak is None:
        daftar_p = daftar_pintasan()
        perintah_nlp = parse_bahasa_natural_lokal(baris, pintasan=daftar_p)
        if perintah_nlp:
            hasil = jalankan_baris(perintah_nlp)
            if isinstance(hasil, dict):
                return hasil
            return '🤖 Dipahami: ' + perintah_nlp + '\n' + hasil

        hasil_ai = parse_bahasa_natural_ai(baris, pintasan=daftar_p, tanggal_hari_ini=sekarang().date())
        if hasil_ai and hasil_ai.get('perintah'):
            daftar_cmd = hasil_ai['perintah']
            if len(daftar_cmd) == 1:
                hasil = jalankan_baris(daftar_cmd[0])
                if isinstance(hasil, dict):
                    return hasil
                return '🤖 Dipahami: ' + daftar_cmd[0] + '\n' + hasil
            gabung = proses_banyak(daftar_cmd)
            return '🤖 Dipahami:\n' + gabung

    return ('Pesan tidak dikenali. Catat pengeluaran dengan: 13rb lotek '
            '(atau qris 13rb lotek, atau kalimat santai seperti "tadi bayar parkir 5rb qris").\n'
            'Daftar perintah: /bantuan')


def proses_banyak(baris_pesan):
    """Pesan berisi beberapa baris pengeluaran: tiap baris diproses sendiri-sendiri.
    Sisa uang dan peringatan batas ditampilkan sekali di akhir, bukan di setiap baris."""
    kategori = set()
    hasil = []
    for nomor, baris in enumerate(baris_pesan, 1):
        try:
            teks = jalankan_baris(baris, kategori)
            if isinstance(teks, dict):
                teks = teks.get('teks', '')
        except TabTidakAda as e:
            hasil.append(str(nomor) + '. ' + pesan_kesalahan(e))
            hasil.append('Baris berikutnya tidak diproses.')
            break
        except Exception as e:
            teks = pesan_kesalahan(e)
        hasil.append(str(nomor) + '. ' + teks)
    return '\n'.join(hasil) + (info_sisa(kategori) if kategori else '')


# ---------------------------------------------------------------------------
# Konfirmasi & Media (Scan Struk Foto dan Voice Note)
# ---------------------------------------------------------------------------

def _draft_aktif(pengirim):
    draft = ambil_konfirmasi(pengirim)
    if not draft:
        return None
    try:
        dibuat = datetime.fromisoformat(draft['dibuat'])
    except (KeyError, ValueError, TypeError):
        hapus_konfirmasi(pengirim)
        return None
    if sekarang() - dibuat > timedelta(minutes=KONFIRMASI_KADALUARSA_MENIT):
        hapus_konfirmasi(pengirim)
        return None
    return draft


def _tanggal_struk_token(tanggal_iso):
    if not tanggal_iso:
        return ''
    try:
        tgl = date.fromisoformat(tanggal_iso)
    except ValueError:
        return ''
    hari_ini = sekarang().date()
    if tgl == hari_ini or tgl > hari_ini or tgl.year != hari_ini.year:
        return ''
    return tgl.strftime('%d/%m')


def _format_perintah_item_struk(item, metode, tgl_token):
    kat_alias = next((a for a, k in KATEGORI_ALIAS.items() if k == item['kategori']), 'jajan')
    bagian = []
    if metode == 'qris_mandiri':
        bagian.extend(['/qris', 'mandiri'])
    elif metode == 'qris_bni':
        bagian.append('/qris')
    else:
        bagian.append('/out')
    if tgl_token:
        bagian.append(tgl_token)
    bagian.append(str(int(item['nominal'])))
    bagian.append(kat_alias)
    bagian.append(item['nama'])
    return ' '.join(bagian)


def _tangani_konfirmasi(teks, pengirim):
    """Tangani jawaban konfirmasi ('ya', 'ya qris', 'gabung', 'batal', dst.) jika ada
    draft aktif dari scan struk atau voice note. Mengembalikan dict hasil atau None."""
    draft = _draft_aktif(pengirim)
    if not draft:
        return None

    low = ' '.join(teks.strip().lower().split())
    if low in ('batal', 'cancel', 'tidak', 'nggak', 'gak', 'ga', 'no'):
        hapus_konfirmasi(pengirim)
        return _bungkus_hasil('❌ Dibatalkan, tidak ada yang dicatat.')

    jenis = draft.get('jenis')
    if jenis == 'struk':
        peta_metode = {
            'ya': (False, None),
            'oke': (False, None),
            'ok': (False, None),
            'simpan': (False, None),
            'ya qris': (False, 'qris_bni'),
            'qris': (False, 'qris_bni'),
            'ya qris bni': (False, 'qris_bni'),
            'ya qris mandiri': (False, 'qris_mandiri'),
            'qris mandiri': (False, 'qris_mandiri'),
            'ya tunai': (False, 'tunai'),
            'tunai': (False, 'tunai'),
            'gabung': (True, None),
            'gabung qris': (True, 'qris_bni'),
            'gabung qris bni': (True, 'qris_bni'),
            'gabung qris mandiri': (True, 'qris_mandiri'),
            'gabung tunai': (True, 'tunai'),
        }
        if low not in peta_metode:
            return None
        gabung, metode_override = peta_metode[low]
        hapus_konfirmasi(pengirim)

        metode = metode_override or draft.get('metode', 'tunai')
        tgl_token = _tanggal_struk_token(draft.get('tanggal'))
        items = draft.get('items') or []
        if gabung or len(items) == 1:
            kat_utama = items[0]['kategori'] if items else 'Jajan'
            nama_gabung = draft.get('toko') or (items[0]['nama'] if items else 'Belanja')
            if len(items) == 1 and not gabung:
                nama_gabung = items[0]['nama']
            nominal_total = int(draft.get('total') or sum(i['nominal'] for i in items))
            cmd = _format_perintah_item_struk(
                {'nama': nama_gabung, 'nominal': nominal_total, 'kategori': kat_utama},
                metode, tgl_token)
            try:
                return _bungkus_hasil(jalankan_baris(cmd))
            except Exception as e:
                return _bungkus_hasil(pesan_kesalahan(e))

        baris_cmd = [_format_perintah_item_struk(i, metode, tgl_token) for i in items[:MAKS_BARIS]]
        return _bungkus_hasil(proses_banyak(baris_cmd))

    if jenis == 'perintah':
        if low not in ('ya', 'oke', 'ok', 'simpan', 'lanjut', 'gas'):
            return None
        hapus_konfirmasi(pengirim)
        daftar_cmd = draft.get('perintah') or []
        if not daftar_cmd:
            return _bungkus_hasil('Draft perintah kosong.')
        if len(daftar_cmd) == 1:
            try:
                return _bungkus_hasil(jalankan_baris(daftar_cmd[0]))
            except Exception as e:
                return _bungkus_hasil(pesan_kesalahan(e))
        return _bungkus_hasil(proses_banyak(daftar_cmd[:MAKS_BARIS]))

    return None


def _perintah_hanya_baca(cmd):
    bagian = cmd.strip().split()
    if not bagian:
        return False
    p = bagian[0].lower()
    if p in _PERINTAH_BACA:
        return True
    if p in ('/deadline', '/tagihan', '/rutin', '/ingatkan', '/remind', '/pintasan', '/batas'):
        return len(bagian) == 1
    return False


def proses_media(jenis, mime_type, data_base64, caption='', pengirim='default'):
    """Proses media masuk dari WhatsApp:
    - jenis == 'gambar' -> scan struk belanja + minta konfirmasi sebelum mencatat.
    - jenis == 'audio'  -> transkrip voice note + terjemahkan ke perintah bot."""
    jenis = (jenis or '').strip().lower()
    try:
        if jenis == 'gambar':
            hasil = analisis_struk(data_base64, mime_type=mime_type, caption=caption)
            draft = {
                'jenis': 'struk',
                'dibuat': sekarang().isoformat(timespec='seconds'),
                'toko': hasil['toko'],
                'tanggal': hasil['tanggal'],
                'metode': hasil['metode'],
                'items': hasil['items'],
                'total': hasil['total'],
            }
            simpan_konfirmasi(pengirim, draft)
            baris = [f'🧾 Hasil Scan Struk: {hasil["toko"]}']
            if hasil['tanggal']:
                baris.append('📅 Tanggal struk: ' + hasil['tanggal'])
            for item in hasil['items']:
                baris.append(f'• {item["kategori"]}: {item["nama"]} {rupiah(item["nominal"])}')
            baris.append(f'💳 Metode terdeteksi: {_format_metode_tagihan(hasil["metode"])}')
            baris.append(f'💰 Total: {rupiah(hasil["total"])}')
            baris.append('')
            baris.append('Balas untuk menyimpan:')
            baris.append('• ya — simpan semua sesuai rincian')
            baris.append('• ya qris / ya qris mandiri / ya tunai — ubah metode bayar')
            if len(hasil['items']) > 1:
                baris.append(f'• gabung — simpan jadi 1 baris ({hasil["toko"]} {rupiah(hasil["total"])})')
            baris.append('• batal — batalkan')
            return _bungkus_hasil('\n'.join(baris))

        if jenis == 'audio':
            transkrip = transkrip_audio(data_base64, mime_type=mime_type)
            daftar_p = daftar_pintasan()
            daftar_cmd = []

            bebas = baca_pesan_bebas(transkrip)
            if bebas is not None:
                arg, lewat_qris = bebas
                daftar_cmd = [('/qris ' if lewat_qris else '/out ') + arg]
            else:
                cmd_lokal = parse_bahasa_natural_lokal(transkrip, pintasan=daftar_p)
                if cmd_lokal:
                    daftar_cmd = [cmd_lokal]
                else:
                    hasil_ai = parse_bahasa_natural_ai(
                        transkrip, pintasan=daftar_p, tanggal_hari_ini=sekarang().date())
                    if hasil_ai and hasil_ai.get('perintah'):
                        daftar_cmd = hasil_ai['perintah']

            if not daftar_cmd:
                return _bungkus_hasil(
                    f'🎤 Terdengar: "{transkrip}"\n\n'
                    'Belum bisa mengenali perintah dari rekaman tersebut. '
                    'Coba sebutkan nominal & barangnya, misalnya "beli kopi dua puluh ribu pakai qris".'
                )

            # Perintah baca langsung dieksekusi tanpa minta konfirmasi
            if len(daftar_cmd) == 1 and _perintah_hanya_baca(daftar_cmd[0]):
                hasil = _bungkus_hasil(jalankan_baris(daftar_cmd[0]))
                hasil['teks'] = f'🎤 Terdengar: "{transkrip}"\n\n' + hasil['teks']
                if hasil.get('caption'):
                    hasil['caption'] = f'🎤 "{transkrip}"\n' + hasil['caption']
                return hasil

            draft = {
                'jenis': 'perintah',
                'dibuat': sekarang().isoformat(timespec='seconds'),
                'transkrip': transkrip,
                'perintah': daftar_cmd,
            }
            simpan_konfirmasi(pengirim, draft)
            pratinjau = '\n'.join('• ' + c for c in daftar_cmd)
            return _bungkus_hasil(
                f'🎤 Terdengar: "{transkrip}"\n\n'
                f'Akan dijalankan:\n{pratinjau}\n\n'
                'Balas *ya* untuk konfirmasi, atau *batal* untuk membatalkan.'
            )

        return _bungkus_hasil('Jenis media tidak didukung: ' + jenis)
    except Exception as e:
        return _bungkus_hasil(pesan_kesalahan(e))


def proses_pesan_lengkap(teks, pengirim='default'):
    """Pintu masuk utama untuk API lokal (mendukung balasan teks maupun gambar base64
    serta state konfirmasi per pengirim)."""
    teks_bersih = (teks or '').strip()
    if not teks_bersih:
        return _bungkus_hasil('')

    # 1. Cek apakah pengguna menjawab draft konfirmasi (struk / voice note)
    hasil_konf = _tangani_konfirmasi(teks_bersih, pengirim)
    if hasil_konf is not None:
        return hasil_konf

    baris_pesan = [b.strip() for b in teks_bersih.splitlines() if b.strip()]
    # Beberapa baris dianggap daftar catatan kalau barisnya tidak diawali perintah
    # selain /out dan /qris (supaya judul /todo dan /catat yang berbaris-baris tetap utuh).
    banyak = len(baris_pesan) > 1 and (
        not baris_pesan[0].startswith('/') or
        baris_pesan[0].split()[0].lower() in ('/out', '/qris'))
    if banyak:
        if len(baris_pesan) > MAKS_BARIS:
            return _bungkus_hasil(
                'Maksimal ' + str(MAKS_BARIS) + ' baris sekali kirim (kamu kirim ' +
                str(len(baris_pesan)) + '), jadi belum ada yang dicatat.')
        return _bungkus_hasil(proses_banyak(baris_pesan))
    try:
        return _bungkus_hasil(jalankan_baris(teks_bersih, izinkan_nlp=True))
    except Exception as e:
        return _bungkus_hasil(pesan_kesalahan(e))


def proses_pesan(teks, pengirim='default'):
    """Versi balasan teks saja (kompatibel dengan test.py dan pemanggil lama)."""
    return proses_pesan_lengkap(teks, pengirim=pengirim)['teks']


def pengingat_catat_pengeluaran():
    """Untuk penjadwal: panggil berkala (misalnya tiap menit) dan kirim hasilnya
    kalau bukan None.

    Mengembalikan teks pengingat kalau sudah lewat JAM_PENGINGAT dan hari ini belum
    ada pengeluaran yang dicatat. Setiap hari hanya ditangani sekali (dicatat di
    status.json): kalau sudah ada catatan, hari itu ditandai selesai tanpa pesan.
    Kalau pembacaan sheet gagal, hari itu tidak ditandai, jadi dicoba lagi nanti.
    """
    waktu = sekarang()
    if waktu.hour < JAM_PENGINGAT:
        return None
    hari = waktu.strftime('%Y-%m-%d')
    if pengingat_sudah_dicek(hari):
        return None

    tambahan = ''
    try:
        sudah_catat = bool(ambil_pengeluaran_hari_ini())
    except TabTidakAda as e:
        sudah_catat = False
        tambahan = ('\n(Tab bulan ' + str(e) + ' belum ada di spreadsheet. '
                    'Duplikat tab Template dulu.)')
    except Exception:
        traceback.print_exc()
        return None

    tandai_pengingat_dicek(hari)
    if sudah_catat:
        return None
    return ('🔔 Belum ada pengeluaran yang dicatat hari ini. '
            'Catat dengan /out atau /qris, atau abaikan kalau memang tidak ada.' + tambahan)


def pengingat_rekap_harian():
    """Untuk penjadwal: rekap pengeluaran harian, sekali sehari mulai JAM_REKAP.
    Kalau pembacaan sheet gagal, hari itu tidak ditandai, jadi dicoba lagi menit berikutnya."""
    waktu = sekarang()
    if waktu.hour < JAM_REKAP:
        return None
    hari = waktu.strftime('%Y-%m-%d')
    if status_sudah('rekap_harian', hari):
        return None
    try:
        teks = susun_rekap_harian()
    except TabTidakAda as e:
        teks = ('🌙 Rekap hari ini belum bisa dibuat: tab bulan ' + str(e) +
                ' belum ada di spreadsheet. Duplikat tab Template dulu.')
    except Exception:
        traceback.print_exc()
        return None
    status_tandai('rekap_harian', hari)
    return teks


def pengingat_berkala():
    """Pintu masuk untuk penjadwal: panggil tiap menit dan kirim hasilnya kalau bukan None.

    Mengumpulkan semua pengingat yang jatuh tempo: pesan pagi, pengingat deadline,
    pengingat cepat (/ingatkan), tagihan rutin (/tagihan), pengingat "belum catat pengeluaran",
    dan rekap harian. Tiap sumber dijaga sendiri-sendiri, jadi satu yang error tidak
    menghalangi yang lain."""
    pesan = []
    for sumber in (pengingat_pagi, pengingat_deadline, pengingat_cepat,
                   pengingat_tagihan, pengingat_catat_pengeluaran,
                   pengingat_rekap_harian):
        try:
            teks = sumber()
        except Exception:
            traceback.print_exc()
            continue
        if teks:
            pesan.append(teks)
    return '\n\n'.join(pesan) if pesan else None


# Nama lama tetap dipakai supaya penjadwal yang sudah memanggil pengingat_pengeluaran()
# otomatis ikut mendapat seluruh pengingat tanpa perubahan di tempat lain.
pengingat_pengeluaran = pengingat_berkala