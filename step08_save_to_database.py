import csv
import re
import sqlite3

from datetime import datetime
from pathlib import Path


# ============================================================
# FAYL YOLLARI
# ============================================================

INPUT_FILE = Path(
    "data/final_price_comparison.csv"
)

LAST_SEARCH_FILE = Path(
    "data/last_search.txt"
)

LAST_SIZE_FILE = Path(
    "data/last_requested_size.txt"
)

DATABASE_FILE = Path(
    "database/mango_price_bot.db"
)


# ============================================================
# DATABASE ÜÇÜN ƏSAS SÜTUNLAR
# ============================================================

# Tarix sütunları bu siyahıya daxil edilmir.
# Çünki köhnə database-də searched_at,
# yeni database-də isə created_at ola bilər.
REQUIRED_SEARCH_COLUMNS = {
    "search_id",
    "user_id",
    "product_url",
    "product_code",
    "product_name",
    "requested_size",
}


REQUIRED_PRICE_RESULT_COLUMNS = {
    "result_id",
    "search_id",
    "country_code",
    "country",
    "available",
    "product_name",
    "price",
    "currency",
    "exchange_rate",
    "rate_date",
    "price_azn",
    "requested_size",
    "all_sizes",
    "available_sizes",
    "size_available",
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
    "conversion_status",
    "product_url",
}


KNOWN_TIMESTAMP_COLUMNS = {
    "searched_at",
    "created_at",
    "checked_at",
    "updated_at",
}


# ============================================================
# KÖHNƏ DATABASE SÜTUN ADLARI ÜÇÜN UYĞUNLUQ
# ============================================================

LEGACY_COLUMN_ALIASES = {
    "searches": {
        # Köhnə database-də məhsul linki input_url adlanırdı.
        "input_url": "product_url",
        "url": "product_url",

        # Köhnə ölçü sütun adları.
        "size": "requested_size",
        "selected_size": "requested_size",
        "search_size": "requested_size",

        # Köhnə məhsul məlumatı sütun adları.
        "code": "product_code",
        "name": "product_name",
        "telegram_user_id": "user_id",
    },

    "price_results": {
        # Link sütunları.
        "input_url": "product_url",
        "url": "product_url",
        "result_url": "product_url",

        # Ölçü sütunları.
        "size": "requested_size",
        "selected_size": "requested_size",
        "local_size": "matched_size",
        "country_size": "matched_size",

        # Mövcudluq sütunları.
        "is_available": "available",
        "in_stock": "size_available",

        # Qiymət və kargo sütunları.
        "shipping_cost_azn": "estimated_shipping_azn",
        "final_price_azn": "final_cost_azn",
        "total_cost_azn": "final_cost_azn",
        "price_difference_azn": "difference_vs_azerbaijan",

        # Digər mümkün köhnə adlar.
        "code": "product_code",
        "name": "product_name",
    },
}


# ============================================================
# RƏQƏM FUNKSİYALARI
# ============================================================

def to_float(value) -> float | None:
    """
    CSV dəyərini float-a çevirir.
    """

    if value is None:
        return None

    clean_value = str(value).strip()

    if clean_value == "":
        return None

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

    if (
        "," in clean_value
        and "." in clean_value
    ):
        if (
            clean_value.rfind(",")
            > clean_value.rfind(".")
        ):
            clean_value = (
                clean_value
                .replace(".", "")
                .replace(",", ".")
            )
        else:
            clean_value = clean_value.replace(
                ",",
                "",
            )

    elif "," in clean_value:
        clean_value = clean_value.replace(
            ",",
            ".",
        )

    try:
        return float(clean_value)

    except ValueError:
        return None


def to_int(value) -> int | None:
    """
    CSV dəyərini integer-ə çevirir.
    """

    float_value = to_float(value)

    if float_value is None:
        return None

    return int(float_value)


# ============================================================
# MƏTN FUNKSİYALARI
# ============================================================

def clean_text(value) -> str:
    """
    None və boş dəyərləri təmizləyir.
    """

    if value is None:
        return ""

    return str(value).strip()


def get_first_non_empty(
    products: list[dict],
    column_name: str,
) -> str:
    """
    Verilən sütunda ilk boş olmayan dəyəri tapır.
    """

    for product in products:
        value = clean_text(
            product.get(column_name)
        )

        if value:
            return value

    return ""


def current_timestamp_text() -> str:
    """
    SQLite üçün cari tarix və saatı qaytarır.
    """

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ============================================================
# CSV OXUNMASI
# ============================================================

