import time
import traceback
import re
import random
import json
import pandas as pd
import csv
import pandas as pd  
from pathlib import Path  
from difflib import SequenceMatcher
from bs4 import BeautifulSoup   # type: ignore
from urllib.parse import quote  
from selenium import webdriver   # type: ignore
from selenium.webdriver.common.keys import Keys   # type: ignore
from selenium.webdriver.common.by import By   # type: ignore
from selenium.webdriver.support.ui import WebDriverWait   # type: ignore
from selenium.webdriver.support import expected_conditions as EC   # type: ignore
from selenium.common.exceptions import (   # type: ignore
    NoSuchElementException,   
    TimeoutException,   
    WebDriverException  
)  
from selenium.webdriver.common.action_chains import ActionChains  # type: ignore
from time import sleep
from datetime import datetime, timedelta
from textblob import TextBlob # type: ignore
from googletrans import Translator # type: ignore
from html.parser import HTMLParser
import re
from tenacity import retry, stop_after_attempt, wait_exponential

def get_hotel_url(hotel_name, checkin_date=None, checkout_date=None):
    """
    Generate search URL for specific hotel with optional dates
    
    Args:
        hotel_name: Nama hotel
        checkin_date: Tanggal checkin (datetime object or YYYY-MM-DD string)
        checkout_date: Tanggal checkout (datetime object or YYYY-MM-DD string)
    """
    # Default ke hari ini dan besok jika tanggal tidak dispecify
    if not checkin_date:
        checkin_date = datetime.now()
    if not checkout_date:
        checkout_date = checkin_date + timedelta(days=1)
        
    # Convert ke string jika input berupa datetime
    if isinstance(checkin_date, datetime):
        checkin_date = checkin_date.strftime("%Y-%m-%d")
    if isinstance(checkout_date, datetime):
        checkout_date = checkout_date.strftime("%Y-%m-%d")
        
    # Build URL
    encoded_name = quote(f"{hotel_name}")
    base_url = f"https://www.google.com/travel/search?q={encoded_name}"
    date_params = f"&dates={checkin_date},{checkout_date}"
    
    return base_url + date_params 

