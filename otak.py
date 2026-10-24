import traceback
from datetime import datetime, timedelta

from kalender import event_hari_ini, tambah_event
from penyimpanan import (WIB, RiwayatBerubah, TabelPenuh, TabTidakAda,
                         ambil_pengeluaran_hari_ini, ambil_saldo,
                         ambil_total_kategori, baca_pengaturan,
                         batalkan_terakhir, nama_bulan, pengingat_sudah_dicek,
                         sekarang, simpan_pemasukan, simpan_pemasukan_bank,
                         simpan_pengeluaran, simpan_riwayat,
                         tandai_pengingat_dicek, tulis_pengaturan)

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
NAMA_TERLARANG = {'hapus', 'qris', 'out'}

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
                 'Contoh: ' + nama_perintah + ' 13rb jajan lotek')
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

    Mengembalikan (pesan, kategori). kategori None artinya tidak ada yang dicatat."""
    bagian = argumen.split()
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
    pintasan = ', '.join(daftar_pintasan()) or 'belum ada'
    return ('Perintah:\n'
            '/out <nominal> <kategori> <nama>  (kategori: jajan, alat, mingguan, bulanan, hiburan)\n'
            '/qris <nominal> <kategori> <nama>\n'
            'Tanpa perintah juga bisa: 13rb lotek, qris 13rb lotek, atau nama pintasan. '
            'Beberapa baris sekaligus boleh (maks ' + str(MAKS_BARIS) + ').\n'
            '/out atau /qris <pintasan> [nominal]  (pintasan: ' + pintasan + ')\n'
            '/pintasan  (lihat, tambah, ubah, hapus pintasan)\n'
            '/batas  (batas bulanan per kategori)\n'
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
    '/pintasan': perintah_pintasan,
    '/batas': perintah_batas,
    '/undo': perintah_undo,
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
    return '⚠️ Error: ' + type(e).__name__ + ': ' + str(e)


def baca_pesan_bebas(baris):
    """Pesan tanpa '/': '13rb lotek', 'galon', 'qris 13rb lotek', 'out 5rb es teh'
    -> (argumen untuk catat_pengeluaran, lewat_qris).
    None kalau pesannya tidak mirip pengeluaran. Kata pertama harus berupa nominal
    atau nama pintasan, jadi obrolan biasa tidak ikut tercatat."""
    bagian = baris.split()
    if not bagian:
        return None
    lewat_qris = False
    if bagian[0].lower() in ('qris', 'out'):
        lewat_qris = bagian[0].lower() == 'qris'
        bagian = bagian[1:]
        if not bagian:
            return None
    pertama = bagian[0].lower()
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