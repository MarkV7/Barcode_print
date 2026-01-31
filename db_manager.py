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