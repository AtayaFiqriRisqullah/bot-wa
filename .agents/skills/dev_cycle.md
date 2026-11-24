---
name: dev_cycle
description: Menjalankan siklus pengembangan berurutan Programmer -> Auditor -> QA sesuai aturan di .agents/agents.md.
---

# Workflow `/dev_cycle`

Gunakan workflow ini setiap kali pengguna memanggil `/dev_cycle <tugas>` untuk menambah fitur, memperbaiki bug, atau mengubah kode di proyek **bot-wa**.

Jalankan ketiga peran di `.agents/agents.md` **secara berurutan**, dengan penanda tahap yang jelas pada laporan kerja.

---

## Langkah 0: Persiapan
1. Baca `.agents/agents.md` agar seluruh aturan 3 peran aktif di konteks.
2. Pahami permintaan pengguna dengan tepat. Jika ada ambiguitas besar yang berdampak pada rumus spreadsheet atau perilaku utama, klarifikasi dulu sebelum mulai menulis kode.
3. Baca hanya file yang benar-benar relevan dengan tugas.

---

## Langkah 1: `[PROGRAMMER]` — Implementasi Sederhana
Bertindak sesuai aturan **Programmer** di `.agents/agents.md`:
1. Rancang perubahan paling sederhana dan langsung ke tujuan (**tanpa over-engineering**, tanpa abstraksi/dependensi yang tidak perlu).
2. Implementasikan perubahan kode secara bersih dan konsisten dengan gaya Bahasa Indonesia di repo ini.
3. Catat secara ringkas:
   * Pendekatan yang dipakai.
   * File & simbol yang diubah.

---

## Langkah 2: `[AUDITOR]` — Audit Efisiensi & Kualitas
Beralih ke sudut pandang kritis **Auditor** sesuai checklist di `.agents/agents.md`:
1. Periksa `git diff` dari hasil Langkah 1.
2. Evaluasi secara tegas:
   * Efisiensi panggilan Google API / LLM / jaringan.
   * Adakah *over-engineering*, duplikasi logika, atau kode berlebih yang bisa disederhanakan?
   * Efisiensi memori/CPU untuk Termux Android, *thread safety*, penulisan atomik, dan timeout.
   * Keamanan (tidak ada rahasia hardcoded, whitelist aman, formula injection dicegah, rumus `SUMIF` BNI/Mandiri aman).
3. Klasifikasikan temuan menjadi **Kritis**, **Sedang**, atau **Saran**.
4. **Gerbang Audit:**
   * Jika ada temuan **Kritis** atau **Sedang**: kembali ke `[PROGRAMMER]` untuk memperbaiki temuan tersebut, lalu lakukan verifikasi ulang oleh `[AUDITOR]` hingga status **`LULUS AUDIT`**.
   * Jika tidak ada temuan Kritis/Sedang: lanjut ke Langkah 3.

---

## Langkah 3: `[QA]` — Pengujian & Edge-Case
Beralih ke peran **QA** sesuai daftar *edge-case* di `.agents/agents.md`:
1. Identifikasi *edge-case* yang paling berisiko mematahkan perubahan baru (input kosong/aneh, nominal nol/negatif/desimal, batas tabel penuh, tab belum ada, konfirmasi kedaluwarsa, idempotensi pengingat, whitelist/LID, `/undo`).
2. Tambahkan atau perbarui unit test pada `tests/test_bot.py` untuk mencakup skenario normal maupun *edge-case* tersebut.
3. Jalankan seluruh verifikasi secara nyata di terminal:
   ```bash
   python3 -m unittest tests/test_bot.py -v
   python3 -m py_compile config.py penyimpanan.py kalender.py catatan.py grafik.py ai_input.py otak.py api_lokal.py test.py tests/test_bot.py
   node --check bot-baileys/index.js
   ```
4. **Gerbang QA:**
   * Jika ada test gagal atau ditemukan bug baru: kembali ke `[PROGRAMMER]` untuk perbaikan (dan audit singkat bila perubahannya substansial), lalu ulangi `[QA]` hingga seluruh verifikasi **100% lulus** (`LULUS QA`).
   * Maksimal 3 iterasi perbaikan; jika masih terblokir, laporkan akar masalahnya ke pengguna.

---

## Langkah 4: Laporan Akhir `/dev_cycle`
Sampaikan ringkasan padat ke pengguna dengan struktur berikut:
1. **`[PROGRAMMER]`** — Ringkasan perubahan & daftar file/simbol.
2. **`[AUDITOR]`** — Temuan audit (jika ada) & perbaikan yang diterapkan, status `LULUS AUDIT`.
3. **`[QA]`** — Daftar *edge-case* yang diuji & hasil eksekusi aktual test suite/syntax check, status `LULUS QA`.
