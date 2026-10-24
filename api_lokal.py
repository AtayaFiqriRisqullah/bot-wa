from fastapi import FastAPI
from pydantic import BaseModel
from otak import proses_pesan

app = FastAPI()

class PesanMasuk(BaseModel):
    teks: str

@app.post("/proses")
def proses(pesan: PesanMasuk):
    # Memasukkan teks dari Node.js ke otak botmu
    balasan = proses_pesan(pesan.teks)
    return {"balasan": balasan}