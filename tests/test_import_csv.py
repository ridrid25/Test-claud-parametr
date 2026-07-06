"""The CSV import engine handles the messy realities of cabinet exports:
cp1251 encoding, ';' delimiters, '1 234,56' numbers, dd.mm.yyyy dates.
Every auto-fix is recorded; unfixable rows come back as errors."""
import pytest

from etl.import_csv import parse_csv_upload, parse_date, parse_number


def _make_csv(text: str, encoding: str = "utf-8") -> bytes:
    return text.encode(encoding)


def test_parse_number_tolerates_ru_formats():
    assert parse_number("1 234,56") == 1234.56
    assert parse_number("1,234.56") == 1234.56
    assert parse_number("₽ 990") == 990
    assert parse_number("-45,00") == -45.0
    assert parse_number("") == 0.0


def test_parse_date_tolerates_common_formats():
    assert parse_date("2023-10-05") == "2023-10-05"
    assert parse_date("05.10.2023") == "2023-10-05"
    assert parse_date("2023-10-05T12:30:00") == "2023-10-05"
    with pytest.raises(ValueError):
        parse_date("не дата")


def test_clean_utf8_file_parses_with_ok_rows():
    raw = _make_csv(
        "Дата,Артикул,Товар,Реализация,Возврат,Комиссия,К выплате\n"
        "2023-10-05,SKU-1,Платье,4000,0,680,3110\n"
    )
    result = parse_csv_upload("demo", "wb", 1, raw)
    assert result["file_fixes"] == []
    row = result["rows"][0]
    assert row["status"] == "ok"
    assert row["data"]["realization"] == 4000
    assert row["data"]["payout"] == 3110


def test_cp1251_semicolon_file_is_autofixed():
    raw = _make_csv(
        "Дата;Артикул;Товар;Реализация;К выплате\n"
        "05.10.2023;SKU-1;Платье;1 234,56;1 000,00\n",
        encoding="cp1251",
    )
    result = parse_csv_upload("demo", "wb", 1, raw)
    assert any("cp1251" in fix for fix in result["file_fixes"])
    assert any("';'" in fix for fix in result["file_fixes"])
    row = result["rows"][0]
    assert row["status"] == "fixed"
    assert row["data"]["period_date"] == "2023-10-05"
    assert row["data"]["realization"] == 1234.56


def test_return_doc_type_moves_amount_to_returns():
    raw = _make_csv(
        "Дата,Артикул,Тип документа,Реализация\n"
        "2023-10-06,SKU-1,Возврат,2000\n"
    )
    row = parse_csv_upload("demo", "wb", 1, raw)["rows"][0]
    assert row["data"]["returns"] == 2000
    assert row["data"]["realization"] == 0
    assert row["status"] == "fixed"


def test_row_without_date_is_an_error_not_a_crash():
    raw = _make_csv(
        "Дата,Артикул,Реализация\n"
        "нет даты,SKU-1,100\n"
        "2023-10-05,SKU-2,200\n"
    )
    rows = parse_csv_upload("demo", "wb", 1, raw)["rows"]
    assert rows[0]["status"] == "error"
    assert "дат" in rows[0]["error"].lower()
    assert rows[1]["status"] == "ok"  # one bad row doesn't sink the batch


def test_row_without_sku_and_name_is_an_error():
    raw = _make_csv(
        "Дата,Артикул,Товар,Реализация\n"
        "2023-10-05,,,100\n"
    )
    row = parse_csv_upload("demo", "wb", 1, raw)["rows"][0]
    assert row["status"] == "error"
    assert "артикул" in row["error"].lower()


def test_file_without_date_column_raises_user_message():
    raw = _make_csv("Артикул,Реализация\nSKU-1,100\n")
    with pytest.raises(ValueError, match="колонка с датой"):
        parse_csv_upload("demo", "wb", 1, raw)


def test_file_without_money_columns_raises_user_message():
    raw = _make_csv("Дата,Артикул\n2023-10-05,SKU-1\n")
    with pytest.raises(ValueError, match="ни одной суммы"):
        parse_csv_upload("demo", "wb", 1, raw)


def test_empty_file_raises_user_message():
    with pytest.raises(ValueError, match="пустой"):
        parse_csv_upload("demo", "wb", 1, b"")


def test_blank_lines_are_skipped_silently():
    raw = _make_csv(
        "Дата,Артикул,Реализация\n"
        "2023-10-05,SKU-1,100\n"
        "\n"
        ",,\n"
        "2023-10-06,SKU-2,200\n"
    )
    rows = parse_csv_upload("demo", "wb", 1, raw)["rows"]
    assert len(rows) == 2


def test_normalized_product_report_format():
    """The 'сводный по товарам' export format: units in headers ('..., ₽'),
    a month period instead of a day date, a marketplace column mixing WB and
    Ozon in one file, and several deduction columns feeding one bucket."""
    raw = _make_csv(
        "Маркетплейс;Период;SKU МП;Название товара;Продано, шт;Реализация, ₽;"
        "Возвраты, ₽;Комиссия МП, ₽;Логистика, ₽;Последняя миля, ₽;Эквайринг, ₽;"
        "Хранение/размещение, ₽;Продвижение, ₽;Прочие удержания, ₽;К выплате, ₽\n"
        "Ozon;2023-11;OZ-1;Коврик;5;9151.60;0.00;1153.79;705.23;268.10;119.67;24.65;300.23;483.29;6096.64\n"
        "Wildberries;2023-10;WB-1;Платье;2;4000.00;0.00;680.00;150.00;0.00;40.00;20.00;0.00;0.00;3110.00\n"
    )
    result = parse_csv_upload("demo", "wb", 1, raw)
    assert any("маркетплейс" in fix for fix in result["file_fixes"])

    ozon_row, wb_row = result["rows"][0]["data"], result["rows"][1]["data"]
    assert ozon_row["marketplace"] == "ozon"  # from the file, not the form
    assert wb_row["marketplace"] == "wb"
    assert ozon_row["period_date"] == "2023-11-01"  # month period pinned to day 1
    assert ozon_row["quantity"] == 5
    assert ozon_row["realization"] == 9151.60
    # Логистика + Последняя миля summed into logistics
    assert ozon_row["logistics"] == pytest.approx(705.23 + 268.10)
    # Эквайринг + Прочие удержания summed into other_deduction
    assert ozon_row["other_deduction"] == pytest.approx(119.67 + 483.29)
    assert ozon_row["storage"] == 24.65
    assert ozon_row["payout"] == 6096.64


def test_unknown_marketplace_value_is_an_error():
    raw = _make_csv(
        "Маркетплейс,Дата,Артикул,Реализация\n"
        "Яндекс Маркет,2023-10-05,SKU-1,100\n"
    )
    row = parse_csv_upload("demo", "wb", 1, raw)["rows"][0]
    assert row["status"] == "error"
    assert "маркетплейс" in row["error"].lower()
