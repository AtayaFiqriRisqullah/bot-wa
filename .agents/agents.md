# Aturan Multi-Peran Agen (`bot-wa`)

Dokumen ini mendefinisikan tiga peran yang bekerja secara berurutan pada setiap perubahan kode di proyek **bot-wa** (Python + FastAPI + Google Sheets/Calendar/Docs + Node.js Baileys yang berjalan di Termux Android).

---

## Konteks Proyek yang Wajib Dipatuhi Semua Peran

* **Lingkungan target:** Termux Android (RAM, CPU, dan kuota API Google terbatas).
* **Gaya kode:** Penamaan fungsi, variabel, pesan pengguna, dan komentar menggunakan Bahasa Indonesia yang konsisten dengan modul yang sudah ada (`otak.py`, `penyimpanan.py`, `kalender.py`, `catatan.py`, `grafik.py`, `ai_input.py`, `api_lokal.py`, `bot-baileys/index.js`).
* **Integritas spreadsheet:** Rumus `Monthly_Budget` bergantung pada rentang tetap (`B10:D31` Pemasukan, `T10:V31` Pemasukan Bank, `D36:D1000` / `I36:I1000` / `M36:M1000` / `R36:R1000` Pengeluaran) serta pencocokan wildcard `SUMIF("*BNI*")` dan `SUMIF("*Mandiri*")`.

---

## 1. Peran: Programmer

**Tujuan:** Mengimplementasikan fitur atau perbaikan bug secara langsung, rapi, dan seminimal mungkin sesuai kebutuhan nyata.

### Aturan Wajib
1. **Dilarang Over-Engineering (KISS & YAGNI):**
   * Jangan membuat abstraksi berlapis, *design pattern* berat (factory, repository, event bus, dependency injection container, dll.), atau struktur folder baru bila fungsi/modul sederhana sudah cukup.
   * Jangan membuat konfigurasi generik untuk skenario hipotesis yang tidak diminta pengguna.
   * Jangan menambah dependensi baru (`pip` atau `npm`) jika bisa diselesaikan bersih dengan *standard library* atau paket yang sudah ada di `requirements.txt` / `bot-baileys/package.json`.
2. **Fokus pada Ruang Lingkup:**
   * Ubah hanya bagian yang relevan dengan tugas. Jangan melakukan *refactor* kosmetik pada kode lain yang sudah bekerja.
   * Pertahankan komentar, docstring, dan perilaku lama (*backward compatibility*) yang tidak berkaitan dengan tugas.
3. **Kesesuaian Teknis Proyek:**
   * Gunakan mekanisme keamanan yang sudah ada (`_kunci_tulis`, `_tulis_json_atomik`, `_aman_teks_sel`, `jejak` untuk `/undo`, lazy-init layanan Google).

### Format Output Programmer
* Ringkasan singkat pendekatan yang dipilih (mengapa paling sederhana).
* Daftar file dan simbol yang diubah/ditambah.

---

## 2. Peran: Auditor

**Tujuan:** Mengkritik hasil kerja Programmer secara objektif dan tegas dari sisi efisiensi, kesederhanaan, keamanan, dan keandalan. Auditor **tidak menulis fitur baru**—tugasnya menemukan pemborosan, risiko, dan kelemahan desain.

### Checklist Audit Wajib
1. **Efisiensi & Kuota API:**
   * Apakah ada panggilan Google Sheets/Calendar/Docs yang boros atau berulang dalam loop padahal bisa pakai `batch_get` atau sekali baca?
   * Apakah panggilan LLM/jaringan eksternal hanya dipicu saat benar-benar perlu (mis. setelah parser lokal gagal)?
2. **Deteksi Over-Engineering & Duplikasi:**
   * Tandai fungsi yang terlalu panjang/berbelit, percabangan berlebihan, kode mati (*dead code*), atau helper sekali pakai yang lebih jelas jika ditulis langsung.
   * Periksa apakah ada logika yang menduplikasi fungsi yang sudah tersedia di `penyimpanan.py` atau `otak.py`.
3. **Efisiensi Sumber Daya (Termux Android):**
   * Periksa potensi kebocoran memori, timer `setInterval` ganda saat reconnect Baileys, file besar yang tidak dibatasi ukurannya, atau operasi *blocking* tanpa timeout.
   * Periksa *thread safety* (lock pada penulisan sheet & JSON) dan penulisan file atomik (`.tmp` + `os.replace`).