def read_final_results() -> list[dict]:
    """
    Step 06 nəticə faylını oxuyur.
    """

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Fayl tapılmadı:\n"
            f"{INPUT_FILE}\n\n"
            "Əvvəl bunları işə sal:\n"
            "python step04_compare_countries.py\n"
            "python step05_convert_to_azn.py\n"
            "python step06_add_shipping_cost.py"
        )

    with INPUT_FILE.open(
        mode="r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        reader = csv.DictReader(
            csv_file
        )

        products = list(reader)

    if not products:
        raise RuntimeError(
            "final_price_comparison.csv faylı boşdur."
        )

    return products


# ============================================================
# ORİJİNAL SORĞU MƏLUMATLARI
# ============================================================

def read_text_file(
    file_path: Path,
) -> str:
    """
    Kiçik mətn faylını oxuyur.
    """

    if not file_path.exists():
        return ""

    try:
        return file_path.read_text(
            encoding="utf-8",
        ).strip()

    except Exception:
        return ""


def get_original_product_url(
    products: list[dict],
) -> str:
    """
    İstifadəçinin göndərdiyi orijinal Mango linkini tapır.
    """

    original_url = read_text_file(
        LAST_SEARCH_FILE
    )

    if original_url:
        return original_url

    azerbaijan_result = next(
        (
            product
            for product in products
            if clean_text(
                product.get("country_code")
            ).upper()
            == "AZ"
        ),
        None,
    )

    if azerbaijan_result:
        url = clean_text(
            azerbaijan_result.get("url")
        )

        if url:
            return url

    return get_first_non_empty(
        products,
        "url",
    )


def get_requested_size(
    products: list[dict],
) -> str:
    """
    İstifadəçinin seçdiyi ölçünü tapır.
    """

    requested_size = get_first_non_empty(
        products,
        "requested_size",
    )

    if requested_size:
        return requested_size

    return read_text_file(
        LAST_SIZE_FILE
    )


def get_product_code(
    products: list[dict],
) -> str:
    """
    Məhsul kodunu tapır.
    """

    return get_first_non_empty(
        products,
        "product_code",
    )


def get_product_name(
    products: list[dict],
) -> str:
    """
    Məhsul adını əvvəlcə Azərbaycan nəticəsindən götürür.
    """

    invalid_names = {
        "",
        "Not found",
        "Error",
        "Timeout",
        "None",
    }

    azerbaijan_result = next(
        (
            product
            for product in products
            if clean_text(
                product.get("country_code")
            ).upper()
            == "AZ"
        ),
        None,
    )

    if azerbaijan_result:
        product_name = clean_text(
            azerbaijan_result.get(
                "product_name"
            )
        )

        if product_name not in invalid_names:
            return product_name

    for product in products:
        product_name = clean_text(
            product.get("product_name")
        )

        if product_name not in invalid_names:
            return product_name

    return "Mango məhsulu"


# ============================================================
# USER ID
# ============================================================

def get_user_id() -> str:
    """
    İstifadəçi ID-sini terminaldan qəbul edir.

    Telegram bot avtomatik belə göndərir:
    telegram_1068549591
    """

    user_id = input(
        "İstifadəçi ID-sini daxil et "
        "(boş buraxsan local_user olacaq): "
    ).strip()

    if not user_id:
        return "local_user"

    return user_id


# ============================================================
# DATABASE BAĞLANTISI
# ============================================================

def connect_database() -> sqlite3.Connection:
    """
    SQLite database bağlantısı yaradır.
    """

    if not DATABASE_FILE.exists():
        raise FileNotFoundError(
            f"Database tapılmadı:\n"
            f"{DATABASE_FILE}\n\n"
            "Əvvəl bunu işə sal:\n"
            "python step07_database.py"
        )

    connection = sqlite3.connect(
        DATABASE_FILE,
        timeout=30,
    )

    connection.row_factory = sqlite3.Row

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    return connection


# ============================================================
# DATABASE STRUKTURUNUN OXUNMASI
# ============================================================

def table_exists(
    connection: sqlite3.Connection,
    table_name: str,
) -> bool:
    """
    Cədvəlin database-də olub-olmadığını yoxlayır.
    """

    cursor = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (
            table_name,
        ),
    )

    return cursor.fetchone() is not None


