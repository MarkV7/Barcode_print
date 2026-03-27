import pandas as pd
from sqlalchemy import create_engine, text
import logging
import os
from typing import Dict, List, Optional
from datetime import datetime
# Создаем логгер для конкретного модуля
logger = logging.getLogger(__name__)

class DBManager:
    def __init__(self, db_name="barcode_print.db"):
        # База данных будет создана в корневой папке проекта как файл
        self.engine = create_engine(f'sqlite:///{db_name}')
        self.init_tables()
        # self.migrate_add_gtin_column()

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
                "GTIN" TEXT,
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
                "Время добавления" TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                "Статус" TEXT DEFAULT 'Отгружен',
                "Маркетплейс" TEXT,
                "Дата обновления" TIMESTAMP,
                "Дата продажи" TEXT
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
            # Запускаем проверку на случай, если таблица уже была создана старой версией
            self._migrate_marking_codes()
            logger.info("DB: Таблицы SQLite инициализированы.")
        except Exception as e:
            logger.error(f"DB: Ошибка инициализации таблиц: {e}")

    # Добавьте этот вызов в ваш класс DatabaseManager или выполните один раз
    def migrate_add_gtin_column(self):
        with self.engine.begin() as conn:
            try:
                conn.execute(text('ALTER TABLE product_barcodes ADD COLUMN "GTIN" TEXT'))
                logger.info("Столбец GTIN успешно добавлен в product_barcodes")
            except Exception as e:
                logger.warning(f"Столбец GTIN вероятно уже существует: {e}")

    def _migrate_marking_codes(self):
        """Добавляет недостающие колонки в существующую таблицу"""
        new_columns = {
            "Статус": "TEXT DEFAULT 'Отгружен'",
            "Маркетплейс": "TEXT",
            "Дата обновления": "TIMESTAMP",
            "Дата продажи": "TEXT"
        }

        try:
            with self.engine.begin() as conn:
                # Получаем текущие колонки
                existing_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(marking_codes)"))]

                for col_name, col_type in new_columns.items():
                    if col_name not in existing_columns:
                        logger.info(f"Миграция БД: Добавление колонки {col_name} в marking_codes")
                        conn.execute(text(f'ALTER TABLE marking_codes ADD COLUMN "{col_name}" {col_type}'))
        except Exception as e:
            logger.error(f"Ошибка миграции marking_codes: {e}")

    def update_kiz_status(self, marking_code: str, status: str, sale_date: str = None):
        """Метод для обновления статуса КИЗ после синхронизации с API"""
        sql = """
        UPDATE marking_codes 
        SET "Статус" = :status, 
            "Дата продажи" = :sale_date, 
            "Дата обновления" = datetime('now', 'localtime')
        WHERE "Код маркировки" = :code
        """
        try:
            with self.engine.begin() as conn:
                conn.execute(text(sql), {"status": status, "sale_date": sale_date, "code": marking_code})
            return True
        except Exception as e:
            logger.error(f"Ошибка обновления статуса КИЗ {marking_code}: {e}")
            return False

    def update_kiz_status_and_price(self, kiz_code, status, price):
        """Обновляет одновременно и статус, и цену товара"""
        # Если цена пришла пустая (None), обновляем только статус
        if price is None:
            query = text('UPDATE marking_codes SET "Статус" = :status WHERE "Код маркировки" = :kiz')
            params = {"status": status, "kiz": kiz_code}
        else:
            query = text('UPDATE marking_codes SET "Статус" = :status, "Цена" = :price WHERE "Код маркировки" = :kiz')
            params = {"status": status, "price": price, "kiz": kiz_code}

        with self.engine.connect() as conn:
            conn.execute(query, params)
            conn.commit()

    def sync_dataframe(self, df: pd.DataFrame, table_name: str, key_columns: list):
        """
        Синхронизирует DataFrame с таблицей БД.
        Если запись с такими ключами есть — обновляет, если нет — создает.
        """
        if df.empty:
            return
        # Подготавливаем названия всех колонок
        cols = df.columns.tolist()
        # Создаем часть запроса для вставки (INSERT)
        col_names = ", ".join([f'"{c}"' for c in cols])
        placeholders = ", ".join([f":{i}" for i in range(len(cols))])

        # Создаем часть запроса для обновления (UPDATE) при конфликте
        # Исключаем ключевые колонки из блока обновления
        update_cols = [c for c in cols if c not in key_columns]
        update_stmt = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in update_cols])

        # Итоговый SQL запрос (UPSERT логика)
        sql = f"""
        INSERT INTO {table_name} ({col_names})
        VALUES ({placeholders})
        ON CONFLICT ({", ".join([f'"{k}"' for k in key_columns])}) 
        DO UPDATE SET {update_stmt}
        """

        try:
            with self.engine.connect() as conn:
                # Преобразуем DF в список кортежей/словарей для выполнения
                data = [tuple(x) for x in df.values]
                # Выполняем для каждой строки
                for row in data:
                    params = {str(i): val for i, val in enumerate(row)}
                    conn.execute(text(sql), params)
                conn.commit()
        except Exception as e:
            logger.error(f"Ошибка UPSERT в таблицу {table_name}: {e}")
            raise e

    def upsert_ozon_orders(self, df: pd.DataFrame):
        """Специфический метод для Ozon: вставка или обновление существующих заказов"""
        if df is None or df.empty: return
        try:
            # На 1 этапе используем простую перезапись таблицы заказов,
            # так как fbs_df всегда содержит актуальное состояние.
            self.sync_dataframe(df, "ozon_fbs_orders", ["Номер отправления"])
            logger.info(f"DB: Таблица ozon_fbs_orders успешно перезаписана ({len(df)} строк).")
        except Exception as e:
            logger.error(f"DB: Ошибка перезаписи ozon_fbs_orders: {e}")

    def upsert_wb_orders(self, df: pd.DataFrame):
        """Специфический метод для WB: вставка или обновление существующих заказов"""
        if df is None or df.empty: return
        try:
            # На 1 этапе используем простую перезапись таблицы заказов,
            # так как fbs_df всегда содержит актуальное состояние.
            self.sync_dataframe(df, "wb_fbs_orders",["Номер заказа"])
            logger.info(f"DB: Таблица wb_fbs_orders успешно перезаписана ({len(df)} строк).")
        except Exception as e:
            logger.error(f"DB: Ошибка перезаписи wb_fbs_orders: {e}")

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
            logger.error(f"DB Error (add_marking): {e}")

    def upsert_marking_codes(self, df: pd.DataFrame):
        """Сохранение кодов маркировки в БД (UPSERT)"""
        if df is None or df.empty:
            return

        # SQL с именованными параметрами для безопасности
        sql = """
        INSERT INTO marking_codes ("Номер отправления", "Код маркировки", "Цена", "sku", "Артикул поставщика", "Размер", "Время добавления")
        VALUES (:order_id, :marking_code, :price, :sku, :vendor_code, :size, :add_time)
        ON CONFLICT ("Код маркировки") 
        DO UPDATE SET 
            "Номер отправления" = EXCLUDED."Номер отправления",
            "Цена" = EXCLUDED."Цена",
            "sku" = EXCLUDED."sku",
            "Артикул поставщика" = EXCLUDED."Артикул поставщика",
            "Размер" = EXCLUDED."Размер",
            "Время добавления" = EXCLUDED."Время добавления"
        """

        try:
            with self.engine.begin() as conn:
                for _, row in df.iterrows():
                    # --- ГЛАВНОЕ ИСПРАВЛЕНИЕ: Типы данных ---
                    # SQLite не понимает pd.Timestamp, поэтому принудительно переводим в строку
                    raw_time = row.get("Время добавления")
                    if pd.notnull(raw_time):
                        if hasattr(raw_time, 'strftime'):
                            add_time = raw_time.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            add_time = str(raw_time)
                    else:
                        add_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                    params = {
                        "order_id": str(row.get("Номер отправления", "")),
                        "marking_code": str(row.get("Код маркировки", "")),
                        "price": str(row.get("Цена", "")),
                        "sku": str(row.get("sku", "")),
                        "vendor_code": str(row.get("Артикул поставщика", "")),
                        "size": str(row.get("Размер", "")),
                        "add_time": add_time
                    }
                    conn.execute(text(sql), params)
            logger.info("КИЗ успешно синхронизированы с БД")
            return True
        except Exception as e:
            logger.error(f"Ошибка UPSERT в таблицу marking_codes: {e}")
            return False

    def delete_marking_code(self, cis_code):
        """Удаление маркировки из базы"""
        sql = 'DELETE FROM marking_codes WHERE "Код маркировки" = :cis;'
        try:
            with self.engine.begin() as conn:
                conn.execute(text(sql), {"cis": cis_code})
        except Exception as e:
            logger.error(f"DB Error (delete_marking): {e}")

    def delete_marking_codes_by_posting(self, posting_number):
        """Удаление всех кодов маркировки для конкретного отправления"""
        sql = 'DELETE FROM marking_codes WHERE "Номер отправления" = :posting;'
        try:
            with self.engine.begin() as conn:
                conn.execute(text(sql), {"posting": posting_number})
            logger.info(f"DB: Удалены КМ для отправления {posting_number}")
        except Exception as e:
            logger.error(f"DB Error (delete_marking_by_posting): {e}")

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
            logger.error(f"DB Error (update_barcode_record): {e}")


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
            logger.error(f"DB Error (get_product): {e}")
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
            logger.error(f"Ошибка обновления строки в {table_name}: {e}")

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
            logger.error(f"Ошибка при получении данных из БД: {e}")
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
            logger.error(f"Ошибка получения по SKU: {e}")
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

        # ВАЖНО: В  SQL-скрипте было "Баркод  Wildberries" (с двумя пробелами)
        params = {f'id{i}': str(b).strip() for i, b in enumerate(barcodes)}
        placeholders = ', '.join([':id' + str(i) for i in range(len(barcodes))])

        sql = f'''
                SELECT * FROM product_barcodes 
                WHERE CAST("Баркод  Wildberries" AS TEXT) IN ({placeholders})
            '''

        try:
            with self.engine.connect() as conn:
                res = pd.read_sql_query(text(sql), conn, params=params)
                return res if not res.empty else empty_df
        except Exception as e:
            logger.error(f"Ошибка DB WB: {e}")
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
            logger.error(f"Ошибка экспорта маркировки: {e}")
            return pd.DataFrame()

    def get_all_product_barcodes(self) -> pd.DataFrame:
        """Получает всю таблицу штрихкодов."""
        try:
            return pd.read_sql_query('SELECT * FROM product_barcodes', self.engine)
        except Exception as e:
            logger.error(f"Ошибка экспорта штрихкодов: {e}")
            return pd.DataFrame()

    def import_product_barcodes_old(self, df: pd.DataFrame):
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
            logger.error(f"Ошибка импорта: {e}")
            return False, str(e)

    def import_product_barcodes(self, df: pd.DataFrame, progress_callback=None):
        """Импорт с передачей прогресса"""
        try:
            # 1. Подготовка (быстрее делать вне транзакции)
            mapping = {"Баркод Wildberries": "Баркод  Wildberries", "Баркод  Wildberries": "Баркод  Wildberries"}
            df = df.rename(columns=mapping)

            existing_cols = ["Артикул производителя", "Размер", "Бренд", "Наименование поставщика",
                             "Штрихкод производителя", "Артикул Ozon", "Артикул Вайлдбериз",
                             "Штрихкод OZON", "Баркод  Wildberries", "Коробка", "SKU OZON"]

            available_cols = [c for c in existing_cols if c in df.columns]
            df = df[available_cols].copy()

            # Очистка форматов
            for col in df.columns:
                df[col] = df[col].astype(str).replace(r'\.0$', '', regex=True)
                df[col] = df[col].replace(['nan', 'None', 'NAN'], None)

            df = df.drop_duplicates(subset=["Артикул производителя", "Размер"])
            total_rows = len(df)
            chunk_size = 2000  # Меньший размер для SQLite стабильнее

            with self.engine.begin() as conn:
                conn.execute(text("DELETE FROM product_barcodes"))

                # Загружаем частями, чтобы обновлять прогресс-бар
                for i in range(0, total_rows, chunk_size):
                    chunk = df.iloc[i:i + chunk_size]
                    chunk.to_sql('product_barcodes', con=conn, if_exists='append', index=False)

                    if progress_callback:
                        percent = min((i + chunk_size) / total_rows, 1.0)
                        progress_callback(percent)

            return True, total_rows
        except Exception as e:
            logger.error(f"Ошибка импорта: {e}")
            return False, str(e)

    def delete_product_barcode(self, vendor_code: str, size: str) -> bool:
        """Удаляет запись из таблицы по артикулу и размеру"""
        sql = 'DELETE FROM product_barcodes WHERE "Артикул производителя" = :vc AND "Размер" = :sz'
        try:
            with self.engine.connect() as conn:
                conn.execute(text(sql), {"vc": vendor_code, "sz": size})
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка удаления записи: {e}")
            return False

    def get_product_by_wb_barcode(self, barcode: str) -> pd.DataFrame:
        """Поиск товара по Баркоду WB"""
        sql = 'SELECT * FROM product_barcodes WHERE "Баркод  Wildberries" = :b'
        with self.engine.connect() as conn:
            return pd.read_sql_query(text(sql), conn, params={"b": str(barcode)})

    def get_product_by_barcode(self, barcode: str) -> pd.DataFrame:
        """Поиск товара по Штрихкоду товара"""
        sql = """ SELECT * 
                    FROM product_barcodes 
                    WHERE "Штрихкод производителя" = :b 
                    LIMIT 1 """
        with self.engine.connect() as conn:
            return pd.read_sql_query(text(sql), conn, params={"b": str(barcode)})

    def get_product_by_ozon_id(self, query: str) -> pd.DataFrame:
        """Поиск товара по Штрихкоду или Артикулу Ozon"""
        sql = '''
            SELECT * FROM product_barcodes 
            WHERE "Штрихкод OZON" = :q OR "Артикул Ozon" = :q
        '''
        with self.engine.connect() as conn:
            return pd.read_sql_query(text(sql), conn, params={"q": str(query)})

    def heal_database_from_df(self, df: pd.DataFrame, progress_callback=None):
        """Синхронизация: дополняет пустые поля в БД данными из DF"""
        if df is None or df.empty:
            return False, "DataFrame пуст"

        total = len(df)
        keys = ["Артикул производителя", "Размер"]

        try:
            with self.engine.begin() as conn:
                for i, (_, row) in enumerate(df.iterrows()):
                    update_parts = []
                    # Базовые параметры для WHERE
                    params = {"vc": str(row[keys[0]]), "sz": str(row[keys[1]])}

                    for col in df.columns:
                        if col not in keys:
                            val = str(row[col]) if pd.notnull(row[col]) else ""

                            # Проверяем, что значение не пустое и не 'nan'
                            if val.strip() and val.lower() != 'nan':
                                # 1. Генерируем БЕЗОПАСНОЕ имя параметра (без пробелов!)
                                # Например: "Баркод  Wildberries" -> "p_Баркод__Wildberries"
                                safe_param_name = f"p_{col.replace(' ', '_').replace('-', '_')}"

                                # 2. Формируем SQL часть
                                # В базе колонка в кавычках ("Баркод  Wildberries"), а параметр безопасный (:p_Баркод__Wildberries)
                                update_parts.append(
                                    f'"{col}" = CASE WHEN "{col}" IS NULL OR "{col}" = "" THEN :{safe_param_name} ELSE "{col}" END')

                                # 3. Добавляем значение в словарь параметров
                                params[safe_param_name] = val.strip()

                    if update_parts:
                        sql = f"""
                            UPDATE product_barcodes 
                            SET {", ".join(update_parts)}
                            WHERE "Артикул производителя" = :vc AND "Размер" = :sz
                        """
                        conn.execute(text(sql), params)

                    if progress_callback and i % 20 == 0:
                        progress_callback(i / total)

            return True, total
        except Exception as e:
            logger.error(f"Ошибка восстановления БД: {e}")
            return False, str(e)

    def patch_marketplace_column(self):
        """Автоматически заполняет колонку Маркетплейс для старых записей"""
        try:
            with self.engine.begin() as conn:
                # 1. Если в номере есть дефис — это точно Ozon
                sql_ozon = """
                UPDATE marking_codes 
                SET "Маркетплейс" = 'Ozon' 
                WHERE "Маркетплейс" IS NULL AND "Номер отправления" LIKE '%-%'
                """
                conn.execute(text(sql_ozon))

                # 2. Если дефиса нет и это только цифры — это WB
                # В SQLite нет сложной проверки на цифры, поэтому используем простую логику:
                # Все, что осталось пустым после Ozon, помечаем как WB
                sql_wb = """
                UPDATE marking_codes 
                SET "Маркетплейс" = 'WB' 
                WHERE "Маркетплейс" IS NULL
                """
                conn.execute(text(sql_wb))

            logger.info("База данных успешно пропатчена: Маркетплейсы распределены.")
            return True
        except Exception as e:
            logger.error(f"Ошибка при патче базы данных: {e}")
            return False

    def sync_gtins_from_history(self):
        """Генератор для синхронизации GTIN из всех существующих КИЗ"""
        try:
            # 1. Получаем все КИЗ и связку с товаром
            with self.engine.connect() as conn:
                query = text('''
                    SELECT "Код маркировки", "Артикул поставщика", "Размер" 
                    FROM marking_codes 
                    WHERE "Код маркировки" IS NOT NULL
                ''')
                records = conn.execute(query).fetchall()

            if not records:
                return

            total = len(records)
            for i, (kiz, art, size) in enumerate(records):
                # ПРОВЕРКА: Если артикул или размер пустые — пропускаем эту итерацию
                if not art or str(art).strip() == "" or not size or str(size).strip() == "":
                    continue
                # Извлекаем GTIN (первые 14 цифр после '01')
                gtin = None
                if kiz.startswith('01') and len(kiz) > 16:
                    # Согласно GS1, GTIN — это 14 цифр после AI '01'
                    gtin = kiz[2:16]

                if gtin:
                    # Записываем в БД через UPDATE
                    with self.engine.begin() as conn_upd:
                        # Проверяем текущий GTIN, чтобы не дублировать
                        check = conn_upd.execute(text(
                            'SELECT "GTIN" FROM product_barcodes WHERE "Артикул производителя" = :art AND "Размер" = :sz'
                        ), {"art": art, "sz": size}).scalar()

                        current_gtins = str(check) if check else ""
                        if gtin not in current_gtins:
                            new_gtin_val = f"{current_gtins}, {gtin}".strip(", ")
                            conn_upd.execute(text('''
                                UPDATE product_barcodes 
                                SET "GTIN" = :gtin 
                                WHERE "Артикул производителя" = :art AND "Размер" = :sz
                            '''), {"gtin": new_gtin_val, "art": art, "sz": size})

                # Отдаем прогресс (от 0 до 1)
                yield (i + 1) / total

        except Exception as e:
            logger.error(f"Ошибка синхронизации GTIN: {e}")
            yield 1.0

    def cleanup_empty_product_records(self):
        """Вспомогательный метод: удаляет строки с пустыми ключевыми полями"""
        try:
            with self.engine.begin() as conn:
                # Удаляем строки, где и Артикул, и Размер пусты или состоят из пробелов
                query = text('''
                    DELETE FROM product_barcodes 
                    WHERE (TRIM("Артикул производителя") = '' OR "Артикул производителя" IS NULL)
                      AND (TRIM("Размер") = '' OR "Размер" IS NULL)
                ''')
                result = conn.execute(query)
                return result.rowcount
        except Exception as e:
            logger.error(f"Ошибка очистки пустых строк: {e}")
            return 0

    def deduplicate_product_barcodes_new(self):
        """Полная очистка: сначала удаляем пустые записи, затем дубликаты"""
        try:
            # 1. Сначала чистим 'призраков' (пустые строки)
            removed_empty = self.cleanup_empty_product_records()
            if removed_empty > 0:
                logger.info(f"Очистка БД: Удалено {removed_empty} пустых строк-призраков.")

            # 2. Теперь запускаем  стандартную логику дедупликации
            with self.engine.begin() as conn:
                # Пример логики удаления дублей, оставляя строку с максимальным кол-вом данных
                query = text('''
                    DELETE FROM product_barcodes 
                    WHERE rowid NOT IN (
                        SELECT MIN(rowid) 
                        FROM product_barcodes 
                        GROUP BY "Артикул производителя", "Размер"
                    )
                ''')
                result = conn.execute(query)
                total_removed = result.rowcount + removed_empty

            return True, total_removed
        except Exception as e:
            logger.error(f"Ошибка дедупликации: {e}")
            return False, str(e)

    def deduplicate_product_barcodes(self):
        """Объединяет дубликаты, схлопывая данные в одну строку"""
        try:
            # 1. Сначала чистим 'призраков' (пустые строки)
            removed_empty = self.cleanup_empty_product_records()
            if removed_empty > 0:
                logger.info(f"Очистка БД: Удалено {removed_empty} пустых строк-призраков.")

            # 2. Теперь запускаем  стандартную логику дедупликации
            with self.engine.connect() as conn:
                # 1. Получаем все данные
                df = pd.read_sql_table("product_barcodes", conn)
                # 2. Группируем по ключам и выбираем первое непустое значение для каждой колонки (first non-null)
                # Это 'умное' объединение
                df_clean = df.groupby(["Артикул производителя", "Размер"], as_index=False).first()

                # 3. Пересоздаем таблицу
                conn.execute(text("DELETE FROM product_barcodes"))
                df_clean.to_sql("product_barcodes", conn, if_exists="append", index=False)
                conn.commit()
            return True, len(df) - len(df_clean)  # Возвращаем кол-во удаленных дублей
        except Exception as e:
            logger.error(f"Ошибка дедупликации: {e}")
            return False, str(e)

    def import_kiz_directory(self, df, progress_callback=None):
        """
        Импортирует данные КИЗ в таблицу marking_codes.
        Ожидает колонки: 'Код маркировки', 'Номер отправления', 'Маркетплейс', 'Статус', 'sku', 'Цена'
        """
        try:
            # Приводим названия колонок к единому стандарту, если нужно
            # (необязательно, если в Excel они называются так же, как в БД)

            total_rows = len(df)
            if total_rows == 0:
                return True, 0

            with self.engine.begin() as conn:
                for index, row in df.iterrows():
                    # Логика: если КИЗ существует - обновляем данные, если нет - создаем
                    # Используем INSERT OR REPLACE для SQLite
                    stmt = text('''
                        INSERT OR REPLACE INTO marking_codes 
                        ("Код маркировки", "Номер отправления", "Маркетплейс", "Статус", "sku", "Цена")
                        VALUES (:kiz, :order_num, :mp, :status, :sku, :price)
                    ''')

                    conn.execute(stmt, {
                        "kiz": str(row.get('Код маркировки', '')).strip(),
                        "order_num": str(row.get('Номер отправления', '')).strip(),
                        "mp": str(row.get('Маркетплейс', '')).strip(),
                        "status": str(row.get('Статус', 'Новый')).strip(),
                        "sku": str(row.get('sku', '')).strip(),
                        "price": row.get('Цена', 0)
                    })

                    if progress_callback and index % 10 == 0:
                        progress_callback(index / total_rows)

            return True, total_rows
        except Exception as e:
            logger.error(f"DB: Ошибка импорта КИЗ: {e}")
            return False, str(e)

    def sync_ozon_returns_old(self,returns_list):
        """
        Обновление статусов в marking_codes на основе данных API.
        """
        if not returns_list:
            return 0

        updated_count = 0

        # Группируем данные из API: {номер_заказа: {sku: количество}}
        # Это нужно, чтобы корректно обработать частичные возвраты
        processed_returns = {}
        for item in returns_list:
            order_id = item.get('posting_number')
            sku = str(item.get('sku'))
            status_ozon = item.get('status_name')  # например, 'returned_to_seller'

            if order_id not in processed_returns:
                processed_returns[order_id] = {}

            if sku not in processed_returns[order_id]:
                processed_returns[order_id][sku] = {
                    'qty': 0,
                    'status': status_ozon
                }
            processed_returns[order_id][sku]['qty'] += 1

        with self.engine.connect() as conn:
            for order_id, skus in processed_returns.items():
                for sku, info in skus.items():
                    # Находим КИЗы по этому заказу и SKU, которые сейчас "Выкуплены"
                    find_query = text("""
                        SELECT id FROM marking_codes 
                        WHERE order_id = :order_id 
                        AND sku = :sku 
                        AND status = 'Выкуплен'
                        ORDER BY id ASC
                    """)

                    rows = conn.execute(find_query, {"order_id": order_id, "sku": sku}).fetchall()

                    # Обновляем ровно столько штук, сколько пришло в отчете о возвратах
                    to_update = rows[:info['qty']]

                    for row in to_update:
                        # Маппинг статуса
                        new_status = f"Возврат: {info['status']}"

                        update_query = text("""
                            UPDATE marking_codes 
                            SET status = :new_status,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = :id
                        """)
                        conn.execute(update_query, {"new_status": new_status, "id": row[0]})
                        updated_count += 1

            conn.commit()

        logger.info(f"Синхронизация завершена. Обновлено статусов: {updated_count}")
        return updated_count


    def sync_ozon_returns(self, returns_list):
        """
        Обновление статусов в marking_codes на основе данных API v1.
        Учитывает частичные возвраты (qty) и пишет дату возврата из API.
        """
        if not returns_list:
            return 0

        updated_count = 0

        # 1. Группируем данные. Учитываем 'quantity' для частичных/множественных возвратов
        processed_returns = {}
        for item in returns_list:
            order_id = item.get('posting_number')
            sku = str(item.get('sku'))
            status_ozon = item.get('status_name') or "Принят"

            # Если Ozon прислал quantity > 1, конвертируем
            qty = int(item.get('quantity', 1))

            # Парсинг даты (Ozon присылает '2024-07-29T06:15:48.998146Z')
            # Переводим в понятный SQLite вид: '2024-07-29 06:15:48'
            return_date_str = item.get('return_date')
            if return_date_str:
                return_date_clean = return_date_str.replace('T', ' ')[:19]
            else:
                return_date_clean = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if not order_id or sku == "None":
                continue

            if order_id not in processed_returns:
                processed_returns[order_id] = {}

            if sku not in processed_returns[order_id]:
                processed_returns[order_id][sku] = {
                    'qty': 0,
                    'status': status_ozon,
                    'return_date': return_date_clean
                }

            # Суммируем количество
            processed_returns[order_id][sku]['qty'] += qty

        # 2. Обновление БД
        with self.engine.connect() as conn:
            for order_id, skus in processed_returns.items():
                for sku, info in skus.items():
                    # Ищем все КИЗы заказа с этим SKU, которые еще НЕ в статусе возврата
                    find_query = text("""
                        SELECT "Код маркировки" FROM marking_codes 
                        WHERE "Номер отправления" = :order_id 
                        AND "sku" = :sku 
                        AND "Статус" NOT LIKE 'Возврат%'
                        ORDER BY "Время добавления" ASC
                    """)

                    rows = conn.execute(find_query, {"order_id": order_id, "sku": sku}).fetchall()

                    if not rows:
                        # Запасной поиск по Артикулу поставщика
                        find_alt_query = text("""
                            SELECT "Код маркировки" FROM marking_codes 
                            WHERE "Номер отправления" = :order_id 
                            AND "Артикул поставщика" = :sku
                            AND "Статус" NOT LIKE 'Возврат%'
                        """)
                        rows = conn.execute(find_alt_query, {"order_id": order_id, "sku": sku}).fetchall()

                    # Ограничиваем список КИЗов количеством возвращенных штук
                    to_update = rows[:info['qty']]

                    if not to_update:
                        # logger.warning(f"DB: Не найден КИЗ для заказа {order_id} (SKU: {sku}, ищем {info['qty']} шт.)")
                        continue

                    for row in to_update:
                        new_status = f"Возврат: {info['status']}"

                        # ИЗМЕНЕНИЕ: Пишем дату возврата из API в "Дата продажи",
                        # а системное время - в "Дата обновления"
                        update_query = text("""
                                            UPDATE marking_codes 
                                            SET "Статус" = :new_status,
                                                "Дата продажи" = :return_date,
                                                "Дата обновления" = datetime('now', 'localtime')
                                            WHERE "Код маркировки" = :code
                                        """)
                        conn.execute(update_query, {
                            "new_status": new_status,
                            "return_date": info['return_date'],  # Дата из API Ozon
                            "code": row[0]
                        })
                        updated_count += 1

            conn.commit()

        logger.info(f"Синхронизация завершена. Из {len(returns_list)} записей API обновлено КИЗов: {updated_count}")
        return updated_count