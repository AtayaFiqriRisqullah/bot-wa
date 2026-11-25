import hmac

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

import config
from otak import (morgana_ambil_outbox, morgana_status, morgana_terima_sync,
                  pengingat_berkala, proses_media, proses_pesan_lengkap)

app = FastAPI(title='Bot WA Keuangan & Produktivitas')

_HOST_LOKAL = {'127.0.0.1', '::1', 'localhost', '::ffff:127.0.0.1', 'testclient'}


def _wajib_lokal(request: Request):
    """Lindungi endpoint internal Baileys jika uvicorn dijalankan di 0.0.0.0 (LAN/Tailscale)."""
    host = request.client.host if request.client else ''
    if host not in _HOST_LOKAL:
        raise HTTPException(status_code=403, detail='Endpoint ini hanya untuk koneksi lokal.')


def _verifikasi_token_morgana(x_morgana_token: str | None):
    if not config.MORGANA_SYNC_TOKEN:
        raise HTTPException(
            status_code=503,
            detail='MORGANA_SYNC_TOKEN belum diatur di file .env bot-wa.',
        )
    if not x_morgana_token or not hmac.compare_digest(
        x_morgana_token.strip(), config.MORGANA_SYNC_TOKEN
    ):
        raise HTTPException(status_code=401, detail='Token sinkronisasi Morgana tidak valid.')


class PesanMasuk(BaseModel):
    teks: str
    pengirim: str = 'default'


class MediaMasuk(BaseModel):
    jenis: str              # 'gambar' atau 'audio'
    mime_type: str = ''
    data_base64: str
    caption: str = ''
    pengirim: str = 'default'


class MorganaTaskItem(BaseModel):
    id: str
    title: str
    deadline: str
    priority: str = 'normal'
    stat: str = 'proficiency'
    updated_at: str = ''


class MorganaSyncPayload(BaseModel):
    tasks: list[MorganaTaskItem] = Field(default_factory=list)
    ack_ids: list[str] = Field(default_factory=list)


@app.get('/health')
def health():
    return {'ok': True}


@app.post('/proses')
def proses(pesan: PesanMasuk, request: Request):
    _wajib_lokal(request)
    # Memasukkan teks dari Node.js ke otak botmu
    hasil = proses_pesan_lengkap(pesan.teks, pengirim=pesan.pengirim)
    return {
        'balasan': hasil['teks'],
        'gambar_base64': hasil.get('gambar_base64'),
        'caption': hasil.get('caption'),
    }


@app.post('/proses_media')
def proses_media_endpoint(media: MediaMasuk, request: Request):
    _wajib_lokal(request)
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
def pengingat(request: Request):
    _wajib_lokal(request)
    # Dipanggil berkala oleh bot-baileys (tiap menit) untuk mengirim pengingat proaktif
    return {'pesan': pengingat_berkala()}


@app.get('/morgana/status')
def endpoint_morgana_status(x_morgana_token: str | None = Header(default=None)):
    _verifikasi_token_morgana(x_morgana_token)
    return morgana_status()


@app.get('/morgana/outbox')
def endpoint_morgana_outbox(x_morgana_token: str | None = Header(default=None)):
    _verifikasi_token_morgana(x_morgana_token)
    return morgana_ambil_outbox()


@app.post('/morgana/sync')
def endpoint_morgana_sync(
    payload: MorganaSyncPayload,
    x_morgana_token: str | None = Header(default=None),
):
    _verifikasi_token_morgana(x_morgana_token)
    daftar_tasks = [t.model_dump() for t in payload.tasks]
    return morgana_terima_sync(daftar_tasks, ack_ids=payload.ack_ids)