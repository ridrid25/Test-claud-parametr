# Продукты №3 и №4: гайд «Налоги селлера 2026» и чек-лист «Разбор отчёта WB».
# Шрифт: Liberation Serif (метрический аналог Times New Roman, с кириллицей),
# размер >=12, чёрный текст, акценты #0A655E (итоги/важное) и #A01A6E (разделы).
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, HRFlowable)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

LB = "/usr/share/fonts/truetype/liberation/"
pdfmetrics.registerFont(TTFont("Serif", LB + "LiberationSerif-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Serif-Bold", LB + "LiberationSerif-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Serif-Italic", LB + "LiberationSerif-Italic.ttf"))

TEAL = HexColor("#0A655E"); PURPLE = HexColor("#A01A6E"); RED = HexColor("#C00000")
GREEN = HexColor("#1E7B1E"); LIGHT = HexColor("#F2F7F6")

def S(name, size=12, bold=False, color=black, align=TA_LEFT, before=0, after=6, leading=None):
    return ParagraphStyle(name, fontName="Serif-Bold" if bold else "Serif",
                          fontSize=size, textColor=color, alignment=align,
                          spaceBefore=before, spaceAfter=after,
                          leading=leading or size * 1.35)

st_title = S("t", 20, True, white, TA_CENTER, leading=26)
st_sub = S("sub", 12, False, black, TA_CENTER, after=10)
st_h = S("h", 14, True, PURPLE, before=12, after=6)
st_b = S("b", 12)
st_bb = S("bb", 12, True)
st_teal = S("tl", 13, True, TEAL, before=6, after=8)
st_small = S("sm", 12, False, black, after=4)
st_it = ParagraphStyle("it", parent=st_b, fontName="Serif-Italic")

def title_block(text, sub):
    t = Table([[Paragraph(text, st_title)]], colWidths=[170 * mm], rowHeights=[22 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TEAL),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return [t, Spacer(1, 6 * mm), Paragraph(sub, st_sub), Spacer(1, 4 * mm)]

def hr():
    return HRFlowable(width="100%", thickness=0.7, color=HexColor("#BFBFBF"),
                      spaceBefore=6, spaceAfter=6)

CTA = ("Считать это автоматически, по всем неделям и карточкам сразу, можно на "
       "<b>mp.ridfinance.ru</b> — загрузите отчёт и посмотрите сами. "
       "Вопросы: <b>@RidFinancebot_bot</b>")

# ============ Продукт №3: гайд по налогам ============
story = []
story += title_block("НАЛОГИ СЕЛЛЕРА — 2026:<br/>УСН, НПД и новый НДС БЕЗ СЮРПРИЗОВ",
                     "Гайд для продавцов Wildberries и Ozon · редакция сентябрь 2026")
story.append(Paragraph(
    "Гайд объясняет принципы и главные ловушки. Ставки и лимиты приведены на дату редакции — "
    "перед решением сверьте актуальные значения в Налоговом кодексе и на nalog.gov.ru: "
    "пороги меняются ежегодно.", st_it))
story.append(hr())

story.append(Paragraph("Ошибка №1, которая стоит дороже всего", st_h))
story.append(Paragraph(
    "На УСН «доходы» налог считается со <b>всей суммы реализации</b> (в отчёте WB — «Продано», Пр), "
    "а не с суммы «к перечислению», которая пришла на счёт. Комиссия и логистика маркетплейса — "
    "это ваши <b>расходы</b>, они не уменьшают базу на «доходах».", st_b))
tbl = Table([
    ["", "Как думают", "Как по закону"],
    ["База за неделю", "114 074 руб. (к перечислению)", "166 900 руб. (Продано, Пр)"],
    ["Налог 6%", "6 844 руб.", "10 014 руб."],
    ["Недоплата за год (~50 недель)", "", "≈ 158 000 руб. + пени и штраф"],
], colWidths=[52 * mm, 57 * mm, 61 * mm])
tbl.setStyle(TableStyle([
    ("FONTNAME", (0, 0), (-1, -1), "Serif"), ("FONTNAME", (0, 0), (-1, 0), "Serif-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 12), ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#BFBFBF")),
    ("TEXTCOLOR", (2, 1), (2, -1), TEAL), ("TEXTCOLOR", (1, 1), (1, 2), RED),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
]))
story.append(tbl)
story.append(Paragraph("Цифры примера — из каскада прибыли (дашборд «Прибыль селлера за 15 минут»). "
                       "Налоговая видит обороты маркетплейса напрямую.", st_it))

