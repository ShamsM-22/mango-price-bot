import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# .env faylını oxuyur
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)


async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    İstifadəçi /start yazdıqda işləyir.
    """

    message = update.effective_message
    user = update.effective_user

    if message is None:
        return

    first_name = (
        user.first_name
        if user and user.first_name
        else "istifadəçi"
    )

    await message.reply_text(
        f"Salam, {first_name}! 👋\n\n"
        "Mən Mango məhsullarının qiymətini "
        "Azərbaycan, İspaniya, Türkiyə və ABŞ "
        "üzrə müqayisə edəcəyəm.\n\n"
        "Mənə Mango məhsul linki göndər."
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    İstifadəçi /help yazdıqda işləyir.
    """

    message = update.effective_message

    if message is None:
        return

    await message.reply_text(
        "Mango məhsul linkini göndər.\n\n"
        "Link bu formada olmalıdır:\n"
        "https://shop.mango.com/..."
    )


def is_mango_product_url(text: str) -> bool:
    """
    Mesajın Mango məhsul linki olduğunu yoxlayır.
    """

    clean_text = text.strip().lower()

    return (
        clean_text.startswith(
            "https://shop.mango.com/"
        )
        and "/p/" in clean_text
    )


async def handle_text_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    İstifadəçinin göndərdiyi adi mesajı qəbul edir.
    """

    message = update.effective_message
    user = update.effective_user

    if message is None or message.text is None:
        return

    text = message.text.strip()

    if not is_mango_product_url(text):
        await message.reply_text(
            "❌ Bu, düzgün Mango məhsul linki deyil.\n\n"
            "Link belə başlamalıdır:\n"
            "https://shop.mango.com/"
        )
        return

    telegram_user_id = (
        user.id
        if user
        else "tapılmadı"
    )

    telegram_username = (
        f"@{user.username}"
        if user and user.username
        else "yoxdur"
    )

    await message.reply_text(
        "✅ Mango məhsul linki qəbul edildi.\n\n"
        f"Telegram ID: {telegram_user_id}\n"
        f"Username: {telegram_username}\n\n"
        "Botun ilkin testi uğurludur."
    )

    logger.info(
        "Mango linki qəbul edildi | "
        "user_id=%s | username=%s | url=%s",
        telegram_user_id,
        telegram_username,
        text,
    )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Botda baş verən xətanı terminalda göstərir.
    """

    logger.error(
        "Telegram botunda xəta baş verdi.",
        exc_info=context.error,
    )


def main() -> None:
    """
    Telegram botunu başladır.
    """

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN tapılmadı.\n"
            ".env faylını və tokeni yoxla."
        )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_text_message,
        )
    )

    application.add_error_handler(
        error_handler
    )

    print("=" * 70)
    print("MANGO TELEGRAM BOT TESTİ")
    print("=" * 70)
    print("Bot başladıldı.")
    print("Telegram-da @MangoAzBot botunu aç.")
    print("/start yaz.")
    print("Botu dayandırmaq üçün Ctrl + C bas.")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()