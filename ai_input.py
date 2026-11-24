"""Input cerdas untuk Bot WA:
1. Parser bahasa natural lokal (Bahasa Indonesia, tanpa butuh API key).
2. Scan struk belanja dari foto (Gemini Vision / OpenAI Vision).
3. Transkripsi voice note / audio (Gemini Audio / OpenAI Whisper).
4. Fallback pemahaman bahasa natural via LLM (Gemini / OpenAI).

Semua panggilan HTTP memakai `requests` standar tanpa SDK tambahan.
"""
import base64
import json
import re
from datetime import date

try:
    import requests
except ImportError:
    requests = None

import config

KATEGORI_VALID = ('Jajan', 'Alat', 'Mingguan&Bulanan', 'Hiburan')
KATEGORI_KE_ALIAS = {
    'Jajan': 'jajan',
    'Alat': 'alat',
    'Mingguan&Bulanan': 'bulanan',
    'Hiburan': 'hiburan',
}

# Kata bantu untuk mengubah angka terucap Bahasa Indonesia (sering muncul di voice note)
_SATUAN_ID = {
    'nol': 0, 'satu': 1, 'se': 1, 'dua': 2, 'tiga': 3, 'empat': 4,
    'lima': 5, 'enam': 6, 'tujuh': 7, 'delapan': 8, 'sembilan': 9,
    'sepuluh': 10, 'sebelas': 11,
}

_KATA_PENGELUARAN = (
    'beli', 'bayar', 'jajan', 'makan', 'minum', 'isi', 'pesan', 'pesen',
    'ongkir', 'parkir', 'habis', 'keluar', 'ngopi', 'nonton', 'cukur',
    'laundry', 'londri', 'bensin', 'belanja', 'order', 'grab', 'gojek',
    'gofood', 'shopeefood', 'grabfood',
)

_PETA_KATEGORI_KATA = {
    'Alat': (
        'alat', 'buku', 'kabel', 'charger', 'obat', 'masker', 'handuk',
        'hanger', 'sarung tangan', 'baju', 'celana', 'sepatu', 'headset',
        'mouse', 'keyboard', 'gunting', 'pulpen', 'pensil', 'botol',
    ),
    'Mingguan&Bulanan': (
        'mingguan', 'bulanan', 'galon', 'laundry', 'londri', 'listrik',
        'token', 'pulsa', 'kuota', 'wifi', 'kos', 'kost', 'sabun', 'shampo',
        'sampo', 'odol', 'cukur', 'bensin', 'pertalite', 'pertamax', 'beras',
        'telur', 'gas', 'deterjen', 'tisu', 'biaya kartu', 'admin',
    ),
    'Hiburan': (
        'hiburan', 'bioskop', 'nonton', 'billiard', 'biliard', 'arcade',
        'game', 'karaoke', 'konser', 'bowling', 'netflix', 'spotify',
        'steam', 'ps', 'rental',
    ),
}

_KATA_BUANG_NAMA = {
    'tadi', 'barusan', 'baru', 'saja', 'aja', 'aku', 'saya', 'gw', 'gue',
    'udah', 'sudah', 'abis', 'habis', 'keluar', 'uang', 'duit', 'beli',
    'bayar', 'belanja', 'pakai', 'pake', 'via', 'lewat', 'dengan', 'sama',
    'buat', 'untuk', 'ke', 'di', 'sebesar', 'senilai', 'total', 'totalnya',
    'harganya', 'harga', 'seharga', 'rp', 'rupiah', 'qris', 'bni', 'mandiri',
    'tunai', 'cash', 'kemarin', 'hariini', 'jajan', 'alat', 'mingguan',
    'bulanan', 'hiburan', 'dong', 'nih', 'ya', 'yah', 'sih', 'terus',
}


class InputAIGagal(Exception):
    """Panggilan ke layanan AI (scan struk / voice note / LLM) gagal."""


def ai_tersedia():
    """True jika AI diaktifkan dan minimal satu API key (Gemini atau OpenAI) terisi."""
    if not config.AI_AKTIF:
        return False
    return bool(config.GEMINI_API_KEY or config.OPENAI_API_KEY)


def nama_provider_ai():
    if not config.AI_AKTIF:
        return None
    if config.GEMINI_API_KEY:
        return 'gemini'
    if config.OPENAI_API_KEY:
        return 'openai'
    return None


# ---------------------------------------------------------------------------
# Utilitas parsing angka & waktu Bahasa Indonesia
# ---------------------------------------------------------------------------

