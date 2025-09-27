from pystrich.datamatrix import DataMatrixEncoder
from typing import Dict, Optional
import os
from PIL import Image
from io import BytesIO


class GS1DataMatrixGenerator:
    """
    Класс для генерации GS1 DataMatrix кодов
    """
    FNC1 = chr(231)  # FNC1 для GS1 DataMatrix

    def __init__(self):
        pass

    def _process_gs1_string(self, gs1_string: str) -> str:
        """
        Обработка строки GS1: добавление FNC1 в начало и замена пробелов на FNC1
        
        Args:
            gs1_string (str): Строка в формате GS1
            
        Returns:
            str: Обработанная строка c FNC1
        """
        # Разбиваем строку по позициям
        gs1_string = gs1_string.replace(' ', '')
        part1 = gs1_string[:31]
        part2 = gs1_string[31:31+6]
        part3 = gs1_string[31+6:]
        result_string = f"{part1} {part2} {part3}"
        # Заменяем пробелы на FNC1
        processed_string = result_string.replace(" ", self.FNC1)
        # Добавляем FNC1 в начало, если его еще нет
        if not processed_string.startswith(self.FNC1):
            processed_string = self.FNC1 + processed_string
        return processed_string

    def generate_from_string(self,
                         gs1_string: str,
                         cell_size: int = 5) -> Image.Image:
        """
        Генерация DataMatrix кода из строки GS1 без сохранения на диск.
        
        Args:
            gs1_string (str): Строка в формате GS1
            cell_size (int): Размер одной ячейки (модуля) в пикселях
            
        Returns:
            PIL.Image.Image: Сгенерированный GS1 DataMatrix как изображение
        """
        # Обрабатываем строку
        data = self._process_gs1_string(gs1_string)

        # Генерируем DataMatrix
        encoder = DataMatrixEncoder(data)

        # Сохраняем в байты
        img_bytes = BytesIO(encoder.get_imagedata())

        # Загружаем из байтов в PIL.Image
        image = Image.open(img_bytes).convert("RGB")

        return image
