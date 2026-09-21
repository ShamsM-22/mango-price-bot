import csv
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from datetime import date, timedelta
from pathlib import Path


# ============================================================
# FAYLLAR
# ============================================================

INPUT_FILE = Path(
    "data/country_price_comparison.csv"
)

OUTPUT_FILE = Path(
    "data/country_price_comparison_azn.csv"
)


# ============================================================
# MƏRKƏZİ BANK PARAMETRLƏRİ
# ============================================================

CBAR_XML_URL = (
    "https://www.cbar.az/currencies/"
    "{rate_date}.xml"
)

# Bu gün məzənnə tapılmasa əvvəlki günlər yoxlanacaq.
MAX_PREVIOUS_DAYS = 10

REQUIRED_CURRENCIES = {
    "USD",
    "EUR",
    "TRY",
}


# ============================================================
# RƏQƏM FUNKSİYALARI
# ============================================================

def parse_number(
    value,
) -> float | None:
    """
    Müxtəlif formatdakı rəqəmləri float-a çevirir.

    Nümunə:
    69.99
    69,99
    4.499,99
    4,499.99
    """

    if value is None:
        return None

    clean_value = str(value).strip()

    if clean_value == "":
        return None

    # Pul işarələri və hərfləri çıxarılır.
    clean_value = re.sub(
        r"[^\d,.\-]",
        "",
        clean_value,
    )

    if clean_value in {
        "",
        "-",
        ".",
        ",",
    }:
        return None

    if "," in clean_value and "." in clean_value:
        # 4.499,99 formatı
        if clean_value.rfind(",") > clean_value.rfind("."):
            clean_value = (
                clean_value
                .replace(".", "")
                .replace(",", ".")
            )

        # 4,499.99 formatı
        else:
            clean_value = clean_value.replace(
                ",",
                "",
            )

    elif "," in clean_value:
        parts = clean_value.split(",")

        # 69,99 formatı
        if len(parts[-1]) in {
            1,
            2,
        }:
            clean_value = clean_value.replace(
                ",",
                ".",
            )

        # 4,499 formatı
        else:
            clean_value = clean_value.replace(
                ",",
                "",
            )

    elif "." in clean_value:
        parts = clean_value.split(".")

        # Birdən çox nöqtə varsa:
        # 4.499.99 və ya 4.499.999
        if clean_value.count(".") > 1:
            last_part = parts[-1]

            if len(last_part) in {
                1,
                2,
            }:
                clean_value = (
                    "".join(parts[:-1])
                    + "."
                    + last_part
                )

            else:
                clean_value = "".join(
                    parts
                )

        # 4.499 formatı minlik ayırıcısı ola bilər.
        elif len(parts[-1]) == 3:
            clean_value = clean_value.replace(
                ".",
                "",
            )

    try:
        return float(
            clean_value
        )

    except ValueError:
        return None


def round_rate(
    rate: float,
) -> float:
    """
    Məzənnəni kifayət qədər dəqiq saxlayır.
    """

    return round(
        rate,
        8,
    )


# ============================================================
# VALYUTA KODU
# ============================================================

def normalize_currency(
    currency,
) -> str:
    """
    Valyuta kodunu standartlaşdırır.
    """

    clean_currency = str(
        currency or ""
    ).strip().upper()

    aliases = {
        "TL": "TRY",
        "₺": "TRY",
        "TURKISH LIRA": "TRY",

        "€": "EUR",
        "EURO": "EUR",

        "$": "USD",
        "US$": "USD",
        "DOLLAR": "USD",

        "₼": "AZN",
        "MANAT": "AZN",
    }

    return aliases.get(
        clean_currency,
        clean_currency,
    )


# ============================================================
# MƏRKƏZİ BANK XML MƏZƏNNƏLƏRİ
# ============================================================

def download_xml(
    xml_url: str,
) -> bytes:
    """
    Mərkəzi Bankın XML faylını yükləyir.
    """

    request = urllib.request.Request(
        xml_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "MangoPriceBot/1.0"
            ),
            "Accept": (
                "application/xml,"
                "text/xml,"
                "*/*"
            ),
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        return response.read()


def parse_cbar_xml(
    xml_content: bytes,
) -> tuple[dict[str, float], str]:
    """
    XML-dən valyuta məzənnələrini oxuyur.

    Mərkəzi Bank bəzi valyutaları 1 deyil,
    10, 100 və ya 1000 nominal üzrə göstərə bilər.

    Buna görə:
    vahid məzənnə = Value / Nominal
    """

    root = ET.fromstring(
        xml_content
    )

    published_date = str(
        root.attrib.get(
            "Date",
            "",
        )
    ).strip()

    rates = {
        "AZN": 1.0,
    }

    for valute in root.findall(
        ".//Valute"
    ):
        currency_code = str(
            valute.attrib.get(
                "Code",
                "",
            )
        ).strip().upper()

        nominal_text = valute.findtext(
            "Nominal"
        )

        value_text = valute.findtext(
            "Value"
        )

        nominal = parse_number(
            nominal_text
        )

        value = parse_number(
            value_text
        )

        if (
            not currency_code
            or nominal is None
            or value is None
            or nominal == 0
        ):
            continue

        rate_for_one_unit = (
            value / nominal
        )

        rates[
            currency_code
        ] = round_rate(
            rate_for_one_unit
        )

    return rates, published_date


