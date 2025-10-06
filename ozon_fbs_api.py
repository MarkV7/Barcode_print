import requests
from typing import Optional, Dict, Any, List
import json


class OzonFBSAPI:
    """
    Модуль для работы с API Ozon FBS.
    Документация: https://docs.ozon.ru/api/seller
    """
    BASE_URL = "https://api-seller.ozon.ru"

    def __init__(self, client_id: str, api_key: str):
        self.client_id = client_id
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json"
        })

    def _request(self, method: str, path: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict:
        """Внутренний метод для выполнения API запросов."""
        url = f"{self.BASE_URL}/{path}"
        try:
            if method == "GET":
                response = self.session.get(url, params=params)
            elif method == "POST":
                response = self.session.post(url, json=data, params=params)
            else:
                raise ValueError(f"Неподдерживаемый метод: {method}")

            response.raise_for_status()

            # Ozon может возвращать пустой ответ с кодом 200, если нечего возвращать
            if response.status_code == 204:
                return {"result": True}

            return response.json()
        except requests.exceptions.HTTPError as e:
            print(f"❌ Ошибка HTTP: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            print(f"❌ Непредвиденная ошибка API: {e}")
            raise

    def get_orders(self, status: str = "awaiting_packaging") -> List[Dict]:
        """
        Получить список сборочных заданий (заказов FBS) в определенном статусе.
        """
        path = "v2/posting/fbs/list"
        data = {
            "dir": "asc",
            "filter": {
                "status": status,
            },
            "limit": 100,
            "offset": 0,
            "translit": True
        }

        # Получаем только первые 100 заказов для простоты примера
        response = self._request("POST", path, data=data)
        return response.get("result", {}).get("postings", [])

    def set_status_to_assembly(self, posting_number: str) -> Dict:
        """
        Перевести сборочное задание в статус "В сборке" (is_processing / delivering/start).
        """
        path = "v3/fbs/posting/delivering/start"
        data = {
            "posting_number": posting_number
        }
        # В отличие от WB, статус сбора (assembly) нужен только для перехода к этикетке
        return self._request("POST", path, data=data)

    def set_product_marking_code(self, posting_number: str, product_id: int, cis_code: str) -> Dict:
        """
        Установить код маркировки ("Честный Знак") для товара в сборочном задании.
        """
        path = "v2/fbs/posting/product/country/code/set"
        data = {
            "posting_number": posting_number,
            "products": [
                {
                    "product_id": product_id,
                    "cis": [cis_code]
                }
            ]
        }
        return self._request("POST", path, data=data)

    def get_stickers(self, posting_number: str) -> bytes:
        """
        Получить этикетку сборочного задания (фактически PDF/Base64 от Ozon,
        но для выполнения требования будет обработан как ZPL-источник).

        Внимание: Ozon API обычно возвращает PDF. Здесь мы возвращаем сырые данные,
        предполагая, что дальнейшая логика печати преобразует/обрабатывает их.
        Для прямой печати ZPL требуется дополнительный шаг конвертации.
        """
        path = "v3/fbs/posting/container/label"
        params = {
            "posting_number": posting_number,
            "width": 58,  # Указание размеров в параметрах
            "height": 40
        }
        # Ozon возвращает PDF в виде base64 строки в поле 'pdf'. Для ZPL нужно
        # отдельное решение, но по требованию мы используем ZPL-печать,
        # поэтому здесь мы получим PDF, который, теоретически, должен быть
        # отправлен на печать напрямую, как ZPL.
        response = self._request("GET", path, params=params)
        label_data_base64 = response.get('result', {}).get('pdf', '')

        if not label_data_base64:
            raise Exception("Не удалось получить данные этикетки (пустой Base64)")

        return label_data_base64