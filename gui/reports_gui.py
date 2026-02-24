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

class ReportsMode(ctk.CTkFrame):
    def __init__(self, parent, font, db_manager, app_context):
        super().__init__(parent)
        self.db = db_manager
        self.font = font
        self.app_context = app_context

        # Внутри __init__ ReportsMode временно, через некоторое время удалить
        self.db.patch_marketplace_column()

        # Заголовок страницы
        self.title_label = ctk.CTkLabel(self, text="Отчеты", font=ctk.CTkFont(size=26, weight="bold"))
        self.title_label.pack(pady=(20, 30))

        # Основной контейнер для блоков
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=40)

        # Настройка сетки (3 колонки для блоков)
        self.main_container.columnconfigure((0, 1, 2, 3), weight=1, uniform="group1", pad=20)

        self._init_export_block()
        self._init_import_block()
        self._init_maintenance_block()
        self._init_analytics_block()

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
        """Блок №2: Импорт справочника"""
        block = ctk.CTkFrame(self.main_container)
        block.grid(row=0, column=1, sticky="nsew", padx=10)

        ctk.CTkLabel(block, text="ИМПОРТ", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        # ДОБАВЛЯЕМ self. к кнопке
        self.btn_import = ctk.CTkButton(
            block,
            text="Импортировать справочник",
            command=self.import_barcodes_logic,
            height=40  # <--- Добавьте этот параметр
        )
        self.btn_import.pack(pady=10, padx=20, fill="x")

        # ДОБАВЛЯЕМ Прогресс-бар (изначально пустой)
        self.progress_bar = ctk.CTkProgressBar(block)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=10, padx=20, fill="x")

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
                # logging.error(f"Ошибка в потоке импорта: {e}")
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
        block.grid(row=0, column=3, sticky="nsew", padx=10)

        ctk.CTkLabel(block, text="АНАЛИТИКА КИЗ", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        self.sync_btn = ctk.CTkButton(
            block,
            text="🔄 Обновить статусы\n(API WB/Ozon)",
            command=self.start_sync_statuses,
            fg_color="#2c3e50"
        )
        self.sync_btn.pack(fill="x", padx=20, pady=10)

        # Прогрессбар для синхронизации
        self.sync_progress = ctk.CTkProgressBar(block)
        self.sync_progress.pack(fill="x", padx=20, pady=(0, 10))
        self.sync_progress.set(0)

        self.export_cz_btn = ctk.CTkButton(
            block,
            text="📑 Экспорт для ЧЗ\n(Выкупленные)",
            command=self.export_for_znak,
            fg_color="#27ae60"
        )
        self.export_cz_btn.pack(fill="x", padx=20, pady=10)

        # Прогрессбар для экспорта
        self.export_progress = ctk.CTkProgressBar(block)
        self.export_progress.pack(fill="x", padx=20, pady=(0, 10))
        self.export_progress.set(0)

        self.sync_label = ctk.CTkLabel(block, text="Статус: готов к работе", font=ctk.CTkFont(size=12))
        self.sync_label.pack(pady=10)

    def start_sync_statuses(self):
        self.sync_btn.configure(state="disabled")
        self.sync_progress.set(0)
        self.sync_label.configure(text="⏳ Подключение к API...")
        threading.Thread(target=self._proc_sync_logic, daemon=True).start()

    def _proc_sync_logic_olded(self):
        try:
            # 1. Инициализируем API (берем данные из контекста, как в fbs_ozon_gui)
            from ozon_fbs_api import OzonFBSAPI
            from wildberries_fbs_api import WildberriesFBSAPI

            ozon_api = None
            wb_api = None

            if self.app_context.ozon_client_id and self.app_context.ozon_api_key:
                ozon_api = OzonFBSAPI(self.app_context.ozon_client_id, self.app_context.ozon_api_key)

            if self.app_context.wb_api_token:
                wb_api = WildberriesFBSAPI(self.app_context.wb_api_token)

            # 2. Получаем данные из БД
            with self.db.engine.connect() as conn:
                query = text(
                    'SELECT "Номер отправления", "Код маркировки", "Маркетплейс", "Статус" FROM marking_codes WHERE "Статус" NOT IN ("Выкуплен", "Возврат")')
                df_to_update = pd.read_sql(query, conn)

            if df_to_update.empty:
                self._update_sync_ui("✅ Все актуально", 1.0)
                return

            total_items = len(df_to_update)
            updated_count = 0
            processed_count = 0

            # 3. Цикл по маркетплейсам
            for mp, group in df_to_update.groupby("Маркетплейс"):
                mp_name = str(mp).strip()
                order_ids = [str(x).strip() for x in group["Номер отправления"].unique().tolist() if x]

                # --- ЛОГИКА OZON ---
                if mp_name == 'Ozon' and ozon_api:
                    for p_num in order_ids:
                        try:
                            # Используем метод, который точно есть в ozon_fbs_api.py
                            info = ozon_api.get_posting_info(p_num)
                            # В Ozon API статус лежит в result -> status
                            ozon_status = info.get('result', {}).get('status')
                            new_status = self._map_ozon_status(ozon_status)

                            if new_status:
                                mask = group["Номер отправления"].astype(str) == p_num
                                for _, row in group[mask].iterrows():
                                    if row['Статус'] != new_status:
                                        self.db.update_kiz_status(row['Код маркировки'], new_status)
                                        updated_count += 1
                        except Exception as e:
                            logging.error(f"Ошибка Ozon {p_num}: {e}")

                        processed_count += 1
                        self._update_sync_ui(f"Проверка Ozon... {processed_count}/{total_items}",
                                             processed_count / total_items)

                # --- ЛОГИКА WB ---
                elif mp_name == 'WB' and wb_api:
                    # У WB есть метод get_orders_statuses, который принимает список ID
                    for i in range(0, len(order_ids), 100):
                        chunk = order_ids[i:i + 100]
                        try:
                            # В wildberries_fbs_api.py этот метод возвращает список статусов
                            statuses = wb_api.get_orders_statuses(chunk)
                            for s in statuses:
                                wb_id = str(s.get('orderId'))
                                wb_status = s.get('status')
                                new_status = self._map_wb_status(wb_status)

                                if new_status:
                                    mask = group["Номер отправления"].astype(str) == wb_id
                                    for _, row in group[mask].iterrows():
                                        if row['Статус'] != new_status:
                                            self.db.update_kiz_status(row['Код маркировки'], new_status)
                                            updated_count += 1
                        except Exception as e:
                            logging.error(f"Ошибка WB: {e}")

                        processed_count += len(chunk)
                        self._update_sync_ui(f"Проверка WB... {processed_count}/{total_items}",
                                             processed_count / total_items)

            self._update_sync_ui(f"✅ Обновлено: {updated_count}", 1.0)
            messagebox.showinfo("Готово", f"Синхронизация завершена.\nОбновлено статусов: {updated_count}")

        except Exception as e:
            logging.error(f"Ошибка синхронизации: {e}", exc_info=True)
            self._update_sync_ui("❌ Ошибка", 0)
        finally:
            self.after(0, lambda: self.sync_btn.configure(state="normal"))

    def _proc_sync_logic(self):
        try:
            logging.info("--- Запуск синхронизации статусов ---")

            # 1. Инициализация API
            from ozon_fbs_api import OzonFBSAPI
            from wildberries_fbs_api import WildberriesFBSAPI

            ozon_api = None
            wb_api = None

            if self.app_context.ozon_client_id and self.app_context.ozon_api_key:
                ozon_api = OzonFBSAPI(self.app_context.ozon_client_id, self.app_context.ozon_api_key)
                logging.info("API Ozon инициализировано")

            if self.app_context.wb_api_token:
                wb_api = WildberriesFBSAPI(self.app_context.wb_api_token)
                logging.info("API WB инициализировано")

            # 2. Получение данных
            with self.db.engine.connect() as conn:
                query = text(
                    'SELECT "Номер отправления", "Код маркировки", "Маркетплейс", "Статус" FROM marking_codes WHERE "Статус" NOT IN ("Выкуплен", "Возврат")')
                df_to_update = pd.read_sql(query, conn)

            logging.info(f"Найдено {len(df_to_update)} поз. для проверки в API")

            if df_to_update.empty:
                self._update_sync_ui("✅ Все актуально", 1.0)
                logging.info("Синхронизация не требуется: все статусы финальные")
                return

            total_items = len(df_to_update)
            updated_count = 0
            processed_count = 0

            # 3. Обработка по маркетплейсам
            for mp, group in df_to_update.groupby("Маркетплейс"):
                mp_name = str(mp).strip()
                order_ids = [str(x).strip() for x in group["Номер отправления"].unique().tolist() if x]

                logging.info(f"Обработка маркетплейса {mp_name}: {len(order_ids)} заказов")

                # OZON
                if mp_name == 'Ozon' and ozon_api:
                    for p_num in order_ids:
                        try:
                            info = ozon_api.get_posting_info(p_num)
                            res = info.get('result', {})
                            ozon_status = res.get('status') if isinstance(res, dict) else info.get('status')

                            new_status = self._map_ozon_status(ozon_status)
                            logging.info(f"Ozon заказ {p_num}: статус API '{ozon_status}' -> '{new_status}'")

                            if new_status:
                                mask = group["Номер отправления"].astype(str) == p_num
                                for _, row in group[mask].iterrows():
                                    if row['Статус'] != new_status:
                                        self.db.update_kiz_status(row['Код маркировки'], new_status)
                                        updated_count += 1
                        except Exception as e:
                            logging.error(f"Ошибка запроса Ozon {p_num}: {e}")

                        processed_count += 1
                        self._update_sync_ui(f"Ozon: {processed_count}/{total_items}", processed_count / total_items)

                # WB
                elif mp_name == 'WB' and wb_api:
                    for i in range(0, len(order_ids), 100):
                        chunk = order_ids[i:i + 100]
                        try:
                            statuses = wb_api.get_orders_statuses(chunk)
                            for s in statuses:
                                wb_id = str(s.get('orderId'))
                                wb_stat = s.get('status')
                                new_stat = self._map_wb_status(wb_stat)

                                logging.info(f"WB заказ {wb_id}: статус API '{wb_stat}' -> '{new_stat}'")

                                if new_stat:
                                    mask = group["Номер отправления"].astype(str) == wb_id
                                    for _, row in group[mask].iterrows():
                                        if row['Статус'] != new_stat:
                                            self.db.update_kiz_status(row['Код маркировки'], new_stat)
                                            updated_count += 1
                        except Exception as e:
                            logging.error(f"Ошибка запроса WB chunk: {e}")

                        processed_count += len(chunk)
                        self._update_sync_ui(f"WB: {processed_count}/{total_items}", processed_count / total_items)

            logging.info(f"Синхронизация завершена. Обновлено записей: {updated_count}")
            self._update_sync_ui(f"✅ Обновлено: {updated_count}", 1.0)
            messagebox.showinfo("Готово", f"Обновлено статусов: {updated_count}")

        except Exception as e:
            logging.error(f"Критическая ошибка синхронизации: {e}", exc_info=True)
            self._update_sync_ui("❌ Ошибка", 0)
        finally:
            self.after(0, lambda: self.sync_btn.configure(state="normal"))

    def _update_sync_ui(self, text_val, progress_val):
        """Безопасное обновление UI из потока"""
        self.after(0, lambda: self.sync_label.configure(text=text_val))
        self.after(0, lambda: self.sync_progress.set(progress_val))

    def _map_wb_status(self, wb_status):
        mapped = {
            'delivered': 'Выкуплен', 'receive': 'Выкуплен', 'sold': 'Выкуплен',
            'cancel': 'Возврат', 'reject': 'Возврат'
        }
        res = mapped.get(wb_status)
        if wb_status and not res:
            logging.debug(f"Статус WB '{wb_status}' пропущен (не финальный)")
        return res

    def _map_ozon_status(self, ozon_status):
        if ozon_status in ['delivered', 'client_received']:
            return 'Выкуплен'
        if ozon_status in ['cancelled', 'not_accepted', 'returned_to_seller']:
            return 'Возврат'

        if ozon_status:
            logging.debug(f"Статус Ozon '{ozon_status}' пропущен (не финальный)")
        return None

    def export_for_znak(self):
        """
        Экспорт выкупленных КИЗ для Честного Знака.
        Выгружает только коды со статусом 'Выкуплен' в формате CSV.
        """
        # 1. Сначала спрашиваем пользователя, куда сохранить файл
        # Это делаем в основном потоке, так как GUI диалоги требуют этого
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"export_cz_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            title="Сохранить коды для Честного Знака"
        )

        if not file_path:
            return

        def run_export():
            try:
                # Начало процесса
                self.after(0, lambda: self.export_cz_btn.configure(state="disabled"))
                self.after(0, lambda: self.export_progress.set(0.1))
                self.after(0, lambda: self.sync_label.configure(text="⏳ Подготовка данных..."))

                # 2. Получаем данные из БД
                with self.db.engine.connect() as conn:
                    # Выбираем только саму колонку с кодом
                    query = text('SELECT "Код маркировки" FROM marking_codes WHERE "Статус" = "Выкуплен"')
                    df = pd.read_sql(query, conn)

                self.after(0, lambda: self.export_progress.set(0.5))

                if df.empty:
                    self.after(0, lambda: messagebox.showinfo("Инфо",
                                                              "В базе нет КИЗ со статусом 'Выкуплен' для экспорта."))
                    return

                # 3. Сохранение в файл
                # Для Честного Знака обычно нужен простой список кодов.
                # Сохраняем без заголовков и индексов.
                df.to_csv(file_path, index=False, header=False, encoding='utf-8-sig')

                self.after(0, lambda: self.export_progress.set(1.0))
                self.after(0, lambda: self.sync_label.configure(text="✅ Экспорт завершен"))

                # Показываем результат
                count = len(df)
                self.after(0, lambda: messagebox.showinfo("Успех",
                                                          f"Экспорт успешно завершен!\n\nКоличество кодов: {count}\nФайл: {os.path.basename(file_path)}"))

            except Exception as e:
                logging.error(f"Ошибка при экспорте для ЧЗ: {e}", exc_info=True)
                self.after(0, lambda: messagebox.showerror("Ошибка", f"Не удалось выполнить экспорт:\n{e}"))
            finally:
                # Возвращаем UI в исходное состояние
                self.after(3000, lambda: self.export_progress.set(0))
                self.after(3000, lambda: self.sync_label.configure(text="Статус: готов к работе"))
                self.after(0, lambda: self.export_cz_btn.configure(state="normal"))

        # Запускаем в отдельном потоке, чтобы прогрессбар плавно работал
        threading.Thread(target=run_export, daemon=True).start()