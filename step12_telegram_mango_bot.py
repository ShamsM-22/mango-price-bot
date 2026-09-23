import asyncio
import csv
import logging
import os
import re
import secrets
import socket
import subprocess
import sys

from pathlib import Path

from dotenv import dotenv_values

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)

from telegram.constants import ChatAction
from telegram.error import InvalidToken

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from step04_compare_countries import (
    discover_available_sizes,
)


# ============================================================
# LAYİHƏ YOLLARI
# ============================================================

PROJECT_FOLDER = Path(
    __file__
).resolve().parent

DATA_FOLDER = (
    PROJECT_FOLDER
    / "data"
)

DATA_FOLDER.mkdir(
    parents=True,
    exist_ok=True,
)

FINAL_RESULT_FILE = (
    DATA_FOLDER
    / "final_price_comparison.csv"
)

ERROR_LOG_FILE = (
    DATA_FOLDER
    / "telegram_bot_errors.log"
)


STEP_FILES = {
    "setup": PROJECT_FOLDER / "step07_database.py",
    "compare": (
        PROJECT_FOLDER
        / "step04_compare_countries.py"
    ),

    "convert": (
        PROJECT_FOLDER
        / "step05_convert_to_azn.py"
    ),

    "shipping": (
        PROJECT_FOLDER
        / "step06_add_shipping_cost.py"
    ),

    "database": (
        PROJECT_FOLDER
        / "step08_save_to_database.py"
    ),
}


COUNTRY_NAMES_AZ = {
    "Azerbaijan": "Azərbaycan",
    "Spain": "İspaniya",
    "Turkey": "Türkiyə",
}


COUNTRY_ORDER = {
    "ES": 1,
    "TR": 2,
    "AZ": 3,
}


# Step 04–08 eyni CSV fayllarına yazdığı üçün
# eyni anda yalnız bir tam müqayisə işlədilir.
WORKFLOW_LOCK = asyncio.Lock()

# Eyni kompüterdə iki bot prosesinin paralel işləməsinin
# və eyni mesajın iki dəfə cavablandırılmasının qarşısını alır.
BOT_INSTANCE_SOCKET = None
BOT_INSTANCE_PORT = 47891


def acquire_single_instance_lock() -> socket.socket:
    """
    Lokal port kilidi ilə yalnız bir bot prosesinə icazə verir.
    """

    instance_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    )

    try:
        instance_socket.bind(
            (
                "127.0.0.1",
                BOT_INSTANCE_PORT,
            )
        )

        instance_socket.listen(
            1
        )

    except OSError as error:
        instance_socket.close()

        raise RuntimeError(
            "Mango Telegram botunun başqa prosesi "
            "hazırda işləyir. Əvvəl köhnə Python "
            "prosesini dayandır və sonra yenidən başlat."
        ) from error

    return instance_socket


# ============================================================
# LOG SİSTEMİ
# ============================================================

console_handler = logging.StreamHandler()

file_handler = logging.FileHandler(
    ERROR_LOG_FILE,
    encoding="utf-8",
)

logging.basicConfig(
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
    level=logging.INFO,
    handlers=[
        console_handler,
        file_handler,
    ],
)

# Telegram API sorğularının tam URL-lərini loglama.
# Bu, bot tokeninin terminal və log faylında görünməsinin qarşısını alır.
logging.getLogger("httpx").setLevel(
    logging.WARNING
)

logging.getLogger("httpcore").setLevel(
    logging.WARNING
)

logger = logging.getLogger(
    __name__
)


# ============================================================
# TELEGRAM TOKEN
# ============================================================

ENV_FILE = (
    PROJECT_FOLDER
    / ".env"
)