def _ubah_kata_angka_id(teks):
    """Ubah frasa angka terucap Bahasa Indonesia menjadi angka bulat, misalnya:
    'dua puluh lima ribu' -> '25000', 'seratus ribu' -> '100000', 'setengah juta' -> '500000'."""
    hasil = re.sub(r'\bsetengah\s+juta\b', '500000', teks, flags=re.IGNORECASE)
    hasil = re.sub(r'\bsejuta\b', '1000000', hasil, flags=re.IGNORECASE)
    hasil = re.sub(r'\bseratus\s+(ribu|rebu)\b', '100000', hasil, flags=re.IGNORECASE)
    hasil = re.sub(r'\bseribu\b', '1000', hasil, flags=re.IGNORECASE)

    # Pola "<angka_kata> ribu/rebu/juta"
    kata_bil = (
        r'(?:seratus|sebelas|sepuluh|satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|'
        r'belas|puluh|ratus|setengah|koma)'
    )
    pola = re.compile(
        rf'\b((?:{kata_bil}\s+)+)(ribu|rebu|juta)\b',
        re.IGNORECASE,
    )

    def ganti(m):
        bagian = m.group(1).lower().split()
        satuan = m.group(2).lower()
        pengali = 1_000_000 if satuan == 'juta' else 1_000
        nilai = _hitung_frasa_bilangan(bagian)
        if nilai is None or nilai <= 0:
            return m.group(0)
        return str(int(round(nilai * pengali)))

    hasil = pola.sub(ganti, hasil)
    # Bentuk "<angka> ribu" / "<angka> juta", misal "20 ribu", "1,5 juta"
    hasil = re.sub(
        r'\b(\d+(?:[.,]\d+)?)\s*(ribu|rebu)\b',
        lambda m: str(int(round(float(m.group(1).replace(',', '.')) * 1000))),
        hasil, flags=re.IGNORECASE,
    )
    hasil = re.sub(
        r'\b(\d+(?:[.,]\d+)?)\s*juta\b',
        lambda m: str(int(round(float(m.group(1).replace(',', '.')) * 1_000_000))),
        hasil, flags=re.IGNORECASE,
    )
    return hasil


def _hitung_frasa_bilangan(kata_list):
    """['dua', 'puluh', 'lima'] -> 25; ['seratus', 'lima', 'puluh'] -> 150."""
    total = 0
    sementara = 0
    ada = False
    i = 0
    while i < len(kata_list):
        w = kata_list[i]
        if w == 'seratus':
            sementara += 100
            ada = True
        elif w == 'setengah':
            sementara += 0.5
            ada = True
        elif w in _SATUAN_ID:
            angka = _SATUAN_ID[w]
            if i + 1 < len(kata_list) and kata_list[i + 1] == 'belas':
                sementara += 10 + angka
                i += 1
            elif i + 1 < len(kata_list) and kata_list[i + 1] == 'puluh':
                sementara += angka * 10
                i += 1
            elif i + 1 < len(kata_list) and kata_list[i + 1] == 'ratus':
                sementara += angka * 100
                i += 1
            else:
                sementara += angka
            ada = True
        elif w in ('koma',):
            if i + 1 < len(kata_list) and kata_list[i + 1] in _SATUAN_ID:
                sementara += _SATUAN_ID[kata_list[i + 1]] / 10.0
                i += 1
                ada = True
            else:
                return None
        else:
            return None
        i += 1
    total += sementara
    return total if ada else None


def _ekstrak_nominal_token(teks):
    """Cari token nominal pertama di `teks`, kembalikan (nilai_int, span_mulai, span_akhir) atau None."""
    pola = re.compile(
        r'(?:rp\.?\s*)?(\d{1,3}(?:\.\d{3})+|\d+(?:[.,]\d+)?)\s*(jt|rb|k)?\b',
        re.IGNORECASE,
    )
    for m in pola.finditer(teks):
        # Hindari mencocokkan tanggal DD/MM atau jam HH:MM
        awal, akhir = m.span()
        if awal > 0 and teks[awal - 1] in '/:':
            continue
        if akhir < len(teks) and teks[akhir] in '/:':
            continue
        angka_str = m.group(1)
        sufiks = (m.group(2) or '').lower()
        try:
            if sufiks in ('rb', 'k'):
                nilai = int(round(float(angka_str.replace('.', '').replace(',', '.')) * 1_000))
            elif sufiks == 'jt':
                nilai = int(round(float(angka_str.replace('.', '').replace(',', '.')) * 1_000_000))
            else:
                if ',' in angka_str:
                    continue
                bersih = angka_str.replace('.', '')
                nilai = int(bersih)
                # Angka kecil tanpa satuan (< 500) biasanya jumlah/jam, bukan nominal rupiah
                if nilai < 500:
                    continue
        except ValueError:
            continue
        if nilai > 0:
            return nilai, awal, akhir
    return None


