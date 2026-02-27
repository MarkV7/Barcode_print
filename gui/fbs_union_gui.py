import re
from sqlalchemy import text
import logging


class UnionMark:
    """Базовый класс для общих операций маркировки FBS"""

    @staticmethod
    def extract_gtin(marking_code):
        """
        Извлекает GTIN из кода маркировки (DataMatrix).
        Логика: после '01' и до '215' (согласно ТЗ)
        """
        if not marking_code or len(marking_code) < 16:
            return None

        try:
            # Ищем '01', обычно он в самом начале
            if marking_code.startswith('01'):
                gtin = marking_code[2:16]
                return gtin if gtin.isdigit() else None

            # Если вдруг код пришел с "мусором" в начале, ищем первое вхождение '01'
            idx = marking_code.find('01')
            if idx != -1 and len(marking_code) >= idx + 16:
                gtin = marking_code[idx + 2: idx + 16]
                return gtin if gtin.isdigit() else None

        except Exception as e:
            logging.error(f"Ошибка парсинга GTIN из {marking_code}: {e}")
        return None

    def update_product_gtin(self, db_manager, vendor_code, size, gtin):
        """Записывает GTIN в базу, если его там еще нет для этого товара"""
        if not gtin:
            return

        try:
            with db_manager.engine.begin() as conn:
                # Проверяем существующий GTIN
                query_check = text(
                    'SELECT "GTIN" FROM product_barcodes WHERE "Артикул производителя" = :art AND "Размер" = :sz')
                current_gtin = conn.execute(query_check, {"art": vendor_code, "sz": size}).scalar()

                # Если GTIN пустой или другой, обновляем
                # (ТЗ: "уникальный... если записан то уже не записываем")
                if not current_gtin or gtin not in str(current_gtin):
                    new_val = gtin if not current_gtin else f"{current_gtin}, {gtin}"

                    update_query = text('''
                        UPDATE product_barcodes 
                        SET "GTIN" = :gtin 
                        WHERE "Артикул производителя" = :art AND "Размер" = :sz
                    ''')
                    conn.execute(update_query, {"gtin": new_val, "art": vendor_code, "sz": size})
                    logging.info(f"GTIN {gtin} обновлен для {vendor_code}")
        except Exception as e:
            logging.error(f"Ошибка записи GTIN в БД: {e}")

    def is_valid_chestny_znak(self, code: str) -> bool:
        # Проверяем, содержит ли строка неправильный регистр в известных фиксированных частях
        # Например: 91ee11 вместо 91EE11 — признак Caps Lock
        if '91ee11' in code or '92ee' in code.lower():  # можно расширить
            self.show_log('Отключите Casp Lock и сканируйте код маркировки еще раз')
            return False
        # Убираем спецсимволы разделители (FNC1 / GS / \x1d), если сканер их передает
        clean_code = code.replace('\x1d', '').strip()

        # Шаблон для полного кода (с криптохвостом)
        # GTIN(14) + Serial(13-20) + (опционально 91(4) + 92(44/88))
        # Обратите внимание: длина серийного номера бывает разной для разных товарных групп
        # (обувь, одежда - 13, шины - 20, табак - 7 и т.д.), поэтому ставим {1,20}
        pattern = r"^01(\d{14})21([\x21-\x7A]{1,20})(91[\x21-\x7A]{4}92[\x21-\x7A]{44,88})?$"

        return bool(re.match(pattern, clean_code))

    def is_valid_barcode(self, barcode: str) -> bool:
        """
        Проверяет, является ли строка валидным штрихкодом товара.

        Поддерживаемые форматы:
        - EAN-13: 13 цифр
        - EAN-8: 8 цифр (опционально)
        - UPC-A: 12 цифр (можно включить при необходимости)

        По умолчанию — только EAN-13 (наиболее распространён в РФ).
        """

        if not isinstance(barcode, str):
            return False
        # Убираем возможные пробелы или дефисы (иногда встречаются)
        barcode = barcode.strip().replace("-", "").replace(" ", "")

        # Проверка длины и цифр
        if not re.fullmatch(r"^\d{13}$", barcode):
            return False

        # Опционально: проверка контрольной суммы для EAN-13
        return self.is_valid_ean13_checksum(barcode)

    def is_valid_ean13_checksum(self,barcode: str) -> bool:
        """
        Проверяет контрольную сумму EAN-13.
        Алгоритм:
        - Сумма цифр на чётных позициях (2,4,6...) * 3
        - Плюс сумма цифр на нечётных позициях (1,3,5...)
        - Последняя цифра — контрольная
        - Общая сумма должна быть кратна 10
        """
        if len(barcode) != 13 or not barcode.isdigit():
            return False

        digits = [int(d) for d in barcode]
        # Позиции: 0-based, но в EAN-13 нумерация с 1 → чётные индексы = нечётные позиции
        # Считаем: позиции 1,3,5,7,9,11 → индексы 0,2,4,6,8,10 → НЕЧЁТНЫЕ индексы в 0-based считаются как "чётные позиции"
        # Правильный алгоритм:
        sum_odd = sum(digits[i] for i in range(0, 12, 2))  # позиции 1,3,5,...,11 → индексы 0,2,...,10
        sum_even = sum(digits[i] for i in range(1, 12, 2))  # позиции 2,4,...,12 → индексы 1,3,...,11
        total = sum_odd + 3 * sum_even
        check_digit = (10 - (total % 10)) % 10
        return check_digit == digits[12]