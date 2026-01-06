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
from datetime import datetime

# Add parent directory to path to import scraped_prices
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

app = Flask(__name__)
CORS(app)

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
    try:
        # Import yang dibutuhkan
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from bs4 import BeautifulSoup
        from time import sleep
        from datetime import datetime as dt, timedelta
        from urllib.parse import quote
        import re
        
        data = request.get_json()
        hotels_input = data.get('hotels', [])
        
        # Fallback: jika masih pakai format lama (hotelIds array)
        if not hotels_input and data.get('hotelIds'):
            hotels_input = [{"hotelId": hid, "hotelName": None} for hid in data.get('hotelIds', [])]
        
        if not hotels_input:
            return jsonify({"ok": False, "error": "hotels array required with hotelId and hotelName"}), 400
        
        date_range = data.get('range', {})
        start_str = date_range.get('start', datetime.now().strftime('%Y-%m-%d'))
        end_str = date_range.get('end', start_str)
        
        print(f"\n{'='*60}")
        print(f"[SCRAPING] Starting scraping session")
        print(f"[SCRAPING] Hotels count: {len(hotels_input)}")
        print(f"[SCRAPING] Date Range: {start_str} to {end_str}")
        print(f"{'='*60}\n")
        
        # Generate date list
        start = dt.strptime(start_str, '%Y-%m-%d')
        end = dt.strptime(end_str, '%Y-%m-%d')
        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        
        print(f"[SCRAPING] Total dates to scrape: {len(dates)}")
        print(f"[SCRAPING] Dates: {dates}\n")
        
        # Setup Chrome - HEADLESS dengan anti-detection
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        results = []
        
        try:
            # SCRAPE EACH HOTEL
            for hotel_obj in hotels_input:
                hotel_id = hotel_obj.get('hotelId')
                hotel_name = hotel_obj.get('hotelName')
                
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
                    sleep(4)
                    
                    # ✅ STEP 2: CLICK/PILIH HOTEL YANG BENAR dari hasil pencarian
                    print(f"[STEP 2] Selecting hotel from search results...")
                    soup = BeautifulSoup(driver.page_source, "lxml")
                    hotel_cards = soup.find_all("div", class_="BcKagd")
                    
                    hotel_selected = False
                    if hotel_cards:
                        for hotel in hotel_cards:
                            name_elem = hotel.find("h2", class_="BgYkof")
                            if name_elem and hotel_name.lower() in name_elem.text.lower():
                                link = hotel.find("a", class_="PVOOXe")
                                if link:
                                    driver.get("https://www.google.com" + link["href"])
                                    hotel_selected = True
                                    print(f"✓ Hotel selected: {name_elem.text}")
                                    sleep(3)
                                    break
                        
                        # Fallback: klik yang pertama jika tidak ada exact match
                        if not hotel_selected and hotel_cards:
                            first_link = hotel_cards[0].find("a", class_="PVOOXe")
                            if first_link:
                                driver.get("https://www.google.com" + first_link["href"])
                                hotel_selected = True
                                print(f"✓ Selected first hotel (fallback)")
                                sleep(3)
                    
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
                
                # ✅ STEP 3: SEKARANG BARU SCRAPE EACH DATE (hotel sudah dipilih)
                for date_str in dates:
                    print(f"\n[DATE] Scraping date: {date_str}")
                    
                    try:
                        checkout = dt.strptime(date_str, '%Y-%m-%d') + timedelta(days=1)
                        checkout_str = checkout.strftime('%Y-%m-%d')
                        
                        # ✅ UPDATE TANGGAL di halaman hotel yang sudah terbuka
                        # CARA LEBIH RELIABLE: Update URL langsung dengan query parameter
                        print(f"[STEP 3] Updating dates to {date_str} - {checkout_str}")
                        
                        try:
                            # Method 1: Update URL langsung (paling reliable!)
                            current_url = driver.current_url
                            
                            # Parse dan update dates di URL
                            if 'dates=' in current_url:
                                # Replace existing dates
                                import re as regex_module
                                new_url = regex_module.sub(
                                    r'dates=[\d-]+,[\d-]+', 
                                    f'dates={date_str},{checkout_str}',
                                    current_url
                                )
                            else:
                                # Add dates parameter
                                separator = '&' if '?' in current_url else '?'
                                new_url = f"{current_url}{separator}dates={date_str},{checkout_str}"
                            
                            if new_url != current_url:
                                print(f"[UPDATE URL] {new_url}")
                                driver.get(new_url)
                                sleep(4)  # Tunggu page load
                            else:
                                # Fallback: Coba klik date picker (method lama)
                                print(f"[FALLBACK] Using date picker...")
                                date_picker = driver.find_element(By.CSS_SELECTOR, "div.FMXxAd.P0TvEc")
                                driver.execute_script("arguments[0].click();", date_picker)
                                sleep(2)
                                
                                # Pilih tanggal check-in dan check-out dengan JavaScript
                                driver.execute_script(f"""
                                    const checkinDate = "{date_str}";
                                    const checkoutDate = "{checkout_str}";
                                    
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
                                    }}, 500);
                                """)
                                sleep(2)
                                
                                # Klik Done button
                                done_buttons = driver.find_elements(By.CSS_SELECTOR, "div.VfPpkd-RLmnJb")
                                for btn in done_buttons:
                                    if "Done" in btn.text or btn.is_displayed():
                                        driver.execute_script("arguments[0].click();", btn)
                                        break
                                sleep(3)
                            
                        except Exception as date_error:
                            print(f"[WARNING] Date update failed: {date_error}, continuing anyway...")
                            sleep(2)
                        
                        # ✅ EXTRACT PRICE - Multiple methods dengan priority
                        price_found = 0
                        method_used = None
                        
                        # METODE 1: CSS Selector class "qQOQpe prxS3d" (harga utama di detail hotel)
                        try:
                            price_elem = driver.find_element(By.CSS_SELECTOR, "span.qQOQpe.prxS3d")
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
                        
                        # ✅ Extract rating & reviewsCount once per hotel (use first date page)
                        if hotel_result.get("rating") is None or hotel_result.get("reviewsCount") is None:
                            def parse_reviews_count(raw: str):
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

                            soup = BeautifulSoup(driver.page_source, "lxml")
                            rating_span = soup.find("span", class_="KFi5wf lA0BZ")
                            if rating_span and rating_span.text:
                                try:
                                    hotel_result["rating"] = float(
                                        rating_span.text.strip().replace(",", ".")
                                    )
                                except:
                                    pass

                            reviews_precise = soup.select_one("span.P2NYOe.GFm7je.sSHqwe")
                            if reviews_precise and reviews_precise.text:
                                parsed = parse_reviews_count(reviews_precise.text)
                                if parsed:
                                    hotel_result["reviewsCount"] = parsed
                            if hotel_result["reviewsCount"] is None:
                                reviews_elem = soup.find("span", class_="jdzyld")
                                if reviews_elem and reviews_elem.text:
                                    parsed = parse_reviews_count(reviews_elem.text)
                                    if parsed:
                                        hotel_result["reviewsCount"] = parsed

                        print(f"[RESULT] Price: {price_found} | Method: {method_used}")
                        
                        hotel_result["prices"].append({
                            "date": date_str,
                            "price": price_found,
                            "method": method_used,
                            "error": None if price_found > 0 else "No price found"
                        })
                        
                    except Exception as e:
                        print(f"[ERROR] Scraping failed for {date_str}: {e}")
                        hotel_result["prices"].append({
                            "date": date_str,
                            "price": 0,
                            "method": None,
                            "error": str(e)
                        })
                
                results.append(hotel_result)
                print(f"\n[HOTEL] Finished hotel {hotel_name}: {len(hotel_result['prices'])} prices scraped")
        
        finally:
            driver.quit()
            print(f"\n[SCRAPING] Session completed. Browser closed.\n")
        
        project_id = f"manual_{int(datetime.now().timestamp())}"
        
        return jsonify({
            "ok": True,
            "projectId": project_id,
            "dateRange": {"start": start_str, "end": end_str},
            "hotels": results
        })
        
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}\n")
        import traceback
        traceback.print_exc()
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500

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
    try:
        data = request.get_json()
        hotels = data.get('hotels', [])
        dates = data.get('dates', {})
        
        if not hotels:
            return jsonify({"ok": False, "error": "No hotels provided"}), 400
        
        if not dates.get('start') or not dates.get('end'):
            return jsonify({"ok": False, "error": "Missing start/end dates"}), 400
        
        # Import scraper functions
        from scraped_prices import (
            get_hotel_url,
            click_matching_hotel,
            extract_hotel_data,
            update_hotel_dates
        )
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from time import sleep
        from datetime import datetime as dt, timedelta
        
        # Generate list of dates to scrape
        start_date = dt.strptime(dates['start'], '%Y-%m-%d')
        end_date = dt.strptime(dates['end'], '%Y-%m-%d')
        
        date_list = []
        current = start_date
        while current <= end_date:
            date_list.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        
        # Setup Chrome driver
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        driver = webdriver.Chrome(options=chrome_options)
        driver.implicitly_wait(10)
        
        results = []
        
        try:
            # Convert hotels list to lookup dict
            hotel_lookup = {h['name'].lower(): h for h in hotels}
            
            # Iterate through each hotel
            for hotel in hotels:
                hotel_result = {
                    "hotel_id": hotel.get('place_id', 'N/A'),
                    "name": hotel.get('name', 'N/A'),
                    "prices": []
                }
                
                # Iterate through each date in the range
                for date_str in date_list:
                    try:
                        # Calculate checkout date (next day)
                        checkin = dt.strptime(date_str, '%Y-%m-%d')
                        checkout = checkin + timedelta(days=1)
                        checkout_str = checkout.strftime('%Y-%m-%d')
                        
                        # Get hotel page
                        url = get_hotel_url(
                            hotel['name'],
                            checkin_date=date_str,
                            checkout_date=checkout_str
                        )
                        driver.get(url)
                        sleep(3)
                        
                        # Click matching hotel
                        if click_matching_hotel(driver, hotel['name']):
                            sleep(2)
                            
                            # Update dates
                            update_hotel_dates(driver, date_str, checkout_str)
                            sleep(2)
                            
                            # Extract data
                            hotel_data = extract_hotel_data(driver, hotel['name'], hotel_lookup)
                            
                            if hotel_data:
                                # Parse price if it's a string
                                price = hotel_data.get('Price', 'N/A')
                                price_value = 'N/A'
                                
                                if isinstance(price, str) and price != 'N/A':
                                    # Convert "Rp 500.000" to float
                                    try:
                                        price_value = float(price.replace('Rp', '').replace('.', '').replace(',', '').strip())
                                    except:
                                        price_value = price
                                else:
                                    price_value = price
                                
                                hotel_result["prices"].append({
                                    "date": date_str,
                                    "price": price_value,
                                    "booking_options": hotel_data.get('Booking_Options', {})
                                })
                        
                    except Exception as e:
                        print(f"Error scraping {hotel['name']} on {date_str}: {str(e)}")
                        hotel_result["prices"].append({
                            "date": date_str,
                            "price": "N/A",
                            "error": str(e)
                        })
                
                results.append(hotel_result)
                
        finally:
            driver.quit()
        
        return jsonify({
            "ok": True,
            "scraped_at": datetime.now().isoformat(),
            "total_hotels": len(hotels),
            "total_dates": len(date_list),
            "date_range": f"{dates['start']} to {dates['end']}",
            "results": results
        })
        
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500

if __name__ == '__main__':
    # Hugging Face Space uses port 7860
    port = int(os.environ.get('PORT', 7860))
    app.run(host='0.0.0.0', port=port, debug=False)
