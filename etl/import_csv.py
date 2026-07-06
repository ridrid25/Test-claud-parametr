"""Parse a user-uploaded WB/Ozon CSV export into unified-schema rows.

Manual exports are messier than API responses: cp1251 vs UTF-8 encodings,
';' vs ',' delimiters, '1 234,56 ₽'-style numbers, dd.mm.yyyy dates, and
column names that vary between cabinet export versions. Every fix applied
to a row is recorded so the UI can show what was auto-corrected; rows that
can't be fixed automatically come back as status='error' with a reason the
user can act on in the manual row editor.
"""
import csv
import io
import json
import re
from datetime import datetime

# Column aliases: unified field -> recognizable header names (lowered,
# stripped). Covers the WB/Ozon cabinet CSV exports we know plus our own
# unified export format, so a round-trip of our "Товары CSV" also imports.
COLUMN_ALIASES = {
    "period_date": (
        "period_date", "дата", "дата продажи", "дата операции", "sale_dt",
        "operation_date", "дата начисления",
    ),
    "sku": (
        "sku", "артикул", "артикул поставщика", "артикул продавца", "sa_name",
        "код товара", "артикул wb", "ozon sku id",
    ),
    "product_name": (
        "product_name", "товар", "название", "название товара", "наименование",
        "предмет", "subject_name", "наименование товара",
    ),
    "doc_type": (
        "doc_type", "тип документа", "обоснование для оплаты", "тип операции",
        "doc_type_name", "операция",
    ),
    "quantity": ("quantity", "количество", "кол-во", "шт",),
    "realization": (
        "realization", "реализация", "продажа", "сумма продажи", "retail_amount",
        "вайлдберриз реализовал товар (пр)", "цена реализации",
        "accruals_for_sale", "сумма реализации",
    ),
    "returns": ("returns", "возврат", "возвраты", "сумма возврата",),
    "commission": (
        "commission", "комиссия", "комиссия мп", "вознаграждение вайлдберриз",
        "sale_commission", "ppvz_sales_commission", "комиссия за продажу",
    ),
    "logistics": (
        "logistics", "логистика", "доставка", "услуги по доставке",
        "delivery_rub", "стоимость логистики", "логистика мп",
    ),
    "storage": ("storage", "хранение", "storage_fee", "стоимость хранения",),
    "promotion": ("promotion", "продвижение", "реклама", "supplier_promo",),
    "penalty": ("penalty", "штраф", "штрафы", "общая сумма штрафов",),
    "other_deduction": (
        "other_deduction", "прочие удержания", "удержания", "deduction",
        "прочие услуги",
    ),
    "payout": (
        "payout", "к выплате", "к перечислению", "итого к оплате",
        "ppvz_for_pay", "к перечислению продавцу за реализованный товар",
        "сумма выплат", "amount",
    ),
}

RETURN_DOC_TYPES = ("возврат", "return", "возврат товара")

# NB: no '.' in this class — a literal dot must survive as the decimal
# separator; trailing dots from 'руб.' are stripped separately below.
_NUM_CLEAN_RE = re.compile(r"[₽руб\s  ]", re.IGNORECASE)
_DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y.%m.%d")


def sniff_text(raw: bytes) -> tuple[str, str | None]:
    """Decode bytes trying UTF-8 (with BOM) first, then cp1251.
    Returns (text, fix_note or None)."""
    try:
        return raw.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1251"), "кодировка cp1251 → UTF-8"
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), "нечитаемые символы заменены"


def sniff_delimiter(text: str) -> str:
    sample = text[:4096]
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t").delimiter
    except csv.Error:
        # Fall back to whichever appears more in the header line.
        header = sample.splitlines()[0] if sample.splitlines() else ""
        return ";" if header.count(";") >= header.count(",") else ","


def map_headers(headers: list[str]) -> dict[int, str]:
    """Return {column_index: unified_field} for recognized headers."""
    mapping = {}
    claimed = set()
    for index, header in enumerate(headers):
        key = (header or "").strip().lower().strip('"')
        for field, aliases in COLUMN_ALIASES.items():
            if field not in claimed and key in aliases:
                mapping[index] = field
                claimed.add(field)
                break
    return mapping


def parse_number(value: str) -> float:
    """Tolerate '1 234,56', '1,234.56', '₽ 990', '-45,00'."""
    text = _NUM_CLEAN_RE.sub("", str(value or "").strip())
    if not text:
        return 0.0
    # If both separators present, the rightmost one is decimal.
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    return float(text)


def parse_date(value: str) -> str:
    text = str(value or "").strip()[:19]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(fmt))], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # ISO with time ("2023-10-05T12:00:00" / "2023-10-05 12:00:00")
    match = re.match(r"(\d{4}-\d{2}-\d{2})[T ]", text)
    if match:
        return match.group(1)
    raise ValueError(f"не удалось разобрать дату: {value!r}")