def _ubah_jam_id(jam, menit, waktu_hari):
    waktu_hari = (waktu_hari or '').lower()
    if waktu_hari in ('sore', 'malam', 'mlm', 'petang') and 1 <= jam <= 11:
        jam += 12
    elif waktu_hari == 'siang' and 1 <= jam <= 5:
        jam += 12
    elif waktu_hari == 'pagi' and jam == 12:
        jam = 0
    if 0 <= jam <= 23 and 0 <= menit <= 59:
        return f'{jam:02d}:{menit:02d}'
    return None


def _deteksi_kategori(teks_lower):
    for kat, daftar_kata in _PETA_KATEGORI_KATA.items():
        for kata in daftar_kata:
            if re.search(rf'\b{re.escape(kata)}\b', teks_lower):
                return KATEGORI_KE_ALIAS[kat]
    return None


def _bersihkan_nama_barang(teks):
    kata = re.findall(r"[a-zA-Z0-9&'+/-]+", teks)
    hasil = []
    for w in kata:
        wl = w.lower()
        if wl in _KATA_BUANG_NAMA:
            continue
        if re.fullmatch(r'\d{1,2}/\d{1,2}', wl):
            continue
        hasil.append(w)
    return ' '.join(hasil).strip()


# ---------------------------------------------------------------------------
# Parser Bahasa Natural Lokal (tanpa API key)
# ---------------------------------------------------------------------------

