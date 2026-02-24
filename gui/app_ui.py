import json
import os
import pandas as pd
import numpy as np
from functools import partial
import customtkinter as ctk
import tkinter.messagebox as messagebox
from context import AppContext
from gui.settings_gui import SettingsMode
from gui.database_gui import DatabaseMode
from gui.return_sklad_gui import ReturnMode
from gui.ozon_gui import OzonMode
from gui.wb_gui import WildberriesMode
from db_manager import DBManager
from gui.fbs_wb_gui import FBSModeWB
from gui.fbs_ozon_gui import FBSModeOzon
from gui.reports_gui import ReportsMode
from gui.db_viewer_gui import DBViewerMode
from gui.kiz_directory_gui import KizDirectoryMode
import base64
import logging

CONFIG_FILE = "config.json"
CONTEXT_FILE = 'app_context.pkl'

ctk.set_appearance_mode("System")  # или "Light"
ctk.set_default_color_theme("blue")


class AppUI:
    def __init__(self, root):
        self.root = root
        self._setup_logger()  # <--- ДОБАВИТЬ СЮДА
        self.root.title("Склад Ozon / Wildberries")
        self.root.geometry("1700x800")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.db_manager = DBManager()
        # Контекст — центральное хранилище данных
        self.context = AppContext()
        self.context.load_from_file(CONTEXT_FILE)

        # Загружаем данные в контекст из конфига
        self.load_config()
        self.df_original = None

        # Настройка сетки
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # Шрифты
        self.font_bold = ctk.CTkFont(family="Segoe UI", size=18, weight="bold")
        self.font_normal = ctk.CTkFont(family="Segoe UI", size=14)

        # Меню слева
        self.menu_frame = ctk.CTkFrame(
            self.root, width=200, corner_radius=0, fg_color="#2A2D2E")
        self.menu_frame.grid(row=0, column=0, sticky="nswe")

        self.label_menu = ctk.CTkLabel(
            self.menu_frame,
            text="Меню",
            font=self.font_bold,
            text_color="white"
        )
        self.label_menu.pack(pady=20)

        # Кнопки меню
        self.btns = {}
        btn_data = [
            # ("База данных стар.", self.show_database),
            ("База данных (SQL)", self.show_db_viewer_page),
            ("Справочник КИЗ", self.show_kiz_directory_page),
            ("Возврат на склад", self.show_return),
            ("ФБО Ozon", self.show_ozon),
            # ("ФБО Ozon (New)", self.show_ozon2),
            ("ФБО Wildberries", self.show_wildberries),
            ("Wildberries ФБС", self.show_wildberries_fbs),
            ("Ozon ФБС", self.show_ozon_fbs),
            ("Настройки", self.show_settings),
            ("Отчеты", self.show_reports_page),
            ("Выход", self.on_close),
        ]

        for i, (name, command) in enumerate(btn_data):
            btn = ctk.CTkButton(
                self.menu_frame,
                text=name,
                anchor="w",
                font=self.font_normal,
                fg_color="transparent",
                hover_color="#555555",
                command=partial(self.set_active_and_show, command, i)
            )
            btn.pack(pady=5, padx=10, fill="x")
            self.btns[name] = btn

        # Активная кнопка по умолчанию
        self.active_index = None
        self.set_active(0)

        # Область контента <-- Сначала создаём
        self.content_frame = ctk.CTkFrame(self.root, corner_radius=10)
        self.content_frame.grid(
            row=0, column=1, sticky="nswe", padx=10, pady=10)

        # Текущий экран
        self.current_frame = None

        # Вместо self.show_database() теперь вызываем приветственный экран
        self.show_welcome_screen()

    def _setup_logger(self):
        """Настраивает логирование: удаляет дубли, ставит UTF-8 и глушит мусор."""
        # 1. Получаем корневой логгер
        root_logger = logging.getLogger()

        # 2. Удаляем ВСЕ существующие обработчики (чтобы не было дублей)
        if root_logger.hasHandlers():
            root_logger.handlers.clear()

        # 3. Создаем форматтер
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')

        # 4. Обработчик для файла (обязательно utf-8)
        file_handler = logging.FileHandler("app.log", encoding='utf-8')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        # 5. Обработчик для консоли
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # 6. Устанавливаем уровень INFO
        root_logger.setLevel(logging.INFO)

        # 7. Глушим шумные библиотеки
        logging.getLogger('PIL').setLevel(logging.WARNING)
        logging.getLogger('Image').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('fitz').setLevel(logging.WARNING)

    def show_welcome_screen(self):
        """Отрисовка приветственного экрана с быстрыми кнопками"""
        # 1. Очищаем контент-фрейм (используем правильное имя self.content_frame)
        self._clear_content() #

        # 2. Создаем центральный контейнер для текста и кнопок
        welcome_container = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        welcome_container.place(relx=0.5, rely=0.45, anchor="center")

        # 3. Заголовок
        title_label = ctk.CTkLabel(
            welcome_container,
            text="Рабочее место оператора",
            font=ctk.CTkFont(size=42, weight="bold")
        )
        title_label.pack(pady=(0, 10))

        # 4. Подзаголовок
        subtitle_label = ctk.CTkLabel(
            welcome_container,
            text="Интегрированная система обработки заказов: Ozon & Wildberries",
            font=ctk.CTkFont(size=20),
            text_color="gray60"
        )
        subtitle_label.pack(pady=(0, 60))

        # 5. Контейнер для больших кнопок
        button_frame = ctk.CTkFrame(welcome_container, fg_color="transparent")
        button_frame.pack()

        # Кнопка Ozon FBS
        ozon_btn = ctk.CTkButton(
            button_frame,
            text="Ozon ФБС",
            width=280,
            height=140,
            font=ctk.CTkFont(size=22, weight="bold"),
            corner_radius=15,
            # Используем индекс 6 (соответствует Ozon ФБС в вашем списке btn_data)
            command=lambda: self.set_active_and_show(self.show_ozon_fbs, 6)
        )
        ozon_btn.grid(row=0, column=0, padx=25)

        # Кнопка Wildberries FBS
        wb_btn = ctk.CTkButton(
            button_frame,
            text="Wildberries ФБС",
            width=280,
            height=140,
            font=ctk.CTkFont(size=22, weight="bold"),
            corner_radius=15,
            fg_color="#7B1FA2",      # Фиолетовый WB
            hover_color="#6A1B9A",
            # Используем индекс 5 (соответствует Wildberries ФБС в вашем списке btn_data)
            command=lambda: self.set_active_and_show(self.show_wildberries_fbs, 5)
        )
        wb_btn.grid(row=0, column=1, padx=25)

        # 6. Подсказка внизу
        hint_label = ctk.CTkLabel(
            welcome_container,
            text="Выберите сервис для начала работы или воспользуйтесь боковым меню",
            font=ctk.CTkFont(size=15, slant="italic"),
            text_color="gray50"
        )
        hint_label.pack(pady=(50, 0))

    def save_config(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_excel_path": self.context.file_path},
                      f, ensure_ascii=False)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.context.file_path = data.get("last_excel_path")

    def save_df_to_excel(self):
        """
        Сохраняет DataFrame из контекста обратно в Excel по пути self.context.file_path
        """
        if self.context.df is not None and self.context.file_path:
            try:
                # Сохраняем DataFrame обратно в Excel
                self.context.df.to_excel(self.context.file_path, index=False)
                logging.info(f"✅ Данные успешно сохранены в {self.context.file_path}")
            except Exception as e:
                logging.error(f"❌ Ошибка при сохранении файла: {e}")
        else:
            logging.info("⚠️ Нет данных для сохранения или не указан путь к файлу")

    def save_df_to_excel_cis(self):
        """
        Сохраняет DataFrame из контекста обратно в Excel по пути Data/
        Создаёт резервные копии: _back и _back_back
        """
        temp_dir = "Data"
        file_name = "Справочник кодов маркировки.xlsx"
        os.makedirs(temp_dir, exist_ok=True)
        filepath = os.path.join(temp_dir, file_name)

        if self.context.df_cis is not None:
            try:
                # Пути к резервным копиям
                back_file = os.path.join(temp_dir, "Справочник кодов маркировки_back.xlsx")
                back_back_file = os.path.join(temp_dir, "Справочник кодов маркировки_back_back.xlsx")

                # Если основной файл уже существует, сдвигаем копии
                if os.path.exists(filepath):
                    if os.path.exists(back_file):
                        if os.path.exists(back_back_file):
                            # Удаляем старую back_back копию
                            os.remove(back_back_file)
                        # Перемещаем back в back_back
                        os.rename(back_file, back_back_file)
                    # Перемещаем текущий файл в back
                    os.rename(filepath, back_file)

                # Проверяем, есть ли колонка "Код маркировки"
                if "Код маркировки" in self.context.df_cis.columns:
                    # Кодируем значения в Base64
                    # self.context.df_cis["Код маркировки"] = self.context.df_cis["Код маркировки"].apply(
                    #     lambda x: base64.b64encode(x.encode('utf-8')).decode('utf-8') if pd.notna(x) else x)
                    # Удаляем из строки подстроку с управляющими символами: 91EE11
                    self.context.df_cis["Код маркировки"] = self.context.df_cis["Код маркировки"].apply(
                        lambda x: x.replace('\x1D91EE11\x1D', '') if pd.notna(x) and isinstance(x, str) else x
                    )

                # Сохраняем новый DataFrame в основной файл
                self.context.df_cis.to_excel(filepath, index=False)
                logging.info(f"✅ Данные успешно сохранены в {filepath}")

            except Exception as e:
                logging.error(f"❌ Ошибка при сохранении файла: {e}")
        else:
            logging.info("⚠️ Нет данных для сохранения Справочника кодов маркировки")

    def set_active_and_show(self, screen_func, index):
        self.set_active(index)
        screen_func()

    def set_active(self, index):
        """Выделяет активную кнопку"""
        for i, btn in enumerate(self.btns.values()):
            if i == index:
                btn.configure(fg_color="#1F6AA5")
            else:
                btn.configure(fg_color="transparent")
        self.active_index = index

    def _clear_content(self):
        """
        Уничтожает текущий активный виджет, гарантируя отмену всех
        запланированных после-вызовов (after-колбэков).
        """
        if self.current_frame:
            try:
                # 1. Вызываем destroy().
                # Если форма (FBSModeOzon/WB) имеет наш кастомный метод destroy(),
                # он отменит все self.after() таймеры.
                self.current_frame.destroy()
            except Exception:
                # На случай, если что-то пошло не так при уничтожении,
                # просто игнорируем, чтобы избежать краша в app_ui.py.
                pass
            finally:
                # 2. Обнуляем ссылку, чтобы не обращаться к удаленному объекту
                self.current_frame = None

    def show_database(self):
        self._clear_content()
        frame = DatabaseMode(self.content_frame,
                             self.font_normal, self.context)
        frame.pack(fill="both", expand=True)
        self.current_frame = frame

        def load_data_after_show():
            if self.context.file_path:
                frame.load_excel_file(self.context.file_path)
                if self.df_original is None:
                    self.df_original = self.context.df.copy()

        self.root.after(100, load_data_after_show)

    def show_return(self):
        self._clear_content()
        frame = ReturnMode(self.content_frame, self.font_normal, self.context)
        frame.pack(fill="both", expand=True)
        self.current_frame = frame

    def show_ozon(self):
        self._clear_content()
        frame = OzonMode(self.content_frame, self.font_normal, self.context)
        frame.pack(fill="both", expand=True)
        self.current_frame = frame

    def show_wildberries(self):
        self._clear_content()
        frame = WildberriesMode(
            self.content_frame, self.font_normal, self.context)
        frame.pack(fill="both", expand=True)
        self.current_frame = frame

    # def show_autosborka_fbs(self):
    #     self._clear_content()
    #     frame = FBSMode(
    #         self.content_frame, self.font_normal, self.context
    #     )
    #     frame.pack(fill="both", expand=True)
    #     self.current_frame = frame

    def show_wildberries_fbs(self):
        self._clear_content()
        frame = FBSModeWB(
            self.content_frame, self.font_normal, self.context
        )
        frame.pack(fill="both", expand=True)
        self.current_frame = frame

    def show_ozon_fbs(self):
        self._clear_content()
        frame = FBSModeOzon(
            self.content_frame, self.font_normal, self.context
        )
        frame.pack(fill="both", expand=True)
        self.current_frame = frame

    def show_settings(self):
        self._clear_content()
        frame = SettingsMode(self.content_frame,
                             self.font_normal, self.context)
        frame.pack(fill="both", expand=True)
        self.current_frame = frame

    # Метод переключения
    def show_reports_page(self):
        self._clear_content()
        frame = ReportsMode(self.content_frame,
                             self.font_normal, self.db_manager, self.context)
        frame.pack(fill="both", expand=True)
        self.current_frame = frame
    def show_kiz_directory_page(self):
        """Переключение на просмотр базы данных из SQL"""
        self._clear_content()

        # Создаем фрейм. Передаем self.db_manager
        frame = KizDirectoryMode(self.content_frame,
                             self.font_normal, self.db_manager)
        frame.pack(fill="both", expand=True)
        self.current_frame = frame

    def show_db_viewer_page(self):
        """Переключение на просмотр базы данных из SQL"""
        self._clear_content()

        # Создаем фрейм. Передаем self.db_manager
        frame = DBViewerMode(self.content_frame,
                             self.font_normal, self.db_manager)
        frame.pack(fill="both", expand=True)
        self.current_frame = frame

    def on_close(self):
        # Сохраняем данные из текущего экрана, если есть метод save_data_to_context
        if self.current_frame and hasattr(self.current_frame, 'save_data_to_context'):
            try:
                self.current_frame.save_data_to_context()
            except Exception as e:
                logging.info(f"[on_close] Ошибка при сохранении данных экрана: {e}")
        if self.has_unsaved_changes():
            answer = messagebox.askyesnocancel(
                "Несохраненные изменения",
                "В изначальную базу данных в Excel файле были внесены изменения.\n"
                "Хотите ли вы сохранить их в файле?"
            )
            if answer == True:
                self.save_df_to_excel()
            elif answer == None:
                return

        # self.save_df_to_excel_cis()
        self.save_config()
        self.context.save_to_file(CONTEXT_FILE)
        self.root.destroy()

    def has_unsaved_changes(self):
        if self.context.df is None or self.df_original is None:
            return False

        try:
            df1 = self.df_original
            df2 = self.context.df

            # Оставляем только общие столбцы
            common_cols = sorted(set(df1.columns) & set(df2.columns))
            df1 = df1[common_cols]
            df2 = df2[common_cols]

            # Приводим все значения к строкам, заменяем NaN, None и т.п. на ''
            df1_str = df1.astype(str).replace(
                ['nan', 'NaN', 'None', 'none', 'null', ''], '', regex=False)
            df2_str = df2.astype(str).replace(
                ['nan', 'NaN', 'None', 'none', 'null', ''], '', regex=False)

            # Сбрасываем индексы
            df1_str.reset_index(drop=True, inplace=True)
            df2_str.reset_index(drop=True, inplace=True)

            # Сравниваем как строки
            return not df1_str.equals(df2_str)

        except Exception as e:
            logging.error(f"[Ошибка] {e}")
            return True  # На всякий случай считаем, что изменения есть