def get_table_info(
    connection: sqlite3.Connection,
    table_name: str,
) -> list[sqlite3.Row]:
    """
    PRAGMA table_info nəticəsini qaytarır.
    """

    cursor = connection.execute(
        f"PRAGMA table_info({table_name})"
    )

    return cursor.fetchall()


def get_table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    """
    Cədvəlin sütun adlarını qaytarır.
    """

    return {
        str(row["name"])
        for row in get_table_info(
            connection,
            table_name,
        )
    }


def validate_database_structure(
    connection: sqlite3.Connection,
) -> None:
    """
    Database strukturunun əsas sütunlarını yoxlayır.

    searched_at və created_at fərqi xəta sayılmır.
    """

    for table_name in [
        "searches",
        "price_results",
    ]:
        if not table_exists(
            connection,
            table_name,
        ):
            raise RuntimeError(
                f"{table_name} cədvəli tapılmadı.\n\n"
                "Əvvəl bunu işə sal:\n"
                "python step07_database.py"
            )

    search_columns = get_table_columns(
        connection,
        "searches",
    )

    price_columns = get_table_columns(
        connection,
        "price_results",
    )

    missing_search_columns = (
        REQUIRED_SEARCH_COLUMNS
        - search_columns
    )

    missing_price_columns = (
        REQUIRED_PRICE_RESULT_COLUMNS
        - price_columns
    )

    if (
        missing_search_columns
        or missing_price_columns
    ):
        error_lines = [
            "Database strukturu köhnədir.",
            "",
        ]

        if missing_search_columns:
            error_lines.append(
                "searches cədvəlində çatışmayan sütunlar:"
            )

            error_lines.append(
                ", ".join(
                    sorted(
                        missing_search_columns
                    )
                )
            )

            error_lines.append("")

        if missing_price_columns:
            error_lines.append(
                "price_results cədvəlində "
                "çatışmayan sütunlar:"
            )

            error_lines.append(
                ", ".join(
                    sorted(
                        missing_price_columns
                    )
                )
            )

            error_lines.append("")

        error_lines.extend(
            [
                "Bunu yenidən işə sal:",
                "python step07_database.py",
            ]
        )

        raise RuntimeError(
            "\n".join(error_lines)
        )


# ============================================================
# DİNAMİK INSERT KÖMƏKÇİLƏRİ
# ============================================================

def add_legacy_alias_values(
    table_name: str,
    table_columns: set[str],
    payload: dict,
) -> None:
    """
    Köhnə database sütun adlarını yeni sütunlardan doldurur.

    Məsələn searches cədvəlində:
    input_url <- product_url

    Beləliklə əvvəlki SQL məlumatları silinmədən
    yeni Step 08 köhnə database strukturu ilə də işləyir.
    """

    aliases = LEGACY_COLUMN_ALIASES.get(
        table_name,
        {},
    )

    for (
        legacy_column,
        current_column,
    ) in aliases.items():

        if legacy_column not in table_columns:
            continue

        if legacy_column in payload:
            continue

        if current_column not in payload:
            continue

        payload[legacy_column] = payload[
            current_column
        ]


def add_timestamp_values(
    connection: sqlite3.Connection,
    table_name: str,
    payload: dict,
) -> None:
    """
    Köhnə və yeni database tarix sütunlarını doldurur.

    Məsələn:
    searched_at
    created_at
    checked_at
    updated_at

    Beləliklə searched_at NOT NULL xətası yaranmır.
    """

    timestamp_value = current_timestamp_text()

    for column_info in get_table_info(
        connection,
        table_name,
    ):
        column_name = str(
            column_info["name"]
        )

        not_null = int(
            column_info["notnull"]
        )

        default_value = column_info[
            "dflt_value"
        ]

        if column_name in payload:
            continue

        is_known_timestamp = (
            column_name
            in KNOWN_TIMESTAMP_COLUMNS
        )

        is_required_at_column = (
            column_name.endswith("_at")
            and not_null == 1
            and default_value is None
        )

        if (
            is_known_timestamp
            or is_required_at_column
        ):
            payload[column_name] = (
                timestamp_value
            )