def normalize_row(
    client_id: str, marketplace: str, upload_id: int, row_index: int,
    field_values: dict[str, str],
) -> dict:
    """Turn one CSV row's mapped values into a staged unified row.

    Returns {"status": "ok"|"fixed"|"error", "fixes": [...], "error": str|None,
    "data": {...unified fields...}}.
    """
    fixes: list[str] = []
    data = {
        "client_id": client_id,
        "marketplace": marketplace,
        "period_date": "",
        "sku": "",
        "product_name": "",
        "quantity": 0,
        "realization": 0.0,
        "returns": 0.0,
        "commission": 0.0,
        "logistics": 0.0,
        "storage": 0.0,
        "promotion": 0.0,
        "penalty": 0.0,
        "other_deduction": 0.0,
        "payout": 0.0,
        "source_report": f"csv_upload:{upload_id}",
        "raw_ref": f"csv:{upload_id}:{row_index}",
    }

    # Parse everything best-effort and collect errors at the end, so an
    # error row still carries every parseable field — the manual row editor
    # prefills from this data, and losing the good fields over one bad one
    # would force the user to retype the whole row.
    errors: list[str] = []

    raw_date = field_values.get("period_date", "")
    try:
        data["period_date"] = parse_date(raw_date)
        if data["period_date"] != str(raw_date).strip():
            fixes.append(f"дата '{raw_date}' → {data['period_date']}")
    except ValueError:
        errors.append(
            f"Нет распознаваемой даты (значение: {raw_date!r}). Укажите дату в формате ГГГГ-ММ-ДД."
        )

    data["sku"] = str(field_values.get("sku", "")).strip()
    data["product_name"] = str(field_values.get("product_name", "")).strip()
    if not data["sku"] and not data["product_name"]:
        errors.append("Не указан ни артикул, ни название товара — строку не к чему привязать.")

    numeric_fields = (
        "quantity", "realization", "returns", "commission", "logistics",
        "storage", "promotion", "penalty", "other_deduction", "payout",
    )
    for field in numeric_fields:
        raw_value = field_values.get(field, "")
        if raw_value in ("", None):
            continue
        try:
            parsed = parse_number(raw_value)
        except ValueError:
            errors.append(f"Не удалось разобрать число в колонке '{field}': {raw_value!r}")
            continue
        cleaned_source = str(raw_value).strip()
        if cleaned_source and cleaned_source != (f"{parsed:g}"):
            if _NUM_CLEAN_RE.search(cleaned_source) or "," in cleaned_source:
                fixes.append(f"{field}: '{raw_value}' → {parsed:g}")
        data[field] = int(parsed) if field == "quantity" else parsed

    if errors:
        return {"status": "error", "fixes": fixes, "error": " ".join(errors), "data": data}

    # A row explicitly marked as return moves its amount to returns.
    doc_type = str(field_values.get("doc_type", "")).strip().lower()
    if doc_type in RETURN_DOC_TYPES and data["realization"] and not data["returns"]:
        data["returns"] = abs(data["realization"])
        data["realization"] = 0.0
        fixes.append("строка-возврат: сумма перенесена из реализации в возвраты")

    if data["returns"] < 0:
        data["returns"] = abs(data["returns"])
        fixes.append("возврат с минусом приведён к положительному значению")

    return {"status": "fixed" if fixes else "ok", "fixes": fixes, "error": None, "data": data}


def parse_csv_upload(client_id: str, marketplace: str, upload_id: int, raw: bytes) -> dict:
    """Parse the whole file. Returns {"file_fixes": [...], "columns": {...},
    "rows": [normalize_row results with raw values attached]} or raises
    ValueError with a user-facing message for file-level failures."""
    text, encoding_fix = sniff_text(raw)
    delimiter = sniff_delimiter(text)

    file_fixes = []
    if encoding_fix:
        file_fixes.append(encoding_fix)
    if delimiter != ",":
        file_fixes.append(f"разделитель '{delimiter}'")

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        headers = next(reader)
    except StopIteration:
        raise ValueError("Файл пустой — в нём нет ни одной строки.")

    mapping = map_headers(headers)
    if "period_date" not in mapping.values():
        raise ValueError(
            "Не найдена колонка с датой. Ожидаются заголовки вида 'Дата', "
            "'Дата продажи', 'Дата операции' или 'period_date'. "
            f"Найденные заголовки: {', '.join(h.strip() for h in headers if h.strip())[:300]}"
        )
    money_fields = {"realization", "returns", "payout", "commission"}
    if not money_fields.intersection(mapping.values()):
        raise ValueError(
            "Не найдено ни одной суммы (реализация / возврат / комиссия / к выплате). "
            "Проверьте, что это финансовый отчёт, а не, например, список остатков."
        )

    rows = []
    for row_index, raw_row in enumerate(reader):
        if not any(cell.strip() for cell in raw_row):
            continue  # skip fully blank lines silently
        field_values = {field: raw_row[idx] if idx < len(raw_row) else "" for idx, field in mapping.items()}
        result = normalize_row(client_id, marketplace, upload_id, row_index, field_values)
        result["row_index"] = row_index
        result["raw"] = json.dumps(
            {headers[idx].strip(): (raw_row[idx] if idx < len(raw_row) else "") for idx in mapping},
            ensure_ascii=False,
        )
        rows.append(result)

    if not rows:
        raise ValueError("В файле есть заголовки, но нет ни одной строки с данными.")

    return {
        "file_fixes": file_fixes,
        "columns": {headers[idx].strip(): field for idx, field in mapping.items()},
        "rows": rows,
    }
