# Manual Scrape Orchestrator API

API ini **tidak mengubah** file scraper lama (`scraped_prices.py`, `scraped_reviews.py`, dll). Ini service baru yang mengorkestrasi:

1. User pilih hotel + input rentang tanggal (mulai dari hari ini dan seterusnya)
2. Jalankan scraping harga aktual (manual scrape) untuk rentang tanggal
3. (Opsional) jika `includeReviews=true`, jalankan scraping review
4. Simpan hasil ke Firestore:
   - `projects/{projectId}` (ringkas + status)
   - `hotel_prices` (harga aktual platform=`dataset` biar kompatibel dengan UI yang sekarang)
5. Panggil API prediksi harga dan simpan hasil prediksi ke `projects/{projectId}.predictions`

> Nearby places + amenities tetap dari database (Firestore) sesuai requirement.

## Jalankan lokal (Windows)

1. Siapkan Python env (venv/conda) lalu install dependencies dari `requirements.txt`.
2. Copy `.env.example` ke `.env` dan isi credential Firebase.
3. Start server via Uvicorn.

## Endpoint (ringkas)

- `POST /v1/projects` → buat project baru + simpan metadata (hotelIds, range, flags)
- `POST /v1/projects/{projectId}/scrape/prices` → scraping harga aktual untuk rentang tanggal
- `POST /v1/projects/{projectId}/scrape/reviews` → scraping review (opsional)
- `POST /v1/projects/{projectId}/predict` → panggil API prediksi dan simpan

Detail payload/response ada di `docs/MANUAL_SCRAPE_API.md`.