story.append(Paragraph("Какие режимы бывают и кому подходят", st_h))
story.append(Paragraph("<b>НПД (самозанятость).</b> Лимит 2,4 млн руб. в год. Продавать можно "
    "<b>только товары собственного производства</b> — перепродажа закупленного запрещена. "
    "Для классического селлера-перекупа НПД не подходит.", st_b))
story.append(Paragraph("<b>УСН «доходы» (6%).</b> Просто, без учёта расходов. Выгодно при высокой "
    "марже. Помните про базу = Пр (ошибка №1).", st_b))
story.append(Paragraph("<b>УСН «доходы минус расходы» (15%).</b> Выгодно, когда документально "
    "подтверждённые расходы стабильно больше ~60–65% выручки: закупка, комиссия, логистика, реклама. "
    "Требует дисциплины с документами от поставщиков.", st_b))
story.append(Paragraph("<b>АУСН.</b> Автоматизированная УСН: ставки выше (8% / 20%), зато без "
    "деклараций и взносов; лимиты по доходу и сотрудникам — проверьте актуальные на nalog.gov.ru.", st_b))
story.append(Paragraph("<b>ОСНО.</b> Общий режим с НДС — как правило, для крупных или вынужденных.", st_b))

story.append(Paragraph("Реформа-2026: НДС добрался до УСН", st_h))
story.append(Paragraph("Главное изменение для селлеров:", st_b))
P = lambda x, b=False: Paragraph(x, st_bb if b else st_b)
tbl2 = Table([
    [P("Что изменилось", True), P("Было (2025)", True), P("Стало (2026)", True)],
    [P("Основная ставка НДС"), P("20%"), P("22%")],
    [P("Порог дохода на УСН, после которого возникает НДС"), P("60 млн руб."),
     P("20 млн руб. (2027 — 15 млн, 2028 — 10 млн)")],
    [P("Спецставки НДС для УСН (без вычета входного НДС)"), P("5% / 7%"), P("5% / 7%")],
], colWidths=[62 * mm, 40 * mm, 68 * mm])
tbl2.setStyle(TableStyle([
    ("FONTNAME", (0, 0), (-1, -1), "Serif"), ("FONTNAME", (0, 0), (-1, 0), "Serif-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 12), ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
    ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#BFBFBF")),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
]))
story.append(tbl2)
story.append(Paragraph("Как это работает: превысили 20 млн руб. дохода с начала года — "
    "<b>с 1-го числа следующего месяца</b> вы плательщик НДС автоматически, уведомлений подавать "
    "не нужно: налоговая узнаёт о ваших оборотах от самих маркетплейсов. Дальше выбор: общий порядок "
    "(22% / 10% с вычетами входного НДС) или спецставка 5% / 7% без вычетов — что выгоднее, зависит "
    "от доли подтверждённого входного НДС в закупке.", st_b))
story.append(Paragraph("Вывод: порог 20 млн — это ~1,7 млн руб. продаж в месяц. Следите за ним "
    "по строке «Продано (Пр)» нарастающим итогом, а не по поступлениям на счёт.", st_teal))

story.append(Paragraph("Что сделать уже на этой неделе", st_h))
for i, step in enumerate([
    "Посчитайте прогноз дохода за год <b>по Пр</b>, а не по «к перечислению».",
    "Проверьте, тем ли режимом пользуетесь: доля подтверждённых расходов больше 60–65% — "
    "посчитайте вариант «доходы минус расходы».",
    "Если Пр идёт к 20 млн в год — заранее выберите вариант НДС (22% с вычетами или 5%/7% без) "
    "и заложите его в цены.",
    "Поставьте контрольную точку раз в месяц: каскад прибыли + налоговая база нарастающим итогом.",
], start=1):
    story.append(Paragraph(f"{i}. {step}", st_b))
story.append(hr())
story.append(Paragraph(CTA, st_bb))
story.append(Paragraph("Материал носит информационный характер и не является индивидуальной "
    "налоговой консультацией. Сверяйтесь с НК РФ и nalog.gov.ru.", st_it))

doc = SimpleDocTemplate("Гайд_Налоги_селлера_2026.pdf", pagesize=A4,
                        leftMargin=20 * mm, rightMargin=20 * mm,
                        topMargin=15 * mm, bottomMargin=15 * mm,
                        title="Налоги селлера — 2026")
doc.build(story)
print("guide saved")

# ============ Продукт №4: чек-лист ============
story = []
story += title_block("РАЗБОР ОТЧЁТА WB ПО ШАГАМ",
                     "Чек-лист на 15 минут · раз в неделю · без бухгалтера")
story.append(Paragraph("Откройте детализацию еженедельного отчёта WB и идите по порядку. "
                       "Не перепрыгивайте.", st_it))
story.append(hr())

steps = [
    ("Скачайте детализацию", "Кабинет WB → Финансовые отчёты → нужная неделя → «Детализация» (Excel)."),
    ("Зафиксируйте итог", "Выпишите «Итого к перечислению» из отчёта — это контрольная цифра, с ней всё должно сойтись."),
    ("Продано (Пр)", "Сумма продаж минус возвраты в ценах реализации. Это ваша выручка и налоговая база на УСН «доходы»."),
    ("Комиссия WB", "Пр минус «к перечислению за товар». Сравните % с прошлой неделей — вырос без причины? Ищите почему."),
    ("Логистика", "Вся логистика за неделю. Норма — до 8–10% от Пр. Выше 12% — у вас проблема с процентом выкупа."),
    ("Штрафы", "Каждый штраф — расшифровать: за что. Регулярные штрафы — это процесс, а не случайность."),
    ("Удержания", "Внимание на рекламу («ВБ.Продвижение»): ДРР выше 15% от Пр — кампании работают в минус."),
    ("Компенсации", "Компенсации ВБ (утеря, брак) в деньгах прибавляются. В штуках продаж их не считайте — это не товар."),
    ("Сведите каскад", "Пр − комиссия − логистика − штрафы − удержания + компенсации ± прочее = «к перечислению». "
                       "Должно сойтись с шагом 2 <b>до рубля</b>. Не сошлось — ищите «прочее», а не машите рукой."),
    ("Прибыль", "Из «к перечислению» вычтите себестоимость проданных штук и налог (от Пр!). "
                "Это и есть ответ на вопрос «сколько я заработал»."),
]
rows = [[Paragraph("[ ]", S("cb", 13, True)), Paragraph(f"<b>Шаг {i}. {t}</b><br/>{d}", st_small)]
        for i, (t, d) in enumerate(steps, start=1)]
t = Table(rows, colWidths=[10 * mm, 160 * mm])
t.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [white, LIGHT]),
    ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
]))
story.append(t)

story.append(Paragraph("Красные флаги недели", st_h))
for flag in [
    "Логистика больше 12% от Пр — падает процент выкупа, деньги уезжают на «катание» товара.",
    "Реклама (ДРР) больше 15% от Пр — продвижение съедает маржу.",
    "Штрафы второй раз подряд по одной причине — чините процесс.",
    "В каскаде появилось непонятное «прочее» — новая формулировка WB, разберитесь, что это.",
    "Каскад не сходится с отчётом — не «примерно сошлось», а ошибка. Найдите её.",
]:
    story.append(Paragraph(f"• {flag}", S("fl", 12, False, RED)))
story.append(hr())
story.append(Paragraph(CTA, st_bb))

doc = SimpleDocTemplate("Чек-лист_Разбор_отчёта_WB.pdf", pagesize=A4,
                        leftMargin=20 * mm, rightMargin=20 * mm,
                        topMargin=15 * mm, bottomMargin=15 * mm,
                        title="Разбор отчёта WB по шагам")
doc.build(story)
print("checklist saved")
