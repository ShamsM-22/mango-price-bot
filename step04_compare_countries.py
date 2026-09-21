import csv
import json
import re
import time
import unicodedata

from html.parser import HTMLParser

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, urlparse

import httpx

from playwright.sync_api import (
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


# ============================================================
# FAYLLAR
# ============================================================

DATA_FOLDER = Path("data")

OUTPUT_FILE = (
    DATA_FOLDER
    / "country_price_comparison.csv"
)

LAST_SEARCH_FILE = (
    DATA_FOLDER
    / "last_search.txt"
)

LAST_SIZE_FILE = (
    DATA_FOLDER
    / "last_requested_size.txt"
)

HEADLESS = True

SCRIPT_VERSION = (
    "2026-08-21-CLOUD-HEADLESS-V20"
)


# ============================================================
# ÖLKƏLƏR
# ============================================================

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


COUNTRIES = {
    "AZ": {
        "name": "Azerbaijan",
        "language": "en",
        "locale": "en-US",
    },
    "ES": {
        "name": "Spain",
        "language": "es",
        "locale": "es-ES",
    },
    "TR": {
        "name": "Turkey",
        "language": "tr",
        "locale": "tr-TR",
    },
}


COLOR_HEADINGS = [
    "select a color",
    "select a colour",
    "choose a color",
    "choose a colour",
    "pick a color",
    "pick a colour",
    "selecciona un color",
    "elige un color",
    "bir renk seçin",
    "bir renk secin",
    "renk seçin",
    "renk secin",
    "rəng seçin",
    "reng secin",
]


SIZE_HEADINGS = [
    "select your size",
    "select a size",
    "select size",
    "choose your size",
    "choose a size",
    "choose size",
    "selecciona tu talla",
    "selecciona una talla",
    "elige tu talla",
    "elige una talla",
    "beden seçin",
    "beden secin",
    "beden seç",
    "beden sec",
    "beden seçiniz",
    "beden seciniz",
    "ölçünü seç",
    "olcunu sec",
    "ölçü seç",
    "olcu sec",
]


SIZE_SECTION_ENDINGS = [
    "measurements",
    "size guide",
    "guía de tallas",
    "guia de tallas",
    "ölçüler",
    "olculer",
    "sepete ekle",
    "ekle",
    "add",
    "add to bag",
    "add to wishlist",
    "favori olarak kaydet",
    "beni bilgilendir",
    "notify me",
    "avísame",
    "avisame",
    "añadir",
    "anadir",
]


SHOE_WORDS = [
    "/shoes/",
    "/shoe/",
    "/footwear/",
    "/sandals/",
    "/boots/",
    "/sneakers/",
    "shoe",
    "shoes",
    "heeled shoes",
    "sandal",
    "sandals",
    "boot",
    "boots",
    "loafer",
    "moccasin",
    "sneaker",
    "trainer",
    "zapato",
    "sandalia",
    "bota",
    "ayakkabı",
    "ayakkabi",
    "ayaqqabı",
    "ayaqqabi",
]


LETTER_SIZES = [
    "XXXXL",
    "XXXL",
    "XXL",
    "XL",
    "L",
    "M",
    "S",
    "XS",
    "XXS",
    "XXXS",
]


UNAVAILABLE_WORDS = [
    "disabled",
    "unavailable",
    "not available",
    "out of stock",
    "sold out",
    "no stock",
    "agotado",
    "no disponible",
    "sin stock",
    "tükendi",
    "stokta yok",
    "mevcut değil",
    "mövcud deyil",
    "stokda yoxdur",
]


ONE_SIZE_WORDS = [
    "standart",
    "standard",
    "one size",
    "one-size",
    "one size fits all",
    "tek beden",
    "talla única",
    "talla unica",
    "taille unique",
]


LAST_FEW_WORDS = [
    "last few items",
    "son ürünler",
    "son urunler",
    "últimas unidades",
    "ultimas unidades",
]


# ============================================================
# MƏTN FUNKSİYALARI
# ============================================================

def normalize_text(
    value: str,
) -> str:
    """
    Müqayisə üçün mətni sadələşdirir.
    """

    normalized = unicodedata.normalize(
        "NFKD",
        str(value).casefold(),
    )

    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(
            character
        )
    )

    normalized = normalized.replace(
        "–",
        "-",
    )

    normalized = normalized.replace(
        "—",
        "-",
    )

    return re.sub(
        r"\s+",
        " ",
        normalized,
    ).strip()


def normalize_fractional_size_text(
    value: str,
) -> str:
    """
    Yarım ölçüləri decimal formaya çevirir.

    6½    -> 6.5
    7 1/2 -> 7.5
    6,5   -> 6.5
    """

    clean_value = str(
        value
    )

    clean_value = re.sub(
        r"(\d+)\s+1\s*/\s*2",
        r"\1.5",
        clean_value,
    )

    clean_value = re.sub(
        r"(\d+)\s*½",
        r"\1.5",
        clean_value,
    )

    clean_value = clean_value.replace(
        ",",
        ".",
    )

    return clean_value


def format_numeric_size(
    value: str,
) -> str:
    """
    37.0 -> 37
    6½   -> 6.5
    """

    clean_value = (
        normalize_fractional_size_text(
            value
        )
        .strip()
    )

    try:
        number = float(
            clean_value
        )

    except ValueError:
        return clean_value

    if number.is_integer():
        return str(
            int(number)
        )

    return (
        f"{number:.2f}"
        .rstrip("0")
        .rstrip(".")
    )


def normalize_size(
    value: str,
) -> str:
    """
    Ölçünü müqayisə üçün standartlaşdırır.
    """

    clean_value = (
        normalize_fractional_size_text(
            value
        )
        .strip()
        .upper()
    )

    clean_value = re.sub(
        r"\s+",
        " ",
        clean_value,
    )

    return clean_value


def unique_size_options(
    options: list[dict],
) -> list[dict]:
    """
    Eyni lokal ölçünün təkrarlarını silir.
    """

    result = []
    seen = set()

    for option in options:
        size = str(
            option.get(
                "size",
                "",
            )
        ).strip()

        size_key = normalize_size(
            size
        )

        if not size_key:
            continue

        if size_key in seen:
            existing = next(
                item
                for item in result
                if normalize_size(
                    item["size"]
                )
                == size_key
            )

            existing["available"] = (
                bool(
                    existing.get(
                        "available"
                    )
                )
                or bool(
                    option.get(
                        "available"
                    )
                )
            )

            if (
                not existing.get(
                    "eur_size"
                )
                and option.get(
                    "eur_size"
                )
            ):
                existing[
                    "eur_size"
                ] = option[
                    "eur_size"
                ]

            if (
                not existing.get(
                    "canonical_key"
                )
                and option.get(
                    "canonical_key"
                )
            ):
                existing[
                    "canonical_key"
                ] = option[
                    "canonical_key"
                ]

            continue

        seen.add(
            size_key
        )

        new_option = {
            "size": size,
            "available": bool(
                option.get(
                    "available",
                    True,
                )
            ),
            "eur_size": str(
                option.get(
                    "eur_size",
                    "",
                )
            ).strip(),
            "canonical_key": str(
                option.get(
                    "canonical_key",
                    "",
                )
            ).strip(),
            "position": len(
                result
            ),
        }

        result.append(
            new_option
        )

    return result


# ============================================================
# MANGO LİNK FUNKSİYALARI
# ============================================================

def extract_original_country_code(
    product_url: str,
) -> str:
    """
    Linkdəki orijinal bazarı götürür.
    """

    parts = [
        part
        for part in urlparse(
            product_url
        ).path.split("/")
        if part
    ]

    if not parts:
        return ""

    return parts[0].upper()


def extract_product_path(
    product_url: str,
) -> str:
    """
    Linkdən ölkə və dil hissəsini çıxarır.
    """

    parsed_url = urlparse(
        product_url
    )

    if parsed_url.netloc.lower() not in {
        "shop.mango.com",
        "www.shop.mango.com",
    }:
        raise ValueError(
            "Bu, düzgün Mango mağaza linki deyil."
        )

    parts = [
        part
        for part in parsed_url.path.split("/")
        if part
    ]

    if len(parts) < 3:
        raise ValueError(
            "Mango məhsul linkinin quruluşu düzgün deyil."
        )

    if "p" not in parts:
        raise ValueError(
            "Link Mango məhsul səhifəsi deyil."
        )

    return "/".join(
        parts[2:]
    )


def build_country_url(
    country_code: str,
    language: str,
    product_path: str,
) -> str:
    """
    Eyni məhsul üçün ölkə linki yaradır.
    """

    return (
        "https://shop.mango.com/"
        f"{country_code.lower()}/"
        f"{language}/"
        f"{product_path}"
    )


def extract_product_code(
    product_url: str,
) -> str:
    """
    Linkdən 8 rəqəmli məhsul kodunu götürür.
    """

    match = re.search(
        r"/(\d{8})(?:/|$|[?#])",
        product_url,
    )

    if match:
        return match.group(1)

    return "Not found"


# ============================================================
# SÜRƏTLİ / ADAPTİV SƏHİFƏ GÖZLƏMƏSİ
# ============================================================

def wait_for_mango_product_ready(
    page: Page,
    timeout_ms: int = 6_000,
) -> None:
    """
    networkidle + sabit 3.5 saniyə əvəzinə,
    əsas məhsul kontenti görünən kimi davam edir.
    """

    deadline = (
        time.perf_counter()
        + timeout_ms / 1000
    )

    while time.perf_counter() < deadline:
        try:
            h1_ready = (
                page.locator(
                    "h1"
                ).count()
                > 0
            )

            json_ld_ready = (
                page.locator(
                    'script[type="application/ld+json"]'
                ).count()
                > 0
            )

            body_ready = (
                page.locator(
                    "body"
                ).count()
                > 0
            )

            if (
                body_ready
                and (
                    h1_ready
                    or json_ld_ready
                )
            ):
                page.wait_for_timeout(
                    350
                )
                return

        except Exception:
            pass

        page.wait_for_timeout(
            150
        )

    try:
        page.wait_for_timeout(
            300
        )
    except Exception:
        pass


# ============================================================
# POPUP
# ============================================================

def dismiss_popups(
    page: Page,
) -> None:
    """
    Cookie pəncərələrini bağlamağa çalışır.
    """

    names = [
        "Accept",
        "Accept all",
        "Allow all",
        "Only necessary cookies",
        "Aceptar",
        "Aceptar todo",
        "Kabul et",
        "Tümünü kabul et",
        "Yalnızca gerekli çerezler",
        "Qəbul et",
        "Razıyam",
    ]

    for name in names:
        try:
            button = page.get_by_role(
                "button",
                name=re.compile(
                    rf"^{re.escape(name)}$",
                    re.IGNORECASE,
                ),
            ).first

            if button.is_visible(
                timeout=400
            ):
                button.click(
                    timeout=1_500
                )

                page.wait_for_timeout(
                    300
                )

        except Exception:
            continue


# ============================================================
# MƏHSUL ADI VƏ QİYMƏT
# ============================================================

def get_product_name(
    page: Page,
) -> str:
    """
    Məhsulun əsas adını tapır.
    """

    try:
        headings = page.locator(
            "h1"
        ).all_inner_texts()

    except Exception:
        headings = []

    ignored = [
        "WHICH COUNTRY",
        "SELECT YOUR COUNTRY",
        "HANSI ÖLKƏ",
    ]

    for heading in headings:
        clean_heading = heading.strip()

        if not clean_heading:
            continue

        if any(
            phrase in clean_heading.upper()
            for phrase in ignored
        ):
            continue

        return clean_heading

    return "Not found"


def is_shoe_product(
    product_url: str,
    product_name: str,
) -> bool:
    """
    Məhsulun ayaqqabı olub-olmadığını müəyyən edir.
    """

    decoded_url = unquote(
        product_url
    )

    search_text = normalize_text(
        f"{decoded_url} {product_name}"
    )

    return any(
        normalize_text(
            word
        ) in search_text
        for word in SHOE_WORDS
    )


def normalize_price_text(
    value: str,
) -> str:
    """
    Qiymət mətnindəki artıq boşluqları təmizləyir.
    """

    return re.sub(
        r"\s+",
        " ",
        str(
            value
            or ""
        ),
    ).strip()


def price_text_from_value_and_currency(
    price_value,
    currency_value,
) -> str:
    """
    JSON-LD qiymətini standart mətnə çevirir.

    100.99 + AZN -> 100.99 AZN
    """

    if price_value in {
        None,
        "",
    }:
        return ""

    currency = str(
        currency_value
        or ""
    ).strip().upper()

    price = str(
        price_value
    ).strip()

    if not price:
        return ""

    if currency:
        return f"{price} {currency}"

    return price


def find_offer_in_json_ld(
    value,
) -> tuple[
    object | None,
    str,
]:
    """
    JSON-LD daxilində Product/Offer qiymətini rekursiv tapır.

    Schema.org offers.price normalda cari satış qiymətidir.
    """

    if isinstance(
        value,
        list,
    ):
        for item in value:
            price, currency = (
                find_offer_in_json_ld(
                    item
                )
            )

            if price not in {
                None,
                "",
            }:
                return (
                    price,
                    currency,
                )

        return (
            None,
            "",
        )

    if not isinstance(
        value,
        dict,
    ):
        return (
            None,
            "",
        )

    offer_type = str(
        value.get(
            "@type",
            "",
        )
    ).casefold()

    if (
        "offer" in offer_type
        or "aggregateoffer"
        in offer_type
    ):
        direct_price = value.get(
            "price"
        )

        direct_currency = value.get(
            "priceCurrency",
            "",
        )

        if direct_price not in {
            None,
            "",
        }:
            return (
                direct_price,
                str(
                    direct_currency
                    or ""
                ),
            )

        price_specification = value.get(
            "priceSpecification"
        )

        price, currency = (
            find_offer_in_json_ld(
                price_specification
            )
        )

        if price not in {
            None,
            "",
        }:
            return (
                price,
                currency,
            )

    if "offers" in value:
        price, currency = (
            find_offer_in_json_ld(
                value.get(
                    "offers"
                )
            )
        )

        if price not in {
            None,
            "",
        }:
            return (
                price,
                currency,
            )

    graph = value.get(
        "@graph"
    )

    if graph is not None:
        price, currency = (
            find_offer_in_json_ld(
                graph
            )
        )

        if price not in {
            None,
            "",
        }:
            return (
                price,
                currency,
            )

    for nested_value in value.values():
        price, currency = (
            find_offer_in_json_ld(
                nested_value
            )
        )

        if price not in {
            None,
            "",
        }:
            return (
                price,
                currency,
            )

    return (
        None,
        "",
    )