def update_hotel_dates(driver, new_checkin_date, new_checkout_date, max_attempts=3):
    """
    Update tanggal check-in dan check-out di halaman detail hotel
    dengan mengklik kalender dan memilih tanggal - dengan multiple attempt
    
    Args:
        driver: WebDriver instance
        new_checkin_date: Tanggal check-in baru (format: "YYYY-MM-DD")
        new_checkout_date: Tanggal check-out baru (format: "YYYY-MM-DD")
        max_attempts: Jumlah maksimum percobaan
    
    Returns:
        bool: True jika berhasil, False jika gagal
    """
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"[Attempt {attempt}/{max_attempts}] Updating dates: Check-in {new_checkin_date}, Check-out {new_checkout_date}")
            
            # 1. Coba beberapa metode untuk membuka date picker
            date_picker_opened = False
            
            # Metode 1: Cari tombol/div yang membuka date picker
            try:
                date_pickers = driver.find_elements(By.CSS_SELECTOR, "div.FMXxAd.P0TvEc")
                
                if date_pickers and len(date_pickers) > 0:
                    for picker in date_pickers:
                        if picker.is_displayed():
                            driver.execute_script("arguments[0].click();", picker)
                            print("✓ Clicked date picker to open calendar")
                            time.sleep(3)  # Penting! Tambahkan delay setelah klik
                            date_picker_opened = True
                            break
            except Exception as e:
                print(f"Method 1 failed: {str(e)}")
                
            # Metode 2: Coba klik input tanggal langsung
            if not date_picker_opened:
                try:
                    date_inputs = driver.find_elements(By.CSS_SELECTOR, "input.TP4Lpb.eoY5cb")
                    if date_inputs and len(date_inputs) > 0:
                        for input_field in date_inputs:
                            if input_field.is_displayed():
                                driver.execute_script("arguments[0].click();", input_field)
                                print("✓ Clicked date input field to open calendar")
                                time.sleep(3)  # Penting! Tambahkan delay setelah klik
                                date_picker_opened = True
                                break
                except Exception as e:
                    print(f"Method 2 failed: {str(e)}")
            
            # Metode 3: Klik area tanggal dengan JavaScript
            if not date_picker_opened:
                try:
                    driver.execute_script("""
                        // Cari elemen dengan tanggal atau date picker
                        const dateElements = document.querySelectorAll('div.FMXxAd, div.TP4Lpb, div[role="button"]');
                        for (const el of dateElements) {
                            if (el.textContent.includes('/') || el.textContent.includes('-')) {
                                el.click();
                                return true;
                            }
                        }
                        return false;
                    """)
                    print("✓ Tried JavaScript method to open calendar")
                    time.sleep(3)  # Penting! Tambahkan delay setelah klik
                    date_picker_opened = True
                except Exception as e:
                    print(f"Method 3 failed: {str(e)}")
                
            if not date_picker_opened:
                print(f"× Failed to open date picker on attempt {attempt}")
                if attempt < max_attempts:
                    print("Refreshing page and trying again...")
                    driver.refresh()
                    time.sleep(5)
                    continue
                else:
                    return False
                
            # 2. Tunggu kalender muncul dengan multiple approaches
            calendar_found = False
            calendar_selectors = [
                "div[role='grid']", 
                "div[role='dialog']", 
                "div.UYJibd",
                "table.CalendarTable"
            ]
            
            for selector in calendar_selectors:
                try:
                    wait = WebDriverWait(driver, 5)
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    print(f"✓ Calendar found with selector: {selector}")
                    calendar_found = True
                    break
                except Exception:
                    continue
            
            if not calendar_found:
                print(f"× Calendar not found on attempt {attempt}")
                if attempt < max_attempts:
                    print("Refreshing page and trying again...")
                    driver.refresh()
                    time.sleep(5)
                    continue
                else:
                    return False
            
            # 3. Parse dan manipulasi tanggal untuk mencari dengan lebih fleksibel
            checkin_dt = datetime.strptime(new_checkin_date, "%Y-%m-%d")
            checkout_dt = datetime.strptime(new_checkout_date, "%Y-%m-%d")
            
            checkin_day = checkin_dt.day
            checkout_day = checkout_dt.day
            
            # 4. Coba implementasi JavaScript untuk memilih tanggal
            try:
                dates_selected = driver.execute_script(f"""
                    // Format tanggal untuk perbandingan
                    const checkinDate = "{new_checkin_date}";
                    const checkoutDate = "{new_checkout_date}";
                    const checkinDay = {checkin_day};
                    const checkoutDay = {checkout_day};
                    
                    // Cari semua sel tanggal
                    let allDates = document.querySelectorAll('div[data-iso], td[data-date], div[role="button"][aria-label*="day"], div[role="gridcell"]');
                    let checkinSelected = false;
                    let checkoutSelected = false;
                    
                    // Untuk setiap sel, coba temukan yang cocok
                    for (const dateCell of allDates) {{
                        // Cek apakah ini adalah tanggal checkin
                        if (!checkinSelected) {{
                            if (dateCell.getAttribute('data-iso') === checkinDate || 
                                dateCell.getAttribute('data-date') === checkinDate ||
                                dateCell.getAttribute('aria-label')?.includes(checkinDay) ||
                                (dateCell.textContent == checkinDay && dateCell.getAttribute('aria-disabled') !== 'true')) {{
                                    dateCell.click();
                                    checkinSelected = true;
                                    console.log('Check-in date selected');
                                    // Wait a bit before selecting checkout
                                    setTimeout(() => {{}}, 1000);
                                    continue;
                            }}
                        }}
                        
                        // Lalu cek apakah ini adalah tanggal checkout
                        if (checkinSelected && !checkoutSelected) {{
                            if (dateCell.getAttribute('data-iso') === checkoutDate || 
                                dateCell.getAttribute('data-date') === checkoutDate ||
                                dateCell.getAttribute('aria-label')?.includes(checkoutDay) ||
                                (dateCell.textContent == checkoutDay && dateCell.getAttribute('aria-disabled') !== 'true')) {{
                                    dateCell.click();
                                    checkoutSelected = true;
                                    console.log('Check-out date selected');
                                    break;
                            }}
                        }}
                    }}
                    
                    return {{checkinSelected, checkoutSelected}};
                """)
                
                print(f"JavaScript selection results: {dates_selected}")
                
                # Jika kedua tanggal dipilih, klik Done
                if dates_selected and dates_selected.get('checkinSelected') and dates_selected.get('checkoutSelected'):
                    print("✓ Both dates selected via JavaScript")
                    
                    # PERBAIKAN: Tunggu sejenak setelah memilih tanggal
                    time.sleep(2)
                    
                    # 5. Klik tombol DONE dengan lebih agresif
                    done_clicked = False
                    
                    # PERBAIKAN: Tambahkan lebih banyak selector untuk Done button
                    done_selectors = [
                        "div.VfPpkd-RLmnJb",
                        "button:contains('Done')",
                        "button.done-button",
                        "button.confirm-button",
                        "div[role='button']:contains('Done')",
                        "div.VfPpkd-dgl2Hf-ppHlrf-sM5MNb button",
                        ".VfPpkd-LgbsSe",
                        "div[data-mdc-dialog-action='accept']"
                    ]
                    
                    for selector in done_selectors:
                        try:
                            result = driver.execute_script(f"""
                                const doneButtons = document.querySelectorAll('{selector}');
                                for (const button of doneButtons) {{
                                    if (button.innerText.includes('Done') || 
                                        button.textContent.includes('Done') ||
                                        button.getAttribute('data-mdc-dialog-action') === 'accept') {{
                                        console.log("Found Done button:", button);
                                        button.click();
                                        return true;
                                    }}
                                }}
                                return false;
                            """)
                            
                            if result:
                                print(f"✓ Clicked DONE button via JavaScript using selector: {selector}")
                                done_clicked = True
                                # PERBAIKAN: Tambahkan delay lebih lama setelah klik Done
                                time.sleep(8)
                                break
                        except Exception as e:
                            print(f"Failed to click done with selector {selector}: {str(e)}")
                            continue
                    
                    # PERBAIKAN: Coba metode lain jika semua selectors di atas gagal
                    if not done_clicked:
                        try:
                            # Metode tekanan tombol Escape
                            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
                            print("✓ Pressed ESC key to close calendar")
                            time.sleep(5)
                            done_clicked = True
                        except Exception as e:
                            print(f"ESC method failed: {str(e)}")
                    
                    # Jika Done button tidak ditemukan, klik area lain
                    if not done_clicked:
                        try:
                            # Klik area lain
                            driver.execute_script("document.querySelector('h2') && document.querySelector('h2').click();")
                            print("✓ Clicked elsewhere to close calendar")
                            time.sleep(5)
                            done_clicked = True
                        except Exception as e:
                            print(f"× Failed to close calendar: {str(e)}")
                    
                    # PERBAIKAN: Periksa jika kalender ditutup berhasil
                    try:
                        # Periksa kalender sudah tidak ada
                        calendar_closed = True
                        for selector in calendar_selectors:
                            try:
                                calendar_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                                visible_calendars = [cal for cal in calendar_elements if cal.is_displayed()]
                                if len(visible_calendars) > 0:
                                    calendar_closed = False
                                    break
                            except:
                                continue
                        
                        if calendar_closed:
                            print("✓ Calendar successfully closed")
                            return True
                        else:
                            print("× Calendar might still be open, but continuing...")
                            # Return true anyway since dates were selected
                            return True
                    except Exception as e:
                        print(f"Error checking calendar status: {str(e)}")
                        # Return true since dates were selected even if we can't confirm calendar closed
                        return True
                else:
                    print(f"× Failed to select dates via JavaScript on attempt {attempt}")
            except Exception as js_error:
                print(f"JavaScript date selection error: {str(js_error)}")
                
            # 6. Jika masih gagal dan ini bukan percobaan terakhir, mulai dari awal
            if attempt < max_attempts:
                print("Refreshing page and trying again...")
                driver.refresh()
                time.sleep(5)
            else:
                return False
                
        except Exception as e:
            print(f"Error updating dates: {str(e)}")
            if attempt < max_attempts:
                print("Refreshing page and trying again...")
                driver.refresh()
                time.sleep(5)
            else:
                return False
                
    return False
    
