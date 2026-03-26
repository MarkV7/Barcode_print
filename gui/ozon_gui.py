import traceback
import os
import tkinter as tk
import customtkinter as ctk
import pandas as pd
from datetime import datetime
from tkinter import messagebox
from gui.gui_table import EditableDataTable
from sound_player import play_success_scan_sound, play_unsuccess_scan_sound
from printer_handler import LabelPrinter
from db_manager import DBManager  # <--- ИМПОРТ МЕНЕДЖЕРА БД
from gui.fbs_union_gui import UnionMark
import logging
# Создаем логгер для конкретного модуля
logger = logging.getLogger(__name__)

class OzonMode(ctk.CTkFrame, UnionMark):
    def __init__(self, parent, font, app_context):
        super().__init__(parent)
        self.font = font
        self.app_context = app_context
        self.editing = False
        self.focus_timer_id = None
        self.clear_timer_id = None
        self.scan_entry = None
        self.marking_code_entry = None
        self.current_product = None

        # Инициализация менеджера БД
        self.db = DBManager()

        # Инициализируем UI
        self.setup_ui()

        # Восстанавливаем таблицу из контекста приложения
        if self.app_context.fbo_table_ozon is not None and not self.app_context.fbo_table_ozon.empty:
            self.fbo_df = self.app_context.fbo_table_ozon.copy()
        else:
            self.fbo_df = pd.DataFrame(columns=["Артикул Ozon", "Количество", "Код маркировки"])

        self.update_table()

    def setup_ui(self):
        """Создаёт интерфейс"""
        # Заголовок
        self.title_label = ctk.CTkLabel(
            self,
            text="ФБО Озон",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w"
        )
        self.title_label.place(relx=0.0, rely=0.0, anchor="nw", x=10, y=5)

        # Скрытый Entry для сканирования
        self.scan_entry = ctk.CTkEntry(self, width=200, height=1, border_width=0)
        self.scan_entry.pack(pady=0, padx=0)
        self.scan_entry.bind("<KeyRelease>", self.reset_clear_timer)
        self.scan_entry.bind("<Return>", self.handle_barcode)
        self.scan_entry.bind("<FocusIn>", self.on_entry_focus_in)
        self.scan_entry.bind("<FocusOut>", self.on_entry_focus_out)
        self.scan_entry.bind("<KeyPress>", self.handle_keypress)
        self.restore_entry_focus()

        # Метка статуса
        status_frame = ctk.CTkFrame(self, fg_color="transparent")
        status_frame.pack(fill="x", pady=(10, 0))
        self.scanning_label = ctk.CTkLabel(
            status_frame,
            text="Ожидание сканирования... 📱",
            font=("Segoe UI", 16, "bold"),
            anchor="center"
        )
        self.scanning_label.pack()

        # Поле ввода честного знака
        self.marking_code_entry = ctk.CTkEntry(self, placeholder_text="Введите код маркировки...", width=300)
        self.marking_code_entry.pack(pady=10)
        self.marking_code_entry.focus_set()
        self.marking_code_entry.lower()
        self.marking_code_entry.bind("<Return>", self.handle_marking_code)
        self.marking_code_entry.bind("<FocusOut>", self.handle_marking_code)

        self.product_info_label = ctk.CTkLabel(
            self,
            text="Информация о товаре",
            font=("Segoe UI", 14),
            anchor="e",
            corner_radius=5,
            fg_color="gray85",
            text_color="gray20",
        )
        self.product_info_label.pack()
        self.product_info_label.lower()

        # Лог сообщений
        self.log_label = ctk.CTkLabel(
            self,
            text="",
            font=("Segoe UI", 14),
            anchor="e",
            padx=10,
            pady=5,
            corner_radius=5,
            fg_color="gray85",
            text_color="gray20",
        )
        self.log_label.place(relx=1.0, rely=0.0, anchor="ne", x=-15, y=15)
        self.log_label.lower()

        # Контейнер таблицы
        self.table_container = ctk.CTkFrame(self)
        self.table_container.pack(fill="both", expand=True, padx=20, pady=10)

    def handle_keypress(self, event):
        if hasattr(self, 'table') and self.table:
            self.table.on_keypress(event)

    def reset_clear_timer(self, event=None):
        if self.clear_timer_id:
            self.after_cancel(self.clear_timer_id)
        self.clear_timer_id = self.after(300, self.scan_entry.delete, 0, "end")

    def restore_entry_focus(self, event=None):
        if self.editing:
            return
        self.scan_entry.focus_set()
        self.focus_timer_id = self.after(100, self.restore_entry_focus)

    def on_entry_focus_in(self, event=None):
        if not self.editing:
            self.scanning_label.configure(text="Ожидание сканирования... 📱")

    def on_entry_focus_out(self, event=None):
        if not self.editing:
            self.scanning_label.configure(text="")

    def handle_barcode(self, event=None):
        barcode = self.scan_entry.get().strip()
        self.scan_entry.delete(0, "end")
        if not barcode:
            return

        # === 1. ПОПЫТКА ПОИСКА В БД (SQLite) ===
        try:
            result = self.db.get_product_by_barcode(barcode=barcode)

            if len(result) > 0:
                self.current_product = result.iloc[0]
                row = result.iloc[0]  # Извлекаем первую (и единственную) строку

                # Конфигурация проверок: поле → сообщение → проигрывать звук
                VALIDATIONS = [
                    ("Штрихкод OZON", "⚠️ У продукта нет штрихкода OZON", True),
                    ("Артикул Ozon", "⚠️ У продукта нет артикула OZON", False),
                ]
                for field, message, play_sound in VALIDATIONS:
                    value = row.get(field)
                    if pd.isna(value) or not value:
                        if play_sound:
                            play_unsuccess_scan_sound()
                        self.show_log(message, bg_color="#FFE0E0", text_color="red")
                        return
                self.show_log("✅ Товар найден в БД", bg_color="#E0FFE0", text_color="green")
            else:
                self.show_log("✅ Товар НЕ найден в БД", bg_color="#E0FFE0", text_color="red")
                return

        except Exception as e:
            self.show_log(f"Ошибка поиска в БД: {e}")
        #     # Если ошибка БД, просто идем дальше к старому методу
        #
        # # === 2. ФОЛБЭК НА СТАРЫЙ МЕТОД (Excel/Context) ===
        # if founded_row.empty:
        #     messagebox.showwarning("Ошибка", "Товар не найден в БД, а файл базы данных не загружен.")
        #     return
        #
        # #     # Старый поиск по штрихкоду
        # #     founded_row = self.app_context.df[self.app_context.df["Штрихкод производителя"].astype(str) == barcode]
        # #     source = "context"
        # #
        # # # === ПРОВЕРКИ РЕЗУЛЬТАТА ===
        # # if founded_row.empty:
        # #     play_unsuccess_scan_sound()
        # #     self.show_log("⚠️ Штрихкод не найден ни в БД, ни в файле", bg_color="#FFE0E0", text_color="red")
        # #     return
        #
        # # Сохраняем текущий товар
        # self.current_product = founded_row.iloc[0]
        #
        # Проверяем наличие обязательных полей
        # ozon_barcode = self.current_product.get('Штрихкод OZON')
        # if pd.isna(ozon_barcode) or not ozon_barcode:
        #     play_unsuccess_scan_sound()
        #     self.show_log("⚠️ У продукта нет штрихкода OZON", bg_color="#FFE0E0", text_color="red")
        #     return
        #
        # ozon_article = self.current_product.get('Артикул Ozon')
        # if pd.isna(ozon_article) or not ozon_article:
        #     self.show_log("⚠️ У продукта нет артикула OZON", bg_color="#FFE0E0", text_color="red")
        #     return
        #
        # play_success_scan_sound()

        self.show_log("✅ Код принят (из БД)", bg_color="#D0F0C0", text_color="darkgreen")
        product_info = (
            f"{self.current_product['Артикул производителя']} | "
            f"{self.current_product['Размер']} | "
            f"{self.current_product['Наименование поставщика']} | "
            f"{self.current_product['Артикул Ozon']}"
        )
        # Переключаемся на ввод кода маркировки
        self.await_marking_code(product_info)



    def await_marking_code(self, product_info):
        """Открывает поле для ввода кода маркировки"""
        self.marking_code_entry.lift()
        self.marking_code_entry.focus()
        self.scanning_label.configure(text="Отсканируйте честный знак:")
        self.scanning_label.lift()
        self.product_info_label.configure(text=product_info)
        self.product_info_label.lift()
        self.on_edit_start()

    def handle_marking_code(self, event=None):
        self.on_edit_end()

        label_printer = LabelPrinter(self.app_context.printer_name)
        code = self.marking_code_entry.get().strip()

        # Сбрасываем UI
        self.scanning_label.configure(text="Ожидание сканирования... 📱")
        self.product_info_label.lower()
        self.marking_code_entry.delete(0, tk.END)
        self.marking_code_entry.lower()

        if not code:
            return

        # if not label_printer.is_correct_gs1_format(code):
        #     play_unsuccess_scan_sound()
        #     self.show_log("❌ Неверный формат кода маркировки", bg_color="#FFE0E0", text_color="red")
        #     return
        if not self.is_valid_chestny_znak(code):
            play_unsuccess_scan_sound()
            self.show_log("❌ Неверный формат кода маркировки", bg_color="#FFE0E0", text_color="red")
            return
        play_success_scan_sound()
        self.scanning_label.configure(text='Идет распечатка этикеток...')

        # === ПЕЧАТЬ ЭТИКЕТОК ===
        filename = '__temp_label_print__.png'
        try:
            ozon_id = self.current_product['Штрихкод OZON']
            ozon_product_info = [
                f"{ozon_id}",
                f"{self.current_product.get('Наименование поставщика', '')}",
                f"Артикул ozon: {self.current_product.get('Артикул Ozon', '')}"
            ]
            ozon_label = label_printer.create_ozon_label(str(ozon_id), ozon_product_info, 'DejaVuSans.ttf')
            ozon_label.save(filename)
            label_printer.print_on_windows(image_path=filename)
            # label_printer.print_on_windows(image_path=filename) # Второй раз если нужно
        except Exception as ex:
            self.log_error("OZON_eticate", ex)

        try:
            chestniy_znak_product_info = [
                f"{self.current_product.get('Наименование поставщика', '')}",
                f"Размер: {self.current_product.get('Размер', '')}"
            ]
            chestniy_znak_label = label_printer.generate_gs1_datamatrix_from_raw(code, chestniy_znak_product_info)
            chestniy_znak_label.save(filename)
            label_printer.print_on_windows(image_path=filename)
            # label_printer.print_on_windows(image_path=filename) # Второй раз если нужно
        except Exception as ex:
            self.log_error("CHESTNZKNAK", ex)

        if os.path.exists(filename):
            os.remove(filename)

        # Обновляем таблицу интерфейса
        self.add_or_update_table_entry(code)

        self.after(2000, lambda: self.log_label.configure(text=""))
        self.scanning_label.configure(text='Ожидание сканирования... 📱')
        self.show_log("✅ Успешно", bg_color="#E0FFE0", text_color="green")
        play_success_scan_sound()

    def log_error(self, prefix, ex):
        error_details = {
            'type': type(ex).__name__,
            'message': str(ex),
            'traceback': traceback.format_exc()
        }
        with open(f'error_{prefix}.txt', 'w', encoding='utf-8') as f:
            f.write(f"=== Ошибка при печати {prefix} ===\n")
            f.write(f"Тип ошибки: {error_details['type']}\n")
            f.write(f"Сообщение: {error_details['message']}\n")
            f.write("Traceback:\n")
            f.write(''.join(error_details['traceback']))

    def print_labels(self, code):
        """Моделирует печать этикеток"""
        print(f"Печать этикеток для: {code}")

    def add_or_update_table_entry(self, code):
        art = self.current_product.get("Артикул Ozon")

        matches = self.fbo_df[self.fbo_df["Артикул Ozon"] == art]

        if not matches.empty:
            idx = matches.index[0]
            current_count = self.fbo_df.loc[idx, "Количество"]
            marking_codes = self.fbo_df.loc[idx, "Код маркировки"]

            try:
                current_count = int(current_count)
            except (ValueError, TypeError):
                current_count = 0

            if isinstance(marking_codes, str) and marking_codes:
                marking_codes += ", " + code
            else:
                marking_codes = code

            self.fbo_df.loc[idx, "Количество"] = current_count + 1
            self.fbo_df.loc[idx, "Код маркировки"] = marking_codes
        else:
            new_row = pd.DataFrame([{
                "Артикул Ozon": art,
                "Количество": 1,
                "Код маркировки": code
            }])
            self.fbo_df = pd.concat([self.fbo_df, new_row], ignore_index=True)

        self.update_table()

    def update_table(self):
        """Обновляет таблицу"""
        if hasattr(self, 'table'):
            self.table.destroy()

        self.table = EditableDataTable(
            self.table_container,
            dataframe=self.fbo_df,
            columns='',
            header_font=("Segoe UI", 14, "bold"),
            cell_font=("Segoe UI", 14),
            on_row_select=None,
            readonly=False,
            on_edit_start=self.on_edit_start,
            on_edit_end=self.on_edit_end
        )
        self.table.pack(fill="both", expand=True)

    def on_edit_start(self):
        self.editing = True
        if self.focus_timer_id:
            self.after_cancel(self.focus_timer_id)

    def on_edit_end(self):
        self.editing = False
        self.app_context.fbo_table_ozon = self.table.displayed_df.copy()
        self.fbo_df = self.table.displayed_df.copy()
        self.start_auto_focus()

    def start_auto_focus(self):
        if self.focus_timer_id:
            self.after_cancel(self.focus_timer_id)
        self.restore_entry_focus()

    def show_log(self, message, bg_color="#E0FFE0", text_color="green", is_error=False):
        """Показывает сообщение с анимацией появления и исчезновения"""
        self._log_bg_color = bg_color
        self._log_text_color = text_color
        self.log_label.configure(text=message, text_color=text_color, fg_color=bg_color)
        self.log_label.lift()
        # --- дополнение нового вывода ----
        if self.log_label:
            color = "red" if is_error else "green"
            self.log_label.configure(text=message, text_color=color)
            if is_error:
                logger.error(message)
            else:
                logger.info(message)
        # ----------------------------------
        self.after(1500, self.animate_log_fade_out)

    def animate_log_fade_in(self, bg_color, text_color, alpha):
        if alpha >= 1.0:
            self.after(1500, lambda: self.animate_log_fade_out(bg_color, text_color, 1.0))
            return
        start_bg = "#DDDDDD"
        blended_bg = self.blend_colors(start_bg, bg_color, alpha)
        blended_text = text_color if alpha >= 0.5 else "gray50"
        self.log_label.configure(fg_color=blended_bg, text_color=blended_text)
        self.after(30, lambda: self.animate_log_fade_in(bg_color, text_color, alpha + 0.1))

    def animate_log_fade_out(self, step=10, current_step=0):
        if current_step >= step:
            self.log_label.configure(text="", fg_color="#FFFFFF")
            self.log_label.lower()
            return
        bg = self.hex_to_grayscale(self._log_bg_color, factor=1 - (current_step / step))
        text = self._log_text_color if current_step < step * 0.6 else "gray70"
        self.log_label.configure(fg_color=bg, text_color=text)
        self.after(30, lambda: self.animate_log_fade_out(step, current_step + 1))

    def hex_to_grayscale(self, color, factor=1.0):
        def hex_to_rgb(h):
            h = h.lstrip('#')
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

        def rgb_to_hex(r, g, b):
            return f"#{r:02X}{g:02X}{b:02X}"

        try:
            r, g, b = hex_to_rgb(color)
        except ValueError:
            return "#FFFFFF"
        w_r, w_g, w_b = 255, 255, 255
        blended_r = int(r * factor + w_r * (1 - factor))
        blended_g = int(g * factor + w_g * (1 - factor))
        blended_b = int(b * factor + w_b * (1 - factor))
        return rgb_to_hex(blended_r, blended_g, blended_b)