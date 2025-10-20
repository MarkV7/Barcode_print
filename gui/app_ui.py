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
from gui.fbs_autosborka_gui import FBSMode
from gui.fbs_wb_gui import FBSModeWB
from gui.fbs_ozon_gui import FBSModeOzon

CONFIG_FILE = "config.json"
CONTEXT_FILE = 'app_context.pkl'

ctk.set_appearance_mode("System")  # или "Light"
ctk.set_default_color_theme("blue")


class AppUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Склад Ozon / Wildberries")
        self.root.geometry("1600x600")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

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
            ("База данных", self.show_database),
            ("Возврат на склад", self.show_return),
            ("ФБО Ozon", self.show_ozon),
            ("ФБО Wildberries", self.show_wildberries),
            #("Автосборка ФБС", self.show_autosborka_fbs),
            ("Wildberries ФБС", self.show_wildberries_fbs),
            ("Ozon ФБС", self.show_ozon_fbs),
            ("Настройки", self.show_settings),
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

        # Теперь можно безопасно вызвать show_database()
        self.show_database()

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
                print(f"✅ Данные успешно сохранены в {self.context.file_path}")
            except Exception as e:
                print(f"❌ Ошибка при сохранении файла: {e}")
        else:
            print("⚠️ Нет данных для сохранения или не указан путь к файлу")

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
        if self.current_frame:
            self.current_frame.pack_forget()

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

    def show_autosborka_fbs(self):
        self._clear_content()
        frame = FBSMode(
            self.content_frame, self.font_normal, self.context
        )
        frame.pack(fill="both", expand=True)
        self.current_frame = frame

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

    def on_close(self):
        # Сохраняем данные из текущего экрана, если есть метод save_data_to_context
        if self.current_frame and hasattr(self.current_frame, 'save_data_to_context'):
            try:
                self.current_frame.save_data_to_context()
            except Exception as e:
                print(f"[on_close] Ошибка при сохранении данных экрана: {e}")
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
            print(f"[Ошибка] {e}")
            return True  # На всякий случай считаем, что изменения есть
