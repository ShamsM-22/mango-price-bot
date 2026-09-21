from pathlib import Path
import re

from playwright.sync_api import sync_playwright


# Nəticələrin saxlanacağı qovluq
OUTPUT_FOLDER = Path("data")
OUTPUT_FOLDER.mkdir(exist_ok=True)


product_url = input("Mango məhsul linkini daxil et: ").strip()

if not product_url.startswith("http"):
    raise ValueError("Düzgün Mango məhsul linki daxil edilməyib.")


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)

    page = browser.new_page(
        viewport={
            "width": 1400,
            "height": 900,
        }
    )

    print("\nMəhsul səhifəsi açılır...")

    page.goto(
        product_url,
        wait_until="domcontentloaded",
        timeout=90_000,
    )

    # Dinamik məlumatların yüklənməsi üçün gözləyirik
    page.wait_for_timeout(5_000)

    print("\n--- SƏHİFƏ MƏLUMATLARI ---")
    print("Səhifənin adı:", page.title())
    print("Cari link:", page.url)

    # Səhifədəki H1 başlıqlarını yoxlayırıq
    product_titles = page.locator("h1").all_inner_texts()

    print("\n--- H1 BAŞLIQLARI ---")

    if product_titles:
        for title in product_titles:
            print(title.strip())
    else:
        print("H1 başlığı tapılmadı.")

    # Səhifənin görünən mətnini götürürük
    body_text = page.locator("body").inner_text()

    currency_pattern = re.compile(
        r"€|£|\$|₺|AZN|TL|EUR|GBP|USD",
        re.IGNORECASE,
    )

    price_lines = []

    for line in body_text.splitlines():
        clean_line = line.strip()

        if clean_line and currency_pattern.search(clean_line):
            if clean_line not in price_lines:
                price_lines.append(clean_line)

    print("\n--- QİYMƏT OLA BİLƏCƏK SƏTİRLƏR ---")

    if price_lines:
        for line in price_lines[:20]:
            print(line)
    else:
        print("Qiymət sətiri tapılmadı.")

    # Səhifənin şəklini saxlayırıq
    screenshot_path = OUTPUT_FOLDER / "mango_product_page.png"

    page.screenshot(
        path=str(screenshot_path),
        full_page=True,
    )

    # HTML kodunu saxlayırıq
    html_path = OUTPUT_FOLDER / "mango_product_page.html"

    html_path.write_text(
        page.content(),
        encoding="utf-8",
    )

    print("\n--- SAXLANILAN FAYLLAR ---")
    print("Şəkil:", screenshot_path)
    print("HTML:", html_path)

    print("\nBrauzer 15 saniyə açıq qalacaq...")

    page.wait_for_timeout(15_000)
    browser.close()