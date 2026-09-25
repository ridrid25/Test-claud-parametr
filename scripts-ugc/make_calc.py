# Лид-магнит: калькулятор юнит-экономики карточки товара WB/Ozon.
# Стиль проекта: Times New Roman >=12, чёрный текст, бирюзовый #0A655E (итоги),
# пурпурный #A01A6E (разделы), красный — расходы/минусы, зелёный — плюсы,
# белый — только на тёмной заливке шапки. Жёлтая заливка = ячейки для ввода.
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

TEAL = "0A655E"; PURPLE = "A01A6E"; RED = "C00000"; GREEN = "1E7B1E"
YELLOW = PatternFill("solid", fgColor="FFF2A8")
DARK = PatternFill("solid", fgColor="0A655E")
LIGHT = PatternFill("solid", fgColor="F2F7F6")

def f(size=12, bold=False, color="000000"):
    return Font(name="Times New Roman", size=size, bold=bold, color=color)

wb = Workbook()
ws = wb.active
ws.title = "Юнит-экономика"
ws.sheet_view.showGridLines = False
ws.column_dimensions["A"].width = 3
ws.column_dimensions["B"].width = 52
ws.column_dimensions["C"].width = 16
ws.column_dimensions["D"].width = 44

RUB = '#,##0.00" ₽";[Red]-#,##0.00" ₽";"–"'
PCT = '0.0%;[Red]-0.0%;"–"'

def cell(addr, value, font=None, fill=None, fmt=None, align=None, wrap=False):
    c = ws[addr]
    c.value = value
    c.font = font or f()
    if fill: c.fill = fill
    if fmt: c.number_format = fmt
    c.alignment = Alignment(horizontal=align or ("left" if isinstance(value, str) else "right"),
                            vertical="center", wrap_text=wrap)
    return c

# Шапка
ws.merge_cells("B2:D2")
cell("B2", "КАЛЬКУЛЯТОР ЮНИТ-ЭКОНОМИКИ КАРТОЧКИ ТОВАРА (WB / Ozon)",
     f(16, True, "FFFFFF"), DARK, align="center")
ws.row_dimensions[2].height = 30
ws.merge_cells("B3:D3")
cell("B3", "Заполните жёлтые ячейки своими цифрами — всё остальное посчитается само. "
           "Значения в примере — условные, для образца формата.",
     f(12), align="left", wrap=True)
ws.row_dimensions[3].height = 30

r = 5
# Раздел 1. Цена и комиссия
cell(f"B{r}", "1. ЦЕНА И КОМИССИЯ МАРКЕТПЛЕЙСА", f(13, True, PURPLE)); r += 1
cell(f"B{r}", "Цена продажи для покупателя (после скидок)"); cell(f"C{r}", 1490, fill=YELLOW, fmt=RUB)
cell(f"D{r}", "цена, которую платит покупатель", f(12)); price = f"C{r}"; r += 1
cell(f"B{r}", "Комиссия маркетплейса, % от цены"); cell(f"C{r}", 0.23, fill=YELLOW, fmt=PCT)
cell(f"D{r}", "ставка вашей категории (WB: раздел «Комиссия»)", f(12)); comm = f"C{r}"; r += 1
cell(f"B{r}", "Комиссия маркетплейса, ₽"); cell(f"C{r}", f"={price}*{comm}", fmt=RUB)
commr = f"C{r}"; r += 2

# Раздел 2. Расходы на единицу
cell(f"B{r}", "2. РАСХОДЫ НА ОДНУ ПРОДАННУЮ ЕДИНИЦУ", f(13, True, PURPLE)); r += 1
cell(f"B{r}", "Себестоимость закупки (с доставкой до вас)"); cell(f"C{r}", 420, fill=YELLOW, fmt=RUB)
cost = f"C{r}"; r += 1
cell(f"B{r}", "Упаковка и маркировка"); cell(f"C{r}", 25, fill=YELLOW, fmt=RUB)
pack = f"C{r}"; r += 1
cell(f"B{r}", "Доставка до склада маркетплейса, на единицу"); cell(f"C{r}", 15, fill=YELLOW, fmt=RUB)
ship = f"C{r}"; r += 1
cell(f"B{r}", "Логистика МП до покупателя (прямая), за шт."); cell(f"C{r}", 72, fill=YELLOW, fmt=RUB)
log1 = f"C{r}"; r += 1
cell(f"B{r}", "Обратная логистика (возврат), за шт."); cell(f"C{r}", 50, fill=YELLOW, fmt=RUB)
log2 = f"C{r}"; r += 1
cell(f"B{r}", "Процент выкупа"); cell(f"C{r}", 0.55, fill=YELLOW, fmt=PCT)
cell(f"D{r}", "одежда ~30–60%, товары для дома ~90%+", f(12)); buyout = f"C{r}"; r += 1
cell(f"B{r}", "Логистика на 1 выкуп (с учётом невыкупов)")
cell(f"C{r}", f"=IF({buyout}=0,0,({log1}+({log1}+{log2})*(1-{buyout})/{buyout}))", fmt=RUB)
cell(f"D{r}", "прямая + катания невыкупленных на один выкуп", f(12)); logeff = f"C{r}"; r += 1
cell(f"B{r}", "Хранение на складе МП, на единицу"); cell(f"C{r}", 12, fill=YELLOW, fmt=RUB)
stor = f"C{r}"; r += 1
cell(f"B{r}", "Реклама, % от цены (ДРР)"); cell(f"C{r}", 0.10, fill=YELLOW, fmt=PCT)
drr = f"C{r}"; r += 1
cell(f"B{r}", "Реклама, ₽ на единицу"); cell(f"C{r}", f"={price}*{drr}", fmt=RUB)
adv = f"C{r}"; r += 1
cell(f"B{r}", "Прочие расходы на единицу (брак, фотосъёмка и т.п.)"); cell(f"C{r}", 20, fill=YELLOW, fmt=RUB)
other = f"C{r}"; r += 2

