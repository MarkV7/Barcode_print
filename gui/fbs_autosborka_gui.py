import pandas as pd
import customtkinter as ctk
import os
from datetime import datetime
from tkinter import messagebox
import easygui as eg
from sound_player import play_success_scan_sound, play_unsuccess_scan_sound
from gui.gui_table import EditableDataTable
from wildberries_fbs_api import WildberriesFBSAPI
from printer_handler import LabelPrinter


class FBSMode(ctk.CTkFrame):
    def __init__(self, parent, font, app_context):
        super().__init__(parent)
        self.font = font
        self.app_context = app_context
        self.editing = False
        self.focus_timer_id = None
        self.clear_timer_id = None
        self.scan_entry = None
        self.selected_row_index = None  # Для хранения выбранной строки
        self.current_barcode = None     # Последний отсканированный штрихкод
        self.fbs_df = pd.DataFrame()     # Таблица заказов
        self.marking_db = {}             # База данных артикул+размер -> штрихкод
        self.log_timer_id = None         # Таймер для скрытия лога
        self.input_mode = "barcode"      # "barcode" или "marking" - режим ввода
        self.pending_barcode = None      # для хранения штрихкода между вводами
        self.supplies = []               # Список поставок
        self.selected_supply_id = None   # ID выбранной поставки
        self.api = WildberriesFBSAPI(self.app_context.wb_api_token)
        self.label_printer = LabelPrinter()  # Экземпляр для печати

        # Восстановление данных из контекста приложения
        if hasattr(self.app_context, "fbs_table") and self.app_context.fbs_table is not None:
            self.fbs_df = self.app_context.fbs_table.copy()
            # Добавляем столбец "Статус обработки" если его нет
            if "Статус обработки" not in self.fbs_df.columns:
                self.fbs_df["Статус обработки"] = "Не обработан"
        else:
            self.fbs_df = pd.DataFrame(columns=[
                "Номер заказа", "Маркетплейс", "Покупатель", "Бренд", "Цена",
                "Статус доставки", "Артикул поставщика", "Количество", "Размер",
                "Штрихкод", "Код маркировки", "Номер поставки", "Статус обработки"
            ])

        # Логируем и печатаем id поставки при открытии
        saved_wb_supply_id = getattr(self.app_context, "wb_fbs_supply_id", "")
        print(f"[DEBUG] __init__: подставляю wb_fbs_supply_id = '{saved_wb_supply_id}'")
        # self.show_log(f"Подставляю id поставки: {saved_supply_id}")  # Можно раскомментировать для визуального лога

        self.setup_ui()
        # self.load_supplies()  # Удалено, больше не нужно

    def setup_ui(self):
        """Создаёт интерфейс"""
        # Заголовок
        self.title_label = ctk.CTkLabel(
            self,
            text="ФБС Автосборка",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w"
        )
        self.title_label.pack(anchor="nw", padx=20, pady=(15, 0))

        # --- Блок выбора/создания поставки ---
        self.supply_frame = ctk.CTkFrame(self, fg_color="white", height=56)
        self.supply_frame.pack(fill="x", padx=0, pady=(10, 0))
        self.supply_frame.pack_propagate(False)

        self.supply_label = ctk.CTkLabel(self.supply_frame, text="ID поставки:", font=self.font)
        self.supply_label.pack(side="left", padx=(20, 8), pady=10)

        self.wb_supply_id_var = ctk.StringVar()
        # Восстанавливаем сохранённый id поставки из контекста
        saved_wb_supply_id = getattr(self.app_context, "wb_fbs_supply_id", "")
        self.wb_supply_id_var.set(str(saved_wb_supply_id) if saved_wb_supply_id else "")
        self.wb_supply_id_entry = ctk.CTkEntry(self.supply_frame, textvariable=self.wb_supply_id_var, font=self.font, width=200)
        self.wb_supply_id_entry.pack(side="left", padx=(5, 10), pady=10)
        self.wb_supply_id_entry.bind("<FocusIn>", self.on_wb_supply_entry_focus_in)
        self.wb_supply_id_entry.bind("<FocusOut>", self.on_wb_supply_entry_focus_out)
        self.wb_supply_id_entry.bind("<Return>", self.on_wb_supply_entry_focus_out)
        self.wb_supply_id_entry.bind("<KeyRelease>", self.on_wb_supply_entry_focus_out)

        self.create_supply_btn = ctk.CTkButton(
            self.supply_frame,
            text="Создать поставку",
            font=self.font,
            command=self.open_create_supply_dialog,
            width=160,
            height=36
        )
        self.create_supply_btn.pack(side="left", padx=(0, 20), pady=10)

        self.supply_separator = ctk.CTkFrame(self, height=1, fg_color="#E0E0E0")
        self.supply_separator.pack(fill="x", padx=0, pady=(0, 0))

        # Кнопка загрузки файла
        self.load_button = ctk.CTkButton(
            self,
            text="Загрузить заказы",
            command=self.load_orders
        )
        self.load_button.pack(pady=10)

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

        # Лог сообщений
        self.log_label = ctk.CTkLabel(
            self,
            text="",
            font=("Segoe UI", 14),
            anchor="e",
            padx=10,
            pady=5,
            corner_radius=5,
            fg_color="#CFCFCF",
            text_color="gray20",
        )
        self.log_label.place(relx=1.0, rely=0.0, anchor="ne", x=-15, y=15)
        
        # Привязываем клик для скрытия лога
        self.log_label.bind("<Button-1>", self.hide_log)

        # Контейнер таблицы
        self.table_container = ctk.CTkFrame(self)
        self.table_container.pack(fill="both", expand=True, padx=20, pady=10)

        # Обновляем таблицу
        self.update_table()

        # --- Биндим клик только на self и table_container для сброса выделения ---
        self.bind("<Button-1>", self.on_global_click, add='+')
        self.table_container.bind("<Button-1>", self.on_global_click, add='+')

    def on_global_click(self, event):
        # Если клик был не по таблице — сбрасываем выделение
        if not hasattr(self, 'table') or not hasattr(self.table, 'tree'):
            return
        widget = event.widget
        # Проверяем, что клик был не по Treeview
        if widget is not self.table.tree and not self._is_child_of(widget, self.table.tree):
            self.clear_selection()

    def _is_child_of(self, widget, parent_widget):
        # Проверяет, является ли widget потомком parent_widget
        while widget is not None:
            if widget == parent_widget:
                return True
            widget = widget.master
        return False

    def clear_selection(self):
        # Снимает выделение строки в таблице и сбрасывает selected_row_index
        if hasattr(self, 'table') and hasattr(self.table, 'tree'):
            self.table.tree.selection_remove(self.table.tree.selection())
        self.selected_row_index = None

    def load_orders(self):
        """Загружает заказы из Excel"""
        import tkinter.filedialog as fd
        file_path = fd.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xls")])
        if not file_path:
            return

        try:
            df = pd.read_excel(file_path)
            required_columns = [
                "Номер заказа", "Служба доставки", "Бренд", "Цена",
                "Статус", "Артикул поставщика", "Количество", "Размер"
            ]
            missing_cols = [col for col in required_columns if col not in df.columns]
            if missing_cols:
                self.show_log(f"Ошибка: Отсутствуют столбцы: {', '.join(missing_cols)}", is_error=True)
                return

            # Разбиваем каждую запись на количество
            expanded_rows = []
            for _, row in df.iterrows():
                count = int(row["Количество"])
                for _ in range(count):
                    new_row = row.to_dict()
                    new_row["Количество"] = 1
                    expanded_rows.append(new_row)

            new_df = pd.DataFrame(expanded_rows)

            # Добавляем внутренние поля
            new_df["Штрихкод"] = ""
            new_df["Код маркировки"] = ""
            new_df["Номер поставки"] = ""
            new_df["Статус обработки"] = "Не обработан"

            # Автоматически заполняем штрихкоды из основной базы данных
            if self.app_context.df is not None:
                for idx, row in new_df.iterrows():
                    # Ищем по артикулу и размеру в основной базе
                    matches = self.app_context.df[
                        (self.app_context.df["Артикул производителя"].astype(str) == str(row["Артикул поставщика"])) &
                        (self.app_context.df["Размер"].astype(str) == str(row["Размер"]))
                    ]
                    if not matches.empty:
                        # Берем первый найденный штрихкод
                        barcode = matches.iloc[0]["Штрихкод производителя"]
                        if pd.notna(barcode) and str(barcode).strip() != "":
                            new_df.at[idx, "Штрихкод"] = str(barcode)
                            # Также добавляем в локальную базу
                            key = f"{row['Артикул поставщика']}_{row['Размер']}"
                            self.marking_db[key] = str(barcode)

            # Удаляем дубли по "Номер заказа"
            if not self.fbs_df.empty:
                existing_orders = set(self.fbs_df["Номер заказа"].unique())
                new_df = new_df[~new_df["Номер заказа"].isin(existing_orders)]

            # Объединяем с текущими данными
            if self.fbs_df.empty:
                self.fbs_df = new_df
            else:
                self.fbs_df = pd.concat([self.fbs_df, new_df], ignore_index=True)

            # Сохраняем в контекст
            self.save_data_to_context()

            # Обновляем таблицу
            self.update_table()

            self.show_log(f"Загружено {len(new_df)} новых заказов.")
        except Exception as e:
            self.show_log(f"Ошибка при загрузке файла: {str(e)}", is_error=True)

    def update_table(self):
        """Обновляет таблицу с заказами"""
        # Очищаем предыдущие виджеты
        for widget in self.table_container.winfo_children():
            widget.destroy()

        if self.fbs_df.empty:
            empty_label = ctk.CTkLabel(self.table_container, text="Нет загруженных заказов", font=("Segoe UI", 14))
            empty_label.pack(pady=20)
            return

        # Используем EditableDataTable
        self.table = EditableDataTable(
            self.table_container,
            dataframe=self.fbs_df,
            max_rows=5000,
            header_font=("Segoe UI", 14, "bold"),
            cell_font=("Segoe UI", 14),
            readonly=False,
            on_edit_start=self.on_edit_start,
            on_edit_end=self.on_edit_end
        )
        self.table.pack(fill="both", expand=True)

        # Цветовая индикация строк (через Treeview внутри EditableDataTable)
        tree = self.table.tree
        for idx, row in self.fbs_df.iterrows():
            tag = self.get_row_status(row)
            tree.item(str(idx), tags=(tag,))
        tree.tag_configure("found", background="#FFFACD")  # Желтый - найден штрихкод или товар в БД
        tree.tag_configure("missing", background="#FFB6C1")  # Красный - товар не найден в БД
        tree.tag_configure("completed", background="#90EE90")  # Зеленый - есть и штрихкод, и маркировка

        # Привязываем выделение строки
        tree.bind("<<TreeviewSelect>>", self.on_row_select)

    def on_row_select(self, event=None):
        """Обработчик выбора строки"""
        tree = self.table.tree
        selected_items = tree.selection()
        if not selected_items:
            self.selected_row_index = None
            return

        item = selected_items[0]
        index = int(item)
        self.selected_row_index = index
        row = self.fbs_df.loc[index]

    def get_row_status(self, row):
        """Определяет статус строки для цветовой индикации"""
        # Если товар обработан - зеленый (независимо от наличия маркировки)
        if "Статус обработки" in row and row["Статус обработки"] == "Обработан":
            return "completed"  # Зеленый цвет для обработанных заказов
        
        # Если есть и штрихкод, и код маркировки - зеленый
        if row["Штрихкод"] != "" and row["Код маркировки"] != "":
            return "completed"  # Зеленый цвет для завершенных заказов
        
        # Если есть только штрихкод - желтый
        if row["Штрихкод"] != "":
            return "found"  # Желтый цвет для найденных штрихкодов
        
        # Проверяем наличие в основной базе данных
        if self.app_context.df is not None:
            matches = self.app_context.df[
                (self.app_context.df["Артикул производителя"].astype(str) == str(row["Артикул поставщика"])) &
                (self.app_context.df["Размер"].astype(str) == str(row["Размер"]))
            ]
            if not matches.empty:
                return "found"
        
        # Проверяем в локальной базе
        key = f"{row['Артикул поставщика']}_{row['Размер']}"
        if key in self.marking_db:
            return "found"
        
        return "missing"

    def handle_barcode(self, event=None):
        """Обрабатывает ввод штрихкода и кода маркировки"""
        input_value = self.scan_entry.get().strip()
        if self.input_mode == "barcode":
            # Первый этап: ввод штрихкода
            self.handle_barcode_input(input_value)
        else:
            # Второй этап: ввод кода маркировки
            self.handle_marking_input(input_value)

    def handle_barcode_input(self, barcode):
        """ Обрабатывает ввод штрихкода """
        if self.selected_row_index is not None:
            # Если выбрана строка, привязываем штрихкод к ней
            row = self.fbs_df.loc[self.selected_row_index]
            key = f"{row['Артикул поставщика']}_{row['Размер']}"
            
            # Сохраняем штрихкод
            self.marking_db[key] = barcode
            self.fbs_df.at[self.selected_row_index, "Штрихкод"] = barcode
            
            # Сохраняем в основную базу данных
            self.save_to_main_database(row, barcode)
            
            # Сохраняем данные в контекст
            self.save_data_to_context()
            
            play_success_scan_sound()
            self.show_log(f"✅ Штрихкод {barcode} привязан. Теперь введите код маркировки...")
            
            # Переключаемся на ввод маркировки
            self.input_mode = "marking"
            self.pending_barcode = barcode
            self.scanning_label.configure(text="Введите код маркировки... 🏷️")
            
            # Очищаем поле ввода
            self.scan_entry.delete(0, "end")
            self.restore_entry_focus()     
        else:
            if not str(barcode).strip():
                self.show_log("Ошибка: Штрихкод не введен", is_error=True)
                play_unsuccess_scan_sound()
                return
            
            # Если строка не выбрана, ищем по штрихкоду
            matches = self.fbs_df[self.fbs_df["Штрихкод"] == barcode]
            if not matches.empty:
                # Выбираем найденную строку
                for ind in range(len(matches.index)):
                    self.selected_row_index = matches.index[ind]
                    row = self.fbs_df.loc[self.selected_row_index]
                    
                    # Если товар уже обработан, идем дальше
                    if "Статус обработки" in row and row["Статус обработки"] == "Обработан":
                        pass
                    else:
                        # Если у строки уже есть код маркировки, показываем информацию
                        if row["Код маркировки"] != "":
                            self.show_log(f"Найдена строка: Заказ {row['Номер заказа']}, маркировка: {row['Код маркировки']}")
                            self.selected_row_index = None
                        else:
                            # Запрашиваем код маркировки
                            self.input_mode = "marking"
                            self.pending_barcode = barcode
                            self.scanning_label.configure(text="Введите код маркировки... 🏷️")
                            self.show_log(f"Найдена строка: Заказ {row['Номер заказа']}. Введите код маркировки...")
                        self.scan_entry.delete(0, "end")
                        self.restore_entry_focus()
                        return
                
                self.show_log("Срока уже обработана");
                self.scan_entry.delete(0, "end")
                self.restore_entry_focus()
                self.selected_row_index = None
            else:
                self.show_log("Ошибка: Штрихкод не найден в заказах", is_error=True)
                play_unsuccess_scan_sound()

    def handle_marking_input(self, marking_code):
        """Обрабатывает ввод кода маркировки"""
        if self.selected_row_index is not None:
            # Записываем код маркировки в таблицу
            self.fbs_df.at[self.selected_row_index, "Код маркировки"] = marking_code
            
            # Печатаем этикетку
            row = self.fbs_df.loc[self.selected_row_index]

            # --- Получаем и сохраняем стикер заказа через API ---
            try:
                order_id = row["Номер заказа"]
                stickers_response = self.api.get_stickers([order_id], type="png", width=58, height=40)
                import base64
                stickers = stickers_response.get('stickers')
                if stickers and isinstance(stickers, list) and 'file' in stickers[0]:
                    b64data = stickers[0]['file']
                    img_bytes = base64.b64decode(b64data)
                    filename = f"sticker_{order_id}.png"
                    with open(filename, "wb") as f:
                        f.write(img_bytes)
                    self.show_log(f"Стикер заказа сохранён: {filename}")
                    # --- Печать этикетки ---
                    self.label_printer.print_on_windows(image_path=filename)
                else:
                    self.show_log("Не удалось получить стикер заказа", is_error=True)
            except Exception as e:
                self.show_log(f"Ошибка при получении стикера: {e}", is_error=True)

            # Помечаем товар как обработанный
            self.fbs_df.at[self.selected_row_index, "Статус обработки"] = "Обработан"
            
            # Сохраняем данные в контекст
            self.save_data_to_context()
            
            play_success_scan_sound()
            self.show_log(f"✅ Код маркировки {marking_code} привязан к заказу {row['Номер заказа']}")
            
            # Обновляем таблицу
            self.update_table()
            
            # Сбрасываем состояние
            self.selected_row_index = None
            self.input_mode = "barcode"
            self.pending_barcode = None
            self.scanning_label.configure(text="Ожидание сканирования... 📱")
            
            self.scan_entry.delete(0, "end")
            self.restore_entry_focus()
        else:
            self.show_log("Ошибка: Не выбрана строка для маркировки", is_error=True)
            play_unsuccess_scan_sound()

    def save_to_main_database(self, row, barcode):
        """Сохраняет штрихкод в основную базу данных"""
        if self.app_context.df is None:
            return
            
        # Ищем существующую запись
        matches = self.app_context.df[
            (self.app_context.df["Артикул производителя"].astype(str) == str(row["Артикул поставщика"])) &
            (self.app_context.df["Размер"].astype(str) == str(row["Размер"]))
        ]
        
        if not matches.empty:
            # Обновляем существующую запись
            idx = matches.index[0]
            self.app_context.df.at[idx, "Штрихкод производителя"] = barcode
        else:
            # Создаем новую запись
            new_row = pd.DataFrame([{
                "Артикул производителя": row["Артикул поставщика"],
                "Размер": row["Размер"],
                "Штрихкод производителя": barcode,
                "Наименование поставщика": row.get("Бренд", ""),
                "Бренд": row.get("Бренд", "")
            }])
            self.app_context.df = pd.concat([self.app_context.df, new_row], ignore_index=True)

    def save_to_database(self):
        """Сохраняет данные в основную базу данных"""
        if self.app_context.df is None:
            messagebox.showwarning("Ошибка", "Сначала загрузите основную базу данных.")
            return
            
        try:
            # Сохраняем в Excel файл
            if self.app_context.file_path:
                self.app_context.df.to_excel(self.app_context.file_path, index=False)
                self.show_log("✅ Данные сохранены в основную базу")
            else:
                self.show_log("⚠️ Путь к файлу не указан", is_error=True)
        except Exception as e:
            self.show_log(f"❌ Ошибка сохранения: {str(e)}", is_error=True)

    def show_log(self, message, is_error=False):
        """Отображает сообщение в логе с автоматическим скрытием"""
        # Отменяем предыдущий таймер
        if self.log_timer_id:
            self.after_cancel(self.log_timer_id)
        
        # Настраиваем цвет в зависимости от типа сообщения
        if is_error:
            self.log_label.configure(
                text=message,
                fg_color="#FFE0E0",
                text_color="red"
            )
        else:
            self.log_label.configure(
                text=message,
                fg_color="gray85",
                text_color="gray20"
            )
        
        self.log_label.lift()
        
        # Устанавливаем таймер для автоматического скрытия
        if is_error:
            # Ошибки скрываются через 5 секунд
            self.log_timer_id = self.after(5000, self.hide_log)
        else:
            # Обычные сообщения скрываются через 3 секунды
            self.log_timer_id = self.after(3000, self.hide_log)

    def hide_log(self, event=None):
        """Скрывает лог сообщений"""
        self.log_label.configure(text="", fg_color="#CFCFCF")
        if self.log_timer_id:
            self.after_cancel(self.log_timer_id)
            self.log_timer_id = None

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

    def reset_clear_timer(self, event=None):
        if self.clear_timer_id:
            self.after_cancel(self.clear_timer_id)
        self.clear_timer_id = self.after(1000, self.clear_entry)

    def clear_entry(self):
        self.scan_entry.delete(0, "end")

    def handle_keypress(self, event=None):
        if self.table:
            self.table.on_keypress(event)

    def on_edit_start(self):
        self.editing = True
        if self.focus_timer_id:
            self.after_cancel(self.focus_timer_id)

    def on_edit_end(self):
        self.editing = False
        # Сохраняем изменения в self.fbs_df и контекст
        self.fbs_df = self.table.displayed_df.copy()
        self.save_data_to_context()
        self.start_auto_focus()

    def start_auto_focus(self):
        if self.focus_timer_id:
            self.after_cancel(self.focus_timer_id)
        self.restore_entry_focus()

    def save_data_to_context(self):
        """Сохраняет данные в контекст приложения"""
        try:
            self.app_context.fbs_table = self.fbs_df.copy()
            wb_supply_id = self.wb_supply_id_entry.get().strip()
            print(f"[DEBUG] save_data_to_context: сохраняю wb_fbs_supply_id = '{wb_supply_id}'")
            self.show_log(f"Сохраняю id поставки WB: {wb_supply_id}")
            self.app_context.wb_fbs_supply_id = wb_supply_id
        except Exception as e:
            self.show_log(f"Ошибка сохранения: {str(e)}", is_error=True)

    # Удаляю функцию load_supplies и все её вызовы
    # После создания поставки сохраняю id сразу
    def open_create_supply_dialog(self):
        self.editing = True
        default_name = f"Поставка от {datetime.now().strftime('%d.%m.%Y')}"
        import easygui as eg
        name = eg.enterbox("Создать поставку", "Введите имя поставки:", default=default_name)
        if name:
            result = self.create_supply(name)
            if result and 'id' in result:
                self.wb_supply_id_var.set(str(result['id']))
                self.save_data_to_context()  # Сохраняем сразу после создания
        self.editing = False
        self.start_auto_focus()

    def create_supply(self, name):
        try:
            result = self.api.create_supply(name)
            self.show_log(f"Поставка создана: {result.get('name', name)}")
            return result
        except Exception as e:
            self.show_log(f"Ошибка создания поставки: {e}", is_error=True)
            return None

    def on_wb_supply_entry_focus_in(self, event=None):
        self.editing = True

    def on_wb_supply_entry_focus_out(self, event=None):
        self.editing = False
        self.start_auto_focus()