def parse_bahasa_natural_lokal(teks, pintasan=None):
    """Terjemahkan kalimat santai Bahasa Indonesia menjadi perintah bot (str),
    atau None jika tidak yakin (bisa dilanjutkan ke LLM atau pesan tidak dikenal).

    Hanya mengubah pola yang jelas agar obrolan acak tidak salah dicatat."""
    asli = teks.strip()
    if not asli or asli.startswith('/'):
        return None
    norm = _ubah_kata_angka_id(asli)
    low = norm.lower().strip()

    # 1. Pertanyaan / perintah baca (read-only)
    if re.search(r'\b(cek|lihat|berapa|info|tampilkan)?\s*(saldo|sisa uang|sisa duit|total saldo)\b', low):
        if not _ekstrak_nominal_token(norm):
            return '/saldo'
    if re.search(r'\b(grafik|chart|diagram)\b', low):
        if re.search(r'\b(minggu|mingguan|7\s*hari|pekan)\b', low):
            return '/grafik mingguan'
        return '/grafik'
    if re.search(r'\b(pengeluaran|habis|keluar|jajan).*(hari ini|hariini)\b|\b(hari ini|hariini).*(habis|keluar|pengeluaran)\b', low):
        if not _ekstrak_nominal_token(norm):
            return '/hariini'
    if re.search(r'\b(rekap|laporan|ringkasan)\b.*\b(bulan|bulanan|pengeluaran)\b', low):
        return '/rekap'
    if re.search(r'\b(daftar|lihat|cek|apa aja)\b.*\b(deadline|tenggat)\b', low):
        return '/deadline'
    if re.search(r'\b(daftar|lihat|cek)\b.*\b(tagihan|rutin)\b', low):
        return '/tagihan'
    if re.search(r'\b(daftar|lihat|cek)\b.*\b(pengingat|reminder)\b', low):
        return '/ingatkan'
    if re.search(r'\b(lihat|cek)\s+riwayat\b', low):
        return '/riwayat'

    # 2. Pengingat cepat & deadline dari kalimat natural
    cocok_ingat = re.match(
        r'^(?:tolong\s+)?(?:ingetin|ingatkan|remind(?:\s+me)?)(?:\s+(?:aku|saya|gue|gw))?\s+(.+)$',
        norm, flags=re.IGNORECASE,
    )
    if cocok_ingat:
        isi = cocok_ingat.group(1).strip()
        # 2a. Durasi relatif: "30 menit lagi angkat jemuran" atau "1 jam 30 menit lagi matikan kompor"
        m_rel = re.search(
            r'\b(?:(\d+)\s*(?:jam|j)\s*(?:(\d+)\s*(?:menit|mnt|m))?|(\d+)\s*(?:menit|mnt|m))\s*(?:lagi|dari sekarang)?\b',
            isi, flags=re.IGNORECASE,
        )
        if m_rel and not re.search(r'\bjam\s+\d', isi, flags=re.IGNORECASE):
            if m_rel.group(1) and m_rel.group(2):
                kode = f'{int(m_rel.group(1))}j{int(m_rel.group(2))}m'
            elif m_rel.group(1):
                kode = f'{int(m_rel.group(1))}j'
            else:
                kode = f'{int(m_rel.group(3))}m'
            pesan = (isi[:m_rel.start()] + ' ' + isi[m_rel.end():]).strip(' ,.-')
            pesan = re.sub(r'^(untuk|buat|kalau|kalo)\s+', '', pesan, flags=re.IGNORECASE).strip()
            pesan = re.sub(r'\s+(untuk|buat|dalam)$', '', pesan, flags=re.IGNORECASE).strip()
            if pesan:
                return f'/ingatkan {kode} {pesan}'

        # 2b. Tanggal/hari + jam: "kumpul tugas DML jumat jam 5 sore" atau "besok jam 09:00 bayar kos"
        m_hari = re.search(
            r'\b(hari\s*ini|hariini|besok|lusa|senin|selasa|rabu|kamis|jumat|jum\'at|sabtu|minggu|ahad|\d{1,2}/\d{1,2})\b',
            isi, flags=re.IGNORECASE,
        )
        m_jam = re.search(
            r'\b(?:jam|pukul)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(pagi|siang|sore|malam|mlm|petang)?\b',
            isi, flags=re.IGNORECASE,
        )
        if not m_jam:
            m_jam = re.search(
                r'\b(\d{1,2})[:.](\d{2})\s*(pagi|siang|sore|malam|mlm|petang)?\b',
                isi, flags=re.IGNORECASE,
            )
        if m_jam:
            jam_int = int(m_jam.group(1))
            menit_int = int(m_jam.group(2) or 0)
            jam_str = _ubah_jam_id(jam_int, menit_int, m_jam.group(3))
            if jam_str:
                # Hapus potongan hari & jam untuk mendapatkan judul/pesan
                potongan = sorted(
                    [m.span() for m in (m_hari, m_jam) if m is not None],
                    reverse=True,
                )
                sisa_teks = isi
                for a, b in potongan:
                    sisa_teks = sisa_teks[:a] + ' ' + sisa_teks[b:]
                sisa_teks = re.sub(r'\s+', ' ', sisa_teks).strip(' ,.-')
                sisa_teks = re.sub(r'^(untuk|buat|hari|pada|di|jam)\s+', '', sisa_teks, flags=re.IGNORECASE).strip()
                sisa_teks = re.sub(r'\s+(hari|pada|di|jam|pukul)$', '', sisa_teks, flags=re.IGNORECASE).strip()
                if sisa_teks:
                    hari_token = None
                    if m_hari:
                        hari_token = m_hari.group(1).lower().replace(' ', '')
                    if hari_token and re.search(r'\b(deadline|tugas|kumpul|submit|presentasi|ujian|kuis|laporan)\b', low):
                        return f'/deadline {sisa_teks} {hari_token} {jam_str}'
                    if hari_token:
                        return f'/ingatkan {hari_token} {jam_str} {sisa_teks}'
                    return f'/ingatkan {jam_str} {sisa_teks}'

    # 3. Transfer / Tarik / Setor
    nom = _ekstrak_nominal_token(norm)
    if nom:
        nilai, n_awal, n_akhir = nom

        # 3a. Transfer antar dompet: "transfer 200rb dari bni ke mandiri"
        if re.search(r'\b(transfer|tf|pindahin|pindah|kirim)\b', low):
            m_arah = re.search(
                r'\b(?:dari\s+)?(bni|mandiri|tunai|cash|dompet)\s+(?:ke|->|→)\s+(bni|mandiri|tunai|cash|dompet)\b',
                low,
            )
            if m_arah:
                return f'/transfer {m_arah.group(1)} {m_arah.group(2)} {nilai}'

        # 3b. Setor tunai: "setor tunai 300rb ke bni"
        if re.search(r'\bsetor\b', low):
            m_bank = re.search(r'\b(bni|mandiri)\b', low)
            if m_bank:
                return f'/transfer tunai {m_bank.group(1)} {nilai}'

        # 3c. Tarik tunai: "tarik tunai 250rb" / "ambil uang mandiri 200rb"
        if re.search(r'\b(tarik|narik|ambil\s+(?:uang|duit|tunai|cash)|atm)\b', low):
            m_bank = re.search(r'\b(bni|mandiri)\b', low)
            bank = m_bank.group(1) if m_bank else 'bni'
            return f'/tarik {bank} {nilai}'

        # 3d. Pemasukan umum / bank: "dapat uang saku 500rb", "gaji masuk bni 3jt"
        if re.search(r'\b(dapat|dapet|terima|diterima|masuk|gaji|uang\s+saku|cashback|refund|beasiswa|bonus|pemasukan)\b', low):
            m_bank = re.search(r'\b(bni|mandiri)\b', low)
            tgl_str = 'kemarin ' if re.search(r'\bkemarin\b', low) else ''
            tanpa_nom = norm[:n_awal] + ' ' + norm[n_akhir:]
            ket = _bersihkan_nama_barang(re.sub(
                r'\b(dapat|dapet|terima|diterima|masuk|pemasukan|dari|ke|rekening|bank)\b',
                ' ', tanpa_nom, flags=re.IGNORECASE,
            ))
            if m_bank:
                bank = m_bank.group(1)
                return f'/in {tgl_str}{bank} {nilai}' + (f' {ket}' if ket else '')
            return f'/in {tgl_str}{nilai} ' + (ket or 'Pemasukan')

        # 4. Pengeluaran santai: "tadi bayar parkir 5rb pakai qris", "beli kopi 22rb qris mandiri"
        ada_petunjuk = (
            any(re.search(rf'\b{re.escape(k)}\b', low) for k in _KATA_PENGELUARAN)
            or bool(re.search(r'\bqris\b', low))
            or bool(pintasan and any(re.search(rf'\b{re.escape(p)}\b', low) for p in pintasan))
        )
        if ada_petunjuk:
            lewat_qris = bool(re.search(r'\bqris\b', low))
            bank_qris = 'mandiri' if (lewat_qris and re.search(r'\bmandiri\b', low)) else ''
            m_tgl = re.search(r'\b(\d{1,2}/\d{1,2})\b', low)
            if re.search(r'\bkemarin\b', low):
                tgl_token = 'kemarin'
            elif m_tgl:
                tgl_token = m_tgl.group(1)
            else:
                tgl_token = ''

            tanpa_nom = norm[:n_awal] + ' ' + norm[n_akhir:]
            nama_barang = _bersihkan_nama_barang(tanpa_nom)
            # Jika nama barang kosong (misal: "tadi ngopi 20rb"), pakai kata kerja spesifiknya
            if not nama_barang:
                for kata_spesifik in ('parkir', 'ngopi', 'bensin', 'laundry', 'londri', 'cukur', 'nonton', 'ongkir', 'makan', 'minum'):
                    if re.search(rf'\b{kata_spesifik}\b', low):
                        nama_barang = kata_spesifik
                        break
            if nama_barang:
                kat_alias = _deteksi_kategori(low)
                bagian_cmd = ['/qris' if lewat_qris else '/out']
                if bank_qris:
                    bagian_cmd.append(bank_qris)
                if tgl_token:
                    bagian_cmd.append(tgl_token)
                bagian_cmd.append(str(nilai))
                if kat_alias:
                    bagian_cmd.append(kat_alias)
                bagian_cmd.append(nama_barang)
                return ' '.join(bagian_cmd)

    return None


