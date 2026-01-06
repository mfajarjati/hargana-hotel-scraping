---
title: Hargana Hotel Scraping
emoji: 🏨
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
license: mit
---

# Hargana Hotel Scraping API

Simple API untuk scraping harga hotel dari Google Travel menggunakan Selenium.

## Endpoints

### `GET /`

Service info dan daftar endpoints

### `GET /health`

Health check

### `POST /v1/projects`

Scraping harga hotel untuk multiple hotels dan date range

**Request Body:**

```json
{
  "hotels": [
    {
      "hotelId": "ChIJ...",
      "hotelName": "PRIME PARK Hotel Bandung"
    },
    {
      "hotelId": "ChIJ...",
      "hotelName": "Hotel Dafam Rio"
    }
  ],
  "range": {
    "start": "2026-01-10",
    "end": "2026-01-12"
  }
}
```

**Response:**

```json
{
  "ok": true,
  "projectId": "manual_1234567890",
  "dateRange": {
    "start": "2026-01-10",
    "end": "2026-01-12"
  },
  "hotels": [
    {
      "hotelId": "ChIJ...",
      "hotelName": "PRIME PARK Hotel Bandung",
      "rating": 4.5,
      "reviewsCount": 1250,
      "prices": [
        {
          "date": "2026-01-10",
          "price": 450000,
          "method": "aria-label",
          "error": null
        },
        {
          "date": "2026-01-11",
          "price": 520000,
          "method": "aria-label",
          "error": null
        }
      ]
    }
  ]
}
```

## Features

- ✅ Headless Chrome scraping
- ✅ Anti-detection measures
- ✅ Multiple price extraction methods
- ✅ Rating & reviews extraction
- ✅ Date range support
- ✅ Error handling & logging

## Tech Stack

- **Flask** - Web framework
- **Selenium** - Browser automation
- **BeautifulSoup** - HTML parsing
- **Chrome** - Headless browser

## License

MIT License
