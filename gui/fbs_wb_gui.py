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

# Переменная для хранения имени файла с новыми ШК
NEW_BARCODES_FILE = "new_barcodes.csv"


class FBSModeWB(ctk.CTkFrame):
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
        self.focus_timer_id = None
        self.clear_timer_id = None
        self.current_barcode = None
        self.marking_db = {}  # База данных артикул+размер -> штрихкод
        self.columns=[
                "Номер заказа", "Служба доставки", "Покупатель", "Бренд", "Цена",
                # "Статус доставки",
                "Артикул поставщика", "Количество", "Размер",
                "Штрихкод", 'Штрихкод WB', "Код маркировки", "Номер поставки", "Статус обработки"
            ]
        self.define_status = ('indefinite','new','confirm','complete','cancel')
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

            # 4. Установка значения по умолчанию для "Статус обработки"
            #    (Этот статус мог быть потерян при reindex, если он не существовал в исходном DF,
            #    но должен быть добавлен после создания структуры)
            if "Статус обработки" in self.fbs_df.columns:
                # Заполняем пустые значения в 'Статус обработки' значением "Не обработан"
                self.fbs_df["Статус обработки"] = self.fbs_df["Статус обработки"].replace({'': 'indefinite', 'Не обработан':'indefinite'})

        self.current_orders_df = None  # Заказы, загруженные из API
        self.wb_marking_db = self._load_new_barcodes()  # База данных артикул+размер -> штрихкод

        # --- API и Принтер ---
        self.api = WildberriesFBSAPI(self.app_context.wb_api_token)
        self.label_printer = LabelPrinter(self.app_context.printer_name)

        # --- Настройки поставки WB ---
        saved_supply_id = getattr(self.app_context, "wb_fbs_supply_id", "")
        self.wb_supply_id_var = ctk.StringVar(value=str(saved_supply_id))
        self.wb_supply_id_var.trace_add("write", self.update_supply_id)
        self.df_barcode_WB = self.app_context.df_barcode_WB

        # --- UI элементы ---
        self.scan_entry = None
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
        self.check_var = None
        self.checkbox = None

        self.setup_ui()

        self.show_log(f"Подставлен ID поставки WB: {saved_supply_id}")

    # Фрагмент кода для файла fbs_wb_gui.py (внутри класса FBSModeWB)

    def debug_print_first_row(self,data_df:DataFrame,number_row:int=0):
        """Выводит n-ю строку DataFrame self.fbs_df для проверки структуры данных."""
        if data_df.empty:
            print("--- self.fbs_df пуст, нет данных для вывода. ---")
            return
        print("\n=======================================================")
        print(f"✅ DEBUG: {number_row}-я строка DataFrame self.fbs_df:")
        # .iloc[0] безопасно извлекает строку по числовому индексу 0,
        # независимо от того, какие у DataFrame установлены индексы (строковые/числовые).
        first_row = data_df.iloc[number_row]
        # Вывод в формате Series (колонка: значение)
        print(first_row)
        print("=======================================================\n")

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

        # --- Левая часть: Таблица и Лог ---
        main_frame = ctk.CTkFrame(self)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        # Таблица
        self.table_frame = ctk.CTkFrame(main_frame)
        self.table_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.table_frame.grid_rowconfigure(0, weight=1)
        self.table_frame.grid_columnconfigure(0, weight=1)


        # Лог (самый нижний элемент)
        self.log_label = ctk.CTkLabel(main_frame, text="Ожидание сканирования...", font=self.font, text_color="grey")
        self.log_label.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 5))

        # --- Правая часть: Управление ---
        control_panel = ctk.CTkFrame(self, width=300)
        control_panel.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=10)
        control_panel.grid_columnconfigure(0, weight=1)

        row = 0
        ctk.CTkButton(control_panel, text="Загрузить заказы из Excel",
                      command=self.load_orders, font=self.font,
                      # fg_color="blue",
                      state="normal").grid(row=row, column=0, padx=10, pady=(10, 5), sticky="ew")
        row += 1
        # 1. Кнопка "Загрузить товары" (Требование 5 - смещено вверх)
        ctk.CTkButton(control_panel, text="Загрузить заказы из WB", command=self.load_wb_orders, font=self.font,
                      fg_color="blue", state="normal").grid(row=row, column=0, padx=10, pady=(10, 5), sticky="ew")
        row += 1
        ctk.CTkButton(control_panel, text="Обновить статусы сборки", command=self.update_orders_statuses_from_api, font=self.font,
                      fg_color="gray", state="normal").grid(row=row, column=0, padx=10, pady=(10, 5), sticky="ew")
        row += 1
        # --- Разделитель ---
        # ctk.CTkFrame(control_panel, height=2, fg_color="gray").grid(row=row, column=0, padx=10, pady=10, sticky="ew")


        # 2. Поле сканирования Штрихкода Товара
        ctk.CTkLabel(control_panel, text="Поиск товара по ШК:", font=self.font).grid(row=row, column=0, padx=10,
                                                                               pady=(10, 0), sticky="w")
        row += 1
        self.scan_entry = ctk.CTkEntry(control_panel, font=self.font)
        self.scan_entry.bind('<Return>', lambda event: self.handle_barcode_input(self.scan_entry.get()))
        self.scan_entry.grid(row=row, column=0, padx=10, pady=(0, 10), sticky="ew")
        row += 1

        # Создание переменной для контроля состояния
        self.check_var = ctk.StringVar(value="on")
        # Создание чекбокса
        self.checkbox = ctk.CTkCheckBox(control_panel, text="АвтоПечать", command=self.checkbox_event, variable=self.check_var,
                                             onvalue="on", offvalue="off")
        self.checkbox.grid(row=row, column=0, padx=10, pady=0, sticky="w")
        row += 1

        # 3. Поле сканирования КИЗ (Маркировки) (Требование 3)
        ctk.CTkLabel(control_panel, text="Сканирование КИЗ (ЧЗ):", font=self.font).grid(row=row, column=0, padx=10,
                                                                                        pady=(10, 0), sticky="w")
        row += 1
        self.cis_entry = ctk.CTkEntry(control_panel, font=self.font)
        self.cis_entry.bind('<Return>', lambda event: self.handle_cis_input(self.cis_entry.get()))
        self.cis_entry.grid(row=row, column=0, padx=10, pady=(0, 10), sticky="ew")
        row += 1

        # 4. Кнопка "Собрать Заказ" (Ручная сборка) (Требование 1)
        self.assembly_button = ctk.CTkButton(control_panel, text="Добавить к поставке",
                                             command=self.finalize_manual_assembly, font=self.font, fg_color="green",
                                             state="normal")
        self.assembly_button.grid(row=row, column=0, padx=10, pady=10, sticky="ew")
        row += 1

        # 7. Кнопка "Печать Этикетки" (Требование 2)
        self.print_button = ctk.CTkButton(control_panel, text="🖨️ Печать Этикетки",
                                          command=self.print_label_from_button, font=self.font, fg_color="gray",
                                          state="disabled")
        self.print_button.grid(row=row, column=0, padx=10, pady=10, sticky="ew")
        row += 1
        # --- Разделитель ---
        ctk.CTkFrame(control_panel, height=2, fg_color="gray").grid(row=row, column=0, padx=10, pady=10, sticky="ew")
        row += 1

        # 5. Кнопка "Создать поставку" (Требование 4)
        ctk.CTkButton(control_panel, text="📦 Создать Поставку WB", command=self.create_new_supply, font=self.font).grid(
            row=row, column=0, padx=10, pady=10, sticky="ew")
        row += 1

        # 5. Кнопка "Обновить активные Поставки"
        ctk.CTkButton(control_panel, text="Обновить активные Поставки", command=self.order_relation_supply,
                      font=self.font, fg_color="gray").grid(
                    row=row, column=0, padx=10, pady=10, sticky="ew")
        row += 1

        # 6. Выбор/Просмотр Поставки
        ctk.CTkLabel(control_panel, text="Активная Поставка:", font=self.font).grid(row=row, column=0, padx=10,
                                                                                    pady=(5, 0), sticky="w")
        row += 1
        self.supply_combobox = ctk.CTkComboBox(control_panel, variable=self.wb_supply_id_var, values=[""],
                                               font=self.font, state="readonly",
                                               command=self._update_supply_combobox_selection)
        self.supply_combobox.grid(row=row, column=0, padx=10, pady=(0, 10), sticky="ew")
        row += 1


        # 8. Кнопка "В доставку"
        self.transfer_button = ctk.CTkButton(control_panel, text="Передать поставку в доставку",
                                          command=self.transfer_supply_to_delivery_button, font=self.font, fg_color="blue",
                                          state="normal")
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
        self.start_auto_focus()

    def load_orders(self):
        """Загружает заказы из Excel"""

        file_path = fd.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xls")])
        if not file_path:
            return

        try:
            df_unload = pd.read_excel(file_path)
            required_columns = [
                "Номер заказа", "Служба доставки", "Бренд", "Цена",
                "Статус", "Артикул поставщика", "Количество", "Размер"
            ]
            missing_cols = [col for col in required_columns if col not in df_unload.columns]
            if missing_cols:
                self.show_log(f"Ошибка: Отсутствуют столбцы: {', '.join(missing_cols)}", is_error=True)
                return
            # проверка полек  "Служба доставки" == Wildberries
            # 2. Фильтрация по Wildberries
            filtered_df = df_unload[df_unload['Служба доставки'].astype(str).str.contains(self.marketplace, na=False)].copy()
            filtered_df["Статус обработки"] = filtered_df["Статус"].replace({'': 'indefinite', 'Новый': 'new'})

            #    Мы используем reindex, чтобы гарантировать, что все строки имеют нужные колонки
            if not filtered_df.empty:
                # Берем только существующие колонки из self.columns
                existing_cols_in_filtered_df = [col for col in self.columns if col in filtered_df.columns]

                # Создаем временный DF, который будет содержать данные только по существующим колонкам
                temp_df = filtered_df[existing_cols_in_filtered_df].copy()

                # Добавляем все недостающие колонки и выравниваем индекс
                temp_df = temp_df.reindex(columns=self.columns)

                # 💡 ИСПРАВЛЕНИЕ WARNING 1: Приводим все колонки к строковому типу перед заполнением
                # Это позволяет безопасно хранить строки и NaN, устраняя FutureWarning.
                for col in temp_df.columns:
                    temp_df[col] = temp_df[col].astype(object)
                # Pandas по умолчанию заполняет новые колонки NaN. Заменяем NaN на пустые строки
                temp_df.fillna('', inplace=True)


            # Разбиваем каждую запись на количество
            expanded_rows = []
            for _, row in temp_df.iterrows():
                count = int(row["Количество"])
                for _ in range(count):
                    new_row = row.to_dict()
                    new_row["Количество"] = 1
                    expanded_rows.append(new_row)

            new_df = pd.DataFrame(expanded_rows)

            # # Добавляем внутренние поля
            # new_df["Штрихкод"] = ""
            # new_df["Код маркировки"] = ""
            # new_df["Номер поставки"] = ""
            # new_df["Статус обработки"] = "new"

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

    def checkbox_event(self):
        print("Checkbox toggled, current value:", self.check_var.get())


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
        self.data_table.tree.tag_configure("completed", background="#90EE90")  # Зеленый - есть и штрихкод, и маркировка
        self.data_table.tree.tag_configure("confirm", background="#CCFFCC")  # Очень бледный, почти белый с легким зеленым оттенком.

    # --- МЕТОДЫ ОБРАБОТКИ СКАНИРОВАНИЯ ---
    def handle_barcode_input(self, input_value: str):
        """
        Обрабатывает ввод штрихкода.
        """
        self.editing = True
        self.current_barcode = input_value.strip()
        self.scan_entry.delete(0, 'end')  # Очищаем поле сразу

        if not self.current_barcode:
            self.show_log("❌ Ошибка: Введите штрихкод.", is_error=True)
            self.editing = False
            self.start_auto_focus()
            return

        self.show_log(f"Сканирование: {self.current_barcode}")
        # print(str(self.current_barcode))
        # print(self.fbs_df['Штрихкод'].astype(str))
        # 1. Поиск: ищем  Штрихкод производителя в текущих заказах
        matches = self.fbs_df[self.fbs_df['Штрихкод'].astype(str) == str(self.current_barcode)].copy()
        row_index = 0

        if not matches.empty:
            # --- Логика Сборки по сканированию (автоматическая) ---
            row_index = matches.index[0]
            # print('row_index',row_index)
            row = self.fbs_df.loc[row_index]
            self.selected_row_index = row_index
           # --- ДОБАВЛЕНИЕ ЛОГИКИ ВЫДЕЛЕНИЯ И ФОКУСА - --

            self.data_table.select_row(row_index)
            play_success_scan_sound()
            if self.check_var.get() == 'on':
                self.show_log(f"Печатаем этикетку {self.current_barcode} ШК  ")
                print(f'Печатаем этикетку {self.current_barcode} ШК  ')
                self.print_label_from_button()
        # 2. Несовпадение: возможно, это новый ШК или артикул для добавления
        else:
            # self.handle_unmatched_barcode(self.current_barcode) Этот метод реализовать позже
            self.show_log(f"Несовпадение: возможно, это новый {self.current_barcode} ШК или артикул ")

        # print('row_index', row_index)
        # self._select_row_by_index(row_index)
        # self.editing = True
        # self.start_auto_focus()


    def handle_cis_input(self, input_value: str):
        """Обрабатывает ввод КИЗ (Честный знак). (Требование 3)"""
        cis_code = input_value.strip()
        self.cis_entry.delete(0, 'end')

        if not cis_code:
            self.show_log("❌ Введите КИЗ.", is_error=True)
            self.start_auto_focus()
            return

        if self.selected_row_index is None:
            self.show_log("❌ Сначала выберите или отсканируйте товар.", is_error=True)
            play_unsuccess_scan_sound()
            self.start_auto_focus()
            return

        # ВРЕМЕННАЯ ЛОГИКА: Просто сохраняем КИЗ в строке

        row = self.fbs_df.loc[self.selected_row_index]
        self.fbs_df.loc[self.selected_row_index, 'Код маркировки'] = cis_code
        self.show_log(f"✅ КИЗ ({cis_code[:10]}...) записан для заказа {row['Номер заказа']}.", is_error=False)
        self.update_table()
        self.start_auto_focus()

    def handle_unmatched_barcode(self, barcode: str):
        """
        Обрабатывает штрихкод, который не соответствует ни одному текущему заказу.
        Предлагает сохранить его как новый ШК/Артикул. ЭТО НАДО ДОРАБОТАТЬ !!!
        """
        # Попытка найти совпадение в базе новых ШК (wb_marking_db)
        match = self.wb_marking_db[self.wb_marking_db['Штрихкод'] == barcode]

        if not match.empty:
            self.show_log(f"⚠️ ШК {barcode} найден в базе, но не в текущих заказах. Заказ не найден.", is_error=True)
            play_unsuccess_scan_sound()
            return

        self.show_log(f"❌ ШК/Артикул {barcode} не найден ни в заказах, ни в базе.", is_error=True)

        # Предлагаем добавить ШК в базу (требование 6)
        if messagebox.askyesno("Новый Штрихкод/Артикул",
                               f"ШК/Артикул {barcode} не найден.\nХотите добавить его в базу?"):

            # --- Добавление ШК/Артикула ---
            article = eg.enterbox("Введите Артикул Производителя для этого штрихкода:", "Добавление нового ШК")
            if not article:
                self.show_log("Отменено. Добавление нового ШК/Артикула пропущено.", is_error=True)
                return

            new_row = pd.DataFrame([{
                'Артикул производителя': article,
                'Штрихкод производителя': barcode,
                'Баркод Wildberries': '',
            }])

            # Добавляем в базу и сохраняем
            self.wb_marking_db = pd.concat([self.wb_marking_db, new_row], ignore_index=True)
            self._save_new_barcodes()
            self.show_log(f"✅ Новый ШК/Артикул {article} ({barcode}) добавлен в базу.", is_error=False)

        play_unsuccess_scan_sound()

    # --- МЕТОДЫ УПРАВЛЕНИЯ UI И ДАННЫМИ ---

    # /home/markv7/PycharmProjects/Barcode_print/gui/fbs_wb_gui.py (внутри class FBSModeWB)
    # from typing import Optional, Dict
    def fetch_product_info_by_wb_barcode(self, wb_barcode: str) -> Optional[Dict]:
        """
        Ищет информацию о товаре в общей базе данных (self.app_context.df)
        по Баркоду Wildberries (Баркод  Wildberries).

        :param wb_barcode: Баркод Wildberries, полученный из API.
        :return: Словарь с данными для заполнения полей заказа или None.
        """
        # Проверяем наличие и содержимое общей базы данных
        if self.app_context.df is None or self.app_context.df.empty:
            return None

        # Название столбца в загруженном CSV/Excel файле (с учетом двух пробелов)
        WB_BARCODE_COL = "Баркод  Wildberries"

        if WB_BARCODE_COL not in self.app_context.df.columns:
            print(f"ERROR: Столбец '{WB_BARCODE_COL}' не найден в базе данных.")
            return None

        # Очистка и приведение типов для безопасного сравнения
        search_barcode = str(wb_barcode).strip()

        # 1. Фильтруем базу данных, приводя столбец к строковому типу
        # Используем .astype(str).str.strip() для надежного сравнения
        matches = self.app_context.df[
            self.app_context.df[WB_BARCODE_COL].astype(str).str.strip() == search_barcode
            ]

        if matches.empty:
            return None

        # 2. Берем первую найденную строку и извлекаем данные
        product_row = matches.iloc[0]

        # 3. Составляем словарь для обновления строки заказа
        # Ключи словаря должны соответствовать именам столбцов в self.fbs_df
        result = {}

        # Соответствие полей:
        # Артикул поставщика (заказ) <- Артикул производителя (база)
        if "Артикул производителя" in product_row:
            result["Артикул поставщика"] = str(product_row["Артикул производителя"]).strip()

        # Размер (заказ) <- Размер (база)
        if "Размер" in product_row:
            result["Размер"] = str(product_row["Размер"]).strip()

        # Штрихкод (заказ, наш внутренний) <- Штрихкод производителя (база)
        if "Штрихкод производителя" in product_row:
            result["Штрихкод"] = str(product_row["Штрихкод производителя"]).strip()

        # Бренд (заказ) <- Бренд (база)
        if "Бренд" in product_row:
            result["Бренд"] = str(product_row["Бренд"]).strip()

        return result

    def load_wb_orders(self):
        """Загружает новые сборочные задания WB через API."""
        debug_info = False
        # Проверяем наличие и содержимое общей базы данных
        if self.df_barcode_WB is None or self.df_barcode_WB.empty:
            try:
                file_path = fd.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xls")])
                self.df_barcode_WB = pd.read_excel(file_path)
                setattr(self.app_context, "df_barcode_WB", self.df_barcode_WB)
                setattr(self.app_context, "file_path2", file_path)
            except Exception as e:
                self.show_log(f"Ошибка при загрузке файла: {str(e)}", is_error=True)
        try:
            self.show_log("WB API: Запрос новых сборочных заданий...")
            orders_data = self.api.get_orders(params={'flag': 0})
            orders = orders_data.get('orders', [])

            if not orders:
                self.show_log("✅ Новых сборочных заданий не найдено.", is_error=False)
                return

            new_orders_df = pd.DataFrame(orders)
            if debug_info:
                self.debug_print_first_row(new_orders_df, 2)
                self.debug_print_first_row(new_orders_df, 3)
            else:
                # Создаем ключевые колонки и статусы (сохраняем столбцы, как в self.fbs_df) ВРЕМЕННО ЗАКОММЕНТИРОВА нижние строки
                new_orders_df['Номер заказа'] = new_orders_df['id'] #.astype(str)
                new_orders_df['Служба доставки'] = self.marketplace
                new_orders_df['Цена'] = new_orders_df['finalPrice'].astype(str)
                new_orders_df['Артикул поставщика'] = new_orders_df['article'].astype(str)
                new_orders_df['Размер'] = new_orders_df['chrtId'].astype(str)
                new_orders_df['Количество'] = 1
                new_orders_df['Статус обработки'] = 'new'

                def extract_first_sku(sku_list):
                    """
                    Извлекает первый элемент из списка skus.
                    Возвращает NaN, если список пуст, None, или не является списком.
                    """
                    if isinstance(sku_list, list) and sku_list:
                        return sku_list[0]
                    return ''

                # Создаем новый столбец 'Штрихкод', применяя функцию к колонке 'skus'
                new_orders_df['Штрихкод WB'] = new_orders_df['skus'].apply(extract_first_sku)

                # Добавляем отсутствующие колонки из self.fbs_df, чтобы избежать ошибки при concat
                for col in self.fbs_df.columns:
                    if col not in new_orders_df.columns:
                        new_orders_df[col] = ''
                try:
                    # Автоматически заполняем штрихкоды из основной базы данных
                    if self.df_barcode_WB is not None:
                        for idx, row in new_orders_df.iterrows():
                            # --- ИСПОЛЬЗУЕМ НОВУЮ ФУНКЦИЮ ---
                            additional_info = self.fetch_product_info_by_wb_barcode(row['Штрихкод WB'])
                            if additional_info:
                                # Создаем базовую строку заказа
                                new_orders_df.loc[idx, "Размер"] = additional_info["Размер"]
                                new_orders_df.loc[idx, "Артикул поставщика"] = additional_info["Артикул поставщика"]
                                new_orders_df.loc[idx, "Штрихкод"] = additional_info["Штрихкод"]
                                new_orders_df.loc[idx, "Бренд"] = additional_info["Бренд"]
                except Exception as e:
                    self.show_log(f"❌ Ошибка при попытке сопоставить строки с внутренней базой: {e}", is_error=True)
                    print(f"❌ Ошибка при попытке сопоставить строки с внутренней базой: {e}")
                # Объединяем с текущей таблицей (удаляя дубликаты по 'Номер заказа')
                self.fbs_df = pd.concat([self.fbs_df, new_orders_df], ignore_index=True)
                self.fbs_df = self.fbs_df.drop_duplicates(subset=['Номер заказа'], keep='last')

                # # Очищаем таблицу от строк, где нет номера заказа (могут появиться при ошибке API)
                # self.fbs_df = self.fbs_df[self.fbs_df['Номер заказа'] != ''].copy()

                self.update_table()
                self.show_log(f"✅ Загружено {len(orders)} новых сборочных заданий WB.")

        except Exception as e:
            self.show_log(f"❌ Ошибка загрузки заказов WB: {e}", is_error=True)
            print(f"❌ Ошибка загрузки заказов WB: {e}")
            # play_unsuccess_scan_sound()

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


    def getting_supplies(self) -> List:
        debug_info = False
        start_next = 135615004
        response = self.api.get_supplies(params={"limit": 1000, "next": start_next})
        get_next = response['next']
        if debug_info:  print('get_next:', get_next)
        if debug_info:  print('Кол-во отданных записей:',len(response['supplies']))
        list_supplies = [item['id'] for item in response['supplies'] if item['done'] == False]
        if debug_info:  print('Кол-во активных поставок:', len(list_supplies))
        if debug_info:  print(list_supplies)
        return list_supplies

    def order_relation_supply(self):
        debug_info = True
        list_supplies = self.getting_supplies()
    #  далее поработать получить сборочные задания к каждой поставке
        contain_supply = [{"supplyId":supplyId, "orders":self.api.get_orders_in_supply(supplyId)["orders"]} for supplyId in list_supplies]
        if debug_info:  print('Кол-во активных поставок:', len(contain_supply))
        # обновляем значения в таблице
        if not contain_supply:
            self.show_log("Нет данных для обновления поставок.", is_error=False)
            return
        # здесь надо все проверить !!!!
        for item in  contain_supply:
            supplyId_t = item['supplyId']
            orders = [id_item['id'] for id_item in item['orders']]
            # print(supplyId_t,': ',orders)
            if orders:
                mask = self.fbs_df['Номер заказа'].isin(orders)
                self.fbs_df.loc[mask, 'Номер поставки'] = supplyId_t
        self.update_table()

                # --- МЕТОДЫ СБОРКИ И ПЕЧАТИ (Требования 1, 2, 3) ---
    def _handle_row_selection(self, row_index=None):
        """Обрабатывает выбор строки в таблице."""


        if row_index is None:
            # Деактивировать обе кнопки, если строка не выбрана
            # self.assembly_button.configure(state="disabled")
            # self.print_button.configure(state="disabled")
            return
        # print(f"DEBUG:FBSModeWB _handle_row_select received index: {row_index}")
        self.selected_row_index = row_index
        try:
            row = self.fbs_df.loc[row_index]
        except KeyError:
            # Недопустимый индекс
            self.assembly_button.configure(state="disabled")
            self.print_button.configure(state="disabled")
            return

        is_processed = row["Статус обработки"] == 'confirm'
        has_barcode = row["Штрихкод"] != ""
        has_marking = row["Код маркировки"] != ""
        has_articul = row["Артикул поставщика"] != ""
        has_size = row["Размер"] != ""

        # self.show_log(f"Статус обработки: {is_processed} Штрихкод: {has_barcode} Код маркировки: {has_marking}", is_error=True)
        # Условия для "Собрать заказ" (finalize_manual_assembly):
        # 1. Заказ НЕ обработан.
        # 2. Штрихкод и Код маркировки (если нужен, хотя тут мы просто проверяем наличие) заполнены.
        can_finalize = (not is_processed and has_articul and has_size) # and has_marking)

        # Условия для "Печать этикетки":
        # 1. Заказ уже Обработан.
        can_print = is_processed

        # 💡 УПРАВЛЕНИЕ КНОПКАМИ
        self.assembly_button.configure(state="normal" if can_finalize else "disabled")
        self.print_button.configure(state="normal" if can_print else "disabled")

    def _update_assembly_button_state(self):
        """Обновляет активность кнопки 'Собрать Заказ' (Требование 1)."""
        if self.selected_row_index is not None:
            row = self.fbs_df.loc[self.selected_row_index]
            if row['Статус обработки'] != 'new':
                self.assembly_button.configure(state="normal", fg_color="green")
                return

        self.assembly_button.configure(state="disabled", fg_color="gray")

    def _update_print_button_state(self):
        """Обновляет активность и цвет кнопки 'Печать Этикетки' (Требование 2)."""
        is_printable = False

        if self.selected_row_index is not None:
            row = self.fbs_df.loc[self.selected_row_index]
            # Активна, если собрано и добавлено в поставку
            if row['Статус обработки'] == 'confirm': # and bool(re.match(self.pattern, row['Номер поставки'])):
                is_printable = True

        if is_printable:
            self.print_button.configure(state="normal", fg_color="blue")
        else:
            self.print_button.configure(state="disabled", fg_color="gray")


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
        if debug_info: print(f"🔗 Попытка завершить сборку заказа {order_id} и добавить его в поставку {selected_supply_id}...")
        # 1. Добавление заказа в поставку WB (Шаг 5 - часть 1)
        try:
            self.show_log(f"WB API: Добавление заказа {order_id} в поставку {selected_supply_id}...")
            if debug_info:
                print(f"WB API: Добавление заказа {order_id} в поставку {selected_supply_id}...")
                print(f"Тип данных order_id - {type(order_id)} Тип данных selected_supply_id - {type(selected_supply_id)} ")

            json_obj = self.api.add_order_to_supply(selected_supply_id, order_id)
            print(json_obj)

            self.show_log(f"✅ Заказ {order_id} успешно добавлен в поставку {selected_supply_id} (WB API).")
            if debug_info: print(f"✅ Заказ {order_id} успешно добавлен в поставку {selected_supply_id} (WB API).")
        except Exception as e:
            self.show_log(f"❌ Ошибка добавления заказа {order_id} в поставку {selected_supply_id}: {e}", is_error=True)
            if debug_info: print(f"❌ Ошибка добавления заказа {order_id} в поставку {selected_supply_id}: {e}")
            return

        # 2. Обновление статуса в DataFrame (Шаг 6)
        try:
            # Устанавливаем статус и номер поставки
            self.fbs_df.loc[row_index, "Статус обработки"] = 'confirm'
            self.fbs_df.loc[row_index, "Номер поставки"] = selected_supply_id

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
        # print('Номер заказа:', row["Номер заказа"], 'Индекс строки:', self.selected_row_index)
        # print('Статус обработки:',row['Статус обработки'],'Номер поставки:',row['Номер поставки'])
        # print('Проверка шаблона ID поставки:', bool(re.match(self.pattern,row['Номер поставки'])))

        if row['Статус обработки'] == 'confirm': # and bool(re.match(self.pattern,row['Номер поставки'])):
            self._fetch_and_print_wb_label(int(row['Номер заказа']), self.app_context.printer_name)
        else:
            self.show_log("❌ Заказ не собран или не добавлен в поставку. Печать невозможна.", is_error=True)

    def _fetch_and_print_wb_label(self, order_id, printer_target):
        """Запрашивает  этикетку и отправляет на печать."""
        debug_info = False
        try:
            self.show_log("WB API: Запрос  этикетки...")
            if debug_info: print("WB API: Запрос  этикетки...")
            # Запрашиваем стикер в формате ZPL
            stikers_type = "png"
            width_type = 40 #58
            height_type = 30 #40
            stickers_response = self.api.get_stickers([order_id], type=stikers_type if stikers_type != "zplv" else "zplh",
                                                      width=width_type, height=height_type)
            stickers = stickers_response.get('stickers')

            if stickers and isinstance(stickers, list) and 'file' in stickers[0]:
                label_base64_data = stickers[0]['file']
                if debug_info: print(f"✅ Этикетка WB получена, пытаемся напечатать")
                # print_wb_ozon_label сам определяет, что это ZPL, и отправит его на печать.
                if self.label_printer.print_wb_ozon_label(label_base64_data, printer_target, type=stikers_type):
                # if self.label_printer.print_on_windows(image = label_base64_data):
                    self.show_log(f"✅ Этикетка WB для {order_id} успешно отправлена на печать.", is_error=False)
                    if debug_info: print(f"✅ Этикетка WB для {order_id} успешно отправлена на печать.")
                else:
                    self.show_log("❌ Прямая печать не удалась. Проверьте принтер .", is_error=True)
                    if debug_info: print("❌ Прямая печать не удалась. Проверьте принтер .")
            else:
                self.show_log("❌ WB API не вернул данные этикетки.", is_error=True)
                if debug_info: print("❌ WB API не вернул данные этикетки.")

        except Exception as e:
            self.show_log(f"❌ Ошибка получения или печати этикетки WB: {e}", is_error=True)
            if debug_info: print(f"❌ Ошибка получения или печати этикетки WB: {e}")
            play_unsuccess_scan_sound()

    def transfer_supply_to_delivery_button(self):
        debug_info = False
        selected_supply_id = self.wb_supply_id_var.get().strip()
        try:
            self.show_log(f"WB API: Передаем поставку {selected_supply_id} в доставку", is_error=True)
            if debug_info: print(f"WB API: Передаем поставку {selected_supply_id} в доставку")
            else:
                self.api.close_supply_complete(supplyId = selected_supply_id)
            self.update_status(status=3, supply=selected_supply_id)
            self.show_log(f"Создайте новую поставку", is_error=True)

            self.remove_supply_from_combobox(selected_supply_id)
            # setattr(self.app_context, "wb_fbs_supply_id", None)

        except Exception as e:
            self.show_log(f"❌ Ошибка получения или печати этикетки WB: {e}", is_error=True)
            if debug_info: print(f"❌ Ошибка получения или печати этикетки WB: {e}")

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
            print(f"[DEBUG] save_data_to_context: сохраняю wb_fbs_supply_id = '{wb_supply_id}'")
            self.show_log(f"Сохраняю id поставки WB: {wb_supply_id}")
            self.app_context.wb_fbs_supply_id = wb_supply_id
        except Exception as e:
            self.show_log(f"Ошибка сохранения: {str(e)}", is_error=True)

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

    def update_status(self,status:int=0,supply:str=None):
        if supply:
            mask = self.fbs_df['Номер поставки'] == supply
            self.fbs_df.loc[mask, 'Статус обработки'] = self.define_status[status]
        else:
            # --- 1. Обработка пустых значений (Заполнение заданным дефолтным статусом) ---
            # Сначала заполняем NaN (стандартное отсутствие данных в Pandas)
            self.fbs_df['Статус обработки'] = self.fbs_df['Статус обработки'].fillna(self.define_status[status])

            # Затем находим и заменяем пустые строки или строки, состоящие из пробелов
            empty_string_mask = (self.fbs_df['Статус обработки'].astype(str).str.strip() == '')
            self.fbs_df.loc[empty_string_mask, 'Статус обработки'] = self.define_status[status]
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
            if debug_info: print("❌ Ошибка: Колонка 'Номер заказа' не найдена.")
            return

        if not order_ids:
            self.show_log("Нет ID сборочных заданий для проверки.", is_error=False)
            if debug_info: print("Нет ID сборочных заданий для проверки.")
            return

        try:
            self.show_log(f"WB API: Запрос статусов для {len(order_ids)} заказов...")
            if debug_info: print(f"WB API: Запрос статусов для {len(order_ids)} заказов...")
            # 2. Вызов нового метода API
            chek_orders = {"orders": order_ids }
            status_response = self.api.get_status_orders(chek_orders)
            if debug_info: print('chek_orders:', chek_orders)
            # 3. Обработка и обновление DataFrame
            statuses = status_response.get('orders', [])
            if debug_info: print('status_response:',status_response)
            if debug_info: print('statuses:', statuses)
            if statuses:
                # Преобразуем список статусов в словарь для быстрого поиска: {id: status}
                status_map = {item['id']: item['supplierStatus'] for item in statuses}

                # Функция для обновления статуса в DataFrame
                def map_new_status(row):
                    order_id = row['Номер заказа']
                    # Используем полученный статус, если он есть, иначе оставляем старый
                    return status_map.get(order_id, row['Статус обработки'])
                if debug_info:
                    print('status_map',status_map)
                    print('-----------------------------------')
                else:
                    # Обновляем колонку 'Статус доставки'
                    self.fbs_df['Статус обработки'] = self.fbs_df.apply(map_new_status, axis=1)
                    self.update_table()

                self.show_log("✅ Статусы заказов успешно обновлены из WB API.", is_error=False)
                if debug_info: print("✅ Статусы заказов успешно обновлены из WB API.")
            else:
                self.show_log("WB API не вернул статусы заказов в ожидаемом формате.", is_error=True)
                if debug_info: print("WB API не вернул статусы заказов в ожидаемом формате.")

        # except requests.exceptions.HTTPError as e:
        #     self.show_log(f"❌ Ошибка API при получении статусов: {e}", is_error=True)
        except Exception as e:
            self.show_log(f"❌ Непредвиденная ошибка: {e}", is_error=True)
            if debug_info:
                print(f"❌ Непредвиденная ошибка: {e}")


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
            color = "red" if is_error else "green"
            self.log_label.configure(text=message, text_color=color)

        if hasattr(self, 'log_timer_id') and self.log_timer_id:
            self.after_cancel(self.log_timer_id)

        self.log_timer_id = self.after(5000, lambda: self.log_label.configure(text="Ожидание сканирования...",
                                                                              text_color="grey"))

    def start_auto_focus(self):
        """Устанавливает фокус на поле сканирования."""
        if self.scan_entry:
            if hasattr(self, 'focus_timer_id') and self.focus_timer_id:
                self.after_cancel(self.focus_timer_id)

            self.focus_timer_id = self.after(100, self.scan_entry.focus_set)

    def get_row_status(self, row):
        """Определяет статус строки для цветовой индикации"""
        # Если товар обработан - зеленый (независимо от наличия маркировки)
        if row["Статус обработки"] == 'complete':
            return "completed"  # Зеленый цвет для обработанных заказов
        elif row["Статус обработки"] == 'confirm':
            return 'confirm'  # Зеленый цвет для обработанных заказов

        # # Если есть и штрихкод, и код маркировки - зеленый
        # if row["Штрихкод"] != "" and row["Код маркировки"] != "":
        #     return "completed"  # Зеленый цвет для завершенных заказов

        # Если есть только штрихкод - желтый
        if row["Штрихкод"] != "":
            return "found"  # Желтый цвет для найденных штрих кодов

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
        if key in self.wb_marking_db:
            return "found"

        return "missing"
