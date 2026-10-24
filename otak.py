import traceback
from datetime import datetime, timedelta

from kalender import event_hari_ini, tambah_event
from penyimpanan import (WIB, RiwayatBerubah, TabelPenuh, TabTidakAda,
                         ambil_pengeluaran_hari_ini, ambil_saldo,
                         ambil_total_kategori, batalkan_terakhir, nama_bulan,
                         pengingat_sudah_dicek, sekarang, simpan_pemasukan,
                         simpan_pemasukan_bank, simpan_pengeluaran,
                         simpan_riwayat, tandai_pengingat_dicek)

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

# Pintasan barang langganan: /qris galon, /out kopi, /qris kopi 22rb (harga ditimpa).
# nama pintasan -> (nama tabel kategori, nama yang ditulis di sheet, harga biasa)
# ISI harganya sesuai yang biasa kamu bayar. Selama harganya None, pintasan itu
# hanya jalan kalau nominalnya diketik sendiri. Cek juga kategorinya sudah pas.
PINTASAN = {
    'galon': ('Mingguan&Bulanan', 'Galon', None),
    'kopi': ('Jajan', 'Kopi', None),
    'tempe': ('Jajan', 'Tempe', None),
    'billiard': ('Hiburan', 'Billiard', None),
}

# Pengingat "belum catat pengeluaran": dikirim sekali sehari, mulai jam ini (WIB).
JAM_PENGINGAT = 20

# Nama sumber yang ditulis di tabel Pemasukan.
# Rumus saldo BNI (sel L11) mencari kata "BNI", jadi kata itu harus tetap ada.
SUMBER_QRIS = 'QRIS BNI'
SUMBER_TARIK = 'Tarik Uang BNI'

NOMINAL_TAK_TERBACA = 'Nominal tidak terbaca. Contoh: 25000, 25.000, atau 25rb'

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

def baca_pintasan(bagian, nama_perintah):
    """['galon'] atau ['galon', '22rb'] -> (kategori, nama, nominal).
    Kalau tidak bisa diproses, mengembalikan teks pesan untuk pengguna."""
    kunci = bagian[0].lower()
    kategori, nama, harga = PINTASAN[kunci]
    if len(bagian) > 2:
        return ('Format pintasan: ' + nama_perintah + ' ' + kunci +
                ' [nominal kalau harganya beda]')
    if len(bagian) == 2:
        try:
            return kategori, nama, baca_nominal(bagian[1])
        except ValueError:
            return NOMINAL_TAK_TERBACA
    if harga is None:
        return ('Harga ' + kunci + ' belum diisi di PINTASAN (otak.py). '
                'Sementara, ketik nominalnya: ' + nama_perintah + ' ' + kunci + ' <nominal>')
    return kategori, nama, harga


def baca_pengeluaran_biasa(bagian, nama_perintah):
    """['13rb', 'jajan', 'lotek'] -> (kategori, nama, nominal).
    Kalau tidak bisa diproses, mengembalikan teks pesan untuk pengguna."""
    if len(bagian) < 2:
        return ('Format: ' + nama_perintah + ' <nominal> [kategori] <nama barang>\n'
                'Kategori: jajan (otomatis), alat, mingguan, bulanan, hiburan\n'
                'Contoh: ' + nama_perintah + ' 13rb jajan lotek\n'
                'Pintasan: ' + ', '.join(PINTASAN) + ' (contoh: ' + nama_perintah + ' galon)')
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


def catat_pengeluaran(argumen, nama_perintah, lewat_qris):
    """Dipakai bersama oleh /out dan /qris.
    Kalau lewat_qris True, selain mencatat pengeluaran, bot juga menambah satu
    baris SUMBER_QRIS di tabel Pemasukan dengan nominal yang sama."""
    bagian = argumen.split()
    if bagian and bagian[0].lower() in PINTASAN:
        hasil = baca_pintasan(bagian, nama_perintah)
    else:
        hasil = baca_pengeluaran_biasa(bagian, nama_perintah)
    if isinstance(hasil, str):              # pesan salah format
        return hasil
    kategori, nama, nominal = hasil

    # Pemasukan ditulis lebih dulu: kalau tab bulan belum ada atau tabel
    # Pemasukan penuh, errornya muncul sebelum ada yang tertulis setengah-setengah.
    # "jejak" mencatat sel yang ditulis supaya bisa dibatalkan dengan /undo.
    jejak = []
    baris_qris = None
    ringkasan = ('QRIS ' if lewat_qris else '') + kategori + ' ' + nama + ' ' + rupiah(nominal)
    try:
        if lewat_qris:
            _, baris_qris = simpan_pemasukan(SUMBER_QRIS, nominal, jejak=jejak)
        tab, baris = simpan_pengeluaran(kategori, nama, nominal, jejak=jejak)
    finally:
        if jejak:                           # tetap tercatat walau penulisan kedua gagal
            simpan_riwayat(ringkasan, jejak)

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
            ' dicatat di Pemasukan (tab ' + tab + ', baris ' + str(baris) + ')')


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
            ' dicatat di Pemasukan Bank (tab ' + tab + ', baris ' + str(baris) + ')')


def perintah_saldo(argumen):
    """/saldo -> sisa uang dan saldo bank, dibaca dari hasil rumus di spreadsheet."""
    tab, angka = ambil_saldo()
    baris = []
    for label in ('Sisa Uang', 'BNI', 'Mandiri', 'Pengeluaran'):
        if label in angka:
            teks = label if label != 'Pengeluaran' else 'Pengeluaran bulan ini'
            baris.append(teks + ': ' + rupiah(int(round(angka[label]))))
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
            '/out <nominal> <kategori> <nama>  (kategori: jajan, alat, mingguan, bulanan, hiburan)\n'
            '/qris <nominal> <kategori> <nama>\n'
            '/out atau /qris <pintasan> [nominal]  (pintasan: ' + ', '.join(PINTASAN) + ')\n'
            '/tarik <nominal>  (tarik tunai dari BNI)\n'
            '/topup <rekening> <nominal>\n'
            '/saldo  (sisa uang, saldo BNI dan Mandiri)\n'
            '/rekap  (total per kategori bulan ini dan selisih dengan bulan lalu)\n'
            '/undo  (batalkan catatan terakhir)\n'
            '/todo <hariini|besok|lusa|14/10> <jam> <judul>')


PERINTAH = {
    '/out': perintah_out,
    '/qris': perintah_qris,
    '/tarik': perintah_tarik,
    '/topup': perintah_topup,
    '/saldo': perintah_saldo,
    '/rekap': perintah_rekap,
    '/undo': perintah_undo,
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
    except TabelPenuh as e:
        tabel = str(e) or 'Pemasukan'
        return ('Tabel ' + tabel + ' bulan ini sudah penuh (baris 10-31), jadi belum ada '
                'yang dicatat. Sisipkan baris kosong di dalam tabelnya '
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

def pengingat_pengeluaran():
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