def validate_not_null_payload(
    connection: sqlite3.Connection,
    table_name: str,
    payload: dict,
) -> None:
    """
    Default dəyəri olmayan məcburi sütunların
    INSERT payload-da olduğunu yoxlayır.
    """

    missing_required_columns = []

    for column_info in get_table_info(
        connection,
        table_name,
    ):
        column_name = str(
            column_info["name"]
        )

        column_type = clean_text(
            column_info["type"]
        ).upper()

        not_null = int(
            column_info["notnull"]
        )

        default_value = column_info[
            "dflt_value"
        ]

        primary_key = int(
            column_info["pk"]
        )

        # INTEGER PRIMARY KEY AUTOINCREMENT
        # SQLite tərəfindən avtomatik yaradılır.
        if primary_key == 1:
            continue

        if (
            not_null == 1
            and default_value is None
            and column_name not in payload
        ):
            missing_required_columns.append(
                f"{column_name} ({column_type})"
            )

    if missing_required_columns:
        raise RuntimeError(
            f"{table_name} cədvəlində doldurulmamış "
            "məcburi sütunlar var:\n"
            + "\n".join(
                missing_required_columns
            )
        )


def execute_dynamic_insert(
    connection: sqlite3.Connection,
    table_name: str,
    payload: dict,
) -> sqlite3.Cursor:
    """
    Mövcud cədvəl sütunlarına uyğun dinamik INSERT edir.
    """

    table_columns = get_table_columns(
        connection,
        table_name,
    )

    # Əvvəl köhnə sütun adlarına uyğun dəyərləri əlavə edir.
    expanded_payload = dict(
        payload
    )

    add_legacy_alias_values(
        table_name=table_name,
        table_columns=table_columns,
        payload=expanded_payload,
    )

    filtered_payload = {
        column_name: value
        for (
            column_name,
            value,
        ) in expanded_payload.items()
        if column_name in table_columns
    }

    add_timestamp_values(
        connection=connection,
        table_name=table_name,
        payload=filtered_payload,
    )

    validate_not_null_payload(
        connection=connection,
        table_name=table_name,
        payload=filtered_payload,
    )

    columns = list(
        filtered_payload.keys()
    )

    values = [
        filtered_payload[column_name]
        for column_name in columns
    ]

    column_sql = ", ".join(
        columns
    )

    placeholder_sql = ", ".join(
        ["?"] * len(columns)
    )

    sql = (
        f"INSERT INTO {table_name} "
        f"({column_sql}) "
        f"VALUES ({placeholder_sql})"
    )

    return connection.execute(
        sql,
        tuple(values),
    )


# ============================================================
# SEARCHES CƏDVƏLİNƏ YAZMA
# ============================================================

def insert_search(
    connection: sqlite3.Connection,
    user_id: str,
    product_url: str,
    product_code: str,
    product_name: str,
    requested_size: str,
) -> int:
    """
    Ümumi Mango sorğusunu searches cədvəlinə yazır.

    searched_at və created_at strukturlarının
    hər ikisi ilə işləyir.
    """

    payload = {
        "user_id": user_id,
        "product_url": product_url,
        "product_code": product_code,
        "product_name": product_name,
        "requested_size": requested_size,
    }

    cursor = execute_dynamic_insert(
        connection=connection,
        table_name="searches",
        payload=payload,
    )

    search_id = cursor.lastrowid

    if search_id is None:
        raise RuntimeError(
            "Yeni search_id yaradıla bilmədi."
        )

    return int(search_id)


# ============================================================
# PRICE_RESULTS CƏDVƏLİNƏ YAZMA
# ============================================================

