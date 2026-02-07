import customtkinter as ctk
import pandas as pd
from tkinter import messagebox, filedialog
from datetime import datetime
import re
import os

class ReportsMode(ctk.CTkFrame):
    def __init__(self, parent, font, db_manager):
        super().__init__(parent)
        self.db = db_manager
        self.font = font

        # Заголовок страницы
        self.title_label = ctk.CTkLabel(self, text="Отчеты", font=ctk.CTkFont(size=26, weight="bold"))
        self.title_label.pack(pady=(20, 30))

        # Основной контейнер для блоков
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=40)

        # Настройка сетки (3 колонки для блоков)
        self.main_container.columnconfigure((0, 1, 2), weight=1, uniform="group1", pad=20)

        self._init_export_block()
        self._init_import_block()
        self._init_maintenance_block()

    def _init_export_block(self):
        """Блок №1: Экспорт данных"""
        block = ctk.CTkFrame(self.main_container)
        block.grid(row=0, column=0, sticky="nsew", padx=10)

        ctk.CTkLabel(block, text="ЭКСПОРТ", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        # --- ПОДБЛОК: МАРКИРОВКА (С ДАТАМИ) ---
        marking_group = ctk.CTkFrame(block, fg_color="transparent")
        marking_group.pack(fill="x", padx=10)

        # Секция выбора дат
        date_frame = ctk.CTkFrame(marking_group, fg_color="transparent")
        date_frame.pack(pady=5, fill="x")

        # Поле ОТ
        ctk.CTkLabel(date_frame, text="С даты:", font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w")
        self.date_from = ctk.CTkEntry(date_frame, placeholder_text="ГГГГ-ММ-ДД")
        self.date_from.insert(0, datetime.now().strftime("%Y-%m-01"))
        self.date_from.grid(row=1, column=0, padx=(0, 5), sticky="ew")
        self.date_from.bind("<KeyRelease>", lambda e: self._validate_date(self.date_from))

        # Поле ДО
        ctk.CTkLabel(date_frame, text="По дату:", font=ctk.CTkFont(size=12)).grid(row=0, column=1, sticky="w")
        self.date_to = ctk.CTkEntry(date_frame, placeholder_text="ГГГГ-ММ-ДД")
        self.date_to.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self.date_to.grid(row=1, column=1, padx=(5, 0), sticky="ew")
        self.date_to.bind("<KeyRelease>", lambda e: self._validate_date(self.date_to))

        date_frame.columnconfigure((0, 1), weight=1)

        self.btn_export_marking = ctk.CTkButton(
            marking_group, text="Экспорт Кодов маркировки",
            command=self.export_marking_logic, height=40, fg_color="#27ae60", hover_color="#219150"
        )
        self.btn_export_marking.pack(pady=(15, 10), fill="x")

        # --- РАЗДЕЛИТЕЛЬНАЯ ПОЛОСА ---
        separator = ctk.CTkFrame(block, height=2, fg_color=("gray70", "gray30"))
        separator.pack(fill="x", padx=20, pady=20)

        # --- ПОДБЛОК: ОБЩИЕ ШТРИХКОДЫ ---
        self.btn_export_barcodes = ctk.CTkButton(
            block, text="Экспорт всех Штрихкодов",
            command=self.export_barcodes_logic, height=40
        )
        self.btn_export_barcodes.pack(pady=(0, 20), padx=20, fill="x")

    def _init_import_block(self):
        """Блок №2: Импорт данных"""
        block = ctk.CTkFrame(self.main_container)
        block.grid(row=0, column=1, sticky="nsew", padx=10)

        ctk.CTkLabel(block, text="ИМПОРТ И ОБНОВЛЕНИЕ", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        self.btn_import_barcodes = ctk.CTkButton(
            block, text="Загрузить справочник ШК",
            command=self.import_barcodes_logic, height=40, fg_color="#2c3e50"
        )
        self.btn_import_barcodes.pack(pady=20, padx=20, fill="x")

        ctk.CTkLabel(block, text="Ожидание новых задач...", font=ctk.CTkFont(slant="italic"), text_color="gray").pack()

    def _init_maintenance_block(self):
        """Блок №3: Обслуживание (Заглушка)"""
        block = ctk.CTkFrame(self.main_container)
        block.grid(row=0, column=2, sticky="nsew", padx=10)

        ctk.CTkLabel(block, text="ОБСЛУЖИВАНИЕ БД", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        # Пока пусто по просьбе пользователя

    def _validate_date(self, entry_widget):
        """Визуальная подсказка правильности ввода даты"""
        date_str = entry_widget.get()
        # Регулярка для ГГГГ-ММ-ДД
        pattern = r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$"

        if re.match(pattern, date_str):
            entry_widget.configure(border_color="green", text_color=("black", "white"))
        else:
            entry_widget.configure(border_color="red", text_color="red")

    def export_marking_logic(self):
        """Логика экспорта маркировки ИЗ ПОЛЕЙ ВВОДА"""
        # 1. Получаем данные из полей напрямую
        start_date = self.date_from.get()
        end_date = self.date_to.get()

        # 2. Проверка на ошибки (красные поля)
        if self.date_from.cget("border_color") == "red" or self.date_to.cget("border_color") == "red":
            messagebox.showwarning("Формат даты", "Пожалуйста, введите дату в формате ГГГГ-ММ-ДД")
            return

        # 3. Запрос к БД
        df = self.db.get_marking_codes_by_date_range(start_date, end_date)

        if df.empty:
            messagebox.showinfo("Инфо", f"За период с {start_date} по {end_date} данных не найдено.")
            return

        filename = f"Справочник кодов маркировки_{datetime.now().strftime('%d.%m.%Y_%H-%M')}.xlsx"
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile=filename)
        if path:
            df.to_excel(path, index=False)
            messagebox.showinfo("Успех", f"Файл успешно сохранен!")

    def export_barcodes_logic(self):
        df = self.db.get_all_product_barcodes()
        filename = f"Справочник штрикодов маркировки_{datetime.now().strftime('%d.%m.%Y')}.xlsx"
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile=filename)
        if path:
            df.to_excel(path, index=False)
            messagebox.showinfo("Успех", "База штрихкодов экспортирована")

    def import_barcodes_logic(self):
        path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xls")])
        if path:
            try:
                df = pd.read_excel(path)
                # Простейшая проверка структуры
                if "Артикул производителя" not in df.columns:
                    messagebox.showerror("Ошибка", "В файле нет колонки 'Артикул производителя'")
                    return

                success, count = self.db.import_product_barcodes(df)
                if success:
                    messagebox.showinfo("Успех", f"Загружено/обновлено записей: {count}")
                else:
                    messagebox.showerror("Ошибка БД", count)
            except Exception as e:
                messagebox.showerror("Ошибка файла", str(e))