def get_cbar_rates() -> tuple[
    dict[str, float],
    str,
    str,
]:
    """
    Bugünkü rəsmi məzənnəni götürür.

    Bugünkü XML tapılmasa, əvvəlki günlərə keçir.
    Bu, həftəsonu və qeyri-iş günləri üçün lazımdır.

    Qaytarır:
    rates
    published_date
    source_url
    """

    errors = []

    today = date.today()

    for previous_day in range(
        MAX_PREVIOUS_DAYS + 1
    ):
        requested_date = (
            today
            - timedelta(
                days=previous_day
            )
        )

        formatted_date = (
            requested_date.strftime(
                "%d.%m.%Y"
            )
        )

        xml_url = CBAR_XML_URL.format(
            rate_date=formatted_date
        )

        print(
            "Məzənnə yoxlanılır:",
            formatted_date,
        )

        try:
            xml_content = download_xml(
                xml_url
            )

            rates, published_date = (
                parse_cbar_xml(
                    xml_content
                )
            )

            missing_currencies = (
                REQUIRED_CURRENCIES
                - set(rates)
            )

            if missing_currencies:
                missing_text = ", ".join(
                    sorted(
                        missing_currencies
                    )
                )

                errors.append(
                    f"{formatted_date}: "
                    f"valyutalar yoxdur — "
                    f"{missing_text}"
                )

                continue

            if not published_date:
                published_date = (
                    formatted_date
                )

            return (
                rates,
                published_date,
                xml_url,
            )

        except urllib.error.HTTPError as error:
            errors.append(
                f"{formatted_date}: "
                f"HTTP {error.code}"
            )

        except urllib.error.URLError as error:
            errors.append(
                f"{formatted_date}: "
                f"şəbəkə xətası — "
                f"{error.reason}"
            )

        except ET.ParseError as error:
            errors.append(
                f"{formatted_date}: "
                f"XML xətası — {error}"
            )

        except Exception as error:
            errors.append(
                f"{formatted_date}: {error}"
            )

    error_details = "\n".join(
        errors[-5:]
    )

    raise RuntimeError(
        "Mərkəzi Bankdan rəsmi məzənnə "
        "alına bilmədi.\n\n"
        f"Son yoxlamalar:\n{error_details}"
    )


# ============================================================
# CSV OXUNMASI
# ============================================================

def read_input_file() -> tuple[
    list[dict],
    list[str],
]:
    """
    Step 04 nəticəsini oxuyur.
    """

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Fayl tapılmadı:\n"
            f"{INPUT_FILE}\n\n"
            "Əvvəl bunu işə sal:\n"
            "python step04_compare_countries.py"
        )

    with INPUT_FILE.open(
        mode="r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        reader = csv.DictReader(
            csv_file
        )

        rows = list(
            reader
        )

        fieldnames = (
            reader.fieldnames
            or []
        )

    if not rows:
        raise RuntimeError(
            "Step 04 nəticə faylı boşdur."
        )

    return rows, fieldnames


# ============================================================
# AZN ÇEVRİLMƏSİ
# ============================================================

