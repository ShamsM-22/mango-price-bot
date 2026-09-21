import sqlite3
from pathlib import Path


# ============================================================
# DATABASE YOLU
# ============================================================

DATABASE_FOLDER = Path(
    "database"
)

DATABASE_FILE = (
    DATABASE_FOLDER
    / "mango_price_bot.db"
)


# ============================================================
# ƏSAS CƏDVƏLLƏR
# ============================================================

CREATE_SEARCHES_TABLE = """
CREATE TABLE IF NOT EXISTS searches (
    search_id INTEGER PRIMARY KEY AUTOINCREMENT,

    user_id TEXT,

    product_url TEXT,

    product_code TEXT,

    product_name TEXT,

    requested_size TEXT,

    created_at TEXT
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP
)
"""


CREATE_PRICE_RESULTS_TABLE = """
CREATE TABLE IF NOT EXISTS price_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,

    search_id INTEGER NOT NULL,

    country_code TEXT,

    country TEXT,

    available TEXT,

    product_name TEXT,

    price REAL,

    currency TEXT,

    exchange_rate REAL,

    rate_date TEXT,

    price_azn REAL,

    requested_size TEXT,

    all_sizes TEXT,

    available_sizes TEXT,

    size_available TEXT,

    product_type TEXT,

    estimated_weight_kg REAL,

    estimated_shipping_azn REAL,

    shipping_tariff_count INTEGER,

    shipping_estimate_note TEXT,

    size_status_note TEXT,

    eligible_for_comparison TEXT,

    final_cost_azn REAL,

    difference_vs_azerbaijan REAL,

    rank INTEGER,

    conversion_status TEXT,

    product_url TEXT,

    created_at TEXT
        NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (
        search_id
    )
    REFERENCES searches (
        search_id
    )
)
"""


# ============================================================
# YENİ SÜTUNLAR
# ============================================================

SEARCHES_COLUMNS = {
    "user_id": "TEXT",

    "product_url": "TEXT",

    "product_code": "TEXT",

    "product_name": "TEXT",

    "requested_size": "TEXT",

    "created_at": (
        "TEXT DEFAULT CURRENT_TIMESTAMP"
    ),
}


PRICE_RESULTS_COLUMNS = {
    "search_id": "INTEGER",

    "country_code": "TEXT",

    "country": "TEXT",

    "available": "TEXT",

    "product_name": "TEXT",

    "price": "REAL",

    "currency": "TEXT",

    "exchange_rate": "REAL",

    "rate_date": "TEXT",

    "price_azn": "REAL",

    "requested_size": "TEXT",

    "all_sizes": "TEXT",

    "available_sizes": "TEXT",

    "size_available": "TEXT",

    "product_type": "TEXT",

    "estimated_weight_kg": "REAL",

    "estimated_shipping_azn": "REAL",

    "shipping_tariff_count": "INTEGER",

    "shipping_estimate_note": "TEXT",

    "size_status_note": "TEXT",

    "eligible_for_comparison": "TEXT",

    "final_cost_azn": "REAL",

    "difference_vs_azerbaijan": "REAL",

    "rank": "INTEGER",

    "conversion_status": "TEXT",

    "product_url": "TEXT",

    "created_at": (
        "TEXT DEFAULT CURRENT_TIMESTAMP"
    ),
}


# ============================================================
# DATABASE BAĞLANTISI
# ============================================================

def connect_database() -> sqlite3.Connection:
    """
    SQLite database ilə bağlantı yaradır.
    """

    DATABASE_FOLDER.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        DATABASE_FILE
    )

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    return connection


# ============================================================
# CƏDVƏL SÜTUNLARININ OXUNMASI
# ============================================================

def get_table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    """
    Cədvəldə mövcud olan sütunların
    adlarını qaytarır.
    """

    cursor = connection.execute(
        f"PRAGMA table_info({table_name})"
    )

    columns = {
        str(row[1])
        for row in cursor.fetchall()
    }

    return columns


# ============================================================
# ÇATIŞMAYAN SÜTUNLARIN ƏLAVƏ EDİLMƏSİ
# ============================================================

def add_missing_columns(
    connection: sqlite3.Connection,
    table_name: str,
    required_columns: dict[str, str],
) -> None:
    """
    Köhnə database-də olmayan yeni
    sütunları avtomatik əlavə edir.

    Mövcud məlumatlar silinmir.
    """

    existing_columns = get_table_columns(
        connection=connection,
        table_name=table_name,
    )

    for (
        column_name,
        column_definition,
    ) in required_columns.items():

        if column_name in existing_columns:
            print(
                f"   Mövcuddur: "
                f"{table_name}.{column_name}"
            )

            continue

        sql = (
            f"ALTER TABLE {table_name} "
            f"ADD COLUMN {column_name} "
            f"{column_definition}"
        )

        try:
            connection.execute(
                sql
            )

            print(
                f"   Əlavə edildi: "
                f"{table_name}.{column_name}"
            )

        except sqlite3.OperationalError as error:
            # Bəzi köhnə SQLite versiyalarında
            # ALTER TABLE zamanı CURRENT_TIMESTAMP
            # default dəyəri problem yarada bilər.
            if (
                column_name == "created_at"
                and "default" in str(
                    error
                ).lower()
            ):
                fallback_sql = (
                    f"ALTER TABLE {table_name} "
                    f"ADD COLUMN {column_name} TEXT"
                )

                connection.execute(
                    fallback_sql
                )

                print(
                    f"   Əlavə edildi: "
                    f"{table_name}.{column_name} "
                    f"(default olmadan)"
                )

            else:
                raise


