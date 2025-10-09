import os
import logging
import re
import textwrap
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageWin
from gs1_datamatrix import GS1DataMatrixGenerator
import code128
from datetime import datetime # Нужен для сохранения тестовых файлов в Linux

# НОВЫЕ ИМПОРТЫ ДЛЯ ZPL ПЕЧАТИ
import socket
import base64
from typing import Optional, Dict

try:
    import fitz # PyMuPDF
except ImportError:
    msg="❌ WARNING: PyMuPDF (fitz) не установлен. Печать Ozon (PDF) будет невозможна. Установите командой 'pip install PyMuPDF'"
    logging.info(msg)
    print(msg)
    fitz = None

# УСЛОВНЫЙ ИМПОРТ ДЛЯ WINDOWS-СПЕЦИФИЧНЫХ МОДУЛЕЙ
try:
    import win32print
    import win32ui
    from PIL import ImageWin
    IS_WINDOWS = True
except ImportError:
    # Под Linux импортируем заглушки
    try:
        import win32print
        import win32ui
        # ImageWin не нужен, но на всякий случай определяем класс-заглушку
        class ImageWin:
             class Dib:
                 def __init__(self, *args, **kwargs): pass
                 def draw(self, *args, **kwargs): print("[MOCK] Имитация отрисовки DIB.")
        IS_WINDOWS = False
    except ImportError:
         print("❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить win32print/win32ui или заглушки. Печать невозможна.")
         IS_WINDOWS = False # Убеждаемся, что флаг False

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
    def __init__(self, printer_name='по умолчанию'): #'XPriner 365B'
        self.printer_name = printer_name
        self.MM_TO_PIXELS = 3.78  # ~1 мм ≈ 3.78 пикселей при 96 dpi
        self.label_size_mm = (58, 40)  # размер этикетки в мм
        self.RAW_PRINTER_PORT = 9100  # Стандартный порт для RAW печати ZPL

        # --- Внутренние методы для печати ---
        # -----------------------------------------------------------------

    def _convert_pdf_to_image(self, pdf_bytes: bytes, dpi: int = 300) -> Optional[Image.Image]:
        """
        Конвертирует PDF (в виде байтов) в объект PIL Image.
        Требуется библиотека PyMuPDF (fitz).
        """
        if not fitz:
            log("❌ Ошибка: Библиотека PyMuPDF (fitz) не найдена. Конвертация PDF невозможна.")
            return None

        try:
            # 1. Открытие документа из байтов
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            if not doc:
                log("❌ Не удалось открыть PDF-документ из байтов.")
                return None

            # 2. Рендеринг первой страницы
            page = doc.load_page(0)

            # Установка матрицы трансформации для нужного DPI
            zoom_factor = dpi / 72.0  # 72 dpi - стандарт для PDF
            matrix = fitz.Matrix(zoom_factor, zoom_factor)

            # Получение пиксмапа (растеризация)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            doc.close()

            # 3. Конвертация Pixmap в PIL Image
            img_data = pix.tobytes("ppm")
            image = Image.open(BytesIO(img_data))

            # 4. Преобразование в монохромный режим (L: grayscale, 1: monochrome)
            # Это критически важно для термопринтеров.
            image = image.convert('L').convert('1')

            log(f"✅ PDF успешно конвертирован в ч/б изображение {image.size} @ {dpi} DPI.")
            return image

        except Exception as e:
            log(f"❌ Критическая ошибка при конвертации PDF в Image: {e}")
            return None

    def print_zpl_network(self, zpl_code: str, host: str, port: int = 9100) -> bool:
        """
        Отправляет ZPL код на локальный принтер.
        Под Windows использует win32print (RAW data).
        """

        # ЛОГИКА ДЛЯ LINUX/ТЕСТИРОВАНИЯ
        if not IS_WINDOWS:
            log(f"ZPL-печать имитирована для принтера: {self.printer_name} (Linux/Test)")
            try:
                # Используем заглушку WritePrinter
                win32print.WritePrinter(999, zpl_code.encode('utf-8'))
                log("✅ ZPL-печать успешно имитирована (Linux Mock).")
                return True
            except Exception as e:
                log(f"❌ Ошибка имитации печати ZPL (Linux Mock): {e}")
                return False

        # ОРИГИНАЛЬНАЯ ЛОГИКА ДЛЯ WINDOWS (Использование win32print с RAW)
        printer_name = self.printer_name
        hprinter = None

        try:
            log(f"Отправка ZPL-кода на локальный принтер Windows: {printer_name} (RAW)")

            # Открытие принтера
            hprinter = win32print.OpenPrinter(printer_name)

            # Информация о документе (Тип RAW для ZPL)
            DOC_INFO_1 = ("Этикетка ZPL", None, "RAW")

            # Начало документа
            job_id = win32print.StartDocPrinter(hprinter, 1, DOC_INFO_1)

            # Отправка ZPL-кода
            zpl_bytes = zpl_code.encode('utf-8')
            win32print.WritePrinter(hprinter, zpl_bytes)

            # Конец документа
            win32print.EndDocPrinter(hprinter)

            log(f"✅ ZPL-код успешно отправлен на локальный принтер {printer_name}.")
            return True

        except Exception as e:
            log(f"❌ Ошибка локальной печати ZPL (Windows RAW): {e}")
            return False

        finally:
            if hprinter:
                win32print.ClosePrinter(hprinter)

    # НОВЫЙ МЕТОД: Точка входа для печати WB/Ozon этикеток

    def print_wb_ozon_label(self, label_data_base64: str, *args, **kwargs) -> bool:
        """
        Универсальный метод печати для WB (ZPL) и Ozon (Base64-PDF).
        Определяет формат данных и вызывает соответствующий низкоуровневый метод печати.
        """
        import base64

        log(f"Начало универсальной печати на принтер: {self.printer_name}")

        # 1. Попытка декодирования Base64 и анализ содержимого
        try:
            raw_data = base64.b64decode(label_data_base64)
            # Пытаемся декодировать как строку (для ZPL)
            data_str = raw_data.decode('utf-8', errors='ignore')

        except Exception as e:
            log(f"❌ Ошибка декодирования Base64: {e}")
            return False

        # 2. Определяем формат
        if data_str.strip().startswith('^XA'):
            # --- ZPL (Wildberries) ---
            log("🔎 Формат: ZPL. Передаю в print_zpl_network.")
            return self.print_zpl_network(data_str, host=None, port=None)

        elif raw_data.startswith(b'%PDF'):
            # --- Base64-PDF (Ozon) ---
            log("🔎 Формат: Base64-PDF. Выполняю конвертацию в Image.")

            # Конвертируем PDF байты в Image
            image = self._convert_pdf_to_image(raw_data)

            if image:
                log("✅ Image успешно получен. Отправляю на печать (GDI).")
                # print_on_windows принимает image=PIL.Image
                return self.print_on_windows(image=image)
            else:
                log("❌ Конвертация Base64-PDF провалилась. Печать Ozon невозможна.")
                return False

        else:
            log("❌ Неопознанный формат данных этикетки (ни ZPL, ни PDF).")
            return False

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

        # ----------------------------------------------
        # 1. НОВЫЙ ВНУТРЕННИЙ МЕТОД: Конвертация изображения в ZPL ^GFA
        # ----------------------------------------------

    def _img_to_zpl_hex(self, img: Image.Image) -> str:
        """
        Конвертирует объект PIL.Image в ASCII Hex строку,
        подходящую для команды ZPL ^GFA.
        """
        # 1. Конвертация в монохромный формат для термопринтера
        img = img.convert("L").convert("1", dither=Image.Dither.FLOYDSTEINBERG)

        width_bytes = int(img.width / 8)
        if img.width % 8 != 0:
            width_bytes += 1

        width_in_bytes = width_bytes
        height = img.height

        # 2. Получение байтов и конвертация в ASCII Hex
        temp_buffer = BytesIO()
        img.save(temp_buffer, format='PNG', optimize=True)
        temp_buffer.seek(0)

        # Получаем данные битовой карты (raw image data)
        zpl_hex = ""
        for y in range(height):
            byte_val = 0
            for x in range(img.width):
                pixel = img.getpixel((x, y))
                byte_val = byte_val << 1
                if pixel == 0:  # Черный пиксель
                    byte_val |= 1

                if (x + 1) % 8 == 0 or (x + 1) == img.width:
                    zpl_hex += f"{byte_val:02X}"
                    byte_val = 0

        # 3. ZPL-обертка для команды ^GFA
        # ^XA - начало формата
        # ^FOx,y - поле происхождения (позиция печати)
        # ^GFA - графический формат ASCII
        #   A - data_compression_method (A=ASCII)
        #   h - total_data_bytes
        #   w - width_in_bytes
        #   l - height
        #   data - ASCII data
        # ^FS - конец поля
        # ^XZ - конец формата

        total_data_bytes = len(zpl_hex) // 2

        zpl_command = textwrap.dedent(f"""
               ^XA
               ^FO0,0^GFA,{total_data_bytes},{total_data_bytes},{width_in_bytes},{zpl_hex}^FS
               ^XZ
           """).strip()

        return zpl_command

        # ----------------------------------------------
        # 2. ЗАМЕНА WINDOWS-СПЕЦИФИЧНОГО print_on_windows
        # ----------------------------------------------

    def print_on_windows(self, image_path: Optional[str] = None, image=None):
        """
        Печатает изображение (PNG/BMP) на локальный принтер (Windows GDI).
        Используется для Ozon (после конвертации PDF -> Image).
        """

        # ЛОГИКА ДЛЯ LINUX/ТЕСТИРОВАНИЯ
        if not IS_WINDOWS:
            log(f"Имитация печати изображения на принтере: {self.printer_name} (Linux/Mock)")

            if image:
                # Сохраняем изображение в файл для проверки
                try:
                    test_dir = "test_prints"
                    if not os.path.exists(test_dir): os.makedirs(test_dir)
                    image.save(f"{test_dir}/{self.printer_name}_test_{datetime.now().strftime('%H%M%S')}.png")
                    log("✅ Изображение сохранено в файл для проверки (Linux Mock).")
                except Exception as e:
                    log(f"❌ Ошибка сохранения тестового изображения: {e}")

            # Используем заглушки для имитации процесса GDI
            try:
                hprinter = win32print.OpenPrinter(self.printer_name)
                win32print.StartDocPrinter(hprinter, 1, ("Этикетка", None, "RAW"))
                win32print.EndDocPrinter(hprinter)
            finally:
                win32print.ClosePrinter(hprinter)

            return True

        # ОРИГИНАЛЬНАЯ ЛОГИКА ДЛЯ WINDOWS (GDI/Image printing)
        printer_name = self.printer_name
        temp_path = None

        if image_path is None and image is not None:
            # Если передано изображение PIL, сохраняем его во временный файл BMP
            try:
                temp_path = os.path.join(os.getcwd(), 'temp_print_label.bmp')
                image.save(temp_path, 'BMP')
                image_path = temp_path
            except Exception as e:
                log(f"❌ Ошибка сохранения временного файла BMP: {e}")
                return False

        if image_path is None:
            log("❌ Ошибка: Не передано ни пути к файлу, ни объекта изображения.")
            return False

        try:
            hprinter = win32print.OpenPrinter(printer_name)

            try:
                # 1. Start printing (RAW setup)
                win32print.StartDocPrinter(hprinter, 1, ("Этикетка", None, "RAW"))
                win32print.StartPagePrinter(hprinter)

                # 2. Load image and print via GDI
                bmp = Image.open(image_path)
                dib = ImageWin.Dib(bmp)

                hdc = win32ui.CreateDC()
                hdc.CreatePrinterDC(printer_name)
                hdc.StartDoc("Этикетка")
                hdc.StartPage()
                # Печать растрового изображения
                dib.draw(hdc.GetHandleOutput(), (0, 0, bmp.width, bmp.height))
                hdc.EndPage()
                hdc.EndDoc()
                hdc.DeleteDC()

                # 3. End printing
                win32print.EndPagePrinter(hprinter)
                win32print.EndDocPrinter(hprinter)

            finally:
                win32print.ClosePrinter(hprinter)

            # 4. Clean up
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

            log(f"✅ Изображение успешно отправлено на печать на принтер: {printer_name} (Windows).")
            return True

        except Exception as e:
            log(f"❌ Ошибка печати (Windows GDI): {str(e)}")
            return False

    # ----------------------------------------------
    def print_on_windows_old(self, image_path=None, image=None):
        """
        Пытаемся избавиться от этого метода и привязке к Windows !!!!
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
