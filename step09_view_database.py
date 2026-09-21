import sqlite3
from pathlib import Path


# ============================================================
# DATABASE YOLU
# ============================================================

DATABASE_FILE = Path(
    "database/mango_price_bot.db"
)


# ============================================================
# ÖLKƏ ADLARI
# ============================================================

COUNTRY_NAMES_AZ = {
    "Azerbaijan": "Azərbaycan",
    "Spain": "İspaniya",
    "Turkey": "Türkiyə",
    "United States": "ABŞ",
}


# ============================================================
# DATABASE BAĞLANTISI
# ============================================================

def connect_database() -> sqlite3.Connection:
    """
    SQLite database ilə bağlantı yaradır.
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
# KÖMƏKÇİ FUNKSİYALAR
# ============================================================

def clean_text(
    value,
) -> str:
    """
    None və boş dəyərləri təmizləyir.
    """

    if value is None:
        return ""

    return str(value).strip()


def country_name_az(
    country: str,
) -> str:
    """
    Ölkə adını Azərbaycan dilində göstərir.
    """

    return COUNTRY_NAMES_AZ.get(
        country,
        country,
    )


def format_money(
    value,
) -> str:
    """
    Məbləği AZN formatında göstərir.
    """

    if value is None:
        return "-"

    try:
        return f"{float(value):.2f} AZN"

    except (TypeError, ValueError):
        return "-"


def get_size_symbol(
    size_status: str,
) -> str:
    """
    Ölçü statusuna uyğun simvol qaytarır.
    """

    symbols = {
        "Yes": "✅",
        "No": "❌",
        "Unknown": "⚠️",
    }

    return symbols.get(
        size_status,
        "⚠️",
    )


def translate_size_status(
    size_status: str,
) -> str:
    """
    Ölçü statusunu Azərbaycan dilində göstərir.
    """

    statuses = {
        "Yes": "Mövcuddur",
        "No": "Mövcud deyil",
        "Unknown": "Dəqiq müəyyən edilmədi",
    }

    return statuses.get(
        size_status,
        "Dəqiq müəyyən edilmədi",
    )


def translate_eligible_status(
    eligible_status: str,
) -> str:
    """
    Müqayisəyə daxil olma statusunu göstərir.
    """

    if eligible_status == "Yes":
        return "Bəli"

    return "Xeyr"


# ============================================================
# DATABASE STRUKTURUNUN YOXLAMASI
# ============================================================

def table_exists(
    connection: sqlite3.Connection,
    table_name: str,
) -> bool:
    """
    Cədvəlin mövcudluğunu yoxlayır.
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


def validate_database(
    connection: sqlite3.Connection,
) -> None:
    """
    Lazım olan cədvəllərin mövcudluğunu yoxlayır.
    """

    required_tables = [
        "searches",
        "price_results",
    ]

    missing_tables = [
        table_name
        for table_name in required_tables
        if not table_exists(
            connection,
            table_name,
        )
    ]

    if missing_tables:
        raise RuntimeError(
            "Database-də bu cədvəllər tapılmadı:\n"
            + "\n".join(missing_tables)
            + "\n\nƏvvəl bunu işə sal:\n"
            + "python step07_database.py"
        )


# ============================================================
# ÜMUMİ SAYLAR
# ============================================================

def get_database_counts(
    connection: sqlite3.Connection,
) -> tuple[int, int]:
    """
    Sorğu və ölkə nəticələrinin sayını qaytarır.
    """

    searches_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM searches
        """
    ).fetchone()[0]

    results_count = connection.execute(
        """
        SELECT COUNT(*)
        FROM price_results
        """
    ).fetchone()[0]

    return (
        int(searches_count),
        int(results_count),
    )


# ============================================================
# ƏN SON SORĞUNUN OXUNMASI
# ============================================================

def get_latest_search(
    connection: sqlite3.Connection,
) -> sqlite3.Row | None:
    """
    Database-dəki ən son Mango sorğusunu qaytarır.
    """

    cursor = connection.execute(
        """
        SELECT
            search_id,
            user_id,
            product_url,
            product_code,
            product_name,
            requested_size,
            created_at
        FROM searches
        ORDER BY search_id DESC
        LIMIT 1
        """
    )

    return cursor.fetchone()


def get_search_results(
    connection: sqlite3.Connection,
    search_id: int,
) -> list[sqlite3.Row]:
    """
    Seçilmiş sorğunun bütün ölkə nəticələrini qaytarır.
    """

    cursor = connection.execute(
        """
        SELECT
            result_id,
            country_code,
            country,
            available,
            product_name,

            price,
            currency,
            exchange_rate,
            rate_date,
            price_azn,

            requested_size,
            all_sizes,
            available_sizes,
            size_available,

            product_type,
            estimated_weight_kg,

            estimated_shipping_azn,
            shipping_tariff_count,
            shipping_estimate_note,

            size_status_note,
            eligible_for_comparison,

            final_cost_azn,
            difference_vs_azerbaijan,
            rank,

            conversion_status,
            product_url,
            created_at

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
# ƏN MÜNASİB NƏTİCƏ
# ============================================================

