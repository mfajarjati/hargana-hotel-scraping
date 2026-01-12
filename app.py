"""
Hargana Hotel Scraping API
Simple API untuk scraping harga hotel dari Google Travel

Tidak pakai Firebase, tidak pakai credentials ribet.
Langsung scrape pakai Selenium, return JSON.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
import os
import threading
import queue
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
from time import sleep
from datetime import datetime
from pathlib import Path
from selenium.webdriver.chrome.service import Service

# Add parent directory to path to import scraped_prices
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# FIFO job queue (single-process, no Redis/Celery). maxsize=1 fully prevents overlap.
job_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=1)

# In-memory job registry
jobs: Dict[str, Dict[str, Any]] = {}
jobs_lock = threading.Lock()

# Start exactly one worker thread at app startup
_worker_started = False
_worker_started_lock = threading.Lock()


def ensure_screenshot_dir():
    folder = Path(__file__).parent / "screenshots"
    folder.mkdir(exist_ok=True)
    return folder


def safe_filename(text: str) -> str:
    return "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in text)[:150]


def wait_for_page_ready(driver, label="page", timeout=20):
    """Poll document.readyState until complete to reduce frame detach issues."""
    import time

    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            state = driver.execute_script("return document.readyState")
            if state == "complete":
                return True
        except Exception:
            pass
        sleep(0.5)
    print(f"[WARN] Timeout waiting for {label} to be ready")
    return False


def _iso_now() -> str:
    return datetime.now().isoformat()


def _set_job_fields(job_id: str, updates: Dict[str, Any]) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        job.update(updates)


def start_worker_once() -> None:
    global _worker_started
    with _worker_started_lock:
        if _worker_started:
            return

        t = threading.Thread(target=worker_loop, name="scrape-worker", daemon=True)
        t.start()
        _worker_started = True
        print("[WORKER] Background worker thread started")


def worker_loop() -> None:
    """Single never-exiting worker that runs Selenium jobs sequentially."""
    while True:
        job = job_queue.get()  # blocks
        job_id = job.get("jobId")
        try:
            if not job_id:
                print("[WORKER] Received job without jobId; skipping")
                continue

            print(f"[JOB] Started job {job_id}")
            _set_job_fields(
                job_id,
                {
                    "status": "running",
                    "startedAt": _iso_now(),
                    "progress": {"current": 0, "total": 0, "message": "starting"},
                },
            )

            # Run scraping synchronously in the worker (never in request thread)
            result = run_scrape_job(job_id, job)

            # Mark completed only AFTER Selenium is fully done (driver.quit happens inside run_scrape_job)
            _set_job_fields(
                job_id,
                {
                    "status": "completed",
                    "finishedAt": _iso_now(),
                    "error": None,
                    "result": result,
                    "progress": {"current": 1, "total": 1, "message": "completed"},
                },
            )
            print(f"[JOB] Finished job {job_id}")
        except Exception as e:
            print(f"[JOB] Failed job {job_id}: {e}")
            _set_job_fields(
                job_id,
                {
                    "status": "failed",
                    "finishedAt": _iso_now(),
                    "error": str(e),
                    "progress": {"current": 1, "total": 1, "message": "failed"},
                },
            )
        finally:
            try:
                job_queue.task_done()
            except Exception:
                pass

app = Flask(__name__)
CORS(app)

# Ensure single worker started when module is imported (covers flask run + direct python)
start_worker_once()

@app.route('/', methods=['GET'])
def root():
    return jsonify({
        "ok": True,
        "service": "hargana-hotel-scraping-api",
        "version": "1.0.0",
        "endpoints": {
            "/": "Service info",
            "/health": "Health check",
            "/v1/projects": "POST - Create scraping project",
            "/v1/projects/{id}/scrape/prices": "POST - Scrape prices",
            "/v1/projects/{id}/scrape/reviews": "POST - Scrape reviews"
        }
    })

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/v1/projects', methods=['POST'])
def create_project():
    """
    SCRAPING ACTUAL PRICES - PAKAI HOTEL NAME!
    
    Request:
    {
        "hotels": [
            {"hotelId": "ChIJ...", "hotelName": "PRIME PARK Hotel Bandung"},
            {"hotelId": "ChIJ...", "hotelName": "Hotel Dafam Rio"}
        ],
        "range": {"start": "2025-12-22", "end": "2025-12-22"}
    }
    
    Returns:
    {
        "ok": true,
        "projectId": "manual_xxx",
        "hotels": [
            {
                "hotelId": "ChIJ...",
                "hotelName": "PRIME PARK Hotel Bandung",
                "prices": [
                    {"date": "2025-12-22", "price": 450000, "method": "aria-label"}
                ]
            }
        ]
    }
    """
    # Validate + enqueue job; return immediately.
    data = request.get_json(silent=True) or {}
    hotels_input = data.get('hotels', [])
    if not hotels_input and data.get('hotelIds'):
        hotels_input = [{"hotelId": hid, "hotelName": None} for hid in data.get('hotelIds', [])]

    if not hotels_input:
        return jsonify({"ok": False, "error": "hotels array required with hotelId and hotelName"}), 400

    date_range = data.get('range', {})
    start_str = date_range.get('start')
    end_str = date_range.get('end')
    if not start_str or not end_str:
        return jsonify({"ok": False, "error": "range.start and range.end are required"}), 400

    job_id = f"job_{uuid.uuid4().hex}"
    job_payload = {
        "jobId": job_id,
        "payload": data,
        "createdAt": _iso_now(),
    }

    # Register job before enqueue so polling can see it immediately as queued
    with jobs_lock:
        jobs[job_id] = {
            "jobId": job_id,
            "status": "queued",
            "progress": {"current": 0, "total": 1, "message": "queued"},
            "createdAt": job_payload["createdAt"],
            "startedAt": None,
            "finishedAt": None,
            "error": None,
            "result": None,
        }

    try:
        job_queue.put_nowait(job_payload)
    except queue.Full:
        # Queue maxsize=1: busy means one job is already queued/running
        _set_job_fields(job_id, {"status": "failed", "finishedAt": _iso_now(), "error": "Queue is full"})
        return jsonify({
            "ok": False,
            "error": "Scrape queue is full. Try again shortly.",
            "code": "QUEUE_FULL",
        }), 429

    print(f"[JOB] Enqueued job {job_id}")
    return jsonify({
        "ok": True,
        "jobId": job_id,
        "status": "queued",
    }), 202


@app.route('/v1/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"ok": False, "error": "Job not found", "code": "JOB_NOT_FOUND"}), 404
        # Return only required fields (plus jobId for convenience)
        return jsonify({
            "ok": True,
            "jobId": job_id,
            "status": job.get("status"),
            "progress": job.get("progress"),
            "startedAt": job.get("startedAt"),
            "finishedAt": job.get("finishedAt"),
            "error": job.get("error"),
            # Keep result available for the frontend when completed
            "result": job.get("result"),
        })


def run_scrape_job(job_id: str, job: Dict[str, Any]) -> Dict[str, Any]:
    """Runs the existing Selenium scraping logic for a queued job.

    IMPORTANT: This must only be called from the worker thread.
    """
    # Import yang dibutuhkan (keep same behavior)
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from bs4 import BeautifulSoup
    from datetime import datetime as dt, timedelta
    from urllib.parse import quote
    import re

    data = (job or {}).get("payload") or {}
    hotels_input = data.get('hotels', [])
    if not hotels_input and data.get('hotelIds'):
        hotels_input = [{"hotelId": hid, "hotelName": None} for hid in data.get('hotelIds', [])]

    date_range = data.get('range', {})
    start_str = date_range.get('start', datetime.now().strftime('%Y-%m-%d'))
    end_str = date_range.get('end', start_str)

    print(f"\n{'='*60}")
    print(f"[SCRAPING] Job {job_id} starting")
    print(f"[SCRAPING] Hotels count: {len(hotels_input)}")
    print(f"[SCRAPING] Date Range: {start_str} to {end_str}")
    print(f"{'='*60}\n")

    # ------------------------------------------------------------
    # DEFINITIVE NIGHTLY DATE RULES (LOCKED)
    # range.end is boundary-only but INCLUDED as a check-in night.
    # For each night: checkin = D, checkout = D + 1 day
    # ------------------------------------------------------------
    start_dt = dt.strptime(start_str, '%Y-%m-%d')
    end_dt = dt.strptime(end_str, '%Y-%m-%d')
    nights = []  # list[(checkin, checkout)]
    current = start_dt
    while current <= end_dt:
        checkin = current.strftime('%Y-%m-%d')
        checkout = (current + timedelta(days=1)).strftime('%Y-%m-%d')
        nights.append((checkin, checkout))
        current += timedelta(days=1)

    _set_job_fields(job_id, {"progress": {"current": 0, "total": len(hotels_input), "message": "scraping"}})

    # Setup Chrome - HEADLESS dengan anti-detection
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # # Prepare screenshot directory per job
    # screenshot_dir = ensure_screenshot_dir()

    # driver = webdriver.Chrome(options=chrome_options)


    service = Service("/usr/local/bin/chromedriver")

    driver = webdriver.Chrome(
        service=service,
        options=chrome_options
    )

    
    try:
        try:
            driver.maximize_window()
        except Exception:
            driver.set_window_size(1920, 1080)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        results = []

        # SCRAPE EACH HOTEL
        for idx, hotel_obj in enumerate(hotels_input, start=1):
            hotel_id = hotel_obj.get('hotelId')
            hotel_name = hotel_obj.get('hotelName')

            _set_job_fields(job_id, {"progress": {"current": idx - 1, "total": len(hotels_input), "message": f"hotel {idx}/{len(hotels_input)}"}})

            if not hotel_name:
                print(f"[ERROR] Hotel {hotel_id} has no hotelName!")
                results.append({
                    "hotelId": hotel_id,
                    "hotelName": None,
                    "prices": [],
                    "error": "Hotel name not provided"
                })
                continue

            print(f"\n[HOTEL] Processing: {hotel_name} (ID: {hotel_id})")

            hotel_result = {
                "hotelId": hotel_id,
                "hotelName": hotel_name,
                "prices": [],
                "rating": None,
                "reviewsCount": None,
            }

            # ✅ STEP 1: SEARCH WITH "hotel_name + reviews" - TANPA TANGGAL DULU!
            # Ini penting biar muncul list hotel dan kita bisa PILIH yang benar
            try:
                encoded_name = quote(f"{hotel_name} reviews")
                search_url = f"https://www.google.com/travel/search?q={encoded_name}&hl=id"
                print(f"[STEP 1] Searching hotel: {search_url}")
                driver.get(search_url)
                wait_for_page_ready(driver, "search page")
                sleep(4)

                # ✅ STEP 2: CLICK/PILIH HOTEL YANG BENAR dari hasil pencarian
                print(f"[STEP 2] Selecting hotel from search results...")
                soup = BeautifulSoup(driver.page_source, "lxml")
                hotel_cards = soup.find_all("div", class_="BcKagd")

                hotel_selected = False
                if hotel_cards:
                    # Pilih satu hotel saja (exact match lebih dulu, kalau tidak ada ambil pertama)
                    target_link = None
                    for hotel in hotel_cards:
                        name_elem = hotel.find("h2", class_="BgYkof")
                        if name_elem and hotel_name.lower() in name_elem.text.lower():
                            target_link = hotel.find("a", class_="PVOOXe")
                            break

                    if not target_link:
                        target_link = hotel_cards[0].find("a", class_="PVOOXe") if hotel_cards else None

                    if target_link:
                        driver.get("https://www.google.com" + target_link["href"])
                        wait_for_page_ready(driver, "hotel page")
                        hotel_selected = True
                        print("✓ Hotel selected")
                        sleep(6)

                if not hotel_selected:
                    print(f"× Failed to select hotel")
                    hotel_result["prices"].append({
                        "error": "Failed to select hotel from search results"
                    })
                    results.append(hotel_result)
                    continue

            except Exception as e:
                print(f"[ERROR] Failed to search/select hotel: {e}")
                hotel_result["prices"].append({"error": str(e)})
                results.append(hotel_result)
                continue

            # ✅ STEP 3: SCRAPE PER NIGHT (hotel sudah dipilih, tidak reload page antar malam)
            for checkin_str, checkout_str in nights:
                print(f"\n[NIGHT] Scraping: {checkin_str} -> {checkout_str} (nights=1)")

                try:
                    # ✅ UPDATE TANGGAL di halaman hotel yang sudah terbuka
                    # CARA LEBIH RELIABLE: Update URL langsung dengan query parameter
                    print(f"[STEP 3] Updating dates to {checkin_str} - {checkout_str}")

                    # STRICT: Do NOT reload hotel page between nights.
                    # Always update stay dates via the hotel page date picker.
                    try:
                        date_picker = driver.find_element(By.CSS_SELECTOR, "div.FMXxAd.P0TvEc")
                        driver.execute_script("arguments[0].click();", date_picker)
                        sleep(6)

                        # Pick check-in and check-out
                        driver.execute_script(f"""
                            const checkinDate = \"{checkin_str}\";
                            const checkoutDate = \"{checkout_str}\";

                            const allDates = document.querySelectorAll('div[data-iso], td[data-date]');
                            for (const dateCell of allDates) {{
                                if (dateCell.getAttribute('data-iso') === checkinDate ||
                                    dateCell.getAttribute('data-date') === checkinDate) {{
                                    dateCell.click();
                                    break;
                                }}
                            }}

                            setTimeout(() => {{
                                for (const dateCell of allDates) {{
                                    if (dateCell.getAttribute('data-iso') === checkoutDate ||
                                        dateCell.getAttribute('data-date') === checkoutDate) {{
                                        dateCell.click();
                                        break;
                                    }}
                                }}
                            }}, 600);
                        """)
                        sleep(9)

                        # Click Done/Apply
                        done_buttons = driver.find_elements(By.CSS_SELECTOR, "div.VfPpkd-RLmnJb")
                        for btn in done_buttons:
                            if "Done" in btn.text or btn.is_displayed():
                                driver.execute_script("arguments[0].click();", btn)
                                break
                        sleep(16)

                    except Exception as date_error:
                        print(f"[WARNING] Date update failed: {date_error}, continuing anyway...")
                        sleep(5)

                    # Tunggu tanggal terpasang dan harga muncul setelah tanggal di-set
                    try:
                        wait = WebDriverWait(driver, 25)
                        price_el = wait.until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "span.qQOQpe.prxS3d"))
                        )
                        sleep(4)
                    except Exception:
                        price_el = None
                        print("[WAIT] Price element not found after date set, continuing with fallbacks")

                    # ✅ EXTRACT PRICE - Multiple methods dengan priority
                    price_found = 0
                    method_used = None

                    # METODE 1: CSS Selector class "qQOQpe prxS3d" (harga utama di detail hotel)
                    try:
                        price_elem = price_el or driver.find_element(By.CSS_SELECTOR, "span.qQOQpe.prxS3d")
                        if price_elem:
                            text = price_elem.text.strip()
                            print(f"[METHOD-1] qQOQpe.prxS3d: {text}")
                            if text and 'Rp' in text:
                                numbers = re.findall(r'\d+', text.replace('.', '').replace(',', ''))
                                if numbers:
                                    price_found = int(''.join(numbers))
                                    method_used = "css-qQOQpe"
                    except:
                        pass

                    # METODE 2: Button aria-label (booking platform)
                    if price_found == 0:
                        try:
                            wait = WebDriverWait(driver, 5)
                            price_buttons = wait.until(
                                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "button[aria-label*='Rp']"))
                            )
                            if price_buttons:
                                aria_label = price_buttons[0].get_attribute('aria-label')
                                print(f"[METHOD-2] aria-label: {aria_label}")
                                # Extract HANYA harga, bukan semua angka!
                                # Format: "Rp 347.174 untuk tanggal..."
                                price_match = re.search(r'Rp\s*([\d.,]+)', aria_label)
                                if price_match:
                                    price_str = price_match.group(1).replace('.', '').replace(',', '')
                                    price_found = int(price_str)
                                    method_used = "aria-label"
                        except:
                            pass

                    # METODE 3: Div dengan class yang mengandung price (lebih spesifik)
                    if price_found == 0:
                        try:
                            price_divs = driver.find_elements(By.XPATH, "//div[starts-with(text(), 'Rp') and string-length(text()) > 3 and string-length(text()) < 20]")
                            if price_divs:
                                for div in price_divs:
                                    text = div.text.strip()
                                    print(f"[METHOD-3] div-xpath: {text}")
                                    # Extract hanya bagian harga
                                    price_match = re.search(r'Rp\s*([\d.,]+)', text)
                                    if price_match:
                                        price_str = price_match.group(1).replace('.', '').replace(',', '')
                                        price_found = int(price_str)
                                        method_used = "div-xpath"
                                        break
                        except:
                            pass

                    # METODE 4: BeautifulSoup parsing (paling reliable untuk static content)
                    if price_found == 0:
                        try:
                            soup = BeautifulSoup(driver.page_source, "lxml")

                            # Cari span dengan class price
                            price_span = soup.find("span", class_="qQOQpe prxS3d")
                            if price_span:
                                text = price_span.text.strip()
                                print(f"[METHOD-4] BeautifulSoup span: {text}")
                                price_match = re.search(r'Rp\s*([\d.,]+)', text)
                                if price_match:
                                    price_str = price_match.group(1).replace('.', '').replace(',', '')
                                    price_found = int(price_str)
                                    method_used = "bs4-span"
                        except:
                            pass

                    # METODE 5: Fallback terakhir - cari semua text dengan "Rp" tapi filter yang masuk akal
                    if price_found == 0:
                        try:
                            all_elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'Rp')]")
                            for elem in all_elements:
                                text = elem.text.strip()
                                # Filter: harus dimulai dengan Rp, panjang wajar, ada angka
                                if text.startswith('Rp') and 5 < len(text) < 25:
                                    print(f"[METHOD-5] fallback text: {text}")
                                    # Extract HANYA bagian harga pertama
                                    price_match = re.search(r'Rp\s*([\d.,]+)', text)
                                    if price_match:
                                        price_str = price_match.group(1).replace('.', '').replace(',', '')
                                        try:
                                            potential_price = int(price_str)
                                            # Filter harga yang masuk akal (50rb - 50jt)
                                            if 50000 < potential_price < 50000000:
                                                price_found = potential_price
                                                method_used = "fallback-filtered"
                                                break
                                        except:
                                            continue
                        except:
                            pass

                    # ✅ REMOVED: Rating & reviewsCount scraping moved to END after all dates

                    print(f"[RESULT] Price: {price_found} | Method: {method_used}")

                    # # Simpan screenshot full page (bukan crop harga saja)
                    # try:
                    #     # Screenshot filename MUST include check-in date
                    #     shot_name = f"{safe_filename(job_id)}__{safe_filename(hotel_name)}__{checkin_str}.png"
                    #     shot_path = Path(screenshot_dir) / shot_name
                    #     driver.save_screenshot(str(shot_path))
                    #     print(f"[SS] Saved full-page screenshot: {shot_path}")
                    # except Exception as ss_err:
                    #     print(f"[SS] Failed to save screenshot: {ss_err}")

                    # MANDATORY OUTPUT STRUCTURE PER NIGHT
                    hotel_result["prices"].append({
                        "hotelId": hotel_id,
                        "hotelName": hotel_name,
                        "date": checkin_str,      # MUST be check-in
                        "checkin": checkin_str,
                        "checkout": checkout_str,
                        "nights": 1,
                        "price": price_found,
                        "method": method_used,
                        "error": None if price_found > 0 else "No price found",
                    })

                except Exception as e:
                    print(f"[ERROR] Scraping failed for {checkin_str}: {e}")
                    hotel_result["prices"].append({
                        "hotelId": hotel_id,
                        "hotelName": hotel_name,
                        "date": checkin_str,
                        "checkin": checkin_str,
                        "checkout": checkout_str,
                        "nights": 1,
                        "price": 0,
                        "method": None,
                        "error": str(e),
                    })

            # ✅ SCRAPE RATING & REVIEWS COUNT SETELAH SEMUA HARGA (hotel page masih terbuka)
            print(f"\n[METADATA] Scraping rating & reviews count for {hotel_name}...")
            try:
                def parse_reviews_count(raw: str):
                    """Parse format '4.9 rb' atau '1.234' jadi integer"""
                    text = raw.lower().replace("ulasan", "").strip()
                    text = text.replace("(", "").replace(")", "")
                    if "rb" in text:
                        num_part = text.replace("rb", "").strip().replace(",", ".")
                        try:
                            return int(float(num_part) * 1000)
                        except:
                            return None
                    digits = "".join(ch for ch in text if ch.isdigit())
                    if digits:
                        try:
                            return int(digits)
                        except:
                            return None
                    return None

                # Parse current page (hotel sudah terbuka dari scraping harga terakhir)
                soup = BeautifulSoup(driver.page_source, "lxml")
                
                # Extract rating - class: "KFi5wf lA0BZ"
                rating_span = soup.find("span", class_="KFi5wf lA0BZ")
                if rating_span and rating_span.text:
                    try:
                        rating_text = rating_span.text.strip().replace(",", ".")
                        hotel_result["rating"] = float(rating_text)
                        print(f"[METADATA] ✓ Rating: {hotel_result['rating']}")
                    except Exception as e:
                        print(f"[METADATA] × Failed to parse rating: {e}")

                # Extract reviews count - class: "P2NYOe GFm7je sSHqwe" (precise) or "jdzyld" (fallback)
                reviews_precise = soup.select_one("span.P2NYOe.GFm7je.sSHqwe")
                if reviews_precise and reviews_precise.text:
                    parsed = parse_reviews_count(reviews_precise.text)
                    if parsed:
                        hotel_result["reviewsCount"] = parsed
                        print(f"[METADATA] ✓ Reviews Count (precise): {hotel_result['reviewsCount']}")
                
                # Fallback jika tidak ketemu precise selector
                if hotel_result["reviewsCount"] is None:
                    reviews_elem = soup.find("span", class_="jdzyld")
                    if reviews_elem and reviews_elem.text:
                        parsed = parse_reviews_count(reviews_elem.text)
                        if parsed:
                            hotel_result["reviewsCount"] = parsed
                            print(f"[METADATA] ✓ Reviews Count (fallback): {hotel_result['reviewsCount']}")

                # Default values jika masih None
                if hotel_result["rating"] is None:
                    hotel_result["rating"] = 4.0
                    print(f"[METADATA] ! Using default rating: 4.0")
                if hotel_result["reviewsCount"] is None:
                    hotel_result["reviewsCount"] = 100
                    print(f"[METADATA] ! Using default reviews count: 100")

            except Exception as meta_err:
                print(f"[METADATA] ERROR: {meta_err}")
                # Fallback ke defaults
                if hotel_result["rating"] is None:
                    hotel_result["rating"] = 4.0
                if hotel_result["reviewsCount"] is None:
                    hotel_result["reviewsCount"] = 100

            results.append(hotel_result)
            print(f"\n[HOTEL] Finished hotel {hotel_name}: {len(hotel_result['prices'])} prices scraped")

        _set_job_fields(job_id, {"progress": {"current": len(hotels_input), "total": len(hotels_input), "message": "finalizing"}})

        return {
            "ok": True,
            "jobId": job_id,
            "dateRange": {"start": start_str, "end": end_str},
            "hotels": results,
        }
    finally:
        # Must quit driver before marking completed in worker_loop
        try:
            driver.quit()
        finally:
            print(f"\n[SCRAPING] Job {job_id} completed. Browser closed.\n")

@app.route('/v1/projects/<project_id>/scrape/prices', methods=['POST'])
def scrape_project_prices(project_id):
    """Legacy endpoint - redirect to main scraping"""
    return jsonify({
        "ok": True,
        "projectId": project_id,
        "message": "Use POST /v1/projects instead"
    })

@app.route('/v1/projects/<project_id>/scrape/reviews', methods=['POST'])
def scrape_project_reviews(project_id):
    """Reviews scraping - not implemented yet"""
    return jsonify({
        "ok": True,
        "projectId": project_id,
        "message": "Review scraping not implemented"
    })

@app.route('/scrape-prices', methods=['POST'])
def scrape_prices():
    """
    Scrape hotel prices for given hotels and date range.
    
    Request body:
    {
        "hotels": [
            {"name": "Hotel Name", "place_id": "ChIJ..."}
        ],
        "dates": {
            "start": "2025-12-22",
            "end": "2025-12-23"
        }
    }
    
    Returns:
    {
        "ok": true,
        "results": [
            {
                "hotel_id": "ChIJ...",
                "name": "Hotel Name",
                "prices": [
                    {"date": "2025-12-22", "price": "Rp 500.000", "booking_options": {...}},
                    {"date": "2025-12-23", "price": "Rp 550.000", "booking_options": {...}}
                ]
            }
        ]
    }
    """
    # Legacy endpoint disabled to avoid duplicate runs. Use POST /v1/projects instead.
    return jsonify({
        "ok": False,
        "error": "Endpoint deprecated. Use POST /v1/projects instead for scraping.",
        "code": "DEPRECATED_ENDPOINT"
    }), 410

if __name__ == '__main__':
    # Hugging Face Space uses port 7860
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
