from ozon_fbs_api import OzonFBSAPI
from typing import Dict, List, Optional
import pandas as pd
# import numpy as np
import customtkinter as ctk
import os
import re
from datetime import datetime
from tkinter import messagebox
import tkinter.filedialog as fd
import easygui as eg
from pandas.core.interchange.dataframe_protocol import DataFrame
from sound_player import play_success_scan_sound, play_unsuccess_scan_sound
from gui.gui_table import EditableDataTable
from printer_handler import LabelPrinter
import logging
import ast
from db_manager import DBManager
from gui.fbs_union_gui import UnionMark

# Создаем логгер для конкретного модуля
logger = logging.getLogger(__name__)
# from test_generate import generate_honest_sign_code as ghsc


# Переменная для хранения имени файла с новыми ШК
NEW_BARCODES_FILE = "new_barcodes.csv"

class FBSModeOzon(ctk.CTkFrame, UnionMark):
    """
    Виджет для сборки заказов Ozon (FBS).
    Включает логику сканирования, ручной сборки, создания поставки и печати этикеток.
    """

    def __init__(self, parent, font, app_context):
        super().__init__(parent)
        self.font = font
        self.app_context = app_context
        self.pattern = r'^WB-GI-[0-9]+$'
        self.marketplace = 'Ozon'
        self.editing = False
        self.input_mode = "barcode"  # "barcode" или "marking" - режим ввода
        self.focus_timer_id = None
        self.clear_timer_id = None
        self.current_barcode = None
        self.marking_db = {}  # База данных артикул+размер -> штрихкод
        self.print_capability = True
        self.related_rows = []
        self.flag_upd = False
        self.select_barcode_update = False
        self.columns = [
            "Номер заказа", "Номер отправления", "Служба доставки", "Бренд", "Цена",
            "Артикул поставщика", "Количество", "Размер", "Наименование",
            "Штрихкод", "Штрихкод Ozon", "Код маркировки", "sku", "product_id",
            "Статус заказа", "Подстатус", "Статус обработки", "is_express" # is_express будет скрыт или служебным
        ]
        self.define_status = ('indefinite', # - неопределено
                              'awaiting_registration', #  — ожидает регистрации,
                              'acceptance_in_progress', # — идёт приёмка,
                              'awaiting_approve', # — ожидает подтверждения,
                              'awaiting_packaging', # — ожидает упаковки,
                              'awaiting_deliver', # — ожидает отгрузки,
                              'arbitration', # — арбитраж,
                              'client_arbitration', #— клиентский арбитраж доставки,
                              'delivering', # — доставляется,
                              'driver_pickup', # — у водителя,
                              'cancelled', # — отменено,
                              'not_accepted', # — не принят на сортировочном центре.
                              'awaiting_verification')
        self.assembly_status = ("Не обработан", "Обработан")
        # --- Данные ---
        # 1. Создаем целевой DF с необходимыми колонками, инициализированный пустыми строками
        self.fbs_df = pd.DataFrame(columns=self.columns)
        if self.marketplace == 'Ozon':
            if hasattr(self.app_context, "fbs_table_ozon") and self.app_context.fbs_table_ozon is not None:
                df = self.app_context.fbs_table_ozon.copy()
                # self.debug_print_first_row(df)
                # 2. Фильтрация по Ozon
                filtered_df = df[
                    df['Служба доставки'].astype(str).str.contains(self.marketplace, na=False)
                ].copy()

                # 3. Выравниваем колонки отфильтрованного DF по целевым колонкам.
                #    Колонки, которых нет в filtered_df, будут заполнены NaN (или '')
                #    Мы используем reindex, чтобы гарантировать, что все строки имеют нужные колонки
                if not filtered_df.empty:
                    # Берем только существующие колонки из self.columns
                    existing_cols_in_filtered_df = [col for col in self.columns if col in filtered_df.columns]

                    # Создаем временный DF, который будет содержать данные только по существующим колонкам
                    temp_df = filtered_df[existing_cols_in_filtered_df].copy()

                    # Добавляем все недостающие колонки и выравниваем индекс
                    self.fbs_df = temp_df.reindex(columns=self.columns)

                    # 💡 ИСПРАВЛЕНИЕ WARNING 1: Приводим все колонки к строковому типу перед заполнением
                    # Это позволяет безопасно хранить строки и NaN, устраняя FutureWarning.
                    for col in self.fbs_df.columns:
                        self.fbs_df[col] = self.fbs_df[col].astype(object)

                    # Pandas по умолчанию заполняет новые колонки NaN. Заменяем NaN на пустые строки
                    self.fbs_df.fillna('', inplace=True)

                # 4. Установка значения по умолчанию для "Статус заказа"
                #    (Этот статус мог быть потерян при reindex, если он не существовал в исходном DF,
                #    но должен быть добавлен после создания структуры)
                if "Статус заказа" in self.fbs_df.columns:
                    # Заполняем пустые значения в 'Статус заказа' значением
                    self.fbs_df["Статус заказа"] = self.fbs_df["Статус заказа"].replace({'': self.define_status[0]})

        self.current_orders_df = None  # Заказы, загруженные из API
        self.ozon_marking_db = self._load_new_barcodes()  # База данных артикул+размер -> штрихкод
        self.api = OzonFBSAPI(self.app_context.ozon_client_id, self.app_context.ozon_api_key)
        self.label_printer = LabelPrinter(self.app_context.printer_name)

        # --- Настройки поставки OZON ---
        self.wb_supply_id_var = getattr(self.app_context, "ozon_fbs_order_id", "")

        # --- UI элементы ---
        self.scan_entry = None
        self.scan_entry2 = None
        self.cis_entry = None
        self.table_frame = None
        self.data_table = None
        self.log_label = None
        self.assembly_button = None
        self.print_button = None
        self.transfer_button = None
        self.transfer_button2 = None
        self.supply_combobox = None
        self.selected_row_index = None  # Для хранения выбранной строки
        self.table_label = None
        self.check_var = ctk.BooleanVar(value=True)
        self.checkbox = None
        self.checkbox2 = None
        self.assign_product = None
        self.smart_mode_var = ctk.BooleanVar(value=True)
        self.select_barcode_update = ctk.BooleanVar(value=True)
        self.db = DBManager()
        # self.db.init_tables()
        self.setup_ui()

        self.show_log(f"Подставлен ID текушего заказа OZON: {self.wb_supply_id_var}")

    def _load_new_barcodes(self, filename=NEW_BARCODES_FILE) -> pd.DataFrame:
        """Загружает новые добавленные штрихкоды из отдельного CSV-файла."""
        if os.path.exists(filename):
            try:
                # Читаем с правильными типами и возвращаем DataFrame
                return pd.read_csv(filename,
                                   dtype={'Артикул производителя': str, 'Штрихкод производителя': str}).fillna('')
            except Exception as e:
                self.show_log(f"❌ Ошибка загрузки базы новых ШК: {e}", is_error=True)
                return pd.DataFrame(columns=['Артикул производителя', 'Штрихкод производителя', 'Штрихкод OZON'])
        return pd.DataFrame(columns=['Артикул производителя', 'Штрихкод производителя', 'Штрихкод OZON'])

    def _save_new_barcodes(self):
        """Сохраняет обновленный DataFrame с новыми штрихкодами."""
        try:
            self.ozon_marking_db.to_csv(NEW_BARCODES_FILE, index=False, mode='w')
        except Exception as e:
            self.show_log(f"❌ Ошибка сохранения новых ШК: {e}", is_error=True)

    def update_supply_id(self, *args):
        """Обрабатывает изменение ID поставки (ручное или через комбобокс)."""
        new_id = self.wb_supply_id_var.get().strip()
        setattr(self.app_context, "ozon_fbs_order_id", new_id)
        self._update_print_button_state()
        self.show_log(f"ID поставки обновлен: {new_id}")

    def setup_ui(self):
        """Создаёт интерфейс Ozon FBS ."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)  # Панель управления справа
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        # --- Левая часть: Таблица и Лог ---
        mrow = 0
        main_frame = ctk.CTkFrame(self)
        main_frame.grid(row=mrow, column=0, sticky="nsew", padx=10, pady=10)
        main_frame.grid_rowconfigure(mrow, weight=0)
        main_frame.grid_columnconfigure(mrow, weight=1)

        # Верхнее окно сканирования
        ctk.CTkLabel(main_frame, text="Автосборка:",
                     font=ctk.CTkFont(size=16, weight="bold")  # self.font
                     ).grid(row=mrow, column=0, padx=10, pady=(0, 0))
        mrow += 1
        main_frame.grid_rowconfigure(mrow, weight=0)

        # self.scan_entry = ctk.CTkEntry(main_frame, width=300, font=self.font)
        # self.scan_entry.grid(row=mrow, column=0, padx=0, pady=(0, 0))
        # self.scan_entry.bind('<Return>',
        #                      lambda event: self.handle_barcode_input_auto_smart(self.scan_entry.get()))
        # === НАЧАЛО ИЗМЕНЕНИЙ ===
        # Создаем контейнер для строки ввода и чекбокса, чтобы они были рядом
        input_container = ctk.CTkFrame(main_frame, fg_color="transparent")
        input_container.grid(row=mrow, column=0,  padx=10, pady=(0, 0)) # sticky="ew",

        # Поле ввода (теперь внутри контейнера)
        self.scan_entry = ctk.CTkEntry(input_container, width=300, font=self.font)
        self.scan_entry.pack(side="left", padx=(0, 10))  # pack side="left" ставит их в ряд

        # Чекбокс "smart" справа от поля ввода
        self.smart_checkbox = ctk.CTkCheckBox(input_container, text="smart",
                                              variable=self.smart_mode_var,
                                              font=("Segoe UI", 12))
        self.smart_checkbox.pack(side="left")

        # Привязка Enter к функции-распределителю
        self.scan_entry.bind('<Return>', self._on_scan_enter)

        # === КОНЕЦ ИЗМЕНЕНИЙ ===
        self.scan_entry.bind("<KeyRelease>", self.reset_clear_timer)
        self.scan_entry.bind("<FocusIn>", self.on_entry_focus_in)
        self.scan_entry.bind("<FocusOut>", self.on_entry_focus_out)
        self.scan_entry.bind("<KeyPress>", self.handle_keypress)
        # self.restore_entry_focus()

        mrow += 1
        main_frame.grid_rowconfigure(mrow, weight=1)

        # Таблица
        self.table_frame = ctk.CTkFrame(main_frame)
        self.table_frame.grid(row=mrow, column=0, sticky="nsew", padx=5, pady=5)
        self.table_frame.grid_rowconfigure(mrow, weight=1)
        self.table_frame.grid_columnconfigure(mrow, weight=1)
        mrow += 1

        # Лог (самый нижний элемент)
        self.log_label = ctk.CTkLabel(main_frame, text="Ожидание...",
                                      font=("Consolas", 14),  # Моноширинный шрифт лучше для логов
                                      height=30,
                                      fg_color="#111827",  # Черный фон полосы
                                      corner_radius=6)
        self.log_label.grid(row=mrow, column=0, sticky="ew", padx=5, pady=(0, 5))

        # --- Правая часть: Управление ---
        # control_panel = ctk.CTkFrame(self, width=300)
        control_panel = ctk.CTkFrame(self, width=320, fg_color=("gray90", "#2B2B2B"))  # Чуть светлее фона
        control_panel.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        control_panel.grid_columnconfigure(0, weight=1)
        # Шрифты и отступы
        btn_font = ctk.CTkFont(family="Segoe UI", size=13, weight="bold")
        pad_opt = {'padx': 15, 'pady': 5}
        row = 0

        # === БЛОК 1: ДАННЫЕ (OZON BLUE) ===
        ctk.CTkLabel(control_panel, text="ДАННЫЕ", font=("Segoe UI", 11, "bold"), text_color="gray").grid(row=row,
                                                                                                          column=0,
                                                                                                          sticky="w",
                                                                                                          padx=15,
                                                                                                          pady=(10, 0))
        row += 1
        ctk.CTkButton(control_panel, text="Загрузить заказы OZON",
                      command=self.load_ozon_orders,
                      font=btn_font,
                      height=35,
                      fg_color="#005BFF", hover_color="#0046C7").grid(row=row, column=0, sticky="ew", **pad_opt)
        row += 1
        ctk.CTkButton(control_panel, text="Загрузить Активные",
                      command=self.load_active_orders,
                      font=btn_font,
                      height=35,
                      fg_color="#005BFF", hover_color="#0046C7").grid(row=row, column=0, sticky="ew", **pad_opt)
        row += 1
        ctk.CTkButton(control_panel, text="Обновить статусы",
                      command=self.update_orders_statuses_from_api,
                      font=btn_font,
                      height=35,
                      fg_color="#4B5563", hover_color="#374151").grid(row=row, column=0, sticky="ew", **pad_opt)
        row += 1
        # === НОВАЯ КНОПКА ===
        self.btn_update_prices = ctk.CTkButton(
            control_panel,
            text="💰 Обновить цены",
            command=self.update_buyer_prices_from_finance,
            fg_color="#2c3e50",  # Темно-синий/серый цвет, чтобы отличалась
            hover_color="#34495e",
            width=140
        )
        self.btn_update_prices.grid(row=row, column=0, sticky="ew", **pad_opt)
        row += 1
        # --- Разделитель ---
        ctk.CTkFrame(control_panel, height=2, fg_color="gray40").grid(row=row, column=0, sticky="ew", padx=10, pady=10)
        row += 1

        # === БЛОК 2: СКАНИРОВАНИЕ И ВВОД ===
        ctk.CTkLabel(control_panel, text="ОПЕРАЦИИ", font=("Segoe UI", 11, "bold"), text_color="gray").grid(row=row,
                                                                                                            column=0,
                                                                                                            sticky="w",
                                                                                                            padx=15,
                                                                                                            pady=(0, 0))
        row += 1

        # Поиск товара
        self.scan_entry2 = ctk.CTkEntry(control_panel, placeholder_text="Поиск товара по ШК...", font=self.font,
                                        height=35)
        self.scan_entry2.bind('<Return>', lambda event: self.handle_barcode_input(self.scan_entry2.get()))
        self.scan_entry2.grid(row=row, column=0, sticky="ew", **pad_opt)
        row += 1

        # Чекбокс2
        self.checkbox2 = ctk.CTkCheckBox(control_panel, text="Режим поиск\ввод",
                                        variable=self.select_barcode_update,
                                        font=("Segoe UI", 12))
        self.checkbox2.grid(row=row, column=0, sticky="w", padx=15, pady=5)
        row += 1
        # Сканирование КИЗ
        self.cis_entry = ctk.CTkEntry(control_panel, placeholder_text="Сканирование Честный Знак...", font=self.font,
                                      height=35)
        self.cis_entry.bind('<Return>', lambda event: self.handle_cis_input(self.cis_entry.get()))
        self.cis_entry.grid(row=row, column=0, sticky="ew", **pad_opt)
        row += 1
        # Чекбокс
        self.checkbox = ctk.CTkCheckBox(control_panel, text="Авто-печать после скана",
                                        variable=self.check_var,
                                        font=("Segoe UI", 12))
        self.checkbox.grid(row=row, column=0, sticky="w", padx=15, pady=5)
        row += 1
        # Кнопка очистки (Red/Destructive)
        self.transfer_button = ctk.CTkButton(control_panel, text="🗑 Очистить КИЗ",
                                             command=self.clear_cis_button,
                                             font=btn_font,
                                             fg_color="#EF4444", hover_color="#DC2626")  # Красный
        self.transfer_button.grid(row=row, column=0, sticky="ew", **pad_opt)
        row += 1

        # Разделитель
        ctk.CTkFrame(control_panel, height=2, fg_color="gray40").grid(row=row, column=0, sticky="ew", padx=10, pady=10)
        row += 1

        # === БЛОК 3: СБОРКА И ПЕЧАТЬ (MAIN ACTIONS) ===
        # Собрать заказ (Emerald Green)
        self.assembly_button = ctk.CTkButton(control_panel, text="СОБРАТЬ ЗАКАЗ",
                                             command=self.finalize_manual_assembly,
                                             font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                                             height=45,
                                             fg_color="#10B981", hover_color="#059669",  # Зеленый (Emerald)
                                             state="disabled")
        self.assembly_button.grid(row=row, column=0, sticky="ew", **pad_opt)
        row += 1

        # Привязать КИЗ
        self.assign_product = ctk.CTkButton(control_panel, text="🔗 Привязать КИЗ к заказу",
                                            command=self.assign_product_label,
                                            font=btn_font,
                                            fg_color="#8B5CF6", hover_color="#7C3AED",  # Фиолетовый
                                            state="disabled")
        self.assign_product.grid(row=row, column=0, sticky="ew", **pad_opt)
        row += 1

        # Печать (Indigo/Slate)
        self.print_button = ctk.CTkButton(control_panel, text="🖨️ ПЕЧАТЬ ЭТИКЕТКИ",
                                          command=self.print_label_from_button,
                                          font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                                          height=45,
                                          fg_color="#4F46E5", hover_color="#4338CA",  # Indigo
                                          state="disabled")
        self.print_button.grid(row=row, column=0, sticky="ew", **pad_opt)
        row += 1

        # # Testing
        # ctk.CTkButton(control_panel, text="Testing",
        #                                   command=self.testing_print(),
        #                                   font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
        #                                   height=45,
        #                                   fg_color="#4F46E5", hover_color="#4338CA",  # Indigo
        #                                   state="disabled").grid(row=row, column=0, sticky="ew", **pad_opt)
        # row += 1

        # Инициализация таблицы
        # Используем EditableDataTable
        self.data_table = EditableDataTable(
            self.table_frame,
            dataframe=self.fbs_df,
            columns=self.columns,
            max_rows=5000,
            header_font=("Segoe UI", 12),  # , "bold"),
            cell_font=("Segoe UI", 14),
            on_row_select=self._handle_row_selection,
            readonly=False,
            on_edit_start=self.on_edit_start,
            on_edit_end=self.on_edit_end,
            textlbl=self.marketplace + ' FBS'
        )
        self.data_table.pack(fill="both", expand=True)
        # 💡 ДОБАВЛЕНИЕ ПРИВЯЗОК НАВИГАЦИИ СТРЕЛКАМИ
        # Предполагается, что self.data_table уже создан, и self.data_table.tree доступен.
        # self.data_table.tree.bind('<<TreeviewSelect>>', self.on_row_select)

        # 💡 НОВЫЕ ПРИВЯЗКИ: Используем <KeyRelease> для гарантированного срабатывания после обновления выделения
        self.data_table.tree.bind('<Up>', self.on_arrow_key_release)
        self.data_table.tree.bind('<Down>', self.on_arrow_key_release)
        self.data_table.tree.bind('<Return>', self.on_arrow_key_release)
        # Обновляем таблицу
        self.update_table()
        # self.update_supply_combobox()
        self.restore_entry_focus()
        # self.start_auto_focus()

    def update_buyer_prices_from_finance(self):
        """
        Запрашивает финансовый отчет и обновляет поле 'Цена'.
        Добавлена проверка наличия поля accruals_for_sale.
        """
        if self.fbs_df is None or self.fbs_df.empty:
            self.show_log("Таблица пуста. Нечего обновлять.", is_error=True)
            return

        postings = self.fbs_df["Номер отправления"].astype(str).unique().tolist()
        postings = [p for p in postings if p.strip() and p != 'nan']

        if not postings:
            self.show_log("Нет номеров отправлений для анализа.", is_error=True)
            return

        self.show_log(f"Запрос фин. данных для {len(postings)} заказов...")
        updated_count = 0

        for posting_no in postings:
            try:
                response = self.api.get_order_transaction_info(posting_no)

                if response and "result" in response:
                    operations = response["result"].get("operations", [])

                    for op in operations:
                        # --- ПРОВЕРКА ПОЛЯ ---
                        # Проверяем, существует ли ключ и не является ли значение None
                        if "accruals_for_sale" not in op or op.get("accruals_for_sale") is None:
                            logger.debug(f"В операции для {posting_no} отсутствует начисление (accruals_for_sale).")
                            continue

                        accrual = op.get("accruals_for_sale", 0)

                        items = op.get("items", [])
                        for it in items:
                            sku = str(it.get("sku"))

                            # Если начисление есть и оно не нулевое (значит продажа зафиксирована)
                            if accrual != 0:
                                mask = (self.fbs_df["Номер отправления"].astype(str) == posting_no) & \
                                       (self.fbs_df["sku"].astype(str) == sku)

                                if mask.any():
                                    try:
                                        price_val = str(int(float(accrual)))
                                        self.fbs_df.loc[mask, "Цена"] = price_val
                                        updated_count += 1
                                    except (ValueError, TypeError):
                                        continue

            except Exception as e:
                logger.error(f"Ошибка при обработке {posting_no}: {e}")

        self.update_table()
        self.save_data_to_context()
        self.show_log(f"✅ Цены обновлены из фин. отчета. Успешно: {updated_count} поз.")

    def _on_scan_enter(self, event):
        """
        Распределяет логику сканирования в зависимости от чекбокса 'smart'.
        """
        input_value = self.scan_entry.get()
        if self.smart_mode_var.get():
            self.show_log("Режим сканирования: Smart")
            self.handle_barcode_input_auto_smart(input_value)
        else:
            self.show_log("Режим сканирования: Обычный (Auto)")
            self.handle_barcode_input_auto(input_value)

    def _normalize_cis_to_list(self, raw_value) -> list:
        """
        Универсальный метод для преобразования значения ячейки 'Код маркировки' в список.
        Обрабатывает:
        - list: возвращает как есть.
        - str: "['code1', 'code2']" -> парсит в список.
        - str: "code1" -> превращает в ['code1'].
        - NaN/None/Empty -> возвращает [].
        """
        # 1. Если это уже список — возвращаем как есть
        if isinstance(raw_value, list):
            return raw_value

        # 2. Если это NaN, None или нечто пустое
        if pd.isna(raw_value) or raw_value is None:
            return []

        # 3. Если это строка
        if isinstance(raw_value, str):
            s_val = raw_value.strip()

            # Пустая строка
            if not s_val:
                return []

            # Попытка распознать строковое представление списка (например "['abc']")
            if s_val.startswith('[') and s_val.endswith(']'):
                try:
                    parsed = ast.literal_eval(s_val)
                    if isinstance(parsed, list):
                        return parsed
                except (ValueError, SyntaxError):
                    # Если не вышло распарсить (например, код сам содержит скобки),
                    # считаем это просто одной строкой-кодом.
                    pass

            # Если это обычная строка (один код)
            return [s_val]

        # 4. Если это число или другой объект — превращаем в строку и кладем в список
        return [str(raw_value)]

    # def is_valid_chestny_znak(self, code: str) -> bool:
    #     # Проверяем, содержит ли строка неправильный регистр в известных фиксированных частях
    #     # Например: 91ee11 вместо 91EE11 — признак Caps Lock
    #     if '91ee11' in code or '92ee' in code.lower():  # можно расширить
    #         self.show_log('Отключите Casp Lock и сканируйте код маркировки еще раз')
    #         return False
    #     # Убираем спецсимволы разделители (FNC1 / GS / \x1d), если сканер их передает
    #     clean_code = code.replace('\x1d', '').strip()
    #
    #     # Шаблон для полного кода (с криптохвостом)
    #     # GTIN(14) + Serial(13-20) + (опционально 91(4) + 92(44/88))
    #     # Обратите внимание: длина серийного номера бывает разной для разных товарных групп
    #     # (обувь, одежда - 13, шины - 20, табак - 7 и т.д.), поэтому ставим {1,20}
    #     pattern = r"^01(\d{14})21([\x21-\x7A]{1,20})(91[\x21-\x7A]{4}92[\x21-\x7A]{44,88})?$"
    #
    #     return bool(re.match(pattern, clean_code))
    #
    # def is_valid_barcode(self, barcode: str) -> bool:
    #     """
    #     Проверяет, является ли строка валидным штрихкодом товара.
    #
    #     Поддерживаемые форматы:
    #     - EAN-13: 13 цифр
    #     - EAN-8: 8 цифр (опционально)
    #     - UPC-A: 12 цифр (можно включить при необходимости)
    #
    #     По умолчанию — только EAN-13 (наиболее распространён в РФ).
    #     """
    #
    #     if not isinstance(barcode, str):
    #         return False
    #     # Убираем возможные пробелы или дефисы (иногда встречаются)
    #     barcode = barcode.strip().replace("-", "").replace(" ", "")
    #
    #     # Проверка длины и цифр
    #     if not re.fullmatch(r"^\d{13}$", barcode):
    #         return False
    #
    #     # Опционально: проверка контрольной суммы для EAN-13
    #     return self.is_valid_ean13_checksum(barcode)
    #
    # def is_valid_ean13_checksum(self,barcode: str) -> bool:
    #     """
    #     Проверяет контрольную сумму EAN-13.
    #     Алгоритм:
    #     - Сумма цифр на чётных позициях (2,4,6...) * 3
    #     - Плюс сумма цифр на нечётных позициях (1,3,5...)
    #     - Последняя цифра — контрольная
    #     - Общая сумма должна быть кратна 10
    #     """
    #     if len(barcode) != 13 or not barcode.isdigit():
    #         return False
    #
    #     digits = [int(d) for d in barcode]
    #     # Позиции: 0-based, но в EAN-13 нумерация с 1 → чётные индексы = нечётные позиции
    #     # Считаем: позиции 1,3,5,7,9,11 → индексы 0,2,4,6,8,10 → НЕЧЁТНЫЕ индексы в 0-based считаются как "чётные позиции"
    #     # Правильный алгоритм:
    #     sum_odd = sum(digits[i] for i in range(0, 12, 2))  # позиции 1,3,5,...,11 → индексы 0,2,...,10
    #     sum_even = sum(digits[i] for i in range(1, 12, 2))  # позиции 2,4,...,12 → индексы 1,3,...,11
    #     total = sum_odd + 3 * sum_even
    #     check_digit = (10 - (total % 10)) % 10
    #     return check_digit == digits[12]

    def checkbox_event(self):
        logger.info("Checkbox toggled, current value:", self.check_var.get())

    def on_arrow_key_release(self, event):
        """
        Обрабатывает нажатие стрелок (Up/Down) и Enter.
        Использует задержку, чтобы Treeview успел обновить выделение,
        прежде чем вызывать on_row_select.
        """
        # Небольшая задержка в 5 мс, чтобы Treeview обновил выделение
        self.after(5, lambda: self._handle_row_selection()) #None

    def apply_row_coloring(self):
        """
        Проходит по всем строкам в Treeview и применяет цветовые теги
        ('completed', 'found') на основе статуса в self.fbs_df.
        """
        if self.fbs_df.empty or not hasattr(self, 'data_table'):
            return

        # 1. Сброс старых тегов со всех элементов (чтобы избежать дублирования)
        for item in self.data_table.tree.get_children():
            self.data_table.tree.item(item, tags=())

            # 2. Применение новых тегов
        for index, row in self.fbs_df.iterrows():
            row_id = str(index)  # iid в Treeview всегда совпадает со строковым индексом DF
            if index in self.related_rows:
                status_tag = "related_posting"
            else:
                status_tag = self.get_row_status(row)

            # Проверяем, существует ли строка в Treeview
            if status_tag and self.data_table.tree.exists(row_id):
                self.data_table.tree.item(row_id, tags=(status_tag,))

        self.data_table.tree.tag_configure("found", background="#FFFACD")  # Желтый - найден штрихкод или товар в БД
        self.data_table.tree.tag_configure("missing", background="#FFB6C1")  # Красный - товар не найден в БД
        self.data_table.tree.tag_configure("completed", background="#9966CC")  # Аметист - поставка в доставке
        self.data_table.tree.tag_configure("confirm",
                                           background="#CCFFCC")  # Очень бледный, почти белый с легким зеленым оттенком.- есть и штрихкод, и маркировка
        self.data_table.tree.tag_configure("collected order", background="#ADD8E6")  # Зеленый - заказ собран

        # --- НОВЫЙ ЦВЕТ ---
        # Нежный фисташковый для строк статуса "awaiting_registration"
        self.data_table.tree.tag_configure("awaiting_registration", background="#D2E1C8")
        # Светло-голубой для строк того же отправления
        self.data_table.tree.tag_configure("related_posting", background="#E0FFFF")
        self.data_table.tree.tag_configure("express", background="#FF8C00", foreground="black")  # Ярко-оранжевый
        self.data_table.tree.tag_configure("express_collected", background="#CD853F",
                                 foreground="white")  # Темный оранжевый (собран)

    # --- МЕТОДЫ ОБРАБОТКИ СКАНИРОВАНИЯ ---
    def handle_barcode_input(self, input_value: str):
        """
        Обрабатывает ввод штрихкода.
        """
        self.editing = True
        barcode = input_value.strip()
        self.scan_entry2.delete(0, 'end')  # Очищаем поле сразу
        if not self.select_barcode_update.get():
            self.show_log("Обрабатываем ситуацию когда надо установить штрихкод")
            if not barcode:
                self.show_log("❌ Ошибка: Введите штрихкод.", is_error=True)
                self.start_auto_focus()
                return
            if self.selected_row_index is None:
                self.show_log("Не выделена активная строка для ввода Штрихкода")
                self.start_auto_focus()
                return
            # Извлекаем значение из DataFrame
            barcode_value = self.fbs_df.at[self.selected_row_index, "Штрихкод"]
            # 1. Проверка на пропущенное значение (NaN)
            is_nan = pd.isna(barcode_value)
            # 2. Проверка на пустую строку (после приведения к строке и удаления пробелов)
            is_empty_string = str(barcode_value).strip() == ""
            if is_nan or is_empty_string:
                self.show_log("Поле для ввода Штрихкода пусто, можно вводить новое значение")
            else:
                answer = messagebox.askyesnocancel(
                    "Поле Штрихкод не пусто",
                    "Вы точно хотите внести новое значение \n"
                    "и заменить старое?"
                )
                if not answer:
                    return
            # Если выбрана строка, привязываем штрихкод к ней
            row = self.fbs_df.loc[self.selected_row_index]
            # Сохраняем штрихкод
            self.fbs_df.at[self.selected_row_index, "Штрихкод"] = barcode
            # Сохраняем в основную базу данных
            self.save_to_main_database(row, barcode)
            self.update_table()
            self.data_table.select_row(self.selected_row_index)
            # # Сохраняем в контекст
            self.save_data_to_context()
            play_success_scan_sound()
            # if self.check_var.get():
            #     self.show_log(f"Печатаем этикетку {barcode} ШК  ")
            #     self.print_label_from_button()
            self.show_log(f"✅ Штрихкод {barcode} привязан. Теперь можно ввести код маркировки, при необходимости...")
            # Переключаемся на ввод маркировки
            self.input_mode = "marking"
            self.pending_barcode = barcode
        else:
            self.show_log("Обрабатываем ситуацию когда ищем строку с заданным штрихкодом")
            if not barcode:
                self.show_log("❌ Ошибка: Введите штрихкод.", is_error=True)
                self.editing = False
                self.start_auto_focus()
                return

            self.show_log(f"Сканирование: {barcode}")
            # 1. Поиск: ищем  Штрихкод производителя в текущих заказах
            matches = self.fbs_df[(self.fbs_df['Штрихкод'].astype(str) == str(barcode))
                                  & (self.fbs_df["Статус обработки"] == self.assembly_status[0])].copy()
            row_index = 0

            if not matches.empty:
                # --- Логика Сборки по сканированию (автоматическая) ---
                row_index = matches.index[0]
                # logger.info('row_index',row_index)
                row = self.fbs_df.loc[row_index]
                self.selected_row_index = row_index
                # --- ДОБАВЛЕНИЕ ЛОГИКИ ВЫДЕЛЕНИЯ И ФОКУСА - --

                self.data_table.select_row(row_index)  # выделение строки
                play_success_scan_sound()
                # if self.check_var.get():
                #     self.show_log(f"Печатаем этикетку {barcode} ШК  ")
                #     self.print_label_from_button()
            # 2. Несовпадение: возможно, это новый ШК или артикул для добавления
            else:
                # self.handle_unmatched_barcode(barcode) Этот метод реализовать позже
                self.show_log(f"Несовпадение: возможно, это новый {barcode} ШК или артикул ")
        self.start_auto_focus()

    def handle_barcode_input_auto_smart(self, input_value: str):
        """
        Обрабатывает автоматически  ввод кода и определяем, что это штрихкод или код маркировки,
        для поля автосборки и автоматической обработки
        """
        self.current_barcode = input_value.strip()
        input_value = input_value.strip()
        if self.is_valid_barcode(input_value):
            self.input_mode = "barcode"
            self.show_log(f"Введен штрихкод товара")
            self.handle_barcode_input_for_smart(input_value)
            self.input_mode = "marking"
        elif self.is_valid_chestny_znak(input_value):
            self.input_mode = "marking"
            self.show_log(f"Введен код маркировки ")
            self.handle_marking_input_smart(input_value)
            self.input_mode = "barcode"
        elif not input_value and self.input_mode == "marking":
            self.input_mode = "marking"
            self.show_log(f"Введен пустой Enter ")
            self.handle_marking_input_smart(input_value)
            self.input_mode = "barcode"
        else:
            self.show_log(f"Не определен вид сканированного кода")

    def handle_barcode_input_for_smart(self, barcode):
        """ Обрабатывает полученный штрихкод,
        в автосборке для handle_barcode_input_auto_smart
        """
        if not self.select_barcode_update.get():
            self.show_log("Обрабатываем ситуацию когда надо установить штрихкод")
            if self.selected_row_index is None:
                self.show_log("Не выделена активная строка для ввода Штрихкода")
                return
            # Извлекаем значение из DataFrame
            barcode_value = self.fbs_df.at[self.selected_row_index, "Штрихкод"]
            # 1. Проверка на пропущенное значение (NaN)
            is_nan = pd.isna(barcode_value)
            # 2. Проверка на пустую строку (после приведения к строке и удаления пробелов)
            is_empty_string = str(barcode_value).strip() == ""
            if is_nan or is_empty_string:
                self.show_log("Поле для ввода Штрихкода пусто, можно вводить новое значение")
            else:
                answer = messagebox.askyesnocancel(
                    "Поле Штрихкод не пусто",
                    "Вы точно хотите внести новое значение \n"
                    "и заменить старое?"
                )
                if not answer:
                    return
            # Если выбрана строка, привязываем штрихкод к ней
            row = self.fbs_df.loc[self.selected_row_index]
            # Сохраняем штрихкод
            self.fbs_df.at[self.selected_row_index, "Штрихкод"] = barcode
            # Сохраняем в основную базу данных
            self.save_to_main_database(row, barcode)
            self.update_table()
            # # Сохраняем в контекст
            self.save_data_to_context()
            play_success_scan_sound()
            self.show_log(f"✅ Штрихкод {barcode} привязан. Теперь введите код маркировки...")
            # Переключаемся на ввод маркировки
            # self.input_mode = "marking"
            self.pending_barcode = barcode
            # Очищаем поле ввода
            self.scan_entry.delete(0, "end")
            self.restore_entry_focus()
        else:
            self.show_log("Обрабатываем ситуацию когда ищем строку с заданным штрихкодом")
            # Если строка не выбрана, ищем по штрихкоду
            matches = self.fbs_df[(self.fbs_df['Штрихкод'].astype(str) == str(barcode))
                                  & (self.fbs_df["Статус обработки"] == self.assembly_status[0])
                                  ]
            row_index = 0
            if not matches.empty:
                # --- Логика Сборки по сканированию (автоматическая) ---
                row_index = matches.index[0]
                # logger.info('row_index',row_index)
                row = self.fbs_df.loc[row_index]
                self.selected_row_index = row_index
                # --- ДОБАВЛЕНИЕ ЛОГИКИ ВЫДЕЛЕНИЯ И ФОКУСА - --
                self.data_table.select_row(row_index)  # выделение строки

                # Запрашиваем код маркировки
                # self.input_mode = "marking"
                self.pending_barcode = barcode
                # self.scanning_label.configure(text="Введите код маркировки... 🏷️")
                self.show_log(f"Найдена строка: Номер отправления: {row['Номер отправления']}. Введите код маркировки...")
                self.scan_entry.delete(0, "end")
                self.restore_entry_focus()
            else:
                self.show_log("Ошибка: Штрихкод не найден в заказах", is_error=True)
                play_unsuccess_scan_sound()

    def handle_marking_input_smart(self, marking_code: str):
        """Обрабатывает ввод кода маркировки, для поля автосборки"""
        flag_debug = True
        self.cis_entry.delete(0, 'end')
        if self.selected_row_index is not None:
            row = self.fbs_df.loc[self.selected_row_index]
            # Записываем код маркировки в таблицу, если значение не пусто
            if marking_code:
                self.show_log("Обрабатываем код маркировки")
                # Проверяй корректность введенного кода
                quantity = int(row['Количество'])
                # === ИСПОЛЬЗУЕМ НОВУЮ ФУНКЦИЮ ===
                # Получаем гарантированный список, независимо от того, что там лежало (строка, нан, список)
                cis_list = self._normalize_cis_to_list(self.fbs_df.at[self.selected_row_index, 'Код маркировки'])

                # Обновляем ячейку (на случай если там была строка, теперь там будет чистый список)
                # Это важно сделать сразу, чтобы последующие append работали корректно
                self.fbs_df.at[self.selected_row_index, 'Код маркировки'] = cis_list
                len_cis = len(cis_list)

                if len_cis < quantity:
                    self.fbs_df.loc[self.selected_row_index, 'Код маркировки'].append(marking_code)
                    self.show_log(f"✅ КИЗ записаны для отправления {row['Номер отправления']} и товара {row['sku']}.")
                    self.update_table()
                    # # Сохраняем в контекст
                    self.save_data_to_context()
                    len_cis += 1
                    # if len_cis == quantity:
                    # Привяжем список код маркировки к метаданным заказа Озон
                    self.assign_product_label_internal_directory(marking_code,row)
                    if len_cis < quantity:
                        self.show_log(
                            f"Необходимо заполнить еще {quantity - len_cis} КИЗ для отправления {row['Номер отправления']} и товара {row['sku']}.")
                        # self.input_mode = "marking"
                        # Сохраняем данные в контекст
                        # self.save_data_to_context()
                        # # Обновляем таблицу
                        # self.update_table()
                        # self.scan_entry.delete(0, "end")
                        self.restore_entry_focus()
                        return
                else:
                    self.show_log(
                        f"✅ Список КИЗ УЖЕ ЗАПОЛНЕН !!! для отправления {row['Номер отправления']} и товара {row['sku']}.")
            else:
                self.show_log(
                    f"Предупреждение! Для отправления {row['Номер отправления']} и товара {row['sku']} не задан КИЗ.")
            # Собираем заказ
            # self.show_log(f"self.finalize_manual_assembly()")
            self.finalize_manual_assembly()
            # Печатаем этикетку
            # self.show_log(f"self.print_label_from_button(flag=False)")
            if self.check_var.get():
                self.show_log(f"Печатаем этикетку {self.pending_barcode} ШК  ")
                self.print_label_from_button(flag=False)

            # Сохраняем данные в контекст
            self.save_data_to_context()
            play_success_scan_sound()
            # Обновляем таблицу
            self.update_table()

            # Сбрасываем состояние
            # self.selected_row_index = None # Это почему так?
            # self.input_mode = "barcode"
            self.pending_barcode = None # Это зачем?
            # self.scanning_label.configure(text="Ожидание сканирования... 📱")

            self.scan_entry.delete(0, "end")
            self.restore_entry_focus()
        else:
            self.show_log("Ошибка: Не выбрана строка для маркировки", is_error=True)
            play_unsuccess_scan_sound()

    def handle_barcode_input_auto(self, input_value: str):
        """
        Обрабатывает автоматическую последовательность ввода штрихкода и код маркировки, для поля автосборки
        """
        self.current_barcode = input_value.strip()
        input_value = input_value.strip()
        if self.input_mode == "barcode":
            # Первый этап: ввод штрихкода
            self.handle_barcode_input_old(input_value)
        else:
            # Второй этап: ввод кода маркировки
            self.handle_marking_input(input_value)

    def handle_barcode_input_old(self, barcode):
        """ Обрабатывает ввод штрихкода, для поля автосборки """
        self.show_log("Сканируем штрихкод товара")
        if self.selected_row_index is not None:
            # Извлекаем значение из DataFrame
            barcode_value = self.fbs_df.at[self.selected_row_index, "Штрихкод"]
            # 1. Проверка на пропущенное значение (NaN)
            is_nan = pd.isna(barcode_value)
            # 2. Проверка на пустую строку (после приведения к строке и удаления пробелов)
            is_empty_string = str(barcode_value).strip() == ""
            if is_nan or is_empty_string:
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
            # self.scanning_label.configure(text="Введите код маркировки... 🏷️")

            # Очищаем поле ввода
            self.scan_entry.delete(0, "end")
            self.restore_entry_focus()
        else:
            if not str(barcode).strip():
                self.show_log("Ошибка: Штрихкод не введен", is_error=True)
                play_unsuccess_scan_sound()
                return

            # Если строка не выбрана, ищем по штрихкоду
            matches = self.fbs_df[(self.fbs_df['Штрихкод'].astype(str) == str(barcode))
                                  & (self.fbs_df["Статус обработки"] == self.assembly_status[0])
                                  ]
            row_index = 0
            if not matches.empty:
                # --- Логика Сборки по сканированию (автоматическая) ---
                row_index = matches.index[0]
                # logger.info('row_index',row_index)
                row = self.fbs_df.loc[row_index]
                self.selected_row_index = row_index
                # --- ДОБАВЛЕНИЕ ЛОГИКИ ВЫДЕЛЕНИЯ И ФОКУСА - --

                self.data_table.select_row(row_index)  # выделение строки

                # # Если у строки уже есть код маркировки, показываем информацию
                # if row["Код маркировки"] == "" or pd.isna(row["Код маркировки"]):

                # Запрашиваем код маркировки
                self.input_mode = "marking"
                self.pending_barcode = barcode
                # self.scanning_label.configure(text="Введите код маркировки... 🏷️")
                self.show_log(f"Найдена строка: Номер отправления: {row['Номер отправления']}. Введите код маркировки...")
                #
                # else:
                #     self.show_log(
                #         f"Найдена строка: Заказ {row['Номер заказа']}, маркировка: {row['Код маркировки']}")
                #     self.selected_row_index = None
                #     self.show_log("Строка уже обработана");

                self.scan_entry.delete(0, "end")
                self.restore_entry_focus()

            else:
                self.show_log("Ошибка: Штрихкод не найден в заказах", is_error=True)
                play_unsuccess_scan_sound()

    def assign_product_label(self, row=None):
        if row is None:
            if self.selected_row_index is None:
                self.show_log("❌ Выберите активную строку для привязки маркировки Честный знак.", is_error=True)
                return
            row = self.fbs_df.loc[self.selected_row_index]
            marking_code = self.fbs_df.at[self.selected_row_index, "Код маркировки"]
        else:
            marking_code = row["Код маркировки"]

        if marking_code:
            # Здесь по API OZON Закрепить за сборочным заданием код маркировки товара Честный знак.
            if row["Статус заказа"] == self.define_status[5]:
                posting_number = row["Номер отправления"]
                product_id = int(row["sku"])
                try:
                    self.ozon_api.set_product_marking_code(
                        posting_number=posting_number,
                        cis_code=marking_code,
                        product_id=product_id
                    )
                    self.show_log(
                        f"❌ Успешно в API OZON  привязан код маркировки {marking_code} к отправлению {posting_number} ")
                except Exception as e:
                    logger.info(
                        f"❌ Ошибка API OZON  привязки кода маркировки {marking_code} к отправлению {posting_number}: {str(e)}")
                    self.show_log(
                        f"❌ Ошибка API OZON  привязки кода маркировки {marking_code} к отправлению {posting_number}: {str(e)}",
                        is_error=True)
            else:
                self.show_log(
                    f"❌ Ошибка API OZON  привязки отправления, 'Статус заказа' не  в 'awaiting_packaging'",
                    is_error=True)

    def assign_product_label_internal_directory(self, marking_code, row=None):
        if not marking_code:
            if row is None:
                if self.selected_row_index is None:
                    self.show_log("❌ Выберите активную строку для привязки маркировки Честный знак.", is_error=True)
                    return
                row = self.fbs_df.loc[self.selected_row_index]
                self.show_log(f"Активная строка не была задана, используем активный индекс, в отправлении {row['Номер отправления']} ")
                marking_code = self.fbs_df.at[self.selected_row_index, "Код маркировки"]
            else:
                marking_code = row["Код маркировки"]
                self.show_log(
                    f"Для определения кода маркировки, использовалась переданная строка, в отправлении {row['Номер отправления']} ")
            marking_code = self._normalize_cis_to_list(marking_code)
        if marking_code:
            try:
                # Создаем новую запись
                new_row = pd.DataFrame([{
                    "Номер отправления": row["Номер отправления"],
                    "Код маркировки": marking_code,
                    "Цена": row["Цена"],
                    "sku": row["sku"],
                    "Артикул поставщика": row["Артикул поставщика"],
                    "Размер": row["Размер"],
                    # ИСПРАВЛЕНИЕ: Вместо объекта Timestamp передаем готовую строку
                    "Время добавления": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Маркетплейс":'Ozon'
                }]).explode("Код маркировки", ignore_index=True)

                # ---  СИНХРОНИЗАЦИЯ С БД ---
                # --- обновление marking_codes ---
                try:
                    # Передаем только новые сформированные строки
                    self.db.sync_dataframe(new_row, "marking_codes", ["Код маркировки"])
                    # Используем специализированный метод вместо универсального sync_dataframe
                    # self.db.upsert_marking_codes(new_row)
                    self.show_log(f"Сохранены новые КМ в БД !!!")
                except Exception as e:
                    self.show_log(f"Ошибка сохранения новых КМ в БД: {e}")
                # --- обновление product_barcodes ---
                try:
                    # НОВОЕ: Извлечение и сохранение GTIN
                    gtin = self.extract_gtin(marking_code)
                    if gtin:
                        self.update_product_gtin(self.db, row["Артикул поставщика"], row["Размер"], gtin)
                        self.show_log(f"Сохранена информация в поле GTIN Справочника товаров")
                except Exception as e:
                    self.show_log(f"Ошибка сохранения в поле GTIN Справочника товаров: {e}")
                # ---------------------------------------
            except Exception as e:
                self.show_log(
                    f"❌ Ошибка записи КИЗ {marking_code} в Основной справочник КИЗ {row['Номер отправления']} и товара {row['sku']}: {str(e)}",
                    is_error=True)
        else:
            # предусмотреть удаление строки по sku если есть запись
            self.show_log(f"Отсутствует КИЗ для {row['Номер заказа']} и товара {row['Штрихкод WB']}.")

    def handle_marking_input(self, marking_code: str):
        """Обрабатывает ввод кода маркировки, для поля автосборки"""
        flag_debug = True
        self.show_log("Сканируем код маркировки")
        self.cis_entry.delete(0, 'end')
        if self.selected_row_index is not None:
            row = self.fbs_df.loc[self.selected_row_index]
            # Записываем код маркировки в таблицу, если значение не пусто
            if marking_code:
                # Проверяй корректность введенного кода
                if not self.is_valid_chestny_znak(marking_code):
                    play_unsuccess_scan_sound()
                    self.show_log("❌ Неверный формат кода маркировки", is_error=True)
                    self.input_mode = "marking"
                    # self.scan_entry.delete(0, "end")
                    self.restore_entry_focus()
                    return

                quantity = int(row['Количество'])
                # === ИСПОЛЬЗУЕМ НОВУЮ ФУНКЦИЮ ===
                # Получаем гарантированный список, независимо от того, что там лежало (строка, нан, список)
                cis_list = self._normalize_cis_to_list(self.fbs_df.at[self.selected_row_index, 'Код маркировки'])

                # Обновляем ячейку (на случай если там была строка, теперь там будет чистый список)
                # Это важно сделать сразу, чтобы последующие append работали корректно
                self.fbs_df.at[self.selected_row_index, 'Код маркировки'] = cis_list
                len_cis = len(cis_list)

                if len_cis < quantity:
                    self.fbs_df.loc[self.selected_row_index, 'Код маркировки'].append(marking_code)
                    self.show_log(f"✅ КИЗ записаны для отправления {row['Номер отправления']} и товара {row['sku']}.")
                    self.update_table()
                    # # Сохраняем в контекст
                    self.save_data_to_context()
                    len_cis += 1
                    # if len_cis == quantity:
                    # Привяжем список код маркировки к метаданным заказа Озон
                    self.assign_product_label_internal_directory(marking_code,row)
                    if len_cis < quantity:
                        self.show_log(
                            f"Необходимо заполнить еще {quantity - len_cis} КИЗ для отправления {row['Номер отправления']} и товара {row['sku']}.")
                        self.input_mode = "marking"
                        # Сохраняем данные в контекст
                        # self.save_data_to_context()
                        # # Обновляем таблицу
                        # self.update_table()
                        # self.scan_entry.delete(0, "end")
                        self.restore_entry_focus()
                        return
                else:
                    self.show_log(
                        f"✅ Список КИЗ УЖЕ ЗАПОЛНЕН !!! для отправления {row['Номер отправления']} и товара {row['sku']}.")
            else:
                self.show_log(
                    f"Предупреждение! Для отправления {row['Номер отправления']} и товара {row['sku']} не задан КИЗ.")
            # Расскомментировать после тестирования !!!!
            # Собираем заказ
            # self.show_log(f"self.finalize_manual_assembly()")
            self.finalize_manual_assembly()
            # Печатаем этикетку
            # self.show_log(f"self.print_label_from_button(flag=False)")
            if self.check_var.get():
                self.show_log(f"Печатаем этикетку {self.pending_barcode} ШК  ")
                self.print_label_from_button(flag=False)

            # Сохраняем данные в контекст
            self.save_data_to_context()
            play_success_scan_sound()
            # Обновляем таблицу
            self.update_table()

            # Сбрасываем состояние
            self.selected_row_index = None # Это почему так?
            self.input_mode = "barcode"
            self.pending_barcode = None
            # self.scanning_label.configure(text="Ожидание сканирования... 📱")

            self.scan_entry.delete(0, "end")
            self.restore_entry_focus()
        else:
            self.show_log("Ошибка: Не выбрана строка для маркировки", is_error=True)
            play_unsuccess_scan_sound()

    def handle_cis_input(self, input_value: str):
        """Обрабатывает ввод КИЗ (Честный знак). (Требование 3)"""
        cis_code = input_value.strip()
        self.cis_entry.delete(0, 'end')

        if not cis_code:
            self.show_log("❌ Введите КИЗ.", is_error=True)
            self.cis_entry_focus()
            return

        if self.selected_row_index is None:
            self.show_log("❌ Сначала выберите или отсканируйте товар.", is_error=True)
            play_unsuccess_scan_sound()
            self.start_auto_focus()
            return

        # Проверяй корректность введенного кода
        if not self.is_valid_chestny_znak(cis_code):
            play_unsuccess_scan_sound()
            self.show_log("❌ Неверный формат кода маркировки", is_error=True)
            # self.input_mode = "marking"
            # self.scan_entry.delete(0, "end")
            self.cis_entry_focus()
            return

        # ЛОГИКА: Cохраняем КИЗ в списке текущей строки
        row = self.fbs_df.loc[self.selected_row_index]
        quantity = int(row['Количество'])

        # === ИСПОЛЬЗУЕМ НОВУЮ ФУНКЦИЮ ===
        # Получаем гарантированный список, независимо от того, что там лежало (строка, нан, список)
        cis_list = self._normalize_cis_to_list(self.fbs_df.at[self.selected_row_index, 'Код маркировки'])

        # Обновляем ячейку (на случай если там была строка, теперь там будет чистый список)
        # Это важно сделать сразу, чтобы последующие append работали корректно
        self.fbs_df.at[self.selected_row_index, 'Код маркировки'] = cis_list
        len_cis = len(cis_list)

        if len_cis < quantity:
            self.fbs_df.loc[self.selected_row_index, 'Код маркировки'].append(cis_code)
            self.show_log(f"✅ КИЗ записаны для отправления {row['Номер отправления']} и товара {row['sku']}.")
            self.update_table()
            # Сохраняем в контекст
            self.save_data_to_context()
            len_cis += 1
            # if len_cis == quantity:
            # Привяжем список код маркировки к справочнику
            self.assign_product_label_internal_directory(cis_code,row)
        else:
            self.show_log(f"✅ Список КИЗ УЖЕ ЗАПОЛНЕН !!! для отправления {row['Номер отправления']} и товара {row['sku']}.")
        if len_cis >= quantity:
            self.start_auto_focus()
        else:
            self.show_log(
                f"Необходимо заполнить еще {quantity-len_cis} КИЗ для отправления {row['Номер отправления']} и товара {row['sku']}.")
            self.cis_entry_focus()

    def clear_cis_button(self):
        if self.selected_row_index is None:
            self.show_log("❌ Сначала выберите строку или отсканируйте товар.", is_error=True)
            play_unsuccess_scan_sound()
            self.start_auto_focus()
            return
        row = self.fbs_df.loc[self.selected_row_index]
        posting_number = row["Номер отправления"]

        # --- НОВЫЙ БЛОК: УДАЛЕНИЕ ИЗ БД ---
        self.db.delete_marking_codes_by_posting(posting_number)
        # ----------------------------------

        self.fbs_df.at[self.selected_row_index, 'Код маркировки'] = []
        self.show_log(f"✅ КИЗ очищены для отправления {row['Номер отправления']} и товара {row['sku']}.")
        self.update_table()
        self.data_table.select_row(self.selected_row_index)

        # # Привяжем список код маркировки к справочнику
        # self.assign_product_label_internal_directory(row)

    def save_to_main_database(self, row=None, barcode=None):
        """Сохраняет штрихкод в основную базу данных"""
        if self.selected_row_index is None:
            self.show_log("Сохранение пропущено: активная строка не выбрана.")
            return
        if row is None:
            row = self.fbs_df.loc[self.selected_row_index]
            barcode = row['Штрихкод']
        if not barcode:
            self.show_log(f"❌ Ошибка сохранения. Штрихкод не определился!", is_error=True)
            return
        # Создаем новую запись
        df_new = pd.DataFrame([{
            "Артикул производителя": row["Артикул поставщика"],
            "Размер": row["Размер"],
            "Штрихкод производителя": barcode,
            "Наименование поставщика": row.get("Наименование", ""),
            "Бренд": row.get("Бренд", ""),
            "Штрихкод OZON": row.get("Штрихкод Ozon", ""),
            "SKU OZON": row.get("sku", "")
        }])
        # 2. ОБРАБОТКА УСЛОВИЙ В БАЗЕ ДАННЫХ
        # Метод sync_dataframe использует SQL "REPLACE", который автоматически:
        # - Если (Артикул+Размер) уже есть -> Обновляет строку (Update)
        # - Если (Артикул+Размер) нет -> Создает новую (Insert)
        try:
            self.db.sync_dataframe(df_new, "product_barcodes", ["Артикул производителя", "Размер"])
            self.show_log(f"✅ База данных: синхронизировано {len(df_new)} позиций.")
        except Exception as e:
            self.show_log(f"Ошибка при сохранении в БД: {e}")


    # --- МЕТОДЫ УПРАВЛЕНИЯ UI И ДАННЫМИ ---
    def load_active_orders(self):
        """Загрузка всех невыполненных (активных) заказов через эндпоинт unfulfilled"""
        self.show_log("Ozon API: Запрос всех активных (unfulfilled) заказов...")
        target_db_columns = [
            'Штрихкод OZON',
            'Артикул производителя',
            'Размер',
            'Штрихкод производителя',
            'Бренд',
            'SKU OZON']
        try:
            # Вызываем метод, который  в ozon_fbs_api.py
            response = self.api.get_unfulfilled_orders()

            if not response or 'result' not in response:
                self.show_log( "Не удалось получить данные от API или список пуст.")
                return

            postings = response.get('result', {}).get('postings', [])
            if not postings:
                self.show_log("Активных заказов (unfulfilled) не найдено.")
                return

            new_rows = []
            for item in postings:
                posting_number = item.get('posting_number')
                order_number = item.get('order_number')
                status = item.get('status')
                substatus = item.get('substatus', "")
                is_express = item.get('is_express', False)

                # Извлекаем название службы доставки
                delivery_method = item.get('delivery_method', {}).get('name', "")

                # В одном отправлении может быть несколько товаров
                for prod in item.get('products', []):
                    # Обработка цены (float -> int -> str)
                    final_price = prod.get('price')
                    try:
                        price_str = str(int(float(final_price))) if final_price else "0"
                    except (ValueError, TypeError):
                        price_str = "0"
                    new_rows.append({
                        "Номер заказа": str(order_number),
                        "Номер отправления": str(posting_number),
                        "Служба доставки": delivery_method,
                        "Цена": price_str,
                        "Артикул поставщика": prod.get('offer_id'),
                        "Количество": prod.get('quantity'),
                        "Наименование": prod.get('name'),
                        "sku": prod.get('sku'),
                        "product_id": prod.get('sku'),
                        "Статус заказа": status,
                        "Подстатус": substatus,
                        "Статус обработки": self.assembly_status[0],  # "Новый"
                        "is_express": is_express
                    })

            # 4. Создание DataFrame
            if not new_rows:
                self.show_log(f"Не обнаружено строк для обновления")
                return
            self.show_log(f"Создаем из списка DataFrame new_orders_df")
            # Создаем временный DataFrame
            new_orders_df = pd.DataFrame(new_rows)

            if self.fbs_df is None or self.fbs_df.empty:
                new_orders_df_clean = new_orders_df.copy()
            else:
                # Нам нужно исключить строки, которые УЖЕ есть в базе.
                # Сравнивать нужно тоже по ПАРЕ (Отправление + Артикул).
                self.show_log(f"Создаем временный комбинированный ключ для существующей базы")
                # 1. Создаем временный комбинированный ключ для существующей базы
                # Пример ключа: "12345678-0001-1_987654321"
                existing_keys = (
                        self.fbs_df['Номер отправления'].astype(str) + '_' +
                        self.fbs_df['sku'].astype(str)
                )
                self.show_log(f"Создаем такой же ключ для новых данных")
                # 2. Создаем такой же ключ для новых данных
                new_keys = (
                        new_orders_df['Номер отправления'].astype(str) + '_' +
                        new_orders_df['sku'].astype(str)
                )
                self.show_log(f"Фильтруем: оставляем только те строки new_orders_df")
                # 3. Фильтруем: оставляем только те строки new_orders_df,
                # чьих ключей НЕТ в existing_keys
                new_orders_df_clean = new_orders_df[~new_keys.isin(existing_keys)].copy()
                # 2. ОБНОВЛЕНИЕ СУЩЕСТВУЮЩИХ ЗАПИСЕЙ
                # Находим те новые заказы, которые УЖЕ ЕСТЬ в нашей таблице
                update_mask = new_keys.isin(existing_keys)

                if update_mask.any():
                    df_to_update = new_orders_df[update_mask]

                    for _, row in df_to_update.iterrows():
                        # Ищем строку в основном датафрейме по ключу
                        key = str(row["Номер отправления"]) + "_" + str(row["sku"])
                        fbs_idx = self.fbs_df[(self.fbs_df["Номер отправления"].astype(str) + "_" + self.fbs_df[
                            "sku"].astype(str)) == key].index

                        if not fbs_idx.empty:
                            # Обновляем только нужные поля
                            self.fbs_df.loc[fbs_idx, "Цена"] = row["Цена"]
                            self.fbs_df.loc[fbs_idx, "Статус заказа"] = row["Статус заказа"]
                            self.fbs_df.loc[fbs_idx, "Подстатус"] = row["Подстатус"]
                            self.fbs_df.loc[fbs_idx, "is_express"] = row["is_express"]

                    self.show_log(f"Обновлены статусы и цены для {update_mask.sum()} позиций.")

            # 3. ДОБАВЛЕНИЕ НОВЫХ ЗАПИСЕЙ
            # Берем те, которых НЕТ в существующем списке
            if not new_orders_df_clean.empty:
                # =================================================================
                # ШАГ 2: # --- МЕРЖ 2: ПОЛУЧЕНИЕ ДАННЫХ ИЗ БД SQLite ---
                # =================================================================
                # 1. Берем список SKU из новых заказов
                sku_list = new_orders_df_clean['sku'].unique().tolist()
                # 2. Запрашиваем из БД только нужные строки (мини-справочник)
                product_details_map = self.db.get_products_by_skus(sku_list)
                if not product_details_map.empty:
                    self.show_log("Начинаем МЕРЖ 2: Получение деталей товара из БД таблицы product_barcodes")
                    product_details_map = product_details_map[target_db_columns]
                    product_details_map = product_details_map.dropna(subset=['SKU OZON'])
                    product_details_map = product_details_map.rename(columns={'Штрихкод производителя': 'Штрихкод'})
                    product_details_map = product_details_map.rename(columns={'Штрихкод OZON': 'Штрихкод Ozon'})
                    # 2.2. Очистка lookup-таблицы (убираем дубликаты по ключу)
                    self.show_log("2.2. Очистка lookup-таблицы (убираем дубликаты по ключу)")

                    product_details_map.drop_duplicates(subset=['SKU OZON'], keep='first',
                                                        inplace=True)
                    product_details_map = product_details_map.reset_index(drop=True)

                    # 2.3. Приводим ключи к строковому типу
                    product_details_map['SKU OZON'] = product_details_map['SKU OZON'].astype(
                        str).str.strip()
                    new_orders_df_clean['sku'] = new_orders_df_clean['sku'].astype(
                        str).str.strip()

                    self.show_log("2.4. Выполняем LEFT MERGE")
                    # 2.4. Выполняем LEFT MERGE
                    new_orders_df_clean = new_orders_df_clean.merge(
                        product_details_map,
                        left_on='sku',
                        right_on='SKU OZON',
                        how='left'
                    )
                    self.show_log("2.5. Удаляем дублирующую колонку-ключ ('SKU OZON' из базы)")
                    # 2.5. Удаляем дублирующую колонку-ключ ('SKU OZON' из базы)
                    new_orders_df_clean.drop(columns=['SKU OZON'], errors='ignore', inplace=True)
                    # устанавливаем поле-список для кода маркировки, предполагает множественное значение
                    # в дальнейшем подтянуть заполнение из отдельной таблицы !!!
                    new_orders_df_clean['Код маркировки'] = [[] for _ in range(len(new_orders_df_clean))]
                    # Создаём датафрейм с правильными колонками, заполняя отсутствующие ''
                    new_orders_df_clean = new_orders_df_clean.reindex(columns=self.fbs_df.columns, fill_value='')

                else:
                    self.show_log("Основной справочник товаров (Штрихкод Ozon) пуст. Нет возможности получить Штрихкод")
                    return

                # Используем fillna('') для всего DataFrame или точечно
                new_orders_df_clean = new_orders_df_clean.fillna('')

                # 5. Объединение с текущей базой (self.fbs_df)
                self.show_log("5. Объединение с текущей базой (self.fbs_df)")
                if self.fbs_df is None or self.fbs_df.empty:
                    self.fbs_df = new_orders_df_clean.copy()
                else:
                    # Проходимся по всей колонке и нормализуем данные
                    self.fbs_df['Код маркировки'] = self.fbs_df['Код маркировки'].apply(self._normalize_cis_to_list)
                    self.fbs_df = pd.concat([self.fbs_df, new_orders_df_clean], ignore_index=True)
                # Сохраняем в контекст
                self.save_data_to_context()
                # Обновляем отображение
                self.update_table(self.fbs_df)
                self.show_log(f"✅ Загружено {len(new_orders_df_clean)} новых товаров из Ozon.")
            else:
                self.show_log("Все полученные товары уже есть в таблице.")

        except Exception as e:
            self.show_log(f"Ошибка при загрузке активных заказов: {e}", is_error=True)


    def load_ozon_orders(self):
        """Загружает новые сборочные задания OZON через API."""
        # загружаем лист "Штрихкоды" из 'Data/Справочник SKU Ozon.xlsx'
        df_sku = pd.DataFrame()
        # try:
        #     file_path = 'Data/Справочник SKU Ozon.xlsx'
        #     df_sku = pd.read_excel(file_path, sheet_name="Штрихкоды", header=1)
        #     self.show_log(f"Справочника SKU, успешно загружен!")
        #     # print(df_sku.head(10))
        # except Exception as e:
        #     self.show_log(f"❌ Ошибка загрузки справочника SKU: {e}", is_error=True)
        #     return
        # 1. Определяем, какие поля нам нужны из справочника БД
        target_db_columns = [
            'Штрихкод OZON',
            'Артикул производителя',
            'Размер',
            'Штрихкод производителя',
            'Бренд',
            'SKU OZON' ]
        try:
            self.show_log("OZON API: Запрос новых сборочных заданий...")
            json_data = self.api.get_orders()
            json_data2 = self.api.get_orders(status='awaiting_deliver')
            # json_data3 = self.api.get_orders(status='arbitration')
            """
                Нормализует JSON-структуру ответа API Ozon, создавая DataFrame,
                где каждая строка соответствует отдельному товару.
                """
            if ('result' not in json_data or 'postings' not in json_data['result'])\
                    and ('result' not in json_data2 or 'postings' not in json_data2['result']):
                    # and ('result' not in json_data3 or 'postings' not in json_data3['result']):
                self.show_log("❌ Структура JSON не соответствует ожидаемой (отсутствует 'result' или 'postings').", is_error=False)
                return

            postings_list = json_data['result']['postings']
            postings_list2 = json_data2['result']['postings']
            # postings_list3 = json_data3['result']['postings']
            postings_list.extend(postings_list2)
            # postings_list.extend(postings_list3)

            if not postings_list:
                self.show_log("⚠️ Список 'postings' пуст. Возвращен пустой DataFrame.", is_error=False)
                return
            rows = []

            # 2. Итерируемся по КАЖДОМУ отправлению (posting)
            self.show_log("Итерируемся по КАЖДОМУ отправлению (posting)")
            for posting in postings_list:

                # Мета-данные отправления
                posting_number = posting.get('posting_number', '')
                order_number = posting.get('order_id', '')
                # shipment_date = posting.get('shipment_date', '')
                status = posting.get('status', '')
                # Извлекаем название службы доставки
                delivery_method = posting.get('delivery_method', {}).get('name', "")

                # --- ЛОГИКА ЦЕНЫ (Financial Data) ---
                # self.show_log("Создаем справочник цен из financial_data для быстрого поиска по sku (product_id)")
                # Создаем справочник цен из financial_data для быстрого поиска по sku (product_id)
                # Структура financial_data.products - это список, параллельный products
                fin_prices = {}
                financial_data = posting.get('financial_data')
                if financial_data and isinstance(financial_data, dict):
                    fin_products = financial_data.get('products', [])
                    if fin_products:
                        for item,fp in enumerate(fin_products):
                            pid = fp.get('product_id')
                            price = fp.get('price')  # Это финальная цена продажи
                            if pid:
                                fin_prices[item] = (price,pid)

                # 3. Итерируемся по КАЖДОМУ товару в отправлении
                # Если товаров 5, будет добавлено 5 строк с одинаковым posting_number
                products = posting.get('products', [])
                for item, prod in enumerate(products):
                    sku = prod.get('sku')  # Это Ozon Product ID
                    offer_id = prod.get('offer_id', '')  # Артикул продавца
                    name = prod.get('name', '')
                    quantity = prod.get('quantity', 1)

                    # ОПРЕДЕЛЕНИЕ ЦЕНЫ
                    # Приоритет 1: Цена из financial_data (точная цена продажи)
                    # Приоритет 2: Цена из карточки товара (базовая)
                    pid_price = fin_prices.get(item)
                    if pid_price is None:
                        final_price = prod.get('price', 0)
                        product_id = ''
                    else:
                        final_price = pid_price[0]
                        product_id = pid_price[1]


                    # Обработка цены (float -> int -> str)
                    try:
                        price_str = str(int(float(final_price))) if final_price else "0"
                    except (ValueError, TypeError):
                        price_str = "0"
                    # Формируем строку для DataFrame
                    # Ключи должны совпадать с self.columns (или быть преобразованы позже)
                    row = {
                        "Номер заказа": order_number,
                        "Номер отправления": posting_number,
                        "Служба доставки": delivery_method,
                        "Артикул поставщика": offer_id,
                        "sku": str(sku),  # Сохраняем SKU для поиска
                        "product_id": product_id,
                        "Наименование": name,
                        "Количество": quantity,
                        "Цена": price_str,
                        "Статус заказа": status,
                        "Статус обработки": self.assembly_status[0],  # Внутренний статус приложения
                    }

                    # self.show_log(f"Добавляем строку  по {sku} (product_id) в промежуточный список")
                    rows.append(row)

            # 4. Создание DataFrame
            if not rows:
                return
            self.show_log(f"Создаем из списка DataFrame new_orders_df")
            new_orders_df = pd.DataFrame(rows)

            if self.fbs_df is None or self.fbs_df.empty:
                new_orders_df_clean = new_orders_df.copy()
            else:
                # Нам нужно исключить строки, которые УЖЕ есть в базе.
                # Сравнивать нужно тоже по ПАРЕ (Отправление + Артикул).
                self.show_log(f"Создаем временный комбинированный ключ для существующей базы")
                # 1. Создаем временный комбинированный ключ для существующей базы
                # Пример ключа: "12345678-0001-1_987654321"
                existing_keys = (
                        self.fbs_df['Номер отправления'].astype(str) + '_' +
                        self.fbs_df['sku'].astype(str)
                )
                self.show_log(f"Создаем такой же ключ для новых данных")
                # 2. Создаем такой же ключ для новых данных
                new_keys = (
                        new_orders_df['Номер отправления'].astype(str) + '_' +
                        new_orders_df['sku'].astype(str)
                )
                self.show_log(f"Фильтруем: оставляем только те строки new_orders_df")
                # 3. Фильтруем: оставляем только те строки new_orders_df,
                # чьих ключей НЕТ в existing_keys
                new_orders_df_clean = new_orders_df[~new_keys.isin(existing_keys)]

            if not new_orders_df_clean.empty:
                # =================================================================
                # ШАГ 2: по sku Ozon подтягиваем детали товара  из БД !!!
                # =================================================================

                # 1. Берем список SKU из новых заказов
                sku_list = new_orders_df_clean['sku'].unique().tolist()
                # 2. Запрашиваем из БД только нужные строки (мини-справочник)
                product_details_map = self.db.get_products_by_skus(sku_list)
                if not product_details_map.empty:
                    self.show_log("Начинаем МЕРЖ 2: Получение деталей товара из БД таблицы product_barcodes")
                    product_details_map = product_details_map[target_db_columns]
                    product_details_map = product_details_map.dropna(subset=['SKU OZON'])
                    product_details_map = product_details_map.rename(columns={'Штрихкод производителя':'Штрихкод'})
                    product_details_map = product_details_map.rename(columns={'Штрихкод OZON': 'Штрихкод Ozon'})
                    # 2.2. Очистка lookup-таблицы (убираем дубликаты по ключу)
                    self.show_log("2.2. Очистка lookup-таблицы (убираем дубликаты по ключу)")

                    product_details_map.drop_duplicates(subset=['SKU OZON'], keep='first',
                                                        inplace=True)
                    product_details_map = product_details_map.reset_index(drop=True)

                    # 2.3. Приводим ключи к строковому типу
                    product_details_map['SKU OZON'] = product_details_map['SKU OZON'].astype(
                        str).str.strip()
                    new_orders_df_clean['sku'] = new_orders_df_clean['sku'].astype(
                        str).str.strip()

                    self.show_log("2.4. Выполняем LEFT MERGE")
                    # 2.4. Выполняем LEFT MERGE
                    new_orders_df_clean = new_orders_df_clean.merge(
                        product_details_map,
                        left_on='sku',
                        right_on='SKU OZON',
                        how='left'
                    )
                    self.show_log("2.5. Удаляем дублирующую колонку-ключ ('SKU OZON' из базы)")
                    # 2.5. Удаляем дублирующую колонку-ключ ('SKU OZON' из базы)
                    new_orders_df_clean.drop(columns=['SKU OZON'], errors='ignore', inplace=True)
                    # устанавливаем поле-список для кода маркировки, предполагает множественное значение
                    # в дальнейшем подтянуть заполнение из отдельной таблицы !!!
                    new_orders_df_clean['Код маркировки'] = [[] for _ in range(len(new_orders_df_clean))]
                    # Создаём датафрейм с правильными колонками, заполняя отсутствующие ''
                    new_orders_df_clean = new_orders_df_clean.reindex(columns=self.fbs_df.columns, fill_value='')

                else:
                    self.show_log("Основной справочник товаров (Штрихкод Ozon) пуст. Нет возможности получить Штрихкод")
                    # return

                # Используем fillna('') для всего DataFrame или точечно
                new_orders_df_clean = new_orders_df_clean.fillna('')

                # 5. Объединение с текущей базой (self.fbs_df)
                self.show_log("5. Объединение с текущей базой (self.fbs_df)")
                if self.fbs_df is None or self.fbs_df.empty:
                    self.fbs_df = new_orders_df_clean.copy()
                else:
                    # Проходимся по всей колонке и нормализуем данные
                    self.fbs_df['Код маркировки'] = self.fbs_df['Код маркировки'].apply(self._normalize_cis_to_list)
                    self.fbs_df = pd.concat([self.fbs_df, new_orders_df_clean], ignore_index=True)
                # Сохраняем в контекст
                self.save_data_to_context()
                # Обновляем отображение
                self.update_table(self.fbs_df)
                self.show_log(f"✅ Загружено {len(new_orders_df_clean)} новых товаров из Ozon.")
            else:
                self.show_log("Все полученные товары уже есть в таблице.")

        except Exception as e:
            self.show_log(f"❌ Ошибка загрузки заказов Ozon: {e}", is_error=True)
            # play_unsuccess_scan_sound()


    def _handle_row_selection(self, row_index=None):
        """Обрабатывает выбор строки в таблице."""

        if row_index is None:
            # Деактивировать  кнопки, если строка не выбрана
            # self.assembly_button.configure(state="disabled")
            # self.print_button.configure(state="disabled")
            # self.assign_product.configure(state="disabled")
            return
            # row_index = self.selected_row_index
        # logger.info(f"DEBUG:FBSModeWB _handle_row_select received index: {row_index}")
        else:
            self.selected_row_index = row_index
        try:
            row = self.fbs_df.loc[row_index]
        except KeyError:
            # Недопустимый индекс
            self.assembly_button.configure(state="disabled")
            self.print_button.configure(state="disabled")
            self.assign_product.configure(state="disabled")
            return

        # --- НОВАЯ ЛОГИКА ПОДСВЕТКИ СВЯЗАННЫХ СТРОК ---
        current_posting_number = str(row["Номер отправления"]).strip()

        if current_posting_number:
            # Находим индексы всех строк с таким же номером отправления
            # (исключая саму выбранную строку, так как она уже подсвечена системным цветом выделения)
            self.related_rows = self.fbs_df[
                (self.fbs_df["Номер отправления"].astype(str) == current_posting_number) &
                (self.fbs_df.index != row_index)
                ].index.tolist()

            # # Применяем тег к найденным строкам
            if self.related_rows:
                self.update_table()
                self.data_table.select_row(row_index)  # выделение строки
                self.flag_upd = True
            elif self.flag_upd:
                self.flag_upd = False
                self.update_table()
                self.data_table.select_row(row_index)  # выделение строки
        # --- Остальная логика метода (статусы кнопок и т.д.) ---

        is_processed = row["Статус заказа"] == self.define_status[5]  # 'confirm'
        has_barcode = row["Штрихкод"] != ""
        has_marking = row["Код маркировки"] != ""
        has_articul = row["Артикул поставщика"] != ""
        has_size = row["Размер"] != ""

        # self.show_log(f"Статус заказа: {is_processed} Штрихкод: {has_barcode} Код маркировки: {has_marking}", is_error=True)
        # Условия для "Собрать заказ" (finalize_manual_assembly):
        # 1. Заказ НЕ обработан.
        # 2. Штрихкод и Код маркировки (если нужен, хотя тут мы просто проверяем наличие) заполнены.
        can_finalize = (not is_processed and has_articul and has_size)  # and has_marking)

        # Условия для "Печать этикетки":
        # 1. Заказ уже Обработан.
        can_print = is_processed

        # 💡 УПРАВЛЕНИЕ КНОПКАМИ
        self.assembly_button.configure(state="normal" if can_finalize else "disabled")
        self.print_button.configure(state="normal" if can_print else "disabled")
        self.assign_product.configure(state="normal" if can_print else "disabled")

    def _update_assembly_button_state(self):
        """Обновляет активность кнопки 'Собрать Заказ' (Требование 1)."""
        if self.selected_row_index is not None:
            row = self.fbs_df.loc[self.selected_row_index]
            if row['Статус заказа'] != self.define_status[1]:  # 'new':
                self.assembly_button.configure(state="normal", fg_color="green")
                return

        self.assembly_button.configure(state="disabled", fg_color="gray")

    def _update_print_button_state(self):
        """Обновляет активность и цвет кнопки 'Печать Этикетки' (Требование 2)."""
        is_printable = False

        if self.selected_row_index is not None:
            row = self.fbs_df.loc[self.selected_row_index]
            # Активна, если собрано и добавлено в поставку
            if row['Статус заказа'] == self.define_status[5]:  # 'awaiting_deliver'
                is_printable = True

        if is_printable:
            self.print_button.configure(state="normal", fg_color="blue")
        else:
            self.print_button.configure(state="disabled", fg_color="gray")
            self.assign_product.configure(state="disabled", fg_color="gray")

    def finalize_manual_assembly(self):
        """
        Завершает ручную сборку выделенного заказа:
        1. Добавляет заказ в текущую поставку OZON.
        2. Обновляет статус в таблице.
        3. Активирует кнопку печати.
        """
        debug_info = False
        if self.selected_row_index is None:
            self.show_log("❌ Выберите строку заказа для завершения сборки.", is_error=True)
            return


        row_index = self.selected_row_index
        current_status = self.fbs_df.loc[row_index, "Статус заказа"]
        sku = self.fbs_df.loc[row_index, "sku"]
        posting_number = self.fbs_df.loc[row_index, "Номер отправления"]
        if current_status == 'awaiting_deliver':
            self.show_log(f"Заказ для {posting_number} и товара {sku} уже собран!")
            return

        # Получаем все отправления входящие в текущий заказ
        # mask_orders = self.fbs_df["Номер заказа"] == order_id
        # order_ids = self.fbs_df.loc[mask_orders, "Номер заказа","Номер отправления"]
        # Получаем текущий статус из таблицы

        # 1. Находим ВСЕ товары, относящиеся к этому номеру отправления
        # Даже если в таблице они разнесены по разным строкам
        posting_rows = self.fbs_df[self.fbs_df['Номер отправления'] == posting_number]

        products_to_ship = []

        # 2. Собираем полный список товаров для отправки в API
        for _, p_row in posting_rows.iterrows():
            # Получаем и валидируем SKU (как мы делали ранее)
            raw_sku = p_row.get('sku')  # или 'product_id', проверьте название колонки

            # Пропуск пустых строк, если вдруг попались
            if not raw_sku or str(raw_sku).lower() in ['nan', 'none', '']:
                continue

            try:
                sku_val = int(float(raw_sku))
                qty_val = int(p_row['Количество'])

                # Добавляем товар в общий список
                products_to_ship.append({
                    "product_id": sku_val,
                    # Внимание: параметр API называется 'product_id', а не 'sku' для этого метода
                    "quantity": qty_val
                })
            except ValueError:
                self.show_log(f"❌ Ошибка данных товара в отправлении {posting_number}", is_error=True)
                return
        if not products_to_ship:
            self.show_log(f"❌ Не найдены товары для сборки отправления {posting_number}", is_error=True)
            return


        # 3. Отправляем ОДИН запрос с ПОЛНЫМ списком товаров
        try:
            self.show_log(f"OZON API: Сборка отправления {posting_number}. Товаров: {len(products_to_ship)}...")

            # Важно: products передается внутрь packages
            # Логика в ozon_fbs_api.py должна уметь принимать этот список
            self.api.set_status_to_assembly(posting_number, products=products_to_ship)

            self.show_log(f"✅ Отправление {posting_number} успешно собрано.")

            # ... (обновление статусов в таблице для ВСЕХ строк этого отправления) ...
            self.fbs_df.loc[posting_rows.index, "Статус заказа"] = self.define_status[5]  # awaiting_deliver
            # self.fbs_df.loc[posting_rows.index, "Статус обработки"] = self.assembly_status[1]  # Обработан
            # Сохраняем в контекст
            self.save_data_to_context()
            self.update_table()
            self.print_button.configure(state="normal")
            play_success_scan_sound()
        except Exception as e:
            self.show_log(f"❌ Ошибка сборки отправления {posting_number} : {e}", is_error=True)
            return

    def check_related_shipments(self) -> bool:
        if self.related_rows:
            existing_indices = [idx for idx in self.related_rows if idx in self.fbs_df.index]
            if not existing_indices:
                return True

            subset = self.fbs_df.loc[existing_indices, 'Статус обработки']
            # Гарантируем, что это Series
            if not isinstance(subset, pd.Series):
                subset = pd.Series([subset], index=existing_indices)
            self.show_log(f"Серия для проверки : {subset}")
            condition = (subset.fillna('') == "Обработан")
            return condition.all() and len(condition) > 0
        else:
            return True

    def check_shipments(self) -> bool:
        row = self.fbs_df.loc[self.selected_row_index]
        posting_number = row["Номер отправления"]
        mask = self.fbs_df["Номер отправления"] == posting_number
        if mask.sum() > 1:
            self.show_log(f"Проверка с check_shipments и mask.sum() > 1")
            filtered_df = self.fbs_df[mask & (self.fbs_df.index != self.selected_row_index)]
            all_processed = (filtered_df['Статус обработки'] == "Обработан").all()
            if all_processed and row['Статус обработки'] == "Не обработан":
                return True
            else:
                return False
        else:
            return True

    # def testing_print(self):
    #     for index, row in self.fbs_df.iterrows():
    #         self.selected_row_index = index
    #         print(row["Номер отправления"],' - ', self.check_shipments())

    def print_label_from_button(self,flag:bool = True):
        """Печать этикетки по кнопке (требование 2)."""
        if self.selected_row_index is None:
            self.show_log("❌ Выберите строку для печати.", is_error=True)
            return

        row = self.fbs_df.loc[self.selected_row_index]
        posting_number = row["Номер отправления"]
        # logger.info('Номер заказа:', row["Номер заказа"], 'Индекс строки:', self.selected_row_index)
        # logger.info('Статус заказа:',row['Статус заказа'],'Номер поставки:',row['Номер поставки'])
        # logger.info('Проверка шаблона ID поставки:', bool(re.match(self.pattern,row['Номер поставки'])))

        if row['Статус заказа'] == self.define_status[5]:  # 'awaiting_deliver':
            # if (self.check_related_shipments() and row['Статус обработки'] == self.assembly_status[0]) or flag:
            if flag or self.check_shipments():
                self._fetch_and_print_wb_label(row["Номер отправления"], self.app_context.printer_name)
            else:
                # Помечаем товар как обработанный
                self.fbs_df.loc[self.selected_row_index, "Статус обработки"] = self.assembly_status[1]  # "Обработан"
                self.show_log(f"Для печати этикетки необходимо обработать все отправления {posting_number} ...")
                # Обновление таблицы и раскраски
                self.update_table(self.fbs_df)
        else:
            self.show_log("❌ Отправление должно быть в статусе 'awaiting_deliver'. Печать невозможна.", is_error=True)

    def _fetch_and_print_wb_label(self, posting_number, printer_target):
        """Запрашивает  этикетку и отправляет на печать."""
        debug_info = False

        self.show_log(f"Запрос этикетки Ozon для: {posting_number} ...")
        stikers_type = "pdf"
        try:
            stickers_response = self.api.get_stickers(posting_number)
        except Exception as e:
            self.show_log(f"❌ Критическая ошибка при вызове API get_stickers: {e}", is_error=True)
            return

        # --- БЛОК ПРОВЕРКИ ОТВЕТА ---
        if not stickers_response:
            self.show_log(f"❌ Ozon API вернул пустой ответ (None) для {posting_number}", is_error=True)
            return
        # ... (дальше код отправки на печать) ...
        try:
            if self.label_printer.print_ozon_label_fbs(stickers_response):  # Здесь мы печатаем этикетку
                self.show_log(f"✅ Этикетка OZON для {posting_number} успешно отправлена на печать.", is_error=False)
            else:
                self.show_log("❌ Прямая печать не удалась. Проверьте принтер .", is_error=True)

            # Помечаем товар как обработанный -- это тоже надо закинуть в печать этикетки
            self.fbs_df.loc[self.selected_row_index, "Статус обработки"] = self.assembly_status[1]  # "Обработан"
            # Обновление таблицы и раскраски
            self.update_table(self.fbs_df)
        except Exception as e:
            self.show_log(f"❌ Ошибка печати этикетки OZON: {e}", is_error=True)
            # play_unsuccess_scan_sound()


    # --- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ---
    def restore_entry_focus(self, event=None):
        """Возвращает фокус на поле ввода (однократно)."""
        if self.editing:
            return

        # Если уже есть запланированный фокус - отменяем, чтобы не плодить таймеры
        if hasattr(self, 'focus_timer_id') and self.focus_timer_id:
            try:
                self.after_cancel(self.focus_timer_id)
            except Exception:
                pass

        # Планируем ОДИН вызов
        self.focus_timer_id = self.after(100, self._perform_focus)

    def _perform_focus(self):
        """Внутренний метод для безопасной установки фокуса."""
        try:
            # Проверяем, существует ли виджет (защита от SIGSEGV)
            if self.scan_entry and self.scan_entry.winfo_exists():
                self.scan_entry.focus_set()
        except Exception:
            pass
        finally:
            self.focus_timer_id = None

    def on_entry_focus_in(self, event=None):
        if not self.editing:
            # self.scanning_label.configure(text="Ожидание сканирования... 📱")
            self.show_log(f"Ожидание сканирования...")

    def on_entry_focus_out(self, event=None):
        if not self.editing:
            self.show_log(f"")

    def reset_clear_timer(self, event=None):
        if self.clear_timer_id:
            self.after_cancel(self.clear_timer_id)
        self.clear_timer_id = self.after(1000, self.clear_entry)

    def clear_entry(self):
        self.scan_entry.delete(0, "end")

    def handle_keypress(self, event=None):
        if self.data_table:
            self.data_table.on_keypress(event)

    #         ----------- выше надо сделать поправки всех дополнительных элементов ----------------
    def on_edit_start(self):
        self.editing = True
        if self.focus_timer_id:
            self.after_cancel(self.focus_timer_id)

    def on_edit_end(self):
        self.editing = False
        # Сохраняем изменения в self.fbs_df и контекст
        self.fbs_df = self.data_table.displayed_df.copy()
        # Сохраняем в основную базу данных
        self.save_to_main_database()
        self.save_data_to_context()
        self.start_auto_focus()

    def save_data_to_context(self):
        """Сохраняет данные в контекст приложения"""
        try:
            self.app_context.fbs_table_ozon = self.fbs_df.copy()
            self.show_log(f"Сохраняю id текущего заказа и основную таблицу OZON FBS")
            self.app_context.ozon_fbs_order_id = self.wb_supply_id_var.strip()
        except Exception as e:
            self.show_log(f"Ошибка сохранения контекста: {str(e)}", is_error=True)

    def on_wb_supply_entry_focus_in(self, event=None):
        self.editing = True

    def on_wb_supply_entry_focus_out(self, event=None):
        self.editing = False
        self.start_auto_focus()

    def _select_row_by_index(self, index):
        """Выделяет строку в таблице по индексу DataFrame."""
        try:
            order_id = self.fbs_df.loc[index, 'Номер заказа']
            for item in self.data_table.table.get_children():
                # Проверяем первый элемент в кортеже значений (Номер заказа)
                if str(self.data_table.table.item(item, 'values')[0]) == str(order_id):
                    self.data_table.table.selection_set(item)
                    self.data_table.table.focus(item)
                    # Прокрутка к выделенному элементу
                    self.data_table.table.see(item)
                    return
        except Exception:
            pass

    def update_orders_statuses_from_api(self):
        """
        Получает и обновляет статусы, номера заказов и ЦЕНЫ товаров из API Ozon.
        """
        debug_info = False
        if self.fbs_df.empty:
            self.show_log("Нет данных для обновления статусов.", is_error=False)
            return

        # Явно приводим колонку к строкам один раз, чтобы избежать FutureWarning
        self.fbs_df["Номер заказа"] = self.fbs_df["Номер заказа"].astype(str)

        # 1. Извлекаем список уникальных отправлений для запроса
        try:
            # Получаем уникальные, не пустые номера отправлений
            unique_postings = self.fbs_df[self.fbs_df["Номер отправления"].astype(str).str.strip() != ""][
                "Номер отправления"].unique().tolist()
        except KeyError:
            self.show_log("❌ Ошибка: Колонка 'Номер отправления' не найдена.", is_error=True)
            return

        if not unique_postings:
            self.show_log("Нет номеров отправления для проверки.", is_error=False)
            return

        try:
            self.show_log(f"Ozon API: Запрос статусов и цен для {len(unique_postings)} отправлений...")

            # 2. Вызов API для каждого отправления (как в требовании)
            # Собираем ответы в список. Обрабатываем ошибки внутри генератора или ниже
            status_response = []
            for check_order in unique_postings:
                try:
                    resp = self.api.get_status_orders(check_order)
                    if resp and "result" in resp:
                        status_response.append(resp["result"])
                except Exception as e:
                    logger.warning(f"Ошибка запроса API для {check_order}: {e}")

            # 3. Обработка и обновление DataFrame
            for item in status_response:
                # 3.1. Извлечение общих данных отправления
                posting_number = item.get('posting_number')
                # В JSON есть order_number (строка) и order_id (число). Обычно для UI лучше order_number.
                new_order_number = item.get('order_id')
                new_status = item.get('status')
                substatus = item.get('substatus', "")  # Получаем подстатус
                is_express = item.get('is_express', False)  # Получаем флаг экспресса
                products_data = item.get("products", [])

                if not posting_number or not new_status:
                    continue

                try:
                    # Приводим к строке для поиска
                    str_posting = str(posting_number).strip()

                    # 3.2. Обновление общих полей (Статус, Номер заказа) для ВСЕХ строк этого отправления
                    mask_posting = self.fbs_df["Номер отправления"].astype(str) == str_posting

                    if not mask_posting.any():
                        continue

                    # Обновляем номер заказа
                    if new_order_number:
                        self.fbs_df.loc[mask_posting, "Номер заказа"] = str(new_order_number)

                    # Обновляем статус заказа
                    self.fbs_df.loc[mask_posting, "Статус заказа"] = new_status
                    self.fbs_df.loc[mask_posting, "Подстатус"] = substatus
                    self.fbs_df.loc[mask_posting, "is_express"] = is_express

                    # 3.3. Обновление ЦЕНЫ по SKU (разворачиваем массив products)
                    for prod in products_data:
                        sku_api = prod.get('sku')  # В JSON это число (int), например 180550365
                        price_api = prod.get('price')  # В JSON это строка "279.0000"

                        if sku_api and price_api:
                            # Форматируем цену (убираем лишние нули)
                            try:
                                clean_price = str(int(float(price_api)))
                            except ValueError:
                                clean_price = str(price_api)

                            # Ищем конкретную строку: То же отправление И Тот же SKU
                            # Важно: приводим оба SKU к строке для точного сравнения
                            mask_product = mask_posting & (self.fbs_df["sku"].astype(str) == str(sku_api))

                            if mask_product.any():
                                self.fbs_df.loc[mask_product, "Цена"] = clean_price
                                if debug_info:
                                    logger.info(f"Обновлена цена для {str_posting} / SKU {sku_api}: {clean_price}")

                except Exception as e:
                    self.show_log(f"❌ Ошибка обработки данных для {posting_number}: {e}", is_error=True)

            self.update_table()
            self.save_data_to_context()
            self.show_log(f"✅ Статусы и цены обновлены для {len(status_response)} отправлений.")

        except Exception as e:
            self.show_log(f"❌ Непредвиденная ошибка обновления: {e}", is_error=True)

    def update_orders_statuses_from_api_old(self):
        """
        Получает и обновляет статусы и заказы из API Ozon.
        """
        debug_info = False
        if self.fbs_df.empty:
            self.show_log("Нет данных для обновления статусов.", is_error=False)
            return

        # 1. Извлекаем список отправлений
        try:
            # order_ids = self.fbs_df["Номер отправления"].dropna().tolist()
            order_ids = self.fbs_df[self.fbs_df["Номер отправления"].astype(str).str.strip() != ""]["Номер отправления"].tolist()
        except KeyError:
            self.show_log("❌ Ошибка: Колонка 'Номер отправления' не найдена.", is_error=True)
            return

        if not order_ids:
            self.show_log("Нет номеров отправления для проверки.", is_error=False)
            return

        try:
            self.show_log(f"Ozon API: Запрос статусов и заказов для {len(order_ids)} отправлений...")
            # 2. Вызов нового метода API ------- пока закоментировано, после отработать ---------
            # print(order_ids)
            status_response = [self.api.get_status_orders(chek_order)["result"]  for chek_order in order_ids]

            # if debug_info:
                # print('Получено строк:', len(status_response))
                # print(status_response[0])

            # 3. Обработка и обновление DataFrame
            for item in status_response:
                # 1. Извлечение данных
                posting_number = item.get('posting_number')
                new_order_number = item.get('order_id')
                new_status = item.get('status')

                # Проверка обязательных полей для поиска и обновления
                if not posting_number or not new_status:
                    self.show_log(
                        f"❌ Не найдены обязательные поля для обновления. Posting: {posting_number}, Status: {new_status}", is_error=True)
                    continue

                try:
                    # 2. Создание булевой маски для поиска нужных строк
                    # Важно: Приводим к строке для надежного сравнения с DataFrame
                    mask = self.fbs_df["Номер отправления"].astype(str) == str(posting_number)

                    if not mask.any():
                        self.show_log(f"⚠️ В таблице не найдено отправление с номером: {posting_number}")
                        return

                    # 3. Обновление полей с использованием .loc для безопасности и скорости

                    # Обновляем "Номер заказа" (order_number)
                    if new_order_number:
                        self.fbs_df.loc[mask, "Номер заказа"] = new_order_number

                    # Обновляем "Статус заказа" (status)
                    self.fbs_df.loc[mask, "Статус заказа"] = new_status


                    if debug_info:
                        self.show_log(
                            f"✅ Статус отправления {posting_number} обновлен: "
                            f"Статус -> '{new_status}', Номер заказа -> '{new_order_number}'."
                        )


                except KeyError as e:
                    self.show_log(f"❌ Ошибка: В DataFrame отсутствует ожидаемый столбец {e}. Проверьте названия.", is_error=True)
                except Exception as e:
                    self.show_log(f"❌ Непредвиденная ошибка при обновлении статуса в DataFrame: {e}", is_error=True)
            self.update_table()
            self.save_data_to_context()

        except Exception as e:
            self.show_log(f"❌ Непредвиденная ошибка: {e}", is_error=True)

    def update_table(self, df: pd.DataFrame = None):
        """Обновляет содержимое таблицы и применяет цветовую индикацию."""
        if df is None:
            df = self.fbs_df
        display_df = df[self.columns].copy()
        self.data_table.update_data(display_df)
        self.apply_row_coloring()

    def show_log(self, message: str, is_error: bool = False):
        """Обновляет лог-сообщение в нижней части UI."""
        if self.log_label:
            color = "red" if is_error else "green"
            self.log_label.configure(text=message, text_color=color)
            if is_error:
                logger.error(message)
            else:
                logger.info(message)

        if hasattr(self, 'log_timer_id') and self.log_timer_id:
            self.after_cancel(self.log_timer_id)

        self.log_timer_id = self.after(5000, lambda: self.log_label.configure(text="Ожидание сканирования...",
                                                                              text_color="grey"))

    # --- БЕЗОПАСНАЯ УСТАНОВКА ФОКУСА ---
    def _safe_focus_set(self):
        """Безопасно устанавливает фокус, проверяя существование виджета."""
        try:
            # Проверяем, существует ли виджет и само окно
            if self.scan_entry2 and self.scan_entry2.winfo_exists():
                self.scan_entry2.focus_set()
        except Exception:
            # Игнорируем ошибки, если окно уже закрывается
            pass

    def start_auto_focus(self):
        """Устанавливает фокус на поле сканирования."""
        # Используем общую логику восстановления фокуса
        if self.scan_entry2 and self.scan_entry2.winfo_exists():
            # Если нужно именно на scan_entry2
            if hasattr(self, 'focus_timer_id') and self.focus_timer_id:
                try:
                    self.after_cancel(self.focus_timer_id)
                except Exception:
                    pass

            self.focus_timer_id = self.after(100,
                                             lambda: self.scan_entry2.focus_set() if self.scan_entry2.winfo_exists() else None)
        else:
            self.restore_entry_focus()

    def cis_entry_focus(self):
        """Устанавливает фокус на поле сканирования КИЗ."""
        # Используем общую логику восстановления фокуса
        if self.cis_entry and self.cis_entry.winfo_exists():
            # Если нужно именно на cis_entry
            if hasattr(self, 'focus_timer_id') and self.focus_timer_id:
                try:
                    self.after_cancel(self.focus_timer_id)
                except Exception:
                    pass
            self.focus_timer_id = self.after(100,
                                             lambda: self.cis_entry.focus_set() if self.cis_entry.winfo_exists() else None)
        else:
            self.restore_entry_focus()


    def get_row_status(self, row):
        """Определяет статус строки для цветовой индикации"""
        is_express = row.get("is_express", False)
        status_fbs = row["Статус обработки"]

        # ПРИОРИТЕТ 1: Express заказы
        if is_express:
            if status_fbs == self.assembly_status[1]:  # Если "Обработан"
                return "express_collected"  # Оранжево-коричневый
            return "express"  # Ярко-оранжевый

        # Если товар обработан - зеленый (независимо от наличия маркировки)
        if row["Статус обработки"] == self.assembly_status[1]:  # "Обработан"
            return "collected order"  # Зеленый цвет для обработанных заказов
        # Если поставка добавлена в доставку
        if row["Статус заказа"] == self.define_status[8]:  # 'delivering':
            return "completed"  # Аметист
        elif row["Статус заказа"] == self.define_status[5]:  # 'awaiting_deliver'
            return 'confirm'  # Светло зеленый
        elif row["Статус заказа"] == self.define_status[1]:  # 'awaiting_registration'
            return 'awaiting_registration'  # Нежный фисташковый

        # # Если есть и штрихкод, и код маркировки - зеленый
        # if row["Штрихкод"] != "" and row["Код маркировки"] != "":
        #     return "completed"  # Зеленый цвет для завершенных заказов

        # Если есть только штрихкод - желтый
        if row["Штрихкод"] != "":
            return "found"  # Желтый цвет для найденных штрих кодов

        return "missing"