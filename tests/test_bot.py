"""Pengujian otomatis menyeluruh untuk seluruh fitur Bot WA.

Menjalankan simulasi formula persis seperti Monthly_Budget.xlsx (Hasil Akhir,
Sisa Saldo Bank BNI & Mandiri, tabel Pemasukan, Pemasukan Bank, dan 4 tabel Pengeluaran).
"""
import base64
import os
import re
import sys
import tempfile
import types
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _pasang_stub_jika_perlu():
    """Sediakan stub ringan jika dependensi Google/requests belum terpasang di lingkungan test."""
    if 'requests' not in sys.modules:
        try:
            import requests  # noqa: F401
        except ImportError:
            mod_req = types.ModuleType('requests')
            mod_exc = types.ModuleType('requests.exceptions')

            class RequestException(Exception):
                pass

            class InvalidURL(RequestException):
                pass

            class MissingSchema(RequestException):
                pass

            class InvalidSchema(RequestException):
                pass

            mod_exc.RequestException = RequestException
            mod_exc.InvalidURL = InvalidURL
            mod_exc.MissingSchema = MissingSchema
            mod_exc.InvalidSchema = InvalidSchema
            mod_req.exceptions = mod_exc
            mod_req.get = lambda *a, **kw: None
            mod_req.post = lambda *a, **kw: None
            sys.modules['requests'] = mod_req
            sys.modules['requests.exceptions'] = mod_exc

    if 'httplib2' not in sys.modules:
        try:
            import httplib2  # noqa: F401
        except ImportError:
            mod_h = types.ModuleType('httplib2')

            class HttpLib2Error(Exception):
                pass

            mod_h.HttpLib2Error = HttpLib2Error
            sys.modules['httplib2'] = mod_h

    if 'google.auth.exceptions' not in sys.modules:
        try:
            import google.auth.exceptions  # noqa: F401
        except ImportError:
            for nama in ('google', 'google.auth', 'google.auth.exceptions',
                         'google.oauth2', 'google.oauth2.service_account'):
                sys.modules.setdefault(nama, types.ModuleType(nama))

            class TransportError(Exception):
                pass

            sys.modules['google.auth.exceptions'].TransportError = TransportError
            sys.modules['google.oauth2'].service_account = sys.modules['google.oauth2.service_account']
            sys.modules['google.oauth2.service_account'].Credentials = type(
                'Credentials', (), {'from_service_account_info': staticmethod(lambda *a, **kw: object())}
            )

    if 'googleapiclient.discovery' not in sys.modules:
        try:
            import googleapiclient.discovery  # noqa: F401
        except ImportError:
            for nama in ('googleapiclient', 'googleapiclient.discovery', 'googleapiclient.errors'):
                sys.modules.setdefault(nama, types.ModuleType(nama))

            class HttpError(Exception):
                def __init__(self, status=500, msg='error'):
                    super().__init__(msg)
                    self.resp = types.SimpleNamespace(status=status)

            sys.modules['googleapiclient.discovery'].build = lambda *a, **kw: object()
            sys.modules['googleapiclient.errors'].HttpError = HttpError

    if 'gspread' not in sys.modules:
        try:
            import gspread  # noqa: F401
        except ImportError:
            for nama in ('gspread', 'gspread.exceptions', 'gspread.utils'):
                sys.modules.setdefault(nama, types.ModuleType(nama))

            class APIError(Exception):
                def __init__(self, status=500):
                    self.response = types.SimpleNamespace(status_code=status)

            class WorksheetNotFound(Exception):
                pass

            def a1_to_rowcol(label):
                m = re.fullmatch(r'([A-Za-z]+)(\d+)', label)
                col = 0
                for ch in m.group(1).upper():
                    col = col * 26 + (ord(ch) - ord('A') + 1)
                return int(m.group(2)), col

            sys.modules['gspread'].service_account_from_dict = lambda *a, **kw: object()
            sys.modules['gspread.exceptions'].APIError = APIError
            sys.modules['gspread.exceptions'].WorksheetNotFound = WorksheetNotFound
            sys.modules['gspread.utils'].a1_to_rowcol = a1_to_rowcol


_pasang_stub_jika_perlu()

import ai_input  # noqa: E402
import api_lokal  # noqa: E402
import config  # noqa: E402
import grafik  # noqa: E402
import kalender  # noqa: E402
import otak  # noqa: E402
import penyimpanan  # noqa: E402


def _kol_ke_idx(kol):
    idx = 0
    for ch in kol.upper():
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx


def _parse_a1(sel):
    m = re.fullmatch(r'([A-Za-z]+)(\d+)', sel.strip())
    return int(m.group(2)), _kol_ke_idx(m.group(1))


