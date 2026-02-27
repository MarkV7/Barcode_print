import pandas as pd
import os
import json
import pickle

class AppContext:
    def __init__(self):
        self.df: pd.DataFrame = None  # Данные из Excel -> готовим к удалению
        self.df_barcode_WB: pd.DataFrame = None  # Данные из Excel -> готовим к удалению
        self.file_path: str = None   # Путь к файлу
        self.file_path2: str = None  # Путь к файлу База штрихкодов WB
        self.return_table_df: pd.DataFrame = None  # Таблица возврата
        self.fbo_table_ozon: pd.DataFrame = None
        self.fbo_table_wb: pd.DataFrame = None
        self.fbs_table: pd.DataFrame = None  # Таблица FBS сборки WB
        self.fbs_table_ozon: pd.DataFrame = None  # Таблица FBS сборки Ozon
        self.ozon_fbs_order_id = ''
        self.wb_fbs_supply_id = ''
        self.printer_name: str = 'по умолчанию'
        self.wb_api_token: str = ''
        self.ozon_client_id: str = ''
        self.ozon_api_key: str = ''


    def save_to_file(self, filepath: str):
        """
        Сохраняет контекст приложения в файл.
        Поддерживает форматы: .pkl (pickle) или .json
        """
        data = {
            "printer_name": self.printer_name,
            "wb_api_token": self.wb_api_token,
            "ozon_client_id": self.ozon_client_id,
            "ozon_api_key": self.ozon_api_key,
            "df": self.df.to_dict(orient='records') if isinstance(self.df, pd.DataFrame) else None,
            "df_barcode_WB": self.df.to_dict(orient='records') if isinstance(self.df_barcode_WB, pd.DataFrame) else None,
            "file_path": self.file_path,
            "file_path2": self.file_path2,
            "return_table_df": self.return_table_df.to_dict(orient='records') if isinstance(self.return_table_df, pd.DataFrame) else None,
            "fbo_table_ozon": self.fbo_table_ozon.to_dict(orient='records') if isinstance(self.fbo_table_ozon, pd.DataFrame) else None,
            "fbo_table_wb": self.fbo_table_wb.to_dict(orient='records') if isinstance(self.fbo_table_wb, pd.DataFrame) else None,
            "fbs_table": self.fbs_table.to_dict(orient='records') if isinstance(self.fbs_table, pd.DataFrame) else None,
            "fbs_table_ozon": self.fbs_table_ozon.to_dict(orient='records') if isinstance(self.fbs_table_ozon, pd.DataFrame) else None,
            "ozon_fbs_order_id": getattr(self, "ozon_fbs_order_id", ""),
            "wb_fbs_supply_id": getattr(self, "wb_fbs_supply_id", "")
        }
        if filepath.endswith(".pkl"):
            with open(filepath, "wb") as f:
                pickle.dump(data, f)
            print(f"✅ Контекст успешно сохранён в {filepath} (формат: pickle)")
            # self.save_df_to_parquet()
        elif filepath.endswith(".json"):
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            print(f"✅ Контекст успешно сохранён в {filepath} (формат: json)")
            # self.save_df_to_parquet()
        else:
            raise ValueError("Неподдерживаемый формат файла. Используйте .pkl или .json")

    def load_from_file(self, filepath: str):
        """
        Загружает контекст приложения из файла (.pkl или .json)
        """
        try:
            _, ext = os.path.splitext(filepath)
            if ext == ".pkl":
                with open(filepath, "rb") as f:
                    data = pickle.load(f)
            elif ext == ".json":
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                raise ValueError("Неподдерживаемый формат файла. Используйте .pkl или .json")

            # Восстанавливаем поля
            self.printer_name = data.get("printer_name", "по умолчанию")
            self.wb_api_token = data.get("wb_api_token", "")
            self.ozon_client_id = data.get("ozon_client_id", "")
            self.ozon_api_key = data.get("ozon_api_key", "")
            self.file_path = data.get("file_path", None)
            self.file_path2 = data.get("file_path2", None)
            self.df = pd.DataFrame(data["df"]) if data.get("df") else None
            self.df_barcode_WB = pd.DataFrame(data["df_barcode_WB"]) if data.get("df_barcode_WB") else None
            self.return_table_df = pd.DataFrame(data["return_table_df"]) if data.get("return_table_df") else None
            self.fbo_table_ozon = pd.DataFrame(data["fbo_table_ozon"]) if data.get("fbo_table_ozon") else None
            self.fbo_table_wb = pd.DataFrame(data["fbo_table_wb"]) if data.get("fbo_table_wb") else None
            self.fbs_table = pd.DataFrame(data["fbs_table"]) if data.get("fbs_table") else None
            self.fbs_table_ozon = pd.DataFrame(data["fbs_table_ozon"]) if data.get("fbs_table_ozon") else None
            self.ozon_fbs_order_id = data.get("ozon_fbs_order_id", "")
            self.wb_fbs_supply_id = data.get("wb_fbs_supply_id", "")

            print(f"✅ Контекст успешно загружен из {filepath}")
        except Exception as e:
            print(f"❌ Ошибка при загрузке контекста: {e}")