# ---------------------------------------------------------------------------
# Klien REST Gemini & OpenAI (tanpa SDK tambahan)
# ---------------------------------------------------------------------------

def _ekstrak_json(teks):
    """Ambil objek JSON dari jawaban LLM (walau dibungkus ```json ... ```)."""
    teks = (teks or '').strip()
    m = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', teks, flags=re.DOTALL)
    if m:
        teks = m.group(1)
    else:
        awal_obj = teks.find('{')
        akhir_obj = teks.rfind('}')
        if awal_obj != -1 and akhir_obj > awal_obj:
            teks = teks[awal_obj:akhir_obj + 1]
    return json.loads(teks)


_GEMINI_MODEL_CADANGAN = ('gemini-3.8-flash', 'gemini-3.5-flash-lite')
_gemini_pengganti = {}   # model_lama -> model_aktif hasil fallback 404


def _kandidat_model_gemini():
    utama = (
        (config.GEMINI_MODEL or '').strip().lstrip('/').removeprefix('models/').strip('/')
        or _GEMINI_MODEL_CADANGAN[0]
    )
    awal = _gemini_pengganti.get(utama, utama)
    urutan = [awal]
    for cadangan in _GEMINI_MODEL_CADANGAN:
        if cadangan not in urutan:
            urutan.append(cadangan)
    return utama, urutan


