import json
import re

from playwright.sync_api import sync_playwright


def get_product_code(url: str) -> str:
    """Linkdən 8 rəqəmli məhsul kodunu tapır."""
    match = re.search(r"/(\d{8})/", url)
    return match.group(1) if match else "Tapılmadı"


def get_country_code(url: str) -> str:
    """Linkdən ölkə kodunu götürür: gb, tr, es və s."""
    match = re.search(r"shop\.mango\.com/([^/]+)/", url)
    return match.group(1).upper() if match else "Tapılmadı"


def get_currency(price_text: str) -> str:
    """Qiymətdəki işarəyə əsasən valyutanı müəyyən edir."""
    if "£" in price_text:
        return "GBP"
    if "€" in price_text:
        return "EUR"
    if "₺" in price_text or "TL" in price_text:
        return "TRY"
    if "$" in price_text:
        return "USD"

    return "Tapılmadı"


def clean_price(price_text: str) -> str:
    """Qiymətdən yalnız rəqəmi götürür."""
    match = re.search(r"\d+(?:[.,]\d{1,2})?", price_text)
    return match.group(0).replace(",", ".") if match else "Tapılmadı"


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

    print("\nMango məhsulu oxunur...")

    page.goto(
        product_url,
        wait_until="domcontentloaded",
        timeout=90_000,
    )

    page.wait_for_timeout(5_000)

    product_name = "Tapılmadı"
    price_text = "Tapılmadı"

    # Əvvəlcə səhifədəki strukturlaşdırılmış məhsul məlumatını axtarırıq
    json_scripts = page.locator(
        'script[type="application/ld+json"]'
    ).all_text_contents()

    for script_text in json_scripts:
        try:
            data = json.loads(script_text)

            items = data if isinstance(data, list) else [data]

            for item in items:
                if not isinstance(item, dict):
                    continue

                if item.get("@type") == "Product":
                    product_name = item.get("name", product_name)

                    offers = item.get("offers", {})

                    if isinstance(offers, list) and offers:
                        offers = offers[0]

                    if isinstance(offers, dict):
                        price = offers.get("price")
                        currency = offers.get("priceCurrency")

                        if price:
                            price_text = f"{price} {currency or ''}".strip()

        except json.JSONDecodeError:
            continue

    # JSON məlumatında məhsul adı tapılmasa, H1-dən götürürük
    if product_name == "Tapılmadı":
        headings = page.locator("h1").all_inner_texts()

        if headings:
            product_name = headings[0].strip()

    # Qiymət tapılmasa səhifənin görünən mətnində axtarırıq
    if price_text == "Tapılmadı":
        body_text = page.locator("body").inner_text()

        price_match = re.search(
            r"(?:£|€|₺|\$)\s?\d+(?:[.,]\d{1,2})?",
            body_text,
        )

        if price_match:
            price_text = price_match.group(0)

    product_code = get_product_code(page.url)
    country_code = get_country_code(page.url)
    price = clean_price(price_text)
    currency = get_currency(price_text)

    # JSON məlumatında valyuta ayrıca yazılıbsa
    if currency == "Tapılmadı":
        if "GBP" in price_text:
            currency = "GBP"
        elif "EUR" in price_text:
            currency = "EUR"
        elif "TRY" in price_text:
            currency = "TRY"
        elif "USD" in price_text:
            currency = "USD"

    print("\n--- MƏHSUL MƏLUMATLARI ---")
    print("Product name:", product_name)
    print("Price:", price)
    print("Currency:", currency)
    print("Product code:", product_code)
    print("Country:", country_code)
    print("URL:", page.url)

    page.wait_for_timeout(10_000)
    browser.close()