import os
import logging
import re
import textwrap
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageWin
from gs1_datamatrix import GS1DataMatrixGenerator
import win32print
import win32ui
import code128


# === Настройка логирования ===
logging.basicConfig(
    filename="debug_log.txt",
    level=logging.DEBUG,
    format="%(asctime)s %(message)s",
    datefmt="[%Y-%m-%d %H:%M:%S]"
)

def log(msg):
    logging.info(msg)
    print(f"[DEBUG] {msg}")


class LabelPrinter:
    def __init__(self, printer_name='по умолчанию'):
        self.printer_name = printer_name
        self.MM_TO_PIXELS = 3.78  # ~1 мм ≈ 3.78 пикселей при 96 dpi
        self.label_size_mm = (58, 40)  # размер этикетки в мм

    # --- Внутренние методы из оригинального кода ---
    def create_ozon_label(self, barcode_value, product_infos, font, height=200, font_size=14,
                      left_padding=50, right_padding=50, padding=10, bottom_padding=20):
        log("Начало create_ozon_label()")

        try:
            # --- Генерация штрих-кода в памяти ---
            log("Генерация штрих-кода...")
            barcode_img = code128.image(barcode_value, height=height, thickness=2)
            log(f"Штрих-код успешно сгенерирован (размер: {barcode_img.size})")

            # --- Обрезка изображения до содержимого ---
            def trim(img):
                log("Обрезка штрих-кода...")
                img = img.convert("RGB")
                bg = Image.new("RGB", img.size, img.getpixel((0, 0)))
                diff = ImageChops.difference(img, bg)
                bbox = diff.getbbox()
                if bbox:
                    log(f"trim: bbox найден: {bbox}")
                    return img.crop(bbox)
                else:
                    log("trim: bbox не найден — изображение не обрезано")
                    return img

            trimmed_barcode = trim(barcode_img)

            # --- Загрузка шрифта ---
            log("Попытка загрузить DejaVuSans.ttf...")
            try:
                font_path = "DejaVuSans.ttf"
                if not os.path.exists(font_path):
                    log(f"❌ Файл шрифта не найден: {os.path.abspath(font_path)}")
                font = ImageFont.truetype(font_path, font_size)
                log(f"✅ Успешно загружен шрифт: {font_path}")
            except OSError as e:
                log(f"❌ OSError: {e}")
                log("Используется стандартный шрифт")
                font = ImageFont.load_default()

            log(f"Тип шрифта: {type(font)}")

            # --- Расчёт размеров текста ---
            log("Расчёт ширины текста...")
            draw_temp = ImageDraw.Draw(Image.new("RGB", (1, 1)))

            text_widths = []
            for line in product_infos:
                log(f"Обработка строки: '{line}'")
                try:
                    w = int(draw_temp.textlength(line, font=font))
                    log(f"Строка: '{line}' → ширина: {w} px (через textlength)")
                except Exception as e:
                    log(f"❌ Строка: '{line}' → ошибка textlength(): {e}")
                    avg_char_width = font_size * 0.6
                    w = int(len(line) * avg_char_width)
                    log(f"Используется приблизительный расчёт: {len(line)} символов * {avg_char_width:.2f} ≈ {w} px")
                text_widths.append(w)

            text_max_width = max(text_widths)
            text_total_height = len(product_infos) * font_size + (len(product_infos) - 1) * 5
            log(f"Максимальная ширина текста: {text_max_width}")
            log(f"Высота текста: {text_total_height}")

            # --- Определение финальных размеров этикетки с учётом всех отступов ---
            final_width = max(
                trimmed_barcode.width + left_padding + right_padding,
                text_max_width + left_padding + right_padding
            )
            final_height = (
                trimmed_barcode.height +
                padding +
                text_total_height +
                bottom_padding
            )

            final_width = int(final_width)
            final_height = int(final_height)
            log(f"Создание этикетки размером {final_width}x{final_height} с отступами: "
                f"слева={left_padding}, справа={right_padding}, сверху={padding}, снизу={bottom_padding}")

            # --- Создаём фоновое изображение ---
            etiketka = Image.new("RGB", (final_width, final_height), "white")
            draw = ImageDraw.Draw(etiketka)

            # --- Вставляем штрих-код ---
            barcode_x = left_padding
            barcode_y = padding
            etiketka.paste(trimmed_barcode, (barcode_x, barcode_y))
            log("Штрих-код вставлен на изображение")

            # --- Добавляем текст ---
            text_y = barcode_y + trimmed_barcode.height + padding
            for line in product_infos:
                draw.text((left_padding, text_y), line, fill="black", font=font)
                log(f"Добавлен текст: '{line}' (y={text_y})")
                text_y += font_size + 5

            log("✅ Этикетка создана успешно")
            return etiketka

        except Exception as e:
            log(f"❌ Непредвиденная ошибка: {e}")
            raise

    def convert_to_gs1_format(self, raw_string):
        parts = raw_string.strip().split()
        result = ""
        for i, part in enumerate(parts):
            if part.startswith("01") and len(part) >= 16:
                # GTIN: 01 + 14 символов
                gtin = part[2:16]
                result += f"(01){gtin}"

                # Остаток строки после GTIN — например, '215rzB=majxtZvc'
                rest = part[16:]
                if rest:
                    if rest.startswith("21") and len(rest) > 2:
                        serial = rest[2:]
                        result += f"(21){serial}"
                    else:
                        result += rest  # если нет AI, просто добавить как данные

            elif part.startswith("21"):
                serial = part[2:]
                result += f"(21){serial}"

            elif part.startswith("91"):
                data = part[2:]
                result += f"(91){data}"

            elif part.startswith("92"):
                data = part[2:]
                result += f"(92){data}"
        return result

    def is_correct_gs1_format(self, raw_string):
        # Убираем лишние пробелы и объединяем
        full_data = ''.join(raw_string.strip().split())
        
        # Таблица AI с фиксированной длиной данных
        ai_table = {
            '01': 14,   # GTIN
            '02': 14,   # GTIN для партии
            '10': None, # Серийный номер партии (переменная длина до следующего AI)
            '17': 6,    # Срок годности (YYMMDD)
            '21': None, # Серийный номер товара (переменная длина)
            '310': 6,   # Net weight in kg with 3 decimals (e.g. 3100012345)
            '37': None, # Quantity (переменная длина)
            '91': None, # Внутреннее использование компании
            '92': None, # Защищённые данные
            '93': None,
            '94': None,
            '95': None,
            '96': None,
            '97': None,
            '98': None,
            '99': None,
        }

        current_pos = 0
        data_length = len(full_data)

        while current_pos < data_length:
            matched = False

            for ai in ai_table:
                if full_data.startswith(ai, current_pos):
                    data_length_ai = ai_table[ai]
                    remaining_length = data_length - current_pos - len(ai)

                    if data_length_ai is not None:
                        # Если длина фиксированная
                        if remaining_length >= data_length_ai:
                            current_pos += len(ai) + data_length_ai
                            matched = True
                            break
                        else:
                            return False  # Недостаточно данных для AI
                    else:
                        # Переменная длина — читаем до следующего AI или конца строки
                        next_ai_pos = data_length
                        for possible_ai in ai_table:
                            pos = full_data.find(possible_ai, current_pos + len(ai))
                            if pos != -1:
                                next_ai_pos = min(next_ai_pos, pos)
                        current_pos += len(ai)
                        if next_ai_pos == data_length:
                            # Конец строки — всё считано
                            current_pos = data_length
                        else:
                            # До следующего AI
                            current_pos += next_ai_pos - (current_pos)
                        matched = True
                        break

            if not matched:
                return False  # Не удалось распознать AI

        return True

    def generate_gs1_datamatrix_from_raw(
        self,
        raw_string: str,
        description_text: list,
        logo_path: str = "assets/icons/chestniy_znak.png",
        output_path: str = "etiketka_chestnyi_znak.png",
        label_size: tuple = (450, 280),
        padding: int = 20,
        font_size: int = 14,
    ):
        width, height = label_size
        etiketka = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(etiketka)

        # --- Шрифт ---
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

        # --- Проверка формата ---
        if not self.is_correct_gs1_format(raw_string):
            raise ValueError("Неверный формат входной строки")

        # --- Генерация DataMatrix ---
        matrixGenerator = GS1DataMatrixGenerator()
        datamatrix = matrixGenerator.generate_from_string(raw_string)
        dm_image = datamatrix.resize((200, 200)).convert("RGB")

        # --- Вставка DataMatrix ---
        dm_x = padding
        dm_y = padding
        etiketka.paste(dm_image, (dm_x, dm_y))

        # --- Подпись под DataMatrix ---
        code_text = raw_string[:31]
        bbox = draw.textbbox((0, 0), code_text, font=font)
        text_height = bbox[3] - bbox[1]
        draw.text((dm_x, dm_y + dm_image.height + 10), code_text, fill="black", font=font)

        # --- Логотип справа сверху ---
        if os.path.exists(logo_path):
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((100, 100))
            logo_x = width - logo.width - padding
            logo_y = padding
            etiketka.paste(logo, (logo_x, logo_y), logo.split()[3])
        else:
            print(f"[!] Логотип не найден: {logo_path}")

        # --- Описание товара справа от кода ---
        desc_x = dm_x + dm_image.width + 20
        desc_y_start = dm_y + 60

        for line in description_text:
            wrapped_lines = textwrap.wrap(line, width=30)
            for wrapped_line in wrapped_lines:
                draw.text((desc_x, desc_y_start), wrapped_line, fill="black", font=font)
                desc_y_start += font_size + 4

        # --- Сохраняем результат ---
        # etiketka.save(output_path)
        print(f"✅ Этикетка сохранена как '{output_path}'")
        return etiketka

    def print_on_windows(self, image_path=None, image=None):
        """
        Отправляет изображение этикетки на печать.
        Можно передать либо путь к файлу, либо объект PIL.Image.
        """
        temp_path = None
        if image is not None:
            temp_path = "__temp_label_print__.png"
            image.save(temp_path)
            image_path = temp_path

        try:
            printer_name = self.printer_name if self.printer_name != 'по умолчанию' else win32print.GetDefaultPrinter()
            print(f"🖨️ Печать на принтере: {printer_name}")

            hprinter = win32print.OpenPrinter(printer_name)
            try:
                win32print.StartDocPrinter(hprinter, 1, ("Этикетка", None, "RAW"))
                win32print.StartPagePrinter(hprinter)

                bmp = Image.open(image_path)
                dib = ImageWin.Dib(bmp)

                hdc = win32ui.CreateDC()
                hdc.CreatePrinterDC(printer_name)
                hdc.StartDoc("Этикетка")
                hdc.StartPage()
                dib.draw(hdc.GetHandleOutput(), (0, 0, bmp.width, bmp.height))
                hdc.EndPage()
                hdc.EndDoc()
                hdc.DeleteDC()

                win32print.EndPagePrinter(hprinter)
                win32print.EndDocPrinter(hprinter)
            finally:
                win32print.ClosePrinter(hprinter)

            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

        except Exception as e:
            print("❌ Ошибка печати:", str(e))

    # --- API для работы с этикетками ---
    def print_ozon_label(self, barcode_value, product_info):
        """Создаёт и печатает этикетку Ozon"""
        label = self.create_ozon_label(barcode_value, product_info, 'DejaVuSans.ttf')
        self.print_on_windows(image=label)

    def print_gs1_label(self, raw_string, description_text):
        """Создаёт и печатает GS1 этикетку"""
        label = self.generate_gs1_datamatrix_from_raw(raw_string, description_text)
        self.print_on_windows(image=label)


if __name__ == "__main__":
    printer = LabelPrinter(printer_name="по умолчанию")  # или "по умолчанию"
    printer.print_ozon_label("432432432423", ["fdsfsdf"])
