# Local Project Rules — Indonesian Stock AI (BEI Signal Generator)

## 1. Documentation Rules (MANDATORY)

Setiap pengerjaan/sesi kerja oleh AI agent WAJIB mencatat perubahan pada dua file berikut di root folder project:

### `summary.md` (APPEND-ONLY)
- **HANYA BOLEH MENAMBAH (APPEND-ONLY).** Dilarang keras menghapus atau me-reset entri historis sebelumnya.
- Hanya boleh menambahkan baris baru atau mengedit entri terakhir yang sedang dikerjakan pada sesi berjalan.
- Format log harian (kelompokkan berdasarkan tanggal):
  ```markdown
  ## Log Perubahan Tambahan (YYYY-MM-DD)
  1. {ringkasan issue/task}
     Masalah / Konteks:
     1. {deskripsi masalah 1}
     2. {deskripsi masalah 2}
     Solusi / Hasil:
     1. {solusi/implementasi 1}
     2. {solusi/implementasi 2}
  ```

### `walkthrough.md` (SESSION WORKSPACE)
- Boleh di-reset atau di-overwrite pada setiap sesi kerja baru untuk merinci pekerjaan sesi terkini.
- Berisi rincian breakdown task teknis, file yang disentuh/dibuat, nomor baris, dan deskripsi perubahan.
- **Wajib menyertakan bagian "Testing Checklist" di bagian paling bawah** yang merinci checklist pengujian yang harus diverifikasi pengguna.

---

## 2. Engineering & Code Quality Rules

### Karpathy Guidelines
1. **Think Before Coding:** Nyatakan asumsi secara eksplisit. Jika ragu atau rancu, tanyakan. Jangan berasumsi diam-diam.
2. **Simplicity First:** Tulis kode minimum yang menyelesaikan masalah. Jangan membuat abstraksi spekulatif, factory kosong, atau konfigurasi untuk hal yang tidak diminta.
3. **Surgical Changes:** Sentuh hanya kode yang harus disentuh. Jangan lakukan refactor kosmetik pada kode yang tidak bermasalah.
4. **Goal-Driven Execution:** Definisikan kriteria sukses dan uji secara otomatis sebelum menganggap task selesai.

### Antislop Code Hygiene
- **Dilarang menambahkan komentar AI generic:**
  - Hapus separator dekoratif (`// ========`, `# --------`).
  - Dilarang mengulang hal yang sudah jelas terbaca dari kode (restating the obvious).
  - Dilarang membuat narasi langkah demi langkah (`Step 1`, `Step 2`).
  - Dilarang memakai label kosong (`# Main logic`, `# Helper`).
  - Dilarang memakai emoji dekoratif di dalam kode/komentar.
  - Komentar maksimal 1–2 baris yang menjelaskan **alasan (WHY)** atau constraint platform, bukan mendeskripsikan ulang sintaks.

---

## 3. Architecture & Domain Principles

1. **Prediction history is immutable:** Prediksi model yang sudah diterbitkan tidak boleh diubah secara historis ketika ada model baru.
2. **Pisahkan Signal, Position, dan Outcome:** BUY signal bukan actual position. Position jurnal dicatat terpisah saat user transaksi manual.
3. **ML terpisah dari API/UI:** Engine sinyal dan pipeline ML harus dapat dieksekusi secara independen dari CLI, script, Lambda, maupun API tanpa bergantung pada Next.js atau UI handler.
4. **No future data leakage:** Perhitungan fitur hanya boleh menggunakan data yang tersedia pada saat waktu sinyal dihasilkan.
5. **Typed domain models:** Gunakan Pydantic dataclass/model untuk validasi tipe entitas.

---

## 4. Cloud Portability & Remote Access Rules

Sistem ini dirancang untuk dijalankan lokal dan siap dimigrasikan ke Cloud (AWS / VPS / Serverless) agar dapat diakses dari laptop rumah:
- **Zero Hardcoded Paths:** Dilarang meletakkan path absolut komputer lokal (seperti `C:\Users\...`) di dalam logic runtime atau script. Gunakan `pathlib.Path` relatif terhadap root project atau env variable.
- **12-Factor Configuration:** Semua konfigurasi sensitif, koneksi database, dan API key wajib dikelola via `.env` menggunakan template `.env.example`.
- **Database Abstraction:** Gunakan SQLite untuk development lokal dan pastikan kompatibilitas schema dengan PostgreSQL untuk production/cloud.
- **Serverless & Scheduled Ready:** Python script dan worker harus modular sehingga dapat dijalankan oleh AWS Lambda / EventBridge Scheduler / cron worker di cloud.
