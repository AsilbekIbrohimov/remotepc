# Jamshid Aka Fin chatidagi 5 nakladnoyni Excel database qiladi (2 varaq + rasmlar)
import os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage

BASE = 'C:/Users/Asilbek/OneDrive/Documents/remote'
IMG = BASE + '/media/finchat'
OUT = BASE + '/media/Nakladnoylar_DB.xlsx'

waybills = [
    {"no": 7, "date": "2026-09-08", "auto": "01 880 LYA", "course": 12650, "total": 646, "img": "01.jpg", "items": [
        ("консол подставка", "шт", None, "гп"),
        ("A 0819 Профиль Алюмин 1500мм", "шт", 18, "гп"),
        ("A 0820 Профиль Алюмин 1500мм", "шт", 8, "Резка/покраска"),
        ("A 0821 Профиль Алюмин 1500мм", "шт", 8, "Резка/покраска"),
        ("A 0822 Профиль Алюмин 1500мм", "шт", 8, "Резка/покраска"),
        ("A 0823 Профиль Алюмин 1500мм", "шт", 6, "Резка/покраска"),
        ("Баковой крышка консол", "шт", 20, "Резка/покраска"),
        ("Баковой крышка консол", "шт", 10, "Резка/покраска"),
        ("Кронштейн клапан для медицинской консоли", "шт", 50, "Резка"),
        ("Стабилизатор ношка", "шт", 510, "Резка"),
    ]},
    {"no": 9, "date": "2026-09-10", "auto": "01 892 UKA", "course": 12650, "total": 206, "img": "02.jpg", "items": [
        ("Боковая крашенная алюминевая крышка SWP (наружний)", "шт", 156, "гп"),
        ("Окрашенный Профиль SW 2508 Бел 780мм", "шт", 50, "Резка"),
    ]},
    {"no": 13, "date": "2026-09-14", "auto": "01 805 MKA", "course": 12650, "total": 446, "img": "03.jpg", "items": [
        ("Боковая крашенная алюминиевая крышка SWP (наружний)", "шт", 324, "гп"),
        ("Окрашенный Профиль SWP 2508 Бел 1200мм", "шт", 50, "Резка"),
        ("Окрашенный Профиль SWP 2508 Бел 780мм", "шт", 72, "Резка"),
    ]},
    {"no": 16, "date": "2026-09-17", "auto": "01 763 JJA", "course": 12650, "total": 6, "img": "04.jpg", "items": [
        ("стабилизатор корпус 15кв корпус", "шт", 1, "ГП"),
        ("стабилизатор корпус 20кв корпус", "шт", 1, "ГП"),
        ("стабилизатор корпус 30кв корпус", "шт", 1, "ГП"),
        ("стабилизатор корпус 15кв", "шт", 1, "взврат (Хитой гп)"),
        ("стабилизатор корпус 20кв", "шт", 1, "взврат (Хитой гп)"),
        ("стабилизатор корпус 30кв", "шт", 1, "взврат (Хитой гп)"),
    ]},
    {"no": 18, "date": "2026-09-21", "auto": "01 521 ENA", "course": 12650, "total": 74, "img": "05.jpg", "items": [
        ("Подвесной СС-1 4000мм белый корпус", "шт", 9, "Резка/покраска"),
        ("Подвесной СС-1 3000мм белый корпус", "шт", 4, "Резка/покраска"),
        ("Подвесной СС-1 2000мм белый корпус", "шт", 1, "Резка/покраска"),
        ("SWP вагоний корпус (внутрений) 780 мм", "шт", 20, "Резка"),
        ("SWP баковой крышка внутрений окрашенний", "шт", 40, "ГП"),
    ]},
]

HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
HEAD_FONT = Font(bold=True, color="FFFFFF", size=11)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
thin = Side(style="thin", color="BBBBBB")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)


def style_header(ws, row, ncol):
    for c in range(1, ncol + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = CENTER
        cell.border = BORDER


wb = Workbook()

# --- Varaq 1: Nakladnoylar (umumiy + rasm) ---
ws = wb.active
ws.title = "Nakladnoylar"
heads = ["№ Накладной", "Сана", "Заказчик", "Автомобиль", "Курс", "Товар турлари", "Жами (дона)", "Расм"]
ws.append(heads)
style_header(ws, 1, len(heads))
widths = [14, 12, 12, 14, 10, 13, 12, 22]
for i, w in enumerate(widths, 1):
    ws.column_dimensions[chr(64 + i)].width = w

# thumbnaillar
os.makedirs(IMG + '/thumbs', exist_ok=True)
r = 2
for wbll in waybills:
    ws.cell(r, 1, wbll["no"]).alignment = CENTER
    ws.cell(r, 2, wbll["date"]).alignment = CENTER
    ws.cell(r, 3, "Пром").alignment = CENTER
    ws.cell(r, 4, wbll["auto"]).alignment = CENTER
    ws.cell(r, 5, wbll["course"]).alignment = CENTER
    ws.cell(r, 6, len(wbll["items"])).alignment = CENTER
    ws.cell(r, 7, wbll["total"]).alignment = CENTER
    for c in range(1, 9):
        ws.cell(r, c).border = BORDER
    # rasm thumbnail
    src = os.path.join(IMG, wbll["img"])
    th = os.path.join(IMG + '/thumbs', 't_' + wbll["img"])
    im = PILImage.open(src)
    im.thumbnail((150, 200))
    im.save(th)
    xi = XLImage(th)
    ws.row_dimensions[r].height = max(90, im.height * 0.75)
    ws.add_image(xi, f"H{r}")
    r += 1

# --- Varaq 2: Tovarlar (database) ---
ws2 = wb.create_sheet("Tovarlar")
heads2 = ["№ Накладной", "Сана", "№", "Наименование товара", "Ед.изм.", "Количество", "Примечание"]
ws2.append(heads2)
style_header(ws2, 1, len(heads2))
w2 = [14, 12, 6, 46, 9, 13, 20]
for i, w in enumerate(w2, 1):
    ws2.column_dimensions[chr(64 + i)].width = w
r = 2
for wbll in waybills:
    for idx, (name, unit, qty, note) in enumerate(wbll["items"], 1):
        ws2.cell(r, 1, wbll["no"]).alignment = CENTER
        ws2.cell(r, 2, wbll["date"]).alignment = CENTER
        ws2.cell(r, 3, idx).alignment = CENTER
        ws2.cell(r, 4, name).alignment = LEFT
        ws2.cell(r, 5, unit).alignment = CENTER
        ws2.cell(r, 6, qty if qty is not None else "").alignment = CENTER
        ws2.cell(r, 7, note).alignment = LEFT
        for c in range(1, 8):
            ws2.cell(r, c).border = BORDER
        r += 1
ws2.freeze_panes = "A2"
ws.freeze_panes = "A2"

wb.save(OUT)
print("TAYYOR:", OUT)
print("Nakladnoylar:", len(waybills), "| Jami tovar qatorlari:", sum(len(w["items"]) for w in waybills))