def get_cheapest_result(
    results: list[sqlite3.Row],
) -> sqlite3.Row | None:
    """
    Müqayisəyə daxil olan və rank = 1 olan nəticəni tapır.
    """

    for result in results:
        if (
            clean_text(
                result["eligible_for_comparison"]
            )
            == "Yes"
            and result["rank"] == 1
            and result["final_cost_azn"] is not None
        ):
            return result

    valid_results = [
        result
        for result in results
        if (
            clean_text(
                result["eligible_for_comparison"]
            )
            == "Yes"
            and result["final_cost_azn"] is not None
        )
    ]

    if not valid_results:
        return None

    return min(
        valid_results,
        key=lambda result: float(
            result["final_cost_azn"]
        ),
    )


# ============================================================
# SORĞU MƏLUMATLARININ GÖSTƏRİLMƏSİ
# ============================================================

def show_search_header(
    search: sqlite3.Row,
) -> None:
    """
    Sorğunun əsas məlumatlarını terminalda göstərir.
    """

    print(
        "\n"
        + "=" * 100
    )

    print(
        "MANGO PRICE BOT — ƏN SON SQL SORĞUSU"
    )

    print(
        "=" * 100
    )

    print(
        "Search ID:",
        search["search_id"],
    )

    print(
        "İstifadəçi ID:",
        clean_text(
            search["user_id"]
        )
        or "-",
    )

    print(
        "Məhsul:",
        clean_text(
            search["product_name"]
        )
        or "Mango məhsulu",
    )

    print(
        "Məhsul kodu:",
        clean_text(
            search["product_code"]
        )
        or "-",
    )

    print(
        "Seçilmiş ölçü:",
        clean_text(
            search["requested_size"]
        )
        or "-",
    )

    print(
        "Tarix:",
        clean_text(
            search["created_at"]
        )
        or "-",
    )

    print(
        "Orijinal link:",
        clean_text(
            search["product_url"]
        )
        or "-",
    )


# ============================================================
# ÖLKƏ NƏTİCƏLƏRİNİN GÖSTƏRİLMƏSİ
# ============================================================

def show_country_result(
    result: sqlite3.Row,
    requested_size: str,
) -> None:
    """
    Bir ölkənin qiymət və ölçü nəticəsini göstərir.
    """

    country = country_name_az(
        clean_text(
            result["country"]
        )
        or "-"
    )

    product_available = clean_text(
        result["available"]
    )

    size_status = clean_text(
        result["size_available"]
    ) or "Unknown"

    size_symbol = get_size_symbol(
        size_status
    )

    size_status_az = translate_size_status(
        size_status
    )

    eligible_status = clean_text(
        result["eligible_for_comparison"]
    ) or "No"

    print(
        "\n"
        + "-" * 100
    )

    print(
        country.upper()
    )

    print(
        "-" * 100
    )

    if product_available != "Yes":
        print(
            "Məhsul statusu: Tapılmadı ❌"
        )

        return

    print(
        "Məhsul statusu: Tapıldı ✅"
    )

    print(
        f"Ölçü {requested_size}: "
        f"{size_symbol} {size_status_az}"
    )

    available_sizes = clean_text(
        result["available_sizes"]
    )

    if available_sizes:
        print(
            "Stokda olan ölçülər:",
            available_sizes,
        )

    all_sizes = clean_text(
        result["all_sizes"]
    )

    if all_sizes:
        print(
            "Səhifədə görünən bütün ölçülər:",
            all_sizes,
        )

    print(
        "Müqayisəyə daxildir:",
        translate_eligible_status(
            eligible_status
        ),
    )

    local_price = result["price"]
    currency = clean_text(
        result["currency"]
    )

    if local_price is not None:
        print(
            "Yerli qiymət:",
            f"{float(local_price):.2f}",
            currency,
        )

    if result["price_azn"] is not None:
        print(
            "Məhsulun AZN qiyməti:",
            format_money(
                result["price_azn"]
            ),
        )

    product_type = clean_text(
        result["product_type"]
    )

    if product_type:
        print(
            "Məhsul növü:",
            product_type,
        )

    if result["estimated_weight_kg"] is not None:
        print(
            "Təxmini çəki:",
            f'{float(result["estimated_weight_kg"]):.2f} kq',
        )

    if result["estimated_shipping_azn"] is not None:
        print(
            "Təxmini kargo:",
            format_money(
                result[
                    "estimated_shipping_azn"
                ]
            ),
        )

    if result["final_cost_azn"] is not None:
        print(
            "Təxmini yekun:",
            format_money(
                result["final_cost_azn"]
            ),
        )

    if result["rank"] is not None:
        print(
            "Sıralama:",
            result["rank"],
        )

    size_note = clean_text(
        result["size_status_note"]
    )

    if size_note:
        print(
            "Ölçü qeydi:",
            size_note,
        )

    shipping_note = clean_text(
        result["shipping_estimate_note"]
    )

    if shipping_note:
        print(
            "Kargo qeydi:",
            shipping_note,
        )


# ============================================================
# ƏN MÜNASİB SEÇİMİN GÖSTƏRİLMƏSİ
# ============================================================

