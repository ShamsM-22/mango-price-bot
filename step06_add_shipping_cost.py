import csv
import json
import re
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

from playwright.sync_api import (
    Browser,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


# ============================================================
# FAYLLAR
# ============================================================

INPUT_FILE = Path(
    "data/country_price_comparison_azn.csv"
)

OUTPUT_FILE = Path(
    "data/final_price_comparison.csv"
)

DEBUG_FOLDER = Path(
    "data/cargo_debug"
)


CACHE_FILE = Path(
    "data/cargo_tariff_cache.json"
)

CACHE_TTL_HOURS = 24
CACHE_SCHEMA_VERSION = 3

SCRIPT_VERSION = (
    "2026-09-23-CARGO-OPEN-RANGE-V3"
)


# ============================================================
# KARGO TARİF MƏNBƏLƏRİ
# ============================================================

# Mənbə adları nəticədə istifadəçiyə göstərilmir.
# Proqram daxildə iki tarif mənbəyini yoxlayır
# və alınan qiymətlərin ortalamasını hesablayır.
CARGO_SOURCES = [
    [
        "https://www.expargo.com/pricing",
    ],
    [
        "https://starexglobal.com/az/",
        "https://starexglobal.com/az/tariffs/",
        "https://starexglobal.com/en/tariffs/",
    ],
]


COUNTRY_ALIASES = {
    "TR": [
        "Turkey",
        "Türkiye",
        "Turkiye",
        "Türkiyə",
        "Türkiyədən çatdırılma",
    ],

    "ES": [
        "Spain",
        "España",
        "Espana",
        "İspaniya",
        "İspaniyadan çatdırılma",
    ],

}


# ============================================================
# MƏHSUL NÖVLƏRİ VƏ TƏXMİNİ ÇƏKİ
# ============================================================

PRODUCT_WEIGHTS = {
    "top": 0.30,
    "blouse": 0.30,
    "shirt": 0.35,
    "tshirt": 0.30,
    "trousers": 0.70,
    "jeans": 0.80,
    "skirt": 0.45,
    "dress": 0.55,
    "sweater": 0.60,
    "cardigan": 0.65,
    "jacket": 1.00,
    "coat": 1.50,
    "shoes": 1.20,
    "bag": 0.80,
    "accessory": 0.20,
    "default": 0.50,
}


PRODUCT_KEYWORDS = {
    "top": [
        "/tops/",
        " top",
        "bluz",
        "asimetrik kombine",
        "asymmetric combined",
        "asimétrico combinado",
    ],

    "blouse": [
        "/blouses/",
        "blouse",
        "blusa",
    ],

    "shirt": [
        "/shirts/",
        "shirt",
        "köynək",
        "koynek",
        "gömlek",
        "gomlek",
        "camisa",
    ],

    "tshirt": [
        "/t-shirts/",
        "t-shirt",
        "tshirt",
        "tee",
    ],

    "trousers": [
        "/trousers/",
        "/pants/",
        "trousers",
        "pants",
        "şalvar",
        "salvar",
        "pantolon",
        "pantalón",
    ],

    "jeans": [
        "/jeans/",
        "jeans",
        "denim",
        "vaquero",
    ],

    "skirt": [
        "/skirts/",
        "skirt",
        "ətək",
        "etek",
        "falda",
    ],

    "dress": [
        "/dresses/",
        "dress",
        "don",
        "elbise",
        "vestido",
    ],

    "sweater": [
        "/sweaters/",
        "sweater",
        "jumper",
        "kazak",
        "jersey",
    ],

    "cardigan": [
        "/cardigans/",
        "cardigan",
        "hırka",
        "hirka",
    ],

    "jacket": [
        "/jackets/",
        "/blazers/",
        "jacket",
        "blazer",
        "ceket",
        "chaqueta",
    ],

    "coat": [
        "/coats/",
        "coat",
        "palto",
        "trench",
        "abrigo",
    ],

    "shoes": [
        "/shoes/",
        "shoes",
        "sneaker",
        "boots",
        "sandals",
        "ayaqqabı",
        "ayakkabı",
        "zapatos",
    ],

    "bag": [
        "/bags/",
        "bag",
        "handbag",
        "çanta",
        "canta",
        "bolso",
    ],

    "accessory": [
        "/accessories/",
        "accessory",
        "aksesuar",
        "belt",
        "scarf",
        "kemer",
    ],
}


# ============================================================
# ÜMUMİ KÖMƏKÇİ FUNKSİYALAR
# ============================================================

def normalize_text(text: str) -> str:
    """
    Mətni müqayisə üçün sadələşdirir.
    """

    normalized = unicodedata.normalize(
        "NFKD",
        str(text).casefold(),
    )

    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )

    return re.sub(
        r"\s+",
        " ",
        normalized,
    ).strip()


def parse_number(
    value: str,
) -> float | None:
    """
    5,10 və 5.10 tipli rəqəmləri float-a çevirir.
    """

    value = (
        str(value)
        .strip()
        .replace(" ", "")
        .replace("\u00a0", "")
    )

    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = (
                value.replace(".", "")
                .replace(",", ".")
            )
        else:
            value = value.replace(",", "")

    elif "," in value:
        value = value.replace(",", ".")

    try:
        return float(value)

    except ValueError:
        return None


def to_float(
    value,
) -> float | None:
    """
    CSV dəyərini float-a çevirir.
    """

    if value is None:
        return None

    clean_value = str(value).strip()

    if clean_value == "":
        return None

    return parse_number(clean_value)


def normalize_size_status(
    value,
) -> str:
    """
    Ölçü mövcudluğu statusunu standartlaşdırır.

    Yes     → ölçü stokdadır
    No      → ölçü stokda deyil
    Unknown → ölçü statusu oxunmayıb
    """

    normalized = normalize_text(
        str(value or "")
    )

    if normalized in {
        "yes",
        "true",
        "1",
        "available",
        "movcuddur",
    }:
        return "Yes"

    if normalized in {
        "no",
        "false",
        "0",
        "unavailable",
        "movcud deyil",
    }:
        return "No"

    return "Unknown"


# ============================================================
# MƏHSUL NÖVÜNÜN AŞKARLANMASI
# ============================================================

def detect_product_type(
    product_name: str,
    product_url: str,
) -> str:
    """
    Məhsulun adı və linkinə əsasən növünü müəyyən edir.
    """

    search_text = normalize_text(
        f"{product_name} {product_url}"
    )

    for product_type, keywords in PRODUCT_KEYWORDS.items():
        for keyword in keywords:
            if normalize_text(keyword) in search_text:
                return product_type

    return "default"


def get_estimated_weight(
    product_type: str,
) -> float:
    """
    Məhsul növünə uyğun təxmini çəkini qaytarır.
    """

    return PRODUCT_WEIGHTS.get(
        product_type,
        PRODUCT_WEIGHTS["default"],
    )


# ============================================================
# CSV-NİN OXUNMASI
# ============================================================

