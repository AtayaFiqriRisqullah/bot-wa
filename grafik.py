"""Pembuat grafik ringkasan pengeluaran (PNG base64) untuk dikirim ke WhatsApp.

Menggunakan Pillow (PIL) agar ringan, cepat, dan tidak membutuhkan matplotlib/numpy.
"""
import base64
import io
import os
from datetime import date, timedelta

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None


HARI_PENDEK = ('Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min')

WARNA_KATEGORI = {
    'Jajan': '#F97316',
    'Alat': '#3B82F6',
    'Mingguan&Bulanan': '#10B981',
    'Hiburan': '#8B5CF6',
}
WARNA_CADANGAN = ('#0EA5E9', '#EC4899', '#14B8A6', '#EAB308')

LATAR = '#F8FAFC'
KARTU = '#FFFFFF'
GARIS = '#E2E8F0'
GRID = '#F1F5F9'
TEKS_UTAMA = '#0F172A'
TEKS_SEKUNDER = '#475569'
TEKS_REDUP = '#94A3B8'
MERAH = '#EF4444'
KUNING = '#D97706'
BIRU_AKSEN = '#2563EB'

FONT_REGULAR_PATHS = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    'C:/Windows/Fonts/segoeui.ttf',
    'C:/Windows/Fonts/arial.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
)
FONT_BOLD_PATHS = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    'C:/Windows/Fonts/segoeuib.ttf',
    'C:/Windows/Fonts/arialbd.ttf',
    '/System/Library/Fonts/Helvetica.ttc',
)


class GrafikGagal(Exception):
    """Grafik tidak bisa dibuat (misalnya Pillow belum terpasang)."""


def _muat_font(ukuran, tebal=False):
    kandidat = FONT_BOLD_PATHS if tebal else FONT_REGULAR_PATHS
    for jalur in kandidat:
        if os.path.exists(jalur):
            try:
                return ImageFont.truetype(jalur, ukuran)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=ukuran)
    except TypeError:
        return ImageFont.load_default()


def _rupiah(angka):
    tanda = '-' if angka < 0 else ''
    return tanda + 'Rp' + f'{abs(int(round(angka))):,}'.replace(',', '.')


def _rupiah_singkat(angka):
    angka = int(round(angka))
    if angka == 0:
        return '0'
    if angka >= 1_000_000:
        jt = angka / 1_000_000
        return f'{jt:.1f}jt'.replace('.0jt', 'jt').replace('.', ',')
    if angka >= 1_000:
        rb = angka / 1_000
        if rb >= 100 or rb.is_integer():
            return f'{int(round(rb))}rb'
        return f'{rb:.1f}rb'.replace('.', ',')
    return str(angka)


def _lebar_teks(draw, teks, font):
    kotak = draw.textbbox((0, 0), teks, font=font)
    return kotak[2] - kotak[0]


def _potong_teks(draw, teks, font, maks_lebar):
    if _lebar_teks(draw, teks, font) <= maks_lebar:
        return teks
    while len(teks) > 1 and _lebar_teks(draw, teks + '…', font) > maks_lebar:
        teks = teks[:-1]
    return teks.rstrip() + '…'


def _kartu(draw, x1, y1, x2, y2, radius=18):
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=KARTU, outline=GARIS, width=2)


def _hari_terakhir(transaksi, akhir_tanggal, jumlah_hari=7):
    """Kembalikan [(date, total_int), ...] selama `jumlah_hari` terakhir berakhir pada `akhir_tanggal`."""
    awal = akhir_tanggal - timedelta(days=jumlah_hari - 1)
    per_hari = {awal + timedelta(days=i): 0 for i in range(jumlah_hari)}
    for _, _, tgl, nilai, *_ in transaksi:
        if tgl in per_hari and nilai > 0:
            per_hari[tgl] += nilai
    return [(awal + timedelta(days=i), per_hari[awal + timedelta(days=i)])
            for i in range(jumlah_hari)]


