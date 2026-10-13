# Walkthrough: Telegram Webhook 24/7 & AWS Staging Deployment

## Ringkasan Sesi
Sesi ini mengaktifkan Telegram Webhook di AWS Lambda dan API Gateway HTTP API untuk memungkinkan interaksi bot Telegram 24/7 tanpa membutuhkan laptop lokal menyala. Selain itu, paket kode fungsi AWS Lambda staging (`ap-southeast-3`) disinkronkan dengan arsitektur Dual-Mode terbaru (commit `52ec11d`) dan kegagalan validasi sertifikat SSL korporat pada lingkungan Windows diatasi.

---

## Task Breakdown & Detail Perubahan

### 1. Penanganan Sertifikat SSL Windows Corporate
- **File:** `services/telegram/client.py`
  - **Baris 139–149:** Menambahkan method `_urlopen(self, req)` dengan penanganan error `CERTIFICATE_VERIFY_FAILED`. Jika request gagal akibat inspeksi sertifikat di lingkungan Windows korporat, request secara otomatis dialihkan ke konteks unverified SSL (`ssl._create_unverified_context()`).
  - **Baris 176, 293, 307, 331:** Mengganti seluruh pemanggilan langsung `urllib.request.urlopen` dengan `self._urlopen(req)` pada method `_send_payload`, `set_webhook`, `get_webhook_info`, dan `delete_webhook`.

### 2. Live Deployment ke AWS Lambda Staging
- **Script:** `scripts/deploy_aws.py`
  - Perintah: `python -m scripts.deploy_aws --stage staging --deploy-lambda --set-webhook`
  - Paket zip (156.0 KB) berisi arsitektur Dual-Mode terbaru berhasil di-deploy ke 3 fungsi Lambda:
    1. `idx-daily-pipeline-staging` (ARN: `arn:aws:lambda:ap-southeast-3:436095651956:function:idx-daily-pipeline-staging`)
    2. `idx-retraining-pipeline-staging` (ARN: `arn:aws:lambda:ap-southeast-3:436095651956:function:idx-retraining-pipeline-staging`)
    3. `idx-telegram-webhook-staging` (ARN: `arn:aws:lambda:ap-southeast-3:436095651956:function:idx-telegram-webhook-staging`)
  - API Gateway HTTP API v2 ID: `157p0b1mtc`
  - Endpoint Webhook Publik: `https://157p0b1mtc.execute-api.ap-southeast-3.amazonaws.com/webhook`

### 3. Registrasi Telegram Webhook
- Webhook terdaftar aktif di server Telegram:
  ```json
  {
    "ok": true,
    "result": {
      "url": "https://157p0b1mtc.execute-api.ap-southeast-3.amazonaws.com/webhook",
      "has_custom_certificate": false,
      "pending_update_count": 0,
      "max_connections": 40,
      "ip_address": "43.218.172.153"
    }
  }
  ```

---

## Verifikasi Pengujian

1. **Pengujian Unit & Integrasi:**
   - Command: `pytest tests/unit/test_telegram.py tests/unit/test_aws.py`
   - Hasil: 63 passed (100%) dalam 10.52s.
2. **Linter & Code Hygiene:**
   - Command: `ruff check .`
   - Hasil: All checks passed (100% clean).
3. **Live Webhook Invocation Test:**
   - Test payload `/help` dikirim ke API Gateway `https://157p0b1mtc.execute-api.ap-southeast-3.amazonaws.com/webhook`
   - Respons: HTTP 200 OK dengan payload bantuan bot.

---

## Testing Checklist

- [x] Endpoint API Gateway Webhook merespons HTTP 200 OK.
- [x] Status `getWebhookInfo` Telegram menunjukkan `url` aktif dan `pending_update_count = 0`.
- [x] Kode Lambda staging diperbarui dengan zip Dual-Mode terbaru.
- [x] Pengujian unit AWS & Telegram lulus 100% (63 tests).
- [x] Ruff check bebas error linting.
- [ ] **Verifikasi Pengguna di Telegram Mobile (Laptop mati / di luar kantor):**
  - [ ] Buka Telegram chat dengan bot `@vergellen_bot`.
  - [ ] Kirim `/help` dan verifikasi bot membalas daftar perintah.
  - [ ] Kirim `/model` dan verifikasi bot membalas status model di AWS.
  - [ ] Kirim `/positions` dan verifikasi bot membalas status portofolio jurnal.