# ============================================================
# CƏDVƏLLƏRİN YARADILMASI
# ============================================================

def create_tables(
    connection: sqlite3.Connection,
) -> None:
    """
    Əsas SQL cədvəllərini yaradır.
    """

    connection.execute(
        CREATE_SEARCHES_TABLE
    )

    connection.execute(
        CREATE_PRICE_RESULTS_TABLE
    )

    print(
        "Əsas cədvəllər hazırdır."
    )


# ============================================================
# DATABASE MİQRASİYASI
# ============================================================

def update_database_structure(
    connection: sqlite3.Connection,
) -> None:
    """
    Köhnə database varsa ölçü sütunlarını
    və digər çatışmayan sütunları əlavə edir.
    """

    print(
        "\nsearches cədvəli yoxlanılır..."
    )

    add_missing_columns(
        connection=connection,
        table_name="searches",
        required_columns=SEARCHES_COLUMNS,
    )

    print(
        "\nprice_results cədvəli yoxlanılır..."
    )

    add_missing_columns(
        connection=connection,
        table_name="price_results",
        required_columns=PRICE_RESULTS_COLUMNS,
    )


# ============================================================
# İNDEKSLƏR
# ============================================================

def create_indexes(
    connection: sqlite3.Connection,
) -> None:
    """
    Sonrakı SQL sorğularının daha sürətli
    işləməsi üçün indekslər yaradır.
    """

    index_queries = [
        """
        CREATE INDEX IF NOT EXISTS
        idx_searches_user_id
        ON searches(user_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_searches_product_code
        ON searches(product_code)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_searches_requested_size
        ON searches(requested_size)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_searches_created_at
        ON searches(created_at)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_price_results_search_id
        ON price_results(search_id)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_price_results_country_code
        ON price_results(country_code)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_price_results_size_available
        ON price_results(size_available)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_price_results_eligible
        ON price_results(
            eligible_for_comparison
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_price_results_rank
        ON price_results(rank)
        """,
    ]

    for query in index_queries:
        connection.execute(
            query
        )

    print(
        "\nDatabase indeksləri hazırdır."
    )


# ============================================================
# CƏDVƏL MƏLUMATLARI
# ============================================================

def show_table_structure(
    connection: sqlite3.Connection,
    table_name: str,
) -> None:
    """
    Cədvəlin sütunlarını terminalda göstərir.
    """

    cursor = connection.execute(
        f"PRAGMA table_info({table_name})"
    )

    rows = cursor.fetchall()

    print(
        "\n"
        + "=" * 80
    )

    print(
        f"{table_name.upper()} CƏDVƏLİ"
    )

    print(
        "=" * 80
    )

    for row in rows:
        column_number = row[0]
        column_name = row[1]
        column_type = row[2]
        not_null = row[3]
        default_value = row[4]
        primary_key = row[5]

        print(
            f"{column_number:>2}. "
            f"{column_name:<32} "
            f"{column_type:<12} "
            f"PK={primary_key} "
            f"NOT NULL={not_null} "
            f"DEFAULT={default_value}"
        )


# ============================================================
# MƏLUMAT SAYLARI
# ============================================================

def get_table_count(
    connection: sqlite3.Connection,
    table_name: str,
) -> int:
    """
    Cədvəldə olan məlumat sayını qaytarır.
    """

    cursor = connection.execute(
        f"SELECT COUNT(*) FROM {table_name}"
    )

    result = cursor.fetchone()

    if result is None:
        return 0

    return int(
        result[0]
    )


def show_database_summary(
    connection: sqlite3.Connection,
) -> None:
    """
    Database üzrə ümumi məlumat göstərir.
    """

    searches_count = get_table_count(
        connection=connection,
        table_name="searches",
    )

    price_results_count = get_table_count(
        connection=connection,
        table_name="price_results",
    )

    print(
        "\n"
        + "=" * 80
    )

    print(
        "DATABASE YEKUN MƏLUMATI"
    )

    print(
        "=" * 80
    )

    print(
        "Database faylı:",
        DATABASE_FILE.resolve(),
    )

    print(
        "Sorğu sayı:",
        searches_count,
    )

    print(
        "Ölkə nəticələrinin sayı:",
        price_results_count,
    )


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """
    Database strukturunu yaradır və yeniləyir.
    """

    print(
        "=" * 80
    )

    print(
        "MANGO PRICE BOT — DATABASE SETUP"
    )

    print(
        "=" * 80
    )

    print(
        "\nDatabase faylı:"
    )

    print(
        DATABASE_FILE.resolve()
    )

    connection = connect_database()

    try:
        create_tables(
            connection
        )

        update_database_structure(
            connection
        )

        create_indexes(
            connection
        )

        connection.commit()

        show_table_structure(
            connection=connection,
            table_name="searches",
        )

        show_table_structure(
            connection=connection,
            table_name="price_results",
        )

        show_database_summary(
            connection
        )

    except Exception:
        connection.rollback()

        raise

    finally:
        connection.close()

    print(
        "\n✅ Database uğurla hazırlandı və yeniləndi."
    )

    print(
        "Əvvəlki məlumatlar silinmədi."
    )


if __name__ == "__main__":
    main()