def read_products() -> tuple[list[dict], list[str]]:
    """
    Step 5-də yaradılmış AZN qiymət faylını oxuyur.
    """

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Fayl tapılmadı: {INPUT_FILE}\n"
            "Əvvəl step05_convert_to_azn.py "
            "faylını işə sal."
        )

    with INPUT_FILE.open(
        mode="r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        reader = csv.DictReader(csv_file)

        products = list(reader)
        fieldnames = reader.fieldnames or []

    if not products:
        raise RuntimeError(
            "AZN qiymət müqayisəsi faylı boşdur."
        )

    return products, fieldnames


def build_exchange_rates(
    products: list[dict],
) -> dict[str, float]:
    """
    Əvvəlki CSV faylından AZN məzənnələrini götürür.
    """

    rates = {
        "AZN": 1.0,
    }

    for product in products:
        currency = str(
            product.get(
                "currency",
                "",
            )
        ).upper()

        rate = to_float(
            product.get(
                "exchange_rate"
            )
        )

        if not currency or rate is None:
            continue

        rates[currency] = rate

    return rates


# ============================================================
# KARGO CACHE
# ============================================================

def _empty_cache() -> dict:
    return {
        "version": CACHE_SCHEMA_VERSION,
        "tariff_ranges": {},
        "estimated_rates": {},
    }


def load_cargo_cache() -> dict:
    """
    Diskdə saxlanmış kargo tarif cache-ni oxuyur.
    """

    if not CACHE_FILE.exists():
        return _empty_cache()

    try:
        data = json.loads(
            CACHE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return _empty_cache()

    if not isinstance(
        data,
        dict,
    ):
        return _empty_cache()

    try:
        cache_version = int(
            data.get(
                "version",
                0,
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        return _empty_cache()

    # Parser qaydaları dəyişəndə köhnə, səhv tarifləri
    # avtomatik yenidən istifadə etməmək üçün cache sıfırlanır.
    if cache_version != CACHE_SCHEMA_VERSION:
        return _empty_cache()

    data.setdefault(
        "tariff_ranges",
        {},
    )

    data.setdefault(
        "estimated_rates",
        {},
    )

    return data


def save_cargo_cache(
    cache: dict,
) -> None:
    """
    Cache-ni atomik şəkildə diskə yazır.
    """

    CACHE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = (
        CACHE_FILE.with_suffix(
            ".tmp"
        )
    )

    temporary_file.write_text(
        json.dumps(
            cache,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary_file.replace(
        CACHE_FILE
    )


def cache_timestamp_is_fresh(
    value: str,
) -> bool:
    """
    Cache yazısının 24 saatdan köhnə olub-olmadığını yoxlayır.
    """

    try:
        fetched_at = datetime.fromisoformat(
            str(
                value
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        return False

    return (
        datetime.now()
        - fetched_at
        <= timedelta(
            hours=CACHE_TTL_HOURS
        )
    )


def tariff_cache_key(
    source_number: int,
    country_code: str,
) -> str:
    return (
        f"{source_number}:"
        f"{country_code.upper()}"
    )


def estimate_cache_key(
    country_code: str,
    weight_kg: float,
) -> str:
    return (
        f"{country_code.upper()}:"
        f"{float(weight_kg):.3f}"
    )


def get_cached_tariff_ranges(
    source_number: int,
    country_code: str,
) -> list[dict] | None:
    """
    Mənbə + ölkə üzrə bütün çəki intervalını cache-dən qaytarır.
    """

    cache = load_cargo_cache()

    entry = (
        cache[
            "tariff_ranges"
        ].get(
            tariff_cache_key(
                source_number,
                country_code,
            )
        )
    )

    if not isinstance(
        entry,
        dict,
    ):
        return None

    if not cache_timestamp_is_fresh(
        entry.get(
            "fetched_at",
            "",
        )
    ):
        return None

    ranges = entry.get(
        "ranges"
    )

    if not isinstance(
        ranges,
        list,
    ) or not ranges:
        return None

    return ranges


def save_cached_tariff_ranges(
    source_number: int,
    country_code: str,
    ranges: list[dict],
) -> None:
    """
    Bir səhifədən bütün tarif intervallarını cache-ləyir.
    """

    if not ranges:
        return

    cache = load_cargo_cache()

    cache[
        "tariff_ranges"
    ][
        tariff_cache_key(
            source_number,
            country_code,
        )
    ] = {
        "fetched_at": (
            datetime.now().isoformat(
                timespec="seconds"
            )
        ),
        "ranges": ranges,
    }

    save_cargo_cache(
        cache
    )


def get_cached_estimated_rate(
    country_code: str,
    weight_kg: float,
) -> tuple[
    float,
    int,
] | None:
    """
    Eyni ölkə + çəki üçün əvvəl hesablanmış yekun kargonu qaytarır.
    """

    cache = load_cargo_cache()

    entry = (
        cache[
            "estimated_rates"
        ].get(
            estimate_cache_key(
                country_code,
                weight_kg,
            )
        )
    )

    if not isinstance(
        entry,
        dict,
    ):
        return None

    if not cache_timestamp_is_fresh(
        entry.get(
            "fetched_at",
            "",
        )
    ):
        return None

    try:
        rate = float(
            entry[
                "estimated_shipping_azn"
            ]
        )

        source_count = int(
            entry.get(
                "source_count",
                0,
            )
        )

    except (
        TypeError,
        ValueError,
        KeyError,
    ):
        return None

    return (
        rate,
        source_count,
    )


def save_cached_estimated_rate(
    country_code: str,
    weight_kg: float,
    estimated_shipping_azn: float,
    source_count: int,
) -> None:
    """
    Yekun orta kargo nəticəsini də ayrıca cache-ləyir.
    """

    cache = load_cargo_cache()

    cache[
        "estimated_rates"
    ][
        estimate_cache_key(
            country_code,
            weight_kg,
        )
    ] = {
        "fetched_at": (
            datetime.now().isoformat(
                timespec="seconds"
            )
        ),
        "estimated_shipping_azn": round(
            float(
                estimated_shipping_azn
            ),
            2,
        ),
        "source_count": int(
            source_count
        ),
    }

    save_cargo_cache(
        cache
    )


def bootstrap_rate_from_previous_output(
    country_code: str,
    weight_kg: float,
) -> tuple[
    float,
    int,
] | None:
    """
    Legacy helper. CARGO V3-də normal hesablama axınında istifadə edilmir,
    çünki köhnə parser nəticəsini yenidən cache-ə qaytara bilər.

    Fayl 24 saatdan köhnədirsə istifadə edilmir.
    """

    if not OUTPUT_FILE.exists():
        return None

    try:
        modified_at = datetime.fromtimestamp(
            OUTPUT_FILE.stat().st_mtime
        )

    except OSError:
        return None

    if (
        datetime.now()
        - modified_at
        > timedelta(
            hours=CACHE_TTL_HOURS
        )
    ):
        return None

    try:
        with OUTPUT_FILE.open(
            mode="r",
            encoding="utf-8-sig",
            newline="",
        ) as csv_file:
            rows = list(
                csv.DictReader(
                    csv_file
                )
            )

    except Exception:
        return None

    for row in rows:
        if str(
            row.get(
                "country_code",
                "",
            )
        ).strip().upper() != country_code.upper():
            continue

        previous_weight = to_float(
            row.get(
                "estimated_weight_kg"
            )
        )

        previous_shipping = to_float(
            row.get(
                "estimated_shipping_azn"
            )
        )

        if (
            previous_weight is None
            or previous_shipping is None
            or abs(
                previous_weight
                - weight_kg
            )
            > 0.0005
        ):
            continue

        try:
            source_count = int(
                float(
                    row.get(
                        "shipping_tariff_count",
                        1,
                    )
                    or 1
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            source_count = 1

        save_cached_estimated_rate(
            country_code=country_code,
            weight_kg=weight_kg,
            estimated_shipping_azn=(
                previous_shipping
            ),
            source_count=source_count,
        )

        return (
            previous_shipping,
            source_count,
        )

    return None


def extract_rate_from_ranges(
    ranges: list[dict],
    weight_kg: float,
    exchange_rates: dict[str, float],
) -> float:
    """
    Tarif intervallarından cari çəkinin qiymətini hesablayır.

    Dəstəklənən iki model:
    - fixed: interval üçün sabit məbləğ
    - per_kg: açıq intervalda hər kq üçün tarif
    """

    def calculate_range_cost(
        weight_range: dict,
    ) -> float:
        amount = float(
            weight_range[
                "amount"
            ]
        )

        currency = str(
            weight_range[
                "currency"
            ]
        ).upper()

        billing_mode = str(
            weight_range.get(
                "billing_mode",
                "fixed",
            )
        ).lower()

        if billing_mode == "per_kg":
            amount = (
                amount
                * float(weight_kg)
            )

        return convert_to_azn(
            amount=amount,
            currency=currency,
            exchange_rates=(
                exchange_rates
            ),
        )

    parsed_ranges = []

    for weight_range in ranges:
        try:
            minimum = float(
                weight_range[
                    "minimum"
                ]
            )

            raw_maximum = weight_range.get(
                "maximum"
            )

            maximum = (
                None
                if raw_maximum is None
                else float(raw_maximum)
            )

            # amount/currency burada da yoxlanır ki
            # yarımçıq cache sətri seçimə düşməsin.
            float(
                weight_range[
                    "amount"
                ]
            )
            str(
                weight_range[
                    "currency"
                ]
            )

        except (
            TypeError,
            ValueError,
            KeyError,
        ):
            continue

        parsed_ranges.append(
            (
                minimum,
                maximum,
                weight_range,
            )
        )

    for tolerance in (
        0.0,
        0.005,
    ):
        # Əvvəl qapalı intervalları yoxlayırıq.
        # Beləliklə düz 1.00 kq həm 0.75-1 kq,
        # həm də 1 kq+ kimi görünərsə qapalı interval seçilir.
        for minimum, maximum, weight_range in parsed_ranges:
            if maximum is None:
                continue

            if (
                minimum - tolerance
                <= weight_kg
                <= maximum + tolerance
            ):
                return calculate_range_cost(
                    weight_range
                )

        # Sonra 1 kq+, 1 kq və üzəri və s. açıq intervallar.
        for minimum, maximum, weight_range in parsed_ranges:
            if maximum is not None:
                continue

            if weight_kg >= minimum - tolerance:
                return calculate_range_cost(
                    weight_range
                )

    raise RuntimeError(
        f"{weight_kg:.2f} kq üçün "
        "cache-də uyğun tarif tapılmadı."
    )


def wait_for_cargo_page_ready(
    page: Page,
    timeout_ms: int = 5_000,
) -> None:
    """
    networkidle + 3 saniyə sabit wait əvəzinə,
    səhifənin real mətni gələn kimi davam edir.
    """

    deadline = (
        time.perf_counter()
        + timeout_ms / 1000
    )

    while time.perf_counter() < deadline:
        try:
            body = page.locator(
                "body"
            )

            if (
                body.count()
                > 0
            ):
                body_text = (
                    body.inner_text()
                    or ""
                )

                if len(
                    body_text.strip()
                ) >= 150:
                    page.wait_for_timeout(
                        250
                    )
                    return

        except Exception:
            pass

        page.wait_for_timeout(            150
        )


# ============================================================
# KARGO SƏHİFƏSİ POPUP-LARI
# ============================================================

def dismiss_popups(
    page: Page,
) -> None:
    """
    Cookie və məlumat pəncərələrini bağlamağa çalışır.
    """

    button_names = [
        "Accept",
        "Accept all",
        "Agree",
        "I agree",
        "OK",
        "Got it",
        "Qəbul et",
        "Razıyam",
        "Kabul et",
    ]

    for name in button_names:
        try:
            button = page.get_by_role(
                "button",
                name=re.compile(
                    rf"^{re.escape(name)}$",
                    re.IGNORECASE,
                ),
            ).first

            if button.is_visible(
                timeout=500
            ):
                button.click(
                    timeout=1_500
                )

                page.wait_for_timeout(
                    500
                )

                return

        except Exception:
            continue


# ============================================================
# ÖLKƏNİN KARGO SƏHİFƏSİNDƏ SEÇİLMƏSİ
# ============================================================

def select_country_from_select(
    page: Page,
    aliases: list[str],
) -> bool:
    """
    HTML select sahəsindən ölkəni seçir.
    """

    selects = page.locator(
        "select"
    )

    for select_index in range(
        selects.count()
    ):
        select = selects.nth(
            select_index
        )

        try:
            if not select.is_visible():
                continue

        except Exception:
            continue

        options = select.locator(
            "option"
        )

        for option_index in range(
            options.count()
        ):
            try:
                option_text = (
                    options
                    .nth(option_index)
                    .inner_text()
                    .strip()
                )

            except Exception:
                continue

            normalized_option = normalize_text(
                option_text
            )

            for alias in aliases:
                normalized_alias = normalize_text(
                    alias
                )

                if (
                    normalized_option
                    == normalized_alias
                    or normalized_alias
                    in normalized_option
                ):
                    try:
                        select.select_option(
                            index=option_index
                        )

                        page.wait_for_timeout(
                            350
                        )

                        return True

                    except Exception:
                        continue

    return False


def click_country_element(
    page: Page,
    aliases: list[str],
) -> bool:
    """
    Ölkə düyməsinə, linkinə və ya tabına klik edir.
    """

    selectors = [
        "button",
        "a",
        '[role="tab"]',
        '[role="button"]',
    ]

    for selector in selectors:
        elements = page.locator(
            selector
        )

        for index in range(
            elements.count()
        ):
            element = elements.nth(
                index
            )

            try:
                if not element.is_visible():
                    continue

                element_text = (
                    element
                    .inner_text()
                    .strip()
                )

            except Exception:
                continue

            normalized_element = normalize_text(
                element_text
            )

            for alias in aliases:
                normalized_alias = normalize_text(
                    alias
                )

                if (
                    normalized_element
                    == normalized_alias
                    or normalized_alias
                    in normalized_element
                ):
                    try:
                        element.scroll_into_view_if_needed()

                        element.click(
                            timeout=3_000
                        )

                        page.wait_for_timeout(
                            350
                        )

                        return True

                    except Exception:
                        continue

    return False


def choose_country(
    page: Page,
    country_code: str,
) -> bool:
    """
    Kargo səhifəsində ölkəni seçir.
    """

    aliases = COUNTRY_ALIASES[
        country_code
    ]

    if select_country_from_select(
        page,
        aliases,
    ):
        return True

    return click_country_element(
        page,
        aliases,
    )


# ============================================================
# PUL DƏYƏRLƏRİNİN OXUNMASI
# ============================================================

def extract_money_values(
    text: str,
) -> list[tuple[float, str]]:
    """
    Mətndən pul məbləğlərini çıxarır.
    """

    patterns = [
        (
            r"(?:AZN|₼)\s*"
            r"([0-9]+(?:[.,][0-9]+)?)",
            "AZN",
        ),

        (
            r"([0-9]+(?:[.,][0-9]+)?)"
            r"\s*(?:AZN|₼)",
            "AZN",
        ),

        (
            r"(?:USD|US\$|\$)\s*"
            r"([0-9]+(?:[.,][0-9]+)?)",
            "USD",
        ),

        (
            r"([0-9]+(?:[.,][0-9]+)?)"
            r"\s*(?:USD|US\$|\$)",
            "USD",
        ),

        (
            r"(?:EUR|€)\s*"
            r"([0-9]+(?:[.,][0-9]+)?)",
            "EUR",
        ),

        (
            r"([0-9]+(?:[.,][0-9]+)?)"
            r"\s*(?:EUR|€)",
            "EUR",
        ),

        (
            r"(?:TRY|TL|₺)\s*"
            r"([0-9]+(?:[.,][0-9]+)?)",
            "TRY",
        ),

        (
            r"([0-9]+(?:[.,][0-9]+)?)"
            r"\s*(?:TRY|TL|₺)",
            "TRY",
        ),
    ]

    values = []

    for pattern, currency in patterns:
        for match in re.finditer(
            pattern,
            text,
            re.IGNORECASE,
        ):
            amount = parse_number(
                match.group(1)
            )

            if amount is None:
                continue

            if 0 < amount < 1_000:
                values.append(
                    (
                        amount,
                        currency,
                    )
                )

    return values


def choose_money_value(
    money_values: list[tuple[float, str]],
) -> tuple[float, str] | None:
    """
    Mümkün olduqda AZN qiymətinə üstünlük verir.
    """

    if not money_values:
        return None

    azn_values = [
        value
        for value in money_values
        if value[1] == "AZN"
    ]

    if azn_values:
        return azn_values[0]

    return money_values[0]


# ============================================================
# ÇƏKİ İNTERVALLARININ OXUNMASI
# ============================================================

def find_weight_ranges(
    page_text: str,
) -> list[dict]:
    """
    Kiloqram və qram ilə yazılmış tarif intervallarını tapır.

    Həm qapalı intervalları (məs. 0.75-1 kq),
    həm də açıq intervalları (məs. 1 kq+, 1 kq və üzəri)
    tanıyır. Açıq intervalda "hər kq" / "/kg" kimi qeyd
    varsa tarif per_kg kimi saxlanılır.
    """

    clean_text = re.sub(
        r"\s+",
        " ",
        page_text,
    )

    range_patterns = [
        (
            re.compile(
                r"(?P<min>\d+(?:[.,]\d+)?)"
                r"\s*(?:kg|kq)"
                r"\s*(?:-|–|—|to)"
                r"\s*(?P<max>\d+(?:[.,]\d+)?)"
                r"\s*(?:kg|kq)",
                re.IGNORECASE,
            ),
            1.0,
        ),

        (
            re.compile(
                r"(?P<min>\d+(?:[.,]\d+)?)"
                r"\s*(?:-|–|—|to)"
                r"\s*(?P<max>\d+(?:[.,]\d+)?)"
                r"\s*(?:kg|kq)",
                re.IGNORECASE,
            ),
            1.0,
        ),

        (
            re.compile(
                r"(?P<min>\d+(?:[.,]\d+)?)"
                r"\s*(?:g|gr|qr|qram)"
                r"\s*(?:-|–|—|to)"
                r"\s*(?P<max>\d+(?:[.,]\d+)?)"
                r"\s*(?:g|gr|qr|qram)",
                re.IGNORECASE,
            ),
            0.001,
        ),

        (
            re.compile(
                r"(?P<min>\d+(?:[.,]\d+)?)"
                r"\s*(?:-|–|—|to)"
                r"\s*(?P<max>\d+(?:[.,]\d+)?)"
                r"\s*(?:g|gr|qr|qram)",
                re.IGNORECASE,
            ),
            0.001,
        ),
    ]

    # 1 kq +, 1 kg+, 1 kq və üzəri, 1 kg ve üzeri,
    # 1 kg and above / or more kimi formalar.
    open_range_pattern = re.compile(
        r"(?P<min>\d+(?:[.,]\d+)?)"
        r"\s*(?:kg|kq)\s*"
        r"(?:"
        r"\+"
        r"|və\s+(?:üzəri|yuxarı)"
        r"|ve\s+(?:üzeri|uzeri|yukarı|yukari)"
        r"|(?:və|ve)?\s*(?:üzəri|üzeri|uzeri)"
        r"|and\s+(?:above|over|up)"
        r"|or\s+more"
        r"|(?:-?dan|-?dən)\s+(?:yuxarı|yuxari|çox|cox)"
        r")",
        re.IGNORECASE,
    )

    matches = []

    for pattern, multiplier in range_patterns:
        for match in pattern.finditer(
            clean_text
        ):
            minimum = parse_number(
                match.group("min")
            )

            maximum = parse_number(
                match.group("max")
            )

            if minimum is None or maximum is None:
                continue

            matches.append(
                {
                    "start": match.start(),
                    "end": match.end(),
                    "minimum": minimum * multiplier,
                    "maximum": maximum * multiplier,
                    "open_ended": False,
                }
            )

    for match in open_range_pattern.finditer(
        clean_text
    ):
        minimum = parse_number(
            match.group("min")
        )

        if minimum is None:
            continue

        matches.append(
            {
                "start": match.start(),
                "end": match.end(),
                "minimum": minimum,
                "maximum": None,
                "open_ended": True,
            }
        )

    matches.sort(
        key=lambda item: item["start"]
    )

    unique_matches = []

    for item in matches:
        duplicate = any(
            abs(
                existing["minimum"]
                - item["minimum"]
            ) < 0.0001
            and (
                (
                    existing["maximum"] is None
                    and item["maximum"] is None
                )
                or (
                    existing["maximum"] is not None
                    and item["maximum"] is not None
                    and abs(
                        existing["maximum"]
                        - item["maximum"]
                    ) < 0.0001
                )
            )
            and abs(
                existing["start"]
                - item["start"]
            ) < 5
            for existing in unique_matches
        )

        if not duplicate:
            unique_matches.append(
                item
            )

    results = []

    for index, item in enumerate(
        unique_matches
    ):
        if index + 1 < len(
            unique_matches
        ):
            next_start = unique_matches[
                index + 1
            ]["start"]

        else:
            next_start = min(
                len(clean_text),
                item["end"] + 220,
            )

        # Tarifi interval etiketinə mümkün qədər yaxın saxlayırıq.
        # Beləliklə səhifənin sonrakı hissəsindəki başqa AZN məbləği
        # təsadüfən kargo tarifi kimi seçilmir.
        segment = clean_text[
            item["end"]:next_start
        ][:180]

        money_values = extract_money_values(
            segment
        )

        chosen_value = choose_money_value(
            money_values
        )

        if chosen_value is None:
            continue

        amount, currency = chosen_value

        normalized_segment = normalize_text(
            segment
        )

        per_kg_markers = (
            "/kg",
            "/ kg",
            "/kq",
            "/ kq",
            "per kg",
            "per kq",
            "hər kq",
            "her kq",
            "hər kg",
            "her kg",
            "kq üçün",
            "kq ucun",
            "kg üçün",
            "kg ucun",
        )

        is_per_kg = any(
            marker in normalized_segment
            for marker in per_kg_markers
        )

        results.append(
            {
                "minimum": item["minimum"],
                "maximum": item["maximum"],
                "amount": amount,
                "currency": currency,
                "billing_mode": (
                    "per_kg"
                    if item["open_ended"] and is_per_kg
                    else "fixed"
                ),
            }
        )

    return results


def get_country_section(
    page_text: str,
    country_code: str,
) -> str:
    """
    Səhifədə ölkəyə aid tarif bölməsini tapmağa çalışır.
    """

    lines = [
        line.strip()
        for line in page_text.splitlines()
        if line.strip()
    ]

    aliases = COUNTRY_ALIASES[
        country_code
    ]

    candidate_sections = []

    for index, line in enumerate(
        lines
    ):
        normalized_line = normalize_text(
            line
        )

        for alias in aliases:
            normalized_alias = normalize_text(
                alias
            )

            if normalized_alias in normalized_line:
                section = "\n".join(
                    lines[index:index + 100]
                )

                range_count = len(
                    find_weight_ranges(
                        section
                    )
                )

                candidate_sections.append(
                    (
                        range_count,
                        section,
                    )
                )

                break

    if not candidate_sections:
        return page_text

    candidate_sections.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    best_range_count, best_section = (
        candidate_sections[0]
    )

    if best_range_count == 0:
        return page_text

    return best_section


# ============================================================
# VALYUTANIN AZN-Ə ÇEVRİLMƏSİ
# ============================================================

def convert_to_azn(
    amount: float,
    currency: str,
    exchange_rates: dict[str, float],
) -> float:
    """
    Kargo qiymətini AZN-ə çevirir.
    """

    if currency == "AZN":
        return round(
            amount,
            2,
        )

    exchange_rate = exchange_rates.get(
        currency
    )

    if exchange_rate is None:
        raise RuntimeError(
            f"{currency} üçün AZN məzənnəsi tapılmadı."
        )

    return round(
        amount * exchange_rate,
        2,
    )


def extract_rate_for_weight(
    page_text: str,
    country_code: str,
    weight_kg: float,
    exchange_rates: dict[str, float],
) -> float:
    """
    Məhsulun çəkisinə uyğun tarifi seçir.

    Hesablama eyni qaydanı həm canlı səhifə,
    həm də cache üçün istifadə edir.
    """

    country_section = get_country_section(
        page_text,
        country_code,
    )

    ranges = find_weight_ranges(
        country_section
    )

    return extract_rate_from_ranges(
        ranges=ranges,
        weight_kg=weight_kg,
        exchange_rates=exchange_rates,
    )


# ============================================================
# KARGO KALKULYATORUNUN EHTİYAT VARİANTI
# ============================================================

def find_weight_input(
    page: Page,
):
    """
    Kalkulyator mövcuddursa çəki inputunu tapır.
    """

    inputs = page.locator(
        "input"
    )

    weight_words = [
        "weight",
        "çəki",
        "ceki",
        "kg",
        "kilogram",
    ]

    for index in range(
        inputs.count()
    ):
        input_element = inputs.nth(
            index
        )

        try:
            if not input_element.is_visible():
                continue

            metadata = input_element.evaluate(
                """
                element => {
                    const labels = element.labels
                        ? Array.from(element.labels)
                            .map(label => label.innerText)
                            .join(" ")
                        : "";

                    const parentText = element.parentElement
                        ? element.parentElement.innerText
                        : "";

                    return [
                        element.name || "",
                        element.id || "",
                        element.placeholder || "",
                        element.getAttribute("aria-label") || "",
                        labels,
                        parentText.slice(0, 200)
                    ].join(" ");
                }
                """
            )

            normalized_metadata = normalize_text(
                metadata
            )

            if any(
                normalize_text(word)
                in normalized_metadata
                for word in weight_words
            ):
                return input_element

        except Exception:
            continue

    return None


def extract_calculator_money_value(
    changed_lines: list[str],
) -> tuple[float, str] | None:
    """
    Kalkulyator nəticəsindən yalnız çatdırılma qiyməti ilə
    əlaqəli sətrlərdəki pul məbləğini qəbul edir.

    Məqsəd: səhifədə sonradan görünən endirim, balans,
    minimum ödəniş və s. rəqəmlərin kargo kimi götürülməməsi.
    """

    result_keywords = [
        "delivery",
        "shipping",
        "cargo",
        "kargo",
        "çatdırılma",
        "catdirilma",
        "daşınma",
        "dasinma",
        "cost",
        "price",
        "qiymət",
        "qiymet",
        "məbləğ",
        "mebleg",
        "total",
        "yekun",
    ]

    relevant_lines = []

    for index, line in enumerate(
        changed_lines
    ):
        normalized_line = normalize_text(
            line
        )

        if not any(
            normalize_text(keyword)
            in normalized_line
            for keyword in result_keywords
        ):
            continue

        start = max(
            0,
            index - 1,
        )

        end = min(
            len(changed_lines),
            index + 3,
        )

        relevant_lines.extend(
            changed_lines[
                start:end
            ]
        )

    if not relevant_lines:
        return None

    # Sıralamanı saxlayaraq təkrarlanan sətrləri çıxarırıq.
    unique_lines = list(
        dict.fromkeys(
            relevant_lines
        )
    )

    money_values = extract_money_values(
        "\n".join(
            unique_lines
        )
    )

    if not money_values:
        return None

    unique_money_values = []

    for amount, currency in money_values:
        value = (
            round(
                float(amount),
                4,
            ),
            str(currency).upper(),
        )

        if value not in unique_money_values:
            unique_money_values.append(
                value
            )

    # Eyni nəticə blokunda bir neçə fərqli AZN məbləği varsa
    # hansının çatdırılma haqqı olduğunu təxmin etmirik.
    azn_values = [
        value
        for value in unique_money_values
        if value[1] == "AZN"
    ]

    if len(azn_values) > 1:
        return None

    return choose_money_value(
        unique_money_values
    )


def try_calculator(
    page: Page,
    weight_kg: float,
    exchange_rates: dict[str, float],
) -> float | None:
    """
    Tarif cədvəli olmadıqda kalkulyatoru doldurmağa çalışır.

    Nəticə yalnız çatdırılma qiyməti olduğu aydın olan
    dəyişmiş sətrlərdən götürülür. Şübhəli nəticə qəbul edilmir.
    """

    weight_input = find_weight_input(
        page
    )

    if weight_input is None:
        return None

    before_text = page.locator(
        "body"
    ).inner_text()

    try:
        weight_input.scroll_into_view_if_needed()

        weight_input.click()

        weight_input.fill(
            str(weight_kg)
        )

    except Exception:
        return None

    calculate_names = [
        "Calculate",
        "Calculate price",
        "Hesabla",
        "Hesapla",
    ]

    clicked = False

    for name in calculate_names:
        try:
            button = page.get_by_role(
                "button",
                name=re.compile(
                    name,
                    re.IGNORECASE,
                ),
            ).first

            if button.is_visible(
                timeout=500
            ):
                button.click(
                    timeout=2_000
                )

                clicked = True
                break

        except Exception:
            continue

    if not clicked:
        return None

    page.wait_for_timeout(
        800
    )

    after_text = page.locator(
        "body"
    ).inner_text()

    before_lines = {
        line.strip()
        for line in before_text.splitlines()
        if line.strip()
    }

    changed_lines = [
        line.strip()
        for line in after_text.splitlines()
        if line.strip()
        and line.strip() not in before_lines
    ]

    chosen_value = (
        extract_calculator_money_value(
            changed_lines
        )
    )

    if chosen_value is None:
        return None

    amount, currency = chosen_value

    return convert_to_azn(
        amount=amount,
        currency=currency,
        exchange_rates=exchange_rates,
    )


# ============================================================
# DEBUG FAYLLARI
# ============================================================

def save_debug_files(
    page: Page,
    source_number: int,
    country_code: str,
) -> None:
    """
    Səhifənin quruluşu dəyişərsə
    yoxlama faylları saxlayır.
    """

    DEBUG_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = (
        f"cargo_source_{source_number}_"
        f"{country_code.lower()}"
    )

    try:
        page.screenshot(
            path=str(
                DEBUG_FOLDER
                / f"{filename}.png"
            ),
            full_page=True,
        )

    except Exception:
        pass

    try:
        page_text = page.locator(
            "body"
        ).inner_text()

        (
            DEBUG_FOLDER
            / f"{filename}.txt"
        ).write_text(
            page_text,
            encoding="utf-8",
        )

    except Exception:
        pass


# ============================================================
# CANLI KARGO TARİFİNİN ALINMASI
# ============================================================

def get_rate_from_source(
    browser: Browser,
    source_urls: list[str],
    source_number: int,
    country_code: str,
    weight_kg: float,
    exchange_rates: dict[str, float],
) -> float:
    """
    Bir tarif mənbəyindən kargo qiyməti götürür.

    CARGO V3 prioriteti:
    1. Cari parser versiyasının tarif cache-i
    2. Canlı səhifədə tarif intervalları
    3. Yalnız etibarlı nəticə verən kalkulyator fallback
    """

    cached_ranges = (
        get_cached_tariff_ranges(
            source_number=source_number,
            country_code=country_code,
        )
    )

    if cached_ranges:
        try:
            rate = extract_rate_from_ranges(
                ranges=cached_ranges,
                weight_kg=weight_kg,
                exchange_rates=exchange_rates,
            )

            print(
                f"      Mənbə {source_number}: "
                "tarif cache-dən alındı."
            )

            return rate

        except RuntimeError:
            # Cache-də bu çəki intervalı yoxdursa canlı mənbəni yenilə.
            pass

    last_error = None

    for url in source_urls:
        context = browser.new_context(
            locale="az-AZ",
            viewport={
                "width": 1400,
                "height": 1000,
            },
        )

        page = context.new_page()

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=45_000,
            )

            wait_for_cargo_page_ready(
                page,
                timeout_ms=5_000,
            )

            dismiss_popups(
                page
            )

            choose_country(
                page,
                country_code,
            )

            page.wait_for_timeout(
                450
            )

            page_text = page.locator(
                "body"
            ).inner_text()

            country_section = (
                get_country_section(page_text,
                    country_code,
                )
            )

            ranges = find_weight_ranges(
                country_section
            )

            if ranges:
                save_cached_tariff_ranges(
                    source_number=source_number,
                    country_code=country_code,
                    ranges=ranges,
                )

                try:
                    return extract_rate_from_ranges(
                        ranges=ranges,
                        weight_kg=weight_kg,
                        exchange_rates=exchange_rates,
                    )

                except RuntimeError:
                    pass

            # Mövcud parser full page ilə daha yaxşı işləyirsə saxlayırıq.
            try:
                rate = extract_rate_for_weight(
                    page_text=page_text,
                    country_code=country_code,
                    weight_kg=weight_kg,
                    exchange_rates=exchange_rates,
                )

                return rate

            except RuntimeError:
                calculator_rate = try_calculator(
                    page=page,
                    weight_kg=weight_kg,
                    exchange_rates=exchange_rates,
                )

                if calculator_rate is not None:
                    return calculator_rate

                raise

        except Exception as error:
            last_error = error

            save_debug_files(
                page=page,
                source_number=source_number,
                country_code=country_code,
            )

        finally:
            context.close()

    raise RuntimeError(
        str(last_error)
        if last_error
        else "Tarif mənbəyi oxunmadı."
    )



def calculate_estimated_shipping(
    browser: Browser,
    country_code: str,
    weight_kg: float,
    exchange_rates: dict[str, float],
) -> tuple[float, int]:
    """
    Mövcud tariflərin ortalamasını hesablayır.

    CARGO V3:
    - AZ həmişə 0
    - yalnız cari parser versiyasının cache-i istifadə olunur
    - köhnə final CSV-dən kargo bootstrap edilmir
    - cache yoxdursa source-level canlı tarif yoxlanılır
    """

    if country_code == "AZ":
        return 0.0, 0

    cached_estimate = (
        get_cached_estimated_rate(
            country_code=country_code,
            weight_kg=weight_kg,
        )
    )

    if cached_estimate is not None:
        print(
            "   Kargo cache-dən alındı ⚡"
        )

        return cached_estimate

    live_rates = []

    print(
        "   Kargo tarifləri canlı yoxlanılır..."
    )

    for source_number, source_urls in enumerate(
        CARGO_SOURCES,
        start=1,
    ):
        source_started = (
            time.perf_counter()
        )

        try:
            rate = get_rate_from_source(
                browser=browser,
                source_urls=source_urls,
                source_number=source_number,
                country_code=country_code,
                weight_kg=weight_kg,
                exchange_rates=exchange_rates,
            )

            live_rates.append(
                rate
            )

            print(
                f"      Mənbə {source_number}: "
                f"{time.perf_counter() - source_started:.2f} san"
            )

        except RuntimeError:
            print(
                f"      Mənbə {source_number}: "
                "tarif alınmadı."
            )

            continue

    if not live_rates:
        raise RuntimeError(
            "Canlı kargo tarifi alınmadı."
        )

    estimated_shipping = round(
        mean(
            live_rates
        ),
        2,
    )

    source_count = len(
        live_rates
    )

    save_cached_estimated_rate(
        country_code=country_code,
        weight_kg=weight_kg,
        estimated_shipping_azn=(
            estimated_shipping
        ),
        source_count=source_count,
    )

    return (
        estimated_shipping,
        source_count,
    )




# ============================================================
# QEYDLƏR
# ============================================================

def make_shipping_note(
    product_type: str,
    weight_kg: float,
    source_count: int,
) -> str:
    """
    Təxmini kargo hesablanması barədə qeyd yaradır.
    """

    if source_count == 0:
        return (
            "Azərbaycan daxili qiymət olduğu üçün "
            "beynəlxalq kargo xərci əlavə edilməyib."
        )

    if source_count == 1:
        source_text = (
            "mövcud canlı kargo tarifinə"
        )

    else:
        source_text = (
            f"{source_count} canlı kargo tarifinin "
            "ortalamasına"
        )

    return (
        f"{product_type} məhsulu üçün "
        f"{weight_kg:.2f} kq təxmini bağlama çəkisi və "
        f"{source_text} əsasən hesablanıb."
    )


def make_size_note(
    requested_size: str,
    size_status: str,
    available_sizes: str,
) -> str:
    """
    Seçilmiş ölçünün statusu barədə qeyd yaradır.
    """

    if size_status == "Yes":
        return (
            f"{requested_size} ölçüsü stokdadır."
        )

    if size_status == "No":
        note = (
            f"{requested_size} ölçüsü bu ölkədə "
            "stokda deyil."
        )

        if available_sizes:
            note += (
                f" Stokda olan ölçülər: "
                f"{available_sizes}."
            )

        return note

    return (
        f"{requested_size} ölçüsünün stok vəziyyəti "
        "dəqiq müəyyən edilmədi."
    )


# ============================================================
# YEKUN HESABLAMA
# ============================================================

def calculate_final_prices(
    browser: Browser,
    products: list[dict],
    exchange_rates: dict[str, float],
) -> list[dict]:
    """
    Məhsul növünü, çəkini, ölçü statusunu,
    təxmini kargonu və yekun qiyməti hesablayır.
    """

    results = []

    for product in products:
        product["product_type"] = ""
        product["estimated_weight_kg"] = ""
        product["estimated_shipping_azn"] = ""
        product["shipping_tariff_count"] = ""
        product["shipping_estimate_note"] = ""
        product["size_status_note"] = ""
        product["eligible_for_comparison"] = "No"
        product["final_cost_azn"] = ""
        product["difference_vs_azerbaijan"] = ""
        product["rank"] = ""

        product_available = (
            str(
                product.get(
                    "available",
                    "",
                )
            ).strip()
            == "Yes"
        )

        price_azn = to_float(
            product.get(
                "price_azn"
            )
        )

        country = str(
            product.get(
                "country",
                "",
            )
        )

        country_code = str(
            product.get(
                "country_code",
                "",
            )
        ).upper()

        requested_size = str(
            product.get(
                "requested_size",
                "",
            )
        ).strip()

        available_sizes = str(
            product.get(
                "available_sizes",
                "",
            )
        ).strip()

        size_status = normalize_size_status(
            product.get(
                "size_available"
            )
        )

        product_type = detect_product_type(
            product_name=str(
                product.get(
                    "product_name",
                    "",
                )
            ),
            product_url=str(
                product.get(
                    "url",
                    "",
                )
            ),
        )

        estimated_weight = get_estimated_weight(
            product_type
        )

        product["product_type"] = product_type

        product["estimated_weight_kg"] = round(
            estimated_weight,
            3,
        )

        product["size_status_note"] = make_size_note(
            requested_size=requested_size,
            size_status=size_status,
            available_sizes=available_sizes,
        )

        print(
            f"\n{country} yoxlanılır..."
        )

        print(
            f"   Seçilmiş ölçü: "
            f"{requested_size or '-'}"
        )

        print(
            f"   Ölçü statusu: "
            f"{size_status}"
        )

        if not product_available:
            print(
                "   Məhsul bu ölkədə tapılmadı."
            )

            results.append(
                product
            )

            continue

        if price_azn is None:
            print(
                "   Məhsulun AZN qiyməti tapılmadı."
            )

            results.append(
                product
            )

            continue

        if size_status == "No":
            print(
                f"   {requested_size} ölçüsü "
                "stokda deyil."
            )

            print(
                "   Bu ölkə ən münasib seçim "
                "hesablamasına daxil edilməyəcək."
            )

            results.append(
                product
            )

            continue

        if size_status == "Unknown":
            print(
                f"   {requested_size} ölçüsünün "
                "stok vəziyyəti müəyyən edilmədi."
            )

            print(
                "   Etibarlı nəticə olmadığı üçün "
                "bu ölkə müqayisəyə daxil edilməyəcək."
            )

            results.append(
                product
            )

            continue

        print(
            f"   Məhsul növü: "
            f"{product_type}"
        )

        print(
            f"   Təxmini bağlama çəkisi: "
            f"{estimated_weight:.2f} kq"
        )

        try:
            (
                estimated_shipping,
                source_count,
            ) = calculate_estimated_shipping(
                browser=browser,
                country_code=country_code,
                weight_kg=estimated_weight,
                exchange_rates=exchange_rates,
            )

        except RuntimeError:
            product["shipping_estimate_note"] = (
                "Canlı kargo tarifi alınmadığı üçün "
                "təxmini yekun qiymət hesablanmadı."
            )

            print(
                "   Təxmini kargo hesablanmadı."
            )

            results.append(
                product
            )

            continue

        final_cost = (
            price_azn
            + estimated_shipping
        )

        product["estimated_shipping_azn"] = round(
            estimated_shipping,
            2,
        )

        product["shipping_tariff_count"] = (
            source_count
        )

        product["shipping_estimate_note"] = (
            make_shipping_note(
                product_type=product_type,
                weight_kg=estimated_weight,
                source_count=source_count,
            )
        )

        product["eligible_for_comparison"] = "Yes"

        product["final_cost_azn"] = round(
            final_cost,
            2,
        )

        print(
            f"   Təxmini kargo: "
            f"{estimated_shipping:.2f} AZN"
        )

        print(
            f"   Təxmini yekun qiymət: "
            f"{final_cost:.2f} AZN"
        )

        results.append(
            product
        )

    return results


# ============================================================
# SIRALAMA VƏ AZƏRBAYCANLA FƏRQ
# ============================================================

def add_rank_and_difference(
    products: list[dict],
) -> list[dict]:
    """
    Yalnız seçilmiş ölçüsü stokda olan və
    yekun qiyməti hesablanmış ölkələri sıralayır.
    """

    valid_products = [
        product
        for product in products
        if (
            product.get(
                "eligible_for_comparison"
            )
            == "Yes"
            and to_float(
                product.get(
                    "final_cost_azn"
                )
            )
            is not None
        )
    ]

    invalid_products = [
        product
        for product in products
        if product not in valid_products
    ]

    sorted_products = sorted(
        valid_products,
        key=lambda item: (
            to_float(
                item.get(
                    "final_cost_azn"
                )
            )
            or float("inf")
        ),
    )

    azerbaijan_product = next(
        (
            product
            for product in sorted_products
            if product.get(
                "country_code"
            ) == "AZ"
        ),
        None,
    )

    azerbaijan_price = None

    if azerbaijan_product:
        azerbaijan_price = to_float(
            azerbaijan_product.get(
                "final_cost_azn"
            )
        )

    for rank, product in enumerate(
        sorted_products,
        start=1,
    ):
        product["rank"] = rank

        if azerbaijan_price is not None:
            final_cost = to_float(
                product.get(
                    "final_cost_azn"
                )
            )

            if final_cost is not None:
                product[
                    "difference_vs_azerbaijan"
                ] = round(
                    azerbaijan_price
                    - final_cost,
                    2,
                )

    return (
        sorted_products
        + invalid_products
    )


# ============================================================
# CSV-NİN SAXLANMASI
# ============================================================

def save_results(
    products: list[dict],
    original_fieldnames: list[str],
) -> None:
    """
    Nəticələri CSV faylına yazır.
    """

    new_columns = [
        "product_type",
        "estimated_weight_kg",
        "estimated_shipping_azn",
        "shipping_tariff_count",
        "shipping_estimate_note",
        "size_status_note",
        "eligible_for_comparison",
        "final_cost_azn",
        "difference_vs_azerbaijan",
        "rank",
    ]

    fieldnames = (
        original_fieldnames.copy()
    )

    for column in new_columns:
        if column not in fieldnames:
            fieldnames.append(
                column
            )

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open(
        mode="w",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )

        writer.writeheader()

        writer.writerows(
            products
        )


# ============================================================
# TERMİNAL NƏTİCƏSİ
# ============================================================

def show_results(
    products: list[dict],
) -> None:
    """
    Nəticələri terminalda göstərir.
    """

    requested_size = next(
        (
            str(
                product.get(
                    "requested_size",
                    "",
                )
            ).strip()
            for product in products
            if str(
                product.get(
                    "requested_size",
                    "",
                )
            ).strip()
        ),
        "-",
    )

    valid_products = [
        product
        for product in products
        if (
            product.get(
                "eligible_for_comparison"
            )
            == "Yes"
            and to_float(
                product.get(
                    "final_cost_azn"
                )
            )
            is not None
        )
    ]

    print(
        "\n"
        + "=" * 105
    )

    print(
        f"MƏHSUL + KARGO MÜQAYİSƏSİ — "
        f"SEÇİLMİŞ ÖLÇÜ: {requested_size}"
    )

    print(
        "=" * 105
    )

    for product in products:
        country = str(
            product.get(
                "country",
                "",
            )
        )

        size_status = normalize_size_status(
            product.get(
                "size_available"
            )
        )

        if size_status == "Yes":
            size_symbol = "✅"

        elif size_status == "No":
            size_symbol = "❌"

        else:
            size_symbol = "⚠️"

        print(
            f"\n{country}"
        )

        print(
            f"   Ölçü {requested_size}: "
            f"{size_symbol} {size_status}"
        )

        available_sizes = str(
            product.get(
                "available_sizes",
                "",
            )
        ).strip()

        if available_sizes:
            print(
                f"   Stokdakı ölçülər: "
                f"{available_sizes}"
            )

        final_cost = to_float(
            product.get(
                "final_cost_azn"
            )
        )

        if final_cost is None:
            print(
                f'   Qeyd: '
                f'{product.get("size_status_note") or "-"}'
            )

            continue

        product_price = to_float(
            product.get(
                "price_azn"
            )
        )

        shipping = to_float(
            product.get(
                "estimated_shipping_azn"
            )
        )

        rank = product.get(
            "rank"
        )

        print(
            f"   Sıra: {rank}"
        )

        if product_price is not None:
            print(
                f"   Məhsul: "
                f"{product_price:.2f} AZN"
            )

        if shipping is not None:
            print(
                f"   Təxmini kargo: "
                f"{shipping:.2f} AZN"
            )

        print(
            f"   Təxmini yekun: "
            f"{final_cost:.2f} AZN"
        )

    if not valid_products:
        print(
            "\nSeçilmiş ölçü üzrə müqayisə üçün "
            "uyğun ölkə tapılmadı."
        )

        return

    cheapest = valid_products[0]

    cheapest_cost = to_float(
        cheapest.get(
            "final_cost_azn"
        )
    )

    print(
        "\n"
        + "-" * 105
    )

    print(
        f"{requested_size} ÖLÇÜSÜ ÜÇÜN "
        "ƏN MÜNASİB SEÇİM"
    )

    print(
        "-" * 105
    )

    print(
        "Ən münasib ölkə:",
        cheapest.get(
            "country"
        ),
    )

    if cheapest_cost is not None:
        print(
            "Təxmini yekun xərc:",
            f"{cheapest_cost:.2f} AZN",
        )

    difference = to_float(
        cheapest.get(
            "difference_vs_azerbaijan"
        )
    )

    if difference is not None:
        if difference > 0:
            print(
                "Azərbaycanla müqayisədə "
                "təxmini qənaət:",
                f"{difference:.2f} AZN",
            )

        elif difference < 0:
            print(
                "Azərbaycan qiymətindən "
                "təxminən daha bahadır:",
                f"{abs(difference):.2f} AZN",
            )

        else:
            print(
                "Azərbaycan qiyməti ilə eynidir."
            )

    else:
        print(
            "Azərbaycan üzrə seçilmiş ölçü "
            "stokda olmadığı üçün Azərbaycanla "
            "qiymət fərqi hesablanmadı."
        )


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    step_started = time.perf_counter()

    print(
        f"Step06 versiyası: {SCRIPT_VERSION}"
    )

    print(
        "Seçilmiş ölçünün mövcudluğuna əsasən "
        "kargo və yekun qiymət hesablanır..."
    )

    products, fieldnames = read_products()

    exchange_rates = build_exchange_rates(
        products
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
        )

        products = calculate_final_prices(
            browser=browser,
            products=products,
            exchange_rates=exchange_rates,
        )

        browser.close()

    products = add_rank_and_difference(
        products
    )

    save_results(
        products=products,
        original_fieldnames=fieldnames,
    )

    show_results(
        products
    )

    print(
        "\nNəticə faylı:"
    )

    print(
        OUTPUT_FILE
    )

    print(
        f"Step06 CARGO V3 ümumi vaxt: "
        f"{time.perf_counter() - step_started:.2f} saniyə"
    )


if __name__ == "__main__":
    main()