def read_telegram_token() -> str:
    """Cloud environment, sonra lokal .env faylından tokeni oxuyur."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token and ENV_FILE.exists():
        values = dotenv_values(ENV_FILE, encoding="utf-8-sig")
        token = str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN tapılmadı. "
            "Lokal .env faylını və ya cloud Variables bölməsini yoxla."
        )
    return token






# ============================================================
# KÖMƏKÇİ FUNKSİYALAR
# ============================================================

def clean_text(value) -> str:
    """
    None və boş dəyərləri təmizləyir.
    """

    if value is None:
        return ""

    return str(value).strip()


def to_float(value) -> float | None:
    """
    CSV dəyərini float-a çevirir.
    """

    if value is None:
        return None

    clean_value = str(
        value
    ).strip()

    if clean_value == "":
        return None

    try:
        return float(
            clean_value.replace(
                ",",
                ".",
            )
        )

    except ValueError:
        return None


def country_name_az(
    country: str | None,
) -> str:
    """
    Ölkə adını Azərbaycan dilində göstərir.
    """

    if not country:
        return "-"

    return COUNTRY_NAMES_AZ.get(
        country,
        country,
    )


def normalize_yes_no(value) -> str:
    """
    Yes, No və Unknown dəyərlərini
    standart formaya çevirir.
    """

    clean_value = clean_text(
        value
    ).lower()

    if clean_value in {
        "yes",
        "true",
        "1",
        "available",
    }:
        return "Yes"

    if clean_value in {
        "no",
        "false",
        "0",
        "unavailable",
    }:
        return "No"

    return "Unknown"


def extract_mango_product_url(
    text: str,
) -> str | None:
    """
    Mesajın içindən Mango məhsul URL-ni çıxarır.

    Mango saytından Share -> Telegram zamanı
    linklə birlikdə məhsul adı və əlavə mətn də
    gələ bilər. Bot yalnız /p/ olan məhsul linkini
    götürür və qalan mətni nəzərə almır.
    """

    if not text:
        return None

    matches = re.findall(
        r"https://shop\.mango\.com/"
        r"[^\s<>\[\]\(\)\{\}\"']+",
        text,
        flags=re.IGNORECASE,
    )

    for match in matches:
        candidate = match.rstrip(
            ".,;:!?)]}>"
        )

        if "/p/" in candidate.lower():
            return candidate

    return None


def is_mango_product_url(
    text: str,
) -> bool:
    """
    Mətndə düzgün Mango məhsul linkinin
    olub-olmadığını yoxlayır.
    """

    return (
        extract_mango_product_url(text)
        is not None
    )


def readable_sizes(value: str) -> str:
    """
    CSV-də | işarəsi ilə saxlanmış
    ölçüləri oxunaqlı formaya çevirir.
    """

    return (
        clean_text(value)
        .replace(
            " | ",
            ", ",
        )
        .replace(
            "|",
            ", ",
        )
    )


def check_required_files() -> None:
    """
    Lazım olan proqram fayllarını yoxlayır.
    """

    missing_files = [
        path.name
        for path
        in STEP_FILES.values()
        if not path.exists()
    ]

    if missing_files:
        raise FileNotFoundError(
            "Bu fayllar tapılmadı:\n"
            + "\n".join(
                missing_files
            )
        )


def remove_old_result_files() -> None:
    """
    Köhnə məhsul nəticələrini silir.
    """

    files_to_remove = [
        DATA_FOLDER
        / "country_price_comparison.csv",

        DATA_FOLDER
        / "country_price_comparison_azn.csv",

        DATA_FOLDER
        / "final_price_comparison.csv",

        DATA_FOLDER
        / "last_search.txt",

        DATA_FOLDER
        / "last_requested_size.txt",
    ]

    for file_path in files_to_remove:

        if not file_path.exists():
            continue

        try:
            file_path.unlink()

        except PermissionError as error:
            raise RuntimeError(
                f"{file_path.name} faylı açıqdır.\n"
                "Excel və ya digər proqramda həmin "
                "faylı bağla, sonra yenidən yoxla."
            ) from error


# ============================================================
# PYTHON ADDIMLARININ İŞƏ SALINMASI
# ============================================================

def run_python_script(
    script_path: Path,
    input_text: str | None = None,
) -> str:
    """
    Mövcud Python addımlarını bot daxilindən
    virtual mühitlə işə salır.
    """

    logger.info(
        "İşə salınır: %s",
        script_path.name,
    )

    environment = os.environ.copy()

    environment[
        "PYTHONIOENCODING"
    ] = "utf-8"

    environment[
        "PYTHONUTF8"
    ] = "1"

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(
                    script_path
                ),
            ],
            input=input_text,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            cwd=PROJECT_FOLDER,
            timeout=900,
            env=environment,
        )

    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"{script_path.name} "
            "15 dəqiqədən çox çəkdi və "
            "avtomatik dayandırıldı."
        ) from error

    output_text = (
        result.stdout.strip()
        if result.stdout
        else ""
    )

    error_text = (
        result.stderr.strip()
        if result.stderr
        else ""
    )

    if output_text:
        logger.info(
            "%s terminal nəticəsi:\n%s",
            script_path.name,
            output_text,
        )

    if error_text:
        logger.warning(
            "%s stderr nəticəsi:\n%s",
            script_path.name,
            error_text,
        )

    if result.returncode != 0:

        full_error = (
            error_text
            or output_text
            or "Xətanın detalları alınmadı."
        )

        logger.error(
            "%s işləmədi. Return code: %s\n%s",
            script_path.name,
            result.returncode,
            full_error,
        )

        raise RuntimeError(
            f"{script_path.name} xətası:\n\n"
            f"{full_error[-2800:]}"
        )

    logger.info(
        "Tamamlandı: %s",
        script_path.name,
    )

    return output_text


# ============================================================
# CSV NƏTİCƏSİNİN OXUNMASI
# ============================================================

def read_final_results() -> list[dict]:
    """
    Step 06 nəticəsini oxuyur.
    """

    if not FINAL_RESULT_FILE.exists():
        raise FileNotFoundError(
            "Yekun nəticə faylı yaranmadı:\n"
            "data/final_price_comparison.csv"
        )

    with FINAL_RESULT_FILE.open(
        mode="r",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:

        reader = csv.DictReader(
            csv_file
        )

        results = list(
            reader
        )

    # ABŞ aktiv müqayisə bazarı deyil.
    # Köhnə/stale CSV-də US sətri qalsa belə botda göstərilmir.
    results = [
        result
        for result in results
        if str(
            result.get(
                "country_code",
                "",
            )
            or ""
        ).strip().upper()
        != "US"
    ]

    if not results:
        raise RuntimeError(
            "Yekun nəticə CSV faylı boşdur."
        )

    return results


def get_preferred_product_name(
    results: list[dict],
) -> str:
    """
    Məhsul adını ilk olaraq Azərbaycan
    nəticəsindən götürür.
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
            result
            for result in results
            if clean_text(
                result.get(
                    "country_code"
                )
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

    for result in results:

        product_name = clean_text(
            result.get(
                "product_name"
            )
        )

        if product_name not in invalid_names:
            return product_name

    return "Mango məhsulu"


def get_first_value(
    results: list[dict],
    column_name: str,
    default: str = "-",
) -> str:
    """
    CSV-də ilk boş olmayan dəyəri tapır.
    """

    for result in results:

        value = clean_text(
            result.get(
                column_name
            )
        )

        if value:
            return value

    return default


# ============================================================
# TELEGRAM NƏTİCƏ MESAJI
# ============================================================

def build_result_message(
    results: list[dict],
    requested_size: str,
) -> str:
    """
    Seçilmiş ölçüyə əsasən Telegram
    nəticə mesajını hazırlayır.
    """

    csv_requested_size = get_first_value(
        results,
        "requested_size",
        default=requested_size,
    )

    if csv_requested_size:
        requested_size = csv_requested_size

    valid_results = [
        result
        for result in results
        if (
            normalize_yes_no(
                result.get(
                    "eligible_for_comparison"
                )
            )
            == "Yes"
            and
            normalize_yes_no(
                result.get(
                    "size_available"
                )
            )
            == "Yes"
            and
            to_float(
                result.get(
                    "final_cost_azn"
                )
            )
            is not None
        )
    ]

    valid_results.sort(
        key=lambda result: (
            to_float(
                result.get(
                    "final_cost_azn"
                )
            )
            or float(
                "inf"
            )
        )
    )

    product_name = (
        get_preferred_product_name(
            results
        )
    )

    product_code = get_first_value(
        results,
        "product_code",
    )

    product_type = get_first_value(
        results,
        "product_type",
    )

    original_country_code = get_first_value(
        results,
        "original_country_code",
        default="-",
    )

    estimated_weight = next(
        (
            to_float(
                result.get(
                    "estimated_weight_kg"
                )
            )
            for result in results
            if to_float(
                result.get(
                    "estimated_weight_kg"
                )
            )
            is not None
        ),
        None,
    )

    lines = [
        (
            f"✅ {requested_size} ÖLÇÜSÜ ÜZRƏ "
            "MÜQAYİSƏ HAZIRDIR"
        ),
        "",
        f"🛍 Məhsul: {product_name}",
        f"🔢 Məhsul kodu: {product_code}",
        f"📏 Orijinal linkdə seçilən ölçü: {requested_size}",
    ]

    if (
        original_country_code
        and original_country_code != "-"
    ):
        lines.append(
            f"🌐 Orijinal bazar: "
            f"{original_country_code}"
        )

    lines.append(
        f"📦 Məhsul növü: {product_type}"
    )

    if estimated_weight is not None:

        lines.append(
            f"⚖️ Təxmini çəki: "
            f"{estimated_weight:.2f} kq"
        )

    lines.extend(
        [
            "",
            "🌍 ÖLKƏLƏR ÜZRƏ NƏTİCƏ",
        ]
    )

    display_results = sorted(
        results,
        key=lambda result: (
            COUNTRY_ORDER.get(
                clean_text(
                    result.get(
                        "country_code"
                    )
                ).upper(),
                99,
            )
        ),
    )

    for result in display_results:

        country = country_name_az(
            clean_text(
                result.get(
                    "country"
                )
            )
        )

        product_available = (
            normalize_yes_no(
                result.get(
                    "available"
                )
            )
        )

        size_status = normalize_yes_no(
            result.get(
                "size_available"
            )
        )

        matched_size = clean_text(
            result.get(
                "matched_size"
            )
        )

        size_match_method = clean_text(
            result.get(
                "size_match_method"
            )
        )

        available_sizes = readable_sizes(
            result.get(
                "available_sizes",
                "",
            )
        )

        lines.extend(
            [
                "",
                f"📍 {country}",
            ]
        )

        if product_available != "Yes":

            lines.append(
                "   Məhsul bu ölkədə "
                "tapılmadı ❌"
            )

            continue

        if matched_size:
            if (
                clean_text(matched_size).upper()
                != clean_text(
                    requested_size
                ).upper()
            ):
                lines.append(
                    f"   Uyğun lokal ölçü: "
                    f"{matched_size}"
                )
            else:
                lines.append(
                    f"   Lokal ölçü: "
                    f"{matched_size}"
                )

        if size_status == "No":

            lines.append(
                f"   {requested_size} ölçüsü bu ölkədə "
                "mövcud deyil ❌"
            )

            lines.append(
                "   Qiymət müqayisəsinə "
                "daxil edilmədi."
            )

            continue

        if size_status == "Unknown":

            if size_match_method == "unknown":
                lines.append(
                    f"   {requested_size} ölçüsü bu ölkədə "
                    "mövcud deyil ❌"
                )
            else:
                lines.append(
                    f"   {requested_size} ölçüsünün stoku "
                    "yoxlanıla bilmədi ⚠️"
                )

            lines.append(
                "   Qiymət müqayisəsinə "
                "daxil edilmədi."
            )

            continue

        lines.append(
            "   Uyğun ölçü: "
            "mövcuddur ✅"
        )

        local_price = to_float(
            result.get(
                "price"
            )
        )

        currency = clean_text(
            result.get(
                "currency"
            )
        )

        price_azn = to_float(
            result.get(
                "price_azn"
            )
        )

        shipping = to_float(
            result.get(
                "estimated_shipping_azn"
            )
        )

        final_cost = to_float(
            result.get(
                "final_cost_azn"
            )
        )

        if local_price is not None:

            lines.append(
                f"   Yerli qiymət: "
                f"{local_price:.2f} "
                f"{currency}"
            )

        if price_azn is not None:

            lines.append(
                f"   Məhsulun AZN qiyməti: "
                f"{price_azn:.2f} AZN"
            )

        if shipping is not None:

            lines.append(
                f"   Təxmini kargo: "
                f"{shipping:.2f} AZN"
            )

        if final_cost is not None:

            lines.append(
                f"   Təxmini yekun: "
                f"{final_cost:.2f} AZN"
            )

        else:

            lines.append(
                "   Yekun qiymət "
                "hesablana bilmədi."
            )

    lines.append("")

    if not valid_results:

        lines.extend(
            [
                "❌ ƏN MÜNASİB SEÇİM TAPILMADI",
                "",
                (
                    f"{requested_size} seçiminə uyğun "
                    "ölçü üzrə yekun qiyməti hesablana "
                    "bilən ölkə yoxdur."
                ),
            ]
        )

        return "\n".join(
            lines
        )

    cheapest = valid_results[0]

    cheapest_country = country_name_az(
        clean_text(
            cheapest.get(
                "country"
            )
        )
    )

    cheapest_cost = to_float(
        cheapest.get(
            "final_cost_azn"
        )
    )

    cheapest_matched_size = clean_text(
        cheapest.get(
            "matched_size"
        )
    )

    if cheapest_cost is None:

        raise RuntimeError(
            "Ən münasib yekun qiymət oxunmadı."
        )

    lines.extend(
        [
            "🏆 ƏN MÜNASİB SEÇİM",
            "",
            f"{cheapest_country}",
        ]
    )

    return "\n".join(
        lines
    )


# ============================================================
# TAM QİYMƏT PROSESİ
# ============================================================

def run_full_workflow(
    product_url: str,
    requested_size: str,
    telegram_user_id: int,
) -> str:
    """
    Step 04, 05, 06 və 08-i ardıcıllıqla
    işə salır.
    """

    check_required_files()

    remove_old_result_files()

    # Step 04 əvvəl linki,
    # sonra seçilmiş ölçünü gözləyir.
    run_python_script(
        STEP_FILES[
            "compare"
        ],
        input_text=(
            f"{product_url}\n"
            f"{requested_size}\n"
        ),
    )

    run_python_script(
        STEP_FILES[
            "convert"
        ]
    )

    run_python_script(
        STEP_FILES[
            "shipping"
        ]
    )

    database_user_id = (
        f"telegram_"
        f"{telegram_user_id}"
    )

    run_python_script(
        STEP_FILES[
            "database"
        ],
        input_text=(
            f"{database_user_id}\n"
        ),
    )

    results = read_final_results()

    return build_result_message(
        results=results,
        requested_size=requested_size,
    )


# ============================================================
# TELEGRAM ÖLÇÜ DÜYMƏLƏRİ
# ============================================================

def build_size_keyboard(
    sizes: list[str],
    request_token: str,
) -> InlineKeyboardMarkup:
    """
    Ölçüləri hər sətirdə 3 düymə olmaqla göstərir.
    """

    buttons = [
        InlineKeyboardButton(
            text=size,
            callback_data=(
                f"size|"
                f"{request_token}|"
                f"{index}"
            ),
        )
        for index, size
        in enumerate(
            sizes
        )
    ]

    rows = [
        buttons[
            index:index + 3
        ]
        for index
        in range(
            0,
            len(buttons),
            3,
        )
    ]

    return InlineKeyboardMarkup(
        rows
    )


# ============================================================
# UZUN TELEGRAM MESAJLARI
# ============================================================

async def send_long_message(
    message: Message,
    text: str,
) -> None:
    """
    Telegram mesajı çox uzun olduqda
    hissələrə bölür.
    """

    maximum_length = 3900

    if len(
        text
    ) <= maximum_length:

        await message.reply_text(
            text
        )

        return

    current_part = ""

    for paragraph in text.split(
        "\n"
    ):

        candidate = (
            current_part
            + paragraph
            + "\n"
        )

        if len(
            candidate
        ) > maximum_length:

            if current_part:

                await message.reply_text(
                    current_part.strip()
                )

            current_part = (
                paragraph
                + "\n"
            )

        else:

            current_part = candidate

    if current_part:

        await message.reply_text(
            current_part.strip()
        )


# ============================================================
# TELEGRAM ƏMRLƏRİ
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    /start əmri.
    """

    message = update.effective_message

    user = update.effective_user

    if message is None:
        return

    first_name = (
        user.first_name
        if user
        and user.first_name
        else "istifadəçi"
    )

    await message.reply_text(
        f"Salam, {first_name}! 👋\n\n"
        "Mən Mango məhsulunun qiymətini "
        "Azərbaycan, İspaniya və Türkiyə "
        "üzrə müqayisə edirəm.\n\n"
        "1️⃣ Mango məhsul linkini göndər.\n"
        "2️⃣ Mən orijinal linkdə stokda olan "
        "ölçüləri düymələrlə göstərəcəyəm.\n"
        "3️⃣ Ölçünü seçdikdən sonra həmin fiziki "
        "ölçünün digər ölkələrdəki uyğun lokal "
        "ölçüsünü və stokunu yoxlayacağam."
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    /help əmri.
    """

    message = update.effective_message

    if message is None:
        return

    await message.reply_text(
        "Mango məhsul linkini göndər.\n\n"
        "Link belə başlamalıdır:\n"
        "https://shop.mango.com/\n\n"
        "Bot linkdəki stok ölçülərini tapacaq "
        "və düymələrlə göstərəcək.\n\n"
        "Ayaqqabıda ölkə ölçüləri fərqlidirsə, "
        "bot Mango səhifəsində göstərilən EUR "
        "qarşılığına əsasən uyğun lokal ölçünü "
        "ayrıca göstərəcək."
    )


async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Cari ölçü seçimini ləğv edir.
    """

    message = update.effective_message

    context.user_data.pop(
        "pending_product_url",
        None,
    )

    context.user_data.pop(
        "pending_sizes",
        None,
    )

    context.user_data.pop(
        "request_token",
        None,
    )

    if message is not None:

        await message.reply_text(
            "Cari ölçü seçimi ləğv edildi.\n"
            "Yeni Mango linki göndərə bilərsən."
        )


# ============================================================
# LINKİN QƏBULU VƏ ÖLÇÜLƏRİN TAPILMASI
# ============================================================

async def handle_text_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Mango linkini qəbul edir və stokda olan
    ölçüləri müəyyən edir.
    """

    message = update.effective_message

    chat = update.effective_chat

    if (
        message is None
        or message.text is None
        or chat is None
    ):
        return

    message_sources = [
        message.text
    ]

    # Telegram text_link entity ilə gizli URL
    # göndəribsə onu da yoxlayır.
    for entity in (
        message.entities
        or []
    ):
        entity_url = getattr(
            entity,
            "url",
            None,
        )

        if entity_url:
            message_sources.append(
                entity_url
            )

    product_url = ""

    for source_text in message_sources:
        found_url = extract_mango_product_url(
            source_text
        )

        if found_url:
            product_url = found_url
            break

    if not product_url:

        await message.reply_text(
            "❌ Bu, düzgün Mango məhsul "
            "linki deyil.\n\n"
            "Link belə başlamalıdır:\n"
            "https://shop.mango.com/\n\n"
            "Linkin içində /p/ hissəsi də "
            "olmalıdır."
        )

        return

    context.user_data.pop(
        "pending_product_url",
        None,
    )

    context.user_data.pop(
        "pending_sizes",
        None,
    )

    context.user_data.pop(
        "request_token",
        None,
    )

    status_message = (
        await message.reply_text(
            "✅ Link qəbul edildi.\n\n"
            "📏 Məhsulda stokda olan ölçülər "
            "yoxlanılır..."
        )
    )

    await context.bot.send_chat_action(
        chat_id=chat.id,
        action=ChatAction.TYPING,
    )

    try:

        sizes = await asyncio.to_thread(
            discover_available_sizes,
            product_url,
        )

    except Exception as error:

        logger.exception(
            "Məhsul ölçüləri tapılarkən "
            "xəta baş verdi."
        )

        error_text = str(
            error
        )

        if len(
            error_text
        ) > 2500:

            error_text = (
                error_text[-2500:]
            )

        await status_message.edit_text(
            "❌ Məhsuldakı ölçülər oxunarkən "
            "xəta baş verdi.\n\n"
            "Bir qədər sonra linki yenidən göndər."
        )

        return

    sizes = [
        clean_text(
            size
        )
        for size in sizes
        if clean_text(
            size
        )
    ]

    # Təkrar ölçüləri silir,
    # ölçü ardıcıllığını qoruyur.
    sizes = list(
        dict.fromkeys(
            sizes
        )
    )

    if not sizes:

        await status_message.edit_text(
            "❌ Bu məhsulda stokda olan "
            "ölçülər oxunmadı.\n\n"
            "Məhsul hazırda stokda olmaya bilər "
            "və ya Mango səhifəsinin quruluşu "
            "dəyişmiş ola bilər."
        )

        return

    request_token = (
        secrets.token_hex(
            4
        )
    )

    context.user_data[
        "pending_product_url"
    ] = product_url

    context.user_data[
        "pending_sizes"
    ] = sizes

    context.user_data[
        "request_token"
    ] = request_token

    keyboard = build_size_keyboard(
        sizes=sizes,
        request_token=request_token,
    )

    await status_message.edit_text(
        "📏 Hansı ölçünü istəyirsən?\n\n"
        "Aşağıda orijinal Mango linkində "
        "stokda görünən lokal ölçülər verilib:",
        reply_markup=keyboard,
    )


# ============================================================
# ÖLÇÜ DÜYMƏSİNİN QƏBULU
# ============================================================

async def handle_size_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    İstifadəçinin seçdiyi ölçünü qəbul edir
    və tam müqayisəni başladır.
    """

    query = update.callback_query

    user = update.effective_user

    chat = update.effective_chat

    if (
        query is None
        or query.data is None
        or query.message is None
        or user is None
        or chat is None
    ):
        return

    parts = query.data.split(
        "|"
    )

    if len(
        parts
    ) != 3:

        await query.answer(
            "Ölçü seçimi düzgün oxunmadı.",
            show_alert=True,
        )

        return

    (
        _,
        callback_token,
        index_text,
    ) = parts

    current_token = clean_text(
        context.user_data.get(
            "request_token"
        )
    )

    product_url = clean_text(
        context.user_data.get(
            "pending_product_url"
        )
    )

    sizes = context.user_data.get(
        "pending_sizes",
        [],
    )

    if (
        not current_token
        or callback_token
        != current_token
        or not product_url
        or not isinstance(
            sizes,
            list,
        )
    ):

        await query.answer(
            "Bu ölçü seçiminin vaxtı bitib.\n"
            "Mango linkini yenidən göndər.",
            show_alert=True,
        )

        return

    try:

        size_index = int(
            index_text
        )

        requested_size = clean_text(
            sizes[
                size_index
            ]
        )

    except (
        ValueError,
        IndexError,
        TypeError,
    ):

        await query.answer(
            "Ölçü tapılmadı.\n"
            "Linki yenidən göndər.",
            show_alert=True,
        )

        return

    if WORKFLOW_LOCK.locked():

        await query.answer(
            "Hazırda başqa məhsul hesablanır.\n"
            "Bir qədər sonra bu ölçüyə "
            "yenidən bas.",
            show_alert=True,
        )

        return

    await query.answer()

    # Eyni düyməyə ikinci dəfə basılmasının
    # qarşısını alır.
    context.user_data.pop(
        "request_token",
        None,
    )

    await query.edit_message_text(
        f"✅ Orijinal linkdə seçilən ölçü: "
        f"{requested_size}\n\n"
        "İndi bu ölçünün digər ölkələrdəki "
        "uyğun lokal qarşılığı və stoku "
        "yoxlanacaq."
    )

    async with WORKFLOW_LOCK:

        await context.bot.send_chat_action(
            chat_id=chat.id,
            action=ChatAction.TYPING,
        )

        try:

            result_message = (
                await asyncio.to_thread(
                    run_full_workflow,
                    product_url,
                    requested_size,
                    user.id,
                )
            )

        except Exception as error:

            logger.exception(
                "Mango ölçülü müqayisəsi "
                "zamanı xəta baş verdi."
            )

            error_text = str(
                error
            )

            if len(
                error_text
            ) > 3000:

                error_text = (
                    error_text[-3000:]
                )

            await query.message.reply_text(
                "❌ Məhsul yoxlanarkən "
                "xəta baş verdi.\n\n"
                "Bir qədər sonra linki yenidən göndər."
            )

            return

        await send_long_message(
            query.message,
            result_message,
        )

        context.user_data.pop(
            "pending_product_url",
            None,
        )

        context.user_data.pop(
            "pending_sizes",
            None,
        )

        logger.info(
            "Mango sorğusu tamamlandı | "
            "telegram_user_id=%s | "
            "size=%s | "
            "url=%s",
            user.id,
            requested_size,
            product_url,
        )


# ============================================================
# ÜMUMİ XƏTA HANDLER-İ
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Telegram botunda yaranan ümumi xətanı loglayır.
    """

    logger.error(
        "Telegram botunda ümumi xəta "
        "baş verdi.",
        exc_info=context.error,
    )


# ============================================================
# BOTUN BAŞLADILMASI
# ============================================================

def main() -> None:
    """Bazanın hazır olduğunu yoxlayır və Telegram botunu başladır."""
    global BOT_INSTANCE_SOCKET
    check_required_files()
    token = read_telegram_token()
    BOT_INSTANCE_SOCKET = acquire_single_instance_lock()
    try:
        # Serverdə baza ilk dəfə yaradılır; mövcud məlumatlar saxlanır.
        run_python_script(STEP_FILES["setup"])
        application = (
            Application.builder()
            .token(token)
            # Addımlar ortaq CSV fayllarından istifadə edir.
            .concurrent_updates(False)
            .build()
        )
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("cancel", cancel_command))
        application.add_handler(
            CallbackQueryHandler(handle_size_callback, pattern=r"^size\|")
        )
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
        )
        application.add_error_handler(error_handler)
        logger.info("Mango botu Telegram-a qoşulur.")
        application.run_polling(drop_pending_updates=False)
    except InvalidToken as error:
        raise RuntimeError(
            "Telegram tokeni qəbul edilmədi. "
            "Cloud Variables və ya lokal .env daxilindəki tokeni yoxla."
        ) from error
    finally:
        if BOT_INSTANCE_SOCKET is not None:
            BOT_INSTANCE_SOCKET.close()
            BOT_INSTANCE_SOCKET = None


if __name__ == "__main__":
    main()