def get_original_text(html_content):
    """
    Extract teks asli dari review Google menggunakan struktur HTML spesifik
    dari halaman reviews Google Travel/Maps
    """
    if not html_content:
        return ""
    
    try:
        # SOLUSI 1: Ekstrak menggunakan regex dengan pattern yang SANGAT spesifik
        pattern = r'\(Original\)<br[^>]*>(.*?)(?=</span>|$)'
        matches = re.search(pattern, html_content, re.DOTALL)
        if matches and matches.group(1):
            return matches.group(1).strip()
        
        # SOLUSI 2: Pemecahan string yang tepat berdasarkan struktur HTML
        if "<br>(Original)<br>" in html_content:
            parts = html_content.split("<br>(Original)<br>")
            if len(parts) > 1:
                raw_text = parts[1].split("</span>")[0]
                return raw_text.strip()
        
        # SOLUSI 3: Gunakan BeautifulSoup dengan navigasi yang tepat
        soup = BeautifulSoup(html_content, 'lxml')
        span_content = soup.find('span')
        
        if span_content and "(Original)" in span_content.text:
            # Ambil konten setelah "(Original)"
            original_text = span_content.text.split("(Original)")[-1].strip()
            return original_text
        
        # SOLUSI 4: Pendekatan dengan manipulasi DOM untuk kasus khusus
        if "<br>" in html_content:
            # Split berdasarkan <br>
            parts = html_content.split("<br>")
            
            # Jika ada minimal 3 bagian (2 <br>), ambil yang terakhir
            if len(parts) >= 3:
                # Cari index elemen setelah "(Original)"
                for i, part in enumerate(parts):
                    if "(Original)" in part:
                        # Ambil bagian setelahnya jika ada
                        if i+1 < len(parts):
                            return parts[i+1].split("</span>")[0].strip()
        
        # SOLUSI 5: Ekstraksi paling dasar - langsung dari struktur index.html
        if "<span>" in html_content and "</span>" in html_content:
            full_text = html_content.replace("<div>", "").replace("</div>", "")
            full_text = full_text.replace("<span>", "").replace("</span>", "")
            
            # Jika ada (Original), ambil teks setelahnya
            if "(Original)" in full_text:
                text_parts = full_text.split("(Original)")
                if len(text_parts) > 1:
                    return text_parts[1].replace("<br>", "").replace("<br/>", "").strip()
            
            # Jika tidak ada (Original) dan tidak ada (Translated by Google)
            # kemungkinan review sudah dalam bahasa asli
            elif "(Translated by Google)" not in full_text:
                return full_text.replace("<br>", " ").strip()
        
        # SOLUSI 6: Untuk kasus ekstrim jika masih gagal        
        class MLStripper(HTMLParser):
            def __init__(self):
                super().__init__()
                self.reset()
                self.strict = False
                self.convert_charrefs = True
                self.text = []
            
            def handle_data(self, d):
                self.text.append(d)
            
            def get_data(self):
                return ''.join(self.text)
        
        stripper = MLStripper()
        stripper.feed(html_content)
        full_text = stripper.get_data()
        
        # Jika ada "(Original)", ambil teks setelahnya
        if "(Original)" in full_text:
            return full_text.split("(Original)")[-1].strip()
        
        # Jika tidak ada "(Original)" tapi ada "(Translated by Google)",
        # ambil teks sebelum "(Translated by Google)"
        if "(Translated by Google)" in full_text:
            return full_text.replace("(Translated by Google)", "").strip()
            
        # Fallback ke full text jika tidak ada kondisi terpenuhi
        return full_text.strip()
        
    except Exception as e:
        print(f"Error extracting original text: {str(e)}")
        # Fallback paling aman
        return html_content.replace("<br>", " ").replace("<div>", "").replace("</div>", "").replace("<span>", "").replace("</span>", "")