def insert_price_result(
    connection: sqlite3.Connection,
    search_id: int,
    product: dict,
) -> None:
    """
    Bir ölkənin qiymət, ölçü və kargo
    nəticəsini SQL database-ə yazır.

    matched_size və size_match_method sütunları
    database-də varsa, onlar da avtomatik yazılır.
    """

    payload = {
        "search_id": search_id,

        "country_code": clean_text(
            product.get("country_code")
        ),

        "country": clean_text(
            product.get("country")
        ),

        "available": clean_text(
            product.get("available")
        ),

        "product_name": clean_text(
            product.get("product_name")
        ),

        "price": to_float(
            product.get("price")
        ),

        "currency": clean_text(
            product.get("currency")
        ),

        "exchange_rate": to_float(
            product.get("exchange_rate")
        ),

        "rate_date": clean_text(
            product.get("rate_date")
        ),

        "price_azn": to_float(
            product.get("price_azn")
        ),

        "requested_size": clean_text(
            product.get("requested_size")
        ),

        "all_sizes": clean_text(
            product.get("all_sizes")
        ),

        "available_sizes": clean_text(
            product.get("available_sizes")
        ),

        "size_available": clean_text(
            product.get("size_available")
        ),

        "product_type": clean_text(
            product.get("product_type")
        ),

        "estimated_weight_kg": to_float(
            product.get(
                "estimated_weight_kg"
            )
        ),

        "estimated_shipping_azn": to_float(
            product.get(
                "estimated_shipping_azn"
            )
        ),

        "shipping_tariff_count": to_int(
            product.get(
                "shipping_tariff_count"
            )
        ),

        "shipping_estimate_note": clean_text(
            product.get(
                "shipping_estimate_note"
            )
        ),

        "size_status_note": clean_text(
            product.get(
                "size_status_note"
            )
        ),

        "eligible_for_comparison": clean_text(
            product.get(
                "eligible_for_comparison"
            )
        ),

        "final_cost_azn": to_float(
            product.get(
                "final_cost_azn"
            )
        ),

        "difference_vs_azerbaijan": to_float(
            product.get(
                "difference_vs_azerbaijan"
            )
        ),

        "rank": to_int(
            product.get("rank")
        ),

        "conversion_status": clean_text(
            product.get(
                "conversion_status"
            )
        ),

        "product_url": clean_text(
            product.get("url")
        ),

        # Yeni Step 04-dən gələn əlavə ölçü məlumatları.
        # Database-də bu sütunlar yoxdursa nəzərə alınmır.
        "original_country_code": clean_text(
            product.get(
                "original_country_code"
            )
        ),

        "matched_size": clean_text(
            product.get(
                "matched_size"
            )
        ),

        "size_match_method": clean_text(
            product.get(
                "size_match_method"
            )
        ),
    }

    execute_dynamic_insert(
        connection=connection,
        table_name="price_results",
        payload=payload,
    )


def insert_all_price_results(
    connection: sqlite3.Connection,
    search_id: int,
    products: list[dict],
) -> int:
    """
    Bütün ölkə nəticələrini SQL-ə yazır.
    """

    inserted_count = 0

    for product in products:
        insert_price_result(
            connection=connection,
            search_id=search_id,
            product=product,
        )

        inserted_count += 1

    return inserted_count


# ============================================================
# YAZILMIŞ NƏTİCƏLƏRİN OXUNMASI
# ============================================================

def read_saved_results(
    connection: sqlite3.Connection,
    search_id: int,
) -> list[sqlite3.Row]:
    """
    Yazılmış ölkə nəticələrini yenidən oxuyur.
    """

    cursor = connection.execute(
        """
        SELECT
            country_code,
            country,
            requested_size,
            size_available,
            available_sizes,
            eligible_for_comparison,
            price_azn,
            estimated_shipping_azn,
            final_cost_azn,
            difference_vs_azerbaijan,
            rank
        FROM price_results
        WHERE search_id = ?
        ORDER BY
            CASE
                WHEN rank IS NULL THEN 999
                ELSE rank
            END,
            country
        """,
        (
            search_id,
        ),
    )

    return cursor.fetchall()


# ============================================================
# TERMİNAL NƏTİCƏSİ
# ============================================================

