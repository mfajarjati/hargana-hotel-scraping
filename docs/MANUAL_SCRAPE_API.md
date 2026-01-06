# Manual Scrape API – UI → API → Firestore

Dokumen ini mendeskripsikan flow baru yang kamu minta: **scraping manual** (harga aktual + optional review) lalu **prediksi** — semuanya disimpan ke collection `projects` (dan `hotel_prices` untuk kompatibilitas UI existing).

## Kontrak data utama

### Input wajib

- `hotelIds`: array string (boleh prefixed `id_`/`en_` atau clean id)
- `range.start`, `range.end`: string `YYYY-MM-DD`
  - **aturan:** `start >= today` (hari ini) dan `end >= start`

### Flags

- `includeReviews`: boolean (kalau `true` => jalankan scraping review dan simpan)

### Output utama

- `projects/{projectId}` akan berisi:
  - `dateRange: { start, end }`
  - `selectedHotels: string[]`
  - `actualPricesIngested: boolean`
  - `reviewsIngested: boolean`
  - `predictions: Record<hotelId, Array<{date, price, basePrice?, dynamicPrice?}>>`
  - `scrape: { actualPrices?: Record<hotelId, Array<{date, price, platform, url?}>>, reviews?: Record<hotelId, any[]> }`

### Kompatibilitas UI existing

UI existing membaca harga aktual dari collection `hotel_prices` dengan filter:

- `hotel_id == cleanHotelId`
- `platform == dataset`
- `date == YYYY-MM-DD`

Jadi service ini akan menulis docId:

- `${hotel_id}_${date}_dataset`

## Endpoint

### 1) Create project

`POST /v1/projects`

Body:

```json
{
  "projectName": "Manual Scrape 20 Dec",
  "hotelIds": ["id_ChIJ66PbeC_maC4RMxLwD6swTL0"],
  "range": { "start": "2025-12-20", "end": "2025-12-25" },
  "includeReviews": true
}
```

### 2) Scrape prices (actual)

`POST /v1/projects/{projectId}/scrape/prices`

Body:

```json
{
  "mode": "range",
  "platform": "dataset",
  "useExistingHotelPriceAsFallback": true
}
```

### 3) Scrape reviews (optional)

`POST /v1/projects/{projectId}/scrape/reviews`

Body:

```json
{
  "maxReviews": 200
}
```

### 4) Predict + store

`POST /v1/projects/{projectId}/predict`

Body:

```json
{
  "predictionApiUrl": "https://mfajarjati-hargana-hotel.hf.space/predict"
}
```

Payload yang dipakai untuk memanggil HF Space `/predict` **mengikuti persis** yang dipakai web (`projectProcessingService.ts`):

```json
{
  "hotel_id": "ChIJ66PbeC_maC4RMxLwD6swTL0",
  "hotel_name": "Kimaya Braga Bandung by HARRIS",
  "rating": 4.5,
  "reviews_count": 1800,
  "amenities_count": 45,
  "hotel_star": 4,
  "dist_to_center_km": 2.0,
  "start_date": "2025-12-21",
  "days": 7,
  "confidence_level": 0.95,
  "multiplier_range": [0.8, 1.2]
}
```

## Catatan penting

- Scraper Selenium itu berat; endpoint akan menjalankan job sinkron (versi pertama). Kalau nanti mau scalable, bisa dipindah ke background worker.
- Nearby places & amenities **tidak** discrape di sini, sesuai requirement: ambil dari Firestore (koleksi hotel).

## Endpoint tambahan (reviews)

`POST /v1/projects/{projectId}/scrape/reviews`

Body:

```json
{
  "maxReviews": 200,
  "dryRun": false
}
```