def convert_products_to_azn(
    products: list[dict],
    rates: dict[str, float],
    rate_date: str,
) -> list[dict]:
    """
    Bütün məhsul qiymətlərini AZN-ə çevirir.

    Step 04-dən gələn ölçü sütunları dəyişdirilmir.
    """

    converted_products = []

    for product in products:
        currency = normalize_currency(
            product.get(
                "currency"
            )
        )

        original_price = parse_number(
            product.get(
                "price"
            )
        )

        product_available = str(
            product.get(
                "available",
                "",
            )
        ).strip()

        country = str(
            product.get(
                "country",
                "",
            )
        ).strip()

        requested_size = str(
            product.get(
                "requested_size",
                "",
            )
        ).strip()

        size_available = str(
            product.get(
                "size_available",
                "",
            )
        ).strip()

        product[
            "currency"
        ] = currency

        product[
            "exchange_rate"
        ] = ""

        product[
            "rate_date"
        ] = rate_date

        product[
            "price_azn"
        ] = ""

        product[
            "conversion_status"
        ] = ""

        print(
            "\n"
            + "-" * 70
        )

        print(
            "Ölkə:",
            country or "-",
        )

        print(
            "Seçilmiş ölçü:",
            requested_size or "-",
        )

        print(
            "Ölçü statusu:",
            size_available or "Unknown",
        )

        if product_available != "Yes":
            product[
                "conversion_status"
            ] = (
                "Product not available"
            )

            print(
                "Məhsul ölkədə tapılmadığı üçün "
                "AZN hesablanmadı."
            )

            converted_products.append(
                product
            )

            continue

        if original_price is None:
            product[
                "conversion_status"
            ] = (
                "Price not found"
            )

            print(
                "Qiymət oxunmadığı üçün "
                "AZN hesablanmadı."
            )

            converted_products.append(
                product
            )

            continue

        exchange_rate = rates.get(
            currency
        )

        if exchange_rate is None:
            product[
                "conversion_status"
            ] = (
                f"Exchange rate not found: "
                f"{currency}"
            )

            print(
                f"{currency} üçün məzənnə "
                "tapılmadı."
            )

            converted_products.append(
                product
            )

            continue

        price_azn = round(
            original_price
            * exchange_rate,
            2,
        )

        product[
            "exchange_rate"
        ] = round_rate(
            exchange_rate
        )

        product[
            "price_azn"
        ] = price_azn

        product[
            "conversion_status"
        ] = "Converted"

        print(
            "Yerli qiymət:",
            f"{original_price:.2f}",
            currency,
        )

        print(
            f"1 {currency} =",
            f"{exchange_rate:.8f} AZN",
        )

        print(
            "AZN qiyməti:",
            f"{price_azn:.2f} AZN",
        )

        converted_products.append(
            product
        )

    return converted_products


# ============================================================
# CSV SAXLANMASI
# ============================================================

def save_output_file(
    products: list[dict],
    original_fieldnames: list[str],
) -> None:
    """
    Nəticələri CSV-yə yazır.

    Step 04-dəki bütün sütunlar, o cümlədən
    ölçü məlumatları qorunur.
    """

    new_columns = [
        "exchange_rate",
        "rate_date",
        "price_azn",
        "conversion_status",
    ]

    fieldnames = list(
        original_fieldnames
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
# YEKUN NƏTİCƏ
# ============================================================

def show_summary(
    products: list[dict],
    rate_date: str,
) -> None:
    """
    AZN nəticələrini terminalda göstərir.
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

    print(
        "\n"
        + "=" * 90
    )

    print(
        "QİYMƏTLƏR AZN-Ə ÇEVRİLDİ"
    )

    print(
        "=" * 90
    )

    print(
        "Məzənnə tarixi:",
        rate_date,
    )

    print(
        "Seçilmiş ölçü:",
        requested_size,
    )

    for product in products:
        country = str(
            product.get(
                "country",
                "",
            )
        )

        local_price = parse_number(
            product.get(
                "price"
            )
        )

        currency = str(
            product.get(
                "currency",
                "",
            )
        )

        price_azn = parse_number(
            product.get(
                "price_azn"
            )
        )

        size_status = str(
            product.get(
                "size_available",
                "Unknown",
            )
        )

        size_symbol = {
            "Yes": "✅",
            "No": "❌",
            "Unknown": "⚠️",
        }.get(
            size_status,
            "⚠️",
        )

        print(
            "\n"
            f"{country}"
        )

        print(
            f"   Ölçü {requested_size}: "
            f"{size_symbol} {size_status}"
        )

        if (
            local_price is not None
            and price_azn is not None
        ):
            print(
                f"   Yerli qiymət: "
                f"{local_price:.2f} "
                f"{currency}"
            )

            print(
                f"   AZN qiyməti: "
                f"{price_azn:.2f} AZN"
            )

        else:
            print(
                "   AZN qiyməti hesablanmadı."
            )

    print(
        "\nNəticə faylı:"
    )

    print(
        OUTPUT_FILE
    )


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    print(
        "=" * 80
    )

    print(
        "MANGO QİYMƏTLƏRİNİN AZN-Ə ÇEVRİLMƏSİ"
    )

    print(
        "=" * 80
    )

    products, original_fieldnames = (
        read_input_file()
    )

    (
        exchange_rates,
        published_date,
        source_url,
    ) = get_cbar_rates()

    print(
        "\nRəsmi məzənnə alındı."
    )

    print(
        "Məzənnə tarixi:",
        published_date,
    )

    print(
        "USD:",
        exchange_rates.get(
            "USD"
        ),
    )

    print(
        "EUR:",
        exchange_rates.get(
            "EUR"
        ),
    )

    print(
        "TRY:",
        exchange_rates.get(
            "TRY"
        ),
    )

    converted_products = (
        convert_products_to_azn(
            products=products,
            rates=exchange_rates,
            rate_date=published_date,
        )
    )

    save_output_file(
        products=converted_products,
        original_fieldnames=original_fieldnames,
    )

    show_summary(
        products=converted_products,
        rate_date=published_date,
    )


if __name__ == "__main__":
    main()