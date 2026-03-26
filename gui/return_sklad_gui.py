import tkinter as tk
import customtkinter as ctk
import pandas as pd
from tkinter import messagebox
from gui.gui_table import EditableDataTable
from sound_player import play_success_scan_sound, play_unsuccess_scan_sound
from db_manager import DBManager  #  ИМПОРТ МЕНЕДЖЕРА БД
import logging
# Создаем логгер для конкретного модуля
logger = logging.getLogger(__name__)


class ReturnMode(ctk.CTkFrame):
    def __init__(self, parent, font, app_context):
        super().__init__(parent)
        self.font = font
        self.app_context = app_context
        self.editing = False
        self.focus_timer_id = None
        self.clear_timer_id = None
        # Инициализация менеджера БД
        self.db = DBManager()
        # Заголовок
        self.title_label = ctk.CTkLabel(
            self,
            text="Возврат на склад",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w"
        )
        self.title_label.place(relx=0.0, rely=0.0, anchor="nw", x=10, y=5)

        # Скрытый Entry для сканирования
        self.scan_entry = None
        self.setup_entry()

        # Верхний контейнер для статуса (по центру)
        status_frame = ctk.CTkFrame(self, fg_color="transparent")
        status_frame.pack(fill="x", pady=(10, 0))

        self.scanning_label = ctk.CTkLabel(
            status_frame,
            text="Ожидание сканирования... 📱",
            font=("Segoe UI", 16, "bold"),
            anchor="center"
        )
        self.scanning_label.pack()

        # Журнал справа сверху (в абсолютных координатах)
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

        # Таблица
        self.table_container = ctk.CTkFrame(self)
        self.table_container.pack(fill="both", expand=True, padx=20, pady=10)

        # DataFrame для временного хранения возвращаемых товаров
        if self.app_context.return_table_df is not None and not self.app_context.return_table_df.empty:
            self.return_df = self.app_context.return_table_df.copy()
        else:
            self.return_df = pd.DataFrame(columns=["Артикул производителя", "Размер", "Кол-во", "Коробка"])
        # Определяем список колонок, которые используются в логике обработки (строка 135)
        self.column_names = ["Артикул", "Размер", "Штрихкод", "Код маркировки", "Статус"]
        # Таблица
        self.table = EditableDataTable(
            self.table_container,
            dataframe=self.return_df,
            columns=self.column_names,
            header_font=("Segoe UI", 14, "bold"),
            cell_font=("Segoe UI", 14),
            readonly=False,
            on_edit_start=self.on_edit_start,
            on_row_select=self.on_row_selected,
            on_edit_end=self.on_edit_end
        )
        self.table.pack(fill="both", expand=True)

        # Привязка кликов по таблице для восстановления фокуса
        self.table.bind("<Button-1>", self.restore_entry_focus)
        for child in self.table.winfo_children():
            child.bind("<Button-1>", self.restore_entry_focus)

    def on_row_selected(self, row_values=None):
        """Обработка выбора строки в таблице"""
        # Теперь метод может принимать данные строки напрямую
        pass

    def setup_entry(self):
        """Создаёт скрытое поле ввода и привязывает события"""
        self.scan_entry = ctk.CTkEntry(self, width=200, height=10, border_width=0)
        self.scan_entry.pack(pady=0, padx=0)
        # self.scan_entry.lower()

        self.scan_entry.bind("<KeyRelease>", self.reset_clear_timer)  # Отслеживаем ввод
        self.scan_entry.bind("<Return>", self.handle_barcode)
        self.scan_entry.bind("<FocusIn>", self.on_entry_focus_in)
        self.scan_entry.bind("<FocusOut>", self.on_entry_focus_out)
        self.scan_entry.bind("<KeyPress>", self.handle_keypress)

        self.restore_entry_focus()

    def handle_keypress(self, event):
        if self.table:
            self.table.on_keypress(event)

    def reset_clear_timer(self, event=None):
        if self.clear_timer_id:
            self.after_cancel(self.clear_timer_id)
        self.clear_timer_id = self.after(300, self.scan_entry.delete, 0, "end")

    def start_auto_focus(self):
        if self.focus_timer_id:
            self.after_cancel(self.focus_timer_id)
        self.restore_entry_focus()

    def restore_entry_focus(self, event=None):
        if self.editing:
            return
        self.scan_entry.focus_set()
        self.focus_timer_id = self.after(100, self.restore_entry_focus)

    def on_edit_start(self):
        self.editing = True
        if self.focus_timer_id:
            self.after_cancel(self.focus_timer_id)
            self.focus_timer_id = None

    def on_edit_end(self):
        self.editing = False
        self.start_auto_focus()
        self.app_context.return_table_df = self.table.displayed_df
        self.return_df = self.table.displayed_df

    def on_entry_focus_in(self, event=None):
        """Показываем подсказку при фокусе на entry"""
        self.scanning_label.configure(text="Ожидание сканирования... 📱")

    def on_entry_focus_out(self, event=None):
        """Скрываем подсказку, если фокус потерян"""
        self.scanning_label.configure(text="")

    def handle_barcode(self, event=None):
        barcode = self.scan_entry.get().strip()
        if not barcode:
            return

        self.scan_entry.delete(0, tk.END)

        try:
            result = self.db.get_product_by_barcode(barcode=barcode)

            if len(result) > 0:
                art = result["Артикул производителя"].iloc[0]
                size = result["Размер"].iloc[0]

                if "Коробка" in result.columns:
                    box_raw = result["Коробка"].iloc[0]
                    box = "-" if pd.isna(box_raw) or box_raw is None or box_raw == "" else str(box_raw)
                else:
                    box = "-"

                # Обновление или добавление записи
                mask = (
                        (self.return_df["Артикул производителя"] == art) &
                        (self.return_df["Размер"] == size)
                )
                if mask.any():
                    idx = self.return_df.index[mask].tolist()[0]
                    current_value = self.return_df.at[idx, "Кол-во"]

                    try:
                        current_value = int(current_value)
                    except (ValueError, TypeError):
                        current_value = 0

                    self.return_df.at[idx, "Кол-во"] = current_value + 1
                else:
                    new_row = pd.DataFrame([{
                        "Артикул производителя": art,
                        "Размер": size,
                        "Кол-во": 1,
                        "Коробка": box
                    }])
                    self.return_df = pd.concat([self.return_df, new_row], ignore_index=True)

                # Обновляем лог
                play_success_scan_sound()
                self.show_log(f"✅ Добавлен: {art} | {size}", bg_color="#E0FFE0", text_color="green")
                self.update_table()
                self.on_edit_end()
            else:
                self.show_log(f"✅ Информации по товару : {barcode} в Базе данных не найдено")
        except Exception as e:
            self.show_log(f"Ошибка при поиске штрихкода: {e}")
            # self.scanning_label.configure(text="Ошибка БД", text_color="red")

        # Через 2 секунды очищаем лог
        self.after(2000, lambda: self.log_label.configure(text=""))

    def handle_barcode_old(self, event=None):
        barcode = self.scan_entry.get().strip()
        if not barcode:
            return

        self.scan_entry.delete(0, "end")

        if self.app_context.df is None:
            messagebox.showwarning("Ошибка", "Сначала загрузите файл базы данных.")
            return

        founded_row = None
        for _, row in self.app_context.df.iterrows():
            if str(row["Штрихкод производителя"]) == str(barcode):
                founded_row = row
                break  # Прерываем цикл после первого совпадения

        if founded_row is None:
            play_unsuccess_scan_sound()
            self.show_log("⚠️ Не найдено", bg_color="#FFE0E0", text_color="red")
            return

        art = row["Артикул производителя"]
        size = row["Размер"]
        box = row.get("Коробка")
        if box is None or pd.isna(box) or not bool(box):
            box = "-"

        # Обновление или добавление записи
        if ((self.return_df["Артикул производителя"] == art) & (self.return_df["Размер"] == size)).any():
            idx = self.return_df.index[(self.return_df["Артикул производителя"] == art) & (self.return_df["Размер"] == size)].tolist()[0]
            # Получаем текущее значение
            current_value = self.return_df.at[idx, "Кол-во"]
            # Конвертируем в int, если возможно
            try:
                current_value = int(current_value)
            except (ValueError, TypeError):
                current_value = 0  # или другое значение по умолчанию
            # Увеличиваем и сохраняем обратно
            self.return_df.at[idx, "Кол-во"] = current_value + 1
        else:
            new_row = new_row = pd.DataFrame([{
                "Артикул производителя": art,
                "Размер": size,
                "Кол-во": 1,
                "Коробка": box
            }])
            self.return_df = pd.concat([self.return_df, new_row], ignore_index=True)

        # Обновляем лог
        play_success_scan_sound()
        self.show_log(f"✅ Добавлен: {art} | {size}", bg_color="#E0FFE0", text_color="green")
        self.update_table()
        self.on_edit_end()

        # Через 2 секунды очищаем лог
        self.after(2000, lambda: self.log_label.configure(text=""))

    def show_log(self, message, bg_color="#E0FFE0", text_color="green",is_error=False):
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
        # Показываем сразу (без анимации появления)
        self.after(1500, self.animate_log_fade_out)

    def animate_log_fade_in(self, bg_color, text_color, alpha):
        if alpha >= 1.0:
            # После появления запускаем исчезновение
            self.after(1500, lambda: self.animate_log_fade_out(bg_color, text_color, 1.0))
            return

        # Интерполируем цвет от серого к целевому
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

        # Линейное осветление фона
        bg = self.hex_to_grayscale(self._log_bg_color, factor=1 - (current_step / step))
        text = self._log_text_color if current_step < step * 0.6 else "gray70"

        self.log_label.configure(fg_color=bg, text_color=text)
        self.after(30, lambda: self.animate_log_fade_out(step, current_step + 1))

    def hex_to_grayscale(self, color, factor=1.0):
        """Превращает цвет в более светлый, в зависимости от factor (0 — белый, 1 — оригинал)"""

        def hex_to_rgb(h):
            h = h.lstrip('#')
            return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

        def rgb_to_hex(r, g, b):
            return f"#{r:02X}{g:02X}{b:02X}"

        try:
            r, g, b = hex_to_rgb(color)
        except ValueError:
            return "#FFFFFF"

        # Белый базовый цвет
        w_r, w_g, w_b = 255, 255, 255

        # Смешиваем цвет с белым
        blended_r = int(r * factor + w_r * (1 - factor))
        blended_g = int(g * factor + w_g * (1 - factor))
        blended_b = int(b * factor + w_b * (1 - factor))

        return rgb_to_hex(blended_r, blended_g, blended_b)

    def update_table(self):
        self.table.destroy()
        self.table = EditableDataTable(
            self.table_container,
            dataframe=self.return_df,
            columns=self.column_names,
            header_font=("Segoe UI", 14, "bold"),
            cell_font=("Segoe UI", 14),
            readonly=False,
            on_edit_start=self.on_edit_start,
            on_row_select=self.on_row_selected,
            on_edit_end=self.on_edit_end
        )
        self.table.pack(fill="both", expand=True)