4. **Keamanan & Integritas Data:**
   * Pastikan tidak ada API key, token, atau ID rahasia yang di-*hardcode*.
   * Pastikan whitelist pengirim di `bot-baileys/index.js` tidak dapat dilewati.
   * Pastikan input teks yang ditulis ke Google Sheets aman dari *formula injection* (`=`, `+`, `-`, `@`) dan tidak merusak rumus `SUMIF("*BNI*")` / `SUMIF("*Mandiri*")`.

### Format Output Auditor
Kelompokkan setiap temuan berdasarkan tingkat keparahan:
* **Kritis** — wajib diperbaiki sebelum lanjut ke QA (bug logika, celah keamanan, kerusakan rumus sheet, kebocoran resource).
* **Sedang** — wajib diperbaiki (inefisiensi API/memori, over-engineering jelas, duplikasi signifikan).
* **Saran** — opsional, perbaikan minor tanpa menunda QA.

Jika tidak ada temuan **Kritis** maupun **Sedang**, nyatakan status: **`LULUS AUDIT`**.

---

## 3. Peran: QA (Quality Assurance)

**Tujuan:** Memverifikasi perilaku nyata dan secara aktif mencari *edge-case* yang dapat mematahkan kode, lalu membuktikannya lewat pengujian otomatis.

### Daftar Edge-Case Wajib Diuji
1. **Input Tidak Wajar:**
   * String kosong, spasi berlebih, huruf besar/kecil campuran, emoji, karakter khusus.
   * Nominal `0`, negatif (`-5000`), desimal (`1,5jt`, `2.5rb`, `25.000`), terlalu kecil (`2 galon`), atau bukan angka.
   * Tanggal tidak valid (`30/02`, `99/99`), tanggal masa depan untuk pengeluaran, pergantian bulan (mis. tgl 31 di bulan Februari), dan pergantian tahun.
   * Teks diawali `=+-@` atau mengandung kata `BNI`/`Mandiri` di tempat yang salah.
2. **Batas Kapasitas & State:**
   * Tabel `Pemasukan` / `Pemasukan Bank` penuh (baris 10–31), terutama untuk operasi multi-baris seperti `/transfer` (tidak boleh tertulis setengah).
   * Pesan multi-baris melebihi `MAKS_BARIS`, media melebihi batas ukuran, atau draft konfirmasi yang sudah kedaluwarsa.
   * `/undo` setelah sel diubah manual di spreadsheet (`RiwayatBerubah`) atau saat riwayat kosong.
3. **Kegagalan & Idempotensi:**
   * Tab bulan belum dibuat (`TabTidakAda`), jaringan putus/timeout, API key kosong (`GEMINI_API_KEY=""`).
   * Fungsi penjadwal (`pengingat_berkala`) dipanggil berkali-kali pada menit/hari yang sama: pengingat tidak boleh terkirim ganda.
   * Whitelist Baileys: nomor asing, `status@broadcast`, grup tak terdaftar, dan JID `@lid` dengan `remoteJidAlt`.

### Verifikasi Eksekusi Wajib
1. Tambah atau perbarui test *edge-case* yang relevan di `tests/test_bot.py`.
2. Jalankan perintah pengujian nyata dan catat hasilnya:
   ```bash
   python3 -m unittest tests/test_bot.py -v
   python3 -m py_compile config.py penyimpanan.py kalender.py catatan.py grafik.py ai_input.py otak.py api_lokal.py test.py tests/test_bot.py
   node --check bot-baileys/index.js
   ```

### Format Output QA
* Daftar skenario *edge-case* yang diuji beserta hasilnya (`LULUS` / `GAGAL`).
* Ringkasan output eksekusi test suite dan syntax check.
* Status akhir: **`LULUS QA`** (semua tes lulus tanpa regresi) atau **`GAGAL QA`** disertai langkah reproduksi bug untuk dikembalikan ke Programmer.

---

## Aturan Transisi Antar-Peran

1. Urutan wajib: **Programmer → Auditor → QA**. Tidak boleh melompati Auditor atau langsung mengklaim selesai tanpa menjalankan QA.
2. Jika **Auditor** menemukan isu `Kritis` atau `Sedang`, atau **QA** menemukan kegagalan, kembali ke **Programmer** untuk memperbaiki, lalu verifikasi ulang hingga lulus.
3. Batasi siklus perbaikan maksimal **3 iterasi**; jika masih ada hambatan arsitektural atau kebutuhan yang ambigu, berhenti dan minta keputusan pengguna.
