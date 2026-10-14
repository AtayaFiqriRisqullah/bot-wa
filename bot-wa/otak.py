from datetime import datetime, timedelta

from kalender import event_hari_ini, tambah_event
from penyimpanan import (WIB, TabTidakAda, ambil_harian_hari_ini,
                         ambil_pengeluaran_hari_ini, sekarang, simpan_harian,
                         simpan_pengeluaran)

# Kata kategori yang boleh diketik -> nama tabel di spreadsheet
KATEGORI_ALIAS = {
    'jajan': 'Jajan',
    'alat': 'Alat',
    'mingguan': 'Mingguan&Bulanan',
    'bulanan': 'Mingguan&Bulanan',
    'hiburan': 'Hiburan',
}


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


def perintah_out(argumen):
    bagian = argumen.split()
    if len(bagian) < 2:
        return ('Format: /out <nominal> [kategori] <nama barang>\n'
                'Kategori: jajan (otomatis), alat, mingguan, bulanan, hiburan\n'
                'Contoh: /out 13rb jajan lotek')
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
            return 'Tulis nama barangnya. Contoh: /out 65rb alat teko listrik'
    nama = ' '.join(sisa)

    tab, baris = simpan_pengeluaran(kategori, nama, nominal)
    return ('✅ ' + kategori + ': ' + nama + ' ' + rupiah(nominal) +
            ' (tab ' + tab + ', baris ' + str(baris) + ')')


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


def baca_durasi(teks):
    """'4j20m' -> 260, '90m' -> 90, '2j' -> 120 (hasil dalam menit)"""
    t = teks.lower()
    jam = menit = 0
    if 'j' in t:
        bagian_jam, t = t.split('j', 1)
        jam = int(bagian_jam)
    if t.endswith('m'):
        t = t[:-1]
    if t:
        menit = int(t)
    return jam * 60 + menit


def perintah_harian(argumen):
    bagian = argumen.split()
    if len(bagian) != 2:
        return 'Format: /harian <langkah> <screentime>\nContoh: /harian 8500 4j20m'
    try:
        langkah = int(bagian[0].replace('.', ''))
        menit = baca_durasi(bagian[1])
    except ValueError:
        return 'Angka tidak terbaca. Contoh: /harian 8500 4j20m'
    simpan_harian(langkah, menit)
    return '✅ Tercatat: ' + str(langkah) + ' langkah, screentime ' + str(menit // 60) + 'j ' + str(menit % 60) + 'm'


def perintah_laporan(argumen):
    total = 0
    per_kategori = {}
    for kategori, nama, nilai in ambil_pengeluaran_hari_ini():
        total += nilai
        per_kategori[kategori] = per_kategori.get(kategori, 0) + nilai

    baris = ['📊 Laporan ' + sekarang().strftime('%d/%m/%Y'), '']
    baris.append('💸 Pengeluaran: ' + rupiah(total))
    for kategori, nilai in per_kategori.items():
        baris.append('   • ' + kategori + ': ' + rupiah(nilai))

    harian = ambil_harian_hari_ini()
    if harian:
        menit = int(float(harian[2]))
        baris.append('👟 Langkah: ' + str(harian[1]))
        baris.append('📱 Screentime: ' + str(menit // 60) + 'j ' + str(menit % 60) + 'm')
    else:
        baris.append('👟 Langkah dan screentime belum diisi (pakai /harian)')

    baris.append('')
    acara = event_hari_ini()
    if acara:
        baris.append('📅 Agenda hari ini:')
        for jam, judul in acara:
            baris.append('   • ' + jam + ' ' + judul)
    else:
        baris.append('📅 Tidak ada agenda hari ini')
    return '\n'.join(baris)


def perintah_bantuan(argumen):
    return ('Perintah:\n'
            '/out 13rb jajan lotek  (kategori: jajan, alat, mingguan, bulanan, hiburan)\n'
            '/todo besok 15:00 kumpul DML\n'
            '/harian 8500 4j20m  (langkah, screentime)\n'
            '/laporan')


PERINTAH = {
    '/out': perintah_out,
    '/todo': perintah_todo,
    '/harian': perintah_harian,
    '/laporan': perintah_laporan,
    '/bantuan': perintah_bantuan,
}


def proses_pesan(teks):
    perintah, _, argumen = teks.strip().partition(' ')
    fungsi = PERINTAH.get(perintah.lower())
    if fungsi is None:
        return 'Perintah tidak dikenal. Coba: /bantuan'
    try:
        return fungsi(argumen)
    except TabTidakAda as e:
        nama = str(e)
        if nama == 'harian':
            return ('Tab harian belum ada di spreadsheet. Buat tab baru bernama harian '
                    '(baris 1, kolom A-C: tanggal, langkah, menit_layar).')
        return ('Tab bulan ' + nama + ' belum ada di spreadsheet. '
                'Duplikat tab Template, lalu ganti namanya menjadi ' + nama + '.')