def _panggil_gemini(parts, minta_json=False, timeout=45):
    if requests is None:
        raise InputAIGagal('Library requests belum terpasang.')
    if not config.GEMINI_API_KEY:
        raise InputAIGagal('GEMINI_API_KEY belum diisi di .env')

    # Gemini 3.x/3.8 menghapus parameter sampling (temperature/top_p/top_k).
    body = {'contents': [{'parts': parts}]}
    if minta_json:
        body['generationConfig'] = {'responseMimeType': 'application/json'}
    headers = {'x-goog-api-key': config.GEMINI_API_KEY}

    model_asal, kandidat = _kandidat_model_gemini()
    r = None
    for idx, model in enumerate(kandidat):
        url = (f'https://generativelanguage.googleapis.com/v1beta/models/'
               f'{model}:generateContent')
        try:
            r = requests.post(url, headers=headers, json=body, timeout=timeout)
        except requests.exceptions.RequestException as e:
            raise InputAIGagal(f'Gagal menghubungi Gemini API ({type(e).__name__})') from e
        if r.status_code == 404 and idx + 1 < len(kandidat):
            print(f'[ai] Model {model} tidak tersedia (404), mencoba {kandidat[idx + 1]}')
            continue
        if r.status_code == 200 and model != model_asal:
            _gemini_pengganti[model_asal] = model
        break

    if r.status_code != 200:
        detail = ''
        try:
            detail = r.json().get('error', {}).get('message', '')
        except ValueError:
            detail = r.text[:160]
        raise InputAIGagal(f'Gemini API error {r.status_code}: {detail}')

    try:
        data = r.json()
        bagian = data['candidates'][0]['content']['parts']
        teks = ''.join(p.get('text', '') for p in bagian if not p.get('thought')).strip()
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise InputAIGagal('Jawaban Gemini kosong atau tidak dikenali.') from e
    if not teks:
        raise InputAIGagal('Jawaban Gemini kosong atau tidak dikenali.')
    return teks


def _panggil_openai_chat(messages, minta_json=False, timeout=45):
    if requests is None:
        raise InputAIGagal('Library requests belum terpasang.')
    if not config.OPENAI_API_KEY:
        raise InputAIGagal('OPENAI_API_KEY belum diisi di .env')
    body = {
        'model': config.OPENAI_MODEL,
        'messages': messages,
        'temperature': 0.1,
    }
    if minta_json:
        body['response_format'] = {'type': 'json_object'}
    try:
        r = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers={'Authorization': f'Bearer {config.OPENAI_API_KEY}'},
            json=body, timeout=timeout,
        )
    except requests.exceptions.RequestException as e:
        raise InputAIGagal(f'Gagal menghubungi OpenAI API ({type(e).__name__})') from e
    if r.status_code != 200:
        detail = ''
        try:
            detail = r.json().get('error', {}).get('message', '')
        except ValueError:
            detail = r.text[:160]
        raise InputAIGagal(f'OpenAI API error {r.status_code}: {detail}')
    data = r.json()
    try:
        return data['choices'][0]['message']['content'].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise InputAIGagal('Jawaban OpenAI kosong atau tidak dikenali.') from e


def _panggil_openai_whisper(audio_base64, mime_type, timeout=45):
    if requests is None:
        raise InputAIGagal('Library requests belum terpasang.')
    if not config.OPENAI_API_KEY:
        raise InputAIGagal('OPENAI_API_KEY belum diisi di .env')
    ext = 'ogg'
    if 'mp4' in (mime_type or '') or 'm4a' in (mime_type or ''):
        ext = 'm4a'
    elif 'mpeg' in (mime_type or '') or 'mp3' in (mime_type or ''):
        ext = 'mp3'
    elif 'wav' in (mime_type or ''):
        ext = 'wav'
    raw = base64.b64decode(audio_base64)
    try:
        r = requests.post(
            'https://api.openai.com/v1/audio/transcriptions',
            headers={'Authorization': f'Bearer {config.OPENAI_API_KEY}'},
            files={'file': (f'voice.{ext}', raw, mime_type or 'audio/ogg')},
            data={'model': 'whisper-1', 'language': 'id'},
            timeout=timeout,
        )
    except requests.exceptions.RequestException as e:
        raise InputAIGagal(f'Gagal menghubungi OpenAI Whisper ({type(e).__name__})') from e
    if r.status_code != 200:
        raise InputAIGagal(f'Whisper API error {r.status_code}: {r.text[:160]}')
    return r.json().get('text', '').strip()


# ---------------------------------------------------------------------------
# 1. Scan Struk Belanja (Foto)
# ---------------------------------------------------------------------------

