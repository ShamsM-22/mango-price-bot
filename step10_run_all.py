import subprocess
import sys
from pathlib import Path


PROJECT_FOLDER = Path(__file__).resolve().parent

STEPS = {
    "compare": PROJECT_FOLDER / "step04_compare_countries.py",
    "convert": PROJECT_FOLDER / "step05_convert_to_azn.py",
    "shipping": PROJECT_FOLDER / "step06_add_shipping_cost.py",
    "database": PROJECT_FOLDER / "step08_save_to_database.py",
    "view": PROJECT_FOLDER / "step09_view_database.py",
}


def check_files() -> None:
    """
    Lazım olan Python fayllarının mövcudluğunu yoxlayır.
    """

    missing_files = [
        str(file_path.name)
        for file_path in STEPS.values()
        if not file_path.exists()
    ]

    if missing_files:
        raise FileNotFoundError(
            "Aşağıdakı fayllar tapılmadı:\n"
            + "\n".join(missing_files)
        )


def run_script(
    script_path: Path,
    input_text: str | None = None,
) -> None:
    """
    Python faylını cari virtual mühitdə işə salır.
    """

    print("\n" + "=" * 100)
    print(f"İŞƏ SALINIR: {script_path.name}")
    print("=" * 100)

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
        ],
        input=input_text,
        text=True,
        cwd=PROJECT_FOLDER,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"{script_path.name} işləyərkən xəta baş verdi."
        )


def main() -> None:
    print("=" * 100)
    print("MANGO QİYMƏT MÜQAYİSƏ PROQRAMI")
    print("=" * 100)

    check_files()

    product_url = input(
        "\nMango məhsul linkini daxil et: "
    ).strip()

    if not product_url.startswith(
        "https://shop.mango.com/"
    ):
        raise ValueError(
            "Düzgün Mango məhsul linki daxil edilməyib."
        )

    user_id = input(
        "İstifadəçi adı və ya ID "
        "(boş buraxsan local_user): "
    ).strip()

    if not user_id:
        user_id = "local_user"

    # Step 4 — ölkələr üzrə qiymətlər
    run_script(
        STEPS["compare"],
        input_text=f"{product_url}\n",
    )

    # Step 5 — qiymətlərin AZN-ə çevrilməsi
    run_script(
        STEPS["convert"]
    )

    # Step 6 — təxmini kargo və yekun qiymət
    run_script(
        STEPS["shipping"]
    )

    # Step 8 — SQL bazasına yazılması
    run_script(
        STEPS["database"],
        input_text=f"{user_id}\n",
    )

    # Step 9 — son SQL nəticəsinin göstərilməsi
    run_script(
        STEPS["view"]
    )

    print("\n" + "=" * 100)
    print("BÜTÜN ADDIMLAR UĞURLA TAMAMLANDI")
    print("=" * 100)

    print("\nNəticə faylı:")
    print("data/final_price_comparison.csv")

    print("\nSQL bazası:")
    print("database/mango_price_bot.db")


if __name__ == "__main__":
    try:
        main()

    except Exception as error:
        print("\n" + "=" * 100)
        print("PROQRAM DAYANDI")
        print("=" * 100)

        print("Xəta:", error)

        sys.exit(1)