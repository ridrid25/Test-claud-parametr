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
    "marketplace": ("marketplace", "маркетплейс", "площадка", "мп"),
    "period_date": (
        "period_date", "дата", "дата продажи", "дата операции", "sale_dt",
        "operation_date", "дата начисления", "период", "дата отчёта",
        "дата отчета",
    ),
    "sku": (
        "sku", "артикул", "артикул поставщика", "артикул продавца", "sa_name",
        "код товара", "артикул wb", "ozon sku id", "sku мп",
    ),
    "product_name": (
        "product_name", "товар", "название", "название товара", "наименование",
        "предмет", "subject_name", "наименование товара",
    ),
    "category": (
        "category", "категория", "категория/предмет", "группа товаров",
    ),
    "brand": ("brand", "бренд", "торговая марка"),
    "doc_type": (
        "doc_type", "тип документа", "обоснование для оплаты", "тип операции",
        "doc_type_name", "операция",
    ),
    "quantity": ("quantity", "количество", "кол-во", "шт", "продано",),
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
        "последняя миля",
    ),
    "storage": (
        "storage", "хранение", "storage_fee", "стоимость хранения",
        "хранение/размещение",
    ),
    "promotion": ("promotion", "продвижение", "реклама", "supplier_promo",),
    "penalty": ("penalty", "штраф", "штрафы", "общая сумма штрафов",),
    "other_deduction": (
        "other_deduction", "прочие удержания", "удержания", "deduction",
        "прочие услуги", "эквайринг",
    ),
    "payout": (
        "payout", "к выплате", "к перечислению", "итого к оплате",
        "ppvz_for_pay", "к перечислению продавцу за реализованный товар",
        "сумма выплат", "amount",
    ),
}

# Fields where several source columns may legitimately feed one unified
# bucket (e.g. "Логистика" + "Последняя миля" → logistics) — their values
# are summed. Everything else keeps first-match-wins.
SUMMABLE_FIELDS = {
    "realization", "returns", "commission", "logistics", "storage",
    "promotion", "penalty", "other_deduction", "payout", "quantity",
}

MARKETPLACE_VALUES = {
    "ozon": "ozon", "озон": "ozon",
    "wb": "wb", "вб": "wb", "wildberries": "wb", "вайлдберриз": "wb",
}

# Units and currency tails that cabinet exports append to header names
# ("Реализация, ₽", "Продано, шт", "Ставка комиссии, %").
_HEADER_UNIT_RE = re.compile(r"[,\s]+(₽|руб\.?|шт\.?|%)\s*$", re.IGNORECASE)

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
    """Return {column_index: unified_field} for recognized headers.

    Summable fields may claim several columns (their values are added up);
    text-like fields keep first-match-wins so e.g. 'Период' beats a later
    'Дата отчёта' for period_date.
    """
    mapping = {}
    claimed = set()
    for index, header in enumerate(headers):
        key = (header or "").strip().lower().strip('"')
        key = _HEADER_UNIT_RE.sub("", key)
        for field, aliases in COLUMN_ALIASES.items():
            if key in aliases and (field in SUMMABLE_FIELDS or field not in claimed):
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
    # A bare month period ("2023-11") means "this month" — pin to day 1 so
    # monthly grouping and date-range filters keep working.
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", text):
        return f"{text}-01"
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
        "category": "",
        "brand": "",
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
    data["category"] = str(field_values.get("category", "")).strip()
    data["brand"] = str(field_values.get("brand", "")).strip()
    if not data["sku"] and not data["product_name"]:
        errors.append("Не указан ни артикул, ни название товара — строку не к чему привязать.")

    # A per-row marketplace column (files that mix WB and Ozon) overrides
    # the marketplace chosen in the upload form.
    raw_marketplace = field_values.get("marketplace", "")
    raw_marketplace = str(raw_marketplace[0] if isinstance(raw_marketplace, list) else raw_marketplace).strip()
    if raw_marketplace:
        known = MARKETPLACE_VALUES.get(raw_marketplace.lower())
        if known:
            data["marketplace"] = known
        else:
            errors.append(
                f"Неизвестный маркетплейс в строке: {raw_marketplace!r} (ожидается Wildberries или Ozon)."
            )

    numeric_fields = (
        "quantity", "realization", "returns", "commission", "logistics",
        "storage", "promotion", "penalty", "other_deduction", "payout",
    )
    for field in numeric_fields:
        raw_value = field_values.get(field, "")
        # Summable fields may arrive as a list when several source columns
        # feed one bucket (e.g. Логистика + Последняя миля).
        raw_values = raw_value if isinstance(raw_value, list) else [raw_value]
        raw_values = [v for v in raw_values if v not in ("", None)]
        if not raw_values:
            continue
        total = 0.0
        failed = False
        for item in raw_values:
            try:
                total += parse_number(item)
            except ValueError:
                errors.append(f"Не удалось разобрать число в колонке '{field}': {item!r}")
                failed = True
                break
        if failed:
            continue
        if len(raw_values) > 1:
            fixes.append(f"{field}: {' + '.join(str(v).strip() for v in raw_values)} → {total:g}")
        else:
            cleaned_source = str(raw_values[0]).strip()
            if cleaned_source and cleaned_source != (f"{total:g}"):
                if _NUM_CLEAN_RE.search(cleaned_source) or "," in cleaned_source:
                    fixes.append(f"{field}: '{raw_values[0]}' → {total:g}")
        data[field] = int(total) if field == "quantity" else total

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

    if "marketplace" in mapping.values():
        file_fixes.append("маркетплейс каждой строки взят из колонки файла")

    rows = []
    for row_index, raw_row in enumerate(reader):
        if not any(cell.strip() for cell in raw_row):
            continue  # skip fully blank lines silently
        field_values: dict = {}
        for idx, field in mapping.items():
            value = raw_row[idx] if idx < len(raw_row) else ""
            if field in field_values:
                existing = field_values[field]
                field_values[field] = (existing if isinstance(existing, list) else [existing]) + [value]
            else:
                field_values[field] = value
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


