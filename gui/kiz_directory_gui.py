import customtkinter as ctk
import pandas as pd
from tkinter import messagebox
from gui.gui_table2 import EditableDataTable
from sqlalchemy import text
import logging
# Создаем логгер для конкретного модуля
logger = logging.getLogger(__name__)

class KizDirectoryMode(ctk.CTkFrame):
    def __init__(self, parent, font, db_manager):
        super().__init__(parent)
        self.db = db_manager
        self.font = font

        # Конфигурация колонок для КИЗ
        self.column_configs = {
            "Код маркировки": 300,
            "Номер отправления": 160,
            "Цена": 80,
            "sku": 120,
            "Артикул поставщика": 150,
            "Размер": 70,
            "Время добавления": 150,
            "Статус": 120,
            "Маркетплейс": 100,
            "Дата обновления": 150,
            "Дата продажи": 120
        }

        self.df_full = pd.DataFrame()
        self.df_filtered = pd.DataFrame()

        # Заголовок
        self.title_label = ctk.CTkLabel(
            self,
            text="📋 Справочник КИЗ (Коды маркировки)",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.title_label.pack(pady=(10, 20), padx=20, anchor="w")

        # --- ПАНЕЛЬ УПРАВЛЕНИЯ (как в db_viewer) ---
        self.controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.controls_frame.pack(fill="x", padx=20, pady=5)

        # 1. Поиск
        self.search_entry = ctk.CTkEntry(
            self.controls_frame,
            placeholder_text="Поиск по КИЗ или номеру заказа...",
            width=350
        )
        self.search_entry.pack(side="left", padx=(0, 10))
        self.search_entry.bind("<KeyRelease>", lambda e: self.apply_filters())

        # 2. Фильтр по статусу
        self.status_filter = ctk.CTkOptionMenu(
            self.controls_frame,
            values=["Все статусы", "Отгружен", "Выкуплен", "Возврат"],
            command=lambda v: self.apply_filters()
        )
        self.status_filter.pack(side="left", padx=10)

        # 3. Кнопки управления
        self.refresh_btn = ctk.CTkButton(
            self.controls_frame,
            text="🔄 Обновить",
            width=100,
            command=self.load_data
        )
        self.refresh_btn.pack(side="right", padx=5)

        # ДОБАВЛЯЕМ КНОПКУ СОХРАНЕНИЯ
        self.save_btn = ctk.CTkButton(
            self.controls_frame,
            text="💾 Сохранить",
            fg_color="#27ae60",
            hover_color="#219150",
            width=100,
            command=self.save_changes
        )
        self.save_btn.pack(side="right", padx=5)
        self.delete_btn = ctk.CTkButton(
            self.controls_frame,
            text="🗑️ Удалить",
            fg_color="#c0392b",
            hover_color="#a93226",
            width=100,
            command=self.delete_selected
        )
        self.delete_btn.pack(side="right", padx=5)

        # --- КОНТЕЙНЕР ТАБЛИЦЫ ---
        self.table_frame = ctk.CTkFrame(self)
        self.table_frame.pack(fill="both", expand=True, padx=20, pady=10)

        self.load_data()

    def load_data(self):
        try:
            with self.db.engine.connect() as conn:
                # 1. Загружаем чистый DataFrame из БД без приведения к astype(str)
                query = text('SELECT * FROM marking_codes ORDER BY "Время добавления" DESC')
                df = pd.read_sql(query, conn)

            logger.info(f"Справочник КИЗ: Загружено {len(df)} записей.")

            # 2. Обрабатываем даты, пока они еще не стали обычными строками
            for col in ["Время добавления", "Дата обновления"]:
                if col in df.columns:
                    # format='mixed' позволяет читать даты как с микросекундами, так и без
                    # errors='coerce' превратит битые данные в пустоту (NaT) вместо вылета ошибки
                    df[col] = pd.to_datetime(df[col], errors='coerce', format='mixed')

                    # Сразу форматируем в красивую строку
                    # .dt.strftime работает только с объектами datetime
                    df[col] = df[col].dt.strftime('%d.%m.%Y %H:%M')

            # 3. Теперь, когда даты отформатированы, приводим ВСЕ остальное к строкам
            # Добавляем 'NaT' в список замены, так как пустые даты превращаются в этот символ
            self.df_full = df.fillna('').astype(str).replace(['None', 'nan', 'NaT'], '')

            self.apply_filters()
        except Exception as e:
            # Добавил exc_info=True, чтобы в логах была видна точная строка ошибки
            logger.error(f"Ошибка загрузки КИЗ: {e}", exc_info=True)
            self.render_table(pd.DataFrame())

    def load_data_old(self):
        try:
            with self.db.engine.connect() as conn:
                # Сортируем по времени добавления (новые сверху)
                query = text('SELECT * FROM marking_codes ORDER BY "Время добавления" DESC')
                self.df_full = pd.read_sql(query, conn).fillna('').astype(str).replace(['None', 'nan'], '')

            logger.info(f"Справочник КИЗ: Загружено {len(self.df_full)} записей.")

            # Приведение дат к красивому виду (если они не пустые)
            for col in ["Время добавления", "Дата обновления"]:
                if col in self.df_full.columns:
                    self.df_full[col] = pd.to_datetime(self.df_full[col]).dt.strftime('%d.%m.%Y %H:%M')

            self.apply_filters()
        except Exception as e:
            logger.error(f"Ошибка загрузки КИЗ: {e}")
            self.render_table(pd.DataFrame())

    def _setup_table_events(self):
        """Явное назначение событий для Treeview с защитой от потери фокуса"""
        if hasattr(self, 'table') and hasattr(self.table, 'tree'):
            # Снимаем все старые привязки, если они были
            self.table.tree.unbind("<Double-1>")

            # Назначаем заново самый стабильный вариант события
            # Мы вызываем метод напрямую из экземпляра класса таблицы
            self.table.tree.bind("<Double-1>", lambda event: self.table._on_double_click(event))

            # Дополнительно: разрешаем выбор строки
            self.table.tree.configure(selectmode="browse")

            logger.info("События двойного клика для КИЗ принудительно переназначены.")

    def render_table(self, df):
        """Отрисовка таблицы с принудительной активацией редактирования"""
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        if df is None or df.empty:
            ctk.CTkLabel(self.table_frame, text="Записи не найдены", font=self.font).pack(expand=True)
            return

        # Создаем экземпляр таблицы
        self.table = EditableDataTable(
            self.table_frame,
            dataframe=df,
            columns=df.columns.tolist(),
            on_row_select=None,
            header_font=("Segoe UI", 13, "bold"),
            cell_font=("Segoe UI", 12),
            rows_per_page=50
        )
        self.table.pack(fill="both", expand=True)

        # ПРИНУДИТЕЛЬНЫЙ ХАК:
        # 1. Даем Treeview фокус при клике
        self.table.tree.bind("<Button-1>", lambda e: self.table.tree.focus_set(), add="+")

        # 2. Назначаем двойной клик с задержкой, чтобы объект успел "проснуться"
        def bind_now():
            # Очищаем старые бинды
            self.table.tree.unbind("<Double-1>")
            # Вешаем новый напрямую на метод объекта
            self.table.tree.bind("<Double-1>", self.table._on_double_click, add="+")
            # logger.info("Бинд Double-Click применен принудительно")

        self.after(200, bind_now)

        # 3. Ширины колонок
        self.after(10, self._apply_column_widths)

    def _apply_column_widths(self):
        """Установка ширин для всех колонок, включая новые"""
        if hasattr(self, 'table'):
            for col in self.df_filtered.columns:
                # Если ширина задана в конфиге - берем её, если нет - ставим 150 по умолчанию
                width = self.column_configs.get(col, 150)
                try:
                    self.table.tree.column(col, width=width, stretch=False)
                except:
                    continue

    def save_changes(self):
        """Сохранение изменений согласно точной схеме таблицы marking_codes"""
        try:
            # Получаем актуальный DataFrame из таблицы (в gui_table2 это атрибут .df)
            current_df = self.table.df

            if current_df is None or current_df.empty:
                messagebox.showwarning("Внимание", "Нет данных для сохранения")
                return

            # Используем транзакцию для безопасности
            with self.db.engine.begin() as conn:
                for _, row in current_df.iterrows():
                    # Собираем параметры строго по твоей схеме
                    # .get(column, "") защищает от ошибок, если вдруг колонка не загрузилась
                    params = {
                        "order_id": str(row.get("Номер отправления", "")),
                        "price": str(row.get("Цена", "")),
                        "sku": str(row.get("sku", "")),
                        "vendor_code": str(row.get("Артикул поставщика", "")),
                        "size": str(row.get("Размер", "")),
                        "status": str(row.get("Статус", "Отгружен")),
                        "mp": str(row.get("Маркетплейс", "")),
                        "sell_date": str(row.get("Дата продажи", "")),
                        "kiz_code": row["Код маркировки"]  # PRIMARY KEY
                    }

                    # SQL запрос по твоим полям
                    query = text('''
                        UPDATE marking_codes 
                        SET "Номер отправления" = :order_id,
                            "Цена" = :price,
                            "sku" = :sku,
                            "Артикул поставщика" = :vendor_code,
                            "Размер" = :size,
                            "Статус" = :status,
                            "Маркетплейс" = :mp,
                            "Дата продажи" = :sell_date,
                            "Дата обновления" = datetime('now', 'localtime')
                        WHERE "Код маркировки" = :kiz_code
                    ''')

                    conn.execute(query, params)

            logger.info("Справочник КИЗ: Изменения в БД успешно сохранены.")
            messagebox.showinfo("Успех", "Данные успешно обновлены в базе!")
            self.load_data()  # Перезагружаем, чтобы обновить "Дата обновления" на экране

        except Exception as e:
            logger.error(f"Ошибка при сохранении КИЗ: {e}", exc_info=True)
            messagebox.showerror("Ошибка сохранения", f"Не удалось сохранить изменения:\n{e}")

    def apply_filters(self):
        """Фильтрация данных (Поиск + Статус)"""
        if self.df_full.empty:
            self.render_table(pd.DataFrame())
            return

        search_text = self.search_entry.get().lower()
        status_val = self.status_filter.get()

        df = self.df_full.copy()

        # Фильтр по статусу
        if status_val != "Все статусы":
            df = df[df["Статус"] == status_val]

        # Поиск
        if search_text:
            df = df[
                df["Код маркировки"].astype(str).str.lower().contains(search_text, na=False) |
                df["Номер отправления"].astype(str).str.lower().contains(search_text, na=False)
                ]

        self.df_filtered = df
        self.render_table(df)

    def delete_selected(self):
        """Удаление выбранного КИЗ из БД"""
        selected = self.table.tree.selection()
        if not selected:
            messagebox.showwarning("Внимание", "Выберите запись для удаления")
            return

        if not messagebox.askyesno("Подтверждение", "Вы уверены, что хотите удалить выбранные записи?"):
            return

        try:
            for item in selected:
                values = self.table.tree.item(item, "values")
                kiz_code = values[0]  # Код маркировки - первая колонка

                with self.db.engine.begin() as conn:
                    conn.execute(
                        text('DELETE FROM marking_codes WHERE "Код маркировки" = :code'),
                        {"code": kiz_code}
                    )

            logger.info(f"Удалено {len(selected)} записей из КИЗ")
            self.load_data()
            messagebox.showinfo("Успех", "Записи удалены")
        except Exception as e:
            logger.error(f"Ошибка удаления КИЗ: {e}")
            messagebox.showerror("Ошибка", f"Не удалось удалить:\n{e}")