def show_saved_summary(
    connection: sqlite3.Connection,
    search_id: int,
    user_id: str,
    product_name: str,
    product_code: str,
    requested_size: str,
    inserted_count: int,
) -> None:
    """
    SQL-ə yazılmış nəticəni terminalda göstərir.
    """

    saved_results = read_saved_results(
        connection=connection,
        search_id=search_id,
    )

    print(
        "\n"
        + "=" * 90
    )

    print(
        "SORĞU SQL DATABASE-Ə YAZILDI"
    )

    print(
        "=" * 90
    )

    print(
        "Search ID:",
        search_id,
    )

    print(
        "İstifadəçi ID:",
        user_id,
    )

    print(
        "Məhsul:",
        product_name,
    )

    print(
        "Məhsul kodu:",
        product_code,
    )

    print(
        "Seçilmiş ölçü:",
        requested_size,
    )

    print(
        "Yazılmış ölkə nəticələrinin sayı:",
        inserted_count,
    )

    print(
        "\nÖLKƏLƏR ÜZRƏ NƏTİCƏ"
    )

    for result in saved_results:
        country = (
            result["country"]
            or "-"
        )

        size_status = (
            result["size_available"]
            or "Unknown"
        )

        eligible = (
            result[
                "eligible_for_comparison"
            ]
            or "No"
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

        available_sizes = (
            result["available_sizes"]
            or ""
        )

        if available_sizes:
            print(
                "   Stokdakı ölçülər:",
                available_sizes,
            )

        print(
            "   Müqayisəyə daxildir:",
            eligible,
        )

        final_cost = result[
            "final_cost_azn"
        ]

        if final_cost is not None:
            print(
                "   Təxmini yekun:",
                f"{final_cost:.2f} AZN",
            )

            print(
                "   Sıra:",
                result["rank"],
            )

        else:
            print(
                "   Yekun qiymət hesablanmayıb."
            )

    cheapest_result = next(
        (
            result
            for result in saved_results
            if result["rank"] == 1
            and result[
                "eligible_for_comparison"
            ] == "Yes"
        ),
        None,
    )

    print(
        "\n"
        + "-" * 90
    )

    if cheapest_result:
        print(
            f"{requested_size} ÖLÇÜSÜ ÜÇÜN "
            "ƏN MÜNASİB SEÇİM"
        )

        print(
            "-" * 90
        )

        print(
            "Ölkə:",
            cheapest_result["country"],
        )

        print(
            "Təxmini yekun:",
            f'{cheapest_result["final_cost_azn"]:.2f} AZN',
        )

        difference = cheapest_result[
            "difference_vs_azerbaijan"
        ]

        if difference is not None:
            if difference > 0:
                print(
                    "Azərbaycanla müqayisədə qənaət:",
                    f"{difference:.2f} AZN",
                )

            elif difference < 0:
                print(
                    "Azərbaycan qiymətindən bahadır:",
                    f"{abs(difference):.2f} AZN",
                )

            else:
                print(
                    "Azərbaycan qiyməti ilə eynidir."
                )

        else:
            print(
                "Azərbaycan üzrə seçilmiş ölçü "
                "olmadığı üçün fərq hesablanmayıb."
            )

    else:
        print(
            "Seçilmiş ölçü üzrə müqayisəyə uyğun "
            "ölkə tapılmadı."
        )


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """
    Step 06 nəticəsini SQL database-ə yazır.
    """

    print(
        "=" * 80
    )

    print(
        "MANGO PRICE BOT — SQL QEYDİ"
    )

    print(
        "=" * 80
    )

    products = read_final_results()

    user_id = get_user_id()

    product_url = get_original_product_url(
        products
    )

    product_code = get_product_code(
        products
    )

    product_name = get_product_name(
        products
    )

    requested_size = get_requested_size(
        products
    )

    if not requested_size:
        raise RuntimeError(
            "Seçilmiş ölçü tapılmadı.\n\n"
            "Əvvəl yenilənmiş Step 04-ü işə sal."
        )

    print(
        "\nSQL-ə yazılacaq məlumat:"
    )

    print(
        "İstifadəçi:",
        user_id,
    )

    print(
        "Məhsul:",
        product_name,
    )

    print(
        "Məhsul kodu:",
        product_code,
    )

    print(
        "Seçilmiş ölçü:",
        requested_size,
    )

    connection = connect_database()

    try:
        validate_database_structure(
            connection
        )

        search_id = insert_search(
            connection=connection,
            user_id=user_id,
            product_url=product_url,
            product_code=product_code,
            product_name=product_name,
            requested_size=requested_size,
        )

        inserted_count = (
            insert_all_price_results(
                connection=connection,
                search_id=search_id,
                products=products,
            )
        )

        connection.commit()

        show_saved_summary(
            connection=connection,
            search_id=search_id,
            user_id=user_id,
            product_name=product_name,
            product_code=product_code,
            requested_size=requested_size,
            inserted_count=inserted_count,
        )

    except sqlite3.IntegrityError as error:
        connection.rollback()

        raise RuntimeError(
            "SQL database-ə yazılarkən "
            "məcburi sütun xətası yarandı:\n"
            f"{error}\n\n"
            "Bu Step 08 köhnə input_url və yeni "
            "product_url sütunlarının hər ikisini dəstəkləyir."
        ) from error

    except sqlite3.OperationalError as error:
        connection.rollback()

        if "locked" in str(error).lower():
            raise RuntimeError(
                "Database hazırda başqa proqramda açıqdır.\n\n"
                "DB Browser və ya digər database "
                "proqramını bağla, sonra yenidən yoxla."
            ) from error

        raise

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    print(
        "\n✅ Məlumatlar SQL database-ə uğurla yazıldı."
    )

    print(
        "Database:"
    )

    print(
        DATABASE_FILE.resolve()
    )


if __name__ == "__main__":
    main()