# Раздел 3. Налог
cell(f"B{r}", "3. НАЛОГ", f(13, True, PURPLE)); r += 1
cell(f"B{r}", "Ставка налога, % от выручки (УСН «доходы»)"); cell(f"C{r}", 0.06, fill=YELLOW, fmt=PCT)
cell(f"D{r}", "если у вас УСН «доходы-расходы» или ОСНО — ставьте свою эффективную ставку", f(12), wrap=True)
taxr = f"C{r}"; r += 1
cell(f"B{r}", "Налог, ₽ с единицы"); cell(f"C{r}", f"={price}*{taxr}", fmt=RUB)
tax = f"C{r}"; r += 2

# Раздел 4. Итог
cell(f"B{r}", "4. ИТОГ ПО ЕДИНИЦЕ", f(13, True, PURPLE)); r += 1
cell(f"B{r}", "Все затраты на 1 проданную единицу", f(12, True))
cell(f"C{r}", f"={commr}+{cost}+{pack}+{ship}+{logeff}+{stor}+{adv}+{other}+{tax}",
     f(12, True, RED), fmt=RUB); total = f"C{r}"; r += 1
cell(f"B{r}", "ПРИБЫЛЬ С ЕДИНИЦЫ", f(14, True, TEAL), LIGHT)
cell(f"C{r}", f"={price}-{total}", f(14, True, TEAL), LIGHT, fmt=RUB)
cell(f"D{r}", "если минус — карточка возит деньги из вашего кармана", f(12), LIGHT, wrap=True)
profit = f"C{r}"; ws.row_dimensions[r].height = 24; r += 1
cell(f"B{r}", "Маржинальность (прибыль / цена)", f(12, True))
cell(f"C{r}", f"=IF({price}=0,0,{profit}/{price})", f(12, True, TEAL), fmt=PCT); r += 1
cell(f"B{r}", "Наценка на себестоимость", f(12))
cell(f"C{r}", f"=IF({cost}=0,0,({price}-{cost})/{cost})", fmt=PCT); r += 2

# Раздел 5. Месяц
cell(f"B{r}", "5. ПРИКИНЕМ МЕСЯЦ", f(13, True, PURPLE)); r += 1
cell(f"B{r}", "Продаж (выкупов) в месяц, шт."); cell(f"C{r}", 300, fill=YELLOW, fmt='#,##0')
qty = f"C{r}"; r += 1
cell(f"B{r}", "Прибыль за месяц по этой карточке", f(14, True, TEAL), LIGHT)
cell(f"C{r}", f"={profit}*{qty}", f(14, True, TEAL), LIGHT, fmt=RUB)
ws.row_dimensions[r].height = 24; r += 2

ws.merge_cells(f"B{r}:D{r}")
cell(f"B{r}", "Хотите видеть эти цифры по всем карточкам сразу, из реального отчёта WB — "
              "загрузите отчёт на mp.ridfinance.ru и посмотрите сами. Вопросы: @RidFinancebot_bot",
     f(12, True), align="left", wrap=True)
ws.row_dimensions[r].height = 30

thin = Side(style="thin", color="BFBFBF")
for row in ws.iter_rows(min_row=5, max_row=r, min_col=3, max_col=3):
    for c in row:
        if c.value is not None:
            c.border = Border(left=thin, right=thin, top=thin, bottom=thin)

wb.save("Калькулятор_юнит-экономики_WB_Ozon.xlsx")
print("saved")

# Печать: вписать в одну страницу по ширине
wb2 = __import__("openpyxl").load_workbook("Калькулятор_юнит-экономики_WB_Ozon.xlsx")
ws2 = wb2.active
ws2.page_setup.fitToWidth = 1
ws2.page_setup.fitToHeight = 1
ws2.sheet_properties.pageSetUpPr.fitToPage = True
ws2.page_setup.orientation = "portrait"
wb2.save("Калькулятор_юнит-экономики_WB_Ozon.xlsx")
print("page setup done")