def clean_review_text(text):
    """Helper function untuk membersihkan text review"""
    if not text:
        return ""
        
    # Hapus translated marker
    text = re.sub(r'^\(Translated by Google\)\s*', '', text)
    
    # Hapus original marker
    text = re.sub(r'\(Original\)', '', text)
    
    # Hapus "Read more" dan "..." di akhir
    text = re.sub(r'(?:Read more|\.\.\.).*$', '', text, flags=re.IGNORECASE)
    
    # Hapus semua tag HTML
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Hapus multiple newlines/spaces
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def extract_reviews(driver, max_reviews=10):
    """
    Extract hotel reviews from Google Travel
    
    Args:
        driver: WebDriver instance
        max_reviews: Maximum number of reviews to extract (default: 10)
        
    Returns:
        List of reviews with details
    """
    reviews_data = []
    
    try:
        # 1. Click Reviews tab dengan multiple approaches
        try:
            print("Attempting to navigate to Reviews tab...")
            # List of possible selectors for Reviews tab
            selectors = [
                "//div[@class='iWSGZb kaAt2' and @id='reviews']",
                "//div[contains(@class, 'iWSGZb') and @role='tab' and .//span[text()='Reviews']]",
                "//div[@role='tab' and @id='reviews']",
                "//div[contains(@class, 'kaAt2') and .//span[contains(text(), 'Reviews')]]",
                "//div[contains(text(), 'Reviews') and @role='tab']",
                "//span[text()='Reviews']/parent::div[@role='tab']"
            ]
            
            tab_clicked = False
            for selector in selectors:
                try:
                    reviews_tab = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    driver.execute_script("arguments[0].click();", reviews_tab)
                    print("Successfully clicked Reviews tab")
                    tab_clicked = True
                    time.sleep(3)
                    break
                except Exception as e:
                    print(f"Failed with selector {selector}: {str(e)}")
                    continue
            
            # Alternative approach if XPATH selectors fail
            if not tab_clicked:
                try:
                    print("Trying JavaScript approach to find Reviews tab...")
                    driver.execute_script("""
                        const tabs = document.querySelectorAll('[role="tab"]');
                        for (const tab of tabs) {
                            if (tab.textContent.includes('Reviews')) {
                                tab.click();
                                return true;
                            }
                        }
                        return false;
                    """)
                    tab_clicked = True
                    time.sleep(3)
                except Exception as e:
                    print(f"JavaScript tab click failed: {str(e)}")
            
            # Verify we're on Reviews tab
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.Svr5cf"))
                )
                print("Verified on Reviews tab")
            except:
                if not tab_clicked:
                    print("Failed to verify Reviews tab, trying to continue anyway")
                    
        except Exception as e:
            print(f"Error navigating to Reviews tab: {str(e)}")
            return reviews_data

        # 2. Sort by Most Recent - multiple attempts
        sort_success = False
        max_sort_attempts = 3
        
        for sort_attempt in range(1, max_sort_attempts + 1):
            try:
                print(f"Sort attempt {sort_attempt}/{max_sort_attempts}")
                
                # Find the sort dropdown
                dropdown_selectors = [
                    '//div[@class="MocG8c o7IkCf LMgvRb KKjvXb"]',
                    '//div[contains(@class, "MocG8c") and contains(@class, "KKjvXb")]',
                    '//div[@role="button" and contains(@class, "MocG8c")]',
                    '//div[contains(@aria-label, "Sort reviews") and @role="button"]',
                    '//div[@role="button" and contains(@class, "VfPpkd")]'
                ]
                
                dropdown = None
                for selector in dropdown_selectors:
                    try:
                        dropdown_elements = driver.find_elements(By.XPATH, selector)
                        for element in dropdown_elements:
                            if element.is_displayed():
                                dropdown = element
                                break
                        if dropdown:
                            break
                    except:
                        continue
                
                # If standard selectors failed, try to find it using JavaScript
                if not dropdown:
                    try:
                        print("Trying JavaScript to find sort dropdown...")
                        driver.execute_script("""
                            const buttons = document.querySelectorAll('[role="button"]');
                            for (const button of buttons) {
                                if (button.getAttribute('aria-haspopup') === 'menu' || 
                                    button.getAttribute('aria-haspopup') === 'true') {
                                    button.click();
                                    return true;
                                }
                            }
                            return false;
                        """)
                        time.sleep(2)
                    except Exception as e:
                        print(f"JavaScript dropdown click failed: {str(e)}")
                else:
                    try:
                        # Click the dropdown
                        driver.execute_script("arguments[0].click();", dropdown)
                        time.sleep(2)
                    except Exception as e:
                        print(f"Failed to click dropdown: {str(e)}")
                
                # Try to select "Most recent" from the dropdown
                try:
                    # Try multiple selectors to find the "Most recent" option
                    most_recent_selectors = [
                        '//div[@data-value="2"][@role="option"]',
                        '//div[contains(@aria-label, "Most recent")][@role="option"]',
                        '//div[@class="MocG8c o7IkCf LMgvRb" and @data-value="2"]',
                        '//div[@role="option" and contains(., "Most recent")]',
                        '//div[@role="menuitem" and contains(., "Most recent")]'
                    ]
                    
                    for selector in most_recent_selectors:
                        try:
                            most_recent_elements = driver.find_elements(By.XPATH, selector)
                            for element in most_recent_elements:
                                if element.is_displayed():
                                    driver.execute_script("arguments[0].click();", element)
                                    sort_success = True
                                    print("Clicked 'Most recent' option")
                                    time.sleep(3)
                                    break
                            if sort_success:
                                break
                        except:
                            continue
                 
                except Exception as e:
                    print(f"Error selecting Most recent: {str(e)}")
                
                if sort_success:
                    print("Successfully sorted by most recent")
                    break
                else:
                    print(f"Sort attempt {sort_attempt} failed, trying again...")
                    time.sleep(1)
                    
            except Exception as e:
                print(f"Error in sort handling: {str(e)}")
                time.sleep(1)
        
        if not sort_success:
            print("Warning: Reviews may not be sorted by most recent")

        # 3. Wait for reviews to load
        print("Waiting for reviews container...")
        last_review_count = 0
        scroll_attempts = 0
        max_scroll_attempts = 10

        while len(reviews_data) < max_reviews and scroll_attempts < max_scroll_attempts:
            # Get current reviews
            reviews_containers = driver.find_elements(By.CSS_SELECTOR, "div[jsname='Pa5DKe']")
            reviews = []
            for container in reviews_containers:
                reviews.extend(container.find_elements(By.CSS_SELECTOR, "div.Svr5cf.bKhjM"))

            for review in reviews[last_review_count:]:
                if len(reviews_data) >= max_reviews:
                    break
                    
                try:
                    # PENTING: Inisialisasi text sebagai None di awal setiap iterasi
                    text = None
                    
                    # Get review text
                    try: 
                        expanded_divs = review.find_elements(By.CSS_SELECTOR, "div[jsname='NwoMSd']")
                        if expanded_divs and len(expanded_divs) > 0:
                            # Ambil div yang pertama
                            expanded_div = expanded_divs[0]
                            
                            # Cari K7oBsc span di dalamnya
                            text_elem = expanded_div.find_element(By.CSS_SELECTOR, "div.K7oBsc span")
                            html_content = text_elem.get_attribute('innerHTML')
                            
                            # Dapatkan text asli menggunakan fungsi get_original_text
                            text = get_original_text(html_content)
                        else:
                            # Fallback ke seluruh review container jika tidak ada expanded view
                            k7o_elements = review.find_elements(By.CSS_SELECTOR, "div.K7oBsc span")
                            for k7o in k7o_elements:
                                html_content = k7o.get_attribute('innerHTML')
                                text = get_original_text(html_content)
                                if text and text.strip():
                                    break
                            
                            # Jika tidak ada text ditemukan setelah semua percobaan
                            if not text or not text.strip():
                                print(f"Skipping review: No text found")
                                continue
                        
                        # Bersihkan text
                        text = clean_review_text(text)
                        
                        # Skip jika text kosong SETELAH dibersihkan
                        if not text or not text.strip():
                            print(f"Skipping review: Empty text after cleaning")
                            continue

                    except NoSuchElementException:
                        print(f"Skipping review: Element not found")
                        continue

                    # Get reviewer name
                    name = review.find_element(By.CSS_SELECTOR, "a.DHIhE.QB2Jof").text
                    
                    # Get date
                    date = review.find_element(By.CSS_SELECTOR, "span.iUtr1.CQYfx").text
                    
                    # Get rating 
                    rating = review.find_element(By.CSS_SELECTOR, "div.GDWaad").text.split('/')[0]
                    
                    # Verifikasi final: pastikan text tidak kosong
                    if text and text.strip():
                        reviews_data.append({
                            'reviewer': name,
                            'date': date,
                            'rating': rating,
                            'text': text
                        })
                        print(f"Extracted review {len(reviews_data)}/{max_reviews}: '{text[:30]}...'")
                    else:
                        print(f"Skipping review from {name}: Empty text")

                except Exception as e:
                    print(f"Error extracting review details: {e}")
                    continue

            # Update count of processed reviews
            last_review_count = len(reviews)

            if len(reviews_data) < max_reviews:
                try:
                    # Scroll smooth dengan JavaScript
                    last_review = reviews[-1]
                    driver.execute_script("""
                        arguments[0].scrollIntoView({ 
                            behavior: 'smooth', 
                            block: 'end' 
                        });
                    """, last_review)
                    
                    # Tunggu scroll selesai dan content load
                    time.sleep(3)
                    
                    # Check if new reviews loaded
                    new_reviews = driver.find_elements(By.CSS_SELECTOR, "div.Svr5cf.bKhjM")
                    if len(new_reviews) <= last_review_count:
                        scroll_attempts += 1
                        # Tambahan scroll untuk memastikan
                        driver.execute_script("window.scrollBy(0, 300);")
                        time.sleep(2)
                    else:
                        scroll_attempts = 0  # Reset jika dapat review baru
                        
                except Exception as e:
                    print(f"Error scrolling: {e}")
                    scroll_attempts += 1

            print(f"Current reviews: {len(reviews_data)}, Scroll attempts: {scroll_attempts}")

        print(f"\nExtracted {len(reviews_data)} reviews total")
        return reviews_data
    
    except Exception as e: 
        print(f"Error extracting reviews: {str(e)}")
        print(traceback.format_exc())
        return reviews_data


