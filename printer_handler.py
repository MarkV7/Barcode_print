import os
import logging
import re
import textwrap
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageWin
from gs1_datamatrix import GS1DataMatrixGenerator
import code128
from datetime import datetime # Нужен для сохранения тестовых файлов в Linux
import sys
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

if sys.platform == 'linux':
    IS_WINDOWS = False
else:
    IS_WINDOWS = True
# print('sys.platform:',sys.platform)
# print('IS_WINDOWS:',IS_WINDOWS)

import win32print
import win32ui

# === Настройка логирования ===
logging.basicConfig(
    filename="debug_log.txt",
    level=logging.DEBUG,
    format="%(asctime)s %(message)s",
    datefmt="[%Y-%m-%d %H:%M:%S]"
)
# Получаем логгер для этого модуля
logger = logging.getLogger(__name__)

def log(msg):
    logger.info(msg)
    # print(f"[DEBUG] {msg}")


class LabelPrinter:
    def __init__(self, printer_name='по умолчанию'): #'XPriner 365B'
        self.printer_name = printer_name
        self.MM_TO_PIXELS = 3.78  # ~1 мм ≈ 3.78 пикселей при 96 dpi
        self.label_size_mm = (58, 40)  # размер этикетки в мм
        self.RAW_PRINTER_PORT = 9100  # Стандартный порт для RAW печати ZPL

        # --- Константы для пересчета и печати ---
        # 1 мм ≈ 2.835 pt
        self.DPI_DEFAULT = 300  # Используем 300 DPI как стандарт для высококачественной печати/ресайза
        self.MM_TO_PIX = self.DPI_DEFAULT / 25.4  # 11.811 пикселей на мм

        # Константы для финального размера этикетки Ozon (58x40 мм)
        self.FINAL_LABEL_W_MM = 58.0
        self.FINAL_LABEL_H_MM = 40.0
        self.ZOOM = 0.7
        # Расчет финального размера в пикселях при 300 DPI
        self.FINAL_LABEL_W_PX = round(self.FINAL_LABEL_W_MM * self.MM_TO_PIX * self.ZOOM) # ~685 пикселей
        self.FINAL_LABEL_H_PX = round(self.FINAL_LABEL_H_MM * self.MM_TO_PIX * self.ZOOM) # ~472 пикселя
        # --- Внутренние методы для печати ---
        # -----------------------------------------------------------------

    def _convert_pdf_to_image(self, pdf_bytes: bytes,
                              target_width_mm: Optional[float] = None,
                              target_height_mm: Optional[float] = None) -> Image.Image:
        """
        Конвертирует PDF в изображение PIL.Image, масштабируя его до нужных размеров в мм.
        """
        if fitz is None:
            raise RuntimeError("PyMuPDF (fitz) не установлен. Конвертация PDF невозможна.")
        # 1. ДИАГНОСТИКА И ЗАЩИТА ТИПОВ
        # Сценарий А: Пришла строка (Base64) -> Декодируем
        if isinstance(pdf_bytes, str):
            try:
                pdf_bytes = base64.b64decode(pdf_bytes)
            except Exception as e:
                raise ValueError(f"Ошибка декодирования входной строки Base64: {e}")

        # Сценарий Б: Пришли байты, но это НЕ PDF (начинаются не с %PDF),
        # возможно это байты Base64 (как было в вашей ошибке b'JVBER...')
        elif isinstance(pdf_bytes, bytes) and not pdf_bytes.startswith(b'%PDF'):
            try:
                # Пытаемся декодировать как Base64
                decoded = base64.b64decode(pdf_bytes)
                if decoded.startswith(b'%PDF'):
                    pdf_bytes = decoded
                    # print("✅ Успешно распознаны и декодированы байты Base64")
            except Exception:
                # Если не вышло, оставляем как есть, упадет на следующей проверке
                pass

        # Проверка на пустоту
        if not pdf_bytes:
            raise ValueError("На конвертацию переданы пустые данные (None или 0 байт)")
        # Проверка сигнатуры PDF (должен начинаться с %PDF)
        if not pdf_bytes.startswith(b'%PDF'):
            # Если данные есть, но это не PDF, логируем первые 20 байт для отладки
            raise ValueError(f"Данные не являются PDF файлом (Signature mismatch). Начало: {pdf_bytes[:20]}")
        # print(f"[DEBUG] Конвертация PDF: тип={type(pdf_bytes)}, размер={len(pdf_bytes)} байт")

        try:
            logging.info('1. Загрузка PDF из байтов')
            # 1. Загрузка PDF из байтов
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            page = doc[0]
            # Константа 1 мм ≈ 2.835 pt
            PT_TO_MM = 2.835


            if target_width_mm is not None:
                # Расчет масштаба для подгонки под конкретную ширину
                current_width_pt = page.rect.width
                current_width_mm = current_width_pt / PT_TO_MM
                scale_factor = target_width_mm / current_width_mm

                # Применяем масштабирование
                matrix = fitz.Matrix(scale_factor, scale_factor)

                print(
                    f"Текущая ширина PDF: {current_width_mm:.2f} мм. Целевая: {target_width_mm} мм. Масштаб: {scale_factor:.2f}")
            else:
                # Если масштабирование не задано (target_width_mm = None),
                # используем фиксированный высокий DPI для качественного рендеринга.
                # 72 - исходное разрешение PDF в МуPDF, 300 - целевое DPI
                scale_factor = self.DPI_DEFAULT / 72
                matrix = fitz.Matrix(scale_factor, scale_factor)
                print(f"Масштабирование не требуется (target_width_mm = None). Использование DPI: {self.DPI_DEFAULT}.")

            logging.info('2. Рендеринг страницы в Pixmap')
            # 2. Рендеринг страницы в Pixmap
            pix = page.get_pixmap(matrix=matrix, alpha=False)

            logging.info('3. Конвертация в PIL.Image')
            # 3. Конвертация в PIL.Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            print(f"3. Конвертация в PIL.Image. Размер после рендеринга: {img.size}")
            doc.close()
            # --- ФИНАЛЬНАЯ ОБРАБОТКА: ПОВОРОТ И РЕСАЙЗ/ОБРЕЗКА ---

            # 4. Поворот на -90 градусов (90 градусов по часовой стрелке)
            # expand=True гарантирует, что изображение расширится для размещения повернутого содержимого
            # PIL.Image.rotate(-90) выполняет поворот по часовой стрелке
            image = img.rotate(90, expand=True)
            print(f"4. Поворот на -90 градусов (по часовой). Размер после поворота: {image.size}")

            # 5. Финальное приведение к размеру 58x40 мм (при {self.DPI_DEFAULT} DPI)
            target_size_px = (self.FINAL_LABEL_W_PX, self.FINAL_LABEL_H_PX)

            # Обрезка/Ресайз (для Ozon-этикеток это часто обрезка, т.к. PDF может быть A4)

            # Ресайз до целевого размера с сохранением пропорций
            image.thumbnail(target_size_px, Image.Resampling.LANCZOS)

            # Создаем новое изображение целевого размера с белым фоном
            final_image = Image.new("RGB", target_size_px, "white")

            # Вставляем ресайзенное изображение в центр
            x_offset = (final_image.width - image.width) // 2
            y_offset = (final_image.height - image.height) // 2
            final_image.paste(image, (x_offset, y_offset))

            print(
                f"5. Финальный размер: {final_image.size} ({self.FINAL_LABEL_W_MM}x{self.FINAL_LABEL_H_MM} мм при {self.DPI_DEFAULT} DPI)")

            return final_image

            return img

        except Exception as e:
            # logging.error(f"Ошибка конвертации PDF в Image: {e}")
            raise RuntimeError(f"Ошибка конвертации PDF в Image: {e}")


    def print_png_gdi_from_file(self, png_path: str):
        """
        Печатает PNG-файл, используя драйвер принтера через Windows GDI (win32ui/win32print).

        Эта функция загружает PNG с диска, преобразует его в Windows Bitmap в памяти
        и рисует его на контексте принтера, минуя необходимость сохранения временного файла.

        Args:
            png_path: Полный путь к PNG-файлу.
            printer_name: Имя принтера, как оно указано в "Устройства и принтеры" Windows.
        """
        if not os.path.exists(png_path):
            print(f"❌ Ошибка: Файл не найден по пути: {png_path}")
            return

        # Инициализируем переменные для очистки
        screen_dc = None
        printer_dc = None
        mem_dc = None
        bmp = None

        try:
            # 1. ЗАГРУЗКА ИЗОБРАЖЕНИЯ (PIL)
            image_object = Image.open(png_path)

            # Конвертируем изображение PIL в формат, понятный GDI (RGB)
            image_rgb = image_object.convert("RGB")
            width, height = image_rgb.size
            bmp_data = image_rgb.tobytes()

            # 2. СОЗДАНИЕ BITMAP WINDOWS В ПАМЯТИ (win32ui)

            # Получаем стандартный контекст устройства (для создания совместимого битмапа)
            screen_dc = win32ui.CreateDC()
            screen_dc.CreateCompatibleDC()

            # Создаем объект битмапа Windows
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(screen_dc, width, height)

            # Загружаем данные изображения в битмап
            bmp.SetBitmapBits(len(bmp_data), bmp_data)

            # 3. НАЧАЛО ЗАДАНИЯ ПЕЧАТИ

            # Создаем контекст устройства принтера
            printer_dc = win32ui.CreateDC()
            printer_dc.CreatePrinterDC(self.printer_name)

            # Устанавливаем режим отображения
            printer_dc.SetMapMode(win32ui.MM_TEXT)

            # Начинаем документ печати
            printer_dc.StartDoc('PNG Print Job')
            printer_dc.StartPage()

            # 4. РИСОВАНИЕ ИЗОБРАЖЕНИЯ (BitBlt)

            # Создаем контекст памяти (Memory DC) для хранения битмапа
            mem_dc = printer_dc.CreateCompatibleDC()
            mem_dc.SelectObject(bmp)

            # Копируем битмап из памяти в контекст принтера (BitBlt)
            printer_dc.BitBlt(
                0, 0, width, height,
                mem_dc, 0, 0,
                win32ui.SRCCOPY
            )

            # 5. ЗАВЕРШЕНИЕ ЗАДАНИЯ ПЕЧАТИ

            printer_dc.EndPage()
            printer_dc.EndDoc()

            print(f"✅ Файл '{png_path}' успешно отправлен на печать на принтер '{self.printer_name}' через GDI.")

        except win32print.error as pe:
            print(f"❌ Ошибка принтера: Проверьте, что принтер '{self.printer_name}' установлен и доступен.")
            print(f"Подробности: {pe}")
        except Exception as e:
            print(f"❌ Непредвиденная ошибка: {e}")
        finally:
            # 6. ОЧИСТКА РЕСУРСОВ GDI
            # Удаляем DC. GDI-объекты должны быть удалены в обратном порядке создания.
            if mem_dc:
                mem_dc.DeleteDC()
            if printer_dc:
                printer_dc.DeleteDC()
            if screen_dc:
                screen_dc.DeleteDC()

            # Освобождаем ресурс HBITMAP, полагаясь на деструктор Python-объекта 'bmp'.
            if bmp:
                # Здесь мы полагаемся на то, что del bmp вызовет деструктор Python-объекта
                # и освободит связанный GDI-ресурс (DeleteObject).
                del bmp

    # --- ПРИМЕР ИСПОЛЬЗОВАНИЯ ---
    # print_png_gdi_from_file("C:\\path\\to\\your\\label.png", "Zebra ZD420")
    # print("Для запуска примера замените путь к файлу и имя принтера на ваши реальные и раскомментируйте вызов функции.")

    def print_zpl_network(self, zpl_code, host: str, port: int = 9100) -> bool:
        """
        Отправляет ZPL код на локальный принтер.
        Под Windows использует win32print (RAW data).
        """

        # ЛОГИКА ДЛЯ LINUX/ТЕСТИРОВАНИЯ
        if not IS_WINDOWS:
            log(f"ZPL-печать имитирована для принтера: {self.printer_name} (Linux/Test)")
            try:
                # Используем заглушку WritePrinter
                win32print.WritePrinter(999, zpl_code)
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
            # zpl_bytes = zpl_code.encode('utf-8')
            win32print.WritePrinter(hprinter, zpl_code)

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

    def reorient_zpl_to_portrait_auto(self,zpl_data: str) -> str:
        """
        Автоматически определяет длину этикетки и переориентирует ZPL-код
        с альбомной ориентации (^POI) на портретную (^PON).

        Args:
            zpl_code: Строка с исходным ZPL-кодом.

        Returns:
            Строка с переориентированным ZPL-кодом.
        """
        # Установите значение по умолчанию на случай, если ^LL или ^PW не найдены.
        DEFAULT_LABEL_LENGTH = 58
        # ПРОВЕРКА И ДЕКОДИРОВАНИЕ
        if isinstance(zpl_data, bytes):
            try:
                zpl_code = zpl_data.decode('utf-8')
            except UnicodeDecodeError:
                zpl_code = zpl_data.decode('latin-1')
        elif isinstance(zpl_data, str):
            zpl_code = zpl_data
        else:
            raise TypeError("ZPL input must be a string (str) or bytes-like object (bytes).")

        # --- ЭТАП 1: ОПРЕДЕЛЕНИЕ ДЛИНЫ ЭТИКЕТКИ (LABEL_LENGTH) ---
        label_length = DEFAULT_LABEL_LENGTH

        # 1a. Поиск ^LL (Label Length)
        # Ищем: ^LL и число
        ll_match = re.search(r"\^LL(\d+)", zpl_code)
        if ll_match:
            label_length = int(ll_match.group(1))
        else:
            # 1b. Поиск ^PW (Print Width)
            # В ZPL-коде без ^LL, Print Width (^PW) часто соответствует длине.
            pw_match = re.search(r"\^PW(\d+)", zpl_code)
            if pw_match:
                # Для ^POI, Print Width - это фактическая ДЛИНА в портретном режиме.
                label_length = int(pw_match.group(1))

        print(f"📌 Определенная длина этикетки (LABEL_LENGTH): {label_length} точек")

        # --- ЭТАП 2: ПЕРЕОРИЕНТАЦИЯ КООРДИНАТ И КОМАНД ---
        new_zpl_lines = []

        # Регулярное выражение для поиска команд позиционирования и их координат:
        # Ищем: ^F[O|T] (команда ^FO или ^FT) + x,y (координаты X и Y) + остальная часть команды
        position_regex = re.compile(r"(\^F[O|T])(\d+),(\d+)(.*)")

        for line in zpl_code.splitlines():
            modified_line = line.strip()

            # 2a. Корректировка команд ориентации печати
            # Заменяем инвертированную ориентацию на нормальную (портретную)
            if '^POI' in modified_line:
                modified_line = modified_line.replace('^POI', '^PON')

            # 2b. Корректировка вращения шрифтов
            # Убираем вращение (Rotate)
            if '^AZR' in modified_line:
                modified_line = modified_line.replace('^AZR', '^A0N')

                # 2c. Пересчет координат ^FOx,y и ^FTx,y
            match = position_regex.match(modified_line)

            if match:
                command = match.group(1)
                old_x = int(match.group(2))
                old_y = int(match.group(3))
                rest_of_line = match.group(4)

                # Формула пересчета:
                # X_новое = Y_старое
                # Y_новое = LABEL_LENGTH - X_старое (инверсия относительно длины)

                new_x = old_y
                new_y = label_length - old_x

                modified_line = f"{command}{new_x},{new_y}{rest_of_line}"

            new_zpl_lines.append(modified_line)
            result = '\n'.join(new_zpl_lines)
        return  result.encode('utf-8', errors='ignore')

    def print_ozon_label_fbs(self, file_content:bytes)-> bool:
        file_extension = 'png'
        decoded_data = self._convert_pdf_to_image(file_content) #.encode())
        temp_dir = "debug_labels"
        os.makedirs(temp_dir, exist_ok=True)
        filename = os.path.join(temp_dir, f"temp_{datetime.now().strftime('%H%M%S')}.{file_extension}")
        try:
            # with open(filename, "wb") as f:
            #     f.write(decoded_data)
            # И заменить его на:
            decoded_data.save(filename, format='PNG')  # <-- Правильный способ
            logging.info(f"✅ DEBUG: Сохранен файл этикетки для анализа: {filename}")
            print(f"✅ DEBUG: Сохранен файл этикетки для анализа: {filename}")
        except Exception as e:
            logging.error(f"❌ Ошибка при сохранении файла отладки: {e}")
            print(f"❌ Ошибка при сохранении файла отладки: {e}")
            return False
        log("🔎 Формат: PNG. Выполняю печать.")
        try:
            self.print_on_windows_light(filename)
            logging.info(f"✅ Этикетка успешно напечатана")
            print(f"✅ Этикетка успешно напечатана")
        except Exception as e:
            logging.error(f"❌ Ошибка печати фала:{filename} на принтере {self.printer_name}:{e}")
            print(f"❌ Ошибка печати фала:{filename} на принтере {self.printer_name}:{e}")
            return False
        return True

    # НОВЫЙ МЕТОД: Точка входа для печати WB/Ozon этикеток
    def print_wb_ozon_label(self, label_data_base64: str, order_id: str = 'temp', type: str = 'zpl')-> bool:
        """
        Универсальный метод печати для WB (ZPL) и png.
        Определяет формат данных и вызывает соответствующий низкоуровневый метод печати.
        """
        import base64
        debug_info = True
        try:
            if debug_info: print('Пытаемся декодировать, предполагая base64')
            decoded_data = base64.b64decode(label_data_base64)
        except Exception:
            if debug_info: print('Декодировать не удалось, предполагаем, что это чистый ZPL текст')
            decoded_data = label_data_base64.encode('utf-8', errors='ignore')

        # --- ЛОГИКА ВРЕМЕННОЙ ОТЛАДКИ: СОХРАНЕНИЕ ФАЙЛА ---
        temp_dir = "debug_labels"
        os.makedirs(temp_dir, exist_ok=True)

        # Определяем расширение и имя файла
        file_extension = 'txt'
        if 'png' in type:
            file_extension = 'png'
        elif 'zpl' in type or 'ZPL' in type or decoded_data.startswith(b'^XA'):
            file_extension = 'zpl'
            decoded_data2 = None
            # Пытаемся развернуть изображение --------------
            try:
                decoded_data2 = self.reorient_zpl_to_portrait_auto(decoded_data)
            except Exception as e:
                logging.error(f"❌ Ошибка при конвертации ротации файла zpl: {e}")
                print(f"❌ Ошибка при конвертации ротации файла zpl: {e}")
            # -----------------------------------------------
            filename2 = os.path.join(temp_dir,
                             f"wb_label_{order_id}_{datetime.now().strftime('%H%M%S')}_v2.{file_extension}")
            if decoded_data2:
                try:
                    with open(filename2, "wb") as f2:
                        f2.write(decoded_data2)
                    logging.info(f"✅ DEBUG: Сохранен файл этикетки для анализа: {filename2}")
                    print(f"✅ DEBUG: Сохранен файл этикетки для анализа: {filename2}")
                except Exception as e:
                    logging.error(f"❌ Ошибка при сохранении файла отладки:{filename2} {e}")
                    print(f"❌ Ошибка при сохранении файла отладки:{filename2} {e}")


        filename = os.path.join(temp_dir,f"wb_label_{order_id}_{datetime.now().strftime('%H%M%S')}.{file_extension}")
        try:
            with open(filename, "wb") as f:
                f.write(decoded_data)
            logging.info(f"✅ DEBUG: Сохранен файл этикетки для анализа: {filename}")
            print(f"✅ DEBUG: Сохранен файл этикетки для анализа: {filename}")
        except Exception as e:
            logging.error(f"❌ Ошибка при сохранении файла отладки: {e}")
            print(f"❌ Ошибка при сохранении файла отладки: {e}")


         # --- КОНЕЦ ЛОГИКИ ВРЕМЕННОЙ ОТЛАДКИ ---
        log(f"Начало универсальной печати на принтер: {self.printer_name}")

        # 2. Определяем формат
        if 'zpl' in type or 'ZPL' in type or decoded_data.startswith(b'^XA'):
            # --- ZPL (Wildberries) ---
            log("🔎 Формат: ZPL. Передаю в print_zpl_network.")
            if 'zplh' in type or 'ZPLH' in type:
                return self.print_zpl_network(decoded_data, host=None, port=None)
            elif 'zplv' in type or 'ZPLV' in type:
                return self.print_zpl_network(decoded_data2, host=None, port=None)
            else:
                log("❌ Неопознанный формат данных этикетки ZPL. Обратитесь к разработчику для поддержки печати других форматов")
                return False
        elif 'png' in type:
            # ---  PNG (Wildberries)---
            log("🔎 Формат: PNG. Выполняю печать.")
            try:
                # self.print_png_gdi_from_file(filename)
                self.print_on_windows_light(filename)
                return True
            except Exception as e:
                    logging.error(f"❌ Ошибка печати фала:{filename} на принтере {self.printer_name}:{e}")
                    print(f"❌ Ошибка печати фала:{filename} на принтере {self.printer_name}:{e}")


        else:
            log("❌ Неопознанный формат данных этикетки (ни ZPL, ни PNG). Обратитесь к разработчику для поддержки печати других форматов")
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

    def print_on_windows_other(self, image_path: Optional[str] = None, image=None):
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
    def print_on_windows_light(self, image_path:str):
        """
        Отправляет изображение этикетки на печать.
        Можно передать  путь к файлу,
        """

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

        except Exception as e:
            print(f"❌ Ошибка печати, на принтере {printer_name}:", str(e))

        # ----------------------------------------------
    def print_on_windows(self, image_path=None, image=None): # Оригинальное исполнение, которое ранее работало
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