def _normalisasi_hasil_struk(data, caption=''):
    if not isinstance(data, dict):
        raise InputAIGagal('Hasil baca struk tidak valid.')
    toko = str(data.get('toko') or 'Belanja').strip()[:60]
    tgl = data.get('tanggal')
    if tgl and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(tgl).strip()):
        tgl = None
    else:
        tgl = str(tgl).strip() if tgl else None

    metode = str(data.get('metode') or 'tunai').strip().lower()
    cap_low = (caption or '').lower()
    if 'qris' in cap_low and 'mandiri' in cap_low:
        metode = 'qris_mandiri'
    elif 'qris' in cap_low:
        metode = 'qris_bni'
    elif metode not in ('tunai', 'qris_bni', 'qris_mandiri'):
        metode = 'qris_bni' if 'qris' in metode else 'tunai'

    # Override kategori jika pengguna menyebutkannya di caption
    kat_caption = None
    for alias, nama_kat in (
        ('jajan', 'Jajan'), ('alat', 'Alat'),
        ('mingguan', 'Mingguan&Bulanan'), ('bulanan', 'Mingguan&Bulanan'),
        ('hiburan', 'Hiburan'),
    ):
        if re.search(rf'\b{alias}\b', cap_low):
            kat_caption = nama_kat
            break

    items_mentah = data.get('items') or []
    items = []
    for item in items_mentah[:10]:
        if not isinstance(item, dict):
            continue
        nama = str(item.get('nama') or '').strip()[:60]
        try:
            nominal = int(round(float(item.get('nominal', 0))))
        except (TypeError, ValueError):
            continue
        if not nama or nominal <= 0:
            continue
        kat = kat_caption or str(item.get('kategori') or 'Jajan').strip()
        if kat not in KATEGORI_VALID:
            kat = 'Jajan'
        items.append({'nama': nama, 'nominal': nominal, 'kategori': kat})

    try:
        total = int(round(float(data.get('total') or 0)))
    except (TypeError, ValueError):
        total = 0

    if not items and total > 0:
        kat_utama = kat_caption or str(data.get('kategori') or 'Jajan').strip()
        if kat_utama not in KATEGORI_VALID:
            kat_utama = 'Jajan'
        items = [{'nama': toko, 'nominal': total, 'kategori': kat_utama}]
    elif total <= 0:
        total = sum(i['nominal'] for i in items)

    if not items or total <= 0:
        raise InputAIGagal('Tidak ada nominal belanja yang terbaca dari foto ini.')

    return {
        'toko': toko,
        'tanggal': tgl,
        'metode': metode,
        'items': items,
        'total': total,
    }


def analisis_struk(gambar_base64, mime_type='image/jpeg', caption=''):
    """Ekstrak detail belanja dari foto struk menggunakan Gemini Vision atau OpenAI Vision."""
    provider = nama_provider_ai()
    if not provider:
        raise InputAIGagal(
            'Fitur scan struk membutuhkan GEMINI_API_KEY (atau OPENAI_API_KEY) di file .env.'
        )

    prompt = (
        'Kamu adalah parser struk belanja Indonesia untuk pencatat keuangan pribadi.\n'
        'Baca foto struk ini lalu kembalikan JSON SAJA dengan struktur persis:\n'
        '{\n'
        '  "toko": "nama toko singkat",\n'
        '  "tanggal": "YYYY-MM-DD atau null jika tidak terbaca",\n'
        '  "metode": "tunai" | "qris_bni" | "qris_mandiri",\n'
        '  "total": 35000,\n'
        '  "items": [\n'
        '    {"nama": "nama barang singkat", "nominal": 15000, "kategori": "Jajan"}\n'
        '  ]\n'
        '}\n'
        'Aturan penting:\n'
        '- Kategori HARUS salah satu dari: "Jajan", "Alat", "Mingguan&Bulanan", "Hiburan".\n'
        '  (Makanan/minuman/kopi -> "Jajan"; sabun/galon/laundry/listrik/pulsa/kebutuhan harian -> '
        '"Mingguan&Bulanan"; barang/elektronik/buku/obat -> "Alat"; bioskop/game/hiburan -> "Hiburan").\n'
        '- Nominal berupa angka bulat Rupiah (tanpa titik/Rp), sudah termasuk diskon/pajak bila relevan.\n'
        '- Jika item terlalu banyak (>6), kelompokkan item sejenis agar ringkas dan jumlahnya sesuai total.\n'
        '- Jika pembayaran di struk tampak memakai QRIS/debit BNI -> "qris_bni", QRIS Mandiri -> "qris_mandiri", selain itu -> "tunai".\n'
        '- Jika foto BUKAN struk/bukti bayar, kembalikan {"toko": "", "total": 0, "items": []}.'
    )
    if caption and caption.strip():
        prompt += f'\nCatatan tambahan pengguna: "{caption.strip()}"'

    if provider == 'gemini':
        mime_bersih = (mime_type or 'image/jpeg').split(';')[0].strip()
        teks_hasil = _panggil_gemini([
            {'text': prompt},
            {'inline_data': {'mime_type': mime_bersih, 'data': gambar_base64}},
        ], minta_json=True)
    else:
        mime_bersih = (mime_type or 'image/jpeg').split(';')[0].strip()
        teks_hasil = _panggil_openai_chat([
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompt},
                    {'type': 'image_url', 'image_url': {'url': f'data:{mime_bersih};base64,{gambar_base64}'}},
                ],
            }
        ], minta_json=True)

    try:
        data = _ekstrak_json(teks_hasil)
    except ValueError as e:
        raise InputAIGagal('Gagal membaca format JSON hasil scan struk.') from e
    return _normalisasi_hasil_struk(data, caption=caption)


# ---------------------------------------------------------------------------
# 2. Voice Note (Speech-to-Text)
# ---------------------------------------------------------------------------