def save_to_csv(hotel_info, first_write=False):
    # Tidak perlu formatting lagi karena sudah diformat di extract_hotel_data
    columns = [
        "Name", "Category", "Price", "Rating", "Reviews_count",
        "Location", "Hotel_id", "Coordinate", "Contact", "Website", 
        "About", "Link", "Amenities", "Thumbnails", "Booking_Options"
    ]
    
    df = pd.DataFrame([hotel_info])
    df = df[columns]
    
    df.to_csv(
        "hotels_data_21-22_maret.csv",
        mode='w' if first_write else 'a',
        header=first_write,
        index=False,
        encoding='utf-8-sig',
        quoting=csv.QUOTE_MINIMAL
    )

def save_to_json(hotel_data, json_file="hotels_data_21-22_maret.json"):
    """Save hotel data to JSON file including reviews"""
    try:
        if Path(json_file).exists():
            with open(json_file, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
                hotels = existing_data.get('hotels', [])
        else:
            hotels = []
            
        # Add new hotel data with reviews
        hotels.append(hotel_data)
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump({
                'hotels': hotels,
                'metadata': {
                    'total_hotels': len(hotels),
                    # 'total_reviews': sum(len(h.get('Reviews', [])) for h in hotels),
                    'scraped_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            }, f, indent=2, ensure_ascii=False)
            
        return True
    except Exception as e:
        print(f"Error saving to JSON: {str(e)}")
        return False

def extract_hotel_data(driver, hotel_name, hotel_lookup):
    """Extract data hotel dari halaman detail"""
    try:
        # Tunggu halaman detail load
        wait = WebDriverWait(driver, 20)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "gJGKuf")))
        sleep(3)
        
        soup = BeautifulSoup(driver.page_source, "lxml")
        
        # Extract basic info
        name = soup.find("h2", class_="BgYkof")
        name = name.text if name else "N/A"
        
        price_hotels = soup.find("span", class_="qQOQpe prxS3d")
        price_hotels = price_hotels.text if price_hotels else "N/A" 
        
        rating = soup.find("span", class_="KFi5wf lA0BZ")
        rating = float(rating.text) if rating else "N/A"

        # Extract link hotel
        link_hotel = driver.current_url
        
        # Extract reviews with proper handling
        reviews_count = "N/A"
        reviews_elem = soup.find("span", class_="jdzyld")
        if reviews_elem:
            raw_text = reviews_elem.text.strip()
            # Bersihkan dari karakter () 
            reviews_count = raw_text.replace('(','').replace(')','').strip()
            
        # Extract category
        category_elem = soup.find("ol", class_="DIfNZc")
        category = category_elem.text.split('·')[0].strip() if category_elem else "N/A"
        
        # Extract location
        try:
            location = driver.find_element(By.XPATH, '//div[@class="K4nuhf"]/span[1]').text
        except:
            location = "N/A"

        # Extract contact
        try:
            contact = driver.find_element(By.XPATH, '//div[@class="K4nuhf"]/span[3]').text
            contact = contact.strip().replace('-', '').replace(' ', '')
        except:
            contact = ""

        about = ""
        about_paragraphs = []
        about_elements = soup.find_all("p", class_="GtAk2e")
        if about_elements:
            for elem in about_elements:
                # Ambil teks tanpa tombol "More"
                text = elem.text.split('…')[0].strip()
                if text:
                    about_paragraphs.append(text)
            about = ' '.join(about_paragraphs)
         
            
        # Extract website dengan multiple selectors
        website = "N/A"
        website_selectors = [
            (By.CSS_SELECTOR, '#overview a[href*="hotel"]'),
            (By.CSS_SELECTOR, '#overview a[href*="www"]'),
            (By.CSS_SELECTOR, '.lcr4fd'),
            (By.CSS_SELECTOR, 'a[data-track-type="hotel_website"]'),
            (By.XPATH, '//div[@id="overview"]//a[contains(@href, "http")]')
        ]
        
        for selector_type, selector in website_selectors:
            try:
                elements = driver.find_elements(selector_type, selector)
                for element in elements:
                    href = element.get_attribute("href")
                    if href and not href.startswith(("https://www.google.com", "javascript:")):
                        website = href
                        break
                if website != "N/A":
                    break
            except:
                continue
                
        # Extract amenities
        parent_categories = {
            'Internet': [],  
            'Food & drink': [],  
            'Policies & payments': [],  
            'Services': [],  
            'Pools': [],  
            'Parking & transportation': [],  
            'Wellness': [],  
            'Accessibility': [],  
            'Pets': [],  
            'Languages spoken': [],  
            'Rooms': [],
            'Bathrooms': [],
            'Activities': [],
            'Children': [],
            'Business & events': [],
            'Energy efficiency': [],
            'Waste reduction': [],
            'Water conservation': [],
            'Sustainable sourcing': []
        }

        # amenities
        amenities = {}
        current_parent = None
        amenity_elems = soup.find_all("span", class_="LtjZ2d")
        
        for amenity in amenity_elems:
            amenity_text = amenity.text.strip()
            
            # Check if this is a parent category
            if amenity_text in parent_categories:
                current_parent = amenity_text
                amenities[current_parent] = []  # Initialize empty list for children
                continue
                
            # Add child to current parent
            if current_parent and amenity_text:
                amenities[current_parent].append(amenity_text)
                
        # Extract thumbnails
        thumbnails = []
        thumbnail_elems = soup.find_all("img", class_="q5P4L")
        for thumb in thumbnail_elems:
            src = thumb.get('src') or thumb.get('data-src')
            if src:
                thumbnails.append(src)
                
        # Skip jika data penting tidak ada
        if all(x == "N/A" for x in [name, rating, location]):
            return None

        # Extract booking options
        booking_options = {}
        try:
            booking_elements = driver.find_elements(By.CSS_SELECTOR, "div.IJxDxc")
            
            for idx, element in enumerate(booking_elements, 1):
                try:
                    platform = element.find_element(By.CSS_SELECTOR, "span.FjC1We").text
                    if not platform:
                        continue

                    # Get price dengan multiple pendekatan
                    price = "N/A"
                    price_selectors = [".nDkDDb", ".MW1oTb", ".iqYCVb", ".UeIHqb"]
                    for selector in price_selectors:
                        try:
                            price_elem = element.find_element(By.CSS_SELECTOR, selector)
                            if price_elem and price_elem.text:
                                price = price_elem.text.strip()
                                break
                        except:
                            continue

                    # Get booking link
                    try:
                        link = element.find_element(By.CSS_SELECTOR, "a.hUGVEe").get_attribute("href")
                    except:
                        link = "N/A"

                    # Add to booking options dictionary
                    booking_options[f"Option_{idx}"] = {
                        "platform": platform,
                        "price": price,
                        "link": link
                    }

                except Exception as e:
                    print(f"Error extracting booking option: {str(e)}")
                    continue

        except Exception as e:
            print(f"Error in booking options extraction: {str(e)}")

        # Extract reviews
        # reviews_data = extract_reviews(driver, max_reviews=10)

        # Add hotel_id and coordinate from hotels_bandung_fixs.json
        hotel_id = "N/A"
        coordinate = {"lat": "N/A", "lng": "N/A"}
        
        # Try direct match first
        if hotel_name.lower() in hotel_lookup:
            matched_hotel = hotel_lookup[hotel_name.lower()]
            hotel_id = matched_hotel['place_id']
            coordinate = matched_hotel['location']
        else:
            # Try matching with extracted name
            extracted_name = name.lower()
            if extracted_name in hotel_lookup:
                matched_hotel = hotel_lookup[extracted_name]
                hotel_id = matched_hotel['place_id']
                coordinate = matched_hotel['location']
            else:
                # Try fuzzy matching as a last resort
                from difflib import SequenceMatcher
                
                def similar(a, b):
                    return SequenceMatcher(None, a.lower(), b.lower()).ratio()
                
                best_match = None
                best_score = 0
                for key, h in hotel_lookup.items():
                    score = similar(extracted_name, key)
                    if score > 0.8 and score > best_score:
                        best_score = score
                        best_match = h
                
                if best_match:
                    hotel_id = best_match['place_id']
                    coordinate = best_match['location']
                    print(f"Fuzzy matched: {name} with {best_match['name']}")
            
        return {
            "Name": name,
            "Price": price_hotels, 
            # "Rating": rating,
            # "Reviews_count": reviews_count, 
            # "Location": location,
            # "Contact": contact,
            # "Category": category,
            # "Website": website,
            # "About": about,
            # "Link": link_hotel,
            # "Amenities": amenities,
            # "Thumbnails": thumbnails,
            "Booking_Options": booking_options,
            "Hotel_id": hotel_id,  
            # "Coordinate": coordinate,
            # "Reviews": reviews_data
        }

    except Exception as e:
        print(f"Error extracting data: {str(e)}")
        return None

def click_matching_hotel(driver, hotel_name):
    """Click hotel dari hasil pencarian yang namanya paling cocok"""
    try:
        # Tunggu hasil pencarian muncul
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "BcKagd")))
        sleep(2)
        
        # Parse halaman dengan BeautifulSoup
        soup = BeautifulSoup(driver.page_source, "lxml")
        hotel_cards = soup.find_all("div", class_="BcKagd")
        
        if not hotel_cards:
            print(f"No results found for: {hotel_name}")
            return False
            
        # Cari hotel yang namanya paling cocok
        for hotel in hotel_cards:
            name_elem = hotel.find("h2", class_="BgYkof")
            if name_elem and hotel_name.lower() in name_elem.text.lower():
                try:
                    # Klik link hotel
                    link = hotel.find("a", class_="PVOOXe")
                    if link:
                        driver.get("https://www.google.com" + link["href"])
                        return True
                except:
                    continue
        
        # Jika tidak ada yang cocok, klik yang pertama
        try:
            first_link = hotel_cards[0].find("a", class_="PVOOXe")
            if first_link:
                driver.get("https://www.google.com" + first_link["href"])
                return True
        except:
            print(f"Failed to click first result for: {hotel_name}")
            return False
            
    except Exception as e:
        print(f"Error in click_matching_hotel: {str(e)}")
        return False

