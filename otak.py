import re
import traceback
from datetime import date, datetime, time, timedelta

import requests

from kalender import (GAGAL_KALENDER, TugasGagal, event_hari_ini, tambah_event,
                      tambah_penanda_deadline, tambah_tugas)
from penyimpanan import (BULAN, GAGAL_JARINGAN, RIWAYAT_MAKS, WIB, RiwayatBerubah,
                         TabelPenuh, TabTidakAda,
                         ambil_pengeluaran_hari_ini, ambil_riwayat, ambil_saldo,
                         ambil_total_kategori, baca_deadline, baca_pengaturan,
                         batalkan_terakhir, nama_bulan, pengingat_sudah_dicek,
                         sekarang, simpan_pemasukan, simpan_pemasukan_bank,
                         simpan_pengeluaran, simpan_riwayat, status_sudah,
                         status_tandai, tandai_pengingat_dicek, tulis_pengaturan,
                         ubah_deadline)

# Kata kategori yang boleh diketik -> nama tabel di spreadsheet
KATEGORI_ALIAS = {
    'jajan': 'Jajan',
    'alat': 'Alat',
    'mingguan': 'Mingguan&Bulanan',
    'bulanan': 'Mingguan&Bulanan',
    'hiburan': 'Hiburan',
}

# Bank yang boleh diketik di /topup -> nama yang ditulis di tabel Pemasukan Bank
BANK_ALIAS = {
    'bni': 'BNI',
    'mandiri': 'Mandiri',
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

# Kata yang tidak boleh jadi nama pintasan (dipakai di awal pesan tanpa perintah).
NAMA_TERLARANG = {'hapus', 'qris', 'out', 'kemarin'}

# Tanggal untuk mencatat pengeluaran yang terlewat: "/out kemarin 13rb lotek" atau
# "/out 22/10 13rb lotek" (tanggal/bulan, tahun ini). Tidak boleh di masa depan.
POLA_TANGGAL = re.compile(r'^(\d{1,2})/(\d{1,2})$')

# Jumlah catatan yang ditampilkan /riwayat kalau tidak diberi angka.
RIWAYAT_TAMPIL = 5

# Pengingat "belum catat pengeluaran": dikirim sekali sehari, mulai jam ini (WIB).
JAM_PENGINGAT = 20

# Peringatan batas bulanan mulai muncul saat pengeluaran satu kategori mencapai
# sekian persen dari batasnya (lihat /batas).
AMBANG_PERINGATAN = 0.8

# Pesan tanpa perintah ("13rb lotek"): nominal di bawah ini dianggap salah ketik
# (misalnya "2 galon" terbaca Rp2) dan tidak dicatat.
NOMINAL_MINIMAL_BEBAS = 1000

# Batas jumlah baris dalam satu pesan, supaya tidak melewati kuota Google Sheets.
MAKS_BARIS = 10

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

PETUNJUK_DEADLINE = ('Tambah: /deadline <judul> <tanggal> <jam>\n'
                     'Contoh: /deadline DML 3 jumat 23:59\n'
                     'Tanggal: hariini, besok, lusa, nama hari (jumat), atau 30/10 (30/10/2026)\n'
                     'Lihat: /deadline\n'
                     'Selesai: /deadline selesai <nomor atau judul>')

# Nama sumber yang ditulis di tabel Pemasukan.
# Rumus saldo BNI (sel L11) mencari kata "BNI", jadi kata itu harus tetap ada.
SUMBER_QRIS = 'QRIS BNI'
SUMBER_TARIK = 'Tarik Uang BNI'

NOMINAL_TAK_TERBACA = 'Nominal tidak terbaca. Contoh: 25000, 25.000, atau 25rb'

PETUNJUK_PINTASAN = ('Tambah/ubah: /pintasan <nama> <harga> [kategori] [nama di sheet]\n'
                     'Hapus: /pintasan hapus <nama>')
PETUNJUK_BATAS = ('Atur: /batas <kategori> <nominal>  (kategori: jajan, alat, mingguan, bulanan, hiburan)\n'
                  'Hapus: /batas hapus <kategori>')

def rupiah(angka):
    return 'Rp' + f'{angka:,}'.replace(',', '.')

def baca_nominal(teks):
    """'25000', '25.000', '25rb', '25k' -> 25000"""
    t = teks.lower().replace('.', '').replace(',', '')
    pengali = 1
    if t.endswith('jt'):
        pengali, t = 1_000_000, t[:-2]
    elif t.endswith('rb') or t.endswith('k'):
        pengali, t = 1_000, t.rstrip('rbk')
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


def catat_pengeluaran(argumen, nama_perintah, lewat_qris, nominal_minimal=0):
    """Dipakai bersama oleh /out, /qris, dan pesan tanpa perintah.
    Kalau lewat_qris True, selain mencatat pengeluaran, bot juga menambah satu
    baris SUMBER_QRIS di tabel Pemasukan dengan nominal yang sama.

    Pengeluaran bisa untuk hari lain: tanggalnya ('kemarin' atau '22/10') ditulis paling
    depan, sebelum nominal atau nama pintasan.

    Mengembalikan (pesan, kategori). kategori None artinya baris sisa uang dan peringatan
    batas tidak perlu ditampilkan: tidak ada yang dicatat, atau yang dicatat masuk ke
    bulan lain (sisa uang dan batas yang ditampilkan selalu milik bulan berjalan)."""
    bagian = argumen.split()
    hari_ini = sekarang().date()
    tanggal = None                          # None = hari ini
    if bagian and kata_tanggal(bagian[0]):
        try:
            tanggal = baca_tanggal_lalu(bagian[0])
        except ValueError as e:
            return str(e), None
        bagian = bagian[1:]
        if tanggal == hari_ini:
            tanggal = None
    daftar = daftar_pintasan()
    dari_pintasan = bool(bagian) and bagian[0].lower() in daftar
    if dari_pintasan:
        hasil = baca_pintasan(bagian, nama_perintah, daftar)
    else:
        hasil = baca_pengeluaran_biasa(bagian, nama_perintah, daftar)
    if isinstance(hasil, str):              # pesan salah format
        return hasil, None
    kategori, nama, nominal = hasil

    # Harga tersimpan milik pintasan tidak diperiksa; yang diketik pengguna diperiksa.
    harga_tersimpan = dari_pintasan and len(bagian) == 1
    if not harga_tersimpan and nominal < nominal_minimal:
        return ('Nominal ' + rupiah(nominal) + ' kelihatannya terlalu kecil, jadi belum dicatat. '
                'Tulis 2rb untuk Rp2.000, atau pakai /out kalau memang segitu.'), None

    # Pemasukan ditulis lebih dulu: kalau tab bulan belum ada atau tabel
    # Pemasukan penuh, errornya muncul sebelum ada yang tertulis setengah-setengah.
    # "jejak" mencatat sel yang ditulis supaya bisa dibatalkan dengan /undo.
    jejak = []
    baris_qris = None
    ringkasan = ('QRIS ' if lewat_qris else '') + kategori + ' ' + nama + ' ' + rupiah(nominal)
    if tanggal:
        ringkasan += ' untuk ' + tanggal.strftime('%d/%m')
    try:
        if lewat_qris:
            _, baris_qris = simpan_pemasukan(SUMBER_QRIS, nominal, jejak=jejak, tanggal=tanggal)
        tab, baris = simpan_pengeluaran(kategori, nama, nominal, jejak=jejak, tanggal=tanggal)
    finally:
        if jejak:                           # tetap tercatat walau penulisan kedua gagal
            simpan_riwayat(ringkasan, jejak)

    pesan = ('✅ ' + kategori + ': ' + nama + ' ' + rupiah(nominal) +
             (' untuk ' + tanggal.strftime('%d/%m/%Y') if tanggal else '') +
             ' (tab ' + tab + ', baris ' + str(baris) + ')')
    if lewat_qris:
        pesan += ('\n💳 ' + SUMBER_QRIS + ' ' + rupiah(nominal) +
                  ' dicatat di Pemasukan (baris ' + str(baris_qris) + ')')
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
    """/tarik 250rb -> baris 'Tarik Uang BNI' di tabel Pemasukan."""
    bagian = argumen.split()
    if len(bagian) != 1:
        return 'Format: /tarik <nominal>\nContoh: /tarik 250rb'
    try:
        nominal = baca_nominal(bagian[0])
    except ValueError:
        return NOMINAL_TAK_TERBACA
    if nominal <= 0:
        return 'Nominal harus lebih dari 0.'
    jejak = []
    tab, baris = simpan_pemasukan(SUMBER_TARIK, nominal, jejak=jejak)
    simpan_riwayat('Tarik tunai ' + rupiah(nominal), jejak)
    return ('🏧 ' + SUMBER_TARIK + ' ' + rupiah(nominal) +
            ' dicatat di Pemasukan (tab ' + tab + ', baris ' + str(baris) + ')' + info_sisa())


def perintah_topup(argumen):
    """/topup bni 1jt -> baris di tabel Pemasukan Bank."""
    bagian = argumen.split()
    if len(bagian) != 2 or bagian[0].lower() not in BANK_ALIAS:
        return ('Format: /topup <bni|mandiri> <nominal>\n'
                'Contoh: /topup bni 1jt')
    bank = BANK_ALIAS[bagian[0].lower()]
    try:
        nominal = baca_nominal(bagian[1])
    except ValueError:
        return NOMINAL_TAK_TERBACA
    if nominal <= 0:
        return 'Nominal harus lebih dari 0.'
    jejak = []
    tab, baris = simpan_pemasukan_bank(bank, nominal, jejak=jejak)
    simpan_riwayat('Top up ' + bank + ' ' + rupiah(nominal), jejak)
    return ('🏦 Top up ' + bank + ' ' + rupiah(nominal) +
            ' dicatat di Pemasukan Bank (tab ' + tab + ', baris ' + str(baris) + ')' +
            info_sisa(bank=bank))


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


def tambah_deadline(argumen):
    hasil = baca_deadline_dari_teks(argumen)
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
    entri = {'judul': judul, 'waktu': waktu.isoformat(timespec='seconds'), 'terkirim': terkirim}

    def tambah(daftar):
        if any(d.get('judul', '').lower() == judul.lower() and d.get('waktu') == entri['waktu']
               for d in daftar):
            return False
        daftar.append(entri)
        return True

    if not ubah_deadline(tambah):
        return 'Deadline itu sudah ada: ' + judul + ' (' + teks_waktu(waktu) + ')'
    akan = [teks_waktu(waktu_kirim(t, waktu)) for t in TINGKAT_DEADLINE if t[0] not in terkirim]
    baris = ['✅ Deadline dicatat: ' + judul,
             '📌 ' + teks_waktu(waktu) + ' (' + teks_sisa(waktu, kini) + ')']
    if akan:
        baris.append('🔔 Pengingat: ' + ' · '.join(akan))
    else:
        baris.append('🔔 Tidak ada pengingat tersisa, deadline-nya sudah terlalu dekat.')
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
    return '✅ Deadline selesai: ' + terpilih['judul']


def perintah_deadline(argumen):
    """/deadline DML 3 jumat 23:59 | /deadline | /deadline selesai <nomor atau judul>"""
    bagian = argumen.split()
    if not bagian:
        return daftar_deadline()
    if bagian[0].lower() in ('selesai', 'hapus', 'batal'):
        return selesaikan_deadline(' '.join(bagian[1:]))
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
    deadline = teks_deadline_pagi()
    if deadline:
        bagian.append(deadline)
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


def perintah_bantuan(argumen):
    pintasan = ', '.join(daftar_pintasan()) or 'belum ada'
    return ('Perintah:\n'
            '/out (kategori: jajan, alat, mingguan, bulanan, hiburan)\n'
            '/qris\n'
            '/pintasan\n'
            '/batas (batas bulanan per kategori)\n'
            '/tarik (BNI)\n'
            '/topup\n'
            '/saldo\n'
            '/rekap\n'
            '/hariini\n'
            '/riwayat\n'
            '/undo\n'
            '/deadline (tugas dan pengingatnya)\n'
            '/pagi (pesan pagi sekarang)\n'
            '/todo')


PERINTAH = {
    '/out': perintah_out,
    '/qris': perintah_qris,
    '/tarik': perintah_tarik,
    '/topup': perintah_topup,
    '/saldo': perintah_saldo,
    '/rekap': perintah_rekap,
    '/pintasan': perintah_pintasan,
    '/batas': perintah_batas,
    '/hariini': perintah_hariini,
    '/riwayat': perintah_riwayat,
    '/undo': perintah_undo,
    '/deadline': perintah_deadline,
    '/pagi': perintah_pagi,
    '/todo': perintah_todo,
    '/bantuan': perintah_bantuan,
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
    traceback.print_exc()          # detail lengkap muncul di terminal Python
    if isinstance(e, GAGAL_JARINGAN + GAGAL_KALENDER):
        return ('📶 Koneksi ke Google terputus, padahal sudah dicoba ulang beberapa kali. '
                'Kalau tadi mencatat pengeluaran, cek dulu dengan /riwayat sebelum mengirim ulang, '
                'supaya tidak tercatat dua kali. /todo aman dikirim ulang: acara, tugas, dan '
                'penandanya tidak dibuat dobel.')
    return '⚠️ Error: ' + type(e).__name__ + ': ' + str(e)


def baca_pesan_bebas(baris):
    """Pesan tanpa '/': '13rb lotek', 'galon', 'qris 13rb lotek', 'out 5rb es teh',
    'kemarin 13rb lotek' -> (argumen untuk catat_pengeluaran, lewat_qris).
    None kalau pesannya tidak mirip pengeluaran. Kata pertama (setelah qris/out dan
    tanggal, kalau ada) harus berupa nominal atau nama pintasan, jadi obrolan biasa
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
    mulai = 1 if kata_tanggal(bagian[0]) else 0     # tanggal boleh di depan: "kemarin 13rb lotek"
    if mulai == len(bagian):
        return None
    pertama = bagian[mulai].lower()
    if pertama not in daftar_pintasan():
        try:
            baca_nominal(pertama)
        except ValueError:
            return None
    return ' '.join(bagian), lewat_qris


def jalankan_baris(baris, kategori_banyak=None):
    """Satu baris pesan -> teks balasan. Exception sengaja tidak ditangkap di sini.
    kategori_banyak (set) hanya diisi kalau pesannya terdiri dari beberapa baris."""
    if baris.startswith('/'):
        perintah, _, argumen = baris.partition(' ')
        fungsi = PERINTAH.get(perintah.lower())
        if fungsi is None:
            return 'Perintah tidak dikenal. Coba: /bantuan'
        if kategori_banyak is not None:
            if fungsi not in (perintah_out, perintah_qris):
                return perintah.lower() + ' tidak bisa digabung dalam pesan beberapa baris. Kirim terpisah.'
            return fungsi(argumen, kategori_banyak=kategori_banyak)
        return fungsi(argumen)

    bebas = baca_pesan_bebas(baris)
    if bebas is None:
        return ('Pesan tidak dikenali. Catat pengeluaran dengan: 13rb lotek '
                '(atau qris 13rb lotek, atau nama pintasan seperti galon).\n'
                'Daftar perintah: /bantuan')
    argumen, lewat_qris = bebas
    return catat_dan_lapor(argumen, '/qris' if lewat_qris else '/out', lewat_qris,
                           nominal_minimal=NOMINAL_MINIMAL_BEBAS,
                           kategori_banyak=kategori_banyak)


def proses_banyak(baris_pesan):
    """Pesan berisi beberapa baris pengeluaran: tiap baris diproses sendiri-sendiri.
    Sisa uang dan peringatan batas ditampilkan sekali di akhir, bukan di setiap baris."""
    kategori = set()
    hasil = []
    for nomor, baris in enumerate(baris_pesan, 1):
        try:
            teks = jalankan_baris(baris, kategori)
        except TabTidakAda as e:
            hasil.append(str(nomor) + '. ' + pesan_kesalahan(e))
            hasil.append('Baris berikutnya tidak diproses.')
            break
        except Exception as e:
            teks = pesan_kesalahan(e)
        hasil.append(str(nomor) + '. ' + teks)
    return '\n'.join(hasil) + (info_sisa(kategori) if kategori else '')


def proses_pesan(teks):
    baris_pesan = [b.strip() for b in teks.strip().splitlines() if b.strip()]
    # Beberapa baris dianggap daftar catatan kalau barisnya tidak diawali perintah
    # selain /out dan /qris (supaya judul /todo yang berbaris-baris tetap utuh).
    banyak = len(baris_pesan) > 1 and (
        not baris_pesan[0].startswith('/') or
        baris_pesan[0].split()[0].lower() in ('/out', '/qris'))
    if banyak:
        if len(baris_pesan) > MAKS_BARIS:
            return ('Maksimal ' + str(MAKS_BARIS) + ' baris sekali kirim (kamu kirim ' +
                    str(len(baris_pesan)) + '), jadi belum ada yang dicatat.')
        return proses_banyak(baris_pesan)
    try:
        return jalankan_baris(teks.strip())
    except Exception as e:
        return pesan_kesalahan(e)


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


def pengingat_berkala():
    """Pintu masuk untuk penjadwal: panggil tiap menit dan kirim hasilnya kalau bukan None.

    Mengumpulkan semua pengingat yang jatuh tempo: pesan pagi, pengingat deadline, dan
    pengingat "belum catat pengeluaran". Tiap sumber dijaga sendiri-sendiri, jadi satu yang
    error tidak menghalangi yang lain."""
    pesan = []
    for sumber in (pengingat_pagi, pengingat_deadline, pengingat_catat_pengeluaran):
        try:
            teks = sumber()
        except Exception:
            traceback.print_exc()
            continue
        if teks:
            pesan.append(teks)
    return '\n\n'.join(pesan) if pesan else None


# Nama lama tetap dipakai supaya penjadwal yang sudah memanggil pengingat_pengeluaran()
# otomatis ikut mendapat pesan pagi dan pengingat deadline tanpa perubahan di tempat lain.
pengingat_pengeluaran = pengingat_berkala