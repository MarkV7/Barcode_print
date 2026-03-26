import logging
from logging.handlers import RotatingFileHandler
import os


def setup_global_logger():
    """Централизованная настройка логирования с ротацией и фильтрацией шума"""

    # Создаем каталог для логов, если его нет
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, "app.log")

    # --- КРИТИЧЕСКИЙ МОМЕНТ ---
    # Получаем корневой логгер и УДАЛЯЕМ все старые обработчики (которые пишут в корень)
    root_logger = logging.getLogger()

    if root_logger.hasHandlers():
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
    # -------------------------

    # 1. Настройка ротации (Размер 5МБ, храним 5 последних копий)
    # Итого логи не займут более 25-30 МБ на диске
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding='utf-8'
    )

    # Формат: Дата Время - Имя модуля - Уровень - Сообщение
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # 3. Обработчик для КОНСОЛИ (экрана)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)  # ПРИМЕНЯЕМ ТОТ ЖЕ ФОРМАТ ЗДЕСЬ

    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

    # Блокировка шума
    for noisy in ['PIL', 'Image', 'fitz', 'urllib3', 'requests']:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.info("Логирование переведено в папку /logs/. Ротация включена.")