def get_current_price_from_json_ld(
    page: Page,
) -> str:
    """
    Məhsulun schema.org Offer qiymətini oxuyur.

    Bu qiymət endirim varsa cari satış qiyməti olur.
    """

    scripts = page.locator(
        'script[type="application/ld+json"]'
    )

    try:
        count = scripts.count()

    except Exception:
        count = 0

    for index in range(
        count
    ):
        try:
            raw_text = scripts.nth(
                index
            ).text_content()

            if not raw_text:
                continue

            parsed = json.loads(
                raw_text
            )

            price, currency = (
                find_offer_in_json_ld(
                    parsed
                )
            )

            formatted = (
                price_text_from_value_and_currency(
                    price,
                    currency,
                )
            )

            if formatted:
                return formatted

        except (
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            continue

        except Exception:
            continue

    return ""


def extract_first_currency_price(
    text: str,
) -> str:
    """
    Mətndən ilk valyutalı qiyməti çıxarır.
    """

    clean_text = normalize_price_text(
        text
    )

    patterns = [
        r"(?:US\$|AZN|TRY|TL|EUR|USD|GBP|£|€|₺|\$)"
        r"\s*\d(?:[\d\s.,]*\d)?",

        r"\d(?:[\d\s.,]*\d)?"
        r"\s*(?:AZN|TRY|TL|EUR|USD|GBP|£|€|₺|\$)",
    ]

    matches = []

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            clean_text,
            flags=re.IGNORECASE,
        ):
            matches.append(
                (
                    match.start(),
                    match.group(
                        0
                    ).strip(),
                )
            )

    if not matches:
        return ""

    matches.sort(
        key=lambda item: item[
            0
        ]
    )

    return matches[
        0
    ][
        1
    ]


def get_current_price_from_labeled_text(
    text: str,
) -> str:
    """
    Mango-nun cari qiymət etiketindən sonrakı qiyməti çıxarır.

    Nümunə:
    Initial price ... AZN 125.99
    Current price [AZN 100.99]
    """

    clean_text = normalize_price_text(
        text
    )

    current_labels = [
        "Current price",
        "Sale price",
        "Discounted price",
        "Precio actual",
        "Precio rebajado",
        "Precio de oferta",
        "Güncel fiyat",
        "Guncel fiyat",
        "İndirimli fiyat",
        "Indirimli fiyat",
        "Cari qiymət",
        "Cari qiymet",
        "Endirimli qiymət",
        "Endirimli qiymet",
    ]

    label_pattern = "|".join(
        re.escape(
            label
        )
        for label in current_labels
    )

    match = re.search(
        rf"(?:{label_pattern})"
        rf"\s*[:\-]?\s*"
        rf"(?P<after>.{{0,100}})",
        clean_text,
        flags=re.IGNORECASE,
    )

    if not match:
        return ""

    return extract_first_currency_price(
        match.group(
            "after"
        )
    )


def get_current_price_from_targeted_elements(
    page: Page,
) -> str:
    """
    Cari/endirimli qiymətə aid xüsusi DOM elementlərini oxuyur.
    """

    selectors = [
        '[aria-label*="current price" i]',
        '[aria-label*="sale price" i]',
        '[aria-label*="discounted price" i]',
        '[aria-label*="precio actual" i]',
        '[aria-label*="precio rebajado" i]',
        '[aria-label*="güncel fiyat" i]',
        '[aria-label*="guncel fiyat" i]',
        '[aria-label*="indirimli fiyat" i]',
        '[aria-label*="cari qiymət" i]',
        '[aria-label*="cari qiymet" i]',
        '[aria-label*="endirimli qiymət" i]',
        '[aria-label*="endirimli qiymet" i]',
        '[data-testid*="current-price" i]',
        '[data-testid*="sale-price" i]',
        '[data-testid*="discount" i][data-testid*="price" i]',
        '[class*="currentPrice" i]',
        '[class*="current-price" i]',
        '[class*="salePrice" i]',
        '[class*="sale-price" i]',
        '[class*="discountPrice" i]',
        '[class*="discount-price" i]',
    ]

    for selector in selectors:
        locator = page.locator(
            selector
        )

        try:
            count = min(
                locator.count(),
                30,
            )

        except Exception:
            count = 0

        for index in range(
            count
        ):
            try:
                element = locator.nth(
                    index
                )

                text_values = [
                    element.get_attribute(
                        "aria-label"
                    )
                    or "",
                    element.get_attribute(
                        "title"
                    )
                    or "",
                    element.inner_text()
                    or "",
                    element.text_content()
                    or "",
                ]

                combined_text = " ".join(
                    text_values
                )

                labeled_price = (
                    get_current_price_from_labeled_text(
                        combined_text
                    )
                )

                if labeled_price:
                    return labeled_price

                direct_price = (
                    extract_first_currency_price(
                        combined_text
                    )
                )

                if direct_price:
                    return direct_price

            except Exception:
                continue

    return ""


def get_non_struck_price_candidate(
    page: Page,
) -> str:
    """
    Cari qiymət etiketi tapılmadıqda, üstündən xətt çəkilməmiş
    qiymət elementini seçir.

    Original/initial/old price elementləri rədd edilir.
    """

    candidates = page.evaluate(
        """
        () => {
            const selector = [
                '[data-testid*="price" i]',
                '[class*="price" i]',
                '[aria-label*="price" i]'
            ].join(',');

            const values = [];

            for (
                const element
                of document.querySelectorAll(selector)
            ) {
                const text = [
                    element.getAttribute('aria-label') || '',
                    element.getAttribute('title') || '',
                    element.innerText || '',
                    element.textContent || ''
                ]
                    .join(' ')
                    .replace(/\\s+/g, ' ')
                    .trim();

                if (!text) {
                    continue;
                }

                const classText = String(
                    element.className || ''
                ).toLowerCase();

                const testId = String(
                    element.getAttribute('data-testid')
                    || ''
                ).toLowerCase();

                const style = getComputedStyle(
                    element
                );

                const decoration = String(
                    style.textDecorationLine
                    || style.textDecoration
                    || ''
                ).toLowerCase();

                const struck = Boolean(
                    element.matches('s, del')
                    || element.closest('s, del')
                    || decoration.includes('line-through')
                    || /initial|original|old|previous|crossed|struck/.test(
                        classText
                        + ' '
                        + testId
                        + ' '
                        + text.toLowerCase()
                    )
                );

                const currentHint = Boolean(
                    /current|sale|discount|offer|actual|rebajado|güncel|guncel|indirimli|cari|endirimli/.test(
                        classText
                        + ' '
                        + testId
                        + ' '
                        + text.toLowerCase()
                    )
                );

                values.push({
                    text,
                    struck,
                    currentHint,
                });
            }

            return values;
        }
        """
    )

    priced_candidates = []

    for candidate in candidates:
        price_text = extract_first_currency_price(
            candidate.get(
                "text",
                "",
            )
        )

        if not price_text:
            continue

        priced_candidates.append(
            {
                "price_text": price_text,
                "struck": bool(
                    candidate.get(
                        "struck"
                    )
                ),
                "current_hint": bool(
                    candidate.get(
                        "currentHint"
                    )
                ),
            }
        )

    for candidate in priced_candidates:
        if (
            candidate[
                "current_hint"
            ]
            and not candidate[
                "struck"
            ]
        ):
            return candidate[
                "price_text"
            ]

    for candidate in priced_candidates:
        if not candidate[
            "struck"
        ]:
            return candidate[
                "price_text"
            ]

    return ""


def get_price_text(
    page: Page,
) -> str:
    """
    Məhsulun CARİ satış qiymətini tapır.

    Prioritet:
    1. JSON-LD offers.price
    2. Current price / Sale price etiketli element
    3. Səhifə mətnində Current price-dan sonrakı qiymət
    4. Üstündən xətt çəkilməmiş qiymət elementi
    """

    json_ld_price = (
        get_current_price_from_json_ld(
            page
        )
    )

    if json_ld_price:
        print(
            "Cari qiymət mənbəyi: JSON-LD"
        )

        return json_ld_price

    targeted_price = (
        get_current_price_from_targeted_elements(
            page
        )
    )

    if targeted_price:
        print(
            "Cari qiymət mənbəyi: "
            "current/sale price elementi"
        )

        return targeted_price

    try:
        body_text = page.locator(
            "body"
        ).inner_text()

    except Exception:
        body_text = ""

    labeled_price = (
        get_current_price_from_labeled_text(
            body_text
        )
    )

    if labeled_price:
        print(
            "Cari qiymət mənbəyi: "
            "Current price mətni"
        )

        return labeled_price

    non_struck_price = (
        get_non_struck_price_candidate(
            page
        )
    )

    if non_struck_price:
        print(
            "Cari qiymət mənbəyi: "
            "xətt çəkilməmiş qiymət"
        )

        return non_struck_price

    return "Not found"


def detect_currency(
    price_text: str,
) -> str:
    """
    Qiymətin valyutasını müəyyən edir.
    """

    upper_text = price_text.upper()

    if "AZN" in upper_text:
        return "AZN"

    if (
        "TRY" in upper_text
        or "TL" in upper_text
        or "₺" in price_text
    ):
        return "TRY"

    if (
        "EUR" in upper_text
        or "€" in price_text
    ):
        return "EUR"

    if (
        "GBP" in upper_text
        or "£" in price_text
    ):
        return "GBP"

    if (
        "USD" in upper_text
        or "US$" in upper_text
        or "$" in price_text
    ):
        return "USD"

    return "Not found"


def clean_price(
    price_text: str,
) -> float | None:
    """
    Qiymət mətnini float-a çevirir.
    """

    match = re.search(
        r"\d(?:[\d\s.,]*\d)?",
        price_text,
    )

    if not match:
        return None

    value = (
        match.group(0)
        .replace(" ", "")
        .replace(
            "\u00a0",
            "",
        )
    )

    if (
        "," in value
        and "." in value
    ):
        if value.rfind(
            ","
        ) > value.rfind(
            "."
        ):
            value = (
                value
                .replace(
                    ".",
                    "",
                )
                .replace(
                    ",",
                    ".",
                )
            )

        else:
            value = value.replace(
                ",",
                "",
            )

    elif "," in value:
        parts = value.split(
            ","
        )

        if len(
            parts[-1]
        ) in {
            1,
            2,
        }:
            value = value.replace(
                ",",
                ".",
            )

        else:
            value = value.replace(
                ",",
                "",
            )

    elif "." in value:
        parts = value.split(
            "."
        )

        if (
            value.count(
                "."
            ) == 1
            and len(
                parts[-1]
            ) == 3
        ):
            value = value.replace(
                ".",
                "",
            )

    try:
        return float(
            value
        )

    except ValueError:
        return None


# ============================================================
# BİRBAŞA MANGO HTML-DƏN ÖLÇÜ OXUMA
# ============================================================

class OrderedVisibleTextParser(
    HTMLParser
):
    """
    HTML-dəki görünən mətnləri ardıcıllıqla toplayır.

    script, style, svg və noscript hissələri nəzərə alınmır.
    """

    IGNORED_TAGS = {
        "script",
        "style",
        "svg",
        "noscript",
        "template",
    }

    def __init__(
        self,
    ) -> None:
        super().__init__(
            convert_charrefs=True
        )

        self.items: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs,
    ) -> None:
        if tag.lower() in self.IGNORED_TAGS:
            self._ignored_depth += 1

    def handle_endtag(
        self,
        tag: str,
    ) -> None:
        if (
            tag.lower()
            in self.IGNORED_TAGS
            and self._ignored_depth > 0
        ):
            self._ignored_depth -= 1

    def handle_data(
        self,
        data: str,
    ) -> None:
        if self._ignored_depth:
            return

        clean_text = re.sub(
            r"\s+",
            " ",
            normalize_fractional_size_text(
                data
            ),
        ).strip()

        if clean_text:
            self.items.append(
                clean_text
            )


def fetch_mango_html(
    product_url: str,
) -> str:
    """
    Mango səhifəsinin server tərəfindən verilən HTML-ni götürür.

    Ölçülər Mango səhifəsinin HTML mətnində
    "Select your size" hissəsində təqdim olunur.
    """

    with httpx.Client(
        headers=HTTP_HEADERS,
        follow_redirects=True,
        timeout=35.0,
    ) as client:
        response = client.get(
            product_url
        )

        response.raise_for_status()

        return response.text


def clean_html_size_item(
    value: str,
) -> str:
    """
    Siyahı nömrəsini və artıq boşluqları silir.

    1. 35 -> 35
    3) 6½ (EUR 37) -> 6.5 (EUR 37)
    """

    clean_value = (
        normalize_fractional_size_text(
            value
        )
    )

    clean_value = re.sub(
        # Yalnız "1. 34" və "3) 6.5" kimi siyahı nömrəsini sil.
        # "6.5 EUR 37" ölçüsündəki decimal nöqtəyə toxunma.
        r"^\s*\d+\s*[.)]\s+",
        "",
        clean_value,
    )

    clean_value = re.sub(
        r"\s+",
        " ",
        clean_value,
    ).strip()

    return clean_value


def html_text_is_size_heading(
    value: str,
) -> bool:
    """
    HTML mətninin ölçü başlığı olub-olmadığını yoxlayır.
    """

    normalized_value = normalize_text(
        value
    )

    return any(
        normalized_value
        == normalize_text(
            heading
        )
        for heading in SIZE_HEADINGS
    )