# Header names for a seller's own себестоимость (unit cost) file, most
# specific first so "Полная себестоимость за шт" wins over a bare
# "Себестоимость" when both are present.
COST_COLUMN_ALIASES = (
    "полная себестоимость за шт", "полная себестоимость",
    "себестоимость закупки за шт", "себестоимость за шт", "себестоимость",
    "unit_cost", "cost", "закупочная цена",
)
COST_SKU_ALIASES = ("sku", "артикул", "артикул поставщика", "артикул продавца", "код товара")


def parse_cost_upload(raw: bytes) -> dict:
    """Parse a seller's cost (себестоимость) file into {sku: unit_cost}.

    Returns {"costs": {...}, "skipped": int, "cost_column": str,
    "file_fixes": [...]} or raises ValueError with a user-facing message.
    """
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

    # Match against both the raw header and its unit-stripped form: "Себестоимость, ₽"
    # only matches after stripping, while "Полная себестоимость за шт" must NOT be
    # stripped (its " шт" is part of the name), so accept either.
    header_keys = []
    for header in headers:
        raw_key = (header or "").strip().lower().strip('"')
        header_keys.append({raw_key, _HEADER_UNIT_RE.sub("", raw_key)})

    def matches(aliases):
        # aliases are ordered most-specific-first, so honour that priority.
        for alias in aliases:
            for i, keys in enumerate(header_keys):
                if alias in keys:
                    return i
        return -1

    sku_idx = matches(COST_SKU_ALIASES)
    if sku_idx == -1:
        raise ValueError(
            "Не найдена колонка артикула (SKU). Ожидается заголовок «SKU» или «Артикул». "
            f"Найденные заголовки: {', '.join(h.strip() for h in headers if h.strip())[:300]}"
        )
    cost_idx = matches(COST_COLUMN_ALIASES)
    if cost_idx == -1:
        raise ValueError(
            "Не найдена колонка себестоимости. Ожидается «Полная себестоимость за шт», "
            "«Себестоимость закупки за шт» или «Себестоимость»."
        )

    costs: dict[str, float] = {}
    skipped = 0
    for raw_row in reader:
        if not any(cell.strip() for cell in raw_row):
            continue
        sku = (raw_row[sku_idx].strip() if sku_idx < len(raw_row) else "")
        if not sku:
            skipped += 1
            continue
        try:
            cost = parse_number(raw_row[cost_idx] if cost_idx < len(raw_row) else "")
        except ValueError:
            skipped += 1
            continue
        if cost > 0:
            costs[sku] = cost
        else:
            skipped += 1

    if not costs:
        raise ValueError("Ни одной строки с валидной себестоимостью не найдено.")
    return {
        "costs": costs,
        "skipped": skipped,
        "cost_column": headers[cost_idx].strip(),
        "file_fixes": file_fixes,
    }
