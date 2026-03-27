import threading # Добавь в начало файла
import customtkinter as ctk
import pandas as pd
from tkinter import messagebox, filedialog
from datetime import datetime
import re
import os
import shutil
import logging # Добавлено
from sqlalchemy import text # ОБЯЗАТЕЛЬНО для работы с БД
import time
from ozon_fbs_api import OzonFBSAPI
from wildberries_fbs_api import WildberriesFBSAPI

import requests
# Создаем логгер для конкретного модуля
logger = logging.getLogger(__name__)

class ReportsMode(ctk.CTkFrame):
    def __init__(self, parent, font, db_manager, app_context):
        super().__init__(parent)
        self.db = db_manager
        self.font = font
        self.app_context = app_context
        if not os.path.exists("Data"):
            os.makedirs("Data")
        # Внутри __init__ ReportsMode временно, через некоторое время удалить
        # self.db.patch_marketplace_column()

        # Заголовок страницы
        self.title_label = ctk.CTkLabel(self, text="Отчеты", font=ctk.CTkFont(size=26, weight="bold"))
        self.title_label.pack(pady=(20, 30))

        # Основной контейнер для блоков
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=40)

        # Настройка сетки (3 колонки для блоков)
        self.main_container.columnconfigure((0, 1, 2, 3), weight=1, uniform="group1", pad=20)
        # Даем второй строке (где Блок 5 и низ Блока 4) вес, чтобы они тянулись до низа
        self.main_container.rowconfigure(0, weight=0)
        self.main_container.rowconfigure(1, weight=0)

        if self.app_context.ozon_client_id and self.app_context.ozon_api_key:
            self.ozon_api = OzonFBSAPI(self.app_context.ozon_client_id, self.app_context.ozon_api_key)
        if self.app_context.wb_api_token:
            self.wb_api = WildberriesFBSAPI(self.app_context.wb_api_token)

        self._init_export_block()
        self._init_import_block()
        self._init_maintenance_block()
        self._init_analytics_block()
        self._init_ozon_finance_block()

    def _init_export_block(self):
        """Блок №1: Экспорт данных"""
        block = ctk.CTkFrame(self.main_container)
        block.grid(row=0, column=0, sticky="nsew", padx=10)

        ctk.CTkLabel(block, text="ЭКСПОРТ", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        # --- ПОДБЛОК: МАРКИРОВКА (С ДАТАМИ) ---
        marking_group = ctk.CTkFrame(block, fg_color="transparent")
        marking_group.pack(fill="x", padx=20)

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
            marking_group, text="Экспорт Справочника КИЗ",
            command=self.export_marking_logic, height=40, fg_color="#27ae60", hover_color="#219150"
        )
        self.btn_export_marking.pack(pady=(15, 0), fill="x")
        # --- РАЗДЕЛИТЕЛЬНАЯ ПОЛОСА ---
        separator = ctk.CTkFrame(block, height=2, fg_color="gray30")
        separator.pack(fill="x", padx=20, pady=20)

        # --- ПОДБЛОК: ОБЩИЕ ШТРИХКОДЫ ---
        self.btn_export_barcodes = ctk.CTkButton(
            block, text="Экспорт Справочника ШК",
            command=self.export_barcodes_logic, height=40
        )
        self.btn_export_barcodes.pack(pady=(0, 20), padx=20, fill="x")

    def _init_import_block(self):
        """Блок №2: Импорт справочника"""
        block = ctk.CTkFrame(self.main_container)
        block.grid(row=0, column=1, sticky="nsew", padx=10)

        ctk.CTkLabel(block, text="ИМПОРТ", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        ctk.CTkLabel(block, text="Справочник ШК", font=ctk.CTkFont(size=13, weight="bold")).pack()

        # ДОБАВЛЯЕМ self. к кнопке
        self.btn_import = ctk.CTkButton(
            block,
            text="Импорт Справочник ШК",
            command=self.import_barcodes_logic,
            height=40  # <--- Добавьте этот параметр
        )
        self.btn_import.pack(pady=10, padx=20, fill="x")

        # ДОБАВЛЯЕМ Прогресс-бар (изначально пустой)
        self.progress_bar = ctk.CTkProgressBar(block)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=10, padx=20, fill="x")
        # --- РАЗДЕЛИТЕЛЬ ---
        ctk.CTkFrame(block, height=2, fg_color="gray30").pack(fill="x", padx=30, pady=10)

        # --- НОВОЕ: ИМПОРТ КИЗ ---
        ctk.CTkLabel(block, text="Справочник КИЗ", font=ctk.CTkFont(size=13, weight="bold")).pack()

        self.btn_import_kiz = ctk.CTkButton(
            block, text="Импорт Справочник КИЗ",
            command=self.import_kiz_logic, height=40,
            fg_color="#3498db", hover_color="#2980b9"
        )
        self.btn_import_kiz.pack(pady=10, padx=20, fill="x")

        self.kiz_import_progress = ctk.CTkProgressBar(block)
        self.kiz_import_progress.set(0)
        self.kiz_import_progress.pack(pady=10, padx=20, fill="x")

    def import_kiz_logic(self):
        """Логика импорта КИЗ из Excel"""
        path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xls")])
        if not path:
            return

        self.btn_import_kiz.configure(state="disabled", text="Загрузка КИЗ...")
        self.kiz_import_progress.set(0)

        def worker():
            try:
                df = pd.read_excel(path)

                def update_progress(val):
                    self.after(0, lambda: self.kiz_import_progress.set(val))

                # Вызываем метод в db_manager
                success, count = self.db.import_kiz_directory(df, progress_callback=update_progress)

                self.after(0, lambda: self.finish_kiz_import(success, count))
            except Exception as e:
                logger.error(f"Ошибка в потоке импорта КИЗ: {e}")
                self.after(0, lambda: self.finish_kiz_import(False, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def finish_kiz_import(self, success, result):
        """Завершение импорта КИЗ"""
        self.btn_import_kiz.configure(state="normal", text="Импортировать КИЗ (Excel)")
        if success:
            self.kiz_import_progress.set(1.0)
            messagebox.showinfo("Успех", f"Справочник КИЗ обновлен.\nЗаписей обработано: {result}")
        else:
            self.kiz_import_progress.set(0)
            messagebox.showerror("Ошибка импорта", f"Детали: {result}")
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
        filename = f"Справочник штрихкодов_{datetime.now().strftime('%d.%m.%Y')}.xlsx"
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile=filename)
        if path:
            df.to_excel(path, index=False)
            messagebox.showinfo("Успех", "База штрихкодов экспортирована")

    def import_barcodes_logic(self):
        path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx *.xls")])
        if not path:
            return

        # 1. Сразу блокируем кнопку и сбрасываем прогресс
        self.btn_import.configure(state="disabled", text="Загрузка...")
        self.progress_bar.set(0)

        def worker():
            try:
                # Читаем файл (тяжелая операция)
                df = pd.read_excel(path)

                # Функция-прослойка для обновления прогресс-бара из потока
                def update_progress(val):
                    self.after(0, lambda: self.progress_bar.set(val))

                # Запускаем импорт
                success, count = self.db.import_product_barcodes(df, progress_callback=update_progress)

                # Возвращаемся в главный поток для завершения
                self.after(0, lambda: self.finish_import(success, count))
            except Exception as e:
                # logger.error(f"Ошибка в потоке импорта: {e}")
                self.after(0, lambda: self.finish_import(False, str(e)))

        # Запускаем в отдельном потоке, чтобы GUI не зависал
        threading.Thread(target=worker, daemon=True).start()

    def finish_import(self, success, result):
        """Вызывается по окончании импорта"""
        self.btn_import.configure(state="normal", text="Импортировать справочник")
        if success:
            self.progress_bar.set(1.0)
            messagebox.showinfo("Успех", f"База обновлена. Записей: {result}")
        else:
            self.progress_bar.set(0)
            messagebox.showerror("Ошибка импорта", f"Детали: {result}")

    def _init_maintenance_block(self):
        """Блок №3: Обслуживание БД"""
        block = ctk.CTkFrame(self.main_container)
        block.grid(row=0, column=2, sticky="nsew", padx=10)

        ctk.CTkLabel(block, text="ОБСЛУЖИВАНИЕ БД", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        # --- СИНХРОНИЗАЦИЯ ---
        self.btn_sync = ctk.CTkButton(block, text="Синхронизация с Context", height=40, command=self.run_sync_heal)
        self.btn_sync.pack(pady=(5, 0), padx=20, fill="x")
        self.sync_progress = ctk.CTkProgressBar(block)
        self.sync_progress.pack(pady=(10, 5), padx=20, fill="x")
        self.sync_progress.set(0)

        # --- УДАЛЕНИЕ ДУБЛИКАТОВ ---
        self.btn_dedup = ctk.CTkButton(block, text="Удалить дубликаты", height=40, fg_color="#A36EB5", hover_color="#8E5EA1", command=self.run_deduplication)
        self.btn_dedup.pack(pady=(5, 0), padx=20, fill="x")
        self.dedup_progress = ctk.CTkProgressBar(block)
        self.dedup_progress.pack(pady=(10, 5), padx=20, fill="x")
        self.dedup_progress.set(0)

        # --- РАЗДЕЛИТЕЛЬНАЯ ЛИНИЯ ---
        line = ctk.CTkFrame(block, height=2, fg_color="gray30")
        line.pack(fill="x", padx=30, pady=20)

        # --- РЕЗЕРВНОЕ КОПИРОВАНИЕ ---
        self.btn_backup = ctk.CTkButton(
            block,
            text="Создать бэкап БД",
            height=40,
            fg_color="#28a745",
            hover_color="#218838",
            command=self.run_backup)
        self.btn_backup.pack(pady=5, padx=20, fill="x")

        self.btn_restore = ctk.CTkButton(
            block,
            text="Восстановить из бэкапа",
            height=40,
            fg_color="#dc3545",  # Красный цвет
            hover_color="#c82333",
            command=self.run_restore
        )
        self.btn_restore.pack(pady=5, padx=20, fill="x")

    def run_sync_heal(self):
        """Запуск процесса 'лечения' базы из контекста"""
        # ИСПРАВЛЕНИЕ: Берем контекст напрямую из self.app_context
        if not self.app_context or self.app_context.df is None:
            messagebox.showerror("Ошибка", "Данные в Context (app_context.df) не найдены!")
            return

        self.btn_sync.configure(state="disabled", text="Синхронизация...")
        self.sync_progress.set(0)

        # Передаем сам DataFrame в поток
        source_df = self.app_context.df

        def worker():
            success, result = self.db.heal_database_from_df(
                source_df,
                progress_callback=lambda v: self.after(0, lambda: self.sync_progress.set(v))
            )
            # Возвращаем результат в главный поток
            self.after(0, lambda: self.finish_op(success, f"Синхронизировано строк: {result}", self.btn_sync,
                                                 "Синхронизация с Context"))

        threading.Thread(target=worker, daemon=True).start()

    def run_deduplication(self):
        """Запуск очистки дублей"""
        self.btn_dedup.configure(state="disabled", text="Очистка...")
        self.dedup_progress.set(0)

        def worker():
            # Маленькая задержка для визуального эффекта
            self.after(100, lambda: self.dedup_progress.set(0.3))

            success, result = self.db.deduplicate_product_barcodes()

            self.after(300, lambda: self.dedup_progress.set(0.7))
            self.after(500, lambda: self.dedup_progress.set(1.0))

            self.after(600, lambda: self.finish_op(
                success,
                f"Удалено дублей: {result}",
                self.btn_dedup,
                "Удалить дубликаты"
            ))

        threading.Thread(target=worker, daemon=True).start()

    def finish_op(self, success, message, btn, original_text):
        """Завершение операции и возврат кнопки в исходное состояние"""
        btn.configure(state="normal", text=original_text)
        if success:
            messagebox.showinfo("Готово", message)
        else:
            messagebox.showerror("Ошибка", message)

    def run_backup(self):
        """Создает копию файла БД в папку Data"""
        try:
            source_db = "barcode_print.db"
            if not os.path.exists(source_db):
                messagebox.showerror("Ошибка", "Файл базы данных не найден!")
                return

            backup_dir = "Data"
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)

            # Формируем имя: barcode_print_2024-05-20_14-30.db
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
            backup_name = f"barcode_print_{timestamp}.db"
            dest_path = os.path.join(backup_dir, backup_name)

            shutil.copy2(source_db, dest_path)
            messagebox.showinfo("Успех", f"Резервная копия создана:\n{backup_name}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось создать бэкап: {e}")

    def run_restore(self):
        """Восстановление БД из выбранного файла в папке Data"""
        backup_dir = "Data"
        if not os.path.exists(backup_dir):
            messagebox.showwarning("Внимание", "Папка Data не найдена.")
            return

        # Открываем диалог выбора файла именно в папке Data
        file_path = filedialog.askopenfilename(
            initialdir=backup_dir,
            title="Выберите файл бэкапа для восстановления",
            filetypes=(("Database files", "*.db"), ("All files", "*.*"))
        )

        if not file_path:
            return

        confirm = messagebox.askyesno(
            "Подтверждение",
            "ВНИМАНИЕ! Текущая база данных будет полностью заменена выбранным файлом. \nПродолжить?"
        )

        if confirm:
            try:
                # Закрываем соединение с БД перед заменой (важно!)
                # Если у db_manager есть метод close или dispose, вызываем его.
                # Для SQLite обычно достаточно того, чтобы не было активных запросов.

                target_db = "barcode_print.db"
                # На всякий случай делаем временный бэкап текущей перед заменой
                shutil.copy2(target_db, target_db + ".tmp")

                shutil.copy2(file_path, target_db)

                if os.path.exists(target_db + ".tmp"):
                    os.remove(target_db + ".tmp")

                messagebox.showinfo("Успех",
                                    "База данных успешно восстановлена! \nРекомендуется перезапустить программу.")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Ошибка при восстановлении: {e}")

    # 3. Сам метод создания блока:
    def _init_analytics_block(self):
        """Блок №4: Аналитика и Честный Знак с прогрессбаром"""
        block = ctk.CTkFrame(self.main_container)
        block.grid(row=0, column=3, rowspan=2, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(block, text="АНАЛИТИКА КИЗ", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        # Обычная кнопка (уже есть)
        self.sync_btn = ctk.CTkButton(
            block,
            text="🔄 Обновить статусы\n(быстрая)",
            height=40,
            command=lambda:self.start_sync_statuses(deep=False),
            fg_color="#2c3e50"
        )
        self.sync_btn.pack(fill="x", padx=20, pady=10)
        # Новая кнопка глубокого обновления
        self.deep_sync_btn = ctk.CTkButton(
            block,
            text="Глубокое обновление\n(все статусы)",
            fg_color="#d35400",  # Оранжевый цвет для привлечения внимания
            hover_color="#e67e22",
            command=lambda:self.start_sync_statuses(deep=True)
        )
        self.deep_sync_btn.pack(fill="x", padx=20, pady=10)

        # Прогрессбар для синхронизации
        self.sync_progress = ctk.CTkProgressBar(block)
        self.sync_progress.pack(fill="x", padx=20, pady=(0, 10))
        self.sync_progress.set(0)

        self.export_cz_btn = ctk.CTkButton(
            block,
            text="📑 Экспорт для MarkZnak\n(Выкупленные)",
            height=40,
            command=self.export_for_znak,
            fg_color="#27ae60"
        )
        self.export_cz_btn.pack(fill="x", padx=20, pady=10)

        # Прогрессбар для экспорта
        self.export_progress = ctk.CTkProgressBar(block)
        self.export_progress.pack(fill="x", padx=20, pady=(0, 10))
        self.export_progress.set(0)

        self.gtin_sync_btn = ctk.CTkButton(
            block,
            text="🔄 Собрать GTIN из архива КИЗ",
            height=40,
            command=self.start_gtin_sync
        )
        self.gtin_sync_btn.pack(fill="x", padx=20, pady=10)

        self.gtin_progress = ctk.CTkProgressBar(block)
        self.gtin_progress.set(0)
        self.gtin_progress.pack(fill="x", padx=20, pady=(0, 10))

        self.sync_label = ctk.CTkLabel(block, text="Статус: готов к работе", font=ctk.CTkFont(size=12))
        self.sync_label.pack(pady=10)

        # Кнопка: Синхронизация Ozon
        self.btn_sync_ozon = ctk.CTkButton(
            block,
            text="Синхронизировать возвраты Ozon",
            height=40,
            command=self.on_sync_ozon_returns,
            fg_color="#1f77b4"  # Выделим цветом Ozon
        )
        self.btn_sync_ozon.pack(fill="x", padx=20, pady=10)

        # ПРАВКА 2: Добавлен прогрессбар
        self.ozon_sync_progress = ctk.CTkProgressBar(block)
        self.ozon_sync_progress.pack(fill="x", padx=20, pady=(0, 10))
        self.ozon_sync_progress.set(0)

        # Кнопка: Экспорт для MarkZnak
        self.btn_export_returns = ctk.CTkButton(
            block,
            text="Экспорт возвратов (MarkZnak)",
            height=40,
            command=self.on_export_returns_to_excel,
            fg_color="#2ca02c"  # Зеленая для экспорта
        )
        self.btn_export_returns.pack(fill="x", padx=20, pady=10)

    # --- ПРАВКА 3: Логика с прогрессбаром и потоком ---
    def on_sync_ozon_returns(self):
        """Событие нажатия на кнопку синхронизации возвратов Ozon"""
        self.btn_sync_ozon.configure(state="disabled", text="Синхронизация...")
        self.ozon_sync_progress.set(0.1)
        self.sync_label.configure(text="⏳ Запрос к Ozon API...")

        def worker():
            try:
                # 1. Запрос к API (ИЗМЕНЕНИЕ: собираем обе схемы за 90 дней)
                returns_fbs = self.ozon_api.get_returns_list_v1(schema='FBS', days=90)
                # когда нужно будет fbo, то раскомментировать!
                # returns_fbo = self.ozon_api.get_returns_list_v1(schema='FBO', days=90)

                # Объединяем списки
                returns_data = returns_fbs #+ returns_fbo

                self.after(0, lambda: self.ozon_sync_progress.set(0.5))
                self.after(0, lambda: self.sync_label.configure(text="⏳ Обновление базы данных..."))

                if not returns_data:
                    self.after(0, lambda: messagebox.showinfo("Результат", "Новых возвратов не найдено."))
                    self._reset_ozon_sync_ui()
                    return

                # 2. Обновление БД
                # Если в db_manager.sync_ozon_returns добавлена поддержка callback, передаем её
                # Если нет — просто выполняем
                count = self.db.sync_ozon_returns(returns_data)

                self.after(0, lambda: self.ozon_sync_progress.set(1.0))
                self.after(0, lambda: messagebox.showinfo("Успех", f"Статусы обновлены!\nОбновлено КИЗ: {count}"))

            except Exception as e:
                logger.error(f"Ошибка синхронизации: {e}")
                self.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось обновить данные"))
            finally:
                self.after(0, self._reset_ozon_sync_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _reset_ozon_sync_ui(self):
        """Сброс элементов управления после завершения"""
        self.btn_sync_ozon.configure(state="normal", text="Синхронизировать возвраты Ozon")
        self.ozon_sync_progress.set(0)
        self.sync_label.configure(text="Статус: готов к работе")

    def on_export_returns_to_excel(self):
        """
        Экспорт КИЗ со статусом возврата для MarkZnak.
        Полный аналог export_for_znak с измененным фильтром и префиксом файла.
        """

        def run_export():
            try:
                # 1. Индикация начала (блокировка кнопки и прогрессбар)
                self.after(0, lambda: self.btn_export_returns.configure(state="disabled"))
                self.after(0, lambda: self.export_progress.set(0.1))
                self.after(0, lambda: self.sync_label.configure(text="⏳ Подготовка данных возвратов..."))

                # 2. Запрос к БД (Поля как в export_for_znak, меняем только WHERE)
                query = text("""
                    SELECT 
                        "Код маркировки" AS "КИ (код идентификации)",
                        "Цена" AS "Цена",
                        "Номер отправления" AS "Номер чека"
                    FROM marking_codes 
                    WHERE "Статус" LIKE 'Возврат%'
                """)
                with self.db.engine.connect() as conn:
                    df = pd.read_sql(query, conn)

                if df.empty:
                    self.after(0, lambda: messagebox.showinfo("Экспорт",
                                                              "Нет товаров со статусом 'Возврат' для экспорта."))
                    return

                self.after(0, lambda: self.export_progress.set(0.4))

                # 3. Диалог выбора пути (с измененным префиксом Markznak_Export_Returns_)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                default_filename = f"Markznak_Export_Returns_{timestamp}.xlsx"

                file_path = filedialog.asksaveasfilename(
                    defaultextension=".xlsx",
                    filetypes=[("Excel files", "*.xlsx")],
                    initialfile=default_filename,
                    title="Сохранить экспорт возвратов"
                )

                if not file_path:
                    return

                self.after(0, lambda: self.sync_label.configure(text="💾 Сохранение файла..."))

                # 4. Формирование Excel (полная копия логики формирования из export_for_znak)
                with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Returns')

                    # Автоподбор ширины колонок
                    worksheet = writer.sheets['Returns']
                    for i, col in enumerate(df.columns):
                        column_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                        worksheet.column_dimensions[chr(65 + i)].width = column_len

                self.after(0, lambda: self.export_progress.set(1.0))
                self.after(0, lambda: messagebox.showinfo("Успех", f"Файл возвратов сформирован!\nЗаписей: {len(df)}"))

            except Exception as e:
                logger.error(f"ОШИБКА ЭКСПОРТА ВОЗВРАТОВ: {e}", exc_info=True)
                err_msg = str(e)
                self.after(0, lambda m=err_msg: messagebox.showerror("Ошибка", f"Не удалось создать файл:\n{m}"))
            finally:
                # Возврат UI в исходное состояние
                self.after(0, lambda: self.btn_export_returns.configure(state="normal"))
                self.after(0, lambda: self.export_progress.set(0))
                self.after(0, lambda: self.sync_label.configure(text="Статус: готов к работе"))

        # Запуск в отдельном потоке
        threading.Thread(target=run_export, daemon=True).start()

    def start_gtin_sync(self):
        self.gtin_sync_btn.configure(state="disabled")
        threading.Thread(target=self.run_gtin_sync, daemon=True).start()

    def run_gtin_sync(self):
        try:
            # Вызываем метод из db_manager
            for progress in self.db.sync_gtins_from_history():
                self.gtin_progress.set(progress)

            messagebox.showinfo("Готово", "GTIN успешно синхронизированы на основе истории КИЗ!")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошел сбой: {e}")
        finally:
            self.gtin_sync_btn.configure(state="normal")
            self.gtin_progress.set(0)

    def start_sync_statuses(self, deep=False):
        self.sync_btn.configure(state="disabled")
        self.deep_sync_btn.configure(state="disabled")
        self.sync_progress.set(0)
        self.sync_label.configure(text="⏳ Подключение к API...")
        threading.Thread(target=self._proc_sync_logic, args=(deep,),daemon=True).start()

    def _proc_sync_logic_full(self, deep=False):
        '''
        Запускает синхронизацию по статусам и пытается найти Цену выкупа для Озон
        '''
        try:
            mode_text = "ГЛУБОКОЕ" if deep else "БЫСТРОЕ"
            logger.info(f"--- Запуск синхронизации ({mode_text}) ---")

            from ozon_fbs_api import OzonFBSAPI
            from wildberries_fbs_api import WildberriesFBSAPI
            import time

            ozon_api = self.ozon_api
            wb_api = self.wb_api

            # if self.app_context.ozon_client_id and self.app_context.ozon_api_key:
            #     ozon_api = OzonFBSAPI(self.app_context.ozon_client_id, self.app_context.ozon_api_key)
            # if self.app_context.wb_api_token:
            #     wb_api = WildberriesFBSAPI(self.app_context.wb_api_token)

            # Выборка данных
            where_clause = 'WHERE "Номер отправления" IS NOT NULL AND "Номер отправления" != ""' if deep else \
                'WHERE "Статус" NOT IN ("Выкуплен", "Возврат") AND "Номер отправления" IS NOT NULL'

            with self.db.engine.connect() as conn:
                query = text(
                    f'SELECT "Номер отправления", "Код маркировки", "Маркетплейс", "Статус", "sku", "Цена" FROM marking_codes {where_clause}')
                df_to_update = pd.read_sql(query, conn)

            if df_to_update.empty:
                self._update_sync_ui("✅ Все актуально", 1.0)
                return

            total_items = len(df_to_update)
            updated_count = 0
            processed_count = 0

            for mp, group in df_to_update.groupby("Маркетплейс"):
                mp_name = str(mp).strip()

                # --- БЛОК OZON ---
                if mp_name == 'Ozon' and ozon_api:
                    order_ids = [str(x).strip() for x in group["Номер отправления"].unique().tolist() if
                                 x and str(x).lower() != 'nan']

                    for p_num in order_ids:
                        try:
                            info = ozon_api.get_posting_info(p_num)
                            res = info.get('result', {})
                            if not res:
                                # Если Ozon не ответил по заказу, считаем строки обработанными, чтобы прогресс шел
                                processed_count += len(group[group["Номер отправления"] == p_num])
                                continue

                            actual_price = None
                            target_sku = str(group[group["Номер отправления"] == p_num]["sku"].iloc[0])

                            # Поиск цены в фин. данных
                            fin_data = res.get('financial_data')
                            if fin_data:
                                for p in fin_data.get('products', []):
                                    if str(p.get('sku')) == target_sku:
                                        actual_price = p.get('price')
                                        break

                            # Поиск в транзакциях, если нет в заказе
                            if not actual_price:
                                try:
                                    trans_resp = ozon_api.get_order_transaction_info(p_num)
                                    for op in trans_resp.get('result', {}).get('operations', []):
                                        if op.get('operation_type') in ['OperationRetailSell',
                                                                        'OperationRetailSellRefund']:
                                            for it in op.get('items', []):
                                                if str(it.get('sku')) == target_sku:
                                                    actual_price = it.get('price')
                                                    break
                                        if actual_price: break
                                except:
                                    pass

                            new_status = self._map_ozon_status(res.get('status'))
                            mask = group["Номер отправления"] == p_num

                            for _, row in group[mask].iterrows():
                                # ИСПРАВЛЕНИЕ ЦЕНЫ: Округляем до 2 знаков перед записью
                                final_price = round(float(actual_price), 2) if actual_price else row['Цена']
                                if final_price:
                                    final_price = round(float(final_price), 2)

                                self.db.update_kiz_status_and_price(row['Код маркировки'], new_status, final_price)
                                updated_count += 1
                                processed_count += 1  # Считаем каждую строку

                        except Exception as e:
                            logger.error(f"Ошибка Ozon {p_num}: {e}")
                            processed_count += len(group[group["Номер отправления"] == p_num])

                        self._update_sync_ui(f"Ozon: {processed_count}/{total_items}", processed_count / total_items)
                        time.sleep(0.1)

                # --- БЛОК WILDBERRIES ---
                elif mp_name in ['WB', 'Wildberries'] and wb_api:
                    raw_ids = group["Номер отправления"].unique().tolist()
                    clean_ids = []
                    for rid in raw_ids:
                        try:
                            val = str(rid).strip().lower()
                            if val and val != 'nan': clean_ids.append(int(float(val)))
                        except:
                            continue

                    for i in range(0, len(clean_ids), 100):
                        chunk = clean_ids[i:i + 100]
                        if not chunk: continue

                        try:
                            statuses = wb_api.get_orders_statuses(chunk)
                            if statuses:
                                for s in statuses:
                                    wb_id = str(s.get('orderId'))
                                    new_stat = self._map_wb_status(s.get('status'))

                                    # Фильтруем строки в группе по этому WB ID
                                    mask = group["Номер отправления"].astype(str).str.contains(wb_id, na=False)
                                    sub_group = group[mask]

                                    for _, row in sub_group.iterrows():
                                        # Для WB тоже принудительно округляем старую цену, чтобы убрать лишние нули
                                        old_price = round(float(row['Цена']), 2) if row['Цена'] else 0.0
                                        self.db.update_kiz_status_and_price(row['Код маркировки'], new_stat, old_price)
                                        updated_count += 1
                                        processed_count += 1
                        except Exception as e:
                            logger.error(f"WB error: {e}")
                            processed_count += len(chunk)  # В случае ошибки сдвигаем прогресс

                        self._update_sync_ui(f"WB: {processed_count}/{total_items}",
                                             min(processed_count / total_items, 0.99))

            # ФИНАЛ: Принудительно 100% и красивый статус
            self._update_sync_ui(f"✅ Обновлено: {updated_count}", 1.0)
            logger.info(f"Синхронизация завершена. Обновлено записей: {updated_count}")
            messagebox.showinfo("Готово", f"Синхронизация завершена.\nОбновлено записей: {updated_count}")

        except Exception as e:
            logger.error(f"Критическая ошибка: {e}", exc_info=True)
            self._update_sync_ui("❌ Ошибка", 0)
        finally:
            self.after(0, lambda: self.sync_btn.configure(state="normal"))
            self.after(0, lambda: self.deep_sync_btn.configure(state="normal"))

    def _proc_sync_logic(self, deep=False):
        try:
            mode_text = "ГЛУБОКОЕ" if deep else "БЫСТРОЕ"
            logger.info(f"--- Запуск синхронизации ({mode_text}) ---")

            # from ozon_fbs_api import OzonFBSAPI
            # from wildberries_fbs_api import WildberriesFBSAPI
            #
            # ozon_api = None
            # wb_api = None
            #
            # if self.app_context.ozon_client_id and self.app_context.ozon_api_key:
            #     ozon_api = OzonFBSAPI(self.app_context.ozon_client_id, self.app_context.ozon_api_key)
            # if self.app_context.wb_api_token:
            #     wb_api = WildberriesFBSAPI(self.app_context.wb_api_token)

            where_clause = 'WHERE "Номер отправления" IS NOT NULL AND "Номер отправления" != ""' if deep else \
                           'WHERE "Статус" NOT IN ("Выкуплен", "Возврат") AND "Номер отправления" IS NOT NULL'

            with self.db.engine.connect() as conn:
                query = text(f'SELECT "Номер отправления", "Код маркировки", "Маркетплейс" FROM marking_codes {where_clause}')
                df_to_update = pd.read_sql(query, conn)

            if df_to_update.empty:
                self._update_sync_ui("✅ Все актуально", 1.0)
                return

            # --- ДИАГНОСТИКА ---
            found_mps = df_to_update["Маркетплейс"].unique().tolist()
            logger.info(f"В базе найдены записи для маркетплейсов: {found_mps}")
            # -------------------

            total_items = len(df_to_update)
            updated_count = 0
            processed_count = 0

            for mp, group in df_to_update.groupby("Маркетплейс"):
                mp_name = str(mp).strip()
                logger.info(f"Начало обработки группы: {mp_name} (записей: {len(group)})")
                # --- OZON (Только статусы) ---
                if mp_name == 'Ozon':
                    order_ids = [str(x).strip() for x in group["Номер отправления"].unique().tolist() if x and str(x).lower() != 'nan']
                    for p_num in order_ids:
                        try:
                            info = self.ozon_api.get_posting_info(p_num)
                            res = info.get('result', {})
                            if res:
                                new_status = self._map_ozon_status(res.get('status'))
                                # ИЗМЕНЕНИЕ: Извлекаем дату события из Ozon
                                # API Ozon обычно отдает 'in_process_at' или 'shipment_date' в формате '2024-03-19T10:00:00Z'
                                raw_date = res.get('in_process_at') or res.get('shipment_date')
                                sale_date = None
                                if raw_date:
                                    # Очищаем строку от 'T' и 'Z', чтобы SQLite правильно её понял
                                    sale_date = raw_date.replace('T', ' ')[:19]
                                mask = group["Номер отправления"] == p_num
                                for _, row in group[mask].iterrows():
                                    self.db.update_kiz_status(row['Код маркировки'], new_status, sale_date=sale_date)
                                    updated_count += 1
                                    processed_count += 1
                        except: pass
                        self._update_sync_ui(f"Ozon: {processed_count}/{total_items}", processed_count/total_items)

                # --- WB (Обновление статусов) ---
                elif mp_name == 'WB':
                    # 1. Извлекаем ID строго как строки, чтобы не терять цифры в конце
                    raw_ids = [str(x).strip() for x in group["Номер отправления"].unique().tolist()
                               if x and str(x).lower() != 'nan']

                    logger.info(f"WB: Начинаю обработку {len(group)} записей...")
                    # API WB v3 принимает список чисел, преобразуем аккуратно
                    numeric_ids = []
                    for rid in raw_ids:
                        try:
                            # Убираем возможную точку (если затесалась из excel) и берем только целую часть
                            clean_id = rid.split('.')[0]
                            numeric_ids.append(int(clean_id))
                        except:
                            logger.error(f"WB: Ошибка с  {rid} номером отправления...")
                            continue

                    # Обработка пачками по 100 штук
                    for i in range(0, len(numeric_ids), 100):
                        chunk = numeric_ids[i:i + 100]
                        try:
                            statuses = self.wb_api.get_orders_statuses(chunk)
                            if statuses:
                                for s in statuses:
                                    wb_id = str(s.get('id'))
                                    raw_stat = s.get('wbStatus')
                                    new_stat = self._map_wb_status(raw_stat)

                                    if not new_stat:
                                        logger.error(f"WB: Ошибка с вычислением статуса {raw_stat}...")
                                        continue

                                    # Для WB API v3 в этом методе нет даты события.
                                    # Используем текущее время как дату фиксации статуса
                                    sale_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                                    # Точное сопоставление (не contains, а равенство строк)
                                    # Сначала приводим колонку к строке без .0
                                    mask = group["Номер отправления"].apply(lambda x: str(x).split('.')[0]) == wb_id

                                    for _, row in group[mask].iterrows():
                                        # Вызываем ваш метод (он сам разнесет даты по колонкам)
                                        self.db.update_kiz_status(
                                            row['Код маркировки'],
                                            new_stat,
                                            sale_date=sale_date
                                        )
                                        updated_count += 1
                                        processed_count += 1
                        except Exception as e:
                            logger.error(f"Ошибка WB при обновлении пачки: {e}")
                            pass
                        self._update_sync_ui(f"WB: {processed_count}/{total_items}", processed_count / total_items)

            self._update_sync_ui(f"✅ Готово: {updated_count}", 1.0)
            messagebox.showinfo("Готово", f"Обновлено статусов: {updated_count}")
        except Exception as e:
            logger.error(f"Ошибка синхронизации: {e}")

    def _update_sync_ui(self, text_val, progress_val):
        """Безопасное обновление UI из потока"""
        self.after(0, lambda: self.sync_label.configure(text=text_val))
        self.after(0, lambda: self.sync_progress.set(progress_val))

    def _map_wb_status(self, wb_status):
        mapped = {
            'waiting': 'Ожидает приемки',
            'sorted': 'Ожидает приемки',
            'accepted_by_carrier': 'Ожидает приемки',
            'sold': 'Выкуплен',
            'canceled': 'Возврат',
            'defect': 'Возврат',
            'declined_by_client': 'Возврат',
            'canceled_by_client': 'Возврат',
            'sent_to_carrier': 'Возврат на склад'
        }
        res = mapped.get(wb_status)
        if wb_status and not res:
            logger.debug(f"Статус WB '{wb_status}' пропущен (не финальный)")
        return res

    def _map_ozon_status(self, ozon_status):
        if ozon_status in ['delivered', 'client_received']:
            return 'Выкуплен'
        if ozon_status in ['cancelled', 'not_accepted', 'returned_to_seller']:
            return 'Возврат'

        if ozon_status:
            logger.debug(f"Статус Ozon '{ozon_status}' пропущен (не финальный)")
        return None

    def export_for_znak_csv(self):
        """Экспорт выкупленных КИЗ в формате XLSX для Markznak"""
        # Сразу блокируем кнопку, чтобы не нажать дважды
        self.export_cz_btn.configure(state="disabled")
        self.sync_label.configure(text="⏳ Подготовка...")
        self.export_progress.set(0.1)

        # 1. Диалог выбора файла (должен быть в основном потоке)
        try:
            file_path = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel files", "*.xlsx")],
                initialfile=f"Markznak_Export_{datetime.now().strftime('%d%m%Y')}.xlsx",
                title = "Сохранить экспорт для Markznak"
            )
            if not file_path:
                return
        except Exception as e:
            logger.error(f"Ошибка вызова диалога: {e}")
            self.export_cz_btn.configure(state="normal")
            return

        if not file_path:
            self.export_cz_btn.configure(state="normal")
            self.sync_label.configure(text="Статус: отменено")
            self.export_progress.set(0)
            return

        def worker():
            try:
                # 2. Запрос данных
                # Проверяем наличие нужных колонок в БД через запрос
                query = text('''
                    SELECT 
                        "Код маркировки" AS "КИ (код идентификации)",
                        "Цена" AS "Цена",
                        "Номер отправления" AS "Номер чека"
                    FROM marking_codes
                    WHERE "Статус" = 'Выкуплен'
                ''')

                df = pd.read_sql(query, self.db.engine)

                if df.empty:
                    self.after(0, lambda: messagebox.showwarning("Пусто", "Нет данных со статусом 'Выкуплен'"))
                    return

                # --- ЗАЩИТА ОТ ЗАВИСАНИЯ (Обработка данных) ---
                # Заполняем пустые значения, чтобы .str.replace не вызвал ошибку
                df["КИ (код идентификации)"] = df["КИ (код идентификации)"].fillna("").astype(str)
                df["Цена"] = df["Цена"].fillna(0)
                df["Номер чека"] = df["Номер чека"].fillna("").astype(str)

                # Заменяем спецсимвол GS (разделитель групп) на текстовый код для Markznak
                df["КИ (код идентификации)"] = df["КИ (код идентификации)"].str.replace('\x1d', '_x001d_', regex=False)

                # 3. Сохранение
                # Используем движок openpyxl, индекс не нужен
                df.to_excel(file_path, index=False, engine='openpyxl')

                # 4. Успешное завершение
                count = len(df)
                self.after(0, lambda: self.export_progress.set(1.0))
                self.after(0, lambda: self.sync_label.configure(text="✅ Готово"))
                self.after(0, lambda: messagebox.showinfo("Успех", f"Успешно экспортировано {count} строк."))

            except Exception as e:
                # Если что-то пошло не так в потоке — выводим ошибку
                logger.error(f"КРИТИЧЕСКАЯ ОШИБКА ЭКСПОРТА: {e}", exc_info=True)
                self.after(0, lambda: messagebox.showerror("Ошибка потока", f"Произошла ошибка при сборке файла:\n{e}"))

            finally:
                # В ЛЮБОМ СЛУЧАЕ возвращаем кнопку в рабочее состояние
                self.after(500, lambda: self.export_cz_btn.configure(state="normal"))
                self.after(3000, lambda: self.export_progress.set(0))
                self.after(3000, lambda: self.sync_label.configure(text="Статус: готов к работе"))

        # Запуск потока
        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def export_for_znak(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            initialfile=f"Markznak_Export_{datetime.now().strftime('%d%m%Y')}.xlsx"
        )
        if not file_path:
            return

        self.export_cz_btn.configure(state="disabled")
        self.export_progress.set(0.1)
        self.sync_label.configure(text="⏳ Подготовка Excel...")

        def run_export():
            try:
                # 1. Запрашиваем реальное имя из БД ("Код маркировки")
                # Но для файла Markznak нам нужно имя "КИ (код идентификации)"
                query = text('''SELECT 
                                        "Код маркировки" AS "КИ (код идентификации)",
                                        "Цена" AS "Цена",
                                        "Номер отправления" AS "Номер чека"
                                    FROM marking_codes
                                    WHERE "Статус" = 'Выкуплен'
                                ''')
                with self.db.engine.connect() as conn:
                    df = pd.read_sql(query, conn)

                if df.empty:
                    self.after(0, lambda: messagebox.showwarning("Внимание", "Нет данных для экспорта."))
                    return

                # --- ЗАЩИТА ОТ ЗАВИСАНИЯ (Обработка данных) ---
                # Заполняем пустые значения, чтобы .str.replace не вызвал ошибку
                df["КИ (код идентификации)"] = df["КИ (код идентификации)"].fillna("").astype(str)
                df["Цена"] = df["Цена"].fillna(0)
                df["Номер чека"] = df["Номер чека"].fillna("").astype(str)

                # Заменяем спецсимвол GS (разделитель групп) на текстовый код для Markznak
                df["КИ (код идентификации)"] = df["КИ (код идентификации)"].str.replace('\x1d', '_x001d_',
                                                                                        regex=False)

                # 4. Сохранение в XLSX
                df.to_excel(file_path, index=False, engine='openpyxl')

                # Успех
                count = len(df)
                self.after(0, lambda: self.export_progress.set(1.0))
                self.after(0, lambda: self.sync_label.configure(text="✅ Готово"))
                self.after(0, lambda: messagebox.showinfo("Успех", f"Успешно экспортировано {count} строк в Excel."))

            except Exception as e:
                error_msg = str(e) # Сохраняем текст ошибки в строку заранее
                logger.error(f"ОШИБКА ЭКСПОРТА XLSX: {error_msg}", exc_info=True)
                # Передаем строку ошибки в lambda через аргумент по умолчанию
                self.after(0, lambda m=error_msg: messagebox.showerror("Ошибка", f"Не удалось создать Excel файл:\n{m}"))
            finally:
                # В ЛЮБОМ СЛУЧАЕ возвращаем кнопку в рабочее состояние
                self.after(500, lambda: self.export_cz_btn.configure(state="normal"))
                self.after(3000, lambda: self.export_progress.set(0))
                self.after(3000, lambda: self.sync_label.configure(text="Статус: готов к работе"))

        threading.Thread(target=run_export, daemon=True).start()

    def _init_ozon_finance_block(self):
        """Блок №5: Финансовый отчет Озон (Исправленный визуал)"""
        block = ctk.CTkFrame(self.main_container)
        # Размещаем под Аналитикой.
        # Добавляем pady=(20, 40), чтобы визуально увеличить отступ снизу и "растянуть" зону
        block.grid(row=1, column=2, sticky="nsew", padx=10, pady=10)

        ctk.CTkLabel(block, text="ФИНАНСОВЫЙ ОТЧЕТ OZON", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=10)

        # 1. Даты периода в одну строку (как в Экспорте)
        date_frame = ctk.CTkFrame(block, fg_color="transparent")
        date_frame.pack(fill="x", padx=20, pady=5)

        # Настройка сетки для дат
        ctk.CTkLabel(date_frame, text="С даты:", font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w")
        self.fin_date_from = ctk.CTkEntry(date_frame, placeholder_text="ГГГГ-ММ-ДД")
        self.fin_date_from.insert(0, datetime.now().strftime("%Y-%m-01"))
        self.fin_date_from.grid(row=1, column=0, padx=(0, 5), sticky="ew")

        ctk.CTkLabel(date_frame, text="По дату:", font=ctk.CTkFont(size=12)).grid(row=0, column=1, sticky="w")
        self.fin_date_to = ctk.CTkEntry(date_frame, placeholder_text="ГГГГ-ММ-ДД")
        self.fin_date_to.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self.fin_date_to.grid(row=1, column=1, padx=(5, 0), sticky="ew")

        date_frame.columnconfigure((0, 1), weight=1)

        # 2. Кнопки с высотой 40 (как в Аналитике/Экспорте)
        self.btn_request_fin = ctk.CTkButton(
            block, text="Запросить фин. отчет",
            command=self._request_ozon_finance_report,
            fg_color="#34495e",
            height=40  # Увеличенная высота
        )
        self.btn_request_fin.pack(pady=(20, 10), padx=20, fill="x")

        self.btn_import_fin = ctk.CTkButton(
            block, text="Импортировать отчет\n (обновление цены)",
            command=self._import_ozon_finance_report,
            fg_color="#2980b9",
            height=40  # Увеличенная высота
        )
        self.btn_import_fin.pack(pady=10, padx=20, fill="x")

        # Дополнительный пустой лейбл внизу для "растягивания" серой области вниз
        ctk.CTkLabel(block, text="", height=10).pack()

    def _request_ozon_finance_report(self):
        """Реализация Пункта 3: Запрос отчета через методы класса OzonFBSAPI"""
        date_from = self.fin_date_from.get()
        date_to = self.fin_date_to.get()

        if not re.match(r"\d{4}-\d{2}-\d{2}", date_from) or not re.match(r"\d{4}-\d{2}-\d{2}", date_to):
            messagebox.showerror("Ошибка", "Используйте формат ГГГГ-ММ-ДД")
            return

        self.btn_request_fin.configure(state="disabled", text="⏳ Формирование...")

        def run_request():
            try:
                from ozon_fbs_api import OzonFBSAPI
                # Инициализируем API (сессия и заголовки создаются внутри __init__)
                api = OzonFBSAPI(self.app_context.ozon_client_id, self.app_context.ozon_api_key)

                # 1. Создаем запрос на отчет
                res_create = api.create_orders_report(date_from, date_to)
                report_code = res_create.get('result', {}).get('code')

                if not report_code:
                    raise ValueError(f"Ozon не вернул код отчета: {res_create}")

                # 2. Ожидание готовности
                report_url = None
                attempts = 0
                max_attempts = 30

                while attempts < max_attempts:
                    time.sleep(5)
                    attempts += 1

                    res_info = api.get_report_info(report_code)
                    status_data = res_info.get('result', {})

                    status = status_data.get('status')
                    if status == 'success':
                        report_url = status_data.get('file')
                        break
                    elif status == 'failed':
                        raise ValueError("Ozon отклонил генерацию отчета.")

                    logger.info(f"Ожидание отчета {report_code}: {status}...")

                if not report_url:
                    raise TimeoutError("Превышено время ожидания отчета.")

                # 3. Скачивание (используем ту же сессию API для скачивания)
                if not os.path.exists("Data"):
                    os.makedirs("Data")

                file_name = f"Data/ozon_fin_{date_from}_{date_to}.csv"
                file_resp = api.session.get(report_url)  # Используем сессию из API класса

                with open(file_name, 'wb') as f:
                    f.write(file_resp.content)

                self.after(0, lambda: messagebox.showinfo("Успех",
                                                          f"Отчет готов и сохранен в папку Data:\n{os.path.basename(file_name)}"))

            except Exception as e:
                error_text = str(e)
                logger.error(f"ОШИБКА API OZON: {error_text}", exc_info=True)
                self.after(0,
                           lambda m=error_text: messagebox.showerror("Ошибка API", f"Не удалось получить отчет:\n{m}"))
            finally:
                self.after(0, lambda: self.btn_request_fin.configure(state="normal", text="Запросить фин. отчет"))

        threading.Thread(target=run_request, daemon=True).start()

    def _import_ozon_finance_report(self):
        """Реализация Пункта 2: Импорт цен из CSV по SKU"""
        file_path = filedialog.askopenfilename(
            title="Выберите файл postings.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )

        if not file_path:
            return

        # Блокируем кнопку и запускаем поток
        self.btn_import_fin.configure(state="disabled")

        def run_import():
            try:
                # 1. Чтение файла (Ozon часто использует UTF-8 или CP1251)
                try:
                    df = pd.read_csv(file_path, sep=';', encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(file_path, sep=';', encoding='cp1251')

                # Очистка названий колонок от пробелов
                df.columns = [c.strip() for c in df.columns]

                # Проверка наличия нужных колонок
                required = ['SKU', 'Оплачено покупателем']
                if not all(col in df.columns for col in required):
                    missing = [col for col in required if col not in df.columns]
                    raise ValueError(f"В файле не найдены колонки: {', '.join(missing)}")

                # 2. Подготовка данных для обновления
                # Оставляем только уникальные SKU, берем последнюю встреченную цену
                # (Если один товар купили дважды по разной цене, в справочник попадет последняя)
                price_map = {}
                for _, row in df.iterrows():
                    sku = str(row['SKU']).strip()
                    try:
                        # Превращаем цену в число (заменяем запятую на точку, если она есть)
                        val = str(row['Оплачено покупателем']).replace(',', '.')
                        price = round(float(val), 2)
                        price_map[sku] = price
                    except (ValueError, TypeError):
                        continue

                if not price_map:
                    self.after(0, lambda: messagebox.showwarning("Внимание", "Не удалось извлечь данные о ценах."))
                    return

                # 3. Обновление базы данных
                updated_sku_count = 0
                total_kiz_affected = 0

                with self.db.engine.begin() as conn:  # Транзакция
                    for sku, price in price_map.items():
                        # Обновляем все записи с этим SKU
                        result = conn.execute(
                            text('UPDATE marking_codes SET "Цена" = :price WHERE "sku" = :sku'),
                            {"price": price, "sku": sku}
                        )
                        if result.rowcount > 0:
                            updated_sku_count += 1
                            total_kiz_affected += result.rowcount

                # 4. Результат
                self.after(0, lambda: messagebox.showinfo(
                    "Успех",
                    f"Обновление завершено!\n\n"
                    f"Найдено в файле уникальных SKU: {len(price_map)}\n"
                    f"Обновлено цен для товаров: {updated_sku_count}\n"
                    f"Всего изменено записей КИЗ: {total_kiz_affected}"
                ))

            except Exception as e:
                logger.error(f"ОШИБКА ИМПОРТА ЦЕН: {e}", exc_info=True)
                error_text = str(e)
                self.after(0, lambda m=error_text: messagebox.showerror("Ошибка", f"Ошибка при парсинге файла:\n{m}"))
            finally:
                self.after(0, lambda: self.btn_import_fin.configure(state="normal"))

        threading.Thread(target=run_import, daemon=True).start()

    def on_sync_returns_pressed(self):
        # 1. Получаем данные через API (Шаг 1)
        returns_data = self.app_context.ozon_api.get_fbs_returns()

        if not returns_data:
            messagebox.showinfo("Инфо", "Новых возвратов не найдено.")
            return

        # 2. Отправляем в базу на синхронизацию (Шаг 2)
        # self.app_context.db_manager - это ваш экземпляр менеджера БД
        count = self.app_context.db_manager.sync_ozon_returns(returns_data)

        messagebox.showinfo("Успех", f"Статусы обновлены! Товаров в возврате: {count}")