def main():  
    # Konfigurasi Chrome Options  
    options = webdriver.ChromeOptions()  
    options.add_argument('--start-maximized')  
    options.add_argument('--disable-gpu')  
    options.add_argument('--no-sandbox')  
    options.add_argument('--disable-dev-shm-usage')  
    options.add_argument('--disable-blink-features=AutomationControlled')  
    options.add_experimental_option('excludeSwitches', ['enable-automation'])  
    options.add_experimental_option('useAutomationExtension', False)  
    options.add_argument('--disable-web-security')
    options.add_argument('--disable-features=IsolateOrigins,site-per-process')
    options.add_argument("--disable-blink-features=AutomationControlled")
    
    # Inisialisasi WebDriver  
    driver = None  
    try:  
        driver = webdriver.Chrome(options=options)  
        driver.implicitly_wait(10)  
    except Exception as e:  
        print(f"Error initializing WebDriver: {e}")  
        return  
    
    # Hapus file CSV sebelumnya jika ada  
    if Path("hotels_data_27-28_desember.csv").exists():  
        Path("hotels_data_27-28_desember.csv").unlink()  
    
    try:
        hotels = json.load(open('hotels_bandung.json'))['hotels']
        print(f"Loaded {len(hotels)} hotels")
        # Create lookup dictionary for quick access by name
        hotel_lookup = {hotel['name'].lower(): hotel for hotel in hotels}
        first_write = True
        checkin = "2026-01-09"  # Format: YYYY-MM-DD
        checkout = "2026-01-10"  # Format: YYYY-MM-DD
        
        # Hapus file JSON sebelumnya jika ada
        if Path("hotels_data_08-09_januari.json").exists():
            Path("hotels_data_08-09_januari.json").unlink()
        
        @retry(stop=stop_after_attempt(3), 
               wait=wait_exponential(multiplier=1, min=4, max=10))
        def get_with_retry(driver, url):
            driver.get(url)
            return True
            
        for idx, hotel in enumerate(hotels, 1):
            print(f"\n{'='*80}")
            print(f"[{idx}/{len(hotels)}] Processing: {hotel['name']}")
            print(f"{'='*80}")
            
            retries = 3
            attempt = 1
            
            while retries > 0:
                print(f"\n[Attempt {attempt}/3] Trying to extract data...")
                try:
                    # Use retry wrapper for get requests
                    search_url = get_hotel_url(
                        hotel['name']+" reviews",
                        checkin_date=checkin,
                        checkout_date=checkout
                    )
                    get_with_retry(driver, search_url)
                    time.sleep(5)
                    
                    if not click_matching_hotel(driver, hotel['name']):
                        print(f"× Failed to click hotel: {hotel['name']}")
                        retries -= 1
                        attempt += 1
                        continue
                    
                    time.sleep(3) # Tunggu halaman detail load

                    print("\nUpdating check-in/check-out dates...")
                    update_success = update_hotel_dates(
                        driver,
                        new_checkin_date=checkin,
                        new_checkout_date=checkout
                    )
                    if update_success:
                        print("✓ Successfully updated check-in/check-out dates")
                        time.sleep(3)  # Beri waktu untuk refresh data hotel
                    else:
                        print("⚠ Failed to update dates, continuing with default dates")
                    
                    # 3. Extract data
                    hotel_data = extract_hotel_data(driver, hotel['name'], hotel_lookup)
                    
                    if hotel_data:
                        # Update nama dari JSON jika N/A
                        if hotel_data["Name"] == "N/A":
                            hotel_data["Name"] = hotel['name']
                            
                        print("\nExtracted Data:")
                        print("-" * 50)
                        for key, value in hotel_data.items():
                            if isinstance(value, list):
                                print(f"{key:15}: Found {len(value)} items")
                            else:
                                print(f"{key:15}: {value}")
                        print("-" * 50)
                        
                        # Save to both CSV and JSON
                        # save_to_csv(hotel_data, first_write)
                        save_to_json(hotel_data)
                        first_write = False
                        print(f"✓ Success: {hotel['name']}")
                        break
                    else:
                        print(f"× Failed attempt {attempt}: No data extracted")
                        retries -= 1
                        attempt += 1
                        if retries > 0:
                            print(f"\nRetrying... ({retries} attempts left)")
                            print("Waiting 5 seconds before next attempt...")
                            time.sleep(5)
                            driver.refresh()
                        else:
                            print(f"\n⚠ All attempts failed for: {hotel['name']}")

                except WebDriverException as e:
                    print(f"× Connection error on attempt {attempt}: {str(e)}")
                    retries -= 1
                    attempt += 1
                    if retries > 0:
                        print(f"\nRetrying... ({retries} attempts left)")
                        print("Waiting 5 seconds before next attempt...")
                        time.sleep(5)
                        driver.refresh()
                    else:
                        print(f"\n⚠ All attempts failed for: {hotel['name']}")
                        # Restart browser jika semua retry gagal
                        driver.quit()
                        driver = webdriver.Chrome(options=options)
                        driver.implicitly_wait(10)
                        
            # Delay sebelum hotel berikutnya
            delay = random.uniform(3, 5)
            print(f"\nWaiting {delay:.1f} seconds before next hotel...")
            time.sleep(delay)
            
    except Exception as e:
        print(f"Main error: {str(e)}")
        print(traceback.format_exc())
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":  
    main()