def show_cheapest_result(
    cheapest_result: sqlite3.Row | None,
    requested_size: str,
) -> None:
    """
    Seçilmiş ölçü üzrə ən münasib ölkəni göstərir.
    """

    print(
        "\n"
        + "=" * 100
    )

    print(
        f"{requested_size} ÖLÇÜSÜ ÜÇÜN "
        "ƏN MÜNASİB SEÇİM"
    )

    print(
        "=" * 100
    )

    if cheapest_result is None:
        print(
            "Seçilmiş ölçü üzrə müqayisəyə uyğun "
            "ölkə tapılmadı."
        )

        return

    country = country_name_az(
        clean_text(
            cheapest_result["country"]
        )
    )

    print(
        "Ölkə:",
        country,
    )

    print(
        "Təxmini yekun ödəniş:",
        format_money(
            cheapest_result[
                "final_cost_azn"
            ]
        ),
    )

    difference = cheapest_result[
        "difference_vs_azerbaijan"
    ]

    if difference is None:
        print(
            "Azərbaycan üzrə seçilmiş ölçü "
            "stokda olmadığı üçün qiymət fərqi "
            "hesablanmayıb."
        )

        return

    difference = float(
        difference
    )

    if difference > 0:
        print(
            "Azərbaycandan daha ucuzdur:",
            f"{difference:.2f} AZN",
        )

    elif difference < 0:
        print(
            "Azərbaycan qiymətindən daha bahadır:",
            f"{abs(difference):.2f} AZN",
        )

    else:
        print(
            "Azərbaycan qiyməti ilə eynidir."
        )


# ============================================================
# SON SORĞULARIN QISA SİYAHISI
# ============================================================

def show_recent_searches(
    connection: sqlite3.Connection,
    limit: int = 5,
) -> None:
    """
    Son bir neçə sorğunu qısa formada göstərir.
    """

    cursor = connection.execute(
        """
        SELECT
            search_id,
            user_id,
            product_code,
            product_name,
            requested_size,
            created_at
        FROM searches
        ORDER BY search_id DESC
        LIMIT ?
        """,
        (
            limit,
        ),
    )

    searches = cursor.fetchall()

    print(
        "\n"
        + "=" * 100
    )

    print(
        f"SON {limit} SORĞU"
    )

    print(
        "=" * 100
    )

    if not searches:
        print(
            "Sorğu tapılmadı."
        )

        return

    for search in searches:
        print(
            f'#{search["search_id"]} | '
            f'{clean_text(search["user_id"]) or "-"} | '
            f'{clean_text(search["product_code"]) or "-"} | '
            f'Ölçü: '
            f'{clean_text(search["requested_size"]) or "-"} | '
            f'{clean_text(search["created_at"]) or "-"}'
        )

        print(
            "   ",
            clean_text(
                search["product_name"]
            )
            or "Mango məhsulu",
        )


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """
    Database-dəki ən son sorğunu göstərir.
    """

    print(
        "=" * 100
    )

    print(
        "MANGO PRICE BOT — DATABASE VIEW"
    )

    print(
        "=" * 100
    )

    print(
        "Database:",
        DATABASE_FILE.resolve(),
    )

    connection = connect_database()

    try:
        validate_database(
            connection
        )

        searches_count, results_count = (
            get_database_counts(
                connection
            )
        )

        print(
            "\nÜmumi sorğu sayı:",
            searches_count,
        )

        print(
            "Ümumi ölkə nəticələrinin sayı:",
            results_count,
        )

        latest_search = get_latest_search(
            connection
        )

        if latest_search is None:
            print(
                "\nDatabase-də hələ sorğu yoxdur."
            )

            return

        search_id = int(
            latest_search["search_id"]
        )

        requested_size = clean_text(
            latest_search["requested_size"]
        ) or "-"

        results = get_search_results(
            connection=connection,
            search_id=search_id,
        )

        show_search_header(
            latest_search
        )

        if not results:
            print(
                "\nBu sorğuya aid ölkə nəticəsi tapılmadı."
            )

        else:
            print(
                "\n"
                + "=" * 100
            )

            print(
                "ÖLKƏLƏR ÜZRƏ QİYMƏT VƏ ÖLÇÜ NƏTİCƏLƏRİ"
            )

            print(
                "=" * 100
            )

            for result in results:
                show_country_result(
                    result=result,
                    requested_size=requested_size,
                )

            cheapest_result = get_cheapest_result(
                results
            )

            show_cheapest_result(
                cheapest_result=cheapest_result,
                requested_size=requested_size,
            )

        show_recent_searches(
            connection=connection,
            limit=5,
        )

    except sqlite3.OperationalError as error:
        if "locked" in str(
            error
        ).lower():
            raise RuntimeError(
                "Database başqa proqramda açıqdır.\n\n"
                "DB Browser və digər database "
                "proqramlarını bağla və yenidən yoxla."
            ) from error

        raise

    finally:
        connection.close()

    print(
        "\n✅ SQL məlumatları uğurla göstərildi."
    )


if __name__ == "__main__":
    main()