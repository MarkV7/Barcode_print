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
from wildberries_fbs_api import WildberriesFBSAPI
from printer_handler import LabelPrinter
import logging
from db_manager import DBManager
from gui.fbs_union_gui import UnionMark

# Создаем логгер для конкретного модуля
logger = logging.getLogger(__name__)

# Переменная для хранения имени файла с новыми ШК
NEW_BARCODES_FILE = "new_barcodes.csv"

class FBSModeWB(ctk.CTkFrame, UnionMark):
    """
    Виджет для сборки заказов Wildberries (FBS).
    Включает логику сканирования, ручной сборки, создания поставки и печати этикеток.
    """

    def __init__(self, parent, font, app_context):
        super().__init__(parent)
        self.font = font
        self.app_context = app_context
        self.pattern = r'^WB-GI-[0-9]+$'
        self.marketplace = 'Wildberries'
        self.editing = False
        self.input_mode = "barcode"  # "barcode" или "marking" - режим ввода
        self.focus_timer_id = None
        self.clear_timer_id = None
        self.current_barcode = None
        self.marking_db = {}  # База данных артикул+размер -> штрихкод
        self.columns=[
                "Номер заказа", "Служба доставки", "Покупатель", "Бренд", "Цена",
                "Артикул поставщика", "Количество", "Размер",
                "Штрихкод", 'Штрихкод WB', "Код маркировки", "Номер поставки",
                "Статус заказа", "Статус обработки",
            ]
        self.define_status = ('indefinite','new','confirm','complete','cancel')
        self.assembly_status = ("Не обработан","Обработан")
        # --- Данные ---
        # 1. Создаем целевой DF с необходимыми колонками, инициализированный пустыми строками
        self.fbs_df = pd.DataFrame(columns=self.columns)

        if hasattr(self.app_context, "fbs_table") and self.app_context.fbs_table is not None:
            df = self.app_context.fbs_table.copy()
            # self.debug_print_first_row(df)
            # 2. Фильтрация по Wildberries
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
                # Заполняем пустые значения в 'Статус заказа' значением "Не обработан"
                self.fbs_df["Статус заказа"] = self.fbs_df["Статус заказа"].replace({'': 'indefinite', 'Не обработан':'indefinite'})

        self.current_orders_df = None  # Заказы, загруженные из API
        self.wb_marking_db = self._load_new_barcodes()  # База данных артикул+размер -> штрихкод

        # --- API и Принтер ---
        self.api = WildberriesFBSAPI(self.app_context.wb_api_token)
        self.label_printer = LabelPrinter(self.app_context.printer_name)

        # --- Настройки поставки WB ---
        saved_supply_id = getattr(self.app_context, "wb_fbs_supply_id", "")
        self.wb_supply_id_var = ctk.StringVar(value=str(saved_supply_id))
        self.wb_supply_id_var.trace_add("write", self.update_supply_id)

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
        self.supply_combobox = None
        self.selected_row_index = None  # Для хранения выбранной строки
        self.table_label = None
        self.check_var = ctk.BooleanVar(value=True)
        self.checkbox = None
        self.assign_product = None
        self.smart_mode_var = ctk.BooleanVar(value=True)
        self.select_barcode_update = ctk.BooleanVar(value=True)
        self.db = DBManager()
        self.setup_ui()

        self.show_log(f"Подставлен ID поставки WB: {saved_supply_id}")

    # Фрагмент кода для файла fbs_wb_gui.py (внутри класса FBSModeWB)

    def debug_print_first_row(self,data_df:DataFrame,number_row:int=0):
        """Выводит n-ю строку DataFrame self.fbs_df для проверки структуры данных."""
        if data_df.empty:
            logger.info("--- self.fbs_df пуст, нет данных для вывода. ---")
            return
        logger.info("\n=======================================================")
        logger.info(f"✅ DEBUG: {number_row}-я строка DataFrame self.fbs_df:")
        # .iloc[0] безопасно извлекает строку по числовому индексу 0,
        # независимо от того, какие у DataFrame установлены индексы (строковые/числовые).
        first_row = data_df.iloc[number_row]
        # Вывод в формате Series (колонка: значение)
        logger.info(first_row)
        logger.info("=======================================================\n")

    def _load_new_barcodes(self, filename=NEW_BARCODES_FILE) -> pd.DataFrame:
        """Загружает новые добавленные штрихкоды из отдельного CSV-файла."""
        if os.path.exists(filename):
            try:
                # Читаем с правильными типами и возвращаем DataFrame
                return pd.read_csv(filename,
                                   dtype={'Артикул производителя': str, 'Штрихкод производителя': str}).fillna('')
            except Exception as e:
                self.show_log(f"❌ Ошибка загрузки базы новых ШК: {e}", is_error=True)
                return pd.DataFrame(columns=['Артикул производителя', 'Штрихкод производителя', 'Баркод Wildberries'])
        return pd.DataFrame(columns=['Артикул производителя', 'Штрихкод производителя', 'Баркод Wildberries'])

    def _save_new_barcodes(self):
        """Сохраняет обновленный DataFrame с новыми штрихкодами."""
        try:
            self.wb_marking_db.to_csv(NEW_BARCODES_FILE, index=False, mode='w')
        except Exception as e:
            self.show_log(f"❌ Ошибка сохранения новых ШК: {e}", is_error=True)

    def update_supply_id(self, *args):
        """Обрабатывает изменение ID поставки (ручное или через комбобокс)."""
        new_id = self.wb_supply_id_var.get().strip()
        setattr(self.app_context, "wb_fbs_supply_id", new_id)
        self._update_print_button_state()
        self.show_log(f"ID поставки обновлен: {new_id}")

    def setup_ui(self):
        """Создаёт интерфейс Wildberries FBS (только WB)."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)  # Панель управления справа
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        # Общие параметры для всех кнопок управления
        btn_params = {
            "width": 160,
            # "height":35,
            "corner_radius": 8,
            "font": ("Arial", 12, "bold")
        }
        # --- Левая часть: Таблица и Лог ---
        mrow = 0
        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.grid(row=mrow, column=0, sticky="nsew", padx=10, pady=10)
        main_frame.grid_rowconfigure(mrow, weight=0)
        main_frame.grid_columnconfigure(mrow, weight=1)

        # Верхнее окно сканирования
        ctk.CTkLabel(main_frame, text="Автосборка:",
                     font = ctk.CTkFont(size=16, weight="bold") #self.font
                     ).grid(row=mrow, column=0, padx=10,pady=(0,0))
        mrow += 1
        main_frame.grid_rowconfigure(mrow, weight=0)

        # === НАЧАЛО ИЗМЕНЕНИЙ ===
        # Создаем контейнер для строки ввода и чекбокса, чтобы они были рядом
        input_container = ctk.CTkFrame(main_frame, fg_color="transparent")
        input_container.grid(row=mrow, column=0, padx=10, pady=(0, 0))  # sticky="ew",

        # Поле ввода (теперь внутри контейнера)
        self.scan_entry = ctk.CTkEntry(input_container,
                                       placeholder_text="Автосборка",
                                       width=300, font=self.font)
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
        control_panel = ctk.CTkFrame(self, width=300, fg_color="transparent")
        control_panel.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        control_panel.grid_columnconfigure(0, weight=1)

        row = 0
        ctk.CTkLabel(control_panel, text="ДАННЫЕ",
                     font=("Segoe UI", 11, "bold"),
                     text_color="gray").grid(row=row,
                                          column=0,
                                          sticky="w",
                                          padx=15,
                                          pady=(0, 0))
        row += 1
        ctk.CTkButton(control_panel, text="Загрузить NEW заказы из WB",
                      command=lambda: self.load_wb_orders_add(new_flag=True),
                      # font=self.font,
                      # fg_color="blue",
                      state="normal",
                      **btn_params).grid(row=row, column=0, padx=10, pady=(10, 5), sticky="ew")
        row += 1
        # 1. Кнопка "Подгрузить заказы из WB"
        ctk.CTkButton(control_panel, text="Подгрузить заказы из WB",
                      command=self.load_wb_orders_add,
                      # font=self.font,
                      # fg_color="blue",
                      state="normal",
                      **btn_params).grid(row=row, column=0, padx=10, pady=(10, 5), sticky="ew")
        row += 1
        ctk.CTkButton(control_panel, text="Обновить статусы заказа",
                      command=self.update_orders_statuses_from_api,
                      # font=self.font,
                      # fg_color="gray",
                      fg_color="#2c3e50",
                      hover_color="#34495e",
                      state="normal",
                      **btn_params).grid(row=row, column=0, padx=10, pady=(10, 5), sticky="ew")
        row += 1
        # --- Разделитель ---
        ctk.CTkFrame(control_panel, height=2, fg_color="gray40").grid(row=row, column=0, sticky="ew", padx=10, pady=10)
        row += 1

        # === БЛОК 2: СКАНИРОВАНИЕ И ВВОД ===
        ctk.CTkLabel(control_panel, text="ОПЕРАЦИИ",
                     font=("Segoe UI", 11, "bold"),
                     text_color="gray").grid(row=row,
                                            column=0,
                                            sticky="w",
                                            padx=15,
                                            pady=(0, 0))
        row += 1
        self.scan_entry2 = ctk.CTkEntry(control_panel,
                                        placeholder_text="Сканируйте Штрихкод",
                                        width=160,
                                        # height=40,
                                        font=("Arial", 14))
        self.scan_entry2.bind('<Return>', lambda event: self.handle_barcode_input(self.scan_entry2.get()))
        self.scan_entry2.grid(row=row, column=0, padx=10, pady=(0, 10), sticky="ew")
        row += 1
        # Чекбокс2
        self.checkbox2 = ctk.CTkCheckBox(control_panel, text="Режим поиск\ввод",
                                         variable=self.select_barcode_update,
                                         font=("Segoe UI", 12))
        self.checkbox2.grid(row=row, column=0, sticky="w", padx=10, pady=0)
        row += 1

        # 3. Поле сканирования КИЗ (Маркировки) (Требование 3)
        # ctk.CTkLabel(control_panel, text="Сканирование КИЗ (ЧЗ):", font=self.font).grid(row=row, column=0, padx=10,
        #                                                                                 pady=(10, 0), sticky="w")
        # row += 1
        self.cis_entry = ctk.CTkEntry(control_panel,
                                      placeholder_text="Сканируйте Код Маркировки",
                                      width=160,
                                      # height=40,
                                      font=("Arial", 14))
        self.cis_entry.bind('<Return>', lambda event: self.handle_cis_input(self.cis_entry.get()))
        self.cis_entry.grid(row=row, column=0, padx=10, pady=5, sticky="ew")
        row += 1

        # Создание чекбокса
        self.checkbox = ctk.CTkCheckBox(control_panel, text="АвтоПечать",
                                        variable=self.check_var,
                                        font=("Segoe UI", 12))
        self.checkbox.grid(row=row, column=0, padx=10, pady=5, sticky="w")
        row += 1
        # 8. Кнопка "Очистить КИЗ"
        self.transfer_button = ctk.CTkButton(control_panel, text="Очистить КИЗ",
                                             command=self.clear_cis_button,
                                             fg_color="#c0392b",
                                             hover_color="#e74c3c",
                                             state="normal",
                                             **btn_params)
        self.transfer_button.grid(row=row, column=0, padx=10, pady=10, sticky="ew")
        row += 1
        # 4. Кнопка "Добавить к поставке"
        self.assembly_button = ctk.CTkButton(control_panel, text="Добавить к поставке",
                                             command=self.finalize_manual_assembly,
                                             # font=self.font,
                                             fg_color="green",
                                             state="normal",
                                             **btn_params)
        self.assembly_button.grid(row=row, column=0, padx=10, pady=10, sticky="ew")
        row += 1

        # 4. Кнопка "Привязать КИЗ к заказу"
        self.assign_product = ctk.CTkButton(control_panel, text="Привязать КИЗ к заказу",
                                            command=self.assign_product_label,
                                            # font=self.font,
                                            fg_color="green",
                                            state="disabled",
                                            **btn_params)
        self.assign_product.grid(row=row, column=0, padx=10, pady=10, sticky="ew")
        row += 1
        # 7. Кнопка "Печать Этикетки" (Требование 2)
        self.print_button = ctk.CTkButton(control_panel, text="🖨️ Печать Этикетки",
                                          command=self.print_label_from_button,
                                          # font=self.font,
                                          fg_color="gray",
                                          state="disabled",
                                          **btn_params)
        self.print_button.grid(row=row, column=0, padx=10, pady=10, sticky="ew")
        row += 1
        # --- Разделитель ---
        ctk.CTkFrame(control_panel, height=2, fg_color="gray").grid(row=row, column=0, padx=10, pady=10, sticky="ew")
        row += 1

        # 5. Кнопка "Создать поставку" (Требование 4)
        ctk.CTkButton(control_panel, text="📦 Создать Поставку WB",
                      command=self.create_new_supply,
                      # font=self.font,
                      **btn_params).grid(
            row=row, column=0, padx=10, pady=10, sticky="ew")
        row += 1

        # 5. Кнопка "Обновить активные Поставки"
        (ctk.CTkButton(control_panel, text="Обновить активные Поставки",
                      command=self.order_relation_supply,
                      # font=self.font,
                      fg_color="#2c3e50",
                      hover_color="#34495e",
                      **btn_params).grid(
                    row=row, column=0, padx=10, pady=10, sticky="ew"))
        row += 1

        # 6. Выбор/Просмотр Поставки
        ctk.CTkLabel(control_panel, text="Активная Поставка:", font=self.font).grid(row=row, column=0, padx=10,
                                                                                    pady=(5, 0), sticky="w")
        row += 1
        self.supply_combobox = ctk.CTkComboBox(control_panel,
                                               variable=self.wb_supply_id_var,
                                               values=[""],
                                               # font=self.font,
                                               state="readonly",
                                               command=self._update_supply_combobox_selection,
                                               **btn_params
                                               )
        self.supply_combobox.grid(row=row, column=0, padx=10, pady=(0, 10), sticky="ew")
        row += 1


        # 8. Кнопка "В доставку"
        self.transfer_button = ctk.CTkButton(control_panel, text="Передать поставку в доставку",
                                             command=self.transfer_supply_to_delivery_button,
                                             # font=self.font,
                                             fg_color="blue",
                                             state="normal",
                                             **btn_params)
        self.transfer_button.grid(row=row, column=0, padx=10, pady=10, sticky="ew")
        row += 1
        # Убедимся, что все элементы управления выровнены по верху
        control_panel.grid_rowconfigure(row, weight=1)

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
            textlbl= self.marketplace +' FBS'
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
        self.update_supply_combobox()
        self.restore_entry_focus()

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
        self.after(5, lambda: self._handle_row_selection(None))


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
            status_tag = self.get_row_status(row)

            # Проверяем, существует ли строка в Treeview
            if status_tag and self.data_table.tree.exists(row_id):
                # Применяем нужный тег
                self.data_table.tree.item(row_id, tags=(status_tag,))

        self.data_table.tree.tag_configure("found", background="#FFFACD")  # Желтый - найден штрихкод или товар в БД
        self.data_table.tree.tag_configure("missing", background="#FFB6C1")  # Красный - товар не найден в БД
        self.data_table.tree.tag_configure("completed", background="#9966CC")  # Аметист - поставка в доставке
        self.data_table.tree.tag_configure("confirm", background="#CCFFCC")  # Очень бледный, почти белый с легким зеленым оттенком.- есть и штрихкод, и маркировка
        self.data_table.tree.tag_configure("collected order",background="#90EE90")  # Зеленый - заказ собран

    # --- МЕТОДЫ ОБРАБОТКИ СКАНИРОВАНИЯ ---
    def handle_barcode_input(self, input_value: str):
        """
        Обрабатывает ввод штрихкода.
        """
        self.editing = True
        barcode = input_value.strip()
        self.scan_entry2.delete(0, 'end')  # Очищаем поле сразу
        if not barcode:
            self.show_log("❌ Ошибка: Введите штрихкод.", is_error=True)
            self.start_auto_focus()
            return
        if not self.select_barcode_update.get():
            self.show_log("Обрабатываем ситуацию когда надо установить штрихкод")
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
                    self.start_auto_focus()
                    return
            # Если выбрана строка, привязываем штрихкод к ней
            row = self.fbs_df.loc[self.selected_row_index]
            # Сохраняем штрихкод
            self.fbs_df.at[self.selected_row_index, "Штрихкод"] = barcode
            self.data_table.select_row(self.selected_row_index)
            # Сохраняем в основную базу данных
            self.save_to_main_database(row, barcode)
            self.update_table()
            # # Сохраняем в контекст
            self.save_data_to_context()
            play_success_scan_sound()
            self.show_log(f"✅ Штрихкод {barcode} привязан. Теперь можно ввести код маркировки, при необходимости...")
            # Переключаемся на ввод маркировки
            self.input_mode = "marking"
            self.pending_barcode = barcode
        else:
            self.show_log("Обрабатываем ситуацию когда ищем строку с заданным штрихкодом")
            self.show_log(f"Сканирование: {barcode}")

            # 1. Поиск: ищем  Штрихкод производителя в текущих заказах
            # matches = self.fbs_df[(self.fbs_df['Штрихкод'].astype(str) == str(self.current_barcode))
            #                         & (self.fbs_df["Статус обработки"] == self.assembly_status[0])].copy()
            matches = self.fbs_df[(self.fbs_df['Штрихкод'].astype(str) == str(barcode))
                                  & (self.fbs_df["Статус обработки"] == self.assembly_status[0])
                                  & (~self.fbs_df["Статус заказа"].isin(['indefinite', 'complete', 'cancel']))
                                  ]
            row_index = 0
            if not matches.empty:
                # --- Логика Сборки по сканированию (автоматическая) ---
                row_index = matches.index[0]
                # logger.info('row_index',row_index)
                row = self.fbs_df.loc[row_index]
                self.selected_row_index = row_index
               # --- ДОБАВЛЕНИЕ ЛОГИКИ ВЫДЕЛЕНИЯ И ФОКУСА - --

                self.data_table.select_row(row_index) # выделение строки
                play_success_scan_sound()
                # if self.check_var.get():
                #     self.show_log(f"Печатаем этикетку {self.current_barcode} ШК  ")
                #     logger.info(f'Печатаем этикетку {self.current_barcode} ШК  ')
                #     self.print_label_from_button()
            # 2. Несовпадение: возможно, это новый ШК или артикул для добавления
            else:
                # self.handle_unmatched_barcode(self.current_barcode) Этот метод реализовать позже
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

    def handle_barcode_input_for_smart(self, barcode: str):
        """ Обрабатывает ввод штрихкода,
        в автосборке для handle_barcode_input_auto_smart"""
        if not self.select_barcode_update.get():
            self.show_log("Обрабатываем ситуацию когда надо установить штрихкод")
            if self.selected_row_index is not None:
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
            # Сохраняем данные в контекст
            self.save_data_to_context()

            play_success_scan_sound()
            self.show_log(f"✅ Штрихкод {barcode} привязан. Теперь введите код маркировки...")

            # Переключаемся на ввод маркировки
            # self.input_mode = "marking"
            self.pending_barcode = barcode
            # self.scanning_label.configure(text="Введите код маркировки... 🏷️")

            # Очищаем поле ввода
            self.scan_entry.delete(0, "end")
        else:
            self.show_log("Обрабатываем ситуацию когда ищем строку с заданным штрихкодом")
            # Если строка не выбрана, ищем по штрихкоду
            matches = self.fbs_df[(self.fbs_df['Штрихкод'].astype(str) == str(barcode))
                                  & (self.fbs_df["Статус обработки"] == self.assembly_status[0])
                                  & (~self.fbs_df["Статус заказа"].isin(['indefinite', 'complete', 'cancel']))
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
                # Если у строки уже есть код маркировки, показываем информацию
                # self.input_mode = "marking"
                self.pending_barcode = barcode
                # self.scanning_label.configure(text="Введите код маркировки... 🏷️")
                self.show_log(f"Найдена строка: Заказ {row['Номер заказа']}. Введите код маркировки...")
                self.scan_entry.delete(0, "end")
                self.restore_entry_focus()

            else:
                self.show_log("Ошибка: Штрихкод не найден в заказах", is_error=True)
                play_unsuccess_scan_sound()
            self.restore_entry_focus()

    def handle_marking_input_smart(self, marking_code: str):
        """Обрабатывает ввод кода маркировки, для поля автосборки"""
        label_printer = LabelPrinter(self.app_context.printer_name)

        if self.selected_row_index is not None:
            row = self.fbs_df.loc[self.selected_row_index]
            # Записываем код маркировки в таблицу, если значение не пусто
            if marking_code:
                self.show_log("Обрабатываем введенный код маркировки")
                self.fbs_df.at[self.selected_row_index, "Код маркировки"] = marking_code
                self.show_log(f"✅ Код маркировки {marking_code} привязан к заказу {row['Номер заказа']}")

            # Печатаем этикетку после добавления заказа в поставку
            self.finalize_manual_assembly()
            # Привяжем код маркировки к метаданным заказа WB
            self.assign_product_label(row, marking_code)
            # Занесем код маркировки в Справочник КИЗ
            self.assign_product_label_internal_directory(marking_code, row)

            if self.check_var.get():
                self.show_log(f"Печатаем этикетку {self.pending_barcode} ШК  ")
                self.print_label_from_button()

            play_success_scan_sound()
            # Сохраняем в контекст
            self.save_data_to_context()
            # Обновляем таблицу
            self.update_table()

            # Сбрасываем состояние
            # self.input_mode = "barcode"
            self.pending_barcode = None
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
            matches = self.fbs_df[ (self.fbs_df['Штрихкод'].astype(str) == str(barcode))
                                  & (self.fbs_df["Статус обработки"] == self.assembly_status[0])
                                  & (~self.fbs_df["Статус заказа"].isin(['indefinite', 'complete', 'cancel']))
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
                # Если у строки уже есть код маркировки, показываем информацию
                if row["Код маркировки"] == "" or pd.isna(row["Код маркировки"]):
                    # Запрашиваем код маркировки
                    self.input_mode = "marking"
                    self.pending_barcode = barcode
                    # self.scanning_label.configure(text="Введите код маркировки... 🏷️")
                    self.show_log(f"Найдена строка: Заказ {row['Номер заказа']}. Введите код маркировки...")

                else:
                    self.show_log(
                        f"Найдена строка: Заказ {row['Номер заказа']}, маркировка: {row['Код маркировки']}")
                    self.selected_row_index = None
                    self.show_log("Строка уже обработана");

                self.scan_entry.delete(0, "end")
                self.restore_entry_focus()

            else:
                self.show_log("Ошибка: Штрихкод не найден в заказах", is_error=True)
                play_unsuccess_scan_sound()

    def assign_product_label(self, row=None, marking_code=None):
        if row is None:
            if self.selected_row_index is None:
                self.show_log("❌ Выберите активную строку для привязки КИЗ.", is_error=True)
                return
            row = self.fbs_df.loc[self.selected_row_index]
            marking_code = self.fbs_df.at[self.selected_row_index, "Код маркировки"].astype(str)

        if marking_code:
            # Здесь по API WB Закрепить за сборочным заданием код маркировки товара Честный знак.
            if row["Статус заказа"] == self.define_status[2]:
                order_id = int(row["Номер заказа"])
                try:
                    sgtin = {"sgtins": [marking_code]}
                    self.api.assign_product_labeling(order_id=order_id, sgtins=sgtin)
                    self.show_log(
                        f"❌ Успешно в API WB привязан код маркировки {marking_code} к номеру заказа {order_id} ")
                except Exception as e:
                    logger.info(f"❌ Ошибка API WB привязки кода маркировки {marking_code} к номеру заказа {order_id}: {str(e)}")
                    self.show_log(
                        f"❌ Ошибка API WB привязки кода маркировки {marking_code} к номеру заказа {order_id}: {str(e)}",
                        is_error=True)
            else:
                self.show_log(
                    f"❌ Ошибка API WB привязки кода маркировки, 'Статус заказа' не переведен в 'confirm'",
                    is_error=True)

    def assign_product_label_internal_directory(self, marking_code, row=None):
        if not marking_code:
            if row is None:
                if self.selected_row_index is None:
                    self.show_log("❌ Выберите активную строку для привязки маркировки Честный знак.", is_error=True)
                    return
                row = self.fbs_df.loc[self.selected_row_index]
                self.show_log(f"Активная строка не была задана, используем активный индекс, в заказе {row['Номер заказа']} ")
                marking_code = self.fbs_df.at[self.selected_row_index, "Код маркировки"]
            else:
                marking_code = row["Код маркировки"]
                self.show_log(
                    f"Для определения кода маркировки, использовалась переданная строка, в заказе {row['Номер заказа']} ")
            # marking_code = self._normalize_cis_to_list(marking_code)
        if marking_code:
            try:
                # Создаем новую запись
                new_row = pd.DataFrame([{
                    "Номер отправления": row["Номер заказа"],
                    "Код маркировки": marking_code,
                    "Цена": row["Цена"],
                    "sku": row["Штрихкод WB"],
                    "Артикул поставщика": row["Артикул поставщика"],
                    "Размер": row["Размер"],
                    "Время добавления": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), # pd.Timestamp.now()
                    "Маркетплейс":'WB'
                }]).explode("Код маркировки", ignore_index=True)

                # ---  СИНХРОНИЗАЦИЯ С БД ---
                # --- обновление marking_codes ---
                try:
                    # Передаем только новые сформированные строки
                    self.db.sync_dataframe(new_row, "marking_codes", ["Код маркировки"])
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
                    f"❌ Ошибка записи КИЗ {marking_code} в Основной справочник КИЗ{row['Номер заказа']} и товара {row['Штрихкод WB']}: {str(e)}",
                    is_error=True)
        else:
            # предусмотреть удаление строки по sku если есть запись
            self.show_log(f"Отсутствует КИЗ для {row['Номер заказа']} и товара {row['Штрихкод WB']}.")

    def handle_marking_input(self, marking_code):
        """Обрабатывает ввод кода маркировки, для поля автосборки"""
        label_printer = LabelPrinter(self.app_context.printer_name)

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

                self.fbs_df.at[self.selected_row_index, "Код маркировки"] = marking_code

            # Печатаем этикетку после добавления заказа в поставку
            self.finalize_manual_assembly()
            # Привяжем код маркировки к метаданным заказа WB
            # --- ОТПРАВКА В WB API ---
            try:
                self.assign_product_label(row, marking_code)
                self.show_log(f"✅ Код маркировки {marking_code} привязан к заказу {row['Номер заказа']}")
            except Exception as e:
                # Если это ошибка 409, значит КИЗ уже привязан — это не критично
                if "409" in str(e):
                    self.show_log(f"ℹ️ КИЗ для заказа {row['Номер заказа']} уже был привязан ранее (WB вернул 409).",
                                  is_error=False)
                else:
                    self.show_log(f"❌ Ошибка API WB привязки КИЗ: {e}", is_error=True)
                    # Не прерываем процесс, так как в локальную базу мы уже всё записали

            # Занесем код маркировки в Справочник КИЗ
            self.assign_product_label_internal_directory(marking_code,row)

            if self.check_var.get():
                self.show_log(f"Печатаем этикетку {self.pending_barcode} ШК  ")
                self.print_label_from_button()

            play_success_scan_sound()
            # Сохраняем в контекст
            self.save_data_to_context()
            # Обновляем таблицу
            self.update_table()

            # Сбрасываем состояние
            self.selected_row_index = None
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
            # self.scan_entry.delete(0, "end")
            self.cis_entry_focus()
            return

        row = self.fbs_df.loc[self.selected_row_index]
        self.fbs_df.loc[self.selected_row_index, 'Код маркировки'] = cis_code

        # --- ОТПРАВКА В WB API ---
        try:
            self.assign_product_label(row, cis_code)
            self.show_log(f"✅ КИЗ ({cis_code[:10]}...) записан для заказа {row['Номер заказа']}.", is_error=False)
        except Exception as e:
            # Если это ошибка 409, значит КИЗ уже привязан — это не критично
            if "409" in str(e):
                self.show_log(f"КИЗ для заказа {row['Номер заказа']} уже был привязан ранее (WB вернул 409).")
            else:
                self.show_log(f"❌ Ошибка API WB привязки КИЗ: {e}", is_error=True)
                # Не прерываем процесс, так как в локальную базу мы уже всё записали
        # Занесем код маркировки в Справочник КИЗ
        self.assign_product_label_internal_directory(cis_code, row)
        if self.check_var.get():
            self.show_log(f"Печатаем этикетку {self.pending_barcode} ШК  ")
            self.print_label_from_button()
        # Сохраняем в контекст
        self.save_data_to_context()
        self.update_table()
        self.start_auto_focus()

    def clear_cis_button(self):
        if self.selected_row_index is None:
            self.show_log("❌ Сначала выберите строку или отсканируйте товар.", is_error=True)
            play_unsuccess_scan_sound()
            self.start_auto_focus()
            return
        row = self.fbs_df.loc[self.selected_row_index]
        posting_number = row["Номер заказа"]

        # --- НОВЫЙ БЛОК: УДАЛЕНИЕ ИЗ БД ---
        self.db.delete_marking_codes_by_posting(posting_number)
        # ----------------------------------

        self.fbs_df.at[self.selected_row_index, 'Код маркировки'] = ''
        self.show_log(f"✅ КИЗ очищены для отправления {row['Номер отправления']} и товара {row['sku']}.")
        # Сохраняем в контекст
        self.save_data_to_context()
        self.update_table()
        self.data_table.select_row(self.selected_row_index)

    def save_to_main_database(self, row, barcode):
        """Сохраняет штрихкод в основную базу данных без затирания лишних полей"""
        if self.selected_row_index is None and row is None:
            self.show_log("Сохранение пропущено: активная строка не выбрана.")
            return

        if row is None:
            row = self.fbs_df.loc[self.selected_row_index]

        # Если barcode не передан явно, берем его из строки или аргумента
        final_barcode = barcode if barcode else row.get('Штрихкод')

        if not final_barcode:
            self.show_log(f"❌ Ошибка сохранения. Штрихкод не определился!", is_error=True)
            return

        # Подготавливаем данные, очищая их от лишних пробелов
        vendor_code = str(row["Артикул поставщика"]).strip()
        size = str(row["Размер"]).strip()
        wb_barcode = str(row.get("Штрихкод WB", "")).strip()

        # 1. ПОДГОТОВКА ДАННЫХ ДЛЯ БД
        # Важно: Включаем только те поля, которые мы ДЕЙСТВИТЕЛЬНО хотим обновить сейчас
        update_data = {
            "Артикул производителя": vendor_code,
            "Размер": size,
            "Штрихкод производителя": str(final_barcode).strip(),
            "Бренд": str(row.get("Бренд", "")).strip(),
            "Наименование поставщика": str(row.get("Бренд", "")).strip()
        }

        # Добавляем WB баркод только если он не пустой, чтобы не затереть имеющийся
        if wb_barcode:
            update_data["Баркод  Wildberries"] = wb_barcode

        df_new = pd.DataFrame([update_data])

        try:
            # 2. УМНАЯ СИНХРОНИЗАЦИЯ (Проверьте, поддерживает ли ваш sync_dataframe частичное обновление)
            # Если ваш db.sync_dataframe делает REPLACE, лучше использовать специальный метод "update_or_insert"
            self.db.sync_dataframe(df_new, "product_barcodes", ["Артикул производителя", "Размер"])
            self.show_log(f"✅ БД: Данные для {vendor_code} ({size}) обновлены.")
        except Exception as e:
            self.show_log(f"❌ Ошибка БД: {e}", is_error=True)

        self.save_data_to_context()  # Не забываем сохранить pkl


    # --- МЕТОДЫ УПРАВЛЕНИЯ UI И ДАННЫМИ ---

    # def fetch_product_info_by_wb_barcode(self, wb_barcode: str) -> Optional[Dict]:
    #     """
    #     Ищет информацию о товаре в общей базе данных (self.app_context.df)
    #     по Баркоду Wildberries (Баркод  Wildberries).
    #
    #     :param wb_barcode: Баркод Wildberries, полученный из API.
    #     :return: Словарь с данными для заполнения полей заказа или None.
    #     """
    #     # Проверяем наличие и содержимое общей базы данных
    #     if self.app_context.df is None or self.app_context.df.empty:
    #         return None
    #
    #     # Название столбца в загруженном CSV/Excel файле (с учетом двух пробелов)
    #     WB_BARCODE_COL = "Баркод  Wildberries"
    #
    #     if WB_BARCODE_COL not in self.app_context.df.columns:
    #         logger.info(f"ERROR: Столбец '{WB_BARCODE_COL}' не найден в базе данных.")
    #         return None
    #
    #     # Очистка и приведение типов для безопасного сравнения
    #     search_barcode = str(wb_barcode).strip()
    #
    #     # 1. Фильтруем базу данных, приводя столбец к строковому типу
    #     # Используем .astype(str).str.strip() для надежного сравнения
    #     matches = self.app_context.df[
    #         self.app_context.df[WB_BARCODE_COL].astype(str).str.strip() == search_barcode
    #         ]
    #
    #     if matches.empty:
    #         return None
    #
    #     # 2. Берем первую найденную строку и извлекаем данные
    #     product_row = matches.iloc[0]
    #
    #     # 3. Составляем словарь для обновления строки заказа
    #     # Ключи словаря должны соответствовать именам столбцов в self.fbs_df
    #     result = {}
    #
    #     # Соответствие полей:
    #     # Артикул поставщика (заказ) <- Артикул производителя (база)
    #     if "Артикул производителя" in product_row:
    #         result["Артикул поставщика"] = str(product_row["Артикул производителя"]).strip()
    #
    #     # Размер (заказ) <- Размер (база)
    #     if "Размер" in product_row:
    #         result["Размер"] = str(product_row["Размер"]).strip()
    #
    #     # Штрихкод (заказ, наш внутренний) <- Штрихкод производителя (база)
    #     if "Штрихкод производителя" in product_row:
    #         result["Штрихкод"] = str(product_row["Штрихкод производителя"]).strip()
    #
    #     # Бренд (заказ) <- Бренд (база)
    #     if "Бренд" in product_row:
    #         result["Бренд"] = str(product_row["Бренд"]).strip()
    #
    #     return result
    #
    # def load_wb_orders(self):
    #     """Загружает новые сборочные задания WB через API."""
    #     debug_info = False
    #
    #     try:
    #         self.show_log("WB API: Запрос новых сборочных заданий...")
    #         orders_data = self.api.get_orders(params={'flag': 0})
    #         orders = orders_data.get('orders', [])
    #
    #         if not orders:
    #             self.show_log("✅ Новых сборочных заданий не найдено.", is_error=False)
    #             return
    #
    #         new_orders_df = pd.DataFrame(orders)
    #         if debug_info:
    #             self.debug_print_first_row(new_orders_df, 2)
    #             self.debug_print_first_row(new_orders_df, 3)
    #         else:
    #             # Создаем ключевые колонки и статусы (сохраняем столбцы, как в self.fbs_df) ВРЕМЕННО ЗАКОММЕНТИРОВА нижние строки
    #             new_orders_df['Номер заказа'] = new_orders_df['id'] #.astype(str)
    #             new_orders_df['Служба доставки'] = self.marketplace
    #             new_orders_df['Цена'] = (new_orders_df['convertedPrice'] / 100).astype(str)  # 'finalPrice', 'salePrice', 'convertedFinalPrice'
    #             new_orders_df['Артикул поставщика'] = new_orders_df['article'].astype(str)
    #             new_orders_df['Размер'] = new_orders_df['chrtId'].astype(str)
    #             new_orders_df['Количество'] = 1
    #             new_orders_df['Статус заказа'] = self.define_status[1]
    #             new_orders_df['Статус обработки'] = self.assembly_status[0]
    #
    #             def extract_first_sku(sku_list):
    #                 """
    #                 Извлекает первый элемент из списка skus.
    #                 Возвращает NaN, если список пуст, None, или не является списком.
    #                 """
    #                 if isinstance(sku_list, list) and sku_list:
    #                     return sku_list[0]
    #                 return ''
    #
    #             # Создаем новый столбец 'Штрихкод', применяя функцию к колонке 'skus'
    #             new_orders_df['Штрихкод WB'] = new_orders_df['skus'].apply(extract_first_sku)
    #
    #             # Добавляем отсутствующие колонки из self.fbs_df, чтобы избежать ошибки при concat
    #             for col in self.fbs_df.columns:
    #                 if col not in new_orders_df.columns:
    #                     new_orders_df[col] = ''
    #             try:
    #                 # Автоматически заполняем штрихкоды из основной базы данных
    #                 if self.df_barcode_WB is not None:
    #                     for idx, row in new_orders_df.iterrows():
    #                         # --- ИСПОЛЬЗУЕМ НОВУЮ ФУНКЦИЮ ---
    #                         additional_info = self.fetch_product_info_by_wb_barcode(row['Штрихкод WB'])
    #                         if additional_info:
    #                             # Создаем базовую строку заказа
    #                             new_orders_df.loc[idx, "Размер"] = additional_info["Размер"]
    #                             new_orders_df.loc[idx, "Артикул поставщика"] = additional_info["Артикул поставщика"]
    #                             new_orders_df.loc[idx, "Штрихкод"] = additional_info["Штрихкод"]
    #                             new_orders_df.loc[idx, "Бренд"] = additional_info["Бренд"]
    #             except Exception as e:
    #                 self.show_log(f"❌ Ошибка при попытке сопоставить строки с внутренней базой: {e}", is_error=True)
    #                 logger.info(f"❌ Ошибка при попытке сопоставить строки с внутренней базой: {e}")
    #             # Объединяем с текущей таблицей (удаляя дубликаты по 'Номер заказа')
    #             self.fbs_df = pd.concat([self.fbs_df, new_orders_df], ignore_index=True)
    #             self.fbs_df = self.fbs_df.drop_duplicates(subset=['Номер заказа'], keep='last')
    #
    #             # # Очищаем таблицу от строк, где нет номера заказа (могут появиться при ошибке API)
    #             # self.fbs_df = self.fbs_df[self.fbs_df['Номер заказа'] != ''].copy()
    #             # Сохраняем в контекст
    #             self.save_data_to_context()
    #             self.update_table()
    #             self.show_log(f"✅ Загружено {len(orders)} новых сборочных заданий WB.")
    #
    #     except Exception as e:
    #         self.show_log(f"❌ Ошибка загрузки заказов WB: {e}", is_error=True)
    #         logger.info(f"❌ Ошибка загрузки заказов WB: {e}")
    #         play_unsuccess_scan_sound()

    def load_wb_orders_add(self, new_flag:bool = False):
        """Загружает новые и в работе сборочные задания WB через API."""
        debug_info = False
        target_db_columns = [
            'Баркод  Wildberries',  # Ключ для соединения
            'Артикул производителя',
            'Размер',
            'Штрихкод производителя',  # Штрихкод производителя/внутренний
            'Бренд']
        try:
            if new_flag:
                self.show_log("WB API: Запрос новых сборочных заданий...")
                orders_data = self.api.get_orders(params={'flag': 0})
                orders = orders_data.get('orders', [])
            else:
                self.show_log("WB API: Подгружаем сборочные задания...")
                orders_data = self.api.get_info_about_orders()
                orders = orders_data.get('orders', [])

            if not orders:
                self.show_log("✅ Новых сборочных заданий не найдено.", is_error=False)
                return

            new_orders_df = pd.DataFrame(orders)

            # Создаем ключевые колонки и статусы (сохраняем столбцы, как в self.fbs_df) ВРЕМЕННО ЗАКОММЕНТИРОВА нижние строки
            new_orders_df['Номер заказа'] = new_orders_df['id']  # .astype(str)
            new_orders_df['Служба доставки'] = self.marketplace
            new_orders_df['Цена'] = (new_orders_df['convertedPrice'] / 100).astype(str)
            # new_orders_df['Артикул поставщика'] = new_orders_df['article'].astype(str)
            # new_orders_df['Размер'] = new_orders_df['chrtId'].astype(str)
            new_orders_df['Количество'] = 1
            new_orders_df['Статус заказа'] = self.define_status[1] if new_flag else self.define_status[0]
            new_orders_df['Статус обработки'] = self.assembly_status[0]

            # Здесь вставить статусы и оставить строки только с нужными статусами
            new_orders_df['Штрихкод WB'] = new_orders_df['skus'].apply(
                lambda x: x[0] if isinstance(x, list) and len(x) > 0 else ""
            ).astype(str).str.strip()

            try:

                if self.fbs_df is None or self.fbs_df.empty:
                    new_orders_df_clean = new_orders_df.copy()
                else:
                    # Нам нужно исключить строки, которые УЖЕ есть в базе.
                    # Сравнивать нужно тоже по ['Номер заказа']
                    self.show_log(f"Создаем временный комбинированный ключ для существующей базы")
                    # 1. Создаем временный комбинированный ключ для существующей базы
                    existing_keys = (self.fbs_df['Номер заказа'].astype(str)).tolist()
                    # 2. Создаем такой же ключ для новых данных
                    new_keys = (new_orders_df['Номер заказа'].astype(str))
                    self.show_log(f"Фильтруем: оставляем только те строки new_orders_df")
                    # 3. Фильтруем: оставляем только те строки new_orders_df,
                    # чьих ключей НЕТ в existing_keys
                    # Ищем дубликаты
                    is_duplicate = new_keys.isin(existing_keys)
                    # Если все заказы уже есть
                    if is_duplicate.all():
                        self.show_log("WB API: Новых заказов не найдено (все уже есть в таблице).")
                        return
                    new_orders_df_clean = new_orders_df[~is_duplicate].copy()

                if not new_orders_df_clean.empty:
                    # --- ОБОГАЩЕНИЕ ДАННЫХ ИЗ БД (ВМЕСТО app_context.df) ---
                    self.show_log("WB: Обогащение данных из БД по Баркодам")
                    # 1. Извлекаем все баркоды из новых заказов (в WB это колонка 'Штрихкод')
                    wb_barcodes = new_orders_df['Штрихкод WB'].unique().tolist()
                    # 2. Тянем данные из базы
                    product_details_map = self.db.get_products_by_wb_barcodes(wb_barcodes)

                    if not product_details_map.empty:
                        self.show_log("Начинаем сопоставление данных с БД...")

                        # 1. Оставляем нужные колонки
                        product_details_map = product_details_map[target_db_columns].copy()

                        # 2. Вместо DROPNA используем FILLNA, чтобы не терять строки
                        for col in target_db_columns:
                            product_details_map[col] = product_details_map[col].fillna('').astype(str).str.strip()

                        # Переименовываем для интерфейса
                        product_details_map = product_details_map.rename(columns={
                            'Штрихкод производителя': 'Штрихкод',
                            'Артикул производителя': 'Артикул поставщика'
                        })

                        # Подготовка ключей для мерджа
                        new_orders_df_clean['Штрихкод WB'] = new_orders_df_clean['Штрихкод WB'].astype(str).str.strip()
                        product_details_map['Баркод  Wildberries'] = product_details_map['Баркод  Wildberries'].astype(
                            str).str.strip()

                        # Удаляем дубликаты только в справочнике
                        product_details_map.drop_duplicates(subset=['Баркод  Wildberries'], keep='first', inplace=True)

                        # 3. Выполняем LEFT MERGE
                        new_orders_df_clean = new_orders_df_clean.merge(
                            product_details_map,
                            left_on='Штрихкод WB',
                            right_on='Баркод  Wildberries',
                            how='left',
                            indicator=True
                        )

                        # Логируем результат для диагностики
                        matched_count = (new_orders_df_clean['_merge'] == 'both').sum()
                        unmatched_count = (new_orders_df_clean['_merge'] == 'left_only').sum()

                        if unmatched_count > 0:
                            unmatched_barcodes = new_orders_df_clean[new_orders_df_clean['_merge'] == 'left_only'][
                                'Штрихкод WB'].unique()
                            self.show_log(
                                f"⚠️ Внимание: {unmatched_count} заказов не найдены в базе ШК! Баркоды: {list(unmatched_barcodes)}",
                                is_error=True)

                        self.show_log(f"✅ Успешно сопоставлено: {matched_count} шт.")

                        # Удаляем техническую колонку индикатора
                        new_orders_df_clean.drop(columns=['_merge'], inplace=True)
                    else:
                        self.show_log(
                            "Основной справочник товаров (Штрихкод WB) пуст. Нет возможности получить Штрихкод")
                        return

                    # 5. Объединение с текущей базой (self.fbs_df)
                    self.show_log("5. Объединение с текущей базой (self.fbs_df)")
                    # Создаём датафрейм с правильными колонками, заполняя отсутствующие ''
                    new_orders_df_clean = new_orders_df_clean.reindex(columns=self.fbs_df.columns, fill_value='')
                    # Используем fillna('') для всего DataFrame или точечно
                    new_orders_df_clean = new_orders_df_clean.fillna('')

                    if self.fbs_df is None or self.fbs_df.empty:
                        self.fbs_df = new_orders_df_clean.copy()
                    else:
                        self.fbs_df = pd.concat([self.fbs_df, new_orders_df_clean], ignore_index=True)
                        # self.fbs_df = self.fbs_df.drop_duplicates(subset=['Номер заказа'], keep='last')
                    # Сохраняем в контекст
                    self.save_data_to_context()
                    # Обновляем отображение
                    self.update_table(self.fbs_df)
                    self.show_log(f"✅ Загружено {len(new_orders_df_clean)}  сборочных заданий WB.")
                else:
                    self.show_log("Все полученные товары уже есть в таблице.")
            except Exception as e:
                self.show_log(f"❌ Ошибка при попытке сопоставить строки с внутренней базой: {e}", is_error=True)

        except Exception as e:
            self.show_log(f"❌ Ошибка загрузки заказов WB: {e}", is_error=True)
            play_unsuccess_scan_sound()

    def create_new_supply(self):
        """Создает новую поставку WB (требование 4)."""
        supply_name = eg.enterbox("Введите название новой поставки:", "Создание поставки",
                                  f"Поставка от {datetime.now().strftime('%Y-%m-%d')}")

        if not supply_name:
            self.show_log("Создание поставки отменено.", is_error=True)
            return

        try:
            self.show_log(f"WB API: Создание поставки '{supply_name}'...")
            result = self.api.create_supply(supply_name)
            new_supply_id = result.get('id')

            if new_supply_id:
                self.wb_supply_id_var.set(new_supply_id)
                self.update_supply_combobox()  # Обновляем комбобокс
                self.show_log(f"✅ Новая поставка создана: {new_supply_id}", is_error=False)
            else:
                self.show_log(f"❌ WB API не вернул ID поставки.", is_error=True)

        except Exception as e:
            self.show_log(f"❌ Ошибка создания поставки: {e}", is_error=True)
            play_unsuccess_scan_sound()

    def update_supply_combobox(self):
        """Загружает список активных поставок и обновляет ComboBox."""
        try:
            # supplies_data = self.api.get_supplies(params={'status': 'active'})
            # supplies = supplies_data.get('supplies', [])

            supply_ids = self.getting_supplies()

            if not supply_ids:
                self.supply_combobox.configure(values=["<Нет активных поставок>"])
                # Если текущее значение - реальный ID, не сбрасываем его
                if self.wb_supply_id_var.get() not in supply_ids:
                    self.wb_supply_id_var.set("<Нет активных поставок>")
            else:
                current_id = self.wb_supply_id_var.get()
                if current_id and current_id not in supply_ids:
                    supply_ids.insert(0, current_id)

                self.supply_combobox.configure(values=supply_ids)

                if not current_id or current_id not in supply_ids:
                    self.wb_supply_id_var.set(supply_ids[0])

        except Exception as e:
            self.show_log(f"❌ Ошибка загрузки списка поставок: {e}", is_error=True)
            self.supply_combobox.configure(values=["<Ошибка загрузки>"])

    def _update_supply_combobox_selection(self, selected_id):
        """Обрабатывает выбор поставки из ComboBox."""
        self.wb_supply_id_var.set(selected_id)
        self.show_log(f"Выбрана поставка: {selected_id}")

    def getting_supplies(self) -> List[str]:
        """
        Получает список ID последних поставок (до 1000 шт) с поддержкой пагинации.
        Возвращает: список строк (Supply IDs), совместимый с итератором в order_relation_supply.
        """
        all_ids = []
        next_cursor = 0
        limit_per_request = 1000
        max_total = 1000

        try:
            self.show_log("Запрос списка поставок из WB API (с пагинацией)...")

            while len(all_ids) < max_total:
                # Вызываем API метод из wildberries_fbs_api.py
                response_data = self.api.get_supplies(params={
                    "limit": limit_per_request,
                    "next": next_cursor
                })

                if not response_data or "supplies" not in response_data:
                    break

                batch = response_data.get("supplies", [])
                if not batch:
                    break

                # Извлекаем только идентификаторы поставок (id), как того требует остальной код
                # Совместимость: возвращаем список строк
                current_batch_ids = [str(s.get("id")) for s in batch if s.get("id")]
                all_ids.extend(current_batch_ids)

                # Получаем курсор для следующей страницы
                next_cursor = response_data.get("next", 0)

                # Если API вернул next=0 или данных меньше лимита — мы на последней странице
                if next_cursor == 0 or len(batch) < limit_per_request:
                    break

            # Возвращаем ровно 1000 или меньше, если их всего меньше
            result_list = all_ids[:max_total]
            self.show_log(f"Найдено активных поставок: {len(result_list)}")
            return result_list

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Ошибка в getting_supplies: {error_msg}")

            if "401" in error_msg:
                messagebox.showerror("Ошибка авторизации",
                                     "Wildberries отклонил токен (401 Unauthorized).\n\n"
                                     "Пожалуйста, обновите API-токен в настройках.")
            else:
                self.show_log(f"Ошибка загрузки поставок: {error_msg}", is_error=True)

            # Возвращаем пустой список, чтобы цикл в order_relation_supply не упал
            return []

    def getting_supplies_old(self) -> List:
        debug_info = False
        start_next = 135615004
        response = self.api.get_supplies(params={"limit": 1000, "next": start_next})
        get_next = response['next']
        if debug_info:  logger.info('get_next:', get_next)
        if debug_info:  logger.info('Кол-во отданных записей:',len(response['supplies']))
        if len(response['supplies']) > 990:
            self.show_log("Есть необходимость настроить стартовую переменную. Обратитесь к разработчику !!!")
        list_supplies = [item['id'] for item in response['supplies'] if item['done'] == False]
        if debug_info:  logger.info('Кол-во активных поставок:', len(list_supplies))
        if debug_info:  logger.info(list_supplies)
        return list_supplies

    def order_relation_supply(self):
        debug_info = True
        list_supplies = self.getting_supplies()
    #  далее поработать получить сборочные задания к каждой поставке
        contain_supply = [{"supplyId":supplyId, "orders":self.api.get_orders_in_supply(supplyId)["orders"]} for supplyId in list_supplies]
        if debug_info:  logger.info('Кол-во активных поставок:', len(contain_supply))
        # обновляем значения в таблице
        if not contain_supply:
            self.show_log("Нет данных для обновления поставок.", is_error=False)
            return
        # здесь надо все проверить !!!!
        for item in  contain_supply:
            supplyId_t = item['supplyId']
            orders = [id_item['id'] for id_item in item['orders']]
            # logger.info(supplyId_t,': ',orders)
            if orders:
                mask = self.fbs_df['Номер заказа'].isin(orders)
                self.fbs_df.loc[mask, 'Номер поставки'] = supplyId_t
        # Сохраняем в контекст
        self.save_data_to_context()
        self.update_table()

                # --- МЕТОДЫ СБОРКИ И ПЕЧАТИ (Требования 1, 2, 3) ---
    def _handle_row_selection(self, row_index=None):
        """Обрабатывает выбор строки в таблице."""


        if row_index is None:
            # Деактивировать обе кнопки, если строка не выбрана
            # self.assembly_button.configure(state="disabled")
            # self.print_button.configure(state="disabled")
            return
        # logger.info(f"DEBUG:FBSModeWB _handle_row_select received index: {row_index}")
        self.selected_row_index = row_index
        try:
            row = self.fbs_df.loc[row_index]
        except KeyError:
            # Недопустимый индекс
            self.assembly_button.configure(state="disabled")
            self.print_button.configure(state="disabled")
            self.assign_product.configure(state="disabled")
            return

        is_processed = row["Статус заказа"] == self.define_status[2] # 'confirm'
        has_barcode = row["Штрихкод"] != ""
        has_marking = row["Код маркировки"] != ""
        has_articul = row["Артикул поставщика"] != ""
        has_size = row["Размер"] != ""

        # self.show_log(f"Статус заказа: {is_processed} Штрихкод: {has_barcode} Код маркировки: {has_marking}", is_error=True)
        # Условия для "Собрать заказ" (finalize_manual_assembly):
        # 1. Заказ НЕ обработан.
        # 2. Штрихкод и Код маркировки (если нужен, хотя тут мы просто проверяем наличие) заполнены.
        can_finalize = (not is_processed and has_articul and has_size) # and has_marking)

        # Условия для "Печать этикетки":
        # 1. Заказ уже Обработан.
        can_print = is_processed

        # 💡 УПРАВЛЕНИЕ КНОПКАМИ
        # self.assembly_button.configure(state="normal" if can_finalize else "disabled")
        self.print_button.configure(state="normal" if can_print else "disabled")
        self.assign_product.configure(state="normal" if can_print else "disabled")

    def _update_assembly_button_state(self):
        """Обновляет активность кнопки 'Собрать Заказ' (Требование 1)."""
        if self.selected_row_index is not None:
            row = self.fbs_df.loc[self.selected_row_index]
            if row['Статус заказа'] != self.define_status[1]: # 'new':
                self.assembly_button.configure(state="normal", fg_color="green")
                return

        self.assembly_button.configure(state="disabled", fg_color="gray")

    def _update_print_button_state(self):
        """Обновляет активность и цвет кнопки 'Печать Этикетки' (Требование 2)."""
        is_printable = False

        if self.selected_row_index is not None:
            row = self.fbs_df.loc[self.selected_row_index]
            # Активна, если собрано и добавлено в поставку
            if row['Статус заказа'] == self.define_status[2]:  # 'confirm': and bool(re.match(self.pattern, row['Номер поставки'])):
                is_printable = True

        if is_printable:
            self.print_button.configure(state="normal", fg_color="blue")
        else:
            self.print_button.configure(state="disabled", fg_color="gray")
            self.assign_product.configure(state="disabled", fg_color="gray")


    def finalize_manual_assembly(self):
        """
        Завершает ручную сборку выделенного заказа:
        1. Добавляет заказ в текущую поставку WB.
        2. Обновляет статус в таблице.
        3. Активирует кнопку печати.
        """
        debug_info = True
        selected_supply_id = self.wb_supply_id_var.get().strip()
        if self.selected_row_index is None:
            self.show_log("❌ Выберите строку заказа для завершения сборки.", is_error=True)
            return

        if selected_supply_id  is None:
            self.show_log("❌ Сначала выберите или создайте текущую поставку WB.", is_error=True)
            return

        row_index = self.selected_row_index
        order_id = int(self.fbs_df.loc[row_index, "Номер заказа"])
        # printer_target = self.app_context.printer_name

        self.show_log(
            f"🔗 Попытка завершить сборку заказа {order_id} и добавить его в поставку {selected_supply_id}...")
        if debug_info: logger.info(f"🔗 Попытка завершить сборку заказа {order_id} и добавить его в поставку {selected_supply_id}...")
        # 1. Добавление заказа в поставку WB (Шаг 5 - часть 1)
        try:
            self.show_log(f"WB API: Добавление заказа {order_id} в поставку {selected_supply_id}...")
            self.show_log(f"Тип данных order_id - {type(order_id)} Тип данных selected_supply_id - {type(selected_supply_id)} ")

            json_obj = self.api.add_order_to_supply(selected_supply_id, order_id)
            logger.info(json_obj)

            self.show_log(f"✅ Заказ {order_id} успешно добавлен в поставку {selected_supply_id} (WB API).")
            if debug_info: logger.info(f"✅ Заказ {order_id} успешно добавлен в поставку {selected_supply_id} (WB API).")
        except Exception as e:
            self.show_log(f"❌ Ошибка добавления заказа {order_id} в поставку {selected_supply_id}: {e}", is_error=True)
            if debug_info: logger.info(f"❌ Ошибка добавления заказа {order_id} в поставку {selected_supply_id}: {e}")
            return

        # 2. Обновление статуса в DataFrame (Шаг 6)
        try:
            # Устанавливаем статус и номер поставки
            self.fbs_df.loc[row_index, "Статус заказа"] = self.define_status[2] #'confirm'
            self.fbs_df.loc[row_index, "Номер поставки"] = selected_supply_id

            # Сохраняем в контекст
            self.save_data_to_context()
            # Обновление таблицы и раскраски
            self.update_table(self.fbs_df)

            # 3. Активация кнопки печати (Шаг 6 - часть 2 & Шаг 7)
            # Поскольку мы вызвали update_table, row_select должен быть вызван
            # (если есть привязка или мы делаем это явно)
            # self._handle_row_selection()
            self.print_button.configure(state="normal")  # Явная активация после успешной сборки

            play_success_scan_sound()
            self.show_log(f"🎉 Заказ {order_id} собран и готов к печати этикетки!", is_error=False)

        except Exception as e:
            self.show_log(f"❌ Критическая ошибка при обновлении статуса заказа {order_id}: {e}", is_error=True)

    # def _add_order_to_supply_and_print_need_delete(self, row, supply_id):
    #     """Вспомогательный метод: добавляет заказ в поставку и печатает этикетку."""
    #     order_id = row['Номер заказа']
    #     printer_target = self.app_context.printer_name
    #
    #     # 1. Добавление в поставку
    #     try:
    #         self.show_log(f"WB API: Добавление заказа {order_id} в поставку {supply_id}...")
    #         self.api.add_order_to_supply(supply_id, order_id)
    #
    #         # Обновление статуса в DataFrame
    #         self.fbs_df.loc[row.name, 'Номер поставки'] = supply_id
    #         self.show_log(f"✅ Заказ {order_id} успешно добавлен в поставку {supply_id}.", is_error=False)
    #
    #         # 2. Печать (Автоматическая после добавления)
    #         self._fetch_and_print_wb_label(order_id, printer_target)
    #
    #     except Exception as e:
    #         self.fbs_df.loc[row.name, 'Номер поставки'] = 'Ошибка'
    #         self.show_log(f"❌ Ошибка добавления заказа {order_id} в поставку: {e}", is_error=True)
    #         play_unsuccess_scan_sound()

    def print_label_from_button(self):
        """Печать этикетки по кнопке (требование 2)."""
        if self.selected_row_index is None:
            self.show_log("❌ Выберите строку для печати.", is_error=True)
            return

        row = self.fbs_df.loc[self.selected_row_index]
        # logger.info('Номер заказа:', row["Номер заказа"], 'Индекс строки:', self.selected_row_index)
        # logger.info('Статус заказа:',row['Статус заказа'],'Номер поставки:',row['Номер поставки'])
        # logger.info('Проверка шаблона ID поставки:', bool(re.match(self.pattern,row['Номер поставки'])))

        if row['Статус заказа'] == self.define_status[2]: # 'confirm': # and bool(re.match(self.pattern,row['Номер поставки'])):
            self._fetch_and_print_wb_label(int(row['Номер заказа']), self.app_context.printer_name)
        else:
            self.show_log("❌ Заказ не собран или не добавлен в поставку. Печать невозможна.", is_error=True)

    def _fetch_and_print_wb_label(self, order_id, printer_target):
        """Запрашивает  этикетку и отправляет на печать."""
        debug_info = False
        try:
            self.show_log("WB API: Запрос  этикетки...")
            if debug_info: logger.info("WB API: Запрос  этикетки...")
            # Запрашиваем стикер в формате ZPL
            stikers_type = "png"
            width_type = 40 #58
            height_type = 30 #40
            stickers_response = self.api.get_stickers([order_id], type=stikers_type if stikers_type != "zplv" else "zplh",
                                                      width=width_type, height=height_type)
            stickers = stickers_response.get('stickers')

            if stickers and isinstance(stickers, list) and 'file' in stickers[0]:
                label_base64_data = stickers[0]['file']
                if debug_info: logger.info(f"✅ Этикетка WB получена, пытаемся напечатать")
                # print_wb_ozon_label сам определяет, что это ZPL, и отправит его на печать.
                if self.label_printer.print_wb_ozon_label(label_base64_data, printer_target, type=stikers_type):
                # if self.label_printer.print_on_windows(image = label_base64_data):
                    self.show_log(f"✅ Этикетка WB для {order_id} успешно отправлена на печать.", is_error=False)
                    if debug_info: logger.info(f"✅ Этикетка WB для {order_id} успешно отправлена на печать.")
                else:
                    self.show_log("❌ Прямая печать не удалась. Проверьте принтер .", is_error=True)
                    if debug_info: logger.info("❌ Прямая печать не удалась. Проверьте принтер .")
                # Помечаем товар как обработанный -- это тоже надо закинуть в печать этикетки
                self.fbs_df.loc[self.selected_row_index, "Статус обработки"] = self.assembly_status[1] # "Обработан"
                # Сохраняем в контекст
                self.save_data_to_context()
                # Обновление таблицы и раскраски
                self.update_table(self.fbs_df)
            else:
                self.show_log("❌ WB API не вернул данные этикетки.", is_error=True)
                if debug_info: logger.info("❌ WB API не вернул данные этикетки.")

        except Exception as e:
            self.show_log(f"❌ Ошибка получения или печати этикетки WB: {e}", is_error=True)
            if debug_info: logger.info(f"❌ Ошибка получения или печати этикетки WB: {e}")
            play_unsuccess_scan_sound()

    def transfer_supply_to_delivery_button(self):
        debug_info = False
        selected_supply_id = self.wb_supply_id_var.get().strip()
        try:
            self.show_log(f"WB API: Передаем поставку {selected_supply_id} в доставку", is_error=True)
            if debug_info: logger.info(f"WB API: Передаем поставку {selected_supply_id} в доставку")
            else:
                self.api.close_supply_complete(supplyId = selected_supply_id)
            self.update_status(status=3, supply=selected_supply_id)
            self.show_log(f"Создайте новую поставку", is_error=True)

            self.remove_supply_from_combobox(selected_supply_id)
            # setattr(self.app_context, "wb_fbs_supply_id", None)

        except Exception as e:
            self.show_log(f"❌ Ошибка получения или печати этикетки WB: {e}", is_error=True)
            if debug_info: logger.info(f"❌ Ошибка получения или печати этикетки WB: {e}")

    # Фрагмент кода в классе FBSModeWB (или там, где определен комбобокс)

    def remove_supply_from_combobox(self, supply_to_remove: str):
        """
        Удаляет указанный ID поставки из списка значений комбобокса.
        """

        # 1. Получаем текущий список значений из комбобокса
        current_values = self.supply_combobox.cget("values")

        # cget("values") возвращает кортеж, преобразуем его в список для редактирования
        if isinstance(current_values, tuple):
            values_list = list(current_values)
        else:
            # Если значений нет или формат неожиданный, начинаем с пустого списка
            values_list = []

            # 2. Фильтруем список, исключая ненужный ID
        if supply_to_remove in values_list:
            values_list.remove(supply_to_remove)

        # 3. Обновляем комбобокс новым списком значений
        # Используем метод configure для установки нового списка значений
        self.supply_combobox.configure(values=values_list)

        # 4. Проверяем, не было ли удаленное значение текущим выбранным
        current_selected = self.wb_supply_id_var.get()

        if current_selected == supply_to_remove:
            # Устанавливаем новое значение (например, первое или пустую строку)
            if values_list:
                self.supply_combobox.set(values_list[0])
                self.wb_supply_id_var.set(values_list[0])
            else:
                self.supply_combobox.set("")
                self.wb_supply_id_var.set("")


    # --- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ---
    def restore_entry_focus(self, event=None):
        # Получаем текущий элемент, который держит фокус
        current_focus = self.focus_get()
        # ЕСЛИ фокус уже в одном из ваших полей ввода — НИЧЕГО НЕ ДЕЛАЕМ
        if current_focus in (self.cis_entry, self.scan_entry2):
            return
        if self.editing:
            return
        self.scan_entry.focus_set()
        # self.focus_timer_id = self.after(100, self.restore_entry_focus)

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
        self.save_data_to_context()
        self.start_auto_focus()

    def save_data_to_context(self):
        """Сохраняет данные в контекст приложения"""
        try:
            self.app_context.fbs_table = self.fbs_df.copy()
            wb_supply_id = self.wb_supply_id_var.get().strip()
            self.show_log(f"Сохраняю id поставки WB: {wb_supply_id}")
            self.app_context.wb_fbs_supply_id = wb_supply_id
        except Exception as e:
            self.show_log(f"Ошибка сохранения: {str(e)}", is_error=True)

    # def on_wb_supply_entry_focus_in(self, event=None):
    #     self.editing = True
    #
    # def on_wb_supply_entry_focus_out(self, event=None):
    #     self.editing = False
    #     self.start_auto_focus()

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

    def update_status(self,status:int=0,supply:str=None):
        if supply:
            mask = self.fbs_df['Номер поставки'] == supply
            self.fbs_df.loc[mask, 'Статус заказа'] = self.define_status[status]
        else:
            # --- 1. Обработка пустых значений (Заполнение заданным дефолтным статусом) ---
            # Сначала заполняем NaN (стандартное отсутствие данных в Pandas)
            self.fbs_df['Статус заказа'] = self.fbs_df['Статус заказа'].fillna(self.define_status[status])

            # Затем находим и заменяем пустые строки или строки, состоящие из пробелов
            empty_string_mask = (self.fbs_df['Статус заказа'].astype(str).str.strip() == '')
            self.fbs_df.loc[empty_string_mask, 'Статус заказа'] = self.define_status[status]

        # Сохраняем в контекст
        self.save_data_to_context()
        self.update_table()

        # /home/markv7/PycharmProjects/Barcode_print/gui/fbs_wb_gui.py (внутри класса FBSModeWB)

    def update_orders_statuses_from_api(self):
        """
        Получает статусы всех заказов из self.fbs_df и обновляет DataFrame.
        """
        debug_info = False
        if self.fbs_df.empty:
            self.show_log("Нет данных для обновления статусов.", is_error=False)
            return

        # 1. Извлекаем список ID сборочных заданий
        # 💡 Замените 'ID сборочного задания' на фактическое имя колонки с внутренним ID заказа WB
        try:
            raw_ids = self.fbs_df['Номер заказа'].dropna().tolist()
            order_ids = list(map(int, raw_ids))
        except KeyError:
            self.show_log("❌ Ошибка: Колонка 'Номер заказа' не найдена.", is_error=True)
            if debug_info: logger.info("❌ Ошибка: Колонка 'Номер заказа' не найдена.")
            return

        if not order_ids:
            self.show_log("Нет ID сборочных заданий для проверки.", is_error=False)
            if debug_info: logger.info("Нет ID сборочных заданий для проверки.")
            return

        try:
            self.show_log(f"WB API: Запрос статусов для {len(order_ids)} заказов...")
            if debug_info: logger.info(f"WB API: Запрос статусов для {len(order_ids)} заказов...")
            # 2. Вызов нового метода API
            chek_orders = {"orders": order_ids }
            status_response = self.api.get_status_orders(chek_orders)
            if debug_info: logger.info('chek_orders:', chek_orders)
            # 3. Обработка и обновление DataFrame
            statuses = status_response.get('orders', [])
            if debug_info: logger.info('status_response:',status_response)
            if debug_info: logger.info('statuses:', statuses)
            if statuses:
                # Преобразуем список статусов в словарь для быстрого поиска: {id: status}
                status_map = {item['id']: item['supplierStatus'] for item in statuses}

                # Функция для обновления статуса в DataFrame
                def map_new_status(row):
                    order_id = row['Номер заказа']
                    # Используем полученный статус, если он есть, иначе оставляем старый
                    return status_map.get(order_id, row['Статус заказа'])
                if debug_info:
                    logger.info('status_map',status_map)
                    logger.info('-----------------------------------')
                else:
                    # Обновляем колонку 'Статус доставки'
                    self.fbs_df['Статус заказа'] = self.fbs_df.apply(map_new_status, axis=1)
                    # Сохраняем в контекст
                    self.save_data_to_context()
                    self.update_table()

                self.show_log("✅ Статусы заказов успешно обновлены из WB API.")
            else:
                self.show_log("WB API не вернул статусы заказов в ожидаемом формате.", is_error=True)

        # except requests.exceptions.HTTPError as e:
        #     self.show_log(f"❌ Ошибка API при получении статусов: {e}", is_error=True)
        except Exception as e:
            self.show_log(f"❌ Непредвиденная ошибка: {e}", is_error=True)
            if debug_info:
                logger.info(f"❌ Непредвиденная ошибка: {e}")


    def update_table(self, df: pd.DataFrame=None):
        """Обновляет содержимое таблицы и применяет цветовую индикацию."""
        if df is None:
            df = self.fbs_df

        # 1. Выбираем только те колонки, которые должны быть в таблице (self.columns - 13 шт.)
        # Это обеспечивает корректный входной DataFrame для EditableDataTable.
        # Используем существующий self.columns, который вы определили ранее.
        display_df = df[self.columns].copy()
        # display_df = df.copy()
        # 2. Вызываем метод обновления данных в EditableDataTable
        self.data_table.update_data(display_df)

        # 3. Восстановление расцветки сразу после обновления данных.
        # Этот метод должен быть добавлен в класс FBSModeWB (см. ниже).
        self.apply_row_coloring()

    def show_log(self, message: str, is_error: bool = False):
        """Обновляет лог-сообщение в нижней части UI."""
        if self.log_label:
            color = "blue" if is_error else "green"
            self.log_label.configure(text=message, text_color=color)
            if is_error:
                logger.error(message)
            else:
                logger.info(message)

        if hasattr(self, 'log_timer_id') and self.log_timer_id:
            self.after_cancel(self.log_timer_id)

        self.log_timer_id = self.after(5000, lambda: self.log_label.configure(text="Ожидание сканирования...",
                                                                              text_color="grey"))

    def start_auto_focus(self):
        """Устанавливает фокус на поле сканирования."""
        # if self.scan_entry2:
        #     if hasattr(self, 'focus_timer_id') and self.focus_timer_id:
        #         self.after_cancel(self.focus_timer_id)
        #
        #     self.focus_timer_id = self.after(100, self.scan_entry2.focus_set)
        self.scan_entry2.focus_set()

    def cis_entry_focus(self):
        """Устанавливает фокус на поле сканирования КИЗ."""
        self.cis_entry.focus_set()
        # Используем общую логику восстановления фокуса
        # if self.cis_entry and self.cis_entry.winfo_exists():
        #     # Если нужно именно на cis_entry
        #     if hasattr(self, 'focus_timer_id') and self.focus_timer_id:
        #         try:
        #             self.after_cancel(self.focus_timer_id)
        #         except Exception:
        #             pass
        #     self.focus_timer_id = self.after(100,
        #                                      lambda: self.cis_entry.focus_set() if self.cis_entry.winfo_exists() else None)
        # else:
        #     self.restore_entry_focus()

    def get_row_status(self, row):
        """Определяет статус строки для цветовой индикации"""
        # Если товар обработан - зеленый (независимо от наличия маркировки)
        if row["Статус обработки"] == self.assembly_status[1]: # "Обработан"
            return "collected order"  # Зеленый цвет для обработанных заказов
        # Если поставка добавлена в доставку
        if row["Статус заказа"] == self.define_status[3]: # 'complete':
            return "completed"  # Аметист
        elif row["Статус заказа"] == self.define_status[2]: #'confirm':
            return 'confirm'  # Светло зеленый

        # # Если есть и штрихкод, и код маркировки - зеленый
        # if row["Штрихкод"] != "" and row["Код маркировки"] != "":
        #     return "completed"  # Зеленый цвет для завершенных заказов

        # Если есть только штрихкод - желтый
        if row["Штрихкод"] != "":
            return "found"  # Желтый цвет для найденных штрих кодов

        # Проверяем наличие в основной базе данных
        # if self.app_context.df is not None:
        #     matches = self.app_context.df[
        #         (self.app_context.df["Артикул производителя"].astype(str) == str(row["Артикул поставщика"])) &
        #         (self.app_context.df["Размер"].astype(str) == str(row["Размер"]))
        #         ]
        #     if not matches.empty:
        #         return "found"
        #
        # # Проверяем в локальной базе
        # key = f"{row['Артикул поставщика']}_{row['Размер']}"
        # if key in self.wb_marking_db:
        #     return "found"

        return "missing"
