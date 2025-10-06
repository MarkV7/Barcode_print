# Примерный код для основного процесса
from wildberries_fbs_api import WildberriesFBSAPI
from config import *
import base64
import datetime

# Предполагаем, что есть модуль для прямой печати, например print_utils
import print_utils

def process_wb_orders_and_print(wb_orders_data: list, api_token: str):
    """
    Выполняет полный цикл: создание поставки, добавление заказов,
    получение ZPL-этикеток и печать.
    wb_orders_data: Список объектов/словарей заказов WB,
                    полученных из CRM/таблицы, каждый из которых содержит
                    как минимум 'order_id' (ID сборочного задания).
    """
    if not wb_orders_data:
        print("Нет заказов Wildberries для обработки.")
        return

    # 1. Инициализация API
    wb_api = WildberriesFBSAPI(api_token=api_token)

    # Получаем список ID сборочных заданий для обработки
    all_order_ids = [order['order_id'] for order in wb_orders_data]

    # --- 2. Создание Поставки ---
    # Генерируем уникальное имя для поставки (например, с текущей датой)
    supply_name = f"Поставка_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    try:
        print(f"Создание новой поставки: {supply_name}...")
        supply_response = wb_api.create_supply(name=supply_name)
        supply_id = supply_response.get('id')

        if not supply_id:
            print("Ошибка: Не удалось получить ID созданной поставки.")
            return

        print(f"Поставка создана. ID: {supply_id}")

    except Exception as e:
        print(f"Ошибка при создании поставки: {e}")
        return

    # --- 3. Добавление Заказов в Поставку ---
    try:
        print(f"Добавление {len(all_order_ids)} заказов в поставку {supply_id}...")
        # Предполагаем, что add_orders_to_supply реализован в API-классе
        wb_api.add_orders_to_supply(supply_id=supply_id, order_ids=all_order_ids)
        print("Заказы успешно добавлены в поставку.")

    except Exception as e:
        print(f"Ошибка при добавлении заказов в поставку: {e}")
        # Возможно, здесь нужно удалить поставку или вывести предупреждение
        return

    # --- 4. Получение Этикеток в ZPL формате ---
    try:
        print("Получение этикеток сборочных заданий в формате ZPL...")
        # Устанавливаем type="zpl" для прямой печати
        stickers_response = wb_api.get_stickers(
            order_ids=all_order_ids,
            type="zpl",
            width=58,
            height=40  # Стандартный размер для термоэтикеток
        )

        # Данные стикера в ZPL приходят в base64 кодировке
        encoded_stickers = stickers_response.get('stickers', [])

        if not encoded_stickers:
            print("В ответ не получено ни одной этикетки.")
            return

        # --- 5. Декодирование и Прямая Печать ---
        for sticker in encoded_stickers:
            zpl_base64 = sticker.get('file')
            if zpl_base64:
                # Декодируем base64 в чистый ZPL-код
                zpl_code = base64.b64decode(zpl_base64).decode('utf-8')

                # Отправляем ZPL-код на принтер
                print_utils.send_zpl_to_printer(zpl_code, host="192.168.1.100", port=9100)
                print(f"Отправлен ZPL-код для заказа {sticker.get('id')} на печать.")

            else:
                print(f"Не получены ZPL данные для заказа {sticker.get('id')}.")

    except Exception as e:
        print(f"Ошибка при получении/печати этикеток: {e}")
        return

if __name__ == "__main__":
    wb_orders_from_crm = [
        {'order_id': 12345, 'article': 'ART001', 'barcode': '1234567890'},
        {'order_id': 67890, 'article': 'ART002', 'barcode': '0987654321'},
    ]
    process_wb_orders_and_print(wb_orders_from_crm, api_token)