def html_text_ends_size_section(
    value: str,
) -> bool:
    """
    Ölçü hissəsinin sonunu müəyyən edir.
    """

    normalized_value = normalize_text(
        value
    )

    return any(
        normalized_value
        == normalize_text(
            ending
        )
        or normalized_value.startswith(
            normalize_text(
                ending
            )
        )
        for ending in SIZE_SECTION_ENDINGS
    )


def is_one_size_label(
    value: str,
) -> bool:
    """
    Mango-nun müxtəlif bazarlardakı standart ölçü adlarını
    eyni məntiqdə tanıyır.
    """

    normalized_value = normalize_text(
        value
    ).strip(" :-|,;")

    return any(
        normalized_value
        == normalize_text(
            one_size_word
        )
        for one_size_word
        in ONE_SIZE_WORDS
    )


def text_contains_unavailable_status(
    value: str,
) -> bool:
    """
    Ölçünün stokda olmadığını bildirən mətni tanıyır.
    """

    normalized_value = normalize_text(
        value
    )

    return any(
        normalize_text(
            word
        ) in normalized_value
        for word in UNAVAILABLE_WORDS
    )


def text_contains_last_few_status(
    value: str,
) -> bool:
    """
    'Son məhsullar / Last few items' statusunu tanıyır.
    Bu status ölçünün mövcud olduğunu göstərir.
    """

    normalized_value = normalize_text(
        value
    )

    return any(
        normalize_text(
            word
        ) in normalized_value
        for word in LAST_FEW_WORDS
    )