def _tanggal_acuan_tab(transaksi, kini_tanggal, tab_bulan_ini):
    """Untuk bulan berjalan, akhiri grafik 7 hari di hari ini.
    Untuk tab bulan lalu, akhiri di tanggal transaksi terbaru pada tab tersebut."""
    if tab_bulan_ini:
        return kini_tanggal
    tanggal_valid = [tgl for _, _, tgl, _, *_ in transaksi if isinstance(tgl, date)]
    return max(tanggal_valid) if tanggal_valid else kini_tanggal


def _gambar_grafik_harian(draw, x1, y1, x2, y2, seri_harian, judul, f_sub, f_kecil, f_label):
    _kartu(draw, x1, y1, x2, y2)
    draw.text((x1 + 28, y1 + 22), judul, fill=TEKS_UTAMA, font=f_sub)

    total_7h = sum(v for _, v in seri_harian)
    rata_7h = total_7h / len(seri_harian) if seri_harian else 0
    info_kanan = 'Rata-rata: ' + _rupiah(rata_7h) + '/hari'
    draw.text((x2 - 28 - _lebar_teks(draw, info_kanan, f_kecil), y1 + 26),
              info_kanan, fill=TEKS_SEKUNDER, font=f_kecil)

    area_kiri = x1 + 36
    area_kanan = x2 - 36
    area_atas = y1 + 88
    area_bawah = y2 - 66
    tinggi_area = max(1, area_bawah - area_atas)

    maks_nilai = max((v for _, v in seri_harian), default=0)
    skala_maks = max(maks_nilai, 1)

    # Garis bantu horizontal
    for step in range(4):
        gy = area_bawah - int(tinggi_area * step / 3)
        draw.line([(area_kiri, gy), (area_kanan, gy)], fill=GRID if step > 0 else GARIS, width=2)

    n = len(seri_harian)
    slot = (area_kanan - area_kiri) / max(n, 1)
    lebar_bar = min(72, int(slot * 0.56))

    for i, (tgl, nilai) in enumerate(seri_harian):
        cx = int(area_kiri + slot * (i + 0.5))
        bx1 = cx - lebar_bar // 2
        bx2 = cx + lebar_bar // 2
        if nilai > 0:
            tinggi = max(8, int((nilai / skala_maks) * (tinggi_area - 10)))
            by1 = area_bawah - tinggi
            warna = '#1D4ED8' if nilai == maks_nilai else '#60A5FA'
            draw.rounded_rectangle([bx1, by1, bx2, area_bawah], radius=10, fill=warna)
            teks_val = _rupiah_singkat(nilai)
            lw = _lebar_teks(draw, teks_val, f_kecil)
            draw.text((cx - lw // 2, by1 - 28), teks_val,
                      fill=TEKS_UTAMA if nilai == maks_nilai else TEKS_SEKUNDER, font=f_kecil)
        else:
            draw.rounded_rectangle([bx1, area_bawah - 4, bx2, area_bawah], radius=2, fill=GARIS)

        label_hari = HARI_PENDEK[tgl.weekday()]
        label_tgl = tgl.strftime('%d/%m')
        lw1 = _lebar_teks(draw, label_hari, f_label)
        lw2 = _lebar_teks(draw, label_tgl, f_kecil)
        draw.text((cx - lw1 // 2, area_bawah + 10), label_hari, fill=TEKS_UTAMA, font=f_label)
        draw.text((cx - lw2 // 2, area_bawah + 34), label_tgl, fill=TEKS_REDUP, font=f_kecil)


def _ke_base64(img):
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return base64.b64encode(buf.getvalue()).decode('ascii')


def buat_grafik_bulanan(nama_tab, total_kategori, transaksi, batas=None, kini=None, tab_bulan_ini=True):
    """Buat gambar PNG (base64) ringkasan pengeluaran bulanan + tren 7 hari terakhir.
    Mengembalikan (caption_teks, png_base64)."""
    if Image is None:
        raise GrafikGagal('Library Pillow belum terpasang. Jalankan: pip install Pillow')

    kini_tgl = kini.date() if hasattr(kini, 'date') else (kini or date.today())
    batas = batas or {}

    urutan = sorted(total_kategori.items(), key=lambda item: item[1], reverse=True)
    total_semua = sum(v for _, v in urutan)
    jumlah_transaksi = len(transaksi)
    hari_pembagi = max(1, kini_tgl.day) if tab_bulan_ini else max(
        1, len({tgl for _, _, tgl, _, *_ in transaksi if isinstance(tgl, date)})
    )
    rata_harian = total_semua / hari_pembagi

    akhir_7h = _tanggal_acuan_tab(transaksi, kini_tgl, tab_bulan_ini)
    seri_harian = _hari_terakhir(transaksi, akhir_7h, 7)

    lebar = 1080
    tinggi_kategori = 94 + max(len(urutan), 1) * 96 + 24
    tinggi_harian = 360
    tinggi = 140 + 132 + tinggi_kategori + tinggi_harian + 90

    img = Image.new('RGB', (lebar, tinggi), LATAR)
    draw = ImageDraw.Draw(img)

    f_judul = _muat_font(36, tebal=True)
    f_sub = _muat_font(24, tebal=True)
    f_kpi = _muat_font(30, tebal=True)
    f_teks = _muat_font(22, tebal=False)
    f_teks_tebal = _muat_font(22, tebal=True)
    f_kecil = _muat_font(18, tebal=False)
    f_label = _muat_font(19, tebal=True)

    pad = 40

    # Header
    judul = f'Ringkasan Pengeluaran — {nama_tab}'
    draw.text((pad, 34), judul, fill=TEKS_UTAMA, font=f_judul)
    sub_hdr = f'Diperbarui {kini_tgl.strftime("%d/%m/%Y")} • Tab {nama_tab}'
    draw.text((pad, 84), sub_hdr, fill=TEKS_SEKUNDER, font=f_teks)

    # 3 Kartu KPI
    y_kpi = 132
    jarak = 20
    lebar_kpi = (lebar - 2 * pad - 2 * jarak) // 3
    kpis = [
        ('Total Pengeluaran', _rupiah(total_semua), TEKS_UTAMA),
        ('Jumlah Transaksi', f'{jumlah_transaksi} transaksi', BIRU_AKSEN),
        ('Rata-rata / Hari', _rupiah(rata_harian), '#059669'),
    ]
    for i, (label, nilai_str, warna_val) in enumerate(kpis):
        kx1 = pad + i * (lebar_kpi + jarak)
        kx2 = kx1 + lebar_kpi
        _kartu(draw, kx1, y_kpi, kx2, y_kpi + 110, radius=16)
        draw.text((kx1 + 22, y_kpi + 18), label, fill=TEKS_SEKUNDER, font=f_kecil)
        draw.text((kx1 + 22, y_kpi + 52), _potong_teks(draw, nilai_str, f_kpi, lebar_kpi - 44),
                  fill=warna_val, font=f_kpi)

    # Kartu Kategori
    y_kat = y_kpi + 132
    y_kat_bawah = y_kat + tinggi_kategori
    _kartu(draw, pad, y_kat, lebar - pad, y_kat_bawah)
    draw.text((pad + 28, y_kat + 22), 'Pengeluaran per Kategori', fill=TEKS_UTAMA, font=f_sub)

    maks_kat = max([v for _, v in urutan] + [batas.get(k, 0) for k, _ in urutan] + [1])
    bar_x1 = pad + 28
    bar_x2 = lebar - pad - 28
    lebar_track = bar_x2 - bar_x1

    y_pos = y_kat + 78
    for idx, (kat, nilai) in enumerate(urutan):
        warna = WARNA_KATEGORI.get(kat, WARNA_CADANGAN[idx % len(WARNA_CADANGAN)])
        persen = (nilai * 100 / total_semua) if total_semua > 0 else 0
        kiri_teks = f'{kat}  ({persen:.1f}%)'.replace('.', ',')
        draw.text((bar_x1, y_pos), kiri_teks, fill=TEKS_UTAMA, font=f_teks_tebal)

        kanan_teks = _rupiah(nilai)
        warna_kanan = TEKS_UTAMA
        batas_kat = batas.get(kat)
        if batas_kat:
            persen_batas = int(nilai * 100 / batas_kat)
            kanan_teks += f' / {_rupiah(batas_kat)} ({persen_batas}%)'
            if nilai > batas_kat:
                warna_kanan = MERAH
                warna = MERAH
            elif persen_batas >= 80:
                warna_kanan = KUNING
        lw_kanan = _lebar_teks(draw, kanan_teks, f_teks)
        draw.text((bar_x2 - lw_kanan, y_pos + 2), kanan_teks, fill=warna_kanan, font=f_teks)

        # Track bar
        ty1 = y_pos + 36
        ty2 = ty1 + 26
        draw.rounded_rectangle([bar_x1, ty1, bar_x2, ty2], radius=12, fill=GRID)
        if nilai > 0:
            rasio = min(1.0, nilai / maks_kat)
            fill_w = max(18, int(lebar_track * rasio))
            draw.rounded_rectangle([bar_x1, ty1, bar_x1 + fill_w, ty2], radius=12, fill=warna)

        # Garis batas jika diatur
        if batas_kat and batas_kat > 0:
            pos_batas = bar_x1 + int(lebar_track * min(1.0, batas_kat / maks_kat))
            draw.line([(pos_batas, ty1 - 5), (pos_batas, ty2 + 5)], fill=TEKS_UTAMA, width=3)

        y_pos += 96

    # Kartu Tren 7 Hari
    y_har = y_kat_bawah + 24
    judul_har = 'Tren 7 Hari Terakhir' if tab_bulan_ini else f'Tren 7 Hari Terakhir ({nama_tab})'
    _gambar_grafik_harian(draw, pad, y_har, lebar - pad, y_har + tinggi_harian,
                          seri_harian, judul_har, f_sub, f_kecil, f_label)

    # Footer
    footer = 'Dibuat otomatis oleh Bot WA Keuangan'
    draw.text((pad, tinggi - 42), footer, fill=TEKS_REDUP, font=f_kecil)

    # Caption ringkas untuk WhatsApp & CLI fallback
    baris_cap = [f'📊 Grafik Pengeluaran {nama_tab}', f'Total: {_rupiah(total_semua)} ({jumlah_transaksi} transaksi)']
    for kat, nilai in urutan:
        if nilai > 0:
            persen = (nilai * 100 / total_semua) if total_semua else 0
            baris_cap.append(f'• {kat}: {_rupiah(nilai)} ({persen:.0f}%)')
    return '\n'.join(baris_cap), _ke_base64(img)


def buat_grafik_mingguan(transaksi, kini=None):
    """Buat gambar PNG (base64) fokus tren 7 hari terakhir + 5 transaksi terbesar minggu ini.
    Mengembalikan (caption_teks, png_base64)."""
    if Image is None:
        raise GrafikGagal('Library Pillow belum terpasang. Jalankan: pip install Pillow')

    kini_tgl = kini.date() if hasattr(kini, 'date') else (kini or date.today())
    seri_harian = _hari_terakhir(transaksi, kini_tgl, 7)
    awal_7h = kini_tgl - timedelta(days=6)

    transaksi_7h = [t for t in transaksi if isinstance(t[2], date) and awal_7h <= t[2] <= kini_tgl and t[3] > 0]
    transaksi_7h.sort(key=lambda t: t[3], reverse=True)
    top5 = transaksi_7h[:5]

    total_7h = sum(v for _, v in seri_harian)
    rata_7h = total_7h / 7
    hari_terbesar = max(seri_harian, key=lambda x: x[1])

    lebar = 1080
    tinggi_top = 86 + max(len(top5), 1) * 54 + 24
    tinggi = 132 + 132 + 370 + tinggi_top + 80

    img = Image.new('RGB', (lebar, tinggi), LATAR)
    draw = ImageDraw.Draw(img)

    f_judul = _muat_font(36, tebal=True)
    f_sub = _muat_font(24, tebal=True)
    f_kpi = _muat_font(28, tebal=True)
    f_teks = _muat_font(21, tebal=False)
    f_teks_tebal = _muat_font(21, tebal=True)
    f_kecil = _muat_font(18, tebal=False)
    f_label = _muat_font(19, tebal=True)

    pad = 40
    draw.text((pad, 34), 'Pengeluaran 7 Hari Terakhir', fill=TEKS_UTAMA, font=f_judul)
    rentang_str = f'{awal_7h.strftime("%d/%m/%Y")} – {kini_tgl.strftime("%d/%m/%Y")}'
    draw.text((pad, 84), rentang_str, fill=TEKS_SEKUNDER, font=f_teks)

    y_kpi = 132
    jarak = 20
    lebar_kpi = (lebar - 2 * pad - 2 * jarak) // 3
    puncak_teks = (_rupiah(hari_terbesar[1]) + f' ({HARI_PENDEK[hari_terbesar[0].weekday()]})'
                   if hari_terbesar[1] > 0 else 'Rp0')
    kpis = [
        ('Total 7 Hari', _rupiah(total_7h), TEKS_UTAMA),
        ('Rata-rata / Hari', _rupiah(rata_7h), BIRU_AKSEN),
        ('Tertinggi', puncak_teks, '#DC2626'),
    ]
    for i, (label, nilai_str, warna_val) in enumerate(kpis):
        kx1 = pad + i * (lebar_kpi + jarak)
        kx2 = kx1 + lebar_kpi
        _kartu(draw, kx1, y_kpi, kx2, y_kpi + 108, radius=16)
        draw.text((kx1 + 22, y_kpi + 16), label, fill=TEKS_SEKUNDER, font=f_kecil)
        draw.text((kx1 + 22, y_kpi + 50), _potong_teks(draw, nilai_str, f_kpi, lebar_kpi - 44),
                  fill=warna_val, font=f_kpi)

    y_har = y_kpi + 130
    _gambar_grafik_harian(draw, pad, y_har, lebar - pad, y_har + 360,
                          seri_harian, 'Grafik Pengeluaran Harian', f_sub, f_kecil, f_label)

    y_top = y_har + 384
    _kartu(draw, pad, y_top, lebar - pad, y_top + tinggi_top)
    draw.text((pad + 28, y_top + 22), 'Pengeluaran Terbesar (7 Hari)', fill=TEKS_UTAMA, font=f_sub)

    y_row = y_top + 74
    if not top5:
        draw.text((pad + 28, y_row), 'Belum ada transaksi dalam 7 hari terakhir.',
                  fill=TEKS_SEKUNDER, font=f_teks)
    else:
        for idx, (kat, nama, tgl, nilai, *_) in enumerate(top5, 1):
            kiri = f'{idx}. {nama} ({kat}, {tgl.strftime("%d/%m")})'
            kanan = _rupiah(nilai)
            lw_kanan = _lebar_teks(draw, kanan, f_teks_tebal)
            maks_kiri = (lebar - 2 * pad - 56) - lw_kanan - 24
            draw.text((pad + 28, y_row), _potong_teks(draw, kiri, f_teks, maks_kiri),
                      fill=TEKS_UTAMA, font=f_teks)
            draw.text((lebar - pad - 28 - lw_kanan, y_row), kanan,
                      fill=TEKS_UTAMA, font=f_teks_tebal)
            y_row += 54

    draw.text((pad, tinggi - 42), 'Dibuat otomatis oleh Bot WA Keuangan', fill=TEKS_REDUP, font=f_kecil)

    caption = (f'📈 Pengeluaran 7 Hari Terakhir ({awal_7h.strftime("%d/%m")}–{kini_tgl.strftime("%d/%m")})\n'
               f'Total: {_rupiah(total_7h)} · Rata-rata: {_rupiah(rata_7h)}/hari\n'
               f'Transaksi: {len(transaksi_7h)}x')
    return caption, _ke_base64(img)
