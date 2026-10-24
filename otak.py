import traceback
from datetime import datetime, timedelta

from kalender import event_hari_ini, tambah_event
from penyimpanan import (WIB, TabelPenuh, TabTidakAda,
                         ambil_pengeluaran_hari_ini, sekarang,
                         simpan_pemasukan, simpan_pengeluaran)

# Kata kategori yang boleh diketik -> nama tabel di spreadsheet
KATEGORI_ALIAS = {
    'jajan': 'Jajan',
    'alat': 'Alat',
    'mingguan': 'Mingguan&Bulanan',
    'bulanan': 'Mingguan&Bulanan',
    'hiburan': 'Hiburan',
}

# Nama sumber yang ditulis di tabel Pemasukan untuk pembayaran QRIS.
# Rumus saldo BNI (sel L11) mencari kata "BNI", jadi kata itu harus tetap ada.
SUMBER_QRIS = 'QRIS BNI'

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

def catat_pengeluaran(argumen, nama_perintah, lewat_qris):
    """Dipakai bersama oleh /out dan /qris.
    Kalau lewat_qris True, selain mencatat pengeluaran, bot juga menambah satu
    baris SUMBER_QRIS di tabel Pemasukan dengan nominal yang sama."""
    bagian = argumen.split()
    if len(bagian) < 2:
        return ('Format: ' + nama_perintah + ' <nominal> [kategori] <nama barang>\n'
                'Kategori: jajan (otomatis), alat, mingguan, bulanan, hiburan\n'
                'Contoh: ' + nama_perintah + ' 13rb jajan lotek')
    try:
        nominal = baca_nominal(bagian[0])
    except ValueError:
        return 'Nominal tidak terbaca. Contoh: 25000, 25.000, atau 25rb'

    sisa = bagian[1:]
    kategori = 'Jajan'                      # kalau kategori tidak ditulis
    if sisa[0].lower() in KATEGORI_ALIAS:
        kategori = KATEGORI_ALIAS[sisa[0].lower()]
        sisa = sisa[1:]
        if not sisa:
            return 'Tulis nama barangnya. Contoh: ' + nama_perintah + ' 65rb alat teko listrik'
    nama = ' '.join(sisa)

    # Pemasukan ditulis lebih dulu: kalau tab bulan belum ada atau tabel
    # Pemasukan penuh, errornya muncul sebelum ada yang tertulis setengah-setengah.
    baris_qris = None
    if lewat_qris:
        _, baris_qris = simpan_pemasukan(SUMBER_QRIS, nominal)

    tab, baris = simpan_pengeluaran(kategori, nama, nominal)
    pesan = ('✅ ' + kategori + ': ' + nama + ' ' + rupiah(nominal) +
             ' (tab ' + tab + ', baris ' + str(baris) + ')')
    if lewat_qris:
        pesan += ('\n💳 ' + SUMBER_QRIS + ' ' + rupiah(nominal) +
                  ' dicatat di Pemasukan (baris ' + str(baris_qris) + ')')
    return pesan


def perintah_out(argumen):
    return catat_pengeluaran(argumen, '/out', lewat_qris=False)


def perintah_qris(argumen):
    return catat_pengeluaran(argumen, '/qris', lewat_qris=True)


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
    return '📅 Ditambahkan: ' + bagian[2] + ' (' + waktu + ')'


def perintah_bantuan(argumen):
    return ('Perintah:\n'
            '/out 13rb jajan lotek  (kategori: jajan, alat, mingguan, bulanan, hiburan)\n'
            '/qris 13rb jajan lotek  (sama seperti /out, tapi dibayar QRIS BNI)\n'
            '/todo besok 15:00 kumpul DML\n'
            '/harian 8500 4j20m  (langkah, screentime)\n'
            '/laporan')


PERINTAH = {
    '/out': perintah_out,
    '/qris': perintah_qris,
    '/todo': perintah_todo,
    '/bantuan': perintah_bantuan,
}


def proses_pesan(teks):
    perintah, _, argumen = teks.strip().partition(' ')
    fungsi = PERINTAH.get(perintah.lower())
    if fungsi is None:
        return 'Perintah tidak dikenal. Coba: /bantuan'
    try:
        return fungsi(argumen)
    except TabelPenuh:
        return ('Tabel Pemasukan bulan ini sudah penuh (baris 10-31), jadi belum ada '
                'yang dicatat. Sisipkan baris kosong di dalam tabel Pemasukan '
                '(di antara baris 10 dan 31 supaya rumusnya ikut melebar), lalu kirim ulang.')
    except TabTidakAda as e:
        nama = str(e)
        if nama == 'harian':
            return ('Tab harian belum ada di spreadsheet. Buat tab baru bernama harian '
                    '(baris 1, kolom A-C: tanggal, langkah, menit_layar).')
        return ('Tab bulan ' + nama + ' belum ada di spreadsheet. '
                'Duplikat tab Template, lalu ganti namanya menjadi ' + nama + '.')
    except Exception as e:
        traceback.print_exc()          # detail lengkap muncul di terminal Python
        return '⚠️ Error: ' + type(e).__name__ + ': ' + str(e)