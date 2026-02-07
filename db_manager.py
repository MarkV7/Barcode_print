import pandas as pd
from sqlalchemy import create_engine, text
import logging
import os
from typing import Dict, List, Optional

class DBManager:
    def __init__(self, db_name="barcode_print.db"):
        # База данных будет создана в корневой папке проекта как файл
        self.engine = create_engine(f'sqlite:///{db_name}')
        self.init_tables()

    def init_tables(self):
        """Создание таблиц, если они не существуют"""
        commands = [
            """
            CREATE TABLE IF NOT EXISTS product_barcodes (
                "Артикул производителя" TEXT,
                "Размер" TEXT,
                "Бренд" TEXT,
                "Наименование поставщика" TEXT,
                "Штрихкод производителя" TEXT,
                "Артикул Ozon" TEXT,
                "Артикул Вайлдбериз" TEXT,
                "Штрихкод OZON" TEXT,
                "Баркод  Wildberries" TEXT,
                "Коробка" TEXT,
                "SKU OZON" TEXT,
                PRIMARY KEY ("Артикул производителя", "Размер")
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS marking_codes (
                "Номер отправления" TEXT,
                "Код маркировки" TEXT PRIMARY KEY,
                "Цена" TEXT,
                "sku" TEXT,
                "Артикул поставщика" TEXT,
                "Размер" TEXT,
                "Время добавления" TIMESTAMP DEFAULT (datetime('now', 'localtime'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ozon_fbs_orders (
                "Номер отправления" TEXT PRIMARY KEY,
                "Номер заказа" TEXT,
                "Служба доставки" TEXT,
                "Бренд" TEXT,
                "Цена" NUMERIC,
                "Артикул поставщика" TEXT,
                "Количество" NUMERIC,
                "Размер" TEXT,
                "Наименование" TEXT,
                "Штрихкод" TEXT,
                "Штрихкод Ozon" TEXT,
                "Код маркировки" TEXT
                "sku" TEXT,
                "product_id" TEXT,
                "Статус заказа" TEXT,
                "Подстатус" TEXT,
                "is_express" BOOLEAN,
                "Статус обработки" TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS wb_fbs_orders (
                "Номер заказа" TEXT PRIMARY KEY,
                "Служба доставки" TEXT, 
                "Покупатель" TEXT, 
                "Бренд" TEXT, 
                "Цена" TEXT,
                "Артикул поставщика" TEXT, 
                "Количество" TEXT, 
                "Размер" TEXT,
                "Штрихкод" TEXT,
                "Штрихкод WB" TEXT, 
                "Код маркировки" TEXT, 
                "Номер поставки" TEXT, 
                "Статус заказа" TEXT, 
                "Статус обработки" TEXT
            )
            """
        ]
        try:
            with self.engine.begin() as conn:
                for cmd in commands:
                    conn.execute(text(cmd))
            logging.info("DB: Таблицы SQLite инициализированы.")
        except Exception as e:
            logging.error(f"DB: Ошибка инициализации таблиц: {e}")

    def sync_dataframe(self, df: pd.DataFrame, table_name: str, primary_keys: list):
        """
        Универсальная синхронизация для SQLite.
        Используем INSERT OR REPLACE для совместимости со старыми версиями.
        """
        if df is None or df.empty:
            return

        # Имя временной таблицы
        staging_table = f"temp_{table_name}"

        try:
            with self.engine.begin() as conn:
                # 1. Загружаем данные во временную таблицу (она живет только в рамках транзакции)
                # Здесь используем replace, так как temp_table всегда должна быть свежей
                df.to_sql(staging_table, conn, if_exists='replace', index=False)

                # 2. Формируем список колонок
                columns = [f'"{c}"' for c in df.columns]
                col_str = ", ".join(columns)

                # 3. SQL INSERT OR REPLACE
                # Эта конструкция заменяет строку целиком, если PK совпал.
                # Идеально подходит для синхронизации полных строк.
                sql = f"""
                        INSERT OR REPLACE INTO "{table_name}" ({col_str})
                        SELECT {col_str} FROM "{staging_table}";
                        """

                conn.execute(text(sql))

                # 4. Удаляем временную таблицу
                conn.execute(text(f'DROP TABLE IF EXISTS "{staging_table}"'))

            logging.info(f"DB: Таблица {table_name} синхронизирована (UPSERT).")

        except Exception as e:
            logging.error(f"DB: Ошибка UPSERT для {table_name}: {e}")

    def upsert_ozon_orders(self, df: pd.DataFrame):
        """Специфический метод для Ozon: вставка или обновление существующих заказов"""
        if df is None or df.empty: return
        try:
            # На 1 этапе используем простую перезапись таблицы заказов,
            # так как fbs_df всегда содержит актуальное состояние.
            self.sync_dataframe(df, "ozon_fbs_orders", ["Номер отправления"])
            logging.info(f"DB: Таблица ozon_fbs_orders успешно перезаписана ({len(df)} строк).")
        except Exception as e:
            logging.error(f"DB: Ошибка перезаписи ozon_fbs_orders: {e}")

    def upsert_wb_orders(self, df: pd.DataFrame):
        """Специфический метод для WB: вставка или обновление существующих заказов"""
        if df is None or df.empty: return
        try:
            # На 1 этапе используем простую перезапись таблицы заказов,
            # так как fbs_df всегда содержит актуальное состояние.
            self.sync_dataframe(df, "wb_fbs_orders",["Номер заказа"])
            logging.info(f"DB: Таблица wb_fbs_orders успешно перезаписана ({len(df)} строк).")
        except Exception as e:
            logging.error(f"DB: Ошибка перезаписи wb_fbs_orders: {e}")

    def add_marking_code(self, posting_number, cis_code, price, sku, article, size):
        """Мгновенная вставка или обновление одной маркировки"""
        sql = """
            INSERT OR REPLACE INTO marking_codes 
            ("Номер отправления", "Код маркировки", "Цена", "sku", "Артикул поставщика", "Размер")
            VALUES (?, ?, ?, ?, ?, ?);
        """
        try:
            with self.engine.begin() as conn:
                conn.execute(text(sql), (posting_number, cis_code, price, sku, article, size))
        except Exception as e:
            logging.error(f"DB Error (add_marking): {e}")

    def delete_marking_code(self, cis_code):
        """Удаление маркировки из базы"""
        sql = 'DELETE FROM marking_codes WHERE "Код маркировки" = :cis;'
        try:
            with self.engine.begin() as conn:
                conn.execute(text(sql), {"cis": cis_code})
        except Exception as e:
            logging.error(f"DB Error (delete_marking): {e}")

    def delete_marking_codes_by_posting(self, posting_number):
        """Удаление всех кодов маркировки для конкретного отправления"""
        sql = 'DELETE FROM marking_codes WHERE "Номер отправления" = :posting;'
        try:
            with self.engine.begin() as conn:
                conn.execute(text(sql), {"posting": posting_number})
            logging.info(f"DB: Удалены КМ для отправления {posting_number}")
        except Exception as e:
            logging.error(f"DB Error (delete_marking_by_posting): {e}")

    # Добавить в db_manager.py

    def update_barcode_record(self, data_dict):
        """
        Обновление или вставка одной записи штрихкода.
        data_dict должен содержать ключи, совпадающие с названиями колонок.
        """
        columns = ", ".join([f'"{k}"' for k in data_dict.keys()])
        placeholders = ", ".join([":" + k for k in data_dict.keys()])

        sql = f'INSERT OR REPLACE INTO product_barcodes ({columns}) VALUES ({placeholders});'

        try:
            with self.engine.begin() as conn:
                conn.execute(text(sql), data_dict)
        except Exception as e:
            logging.error(f"DB Error (update_barcode_record): {e}")


    def get_product_by_article_and_size(self, article: str, size: str) -> Optional[dict]:
        """
        Быстрый поиск товара по артикулу и размеру.
        Возвращает словарь с данными товара или None.
        """
        sql = """
            SELECT * FROM product_barcodes 
            WHERE "Артикул производителя" = :article 
            AND "Размер" = :size
            LIMIT 1;
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql), {"article": str(article), "size": str(size)})
                row = result.fetchone()
                if row:
                    # Превращаем результат в обычный словарь {колонка: значение}
                    return dict(row._mapping)
                return None
        except Exception as e:
            logging.error(f"DB Error (get_product): {e}")
            return None

    def update_fbs_order_status(self, table_name: str, key_col: str, key_value: str, status_processing: str,
                                marking_code: str = ""):
        """Обновление статуса обработки и кода маркировки в таблицах заказов"""
        sql = text(f"""
            UPDATE {table_name}
            SET "Статус обработки" = :status,
                "Код маркировки" = :marking,
                "Время обновления" = CURRENT_TIMESTAMP
            WHERE "{key_col}" = :id
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(sql, {
                    "status": status_processing,
                    "marking": marking_code,
                    "id": key_value
                })
        except Exception as e:
            logging.error(f"Ошибка обновления строки в {table_name}: {e}")

    def get_products_by_articles(self, articles: list, columns: list = None) -> pd.DataFrame:
        """
        Выбирает данные из БД только для указанных артикулов и только нужные колонки.
        """
        if not articles:
            return pd.DataFrame()

        # 1. Формируем список колонок
        cols_str = ", ".join([f'"{col}"' for col in columns]) if columns else "*"

        # 2. Создаем словарь параметров: {"a0": "арт1", "a1": "арт2", ...}
        # Это удовлетворяет требованию PyCharm к типу Mapping
        params = {f"a{i}": str(art) for i, art in enumerate(articles)}

        # 3. Формируем плейсхолдеры для SQL: (:a0, :a1, :a2...)
        placeholders = ", ".join([f":a{i}" for i in range(len(articles))])
        sql = f'SELECT {cols_str} FROM product_barcodes WHERE "Артикул производителя" IN ({placeholders})'

        try:
            return pd.read_sql_query(text(sql), self.engine, params=params)
        except Exception as e:
            logging.error(f"Ошибка при получении данных из БД: {e}")
            return pd.DataFrame()

    def get_products_by_skus(self, skus: list) -> pd.DataFrame:
        """
        Получает данные по списку SKU.
        Если список пуст или ничего не найдено, возвращает пустой DF со всеми колонками таблицы.
        """
        # Сначала получаем структуру таблицы (пустой DF с колонками)
        empty_df = pd.read_sql_query('SELECT * FROM product_barcodes LIMIT 0', self.engine)

        if not skus:
            return empty_df

        # Защита: превращаем всё в строки и убираем None
        skus = [str(s) for s in skus if s is not None]

        # Используем именованные параметры для безопасности
        params = {f"s{i}": s for i, s in enumerate(skus)}
        placeholders = ", ".join([f":s{i}" for i in range(len(skus))])

        sql = f'SELECT * FROM product_barcodes WHERE "SKU OZON" IN ({placeholders})'

        try:
            with self.engine.connect() as conn:
                res = pd.read_sql_query(text(sql), conn, params=params)
                # Если результат пустой, возвращаем структуру с колонками
                return res if not res.empty else empty_df
        except Exception as e:
            logging.error(f"Ошибка получения по SKU: {e}")
            return empty_df

    def get_products_by_wb_barcodes(self, barcodes: list) -> pd.DataFrame:
        """
        Получает данные по списку Баркодов WB.
        Возвращает пустую структуру таблицы, если ничего не найдено.
        """
        # Получаем структуру (колонки), чтобы не было KeyError в GUI
        empty_df = pd.read_sql_query('SELECT * FROM product_barcodes LIMIT 0', self.engine)

        if not barcodes:
            return empty_df

        # Чистим список
        barcodes = [str(b) for b in barcodes if b]

        # ВАЖНО: В твоем SQL-скрипте было "Баркод  Wildberries" (с двумя пробелами)
        params = {f"b{i}": b for i, b in enumerate(barcodes)}
        placeholders = ", ".join([f":b{i}" for i in range(len(barcodes))])

        sql = f'SELECT * FROM product_barcodes WHERE "Баркод  Wildberries" IN ({placeholders})'

        try:
            with self.engine.connect() as conn:
                res = pd.read_sql_query(text(sql), conn, params=params)
                return res if not res.empty else empty_df
        except Exception as e:
            logging.error(f"Ошибка DB WB: {e}")
            return empty_df

    # Добавить в db_manager.py

    def get_marking_codes_by_date_range(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Получает коды маркировки за указанный период (гггг-мм-дд)."""
        sql = """
            SELECT * FROM marking_codes 
            WHERE date("Время добавления") BETWEEN :start AND :end
        """
        try:
            with self.engine.connect() as conn:
                return pd.read_sql_query(text(sql), conn, params={"start": start_date, "end": end_date})
        except Exception as e:
            logging.error(f"Ошибка экспорта маркировки: {e}")
            return pd.DataFrame()

    def get_all_product_barcodes(self) -> pd.DataFrame:
        """Получает всю таблицу штрихкодов."""
        try:
            return pd.read_sql_query('SELECT * FROM product_barcodes', self.engine)
        except Exception as e:
            logging.error(f"Ошибка экспорта штрихкодов: {e}")
            return pd.DataFrame()

    def import_product_barcodes(self, df: pd.DataFrame):
        """Массово обновляет или вставляет штрихкоды из DataFrame."""
        try:
            with self.engine.begin() as conn:
                # Используем to_sql с методом multi для ускорения,
                # но для OR REPLACE проще пройтись циклом или использовать временную таблицу.
                # Для надежности используем построчную вставку:
                for _, row in df.iterrows():
                    data = row.to_dict()
                    columns = ", ".join([f'"{k}"' for k in data.keys()])
                    placeholders = ", ".join([":" + k for k in data.keys()])
                    sql = f'INSERT OR REPLACE INTO product_barcodes ({columns}) VALUES ({placeholders})'
                    conn.execute(text(sql), data)
            return True, len(df)
        except Exception as e:
            logging.error(f"Ошибка импорта: {e}")
            return False, str(e)