def parse_dimension_size_label(
    value: str,
) -> dict | None:
    """
    Mango Home kimi kateqoriyalarda ölçünü dimension formatında tanıyır.

    Nümunələr:
        30x50cm Toalla tocador
        50x90cm Toalla lavabo
        90x150cm Toalla baño
        160x200 cm
        50 x 80 cm

    Telegram-da label-i qısa və aydın saxlayır:
        30x50cm
        50x90cm
        90x150cm
    """

    clean_value = re.sub(
        r"\s+",
        " ",
        str(
            value
            or ""
        ),
    ).strip()

    if not clean_value:
        return None

    match = re.search(
        r"(?<!\d)"
        r"(\d{1,4}(?:[.,]\d+)?)"
        r"\s*[x×]\s*"
        r"(\d{1,4}(?:[.,]\d+)?)"
        r"(?:\s*[x×]\s*"
        r"(\d{1,4}(?:[.,]\d+)?))?"
        r"\s*(cm|mm|m)?"
        r"(?!\w)",
        clean_value,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    def clean_number(
        number_text: str,
    ) -> str:
        number_text = (
            number_text
            .replace(
                ",",
                ".",
            )
        )

        try:
            number = float(
                number_text
            )
        except ValueError:
            return number_text

        if number.is_integer():
            return str(
                int(
                    number
                )
            )

        return (
            f"{number:.2f}"
            .rstrip("0")
            .rstrip(".")
        )

    dimensions = [
        clean_number(
            match.group(
                1
            )
        ),
        clean_number(
            match.group(
                2
            )
        ),
    ]

    if match.group(
        3
    ):
        dimensions.append(
            clean_number(
                match.group(
                    3
                )
            )
        )

    unit = (
        match.group(
            4
        )
        or ""
    ).lower()

    size_label = "x".join(
        dimensions
    )

    if unit:
        size_label += unit

    return {
        "size": size_label,
        "eur_size": "",
        "available": True,
        "size_kind": "dimension",
    }



def make_size_canonical_key(
    size_value: str,
    eur_size: str = "",
) -> str:
    """
    Fərqli bazarlarda yazılış dəyişsə də eyni fiziki ölçünü
    mümkün qədər eyni açara çevirir.

    Nümunələr:
        13-14 yaş 164cm
        13-14 years 164cm
        13-14 años 164cm
    hamısı -> NUM:13-14|164cm

    Ayaqqabıda EUR qarşılığı varsa ən güclü açar odur.
    """

    eur_key = normalize_size(
        eur_size
    )

    if eur_key:
        return (
            "EUR:"
            + eur_key
        )

    clean_value = re.sub(
        r"\s+",
        " ",
        str(
            size_value
            or ""
        ),
    ).strip()

    if not clean_value:
        return ""

    if (
        is_one_size_label(
            clean_value
        )
        or normalize_size(
            clean_value
        )
        == "STANDART"
    ):
        return "ONE_SIZE"

    dimension_option = (
        parse_dimension_size_label(
            clean_value
        )
    )

    if dimension_option is not None:
        return (
            "DIM:"
            + normalize_size(
                dimension_option[
                    "size"
                ]
            )
        )

    normalized_value = normalize_size(
        clean_value
    )

    if normalized_value in set(
        LETTER_SIZES
    ):
        return (
            "LETTER:"
            + normalized_value
        )

    # Bra / alphanumeric kimi formatlar:
    # 80B, 85C, 10Y və s.
    alphanumeric_tokens = re.findall(
        r"(?<![A-Z0-9])"
        r"\d{1,3}[A-Z]{1,3}"
        r"(?![A-Z0-9])",
        normalized_value,
    )

    # 164CM kimi measurement token-i bra/alphanumeric size deyil.
    alphanumeric_tokens = [
        token
        for token in alphanumeric_tokens
        if re.fullmatch(
            r"\d+(?:CM|MM|M)",
            token,
            flags=re.IGNORECASE,
        )
        is None
    ]

    # Yaş, boy və s. üçün dil sözlərini deyil,
    # rəqəmsal hissəni əsas götürürük.
    numeric_tokens = re.findall(
        r"(?<!\d)"
        r"\d+(?:[.,]\d+)?"
        r"(?:\s*[-/]\s*\d+(?:[.,]\d+)?)?"
        r"\s*(?:CM|MM|M)?"
        r"(?!\d)",
        normalized_value,
        flags=re.IGNORECASE,
    )

    cleaned_numeric_tokens = []

    for token in numeric_tokens:
        cleaned_token = (
            token
            .replace(
                " ",
                ""
            )
            .replace(
                ",",
                ".",
            )
            .upper()
        )

        if cleaned_token:
            cleaned_numeric_tokens.append(
                cleaned_token
            )

    if alphanumeric_tokens:
        return (
            "ALNUM:"
            + "|".join(
                alphanumeric_tokens
            )
        )

    if cleaned_numeric_tokens:
        return (
            "NUM:"
            + "|".join(
                cleaned_numeric_tokens
            )
        )

    return (
        "TEXT:"
        + normalize_text(
            clean_value
        )
    )


def is_obvious_non_size_structural_text(
    value: str,
) -> bool:
    """
    Struktur daxilində olsa belə ölçü ola bilməyən action/status/prose
    mətnlərini rədd edir.
    """

    clean_value = re.sub(
        r"\s+",
        " ",
        str(
            value
            or ""
        ),
    ).strip()

    if not clean_value:
        return True

    normalized_value = normalize_text(
        clean_value
    )

    if html_text_is_color_heading(
        clean_value
    ):
        return True

    if html_text_ends_size_section(
        clean_value
    ):
        return True

    if (
        text_contains_unavailable_status(
            clean_value
        )
        or text_contains_last_few_status(
            clean_value
        )
    ):
        return True

    blocked_exact = {
        "add",
        "ekle",
        "añadir",
        "anadir",
        "measurements",
        "olculer",
        "ölçüler",
        "size guide",
        "guia de tallas",
        "guía de tallas",
        "add to wishlist",
        "favori olarak kaydet",
        "beni bilgilendir",
        "notify me",
    }

    if normalized_value in {
        normalize_text(
            item
        )
        for item in blocked_exact
    }:
        return True

    # Model / fit cümlələri rəqəm daşısa da size option deyil.
    prose_markers = [
        "the model is wearing",
        "model wears",
        "model is wearing",
        "modelin uzerindeki",
        "modelin üzerindeki",
        "model beden",
        "model giymekte",
        "model giyiyor",
        "la modelo lleva",
        "el modelo lleva",
        "altura del modelo",
        "boyundadir",
        "boyundadır",
        "tall.",
        "height",
    ]

    if any(
        normalize_text(
            marker
        )
        in normalized_value
        for marker
        in prose_markers
    ):
        return True

    # Uzun cümlələri generic size kimi qəbul etmirik.
    if (
        len(
            clean_value
        )
        > 70
    ):
        return True

    return False


def parse_trusted_structural_size_label(
    value: str,
    country_code: str,
    is_shoe: bool,
    available: bool = True,
) -> dict | None:
    """
    Ən vacib V16 funksiyası.

    Burada ölçünün formatını əvvəlcədən bilmirik.
    Əgər mətn Mango-nun real SIZE CONTROL/LIST elementindən gəlibsə,
    həmin label özü ölçü kimi qəbul edilir.

    Buna görə gələcəkdə:
        S
        38
        30x50cm
        6 116cm
        13-14 years 164cm
        80B
        və s.
    üçün ayrıca script dəyişikliyinə ehtiyac olmur.
    """

    clean_value = clean_html_size_item(
        value
    )

    clean_value = re.sub(
        r"\s+",
        " ",
        clean_value,
    ).strip()

    if (
        not clean_value
        or is_obvious_non_size_structural_text(
            clean_value
        )
    ):
        return None

    # Əvvəl mövcud xüsusi parserlərdən istifadə edirik:
    # shoes EUR mapping, Standart, dimension, letter və s.
    exact_option = (
        parse_exact_size_from_html_item(
            value=clean_value,
            country_code=country_code,
            is_shoe=is_shoe,
        )
    )

    if exact_option is not None:
        exact_option[
            "available"
        ] = bool(
            available
        )

        exact_option[
            "canonical_key"
        ] = make_size_canonical_key(
            exact_option.get(
                "size",
                "",
            ),
            exact_option.get(
                "eur_size",
                "",
            ),
        )

        return exact_option

    # Struktur Mango tərəfindən size option kimi təsdiqlənibsə,
    # formatı məcburi regex-lə məhdudlaşdırmırıq.
    # Sadəcə təhlükəli uzun/action mətnləri yuxarıda rədd olunub.
    if len(
        clean_value
    ) > 70:
        return None

    return {
        "size": clean_value,
        "eur_size": "",
        "available": bool(
            available
        ),
        "canonical_key": (
            make_size_canonical_key(
                clean_value
            )
        ),
        "size_kind": "structural",
    }


def parse_exact_size_from_html_item(
    value: str,
    country_code: str,
    is_shoe: bool,
) -> dict | None:
    """
    Bir HTML mətn elementini ölçüyə çevirir.

    Yeni Mango dizaynında ölçü başlığı olmaya bilər.

    AZ/TR/ES ayaqqabı:
        35
        36
        37

    ABŞ ayaqqabı:
        5 EUR 35
        6 EUR 36
        6.5 EUR 37
        6.5 (EUR 37)

    Geyim:
        XS
        S
        M
        L
        34
        36
        38

    Standart məhsul:
        Standart
        Standard
        One size
        Tek beden
        Talla única
    """

    clean_value = clean_html_size_item(
        value
    )

    if not clean_value:
        return None

    dimension_option = (
        parse_dimension_size_label(
            clean_value
        )
    )

    if (
        dimension_option
        is not None
        and not is_shoe
    ):
        return dimension_option

    if is_shoe:
        if country_code.upper() == "US":
            pair_match = re.fullmatch(
                r"(\d{1,2}(?:[.]5)?)"
                r"\s*"
                r"(?:\(\s*)?"
                r"(?:EUR|EU)"
                r"\s*"
                r"(\d{2}(?:[.]5)?)"
                r"(?:\s*\))?",
                clean_value,
                flags=re.IGNORECASE,
            )

            if pair_match:
                return {
                    "size": format_numeric_size(
                        pair_match.group(1)
                    ),
                    "eur_size": format_numeric_size(
                        pair_match.group(2)
                    ),
                    "available": True,
                }

            return None

        local_match = re.fullmatch(
            r"(3[0-9]|4[0-9]|50)"
            r"(?:[.]5)?",
            clean_value,
        )

        if local_match:
            local_size = format_numeric_size(
                clean_value
            )

            return {
                "size": local_size,
                "eur_size": local_size,
                "available": True,
            }

        return None

    if is_one_size_label(
        clean_value
    ):
        return {
            "size": "Standart",
            "eur_size": "",
            "available": True,
        }

    normalized_value = normalize_size(
        clean_value
    )

    if normalized_value in set(
        LETTER_SIZES
    ):
        return {
            "size": normalized_value,
            "eur_size": "",
            "available": True,
        }

    numeric_match = re.fullmatch(
        r"\d{2}(?:[.]5)?",
        clean_value,
    )

    if numeric_match:
        try:
            numeric_value = float(
                normalize_fractional_size_text(
                    clean_value
                )
            )
        except ValueError:
            return None

        if 20 <= numeric_value <= 70:
            return {
                "size": format_numeric_size(
                    clean_value
                ),
                "eur_size": "",
                "available": True,
            }

    return None


def _size_option_numeric_value(
    option: dict,
    country_code: str,
) -> float | None:
    """
    Ölçü ardıcıllığını yoxlamaq üçün numeric dəyəri qaytarır.
    ABŞ ayaqqabısında EUR qarşılığına üstünlük verir.
    """

    if (
        country_code.upper() == "US"
        and option.get(
            "eur_size"
        )
    ):
        raw_value = option.get(
            "eur_size"
        )
    else:
        raw_value = option.get(
            "size"
        )

    try:
        return float(
            str(
                raw_value
            )
            .replace(
                ",",
                ".",
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def _size_option_kind(
    option: dict,
) -> str:
    """
    Ölçünü numeric / letter / one_size qrupuna ayırır.
    """

    size_value = normalize_size(
        option.get(
            "size",
            "",
        )
    )

    if is_one_size_label(
        size_value
    ) or size_value == "STANDART":
        return "one_size"

    if re.fullmatch(
        r"\d+(?:[.]\d+)?"
        r"x"
        r"\d+(?:[.]\d+)?"
        r"(?:x\d+(?:[.]\d+)?)?"
        r"(?:CM|MM|M)?",
        size_value,
        flags=re.IGNORECASE,
    ):
        return "dimension"

    if size_value in set(
        LETTER_SIZES
    ):
        return "letter"

    try:
        float(
            size_value
        )
        return "numeric"
    except ValueError:
        return "other"


def _options_can_continue_run(
    previous_option: dict,
    current_option: dict,
    country_code: str,
) -> bool:
    """
    Yeni Mango səhifəsində ardıcıl görünən ölçülərin
    eyni real size-list-ə aid olub-olmadığını yoxlayır.
    """

    previous_kind = _size_option_kind(
        previous_option
    )

    current_kind = _size_option_kind(
        current_option
    )

    if (
        previous_kind
        != current_kind
    ):
        return False

    if previous_kind == "one_size":
        return False

    if previous_kind == "dimension":
        # Home məhsullarında fərqli ölçülər rəngdən sonra ardıcıl gəlir.
        # 30x50cm -> 50x90cm -> 90x150cm kimi.
        return True

    if previous_kind == "letter":
        order = [
            "XXXS",
            "XXS",
            "XS",
            "S",
            "M",
            "L",
            "XL",
            "XXL",
            "XXXL",
            "XXXXL",
        ]

        try:
            previous_index = order.index(
                normalize_size(
                    previous_option[
                        "size"
                    ]
                )
            )

            current_index = order.index(
                normalize_size(
                    current_option[
                        "size"
                    ]
                )
            )

        except ValueError:
            return False

        return (
            0
            < current_index
            - previous_index
            <= 2
        )

    if previous_kind == "numeric":
        previous_number = (
            _size_option_numeric_value(
                previous_option,
                country_code,
            )
        )

        current_number = (
            _size_option_numeric_value(
                current_option,
                country_code,
            )
        )

        if (
            previous_number is None
            or current_number is None
        ):
            return False

        difference = (
            current_number
            - previous_number
        )

        return (
            0
            < difference
            <= 4
        )

    return False


def _modern_size_end_is_near(
    text_items: list[str],
    last_index: int,
) -> bool:
    """
    Ölçü run-dan dərhal sonra Measurements / Ölçüler / Add / Ekle
    kimi məhsul detal markerinin gəlib-gəlmədiyini yoxlayır.
    """

    for item in text_items[
        last_index + 1:
        last_index + 18
    ]:
        if html_text_ends_size_section(
            item
        ):
            return True

    return False


def _apply_modern_availability(
    run: list[tuple[int, dict]],
    text_items: list[str],
) -> list[dict]:
    """
    Yeni Mango mətn ardıcıllığında stok statusunu ölçülərə bağlayır.

    Aralıq ölçülərdə:
        size -> "Mevcut değil" -> next size
    modeli dəstəklənir.

    Son ölçüdə:
        ilk status "Mevcut değil"dirsə unavailable,
        ilk status "Son ürünler"dirsə available sayılır.
    """

    result = []

    for position, (
        item_index,
        option,
    ) in enumerate(
        run
    ):
        next_size_index = (
            run[
                position + 1
            ][0]
            if position + 1
            < len(
                run
            )
            else None
        )

        if next_size_index is not None:
            status_items = text_items[
                item_index + 1:
                next_size_index
            ]

            unavailable = any(
                text_contains_unavailable_status(
                    status_item
                )
                for status_item
                in status_items
            )

        else:
            status_items = text_items[
                item_index + 1:
                item_index + 12
            ]

            unavailable = False

            for status_item in status_items:
                if html_text_ends_size_section(
                    status_item
                ):
                    break

                if text_contains_last_few_status(
                    status_item
                ):
                    # Yeni Mango səhifəsində bu statusdan sonra
                    # ümumi hidden "not available" mətni gələ bilər.
                    # Ona görə ilk real status mövcuddursa burada dayanırıq.
                    break

                if text_contains_unavailable_status(
                    status_item
                ):
                    unavailable = True
                    break

        new_option = dict(
            option
        )

        new_option[
            "available"
        ] = not unavailable

        result.append(
            new_option
        )

    return unique_size_options(
        result
    )



def html_text_is_color_heading(
    value: str,
) -> bool:
    """
    Mango məhsul detail hissəsində rəng seçim başlığını tanıyır.
    """

    normalized_value = normalize_text(
        value
    )

    if any(
        normalized_value
        == normalize_text(
            heading
        )
        for heading in COLOR_HEADINGS
    ):
        return True

    semantic_patterns = [
        r"^(?:select|choose|pick)\s+(?:a\s+)?colou?r$",
        r"^(?:selecciona|elige)\s+(?:un\s+)?color$",
        r"^(?:bir\s+)?renk\s+(?:secin|seçin|sec|seç)$",
        r"^(?:reng|rəng)\s+(?:secin|seçin|sec|seç)$",
    ]

    return any(
        re.fullmatch(
            pattern,
            normalized_value,
            flags=re.IGNORECASE,
        )
        is not None
        for pattern in semantic_patterns
    )


def _extract_color_product_window(
    text_items: list[str],
    color_heading_index: int,
) -> list[str]:
    """
    Rəng başlığından sonra yalnız əsas məhsul detail hissəsini saxlayır.
    """

    window = []

    for item in text_items[
        color_heading_index + 1:
        color_heading_index + 90
    ]:
        if html_text_ends_size_section(
            item
        ):
            window.append(
                item
            )
            break

        normalized_item = normalize_text(
            item
        )

        hard_end_patterns = [
            "gorunumu goruntule",
            "view the look",
            "ver el look",
            "magazaya ucretsiz gonderim",
            "free delivery to store",
            "detaylari, icerigi ve bakimi",
            "details, composition and care",
            "detalles, composicion y cuidados",
        ]

        if any(
            normalized_item.startswith(
                normalize_text(
                    marker
                )
            )
            for marker
            in hard_end_patterns
        ):
            break

        window.append(
            item
        )

    return window


def extract_color_anchored_size_options_from_html_items(
    text_items: list[str],
    country_code: str,
    is_shoe: bool,
) -> tuple[
    list[dict],
    bool,
]:
    """
    V14 əsas parseri.

    Mango səhifəsində rəng anchor-u varsa, ölçülər yalnız
    həmin product-detail blokundan götürülür.

    Return:
        (options, color_anchor_found)

    color_anchor_found=True olduqda options boş olsa belə
    bütün səhifədə global S/L axtarışı etməməliyik.
    """

    color_heading_indexes = [
        index
        for index, item
        in enumerate(
            text_items
        )
        if html_text_is_color_heading(
            item
        )
    ]

    if not color_heading_indexes:
        return (
            [],
            False,
        )

    candidates = []

    for heading_index in color_heading_indexes:
        product_window = (
            _extract_color_product_window(
                text_items=text_items,
                color_heading_index=heading_index,
            )
        )

        if not product_window:
            continue

        options = (
            extract_modern_size_options_from_html_items(
                text_items=product_window,
                country_code=country_code,
                is_shoe=is_shoe,
            )
        )

        if not options:
            continue

        candidates.append(
            {
                "options": options,
                "heading_index": heading_index,
                "window_length": len(
                    product_window
                ),
            }
        )

    if not candidates:
        return (
            [],
            True,
        )

    candidates.sort(
        key=lambda candidate: (
            -len(
                candidate[
                    "options"
                ]
            ),
            candidate[
                "heading_index"
            ],
            candidate[
                "window_length"
            ],
        )
    )

    return (
        candidates[
            0
        ][
            "options"
        ],
        True,
    )


def extract_modern_size_options_from_html_items(
    text_items: list[str],
    country_code: str,
    is_shoe: bool,
) -> list[dict]:
    """
    2026 Mango məhsul səhifələri üçün heading-siz ölçü parseri.

    Yeni dizaynda "Beden seçin / Select your size" başlığı olmadan
    ölçülər birbaşa məhsul hissəsində göstərilir:

        34
        36
        Mevcut değil
        38
        40
        Mevcut değil
        42
        Ölçüler

    və ya:

        Standart
        ...
        Ekle

    Funksiya bütün səhifədən təsadüfi S/L toplamır.
    Yalnız bir-birinə yaxın və məntiqli ardıcıllıq yaradan
    real ölçü run-larını qiymətləndirir.
    """

    parsed_items: list[
        tuple[int, dict]
    ] = []

    index = 0

    while index < len(
        text_items
    ):
        item = text_items[
            index
        ]

        option = (
            parse_exact_size_from_html_item(
                value=item,
                country_code=country_code,
                is_shoe=is_shoe,
            )
        )

        # ABŞ səhifəsində lokal ölçü və EUR qarşılığı
        # ayrı HTML text node-larında ola bilər:
        # "6.5" + "EUR 37"
        if (
            option is None
            and is_shoe
            and country_code.upper()
            == "US"
        ):
            local_match = re.fullmatch(
                r"\s*(\d{1,2}(?:[.]5)?)\s*",
                normalize_fractional_size_text(
                    clean_html_size_item(
                        item
                    )
                ),
            )

            if (
                local_match
                and index + 1
                < len(
                    text_items
                )
            ):
                eur_match = re.fullmatch(
                    r"\s*(?:EUR|EU)\s*"
                    r"(\d{2}(?:[.]5)?)\s*",
                    normalize_fractional_size_text(
                        text_items[
                            index + 1
                        ]
                    ),
                    flags=re.IGNORECASE,
                )

                if eur_match:
                    local_number = float(
                        local_match.group(
                            1
                        )
                    )

                    if 3 <= local_number <= 15:
                        option = {
                            "size": format_numeric_size(
                                local_match.group(
                                    1
                                )
                            ),
                            "eur_size": format_numeric_size(
                                eur_match.group(
                                    1
                                )
                            ),
                            "available": True,
                        }

                        parsed_items.append(
                            (
                                index,
                                option,
                            )
                        )

                        index += 2
                        continue

        if option is not None:
            parsed_items.append(
                (
                    index,
                    option,
                )
            )

        index += 1

    if not parsed_items:
        return []

    # Standart/one-size ayrıca güclü siqnaldır.
    one_size_candidates = [
        (
            item_index,
            option,
        )
        for item_index, option
        in parsed_items
        if _size_option_kind(
            option
        )
        == "one_size"
    ]

    for (
        item_index,
        option,
    ) in one_size_candidates:
        if _modern_size_end_is_near(
            text_items,
            item_index,
        ):
            one_size_options = (
                _apply_modern_availability(
                    [
                        (
                            item_index,
                            option,
                        )
                    ],
                    text_items,
                )
            )

            if one_size_options:
                one_size_options[
                    0
                ][
                    "size"
                ] = "Standart"

            return one_size_options

    # Digər ölçülər üçün yaxın və ardıcıl run-lar qurulur.
    runs: list[
        list[
            tuple[int, dict]
        ]
    ] = []

    current_run: list[
        tuple[int, dict]
    ] = []

    for (
        item_index,
        option,
    ) in parsed_items:
        if _size_option_kind(
            option
        ) == "one_size":
            continue

        if not current_run:
            current_run = [
                (
                    item_index,
                    option,
                )
            ]
            continue

        previous_index, previous_option = (
            current_run[
                -1
            ]
        )

        close_in_html = (
            1
            <= item_index
            - previous_index
            <= 6
        )

        logical_sequence = (
            _options_can_continue_run(
                previous_option,
                option,
                country_code,
            )
        )

        if (
            close_in_html
            and logical_sequence
        ):
            current_run.append(
                (
                    item_index,
                    option,
                )
            )

        else:
            if len(
                current_run
            ) >= 2:
                runs.append(
                    current_run
                )

            current_run = [
                (
                    item_index,
                    option,
                )
            ]

    if len(
        current_run
    ) >= 2:
        runs.append(
            current_run
        )

    if not runs:
        # Son fallback: ayrıca Standart görünübsə yenə qəbul et.
        if one_size_candidates:
            item_index, option = (
                one_size_candidates[
                    0
                ]
            )

            one_size_options = (
                _apply_modern_availability(
                    [
                        (
                            item_index,
                            option,
                        )
                    ],
                    text_items,
                )
            )

            if one_size_options:
                one_size_options[
                    0
                ][
                    "size"
                ] = "Standart"

            return one_size_options

        return []

    def run_score(
        run: list[
            tuple[int, dict]
        ],
    ) -> tuple[int, int]:
        last_index = run[
            -1
        ][
            0
        ]

        score = (
            len(
                run
            )
            * 20
        )

        if _modern_size_end_is_near(
            text_items,
            last_index,
        ):
            score += 40

        # Daha uzun run əsas üstünlükdür.
        return (
            score,
            len(
                run
            ),
        )

    best_run = max(
        runs,
        key=run_score,
    )

    options = (
        _apply_modern_availability(
            best_run,
            text_items,
        )
    )

    # Təhlükəsizlik limitləri.
    if not (
        2
        <= len(
            options
        )
        <= 15
    ):
        return []

    return options



def extract_size_options_from_html_items(
    text_items: list[str],
    country_code: str,
    is_shoe: bool,
) -> list[dict]:
    """
    "Select your size" başlığından sonrakı dəqiq ölçüləri oxuyur.

    Məhsul səhifəsinin başqa hissəsindəki rəqəmlər
    bu funksiyaya ölçü kimi daxil edilmir.
    """

    candidate_lists = []

    for index, item in enumerate(
        text_items
    ):
        if not html_text_is_size_heading(
            item
        ):
            continue

        options = []

        for next_item in text_items[
            index + 1:
            index + 40
        ]:
            if html_text_ends_size_section(
                next_item
            ):
                break

            option = (
                parse_exact_size_from_html_item(
                    value=next_item,
                    country_code=country_code,
                    is_shoe=is_shoe,
                )
            )

            if option is not None:
                options.append(
                    option
                )

        options = unique_size_options(
            options
        )

        if 1 <= len(
            options
        ) <= 15:
            candidate_lists.append(
                options
            )

    if not candidate_lists:
        return []

    # Ən çox dəqiq ölçü tapılan siyahı istifadə olunur.
    return max(
        candidate_lists,
        key=len,
    )


def fetch_size_options_directly(
    product_url: str,
    country_code: str,
    is_shoe: bool,
) -> list[dict]:
    """
    Playwright DOM-dan asılı olmadan Mango HTML-dən
    ölçüləri birbaşa oxuyur.

    Bu, əsas ölçü mənbəyidir.
    """

    html_text = fetch_mango_html(
        product_url
    )

    parser = OrderedVisibleTextParser()

    parser.feed(
        html_text
    )

    parser.close()

    options = (
        extract_size_options_from_html_items(
            text_items=parser.items,
            country_code=country_code,
            is_shoe=is_shoe,
        )
    )

    # 2026 Mango dizaynında size heading artıq olmaya bilər.
    # V14 prioriteti:
    # 1) Köhnə dəqiq size-heading
    # 2) COLOR ANCHOR -> SIZE RUN
    # 3) Rəng anchor-u ümumiyyətlə yoxdursa general modern fallback
    if not options:
        (
            color_options,
            color_anchor_found,
        ) = (
            extract_color_anchored_size_options_from_html_items(
                text_items=parser.items,
                country_code=country_code,
                is_shoe=is_shoe,
            )
        )

        if color_anchor_found:
            options = color_options

            if options:
                print(
                    f"{country_code.upper()} ölçüləri "
                    "(Mango COLOR ANCHOR): "
                    + ", ".join(
                        get_all_sizes(
                            options
                        )
                    )
                )

        else:
            options = (
                extract_modern_size_options_from_html_items(
                    text_items=parser.items,
                    country_code=country_code,
                    is_shoe=is_shoe,
                )
            )

            if options:
                print(
                    f"{country_code.upper()} ölçüləri "
                    "(Mango modern HTML fallback): "
                    + ", ".join(
                        get_all_sizes(
                            options
                        )
                    )
                )

    DATA_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )

    debug_file = (
        DATA_FOLDER
        / (
            "direct_html_sizes_"
            f"{country_code.upper()}.txt"
        )
    )

    debug_lines = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"URL={product_url}",
        f"COUNTRY={country_code}",
        f"IS_SHOE={is_shoe}",
        "",
        "MATCHED OPTIONS:",
    ]

    for option in options:
        debug_lines.append(
            str(
                option
            )
        )

    debug_lines.extend(
        [
            "",
            "HTML TEXT ITEMS:",
        ]
    )

    debug_lines.extend(
        parser.items
    )

    debug_file.write_text(
        "\n".join(
            debug_lines
        ),
        encoding="utf-8",
    )

    return options


# ============================================================
# ÖLÇÜ BÖLMƏSİNİ AÇMA
# ============================================================

def open_size_selector(
    page: Page,
) -> None:
    """
    Ölçü siyahısı bağlıdırsa açmağa çalışır.
    """

    locators = [
        page.locator(
            'button[data-testid*="size" i]'
        ),
        page.locator(
            'button[class*="size" i]'
        ),
        page.get_by_role(
            "button",
            name=re.compile(
                r"(beden|size|talla|ölçü|olcu)",
                re.IGNORECASE,
            ),
        ),
    ]

    for locator in locators:
        try:
            count = min(
                locator.count(),
                20,
            )

        except Exception:
            continue

        for index in range(
            count
        ):
            try:
                element = locator.nth(
                    index
                )

                if not element.is_visible():
                    continue

                element.click(
                    timeout=1_500
                )

                page.wait_for_timeout(
                    500
                )

                return

            except Exception:
                continue


# ============================================================
# REAL ÖLÇÜ BÖLMƏSİNİN MƏTNİ
# ============================================================

def count_valid_size_tokens(
    section_text: str,
) -> int:
    """
    Mümkün real ölçülərin sayını hesablayır.

    Normal bir məhsulun ölçü siyahısı adətən
    2–15 seçimdən ibarət olur.
    """

    clean_text = normalize_fractional_size_text(
        section_text
    )

    numeric_sizes = re.findall(
        r"(?<![\d.])"
        r"(?:3[0-9]|4[0-9]|50)"
        r"(?:\.5)?"
        r"(?![\d.])",
        clean_text,
    )

    letter_sizes = re.findall(
        r"(?<![A-Z])"
        r"(?:XXXXL|XXXL|XXL|XL|L|M|S|XS|XXS|XXXS)"
        r"(?![A-Z])",
        clean_text,
        flags=re.IGNORECASE,
    )

    return max(
        len(
            numeric_sizes
        ),
        len(
            letter_sizes
        ),
    )


def line_is_size_heading(
    line: str,
) -> bool:
    """
    Sətrin ölçü seçimi başlığı olub-olmadığını yoxlayır.
    """

    normalized_line = normalize_text(
        line
    )

    if any(
        normalized_line
        == normalize_text(
            heading
        )
        for heading in SIZE_HEADINGS
    ):
        return True

    semantic_patterns = [
        r"^(?:select|choose|pick)\b.*\bsize\b$",
        r"^beden\b.*\b(?:sec|seç|secin|seçin|seciniz|seçiniz)\b$",
        r"^(?:selecciona|elige)\b.*\btalla\b$",
        r"^olcu\b.*\bsec\b$",
        r"^ölçü\b.*\bseç\b$",
    ]

    return any(
        re.search(
            pattern,
            normalized_line,
            flags=re.IGNORECASE,
        )
        is not None
        for pattern in semantic_patterns
    )


def line_ends_size_section(
    line: str,
) -> bool:
    """
    Ölçü siyahısının bitdiyi sətri müəyyən edir.
    """

    normalized_line = normalize_text(
        line
    )

    return any(
        normalized_line
        == normalize_text(
            ending
        )
        or normalized_line.startswith(
            normalize_text(
                ending
            )
        )
        for ending in SIZE_SECTION_ENDINGS
    )


def clean_size_section_line(
    line: str,
) -> str:
    """
    Accessibility sıra nömrəsini silir.

    1. 35 -> 35
    2) 36 -> 36
    """

    clean_line = re.sub(
        r"^\s*\d+\s*[.)]\s*",
        "",
        line,
    )

    return re.sub(
        r"\s+",
        " ",
        clean_line,
    ).strip()


def extract_size_section_text(
    body_text: str,
) -> str:
    """
    Yalnız real ölçü seçimi hissəsini çıxarır.

    1. Exact ölçü başlığı tapılır.
    2. Measurements / Ölçüler sətrinə qədər oxunur.
    3. 2–15 real ölçü verən ən qısa hissə seçilir.

    30–50 kimi 21 rəqəmlik nəticə bütün səhifədən
    gəldiyi üçün qəbul edilmir.
    """

    normalized_body = normalize_fractional_size_text(
        body_text
    )

    lines = [
        re.sub(
            r"\s+",
            " ",
            line,
        ).strip()
        for line in normalized_body.splitlines()
        if line.strip()
    ]

    candidates = []

    for heading_index, line in enumerate(
        lines
    ):
        if not line_is_size_heading(
            line
        ):
            continue

        section_lines = []

        for next_line in lines[
            heading_index + 1:
            heading_index + 40
        ]:
            if line_ends_size_section(
                next_line
            ):
                break

            clean_line = clean_size_section_line(
                next_line
            )

            if clean_line:
                section_lines.append(
                    clean_line
                )

        if not section_lines:
            continue

        section_text = "\n".join(
            section_lines
        )

        token_count = count_valid_size_tokens(
            section_text
        )

        if 2 <= token_count <= 15:
            candidates.append(
                {
                    "text": section_text,
                    "token_count": token_count,
                    "length": len(
                        section_text
                    ),
                    "heading_index": (
                        heading_index
                    ),
                }
            )

    if candidates:
        # Ən qısa dəqiq hissə əsas götürülür.
        candidates.sort(
            key=lambda candidate: (
                candidate[
                    "length"
                ],
                candidate[
                    "heading_index"
                ],
            )
        )

        return candidates[
            0
        ][
            "text"
        ]

    # Regex fallback.
    heading_pattern = "|".join(
        re.escape(
            heading
        )
        for heading in SIZE_HEADINGS
    )

    ending_pattern = "|".join(
        re.escape(
            ending
        )
        for ending in SIZE_SECTION_ENDINGS
    )

    pattern = re.compile(
        rf"(?:{heading_pattern})"
        rf"(?P<section>.*?)"
        rf"(?=(?:{ending_pattern})|$)",
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    fallback_candidates = []

    for match in pattern.finditer(
        normalized_body
    ):
        section_text = match.group(
            "section"
        ).strip()

        token_count = count_valid_size_tokens(
            section_text
        )

        if 2 <= token_count <= 15:
            fallback_candidates.append(
                section_text
            )

    if not fallback_candidates:
        return ""

    return min(
        fallback_candidates,
        key=len,
    )


# ============================================================
# DOM-DAN AVAILABILITY MƏLUMATI
# ============================================================

def collect_dom_size_candidates(
    page: Page,
    country_code: str,
    is_shoe: bool,
) -> list[dict]:
    """
    V16 STRUCTURAL SIZE ENGINE.

    Mətnin formatını təxmin etmir.
    Mango DOM-da məhsul detail axınını istifadə edir:

        product
        -> price
        -> color heading
        -> selected color
        -> optional model/fit text
        -> SIZE CONTROL GROUP
        -> Measurements / Ölçüler / Add / Ekle

    Size group daxilindəki label nə olursa olsun götürülür.
    """

    return page.evaluate(
        """
        ({countryCode, isShoe}) => {
            const normalize = (value) => String(
                value || ''
            )
                .toLocaleLowerCase()
                .normalize('NFKD')
                .replace(/[\\u0300-\\u036f]/g, '')
                .replace(/\\s+/g, ' ')
                .trim();

            const textOf = (element) => String(
                element?.innerText
                || element?.textContent
                || element?.getAttribute?.('aria-label')
                || element?.getAttribute?.('title')
                || ''
            )
                .replace(/\\s+/g, ' ')
                .trim();

            const directText = (element) => Array.from(
                element?.childNodes || []
            )
                .filter(
                    (node) => (
                        node.nodeType
                        === Node.TEXT_NODE
                    )
                )
                .map(
                    (node) => node.textContent || ''
                )
                .join(' ')
                .replace(/\\s+/g, ' ')
                .trim();

            const allElements = Array.from(
                document.querySelectorAll(
                    'body *'
                )
            );

            const orderMap = new Map(
                allElements.map(
                    (element, index) => [
                        element,
                        index,
                    ]
                )
            );

            const indexOf = (element) => (
                orderMap.has(element)
                ? orderMap.get(element)
                : -1
            );

            const colorHeadings = [
                'select a color',
                'select a colour',
                'choose a color',
                'choose a colour',
                'pick a color',
                'pick a colour',
                'selecciona un color',
                'elige un color',
                'bir renk seçin',
                'bir renk secin',
                'renk seçin',
                'renk secin',
                'rəng seçin',
                'reng secin'
            ].map(normalize);

            const sizeHeadings = [
                'select your size',
                'select a size',
                'select size',
                'choose your size',
                'choose a size',
                'choose size',
                'selecciona tu talla',
                'selecciona una talla',
                'elige tu talla',
                'elige una talla',
                'beden seçin',
                'beden secin',
                'beden seç',
                'beden sec',
                'beden seçiniz',
                'beden seciniz',
                'ölçünü seç',
                'olcunu sec',
                'ölçü seç',
                'olcu sec'
            ].map(normalize);

            const endingWords = [
                'measurements',
                'size guide',
                'guía de tallas',
                'guia de tallas',
                'ölçüler',
                'olculer',
                'sepete ekle',
                'ekle',
                'add',
                'add to bag',
                'add to wishlist',
                'favori olarak kaydet',
                'beni bilgilendir',
                'notify me',
                'añadir',
                'anadir'
            ].map(normalize);

            const statusWords = [
                'disabled',
                'unavailable',
                'not available',
                'out of stock',
                'sold out',
                'no stock',
                'agotado',
                'no disponible',
                'sin stock',
                'tükendi',
                'stokta yok',
                'mevcut değil',
                'mövcud deyil',
                'stokda yoxdur',
                'last few items',
                'son ürünler',
                'son urunler',
                'últimas unidades',
                'ultimas unidades'
            ].map(normalize);

            const isColorHeadingText = (value) => {
                const text = normalize(value);

                if (
                    colorHeadings.includes(text)
                ) {
                    return true;
                }

                return (
                    /^(select|choose|pick) (a )?colou?r$/.test(text)
                    || /^(selecciona|elige) (un )?color$/.test(text)
                    || /^(bir )?renk (secin|seçin|sec|seç)$/.test(text)
                );
            };

            const isSizeHeadingText = (value) => {
                const text = normalize(value);

                if (
                    sizeHeadings.includes(text)
                ) {
                    return true;
                }

                return (
                    /^(select|choose|pick).*size$/.test(text)
                    || /^beden.*(sec|seç|secin|seçin|seciniz|seçiniz)$/.test(text)
                    || /^(selecciona|elige).*talla$/.test(text)
                );
            };

            const isEndingText = (value) => {
                const text = normalize(value);

                return endingWords.some(
                    (ending) => (
                        text === ending
                        || text.startsWith(
                            ending + ' '
                        )
                    )
                );
            };

            const isStatusText = (value) => {
                const text = normalize(value);

                return statusWords.some(
                    (word) => (
                        text.includes(
                            word
                        )
                    )
                );
            };

            const headingMatches = allElements
                .map(
                    (element) => {
                        const direct = directText(
                            element
                        );

                        const full = textOf(
                            element
                        );

                        return {
                            element,
                            direct,
                            full,
                        };
                    }
                )
                .filter(
                    (item) => {
                        const direct = item.direct;
                        const full = item.full;

                        return (
                            isColorHeadingText(
                                direct
                            )
                            || (
                                full.length <= 80
                                && isColorHeadingText(
                                    full
                                )
                            )
                        );
                    }
                )
                .sort(
                    (left, right) => (
                        indexOf(
                            left.element
                        )
                        - indexOf(
                            right.element
                        )
                    )
                );

            // Köhnə Mango səhifəsi üçün size-heading anchor da fallback-dır.
            const sizeHeadingMatches = allElements
                .map(
                    (element) => ({
                        element,
                        direct: directText(
                            element
                        ),
                        full: textOf(
                            element
                        ),
                    })
                )
                .filter(
                    (item) => (
                        isSizeHeadingText(
                            item.direct
                        )
                        || (
                            item.full.length <= 80
                            && isSizeHeadingText(
                                item.full
                            )
                        )
                    )
                )
                .sort(
                    (left, right) => (
                        indexOf(
                            left.element
                        )
                        - indexOf(
                            right.element
                        )
                    )
                );

            const anchors = (
                headingMatches.length
                ? headingMatches
                : sizeHeadingMatches
            );

            if (!anchors.length) {
                return [];
            }

            const controlSelector = [
                'li',
                'button',
                '[role="option"]',
                '[role="radio"]',
                'label',
                'option'
            ].join(',');

            const groupSelector = [
                'ul',
                'ol',
                '[role="listbox"]',
                '[role="radiogroup"]',
                '[role="group"]',
                'fieldset'
            ].join(',');

            const disabledFor = (element) => {
                const classText = String(
                    element?.className || ''
                ).toLowerCase();

                const statusText = [
                    classText,
                    element?.getAttribute?.(
                        'aria-disabled'
                    ) || '',
                    element?.getAttribute?.(
                        'data-disabled'
                    ) || '',
                    element?.getAttribute?.(
                        'data-stock'
                    ) || '',
                    element?.getAttribute?.(
                        'data-available'
                    ) || '',
                    element?.getAttribute?.(
                        'aria-label'
                    ) || '',
                    element?.getAttribute?.(
                        'title'
                    ) || '',
                ]
                    .join(' ')
                    .toLowerCase();

                return Boolean(
                    element?.disabled
                    || element?.hasAttribute?.(
                        'disabled'
                    )
                    || element?.getAttribute?.(
                        'aria-disabled'
                    ) === 'true'
                    || element?.getAttribute?.(
                        'data-disabled'
                    ) === 'true'
                    || /disabled|unavailable|sold-out|out-of-stock|not-available/.test(
                        statusText
                    )
                );
            };

            const cleanGroupItems = (
                group,
                anchorIndex,
                endIndex
            ) => {
                const raw = Array.from(
                    group.querySelectorAll(
                        controlSelector
                    )
                )
                    .filter(
                        (element) => {
                            const elementIndex = indexOf(
                                element
                            );

                            if (
                                elementIndex <= anchorIndex
                            ) {
                                return false;
                            }

                            if (
                                endIndex >= 0
                                && elementIndex >= endIndex
                            ) {
                                return false;
                            }

                            const text = textOf(
                                element
                            );

                            if (
                                !text
                                || text.length > 90
                                || isColorHeadingText(
                                    text
                                )
                                || isSizeHeadingText(
                                    text
                                )
                                || isEndingText(
                                    text
                                )
                                || isStatusText(
                                    text
                                )
                            ) {
                                return false;
                            }

                            return true;
                        }
                    );

                // Nested li > button kimi duplicate-ləri aradan qaldır.
                const result = [];
                const seen = new Set();

                for (
                    const element
                    of raw
                ) {
                    const text = textOf(
                        element
                    );

                    const key = normalize(
                        text
                    );

                    if (
                        !key
                        || seen.has(
                            key
                        )
                    ) {
                        continue;
                    }

                    // Əgər eyni text ilə daha kiçik nested interactive element
                    // varsa, parent li əvəzinə onu istifadə edirik.
                    const nestedSame = Array.from(
                        element.querySelectorAll(
                            'button,[role="option"],[role="radio"],label'
                        )
                    ).find(
                        (nested) => (
                            normalize(
                                textOf(
                                    nested
                                )
                            )
                            === key
                        )
                    );

                    const chosen = (
                        nestedSame
                        || element
                    );

                    seen.add(
                        key
                    );

                    result.push({
                        element: chosen,
                        text,
                    });
                }

                return result;
            };

            const candidates = [];

            for (
                const anchorMatch
                of anchors
            ) {
                const anchor = (
                    anchorMatch.element
                );

                const anchorIndex = indexOf(
                    anchor
                );

                let ancestor = anchor;

                for (
                    let level = 0;
                    level < 10 && ancestor;
                    level += 1
                ) {
                    const descendantElements = Array.from(
                        ancestor.querySelectorAll(
                            '*'
                        )
                    );

                    const endingElements = descendantElements
                        .filter(
                            (element) => {
                                const elementIndex = indexOf(
                                    element
                                );

                                return (
                                    elementIndex
                                    > anchorIndex
                                    && isEndingText(
                                        textOf(
                                            element
                                        )
                                    )
                                );
                            }
                        )
                        .sort(
                            (left, right) => (
                                indexOf(
                                    left
                                )
                                - indexOf(
                                    right
                                )
                            )
                        );

                    const endElement = (
                        endingElements[
                            0
                        ]
                        || null
                    );

                    const endIndex = (
                        endElement
                        ? indexOf(
                            endElement
                        )
                        : -1
                    );

                    const groups = Array.from(
                        ancestor.querySelectorAll(
                            groupSelector
                        )
                    );

                    for (
                        const group
                        of groups
                    ) {
                        const groupIndex = indexOf(
                            group
                        );

                        if (
                            groupIndex <= anchorIndex
                        ) {
                            continue;
                        }

                        if (
                            endIndex >= 0
                            && groupIndex >= endIndex
                        ) {
                            continue;
                        }

                        const items = cleanGroupItems(
                            group,
                            anchorIndex,
                            endIndex
                        );

                        if (
                            items.length < 1
                            || items.length > 20
                        ) {
                            continue;
                        }

                        // Size group adətən Measurements/Add markerinə
                        // ən yaxın control group-dur.
                        const lastItemIndex = Math.max(
                            ...items.map(
                                (item) => indexOf(
                                    item.element
                                )
                            )
                        );

                        const distanceToEnd = (
                            endIndex >= 0
                            ? Math.max(
                                0,
                                endIndex
                                - lastItemIndex
                            )
                            : 9999
                        );

                        // Rəng swatch group-u adətən daha əvvəldə,
                        // size group isə end markerinə daha yaxındır.
                        const score = (
                            items.length * 100
                            - distanceToEnd
                            - level * 2
                        );

                        candidates.push({
                            items,
                            score,
                            distanceToEnd,
                            anchorIndex,
                        });
                    }

                    ancestor = (
                        ancestor.parentElement
                    );
                }
            }

            if (!candidates.length) {
                return [];
            }

            candidates.sort(
                (left, right) => (
                    right.score
                    - left.score
                )
            );

            const chosen = (
                candidates[
                    0
                ]
            );

            return chosen.items.map(
                (item, position) => ({
                    text: item.text,
                    disabled: disabledFor(
                        item.element
                    ),
                    trustedStructural: true,
                    position,
                })
            );
        }
        """,
        {
            "countryCode": country_code.upper(),
            "isShoe": bool(
                is_shoe
            ),
        },
    )



def parse_dom_size_options(
    dom_candidates: list[dict],
    country_code: str,
    is_shoe: bool,
) -> list[dict]:
    """
    DOM size controls-dan ölçü çıxarır.

    V16-da trustedStructural=True olduqda ölçünün formatı
    əvvəlcədən məhdudlaşdırılmır.
    """

    options = []

    for candidate in dom_candidates:
        candidate_text = (
            normalize_fractional_size_text(
                candidate.get(
                    "text",
                    "",
                )
            )
        )

        available = not bool(
            candidate.get(
                "disabled"
            )
        )

        trusted_structural = bool(
            candidate.get(
                "trustedStructural"
            )
            or candidate.get(
                "trusted_structural"
            )
        )

        if trusted_structural:
            option = (
                parse_trusted_structural_size_label(
                    value=candidate_text,
                    country_code=country_code,
                    is_shoe=is_shoe,
                    available=available,
                )
            )

            if option is not None:
                options.append(
                    option
                )

            continue

        # Köhnə DOM candidate formatı üçün compatibility fallback.
        option = (
            parse_exact_size_from_html_item(
                value=candidate_text,
                country_code=country_code,
                is_shoe=is_shoe,
            )
        )

        if option is not None:
            option[
                "available"
            ] = available

            option[
                "canonical_key"
            ] = (
                make_size_canonical_key(
                    option.get(
                        "size",
                        "",
                    ),
                    option.get(
                        "eur_size",
                        "",
                    ),
                )
            )

            options.append(
                option
            )

    return unique_size_options(
        options
    )



def merge_size_options(
    section_options: list[dict],
    dom_options: list[dict],
) -> list[dict]:
    """
    Real ölçü bölməsini əsas mənbə kimi qəbul edir.

    Vacib qayda:
    - "Select your size / Beden seçin" bölməsində ən azı
      iki ölçü tapılıbsa, yalnız həmin ölçülər saxlanılır.
    - DOM nəticələri yeni ölçü əlavə edə bilməz.
    - DOM yalnız stok statusunu və EUR qarşılığını tamamlayır.

    Bu qayda səhifənin başqa hissələrindən gələn
    30, 31, 43, 45, 46 və s. rəqəmlərin ölçü
    siyahısına düşməsinin qarşısını alır.
    """

    section_options = unique_size_options(
        section_options
    )

    dom_options = unique_size_options(
        dom_options
    )

    # Real məhsul ölçü bölməsində ən azı iki ölçü varsa,
    # bu siyahı whitelist kimi istifadə olunur.
    if len(
        section_options
    ) >= 2:
        dom_by_size = {
            normalize_size(
                option.get(
                    "size",
                    "",
                )
            ): option
            for option in dom_options
            if normalize_size(
                option.get(
                    "size",
                    "",
                )
            )
        }

        merged_options = []

        for section_option in section_options:
            merged_option = dict(
                section_option
            )

            size_key = normalize_size(
                merged_option.get(
                    "size",
                    "",
                )
            )

            matching_dom_option = (
                dom_by_size.get(
                    size_key
                )
            )

            if matching_dom_option is not None:
                merged_option[
                    "available"
                ] = bool(
                    matching_dom_option.get(
                        "available",
                        merged_option.get(
                            "available",
                            True,
                        ),
                    )
                )

                if (
                    not merged_option.get(
                        "eur_size"
                    )
                    and matching_dom_option.get(
                        "eur_size"
                    )
                ):
                    merged_option[
                        "eur_size"
                    ] = matching_dom_option[
                        "eur_size"
                    ]

            merged_options.append(
                merged_option
            )

        return unique_size_options(
            merged_options
        )

    # Mətn bölməsi heç oxunmayıbsa və ya yalnız bir ölçü veribsə,
    # DOM fallback kimi istifadə olunur.
    if dom_options:
        return dom_options

    return section_options


def option_availability_from_dom(
    dom_candidates: list[dict],
    local_size: str,
    eur_size: str,
) -> bool | None:
    """
    DOM-da uyğun ölçünün disabled statusunu tapır.
    """

    normalized_local = normalize_size(
        local_size
    )

    normalized_eur = normalize_size(
        eur_size
    )

    matched_statuses = []

    for candidate in dom_candidates:
        candidate_text = normalize_fractional_size_text(
            candidate.get(
                "text",
                "",
            )
        )

        local_match = re.search(
            rf"(?<![\d.])"
            rf"{re.escape(normalized_local)}"
            rf"(?![\d.])",
            candidate_text.upper(),
        )

        eur_match = False

        if normalized_eur:
            eur_match = bool(
                re.search(
                    rf"\b(?:EUR|EU)\s*"
                    rf"{re.escape(normalized_eur)}"
                    rf"\b",
                    candidate_text,
                    re.IGNORECASE,
                )
            )

        if (
            local_match
            or eur_match
        ):
            matched_statuses.append(
                not bool(
                    candidate.get(
                        "disabled"
                    )
                )
            )

    if not matched_statuses:
        return None

    return any(
        matched_statuses
    )


# ============================================================
# ÖLÇÜLƏRİN PARSE EDİLMƏSİ
# ============================================================

def parse_shoe_size_options(
    section_text: str,
    country_code: str,
) -> list[dict]:
    """
    Ayaqqabı ölçülərini ölkənin lokal formatında oxuyur.

    AZ/TR/ES:
    35, 36, 37...

    US:
    5 (EUR 35)
    6 (EUR 36)
    6.5 (EUR 37)
    """

    section_text = normalize_fractional_size_text(
        section_text
    )

    options = []

    if country_code.upper() == "US":
        pair_pattern = re.compile(
            r"(?<![\d.])"
            r"(\d{1,2}(?:\.5)?)"
            r"\s*\(\s*"
            r"(?:EUR|EU)"
            r"\s*"
            r"(\d{2}(?:\.5)?)"
            r"\s*\)",
            flags=re.IGNORECASE,
        )

        for match in pair_pattern.finditer(
            section_text
        ):
            options.append(
                {
                    "size": format_numeric_size(
                        match.group(
                            1
                        )
                    ),
                    "eur_size": format_numeric_size(
                        match.group(
                            2
                        )
                    ),
                    "available": True,
                }
            )

        return unique_size_options(
            options
        )

    numeric_tokens = re.findall(
        r"(?<![\d.])"
        r"(\d{2}(?:\.5)?)"
        r"(?![\d.])",
        section_text,
    )

    for token in numeric_tokens:
        try:
            numeric_value = float(
                token
            )

        except ValueError:
            continue

        if not (
            30
            <= numeric_value
            <= 50
        ):
            continue

        local_size = format_numeric_size(
            token
        )

        options.append(
            {
                "size": local_size,
                "eur_size": local_size,
                "available": True,
            }
        )

    options = unique_size_options(
        options
    )

    if len(
        options
    ) > 15:
        return []

    return options


def parse_clothing_size_options(
    section_text: str,
) -> list[dict]:
    """
    Geyim və digər məhsulların ölçülərini oxuyur.
    """

    clean_text = normalize_fractional_size_text(
        section_text
    )

    options = []

    # Home kateqoriyalarında 30x50cm, 50x90cm kimi
    # dimension ölçüləri də real size option-dur.
    dimension_pattern = re.compile(
        r"(?<!\d)"
        r"\d{1,4}(?:[.,]\d+)?"
        r"\s*[x×]\s*"
        r"\d{1,4}(?:[.,]\d+)?"
        r"(?:\s*[x×]\s*"
        r"\d{1,4}(?:[.,]\d+)?)?"
        r"\s*(?:cm|mm|m)?"
        r"(?!\w)",
        flags=re.IGNORECASE,
    )

    for match in dimension_pattern.finditer(
        clean_text
    ):
        dimension_option = (
            parse_dimension_size_label(
                match.group(
                    0
                )
            )
        )

        if dimension_option is not None:
            options.append(
                dimension_option
            )

    one_size_pattern = re.compile(
        r"\b(?:"
        r"STANDART|STANDARD|ONE SIZE|ONE-SIZE|"
        r"TALLA ÚNICA|TALLA UNICA|TEK BEDEN|"
        r"TAILLE UNIQUE"
        r")\b",
        re.IGNORECASE,
    )

    if one_size_pattern.search(
        clean_text
    ):
        options.append(
            {
                "size": "Standart",
                "eur_size": "",
                "available": True,
            }
        )

    letter_pattern = re.compile(
        r"(?<![A-Z])"
        r"(?:XXXXL|XXXL|XXL|XL|L|M|S|XS|XXS|XXXS)"
        r"(?![A-Z])",
        re.IGNORECASE,
    )

    for match in letter_pattern.finditer(
        clean_text
    ):
        options.append(
            {
                "size": match.group(
                    0
                ).upper(),
                "eur_size": "",
                "available": True,
            }
        )

    numeric_tokens = re.findall(
        r"(?<![\d.])"
        r"(\d{2}(?:\.5)?)"
        r"(?![\d.])",
        clean_text,
    )

    for token in numeric_tokens:
        try:
            numeric_value = float(
                token
            )

        except ValueError:
            continue

        if not (
            20
            <= numeric_value
            <= 70
        ):
            continue

        options.append(
            {
                "size": format_numeric_size(
                    token
                ),
                "eur_size": "",
                "available": True,
            }
        )

    return unique_size_options(
        options
    )


def get_size_options(
    page: Page,
    country_code: str,
    is_shoe: bool,
) -> list[dict]:
    """
    Məhsul ölçülərini oxuyur.

    Əsas mənbə:
    Mango-nun server HTML-də verdiyi
    "Select your size" bölməsi.

    Playwright DOM yalnız ehtiyat üsuldur.
    """

    # V16: səhifə artıq Playwright-da açıqdır.
    # Əvvəl real DOM control group-u oxuyuruq.
    # Bu yol size text formatından asılı deyil.
    open_size_selector(
        page
    )

    page.wait_for_timeout(
        500
    )

    try:
        structural_dom_candidates = (
            collect_dom_size_candidates(
                page=page,
                country_code=country_code,
                is_shoe=is_shoe,
            )
        )

    except Exception as error:
        structural_dom_candidates = []

        print(
            "Struktur DOM ölçü oxunuşu "
            f"uğursuz oldu: {error}"
        )

    structural_dom_options = (
        parse_dom_size_options(
            dom_candidates=(
                structural_dom_candidates
            ),
            country_code=country_code,
            is_shoe=is_shoe,
        )
    )

    if structural_dom_options:
        print(
            f"{country_code} ölçüləri "
            "(STRUCTURAL DOM V16): "
            + ", ".join(
                get_all_sizes(
                    structural_dom_options
                )
            )
        )

        return structural_dom_options

    try:
        direct_options = (
            fetch_size_options_directly(
                product_url=page.url,
                country_code=country_code,
                is_shoe=is_shoe,
            )
        )

    except Exception as error:
        direct_options = []

        print(
            "Birbaşa HTML ölçü oxunuşu "
            f"uğursuz oldu: {error}"
        )

    if direct_options:
        print(
            f"{country_code} ölçüləri "
            "(birbaşa Mango HTML): "
            + ", ".join(
                get_all_sizes(
                    direct_options
                )
            )
        )

        return direct_options

    open_size_selector(
        page
    )

    page.wait_for_timeout(
        900
    )

    # inner_text bəzi horizontal siyahılarda yalnız ilk ölçünü
    # göstərə bilər. text_content bütün DOM mətnini də oxuyur.
    body_locator = page.locator(
        "body"
    )

    try:
        body_inner_text = (
            body_locator.inner_text()
        )

    except Exception:
        body_inner_text = ""

    try:
        body_text_content = (
            body_locator.text_content()
            or ""
        )

    except Exception:
        body_text_content = ""

    text_sources = [
        body_inner_text,
        body_text_content,
    ]

    section_option_sets = []
    selected_section_texts = []

    for body_text in text_sources:
        section_text = (
            extract_size_section_text(
                body_text
            )
        )

        selected_section_texts.append(
            section_text
        )

        if is_shoe:
            parsed_options = (
                parse_shoe_size_options(
                    section_text=(
                        section_text
                    ),
                    country_code=(
                        country_code
                    ),
                )
            )

        else:
            parsed_options = (
                parse_clothing_size_options(
                    section_text
                )
            )

        section_option_sets.append(
            parsed_options
        )

    section_options = max(
        section_option_sets,
        key=len,
        default=[],
    )

    dom_candidates = (
        collect_dom_size_candidates(
            page=page,
            country_code=country_code,
            is_shoe=is_shoe,
        )
    )

    dom_options = parse_dom_size_options(
        dom_candidates=dom_candidates,
        country_code=country_code,
        is_shoe=is_shoe,
    )

    # Ayaqqabıda real ölçü bölməsində ən azı iki ölçü varsa,
    # yalnız həmin siyahı whitelist kimi qəbul edilir.
    if (
        is_shoe
        and len(
            section_options
        ) >= 2
    ):
        options = merge_size_options(
            section_options=section_options,
            dom_options=dom_options,
        )

    elif (
        is_shoe
        and len(
            dom_options
        ) >= 2
    ):
        options = unique_size_options(
            dom_options
        )

    elif is_shoe:
        # Geniş səhifə DOM-dan təsadüfi 30–50 rəqəmləri
        # götürməkdənsə, etibarsız nəticə qaytarmırıq.
        options = unique_size_options(
            section_options
        )

    else:
        options = merge_size_options(
            section_options=section_options,
            dom_options=dom_options,
        )

    # Stok statusu yalnız artıq təsdiqlənmiş ölçülər üçün yoxlanılır.
    # Burada yeni ölçü əlavə edilmir.
    for option in options:
        dom_available = (
            option_availability_from_dom(
                dom_candidates=(
                    dom_candidates
                ),
                local_size=(
                    option["size"]
                ),
                eur_size=(
                    option.get(
                        "eur_size",
                        "",
                    )
                ),
            )
        )

        if dom_available is not None:
            option[
                "available"
            ] = dom_available

    options = unique_size_options(
        options
    )

    # Ayaqqabıda AZ, TR və ES üçün yalnız real ölçü bölməsində
    # olan 30–50 aralığındakı rəqəmlər saxlanılır.
    if (
        is_shoe
        and country_code.upper()
        in {"AZ", "TR", "ES"}
    ):
        filtered_options = []

        for option in options:
            try:
                numeric_size = float(
                    str(
                        option.get(
                            "size",
                            "",
                        )
                    ).replace(
                        ",",
                        ".",
                    )
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

            if (
                30
                <= numeric_size
                <= 50
            ):
                filtered_options.append(
                    option
                )

        options = unique_size_options(
            filtered_options
        )

    if (
        is_shoe
        and len(
            options
        ) > 15
    ):
        options = []

    DATA_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Hər testdə diaqnostika faylı yazılır.
    debug_file = (
        DATA_FOLDER
        / (
            "size_debug_"
            f"{country_code.upper()}.txt"
        )
    )

    debug_lines = [
        f"SCRIPT_VERSION={SCRIPT_VERSION}",
        f"COUNTRY={country_code}",
        f"IS_SHOE={is_shoe}",
        (
            "SOURCE_PRIORITY="
            "SIZE_SECTION_WHITELIST"
        ),
        "",
        "SELECTED SECTION TEXTS:",
    ]

    for selected_section_text in selected_section_texts:
        debug_lines.append(
            repr(
                selected_section_text
            )
        )

    debug_lines.extend(
        [
            "",
            "SECTION OPTIONS:",
        ]
    )

    for option in section_options:
        debug_lines.append(
            str(
                option
            )
        )

    debug_lines.extend(
        [
            "",
            "DOM CANDIDATES:",
        ]
    )

    for candidate in dom_candidates:
        debug_lines.append(
            str(
                candidate
            )
        )

    debug_lines.extend(
        [
            "",
            "DOM OPTIONS:",
        ]
    )

    for option in dom_options:
        debug_lines.append(
            str(
                option
            )
        )

    debug_lines.extend(
        [
            "",
            "FINAL OPTIONS:",
        ]
    )

    for option in options:
        debug_lines.append(
            str(
                option
            )
        )

    debug_file.write_text(
        "\n".join(
            debug_lines
        ),
        encoding="utf-8",
    )

    print(
        f"Step 04 versiyası: "
        f"{SCRIPT_VERSION}"
    )

    print(
        f"{country_code} ölçüləri: "
        + (
            ", ".join(
                get_all_sizes(
                    options
                )
            )
            or "oxunmadı"
        )
    )

    return options


def get_available_sizes(
    options: list[dict],
) -> list[str]:
    """
    Stokda olan lokal ölçüləri qaytarır.
    """

    return [
        str(
            option["size"]
        )
        for option in options
        if option.get(
            "available"
        )
    ]


def get_all_sizes(
    options: list[dict],
) -> list[str]:
    """
    Bütün görünən lokal ölçüləri qaytarır.
    """

    return [
        str(
            option["size"]
        )
        for option in options
    ]


# ============================================================
# ORİJİNAL SƏHİFƏ
# ============================================================

def inspect_original_product_sizes(
    product_url: str,
) -> dict:
    """
    Orijinal linkin ölçülərini oxuyur.
    """

    country_code = extract_original_country_code(
        product_url
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=HEADLESS,
        )

        context = browser.new_context(
            locale="en-GB",
            viewport={
                "width": 1400,
                "height": 1000,
            },
        )

        page = context.new_page()

        try:
            page.goto(
                product_url,
                wait_until="domcontentloaded",
                timeout=90_000,
            )

            wait_for_mango_product_ready(
                page,
                timeout_ms=6_000,
            )

            dismiss_popups(
                page
            )

            product_name = get_product_name(
                page
            )

            shoe_product = is_shoe_product(
                product_url=product_url,
                product_name=product_name,
            )

            options = get_size_options(
                page=page,
                country_code=country_code,
                is_shoe=shoe_product,
            )

            if not options:
                try:
                    options = (
                        fetch_size_options_directly(
                            product_url=product_url,
                            country_code=country_code,
                            is_shoe=shoe_product,
                        )
                    )

                except Exception:
                    options = []

            return {
                "country_code": country_code,
                "product_name": product_name,
                "is_shoe": shoe_product,
                "size_options": options,
                "available_sizes": (
                    get_available_sizes(
                        options
                    )
                ),
            }

        finally:
            context.close()
            browser.close()


def discover_available_sizes(
    product_url: str,
) -> list[str]:
    """
    Telegram düymələri üçün stok ölçülərini qaytarır.
    """

    print(
        f"Step 04 versiyası: "
        f"{SCRIPT_VERSION}"
    )

    inspection = inspect_original_product_sizes(
        product_url
    )

    return inspection[
        "available_sizes"
    ]


def resolve_requested_option(
    requested_size: str,
    original_options: list[dict],
) -> dict:
    """
    Seçilən ölçünü orijinal variantlarda tapır.
    """

    requested_key = normalize_size(
        requested_size
    )

    for option in original_options:
        if normalize_size(
            option.get(
                "size",
                "",
            )
        ) != requested_key:
            continue

        if not option.get(
            "available"
        ):
            raise ValueError(
                f"{requested_size} ölçüsü stokda deyil."
            )

        return option

    raise ValueError(
        f"{requested_size} ölçüsü "
        "orijinal səhifədə tapılmadı."
    )


MANGO_EU_TO_US_SHOE_MAP = {
    "35": "5",
    "36": "6",
    "37": "6.5",
    "38": "7.5",
    "39": "8.5",
    "40": "9",
    "41": "9.5",
    "42": "10",
}


def match_size_for_country(
    selected_original_option: dict,
    country_options: list[dict],
) -> tuple[
    dict | None,
    str,
]:
    """
    Eyni fiziki ayaqqabı ölçüsünü EUR qarşılığı ilə uyğunlaşdırır.

    Prioritet:
    1. Mango səhifəsində oxunan EUR qarşılığı
    2. US səhifəsində EUR sahəsi boşdursa təhlükəsiz EUR -> US fallback
    3. Eyni lokal label
    """

    requested_eur_size = normalize_size(
        selected_original_option.get(
            "eur_size",
            "",
        )
    )

    if requested_eur_size:
        for option in country_options:
            option_eur_size = normalize_size(
                option.get(
                    "eur_size",
                    "",
                )
            )

            if (
                option_eur_size
                and option_eur_size
                == requested_eur_size
            ):
                return (
                    option,
                    "eur_equivalent",
                )

        # Bəzi Mango US səhifələrində lokal US ölçüsü oxunur,
        # amma EUR metadata ayrıca DOM atributuna düşməyə bilər.
        # Yalnız bütün local option-lar US ayaqqabı diapazonundadırsa
        # bu fallback işə düşür.
        numeric_local_sizes = []

        for option in country_options:
            try:
                numeric_local_sizes.append(
                    float(
                        str(
                            option.get(
                                "size",
                                "",
                            )
                        ).replace(
                            ",",
                            ".",
                        )
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                pass

        looks_like_us_shoe_list = (
            len(
                numeric_local_sizes
            )
            >= 2
            and min(
                numeric_local_sizes
            )
            >= 3
            and max(
                numeric_local_sizes
            )
            <= 15
        )

        if looks_like_us_shoe_list:
            mapped_us_size = (
                MANGO_EU_TO_US_SHOE_MAP.get(
                    requested_eur_size
                )
            )

            if mapped_us_size:
                for option in country_options:
                    if normalize_size(
                        option.get(
                            "size",
                            "",
                        )
                    ) == normalize_size(
                        mapped_us_size
                    ):
                        matched_option = dict(
                            option
                        )

                        matched_option[
                            "eur_size"
                        ] = requested_eur_size

                        return (
                            matched_option,
                            "us_eur_fallback_map",
                        )

    requested_canonical_key = str(
        selected_original_option.get(
            "canonical_key",
            "",
        )
    ).strip()

    if not requested_canonical_key:
        requested_canonical_key = (
            make_size_canonical_key(
                selected_original_option.get(
                    "size",
                    "",
                ),
                selected_original_option.get(
                    "eur_size",
                    "",
                ),
            )
        )

    if requested_canonical_key:
        for option in country_options:
            option_canonical_key = str(
                option.get(
                    "canonical_key",
                    "",
                )
            ).strip()

            if not option_canonical_key:
                option_canonical_key = (
                    make_size_canonical_key(
                        option.get(
                            "size",
                            "",
                        ),
                        option.get(
                            "eur_size",
                            "",
                        ),
                    )
                )

            if (
                option_canonical_key
                and option_canonical_key
                == requested_canonical_key
            ):
                return (
                    option,
                    "canonical_equivalent",
                )

    requested_local_size = normalize_size(
        selected_original_option.get(
            "size",
            "",
        )
    )

    for option in country_options:
        if normalize_size(
            option.get(
                "size",
                "",
            )
        ) == requested_local_size:
            return (
                option,
                "same_label",
            )

    return (
        None,
        "unknown",
    )


# ============================================================
# BİR ÖLKƏNİN YOXLAMASI
# ============================================================

def page_is_unavailable(
    body_text: str,
) -> bool:
    """
    Səhifənin mövcud olmadığını yoxlayır.
    """

    phrases = [
        "page not found",
        "product not found",
        "product is not available",
        "ürün bulunamadı",
        "sayfa bulunamadı",
        "producto no disponible",
    ]

    normalized_body = normalize_text(
        body_text
    )

    return any(
        normalize_text(
            phrase
        ) in normalized_body
        for phrase in phrases
    )


def empty_result(
    country_code: str,
    country_name: str,
    product_code: str,
    original_country_code: str,
    requested_size: str,
    requested_eur_size: str,
    product_url: str,
    product_name: str,
    size_available: str,
    size_match_method: str,
) -> dict:
    """
    Xəta və tapılmayan səhifə üçün boş nəticə.
    """

    return {
        "country_code": country_code,
        "country": country_name,
        "available": "No",
        "product_name": product_name,
        "price": "",
        "currency": "Not found",
        "product_code": product_code,
        "original_country_code": (
            original_country_code
        ),
        "requested_size": requested_size,
        "requested_eur_size": (
            requested_eur_size
        ),
        "matched_size": "",
        "matched_eur_size": "",
        "size_match_method": (
            size_match_method
        ),
        "all_sizes": "",
        "available_sizes": "",
        "size_available": size_available,
        "status_code": "",
        "page_title": "",
        "url": product_url,
    }


def scrape_country(
    browser: Browser,
    country_code: str,
    country_info: dict,
    product_path: str,
    product_code: str,
    original_country_code: str,
    selected_original_option: dict,
    is_shoe: bool,
) -> dict:
    """
    Bir ölkədə məhsulu və uyğun ölçünü yoxlayır.
    """

    country_name = country_info[
        "name"
    ]

    product_url = build_country_url(
        country_code=country_code,
        language=country_info[
            "language"
        ],
        product_path=product_path,
    )

    requested_size = str(
        selected_original_option[
            "size"
        ]
    )

    requested_eur_size = str(
        selected_original_option.get(
            "eur_size",
            "",
        )
    )

    context = browser.new_context(
        locale=country_info[
            "locale"
        ],
        viewport={
            "width": 1400,
            "height": 1000,
        },
    )

    page = context.new_page()

    print(
        f"\n{country_name} yoxlanılır..."
    )

    try:
        response = page.goto(
            product_url,
            wait_until="domcontentloaded",
            timeout=90_000,
        )

        wait_for_mango_product_ready(
            page,
            timeout_ms=6_000,
        )

        dismiss_popups(
            page
        )

        body_text = page.locator(
            "body"
        ).inner_text()

        product_name = get_product_name(
            page
        )

        price_text = get_price_text(
            page
        )

        print(
            f"Oxunan cari qiymət: "
            f"{price_text}"
        )

        price = clean_price(
            price_text
        )

        currency = detect_currency(
            price_text
        )

        status_code = (
            response.status
            if response
            else ""
        )

        final_url = page.url

        product_available = (
            not page_is_unavailable(
                body_text
            )
            and product_name
            != "Not found"
            and price
            is not None
            and currency
            != "Not found"
        )

        if not product_available:
            print(f"DEBUG {country_code} HTTP: {status_code}", flush=True)
            print(f"DEBUG {country_code} URL: {final_url}", flush=True)
            print(f"DEBUG {country_code} TITLE: {page.title()}", flush=True)
            print(f"DEBUG {country_code} BODY: {body_text[:1500]!r}", flush=True)


            
            return empty_result(
                country_code=country_code,
                country_name=country_name,
                product_code=product_code,
                original_country_code=(
                    original_country_code
                ),
                requested_size=requested_size,
                requested_eur_size=(
                    requested_eur_size
                ),
                product_url=final_url,
                product_name="Not found",
                size_available="No",
                size_match_method=(
                    "product_not_found"
                ),
            )

        size_options = get_size_options(
            page=page,
            country_code=country_code,
            is_shoe=is_shoe,
        )

        matched_option, match_method = (
            match_size_for_country(
                selected_original_option=(
                    selected_original_option
                ),
                country_options=size_options,
            )
        )

        if matched_option is None:
            matched_size = ""
            matched_eur_size = ""
            size_available = "Unknown"

        else:
            matched_size = str(
                matched_option.get(
                    "size",
                    "",
                )
            )

            matched_eur_size = str(
                matched_option.get(
                    "eur_size",
                    "",
                )
            )

            size_available = (
                "Yes"
                if matched_option.get(
                    "available"
                )
                else "No"
            )

        print(
            "Bütün ölçülər:",
            ", ".join(
                get_all_sizes(
                    size_options
                )
            )
            or "oxunmadı",
        )

        print(
            "Stok ölçüləri:",
            ", ".join(
                get_available_sizes(
                    size_options
                )
            )
            or "oxunmadı",
        )

        print(
            f"Seçim {requested_size} "
            f"(EUR {requested_eur_size or '-'}) "
            f"→ lokal {matched_size or '-'}"
        )

        return {
            "country_code": country_code,
            "country": country_name,
            "available": "Yes",
            "product_name": product_name,
            "price": price,
            "currency": currency,
            "product_code": product_code,
            "original_country_code": (
                original_country_code
            ),
            "requested_size": requested_size,
            "requested_eur_size": (
                requested_eur_size
            ),
            "matched_size": matched_size,
            "matched_eur_size": (
                matched_eur_size
            ),
            "size_match_method": (
                match_method
            ),
            "all_sizes": " | ".join(
                get_all_sizes(
                    size_options
                )
            ),
            "available_sizes": " | ".join(
                get_available_sizes(
                    size_options
                )
            ),
            "size_available": (
                size_available
            ),
            "status_code": status_code,
            "page_title": page.title(),
            "url": final_url,
        }

    except PlaywrightTimeoutError:
        return empty_result(
            country_code=country_code,
            country_name=country_name,
            product_code=product_code,
            original_country_code=(
                original_country_code
            ),
            requested_size=requested_size,
            requested_eur_size=(
                requested_eur_size
            ),
            product_url=product_url,
            product_name="Timeout",
            size_available="Unknown",
            size_match_method="timeout",
        )

    except Exception as error:
        result = empty_result(
            country_code=country_code,
            country_name=country_name,
            product_code=product_code,
            original_country_code=(
                original_country_code
            ),
            requested_size=requested_size,
            requested_eur_size=(
                requested_eur_size
            ),
            product_url=product_url,
            product_name="Error",
            size_available="Unknown",
            size_match_method="error",
        )

        result["page_title"] = str(
            error
        )

        return result

    finally:
        context.close()


# ============================================================
# CSV
# ============================================================

def save_last_search(
    product_url: str,
    requested_size: str,
) -> None:
    """
    Son linki və ölçünü saxlayır.
    """

    DATA_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )

    LAST_SEARCH_FILE.write_text(
        product_url,
        encoding="utf-8",
    )

    LAST_SIZE_FILE.write_text(
        requested_size,
        encoding="utf-8",
    )


def save_results(
    results: list[dict],
) -> None:
    """
    Müqayisə nəticələrini CSV-yə yazır.
    """

    DATA_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )

    fieldnames = [
        "country_code",
        "country",
        "available",
        "product_name",
        "price",
        "currency",
        "product_code",
        "original_country_code",
        "requested_size",
        "requested_eur_size",
        "matched_size",
        "matched_eur_size",
        "size_match_method",
        "all_sizes",
        "available_sizes",
        "size_available",
        "status_code",
        "page_title",
        "url",
    ]

    with OUTPUT_FILE.open(
        mode="w",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(
            results
        )


# ============================================================
# PARALEL ÖLKƏ WORKER
# ============================================================

def scrape_country_in_own_browser(
    country_code: str,
    country_info: dict,
    product_path: str,
    product_code: str,
    original_country_code: str,
    selected_original_option: dict,
    is_shoe: bool,
) -> tuple[
    str,
    dict,
    float,
]:
    """
    Hər ölkəni ayrıca thread + ayrıca Playwright/browser ilə yoxlayır.

    Sync Playwright obyektləri thread-lər arasında paylaşılmır.
    Buna görə hər worker öz sync_playwright() sessiyasını yaradır.
    """

    started = time.perf_counter()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=HEADLESS,
        )

        try:
            result = scrape_country(
                browser=browser,
                country_code=country_code,
                country_info=country_info,
                product_path=product_path,
                product_code=product_code,
                original_country_code=(
                    original_country_code
                ),
                selected_original_option=(
                    selected_original_option
                ),
                is_shoe=is_shoe,
            )

        finally:
            browser.close()

    elapsed = (
        time.perf_counter()
        - started
    )

    return (
        country_code,
        result,
        elapsed,
    )


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """
    Telegram subprocess üçün sürətli əsas hissə.

    V19:
    - orijinal səhifə ikinci dəfə açılmır
    - AZ / ES / TR paralel yoxlanılır
    """

    workflow_started = time.perf_counter()

    product_url = input(
        "Mango məhsul linkini daxil et: "
    ).strip()

    if not product_url.startswith(
        "https://shop.mango.com/"
    ):
        raise ValueError(
            "Düzgün Mango məhsul linki daxil edilməyib."
        )

    requested_size = input(
        "İstədiyin ölçünü daxil et: "
    ).strip()

    if not requested_size:
        raise ValueError(
            "Ölçü daxil edilməyib."
        )

    print(
        "\nSPEED V19: orijinal ölçü siyahısı "
        "təkrar açılmır və AZ/ES/TR paralel yoxlanılır."
    )

    original_country_code = (
        extract_original_country_code(
            product_url
        )
    )

    product_path = extract_product_path(
        product_url
    )

    product_code = extract_product_code(
        product_url
    )

    shoe_product = is_shoe_product(
        product_url=product_url,
        product_name="",
    )

    requested_eur_size = (
        requested_size
        if shoe_product
        else ""
    )

    selected_option = {
        "size": requested_size,
        "eur_size": requested_eur_size,
        "available": True,
        "canonical_key": (
            make_size_canonical_key(
                requested_size,
                requested_eur_size,
            )
        ),
        "position": 0,
    }

    save_last_search(
        product_url=product_url,
        requested_size=requested_size,
    )

    results_by_country = {}

    max_workers = min(
        3,
        len(
            COUNTRIES
        ),
    )

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:
        future_map = {}

        for (
            country_code,
            country_info,
        ) in COUNTRIES.items():
            future = executor.submit(
                scrape_country_in_own_browser,
                country_code,
                country_info,
                product_path,
                product_code,
                original_country_code,
                selected_option,
                shoe_product,
            )

            future_map[
                future
            ] = country_code

        for future in as_completed(
            future_map
        ):
            country_code = (
                future_map[
                    future
                ]
            )

            try:
                (
                    returned_code,
                    result,
                    elapsed,
                ) = future.result()

                results_by_country[
                    returned_code
                ] = result

                print(
                    f"{returned_code} paralel vaxtı: "
                    f"{elapsed:.2f} saniyə"
                )

            except Exception as error:
                print(
                    f"{country_code} paralel worker xətası: "
                    f"{error}"
                )

                country_info = COUNTRIES[
                    country_code
                ]

                results_by_country[
                    country_code
                ] = empty_result(
                    country_code=country_code,
                    country_name=country_info[
                        "name"
                    ],
                    product_code=product_code,
                    original_country_code=(
                        original_country_code
                    ),
                    requested_size=requested_size,
                    requested_eur_size=(
                        requested_eur_size
                    ),
                    product_url=build_country_url(
                        country_code=country_code,
                        language=country_info[
                            "language"
                        ],
                        product_path=product_path,
                    ),
                    product_name="Error",
                    size_available="Unknown",
                    size_match_method=(
                        "parallel_worker_error"
                    ),
                )

    # CSV və Telegram nəticəsində ölkə sırası əvvəlki kimi qalsın.
    results = [
        results_by_country[
            country_code
        ]
        for country_code in COUNTRIES
        if country_code
        in results_by_country
    ]

    save_results(
        results
    )

    total_seconds = (
        time.perf_counter()
        - workflow_started
    )

    print(
        "\nNəticə yazıldı:"
    )

    print(
        OUTPUT_FILE
    )

    print(
        f"Step04 PARALLEL V19 ümumi vaxt: "
        f"{total_seconds:.2f} saniyə"
    )


if __name__ == "__main__":
    main()
