from typing import Dict, List, Optional
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
from ozon_fbs_api import OzonFBSAPI # НОВЫЙ ИМПОРТ

class OrderAssemblyState:
    """Отслеживает состояние сборки многотоварного заказа Ozon."""

    def __init__(self, posting_number, products: List[Dict]):
        self.posting_number = posting_number
        self.total_products = len(products)
        self.products = []
        self.is_complete = False

        # Разворачиваем список товаров в плоский список для отслеживания
        for p in products:
            for _ in range(p['quantity']):
                # product_id должен быть реальным ID товара на Ozon
                self.products.append({
                    'product_id': p['product_id'],
                    'name': p['name'],
                    'is_marked': p.get('is_marked', True),
                    'scanned_barcode': None,
                    'scanned_cis': None,
                    'is_processed': False,
                })

    def scan_item(self, barcode: str) -> Optional[Dict]:
        """Находит первый несобранный товар по штрихкоду и отмечает его."""
        for item in self.products:
            if not item['is_processed'] and item.get('scanned_barcode') is None:
                item['scanned_barcode'] = barcode
                return item
        return None

    def scan_cis(self, cis_code: str, item_to_mark: Dict):
        """Добавляет код маркировки и отмечает товар как полностью собранный."""
        if item_to_mark:
            item_to_mark['scanned_cis'] = cis_code
            item_to_mark['is_processed'] = True

            # Проверяем, собран ли весь заказ
            if all(item['is_processed'] for item in self.products):
                self.is_complete = True
            return True
        return False

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
        # НОВЫЕ АТРИБУТЫ
        self.api_ozon = OzonFBSAPI(self.app_context.ozon_client_id, self.app_context.ozon_api_key)
        self.label_printer = LabelPrinter(printer_name=self.app_context.printer_name)
        self.active_ozon_assembly: Optional[OrderAssemblyState] = None
        self.current_item_to_mark: Optional[Dict] = None
        # self.label_printer = None  # Экземпляр заглушка для печати


        # Восстановление данных из контекста приложения
        if hasattr(self.app_context, "fbs_table") and self.app_context.fbs_table is not None:
            self.fbs_df = self.app_context.fbs_table.copy()
            # Добавляем столбец "Статус обработки" если его нет
            if "Статус обработки" not in self.fbs_df.columns:
                self.fbs_df["Статус обработки"] = "Не обработан"
        else:
            self.fbs_df = pd.DataFrame(columns=[
                "Номер заказа", "Служба доставки", "Покупатель", "Бренд", "Цена",
                "Статус доставки", "Артикул поставщика", "Количество", "Размер",
                "Штрихкод", "Код маркировки", "Номер поставки", "Статус обработки"
            ])

        # Логируем и печатаем id поставки при открытии
        saved_wb_supply_id = getattr(self.app_context, "wb_fbs_supply_id", "")
        print(f"[DEBUG] __init__: подставляю wb_fbs_supply_id = '{saved_wb_supply_id}'")
        # self.show_log(f"Подставляю id поставки: {saved_wb_supply_id}")  # Можно раскомментировать для визуального лога

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
            return "found"  # Желтый цвет для найденных штрих кодов
        
        # Проверяем наличие в основной базе данных !!! Этот участок надо потестить !!!
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

    def handle_barcode_input_old(self, barcode):
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


    ## Новый метод handle_barcode_input(self, barcode)
    def handle_barcode_input(self, barcode):
        """
        Обрабатывает ввод штрихкода.
        Диспетчер для логики сборки WB и Ozon.
        """
        self.editing = True
        self.current_barcode = barcode.strip()
        if not self.current_barcode:
            self.show_log("❌ Ошибка: Введите штрихкод.", is_error=True)
            self.editing = False
            self.start_auto_focus()
            play_unsuccess_scan_sound()
            return

        self.show_log(f"Сканирование: {self.current_barcode}")

        # 1. Поиск по штрихкоду в таблице FBS
        matches = self.fbs_df[self.fbs_df["Штрихкод"] == barcode]
        if matches.empty:
            self.show_log("Ошибка: Штрихкод не найден в загруженных заказах", is_error=True)
            play_unsuccess_scan_sound()
            return

        first_match = matches.iloc[0]
        marketplace = first_match["Служба доставки"]
        posting_number = first_match["Номер заказа"]

        # --- ЛОГИКА Ozon: МНОГОТОВАРНАЯ СБОРКА ---
        if "ozon" in marketplace.lower():

            # 3. Инициализация состояния сборки Ozon
            if self.active_ozon_assembly is None or self.active_ozon_assembly.posting_number != posting_number:
                # Собрать все строки, относящиеся к этому заказу
                order_rows = self.fbs_df[self.fbs_df["Номер заказа"] == posting_number]
                # Создание списка товаров для OrderAssemblyState (quantity = 1 для каждой строки DF)
                products_list = [
                    {'product_id': row["Артикул поставщика"],  # Используем артикул как Product ID для имитации
                     'name': row["Бренд"],
                     'quantity': 1,
                     'is_marked': row.get("Требует маркировки", True)  # Предполагаем наличие колонки
                     }
                    for idx, row in order_rows.iterrows()
                ]
                # Создаем менеджер состояния
                self.active_ozon_assembly = OrderAssemblyState(posting_number, products_list)
                self.show_log(
                    f"Начата сборка заказа Ozon {posting_number}. Всего товаров: {self.active_ozon_assembly.total_products}")

            # 4. Сканируем товар внутри заказа
            item_to_mark = self.active_ozon_assembly.scan_item(self.current_barcode)

            if item_to_mark:
                if item_to_mark['is_marked']:
                    # Если требуется маркировка - переходим в режим КИЗ
                    self.current_item_to_mark = item_to_mark
                    self.input_mode = "marking"
                    self.scanning_label.configure(text=f"Введите КИЗ для: {item_to_mark['name']} 🏷️")
                    self.show_log(f"Товар {item_to_mark['name']} отсканирован. Ожидание КИЗ.")
                else:
                    # Если не требуется маркировка - товар считается собранным
                    self.active_ozon_assembly.scan_cis(cis_code="N/A",
                                                       item_to_mark=item_to_mark)  # Отмечаем как собранный
                    self.show_log(f"Товар {item_to_mark['name']} отсканирован. Маркировка не требуется.")

                    if self.active_ozon_assembly.is_complete:
                        self.show_log(f"🎉 Заказ Ozon {posting_number} полностью собран.")
                        self.finalize_ozon_assembly(posting_number)
                    else:
                        self.show_log(f"Продолжайте сканирование товаров для заказа Ozon {posting_number}.")
                        play_success_scan_sound()
            else:
                self.show_log(f"Заказ Ozon {posting_number} уже собран или товар не найден.", is_error=True)
                self.finalize_ozon_assembly(posting_number)  # Повторная попытка печати, если заказ собран.

            self.scan_entry.delete(0, "end")
            self.restore_entry_focus()
            self.editing = False
            self.start_auto_focus()
            return

        # --- ЛОГИКА Wildberries: ОДНОТОВАРНАЯ СБОРКА ---
        elif "wildberries" in marketplace.lower():

            # 5. Поиск необработанной строки WB для маркировки
            for ind in range(len(matches.index)):
                self.selected_row_index = matches.index[ind]
                row = self.fbs_df.loc[self.selected_row_index]

                # Находим необработанную строку без кода маркировки
                if row["Статус обработки"] != "Обработан" and row["Код маркировки"] == "":

                    if row.get("Требует маркировки", True):  # Проверка, что товар маркированный
                        self.input_mode = "marking"
                        self.pending_barcode = self.current_barcode
                        self.scanning_label.configure(text="Введите код маркировки... 🏷️")
                        self.show_log(f"Найдена строка WB: Заказ {row['Номер заказа']}. Введите код маркировки...")
                    else:
                        # Если маркировка не нужна, сразу финализируем и печатаем
                        self.fbs_df.at[self.selected_row_index, "Код маркировки"] = "N/A"
                        self.finalize_wb_assembly(row)
                        self.selected_row_index = None  # Сброс, т.к. работа закончена
                        self.show_log(f"Заказ WB {row['Номер заказа']} собран и отправлен на печать.")

                    self.scan_entry.delete(0, "end")
                    self.restore_entry_focus()
                    self.editing = False
                    self.start_auto_focus()
                    return

            self.show_log("Строка уже обработана или не требует маркировки.", is_error=True)
            self.scan_entry.delete(0, "end")
            self.restore_entry_focus()
            self.editing = False
            self.start_auto_focus()
            self.selected_row_index = None
            return


    def handle_marking_input(self, marking_code):
        """Обрабатывает ввод кода маркировки (КИЗ)"""

        # --- ЛОГИКА Ozon: МНОГОТОВАРНЫЙ ЗАКАЗ ---
        if self.active_ozon_assembly and self.current_item_to_mark:
            posting_number = self.active_ozon_assembly.posting_number
            item = self.current_item_to_mark

            # 1. Записать КИЗ в Ozon API
            try:
                # product_id = item['product_id']
                # В реальном коде product_id нужно получить из Ozon API,
                # здесь используем заглушку, т.к. DF не содержит Ozon Product ID
                self.api_ozon.set_product_marking_code(
                    posting_number=posting_number,
                    product_id=int(item['product_id']),
                    cis_code=marking_code
                )
                self.show_log(f"✅ КИЗ {marking_code[:10]}... отправлен в Ozon для {item['name']}.")
            except Exception as e:
                self.show_log(f"❌ Ошибка Ozon API при отправке КИЗ: {e}", is_error=True)

            # 2. Обновить локальное состояние
            self.active_ozon_assembly.scan_cis(marking_code, item)
            self.current_item_to_mark = None

            if self.active_ozon_assembly.is_complete:
                # Полная сборка - переводим в статус и печатаем этикетку
                self.show_log(f"🎉 Заказ Ozon {posting_number} полностью собран.")
                self.finalize_ozon_assembly(posting_number)
            else:
                self.show_log(f"Продолжайте сканирование товаров для заказа Ozon {posting_number}.")
                self.input_mode = "barcode"
                self.scanning_label.configure(text="Ожидание сканирования... 📱")

            self.scan_entry.delete(0, "end")
            self.restore_entry_focus()
            self.update_table()
            return

        # --- ЛОГИКА Wildberries (EXISTING) ---
        elif self.selected_row_index is not None:
            # Записываем код маркировки в таблицу
            self.fbs_df.at[self.selected_row_index, "Код маркировки"] = marking_code
            
            # Печатаем этикетку
            row = self.fbs_df.loc[self.selected_row_index]

            self.finalize_wb_assembly(row) # НОВЫЙ ВЫЗОВ

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

    # В конец класса FBSMode
        # fbs_autosborka_gui.py

    def finalize_ozon_assembly(self, posting_number: str):
        """
        Финализирует сборку Ozon: переводит заказ в статус 'Собрано'
        и печатает этикетку.
        """
        self.show_log(f"Ozon: Финализация сборки заказа {posting_number}...")

        # Получаем IP/Port принтера из контекста (важно для ZPL-печати)
        # Получение целевого принтера из контекста приложения
        printer_target = self.app_context.printer_name

        # 1. Вызов API: Перевод заказа в статус "Собрано" (Ready for shipment)
        try:
            # Используем КОРРЕКТНЫЙ метод, который принимает список номеров
            self.ozon_api.set_posted_status_to_ready_for_shipment([posting_number])
            self.show_log(f"✅ Ozon API: Заказ {posting_number} переведен в статус 'Собрано'.")
        except Exception as e:
            self.show_log(f"❌ Ozon API Ошибка: Не удалось перевести заказ {posting_number} в статус 'Собрано': {e}",
                          is_error=True)
            play_unsuccess_scan_sound()
            return  # Выходим при ошибке статуса

        # 2. Получение и печать этикетки Ozon (Base64 PDF)
        try:
            self.show_log(f"Ozon API: Запрос этикетки для {posting_number}...")
            label_base64_data = self.ozon_api.get_stickers(posting_number)

            if not label_base64_data:
                self.show_log("❌ Ozon API не вернул данные этикетки.", is_error=True)
                play_unsuccess_scan_sound()
                return

            # print_wb_ozon_label должен обрабатывать Base64-PDF для Ozon
            if self.label_printer.print_wb_ozon_label(label_base64_data, printer_target):
                self.show_log(
                    f"✅ Этикетка Ozon для {posting_number} успешно отправлена на печать на принтер: {printer_target}.")
            else:
                self.show_log("❌ Печать этикетки Ozon не удалась. Проверьте принтер или соединение.", is_error=True)

        except Exception as e:
            self.show_log(f"❌ Ошибка получения или печати этикетки Ozon: {e}", is_error=True)
            play_unsuccess_scan_sound()

        # 3. Сброс состояния сборки (Критически важно для следующего заказа!)
        self.current_assembly_state = None

        # 4. Обновление UI и звуковое оповещение
        self.update_table()
        play_success_scan_sound()

    def finalize_wb_assembly(self, row):
        """Финализирует Wildberries заказ и печатает этикетку ZPL."""

        order_id = row["Номер заказа"]

        # 1. Получение целевого принтера из контекста приложения
        # Используем имя выбранного локального принтера.
        # printer_target = getattr(self.app_context, "printer_name", "по умолчанию")
        printer_target = self.app_context.printer_name

        # --- 1. ДОБАВЛЕНИЕ ЗАКАЗА В ПОСТАВКУ ---
        supply_id = self.selected_supply_id
        if not supply_id:
            self.show_log("❌ Ошибка WB: Не выбрана активная поставка!", is_error=True)
            play_unsuccess_scan_sound()
            return

        # 1.1 Добавление заказа в поставку (критический шаг для WB)
        try:
            self.show_log(f"WB API: Добавление заказа {order_id} в поставку {supply_id}...")
            self.api.add_orders_to_supply(supply_id, [order_id])
            self.show_log(f"✅ Заказ {order_id} успешно добавлен в поставку.")
        except Exception as e:
            self.show_log(f"❌ Ошибка добавления заказа {order_id} в поставку: {e}", is_error=True)
            play_unsuccess_scan_sound()
            return

        # 2. Получение и прямая ZPL печать этикетки
        try:
            self.show_log("WB API: Запрос ZPL этикетки...")
            # Запрашиваем стикер в формате ZPL
            stickers_response = self.api.get_stickers([order_id], type="zpl", width=58, height=40)

            stickers = stickers_response.get('stickers')

            # Проверка, что стикер получен и содержит данные
            if stickers and isinstance(stickers, list) and 'file' in stickers[0]:
                # 'file' содержит Base64-строку ZPL-кода
                label_base64_data = stickers[0]['file']

                # print_wb_ozon_label сам определяет, что это ZPL, и отправит его на печать.
                if self.label_printer.print_wb_ozon_label(label_base64_data, printer_target):
                    self.show_log(
                        f"✅ Этикетка WB для {order_id} успешно отправлена на ZPL-печать на принтер: {printer_target}.")
                else:
                    self.show_log("❌ Прямая ZPL-печать не удалась. Проверьте соединение с принтером или его имя.",
                                  is_error=True)
            else:
                self.show_log("❌ WB API не вернул данные этикетки в ожидаемом формате.", is_error=True)

        except Exception as e:
            self.show_log(f"❌ Критическая ошибка при работе с WB API или печати: {e}", is_error=True)