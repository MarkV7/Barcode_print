import customtkinter as ctk
import pandas as pd
from tkinter import messagebox
from gui.gui_table2 import EditableDataTable
from sqlalchemy import text
import logging

# Создаем логгер для конкретного модуля
logger = logging.getLogger(__name__)

class DBViewerMode(ctk.CTkFrame):
    def __init__(self, parent, font, db_manager):
        super().__init__(parent)
        self.db = db_manager
        self.font = font
        # Сохраняем ширины здесь, чтобы они жили вместе с объектом фрейма
        self.column_configs = {
            "Артикул производителя": 180,
            "Бренд": 120,
            "Наименование поставщика": 250,
            "Штрихкод производителя": 160,
            "Размер": 70
        }
        # Инициализируем пустыми DataFrame, чтобы не было ошибки NoneType
        self.df_full = pd.DataFrame()
        self.df_filtered = pd.DataFrame()

        self.title_label = ctk.CTkLabel(
            self,
            text="Справочник ТОВАРОВ",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.title_label.pack(pady=(10, 20), padx=20, anchor="w")

        # --- ПАНЕЛЬ УПРАВЛЕНИЯ ---
        self.controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.controls_frame.pack(fill="x", padx=20, pady=5)

        # Поиск
        self.search_entry = ctk.CTkEntry(
            self.controls_frame, placeholder_text="Поиск по всей базе...", width=300
        )
        self.search_entry.pack(side="left", padx=(0, 10))
        self.search_entry.bind("<Return>", lambda e: self.apply_search())

        self.btn_search = ctk.CTkButton(
            self.controls_frame, text="Найти", command=self.apply_search, width=80
        )
        self.btn_search.pack(side="left", padx=5)

        self.btn_clear = ctk.CTkButton(
            self.controls_frame, text="Сброс", command=self.reset_search, width=80, fg_color="gray"
        )
        self.btn_clear.pack(side="left", padx=5)
        # Добавим кнопку обновления в панель управления
        self.btn_refresh = ctk.CTkButton(
            self.controls_frame,
            text="🔄 Обновить",
            command=self.load_data_from_db,
            width=100 #,
            # fg_color="#27ae60"
        )
        self.btn_refresh.pack(side="left", padx=5)

        # ДОБАВЛЯЕМ КНОПКУ СОХРАНИТЬ
        self.save_btn = ctk.CTkButton(
            self.controls_frame,
            text="💾 Сохранить",
            fg_color="#27ae60",
            # hover_color="#219150",
            width=100,
            command=self.save_changes
        )
        self.save_btn.pack(side="left", padx=5)

        # Кнопка удаления (Красная)
        self.btn_delete = ctk.CTkButton(
            self.controls_frame, text="Удалить строку", command=self.delete_selected_row,
            width=120, fg_color="#c0392b", hover_color="#a93226"
        )
        self.btn_delete.pack(side="left", padx=(150, 20))

        # Инфо-лейблы
        self.rows_label = ctk.CTkLabel(self.controls_frame, text="🔢 Строк: 0")
        self.rows_label.pack(side="right", padx=10)

        # Подсказка о поиске (скрыта по умолчанию)
        self.search_status_label = ctk.CTkLabel(self, text="",
                                                text_color="#2C3E50", # Темный сине-серый цвет
                                                font=("Segoe UI", 12, "italic"))
        self.search_status_label.pack(pady=0, padx=20, anchor="w")

        self.table_frame = ctk.CTkFrame(self)
        self.table_frame.pack(fill="both", expand=True, padx=20, pady=(5, 10))

        self.load_data_from_db()

    def load_data_from_db_old(self):
        try:
            data = self.db.get_all_product_barcodes()
            # Проверка: если пришло None, делаем пустой DF
            self.df_full = data if data is not None else pd.DataFrame()
            # ЗАМЕНЯЕМ None и NaN на пустые строки для красоты
            self.df_filtered = self.df_full.fillna('').copy()

            # ВАЖНО: Вызываем отрисовку
            self.display_table()
        except Exception as e:
            messagebox.showerror("Ошибка БД", f"Не удалось загрузить данные:\n{str(e)}")

    def load_data_from_db(self):
        try:
            data = self.db.get_all_product_barcodes()

            if data is None or data.empty:
                self.df_full = pd.DataFrame()
                self.df_filtered = pd.DataFrame()
            else:
                # 1. Сначала заполняем NaN пустыми строками
                df = data.fillna('')

                # 2. ХАК: Принудительно заменяем строковые "None" и "nan",
                # которые могли появиться при конвертации типов
                df = df.astype(str).replace(['None', 'nan', 'NaN', '<NA>'], '')

                self.df_full = df
                self.df_filtered = self.df_full.copy()

            # Вызываем отрисовку
            self.display_table()

        except Exception as e:
            messagebox.showerror("Ошибка БД", f"Не удалось загрузить данные:\n{str(e)}")

    def apply_search(self):
        query = self.search_entry.get().strip().lower()
        if self.df_full.empty: return

        # 1. ВКЛЮЧАЕМ ИНДИКАЦИЮ
        self.search_status_label.configure(text="⌛ Идет поиск в 50к+ строк, подождите...")
        self.winfo_toplevel().configure(cursor="watch")  # Курсор ожидания
        self.update_idletasks()  # Принудительно обновляем UI, чтобы текст появился сразу

        if not query:
            self.reset_search()
        else:
            # Сам процесс фильтрации
            mask = self.df_full.apply(lambda row: row.astype(str).str.contains(query, case=False).any(), axis=1)
            self.df_filtered = self.df_full[mask]
            self.display_table()

        # 2. ВЫКЛЮЧАЕМ ИНДИКАЦИЮ
        self.search_status_label.configure(text="")
        self.winfo_toplevel().configure(cursor="")

    def delete_selected_row(self):
        """Логика удаления выбранной в таблице строки"""
        if not hasattr(self, 'table'): return

        selected_items = self.table.tree.selection()
        if not selected_items:
            messagebox.showwarning("Внимание", "Сначала выберите строку в таблице!")
            return

        # Получаем IID (который у нас равен индексу в DataFrame)
        row_id = selected_items[0]
        # Извлекаем данные строки
        row_data = self.df_full.loc[int(row_id)]
        vendor_code = row_data["Артикул производителя"]
        size = row_data["Размер"]

        # Подтверждение
        confirm = messagebox.askyesno(
            "Подтверждение",
            f"Вы уверены, что хотите удалить запись:\n\nАртикул: {vendor_code}\nРазмер: {size}?"
        )

        if confirm:
            if self.db.delete_product_barcode(vendor_code, size):
                # Удаляем из локальных данных, чтобы не перекачивать всю БД заново
                self.df_full = self.df_full.drop(index=int(row_id))
                # Если мы были в режиме поиска, удаляем и оттуда
                if int(row_id) in self.df_filtered.index:
                    self.df_filtered = self.df_filtered.drop(index=int(row_id))

                self.display_table()
                messagebox.showinfo("Готово", "Запись успешно удалена из базы.")
            else:
                messagebox.showerror("Ошибка", "Не удалось удалить запись из БД.")

    def reset_search(self):
        """Сброс фильтра"""
        self.search_entry.delete(0, 'end')
        self.df_filtered = self.df_full.copy()
        self.display_table()

    def display_table(self):
        """Отрисовка таблицы"""
        for widget in self.table_frame.winfo_children():
            widget.destroy()

        # Обновляем счетчик строк (теперь используем df_filtered)
        count = len(self.df_filtered)
        self.rows_label.configure(text=f"🔢 Найдено: {count}")

        if self.df_filtered.empty:
            ctk.CTkLabel(self.table_frame, text="Нет данных для отображения").pack(expand=True)
            return

        # Используем ваш новый модуль gui_table2
        self.table = EditableDataTable(
            self.table_frame,
            dataframe=self.df_filtered,
            columns=self.df_filtered.columns.tolist(),
            rows_per_page=100,
            header_font=("Segoe UI", 13, "bold"),
            cell_font=("Segoe UI", 12)
        )
        self.table.set_column_widths(self.column_configs)
        self.table.pack(fill="both", expand=True)

        # Принудительно включаем редактирование по двойному клику
        self.table.tree.bind("<Double-1>", lambda e: self.table._on_double_click(e), add="+")

        # И не забудьте про фокус, чтобы таблица сразу слушала клавиатуру
        self.table.tree.bind("<Button-1>", lambda e: self.table.tree.focus_set(), add="+")



    def save_changes(self):
        """Сохранение отредактированных данных в таблицу product_barcodes"""
        try:
            # Получаем текущие данные из таблицы (атрибут .df в EditableDataTable)
            current_df = self.table.df

            if current_df is None or current_df.empty:
                return

            with self.db.engine.begin() as conn:
                for _, row in current_df.iterrows():
                    # Формируем параметры для SQL
                    # Используем .get() для безопасности, если колонки будут переименованы
                    params = {
                        "brand": str(row.get("Бренд", "")),
                        "supplier_name": str(row.get("Наименование поставщика", "")),
                        "vendor_barcode": str(row.get("Штрихкод производителя", "")),
                        "ozon_art": str(row.get("Артикул Ozon", "")),
                        "wb_art": str(row.get("Артикул Вайлдбериз", "")),
                        "ozon_barcode": str(row.get("Штрихкод OZON", "")),
                        "wb_barcode": str(row.get("Баркод  Wildberries", "")),
                        "box": str(row.get("Коробка", "")),
                        "sku_ozon": str(row.get("SKU OZON", "")),
                        # Ключи для WHERE
                        "main_art": row["Артикул производителя"],
                        "size": row["Размер"]
                    }

                    query = text('''
                        UPDATE product_barcodes 
                        SET "Бренд" = :brand,
                            "Наименование поставщика" = :supplier_name,
                            "Штрихкод производителя" = :vendor_barcode,
                            "Артикул Ozon" = :ozon_art,
                            "Артикул Вайлдбериз" = :wb_art,
                            "Штрихкод OZON" = :ozon_barcode,
                            "Баркод  Wildberries" = :wb_barcode,
                            "Коробка" = :box,
                            "SKU OZON" = :sku_ozon
                        WHERE "Артикул производителя" = :main_art 
                          AND "Размер" = :size
                    ''')

                    conn.execute(query, params)

            import logging
            logger.info("База SQL: Изменения в product_barcodes успешно сохранены.")
            messagebox.showinfo("Успех", "Данные товаров успешно обновлены!")
            self.load_data_from_db()  # Перезагрузка для чистоты данных

        except Exception as e:
            import logging
            logger.error(f"Ошибка сохранения БД товаров: {e}", exc_info=True)
            messagebox.showerror("Ошибка", f"Не удалось сохранить изменения:\n{e}")