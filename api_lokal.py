from fastapi import FastAPI
from pydantic import BaseModel

from otak import pengingat_berkala, proses_media, proses_pesan_lengkap

app = FastAPI(title='Bot WA Keuangan & Produktivitas')


class PesanMasuk(BaseModel):
    teks: str
    pengirim: str = 'default'


class MediaMasuk(BaseModel):
    jenis: str              # 'gambar' atau 'audio'
    mime_type: str = ''
    data_base64: str
    caption: str = ''
    pengirim: str = 'default'


@app.get('/health')
def health():
    return {'ok': True}


@app.post('/proses')
def proses(pesan: PesanMasuk):
    # Memasukkan teks dari Node.js ke otak botmu
    hasil = proses_pesan_lengkap(pesan.teks, pengirim=pesan.pengirim)
    return {
        'balasan': hasil['teks'],
        'gambar_base64': hasil.get('gambar_base64'),
        'caption': hasil.get('caption'),
    }


@app.post('/proses_media')
def proses_media_endpoint(media: MediaMasuk):
    # Memproses foto struk (gambar) atau voice note (audio) dari Node.js
    hasil = proses_media(
        media.jenis,
        media.mime_type,
        media.data_base64,
        caption=media.caption,
        pengirim=media.pengirim,
    )
    return {
        'balasan': hasil['teks'],
        'gambar_base64': hasil.get('gambar_base64'),
        'caption': hasil.get('caption'),
    }


@app.get('/pengingat')
def pengingat():
    # Dipanggil berkala oleh bot-baileys (tiap menit) untuk mengirim pengingat proaktif
    return {'pesan': pengingat_berkala()}