class SheetPalsu:
    """Simulator worksheet yang menghitung rumus persis seperti Monthly_Budget.xlsx."""

    def __init__(self, title, sisa_bulanan=160000, modal_bni=4000000, modal_mandiri=500000):
        self.title = title
        self.cells = {}
        # Baris 9: Sisa Bulanan di Pemasukan (B9:D9)
        self._set(9, 2, 'Sisa Bulanan')
        self._set(9, 3, '2026-11-01')
        self._set(9, 4, sisa_bulanan)
        # Modal awal bank di Pemasukan Bank (T10:V11)
        if modal_bni:
            self._set(10, 20, 'BNI')
            self._set(10, 21, '2026-11-01')
            self._set(10, 22, modal_bni)
        if modal_mandiri:
            self._set(11, 20, 'Mandiri')
            self._set(11, 21, '2026-11-01')
            self._set(11, 22, modal_mandiri)

    def _set(self, r, c, val):
        self.cells[(r, c)] = val

    def _get(self, r, c):
        return self.cells.get((r, c), '')

    def _num(self, r, c):
        v = self._get(r, c)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0

    def _sum_range(self, c, r1, r2):
        return sum(self._num(r, c) for r in range(r1, r2 + 1))

    def _sumif_contains(self, c_krit, r1, r2, kata, c_val):
        k = kata.lower()
        total = 0.0
        for r in range(r1, r2 + 1):
            teks = str(self._get(r, c_krit)).lower()
            if k in teks:
                total += self._num(r, c_val)
        return total

    def hitung_rumus(self):
        """Hitung nilai sel rumus persis seperti tab November di Monthly_Budget.xlsx."""
        pemasukan = self._sum_range(4, 9, 31)                         # H10 = SUM(D9:D31)
        tot_jajan = self._sum_range(4, 36, 1000)                      # D35
        tot_alat = self._sum_range(9, 36, 1000)                       # I35
        tot_mb = self._sum_range(13, 36, 1000)                        # M35
        tot_hiburan = self._sum_range(18, 36, 1000)                   # R35
        pengeluaran = tot_jajan + tot_alat + tot_mb + tot_hiburan     # H11
        sisa_uang = pemasukan - pengeluaran                           # H12

        def saldo_bank(nama):
            masuk = self._sumif_contains(20, 10, 31, nama, 22)
            keluar = (
                self._sumif_contains(2, 10, 31, nama, 4)
                + self._sumif_contains(2, 36, 1000, nama, 4)
                + self._sumif_contains(7, 36, 1000, nama, 9)
                + self._sumif_contains(11, 36, 1000, nama, 13)
                + self._sumif_contains(16, 36, 1000, nama, 18)
            )
            return masuk - keluar

        bni = saldo_bank('BNI')                                       # L11
        mandiri = saldo_bank('Mandiri')                               # L12
        return {
            'Pemasukan': pemasukan,
            'Pengeluaran': pengeluaran,
            'Sisa Uang': sisa_uang,
            'BNI': bni,
            'Mandiri': mandiri,
            'Total Bank': bni + mandiri,
            'D35': tot_jajan,
            'I35': tot_alat,
            'M35': tot_mb,
            'R35': tot_hiburan,
        }

    def col_values(self, nomor_kolom):
        baris_maks = max((r for r, c in self.cells if c == nomor_kolom and str(self.cells[(r, c)]) != ''), default=0)
        return [str(self._get(r, nomor_kolom)) for r in range(1, baris_maks + 1)]

    def update(self, range_name, values, raw=False):
        awal = range_name.split(':')[0]
        r0, c0 = _parse_a1(awal)
        for dr, baris in enumerate(values):
            for dc, val in enumerate(baris):
                self._set(r0 + dr, c0 + dc, val)

    def batch_clear(self, ranges):
        for rg in ranges:
            bagian = rg.split(':')
            r1, c1 = _parse_a1(bagian[0])
            r2, c2 = _parse_a1(bagian[1]) if len(bagian) > 1 else (r1, c1)
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    self.cells.pop((r, c), None)

    def get(self, range_name, value_render_option=None):
        rumus = self.hitung_rumus()
        if range_name == penyimpanan.RENTANG_HASIL_AKHIR:
            return [
                ['Total', 'Nilai'],
                ['Pemasukan', rumus['Pemasukan']],
                ['Pengeluaran', rumus['Pengeluaran']],
                ['Sisa Uang', rumus['Sisa Uang']],
            ]
        if range_name == penyimpanan.RENTANG_SALDO_BANK:
            return [
                ['Source', 'Nilai'],
                ['Total', rumus['Total Bank']],
                ['BNI', rumus['BNI']],
                ['Mandiri', rumus['Mandiri']],
            ]

        bagian = range_name.split(':')
        r1, c1 = _parse_a1(bagian[0])
        r2, c2 = _parse_a1(bagian[1]) if len(bagian) > 1 else (r1, c1)

        # Injeksi baris TOTAL (baris 35)
        hasil = []
        baris_akhir_terisi = r1 - 1
        for r in range(r1, r2 + 1):
            row_vals = []
            ada_isi = False
            for c in range(c1, c2 + 1):
                if r == 35 and c == 4:
                    v = rumus['D35']
                elif r == 35 and c == 9:
                    v = rumus['I35']
                elif r == 35 and c == 13:
                    v = rumus['M35']
                elif r == 35 and c == 18:
                    v = rumus['R35']
                else:
                    v = self._get(r, c)
                if v != '':
                    ada_isi = True
                row_vals.append(v)
            hasil.append(row_vals)
            if ada_isi:
                baris_akhir_terisi = r
        panjang = max(0, baris_akhir_terisi - r1 + 1)
        return hasil[:panjang]

    def batch_get(self, ranges, value_render_option=None):
        return [self.get(rg, value_render_option=value_render_option) for rg in ranges]