def transkrip_audio(audio_base64, mime_type='audio/ogg'):
    """Ubah rekaman voice note menjadi teks Bahasa Indonesia."""
    provider = nama_provider_ai()
    if not provider:
        raise InputAIGagal(
            'Fitur voice note membutuhkan GEMINI_API_KEY (atau OPENAI_API_KEY) di file .env.'
        )

    if provider == 'gemini':
        mime_bersih = (mime_type or 'audio/ogg').split(';')[0].strip()
        prompt = (
            'Transkripsikan rekaman suara berbahasa Indonesia ini secara akurat menjadi satu '
            'kalimat teks biasa. Tulis nominal uang dalam angka (misalnya 20000 atau 20rb) '
            'jika disebutkan. Kembalikan teks transkrip saja tanpa penjelasan atau tanda kutip.'
        )
        teks = _panggil_gemini([
            {'text': prompt},
            {'inline_data': {'mime_type': mime_bersih, 'data': audio_base64}},
        ], minta_json=False)
    else:
        teks = _panggil_openai_whisper(audio_base64, mime_type)

    teks = (teks or '').strip().strip('"').strip("'")
    if not teks:
        raise InputAIGagal('Suara tidak terdengar jelas atau kosong.')
    return teks


# ---------------------------------------------------------------------------
# 3. Pemahaman Bahasa Natural via LLM (Fallback)
# ---------------------------------------------------------------------------

def parse_bahasa_natural_ai(teks, pintasan=None, tanggal_hari_ini=None):
    """Panggil LLM untuk menerjemahkan pesan santai Bahasa Indonesia menjadi perintah bot.
    Mengembalikan dict {'perintah': ['/out ...'], 'penjelasan': '...'} atau None jika bukan perintah."""
    provider = nama_provider_ai()
    if not provider:
        return None

    tgl_str = (tanggal_hari_ini or date.today()).isoformat()
    daftar_pintasan = ', '.join(sorted(pintasan.keys())) if pintasan else '-'
    prompt = (
        f'Kamu penerjemah perintah untuk bot WhatsApp keuangan & produktivitas pribadi. '
        f'Tanggal hari ini: {tgl_str}.\n'
        f'Pintasan tersedia: {daftar_pintasan}.\n\n'
        'Perintah valid yang tersedia:\n'
        '- /out [kemarin|DD/MM] <nominal> [jajan|alat|bulanan|hiburan] <nama barang>\n'
        '- /qris [mandiri] [kemarin|DD/MM] <nominal> [jajan|alat|bulanan|hiburan] <nama barang>\n'
        '- /in [kemarin|DD/MM] <nominal> <sumber tunai>  ATAU  /in [kemarin|DD/MM] <bni|mandiri> <nominal> [keterangan]\n'
        '- /tarik [bni|mandiri] <nominal>\n'
        '- /transfer <bni|mandiri|tunai> <bni|mandiri|tunai> <nominal>\n'
        '- /saldo\n'
        '- /rekap\n'
        '- /hariini\n'
        '- /grafik [mingguan]\n'
        '- /cari_transaksi <kata kunci>\n'
        '- /ingatkan <30m|2j|HH:MM|besok HH:MM|nama_hari HH:MM> <pesan>\n'
        '- /deadline <judul> <hariini|besok|lusa|nama_hari|DD/MM> <HH:MM>\n'
        '- /tagihan\n'
        '- /catat <isi catatan>\n'
        '- /cari <kata kunci catatan>\n\n'
        'Ubah pesan pengguna berikut menjadi JSON SAJA:\n'
        '{"cocok": true, "perintah": ["/qris 5000 parkir"], "ringkas": "Pengeluaran QRIS BNI Rp5.000 parkir"}\n'
        'Jika pesan HANYA obrolan biasa/sapaan dan tidak meminta aksi bot, kembalikan:\n'
        '{"cocok": false, "perintah": [], "ringkas": ""}\n\n'
        f'Pesan pengguna: "{teks}"'
    )

    try:
        if provider == 'gemini':
            jawaban = _panggil_gemini([{'text': prompt}], minta_json=True, timeout=30)
        else:
            jawaban = _panggil_openai_chat([{'role': 'user', 'content': prompt}],
                                           minta_json=True, timeout=30)
        data = _ekstrak_json(jawaban)
    except (InputAIGagal, ValueError):
        return None

    if not isinstance(data, dict) or not data.get('cocok'):
        return None
    perintah = [str(p).strip() for p in (data.get('perintah') or []) if str(p).strip().startswith('/')]
    if not perintah:
        return None
    return {
        'perintah': perintah[:10],
        'ringkas': str(data.get('ringkas') or '').strip(),
    }
