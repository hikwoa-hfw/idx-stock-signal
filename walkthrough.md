# Walkthrough: Resolusi Alert Kegagalan Pipeline CloudWatch/Telegram (16:30 WIB) & Serverless ID Collision

## Ringkasan Sesi
Sesi ini menginvestigasi dan menyelesaikan insiden alert kegagalan otomatis yang terpicu pada jam 16:30 WIB (09:30:07 UTC) tanggal 14 Oktober 2026:
```
[ALERT] BEI Stock Signal Failure
• Stage: daily_pipeline
• Date: 2026-10-14
• Error: 'NoneType' object is not callable
• Timestamp: 2026-10-14 09:30:07 UTC
```
Penyelidikan mendalam membuktikan bahwa dispatch alert CloudWatch/Telegram bekerja dengan benar, namun ada dua akar masalah pada lapisan eksekusi serverless:
1. **`TypeError: 'NoneType' object is not callable` pada baris 171 `handlers.py`:**
   Kelas repositori murni SQLite (`OutcomeRepository`, `OutcomeEngine`, `FeatureRepository`, `LabelRepository`) sebelumnya dibungkus di dalam blok `try...except ImportError` bersama pustaka berat (`SignalEngine`, `FeatureEngine`, `run_ingest` / `pandas`, `lightgbm`). Di lingkungan AWS Lambda serverless (zip 161 KB), dependensi ML tidak ada, sehingga `OutcomeRepository = None`. Saat baris 171 mencoba membuat `OutcomeRepository(...)`, Python melempar `TypeError` sebelum pengecekan duplicate-run protection di baris 178 sempat dievaluasi.
2. **`sqlite3.IntegrityError: UNIQUE constraint failed: outcomes_daily.outcome_id`:**
   Pada fallback `BaseModel` di `python/common/types.py` (yang aktif saat `pydantic` tidak terpasang di Lambda runtime), helper `Field(default_factory=lambda: str(uuid.uuid4()))` mengevaluasi fungsi factory satu kali saja saat kelas didefinisikan (tingkat class attribute). Akibatnya, seluruh record `SignalOutcomeRecord` dan `SignalDailySnapshot` yang dibuat di memori berbagi `outcome_id` dan `snapshot_id` statis yang sama, memicu benturan kunci primer unik pada SQLite saat melakukan resolusi multi-sinyal.

---

## Perubahan Kode & File

### 1. `python/cloud/handlers.py`
- Memindahkan repositori murni SQLite (`DailyBarRepository`, `SignalRepository`, `OutcomeRepository`, `OutcomeEngine`, `FeatureRepository`, `LabelRepository`) keluar dari blok `try...except` agar selalu terdefinisi di modul root level tanpa dependensi ML eksternal.
- Mengamankan pemanggilan `run_ingest`, `FeatureEngine`, dan `SignalEngine` dengan pengecekan `is not None` agar mencatat log informatif di mode serverless.
- Menambahkan fallback sinyal pre-computed: bila `SignalEngine` tidak ada di serverless runtime, handler secara otomatis memuat sinyal yang telah dihitung sebelumnya dari basis data SQLite/S3 untuk diproses dan disiarkan.

### 2. `python/common/types.py`
- Mengganti evaluasi statis `Field(default_factory=...)` pada fallback `BaseModel` dengan kelas `_FieldInfo`.
- Pada `BaseModel.__init__`, mengevaluasi `val.default_factory()` secara dinamis untuk setiap instansiasi baru, menjamin setiap model instance mendapatkan UUID dan timestamp independen.

### 3. `python/outcomes/engine.py`
- Menetapkan `outcome_id = outcome_id or str(uuid.uuid4())` dan `snapshot_id = str(uuid.uuid4())` secara eksplisit pada instansiasi model outcome dan snapshot untuk menjamin keunikan kunci bahkan bila runtime fallback digunakan.

### 4. `tests/unit/test_aws.py`
- Memperbarui pengujian `test_lambda_daily_pipeline_handler_error_handling` dengan menyertakan `force_rerun: True, max_retries: 1` agar tidak terintersepsi oleh duplicate-run protection saat basis data pengujian lokal telah memiliki sinyal pada hari yang sama.

---

## Verifikasi & Deployment

1. **Unit & Linter Checks:**
   - `ruff check .` -> **0 errors, all checks passed**.
   - `pytest tests/unit/test_aws.py` -> **39 passed 100%**.
   - `pytest tests/unit/test_price_integrity.py` -> **23 passed 100%**.
2. **Deployment ke AWS Lambda Staging:**
   - Command: `python -m scripts.deploy_aws --stage staging --deploy-lambda --set-webhook`
   - Fungsi Lambda yang diperbarui: `idx-daily-pipeline-staging`, `idx-retraining-pipeline-staging`, `idx-telegram-webhook-staging`.
3. **Live Test Invocation (AWS Boto3):**
   - Invocasi Standar:
     ```json
     {"statusCode": 200, "body": {"status": "SKIPPED_DUPLICATE", "message": "Pipeline already executed successfully for 2026-10-14", "date": "2026-10-14", "signals_count": 10}}
     ```
   - Invocasi Forced (`force_rerun=True`):
     ```json
     {"statusCode": 200, "body": {"status": "SUCCESS", "date": "2026-10-14", "bars_ingested": 0, "outcomes_resolved": 2, "signals_generated": 10, "telegram_status": "SKIPPED", "db_uploaded": true, "log_uploaded": true}}
     ```

---

## Testing Checklist
- [x] Pengecekan CloudWatch Logs menunjukkan akar masalah asli (`TypeError: 'NoneType' object is not callable` pada baris 171 `handlers.py`).
- [x] Repositori SQLite murni diimpor di level modul tanpa dependensi ML.
- [x] Fallback `BaseModel` menghasilkan UUID unik pada setiap instansiasi tanpa `pydantic`.
- [x] Pengecekan duplicate-run protection berjalan mulus (HTTP 200 `SKIPPED_DUPLICATE`).
- [x] Resolusi outcomes dan pembuatan snapshot tidak memicu kolisi kunci primer SQLite (HTTP 200 `SUCCESS`).
- [x] Seluruh unit test AWS dan Telegram lulus 100%.
- [x] Kode ter-deploy dan terverifikasi live di AWS staging.