class BukuPalsu:
    def __init__(self, sheets):
        self.sheets = sheets

    def worksheet(self, nama):
        if nama not in self.sheets:
            raise penyimpanan.WorksheetNotFound(nama)
        return self.sheets[nama]


class TestBotWA(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.kini = datetime(2026, 11, 24, 10, 0, 0, tzinfo=penyimpanan.WIB)

        self.sheet_nov = SheetPalsu('November', sisa_bulanan=200_000, modal_bni=3_000_000, modal_mandiri=500_000)
        self.sheet_okt = SheetPalsu('Oktober', sisa_bulanan=100_000, modal_bni=2_000_000, modal_mandiri=100_000)
        self.buku = BukuPalsu({'November': self.sheet_nov, 'Oktober': self.sheet_okt})

        self.patchers = [
            patch.object(penyimpanan, '_buku', self.buku),
            patch.object(penyimpanan, 'RIWAYAT_FILE', os.path.join(self.tmpdir.name, 'riwayat.json')),
            patch.object(penyimpanan, 'STATUS_FILE', os.path.join(self.tmpdir.name, 'status.json')),
            patch.object(penyimpanan, 'PENGATURAN_FILE', os.path.join(self.tmpdir.name, 'pengaturan.json')),
            patch.object(penyimpanan, 'DEADLINE_FILE', os.path.join(self.tmpdir.name, 'deadline.json')),
            patch.object(penyimpanan, 'PENGINGAT_CEPAT_FILE', os.path.join(self.tmpdir.name, 'pengingat_cepat.json')),
            patch.object(penyimpanan, 'TAGIHAN_FILE', os.path.join(self.tmpdir.name, 'tagihan.json')),
            patch.object(penyimpanan, 'KONFIRMASI_FILE', os.path.join(self.tmpdir.name, 'konfirmasi.json')),
            patch.object(penyimpanan, 'sekarang', side_effect=lambda: self.kini),
            patch.object(otak, 'sekarang', side_effect=lambda: self.kini),
            patch.object(config, 'GEMINI_API_KEY', ''),
            patch.object(config, 'OPENAI_API_KEY', ''),
            patch.object(config, 'CALENDAR_ID', 'test-cal@group.calendar.google.com'),
            patch.object(config, 'DEADLINE_KE_KALENDER', True),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.tmpdir.cleanup()

    # ------------------------------------------------------------------
    # Area 1: Keamanan config & Endpoint API
    # ------------------------------------------------------------------

    def test_config_tidak_ada_rahasia_hardcoded(self):
        with open(os.path.join(ROOT, 'config.py'), encoding='utf-8') as f:
            isi = f.read()
        self.assertNotIn('AKfycbyi', isi)
        self.assertNotIn('1DFHCt1NPUBjcsJukxQQO7inKHBgYujTYl2X70_wJv34', isi)
        self.assertNotIn("'12345'", isi)

    def test_api_lokal_endpoints(self):
        self.assertEqual(api_lokal.health(), {'ok': True})
        res = api_lokal.proses(api_lokal.PesanMasuk(teks='/saldo', pengirim='628111'))
        self.assertIn('BNI: Rp3.000.000', res['balasan'])
        self.assertIsNone(res['gambar_base64'])
        with patch.object(otak, 'event_hari_ini', return_value=[('09:00', 'Kuliah')]), \
             patch.object(otak, 'ambil_cuaca', return_value='☀️ Cuaca Yogyakarta: cerah, 25–32°C'):
            res_peng = api_lokal.pengingat()
            self.assertIn('Selamat pagi!', res_peng['pesan'])
            # Panggilan kedua di hari yang sama tidak mengirim pesan pagi lagi
            res_peng2 = api_lokal.pengingat()
            self.assertIsNone(res_peng2['pesan'])

    # ------------------------------------------------------------------
    # Area 3: Keuangan Lengkap sesuai rumus Monthly_Budget.xlsx
    # ------------------------------------------------------------------

    def test_qris_bni_dan_mandiri_serta_tarik_mandiri(self):
        # Awal: Tunai 200rb, BNI 3jt, Mandiri 500rb (Total 3.7jt)
        r1 = otak.proses_pesan('/qris 25rb kopi')
        self.assertIn('QRIS BNI', r1)
        rumus = self.sheet_nov.hitung_rumus()
        self.assertEqual(rumus['Sisa Uang'], 200_000)
        self.assertEqual(rumus['BNI'], 2_975_000)
        self.assertEqual(rumus['Mandiri'], 500_000)

        r2 = otak.proses_pesan('/qris mandiri 15rb tempe')
        self.assertIn('QRIS Mandiri', r2)
        rumus = self.sheet_nov.hitung_rumus()
        self.assertEqual(rumus['Sisa Uang'], 200_000)
        self.assertEqual(rumus['BNI'], 2_975_000)
        self.assertEqual(rumus['Mandiri'], 485_000)

        # Free-text QRIS Mandiri juga dikenali
        r3 = otak.proses_pesan('qris mandiri 10rb es teh')
        self.assertIn('QRIS Mandiri', r3)
        self.assertEqual(self.sheet_nov.hitung_rumus()['Mandiri'], 475_000)

        # Tarik tunai Mandiri -> Mandiri berkurang, Tunai bertambah
        r4 = otak.proses_pesan('/tarik mandiri 100rb')
        self.assertIn('Tarik Uang Mandiri', r4)
        rumus = self.sheet_nov.hitung_rumus()
        self.assertEqual(rumus['Mandiri'], 375_000)
        self.assertEqual(rumus['Sisa Uang'], 300_000)

    def test_pemasukan_umum_tunai_dan_bank(self):
        # Pemasukan tunai tidak mengurangi saldo bank
        r1 = otak.proses_pesan('/in 150rb uang saku')
        self.assertIn('Pemasukan tunai', r1)
        rumus = self.sheet_nov.hitung_rumus()
        self.assertEqual(rumus['Sisa Uang'], 350_000)
        self.assertEqual(rumus['BNI'], 3_000_000)
        self.assertEqual(rumus['Mandiri'], 500_000)

        # Perlindungan kata bank pada pemasukan tunai
        r_warn = otak.proses_pesan('/in 100rb kiriman bni')
        self.assertIn('tidak boleh mengandung kata "BNI"', r_warn)

        # Pemasukan bank BNI + keterangan
        r2 = otak.proses_pesan('/in bni 1,5jt gaji freelance')
        self.assertIn('BNI - gaji freelance', r2)
        rumus = self.sheet_nov.hitung_rumus()
        self.assertEqual(rumus['BNI'], 4_500_000)
        self.assertEqual(rumus['Sisa Uang'], 350_000)

        # Undo pemasukan bank
        r_undo = otak.proses_pesan('/undo')
        self.assertIn('Dibatalkan', r_undo)
        self.assertEqual(self.sheet_nov.hitung_rumus()['BNI'], 3_000_000)

    def test_transfer_semua_arah_dan_undo_atomik(self):
        # Awal: Tunai 200rb, BNI 3.000rb, Mandiri 500rb -> Total 3.700rb
        def cek_total():
            rm = self.sheet_nov.hitung_rumus()
            self.assertEqual(rm['Sisa Uang'] + rm['BNI'] + rm['Mandiri'], 3_700_000)
            return rm

        # 1. BNI -> Mandiri (200rb)
        r = otak.proses_pesan('/transfer bni mandiri 200rb')
        self.assertIn('BNI → Mandiri', r)
        rm = cek_total()
        self.assertEqual((rm['Sisa Uang'], rm['BNI'], rm['Mandiri']), (200_000, 2_800_000, 700_000))

        # 2. Mandiri -> BNI (50rb)
        otak.proses_pesan('/tf mandiri bni 50rb')
        rm = cek_total()
        self.assertEqual((rm['Sisa Uang'], rm['BNI'], rm['Mandiri']), (200_000, 2_850_000, 650_000))

        # 3. Tunai -> BNI (100rb)
        otak.proses_pesan('/transfer tunai bni 100rb')
        rm = cek_total()
        self.assertEqual((rm['Sisa Uang'], rm['BNI'], rm['Mandiri']), (100_000, 2_950_000, 650_000))

        # 4. BNI -> Tunai (150rb)
        otak.proses_pesan('/transfer bni tunai 150rb')
        rm = cek_total()
        self.assertEqual((rm['Sisa Uang'], rm['BNI'], rm['Mandiri']), (250_000, 2_800_000, 650_000))

        # 5. Mandiri -> Tunai (50rb)
        otak.proses_pesan('/transfer mandiri tunai 50rb')
        rm = cek_total()
        self.assertEqual((rm['Sisa Uang'], rm['BNI'], rm['Mandiri']), (300_000, 2_800_000, 600_000))

        # 6. Tunai -> Mandiri (80rb) lalu /undo (2 baris sekaligus dibatalkan!)
        otak.proses_pesan('/transfer tunai mandiri 80rb')
        rm = cek_total()
        self.assertEqual((rm['Sisa Uang'], rm['BNI'], rm['Mandiri']), (220_000, 2_800_000, 680_000))
        otak.proses_pesan('/undo')
        rm = cek_total()
        self.assertEqual((rm['Sisa Uang'], rm['BNI'], rm['Mandiri']), (300_000, 2_800_000, 600_000))

    def test_cari_transaksi_dan_grafik(self):
        otak.proses_pesan('/out 15rb kopi kenangan')
        otak.proses_pesan('/out 22rb kopi susu')
        otak.proses_pesan('/out 65rb alat kabel usb')
        otak.proses_pesan('/out kemarin 30rb bulanan laundry')

        r_cari = otak.proses_pesan('/cari_transaksi kopi')
        self.assertIn('2 transaksi', r_cari)
        self.assertIn('Rp37.000', r_cari)

        # Grafik bulanan menghasilkan PNG valid base64
        res_g = otak.proses_pesan_lengkap('/grafik')
        self.assertIsNotNone(res_g['gambar_base64'])
        png_bytes = base64.b64decode(res_g['gambar_base64'])
        self.assertTrue(png_bytes.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertIn('Rp132.000', res_g['teks'])

        # Grafik mingguan juga valid
        res_m = otak.proses_pesan_lengkap('/grafik mingguan')
        self.assertTrue(base64.b64decode(res_m['gambar_base64']).startswith(b'\x89PNG\r\n\x1a\n'))

    def test_tagihan_rutin_manual_dan_auto(self):
        # Tambah tagihan manual & tagihan auto
        r1 = otak.proses_pesan('/tagihan tambah 24 100rb bulanan qris WiFi Kos')
        self.assertIn('Tagihan rutin ditambah', r1)
        r2 = otak.proses_pesan('/tagihan tambah 20 50rb hiburan qris auto Spotify')
        self.assertIn('otomatis dicatat', r2)

        # Penjadwal pada jam 10:00 WIB: WiFi diingatkan, Spotify dicatat otomatis
        ingat = otak.pengingat_tagihan()
        self.assertIn('Pengingat tagihan rutin', ingat)
        self.assertIn('WiFi Kos', ingat)
        self.assertIn('Tagihan otomatis dicatat', ingat)
        self.assertIn('Spotify', ingat)

        # Pemanggilan ulang di bulan yang sama tidak mengirim ganda
        self.assertIsNone(otak.pengingat_tagihan())

        # Bayar WiFi Kos manual
        r_bayar = otak.proses_pesan('/tagihan bayar wifi')
        self.assertIn('Tagihan dibayar', r_bayar)
        self.assertIn('QRIS BNI', r_bayar)

        daftar = otak.proses_pesan('/tagihan')
        self.assertEqual(daftar.count('✅'), 2)

        # Hapus tagihan
        r_hps = otak.proses_pesan('/tagihan hapus spotify')
        self.assertIn('dihapus', r_hps)

    # ------------------------------------------------------------------
    # Area 4: /ingatkan dan sinkronisasi /deadline <-> Google Calendar
    # ------------------------------------------------------------------

    def test_ingatkan_cepat_dan_pemicu(self):
        r1 = otak.proses_pesan('/ingatkan 30m angkat jemuran')
        self.assertIn('Pengingat disimpan: angkat jemuran', r1)
        r2 = otak.proses_pesan('/ingatkan 21:00 matikan kompor')
        self.assertIn('21:00', r2)

        # Belum jatuh tempo pada jam 10:00
        self.assertIsNone(otak.pengingat_cepat())
        self.assertIn('angkat jemuran', otak.proses_pesan('/ingatkan'))

        # Maju 35 menit -> angkat jemuran jatuh tempo, matikan kompor belum
        self.kini = datetime(2026, 11, 24, 10, 35, 0, tzinfo=penyimpanan.WIB)
        terkirim = otak.pengingat_cepat()
        self.assertIn('angkat jemuran', terkirim)
        self.assertNotIn('matikan kompor', terkirim)

        # Sudah terhapus setelah terkirim, jadi tidak dikirim dua kali
        self.assertIsNone(otak.pengingat_cepat())
        self.assertNotIn('angkat jemuran', otak.proses_pesan('/ingatkan'))

        # Hapus pengingat yang tersisa
        r_hps = otak.proses_pesan('/ingatkan hapus 1')
        self.assertIn('dihapus', r_hps)

    def test_deadline_sinkron_google_calendar(self):
        dibuat_penanda = []
        dibuat_event = []
        dihapus = []

        def fake_penanda(judul, tgl, deskripsi=''):
            eid = 'penanda-1'
            dibuat_penanda.append((judul, tgl, deskripsi))
            return eid

        def fake_event(judul, mulai, durasi_menit=60, warna_id=None, deskripsi=''):
            eid = 'event-1'
            dibuat_event.append((judul, mulai, durasi_menit, warna_id))
            return eid

        def fake_hapus(eid):
            dihapus.append(eid)
            return True

        with patch.object(otak, 'tambah_penanda_deadline', side_effect=fake_penanda), \
             patch.object(otak, 'tambah_event', side_effect=fake_event), \
             patch.object(otak, 'hapus_event', side_effect=fake_hapus):
            r = otak.proses_pesan('/deadline DML 3 jumat 23:59')
            self.assertIn('Tersinkron ke Google Calendar', r)
            self.assertEqual(len(dibuat_penanda), 1)
            self.assertEqual(len(dibuat_event), 1)
            self.assertEqual(dibuat_event[0][2], 30)  # durasi 30 menit sebelum deadline

            # --lokal tidak memanggil kalender
            r_lokal = otak.proses_pesan('/deadline Tugas Lokal besok 18:00 --lokal')
            self.assertNotIn('Tersinkron', r_lokal)
            self.assertEqual(len(dibuat_penanda), 1)

            # /deadline selesai ikut menghapus kedua event di Google Calendar
            r_done = otak.proses_pesan('/deadline selesai DML 3')
            self.assertIn('Penanda di Google Calendar ikut dihapus', r_done)
            self.assertEqual(dihapus, ['penanda-1', 'event-1'])

            # /deadline sinkron menyinkronkan deadline lokal yang tersisa
            r_sync = otak.proses_pesan('/deadline sinkron')
            self.assertIn('1 deadline ditambahkan', r_sync)
            self.assertEqual(len(dibuat_penanda), 2)

    # ------------------------------------------------------------------
    # Area 2: Bahasa Natural Lokal, Scan Struk Foto, & Voice Note
    # ------------------------------------------------------------------

    def test_bahasa_natural_lokal(self):
        # Pengeluaran QRIS
        r1 = otak.proses_pesan('tadi bayar parkir 5rb pakai qris')
        self.assertIn('Dipahami: /qris 5000 parkir', r1)
        self.assertIn('QRIS BNI', r1)

        # Pengeluaran dengan angka kata (seperti hasil voice note) + QRIS Mandiri
        r2 = otak.proses_pesan('beli kopi dua puluh lima ribu qris mandiri')
        self.assertIn('/qris mandiri 25000 kopi', r2)
        self.assertEqual(self.sheet_nov.hitung_rumus()['Mandiri'], 475_000)

        # Pengingat cepat natural
        r3 = otak.proses_pesan('ingetin 45 menit lagi angkat jemuran')
        self.assertIn('Dipahami: /ingatkan 45m angkat jemuran', r3)
        self.assertIn('Pengingat disimpan', r3)

        # Deadline natural
        with patch.object(config, 'DEADLINE_KE_KALENDER', False):
            r4 = otak.proses_pesan('ingetin kumpul tugas DML hari jumat jam 5 sore')
            self.assertIn('Dipahami: /deadline kumpul tugas DML jumat 17:00', r4)
            self.assertIn('Deadline dicatat', r4)

        # Transfer natural
        r5 = otak.proses_pesan('transfer 100rb dari bni ke mandiri')
        self.assertIn('Dipahami: /transfer bni mandiri 100000', r5)

        # Obrolan biasa TIDAK dicatat sebagai transaksi
        r_chat = otak.proses_pesan('halo apa kabar hari ini')
        self.assertIn('Pesan tidak dikenali', r_chat)

    def test_scan_struk_dan_konfirmasi(self):
        fake_struk = {
            'toko': 'Indomaret',
            'tanggal': '2026-11-24',
            'metode': 'tunai',
            'total': 35_500,
            'items': [
                {'nama': 'Sabun Mandi', 'nominal': 27_000, 'kategori': 'Mingguan&Bulanan'},
                {'nama': 'Kopi Kaleng', 'nominal': 8_500, 'kategori': 'Jajan'},
            ],
        }
        with patch.object(otak, 'analisis_struk', return_value=fake_struk):
            res = otak.proses_media('gambar', 'image/jpeg', 'ZmFrZQ==', pengirim='628123')
            self.assertIn('Hasil Scan Struk: Indomaret', res['teks'])
            self.assertIn('Rp35.500', res['teks'])

        # Konfirmasi ubah metode ke QRIS Mandiri
        res_ya = otak.proses_pesan_lengkap('ya qris mandiri', pengirim='628123')
        self.assertIn('Sabun Mandi', res_ya['teks'])
        self.assertIn('Kopi Kaleng', res_ya['teks'])
        self.assertIn('QRIS Mandiri', res_ya['teks'])
        self.assertEqual(self.sheet_nov.hitung_rumus()['Mandiri'], 500_000 - 35_500)

        # Uji opsi "gabung" dan "batal"
        with patch.object(otak, 'analisis_struk', return_value=fake_struk):
            otak.proses_media('gambar', 'image/jpeg', 'ZmFrZQ==', pengirim='628123')
        res_gabung = otak.proses_pesan_lengkap('gabung', pengirim='628123')
        self.assertIn('Indomaret', res_gabung['teks'])
        self.assertIn('Rp35.500', res_gabung['teks'])

        with patch.object(otak, 'analisis_struk', return_value=fake_struk):
            otak.proses_media('gambar', 'image/jpeg', 'ZmFrZQ==', pengirim='628123')
        res_batal = otak.proses_pesan_lengkap('batal', pengirim='628123')
        self.assertIn('Dibatalkan', res_batal['teks'])

    def test_voice_note_baca_dan_tulis(self):
        # Voice note baca (langsung dieksekusi)
        with patch.object(otak, 'transkrip_audio', return_value='cek saldo saya berapa sekarang'):
            res = otak.proses_media('audio', 'audio/ogg', 'ZmFrZQ==', pengirim='628123')
            self.assertIn('Terdengar:', res['teks'])
            self.assertIn('BNI: Rp3.000.000', res['teks'])

        # Voice note tulis (minta konfirmasi ya/batal dulu)
        with patch.object(otak, 'transkrip_audio', return_value='tadi isi bensin dua puluh ribu pakai qris'):
            res = otak.proses_media('audio', 'audio/ogg', 'ZmFrZQ==', pengirim='628123')
            self.assertIn('Akan dijalankan:', res['teks'])
            self.assertIn('/qris 20000 bulanan isi bensin', res['teks'])

        res_ok = otak.proses_pesan_lengkap('ya', pengirim='628123')
        self.assertIn('Mingguan&Bulanan: isi bensin Rp20.000', res_ok['teks'])
        self.assertIn('QRIS BNI', res_ok['teks'])

    def test_gemini_model_default_fallback_404_dan_edge_case(self):
        class RespPalsu:
            def __init__(self, status_code, payload=None, text=''):
                self.status_code = status_code
                self._payload = payload
                self.text = text

            def json(self):
                if isinstance(self._payload, Exception):
                    raise self._payload
                return self._payload

        # 1. Default model adalah gemini-3.5-flash-lite (hemat kuota & minim 503 di free tier)
        self.assertEqual(config.GEMINI_MODEL, 'gemini-3.5-flash-lite')

        # 2. Fallback otomatis 404 saat .env masih pakai gemini-2.5-flash + cache permanen di panggilan ke-2
        panggilan = []

        def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
            panggilan.append((url, headers, json, timeout, kwargs))
            if 'gemini-2.5-flash' in url:
                return RespPalsu(404, {'error': {'message': 'no longer available to new users'}})
            return RespPalsu(200, {
                'candidates': [{
                    'content': {
                        'parts': [
                            {'thought': True, 'text': 'internal thinking...'},
                            {'text': '{"ok": true}'},
                        ]
                    }
                }]
            })

        ai_input._gemini_pengganti.clear()
        with patch.object(config, 'GEMINI_API_KEY', 'test-key-123'), \
             patch.object(config, 'GEMINI_MODEL', 'gemini-2.5-flash'), \
             patch.object(ai_input.requests, 'post', side_effect=fake_post):
            hasil1 = ai_input._panggil_gemini([{'text': 'tes'}], minta_json=True)
            self.assertEqual(hasil1, '{"ok": true}')
            # Panggilan pertama: 404 ke 2.5-flash -> fallback ke 3.5-flash-lite
            self.assertEqual(len(panggilan), 2)
            self.assertIn('/models/gemini-3.5-flash-lite:generateContent', panggilan[1][0])
            # API key dikirim lewat header, bukan query string; tanpa parameter temperature
            self.assertEqual(panggilan[1][1], {'x-goog-api-key': 'test-key-123'})
            self.assertNotIn('params', panggilan[1][4])
            self.assertNotIn('temperature', panggilan[1][2].get('generationConfig', {}))
            self.assertEqual(panggilan[1][2]['generationConfig'], {'responseMimeType': 'application/json'})
            # Timeout percobaan pertama dibatasi separuh budget agar cadangan kebagian waktu
            self.assertLessEqual(panggilan[0][3], 23)

            # Panggilan kedua langsung ke gemini-3.5-flash-lite (cached, tidak 404 lagi)
            hasil2 = ai_input._panggil_gemini([{'text': 'tes2'}], minta_json=False)
            self.assertEqual(hasil2, '{"ok": true}')
            self.assertEqual(len(panggilan), 3)
            self.assertIn('/models/gemini-3.5-flash-lite:generateContent', panggilan[2][0])
            self.assertNotIn('generationConfig', panggilan[2][2])

        # 3. Normalisasi prefix 'models/', '/models/.../', bare 'models/', dan kosong
        ai_input._gemini_pengganti.clear()
        for nilai_env, harapan in (
            ('models/gemini-3.8-flash', 'gemini-3.8-flash'),
            ('/models/gemini-3.5-flash-lite/', 'gemini-3.5-flash-lite'),
            ('models/', 'gemini-3.5-flash-lite'),
            ('   ', 'gemini-3.5-flash-lite'),
        ):
            with patch.object(config, 'GEMINI_MODEL', nilai_env):
                utama, urutan = ai_input._kandidat_model_gemini()
                self.assertEqual(utama, harapan)
                self.assertEqual(urutan[0], harapan)

        # 4. 503 high demand jatuh ke model berikutnya & TIDAK di-cache permanen
        ai_input._gemini_pengganti.clear()
        url_503 = []

        def fake_post_503(url, **kwargs):
            url_503.append(url)
            if 'gemini-3.8-flash' in url:
                return RespPalsu(503, {'error': {'message': 'high demand'}})
            if 'gemini-3.5-flash-lite' in url:
                return RespPalsu(404, {'error': {'message': 'not found'}})
            return RespPalsu(200, {'candidates': [{'content': {'parts': [{'text': 'ok 3.6'}]}}]})

        with patch.object(config, 'GEMINI_API_KEY', 'k'), \
             patch.object(config, 'GEMINI_MODEL', 'gemini-3.8-flash'), \
             patch.object(ai_input.requests, 'post', side_effect=fake_post_503):
            self.assertEqual(ai_input._panggil_gemini([{'text': 'hi'}]), 'ok 3.6')
            self.assertEqual(len(url_503), 3)
            # Karena model utama (3.8-flash) hanya 503 (bukan 404), cache permanen tidak ditulis
            self.assertNotIn('gemini-3.8-flash', ai_input._gemini_pengganti)

        # 5. Semua model kena 503 -> pesan ramah untuk pengguna
        ai_input._gemini_pengganti.clear()
        with patch.object(config, 'GEMINI_API_KEY', 'k'), \
             patch.object(config, 'GEMINI_MODEL', 'gemini-3.5-flash-lite'), \
             patch.object(ai_input.requests, 'post', return_value=RespPalsu(503, {'error': {'message': 'high demand'}})):
            with self.assertRaises(ai_input.InputAIGagal) as ctx:
                ai_input._panggil_gemini([{'text': 'hi'}])
            self.assertIn('sedang sibuk (503)', str(ctx.exception))

        # 6. Error jaringan di model pertama jatuh ke model kedua; 401 tidak fallback
        ai_input._gemini_pengganti.clear()
        percobaan_net = []

        def fake_post_net(url, **kwargs):
            percobaan_net.append(url)
            if len(percobaan_net) == 1:
                raise ai_input.requests.exceptions.RequestException('timeout')
            return RespPalsu(200, {'candidates': [{'content': {'parts': [{'text': 'ok cadangan'}]}}]})

        with patch.object(config, 'GEMINI_API_KEY', 'k'), \
             patch.object(config, 'GEMINI_MODEL', 'gemini-3.5-flash-lite'), \
             patch.object(ai_input.requests, 'post', side_effect=fake_post_net):
            self.assertEqual(ai_input._panggil_gemini([{'text': 'hi'}]), 'ok cadangan')
            self.assertEqual(len(percobaan_net), 2)

        ai_input._gemini_pengganti.clear()
        url_401 = []

        def fake_post_401(url, **kwargs):
            url_401.append(url)
            return RespPalsu(401, {'error': {'message': 'API key invalid'}})

        with patch.object(config, 'GEMINI_API_KEY', 'k'), \
             patch.object(config, 'GEMINI_MODEL', 'gemini-3.5-flash-lite'), \
             patch.object(ai_input.requests, 'post', side_effect=fake_post_401):
            with self.assertRaises(ai_input.InputAIGagal) as ctx:
                ai_input._panggil_gemini([{'text': 'hi'}])
            self.assertIn('401', str(ctx.exception))
            self.assertEqual(len(url_401), 1)

        # 7. Respons HTTP 200 bukan JSON atau hanya berisi thought part -> InputAIGagal
        with patch.object(config, 'GEMINI_API_KEY', 'k'), \
             patch.object(config, 'GEMINI_MODEL', 'gemini-3.5-flash-lite'), \
             patch.object(ai_input.requests, 'post',
                          return_value=RespPalsu(200, ValueError('invalid json'), text='<html></html>')):
            with self.assertRaises(ai_input.InputAIGagal):
                ai_input._panggil_gemini([{'text': 'hi'}])

        with patch.object(config, 'GEMINI_API_KEY', 'k'), \
             patch.object(config, 'GEMINI_MODEL', 'gemini-3.5-flash-lite'), \
             patch.object(ai_input.requests, 'post',
                          return_value=RespPalsu(200, {'candidates': [{'content': {'parts': [{'thought': True, 'text': 'hmm'}]}}]})):
            with self.assertRaises(ai_input.InputAIGagal):
                ai_input._panggil_gemini([{'text': 'hi'}])


if __name__ == '__main__':
    unittest.main(verbosity=2)
