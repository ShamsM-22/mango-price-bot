from playwright.sync_api import sync_playwright


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    print("Mango saytı açılır...")

    page.goto(
        "https://shop.mango.com/",
        wait_until="domcontentloaded",
        timeout=60000
    )

    print("Səhifənin adı:", page.title())
    print("Playwright uğurla işləyir!")

    page.wait_for_timeout(10000)
    browser.close()