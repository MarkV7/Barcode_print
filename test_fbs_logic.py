import unittest
import pandas as pd
from unittest.mock import MagicMock, patch, call, PropertyMock
import sys
from typing import List, Dict
import logging

# Отключаем логирование, чтобы оно не мешало выводу на консоль
logging.getLogger().setLevel(logging.CRITICAL)

# --------------------------------------------------------------------
# 1. Загрузка тестируемого модуля
# --------------------------------------------------------------------
try:
    from gui.fbs_autosborka_gui import FBSMode, OrderAssemblyState

    CTK_FONT_PATCH_PATH = 'gui.fbs_autosborka_gui.ctk.CTkFont'
except ImportError:
    class MockFBSMode:
        pass


    class MockOrderAssemblyState:
        def __init__(self, *args, **kwargs): pass


    FBSMode = MockFBSMode
    OrderAssemblyState = MockOrderAssemblyState
    CTK_FONT_PATCH_PATH = 'gui.fbs_autosborka_gui.ctk.CTkFont'
    print("ВНИМАНИЕ: Не удалось импортировать FBSMode. Используются заглушки.")


# --------------------------------------------------------------------
# 2. МОК-ОБЪЕКТЫ
# --------------------------------------------------------------------

class MockWildberriesFBSAPI:
    """Имитация WildberriesFBSAPI. Методы определены как MagicMock-атрибуты."""

    def __init__(self, api_token):
        self.api_token = api_token
        self.create_supply = MagicMock(return_value={'id': 1234567, 'name': 'MockSupply'})
        self.add_orders_to_supply = MagicMock(return_value={'result': True})
        self.get_stickers = MagicMock(return_value={'stickers': [{'file': 'WB_ZPL_LABEL_BASE64_DATA'}]})


class MockOzonFBSAPI:
    """Имитация OzonFBSAPI. Методы определены как MagicMock-атрибуты."""

    def __init__(self, client_id, api_key):
        self.client_id = client_id
        self.api_key = api_key
        # Мокируем set_posting_state_to_assembly, который должен быть вызван первым
        self.set_posting_state_to_assembly = MagicMock(return_value={'result': True})
        self.to_assembly_with_cis = MagicMock(return_value={'result': True})
        self.get_stickers = MagicMock(return_value={'result': {'pdf': 'OZON_PDF_LABEL_BASE64_DATA'}})


class MockLabelPrinter:
    """Имитация LabelPrinter."""

    def __init__(self, printer_name):
        self.printer_name = printer_name
        self.print_wb_ozon_label = MagicMock(return_value=True)


class MockAppContext:
    """Имитация AppContext с необходимыми настройками"""

    def __init__(self):
        self.wb_api_token = "mock_wb_token"
        self.ozon_client_id = "mock_ozon_client"
        self.ozon_api_key = "mock_ozon_key"
        self.printer_ip = "192.168.1.100"
        self.printer_port = 9100
        self.printer_name = "Mock_XPrinter_365B"
        self.wb_fbs_supply_id = 1234567
        self.df = pd.DataFrame({"Артикул производителя": ["A1"], "Размер": ["S"], "Штрихкод_товара": ["WB_BARCODE_1"]})


# --------------------------------------------------------------------
# 3. ТЕСТИРУЕМЫЙ КЛАСС (с применением моков)
# --------------------------------------------------------------------

@patch('gui.fbs_autosborka_gui.WildberriesFBSAPI', MockWildberriesFBSAPI)
@patch('gui.fbs_autosborka_gui.LabelPrinter', MockLabelPrinter)
@patch('gui.fbs_autosborka_gui.OzonFBSAPI', MockOzonFBSAPI)
@patch(CTK_FONT_PATCH_PATH, MagicMock)
@patch('gui.fbs_autosborka_gui.ctk.CTkFrame', MagicMock)
@patch('gui.fbs_autosborka_gui.play_success_scan_sound', MagicMock)
@patch('gui.fbs_autosborka_gui.play_unsuccess_scan_sound', MagicMock)
@patch('gui.fbs_autosborka_gui.EditableDataTable', MagicMock)
@patch('gui.fbs_autosborka_gui.messagebox.askyesno', MagicMock(return_value=True))
@patch('gui.fbs_autosborka_gui.messagebox.showerror', MagicMock)
class FBSModeTest(unittest.TestCase):

    def setUp(self):
        """Настройка перед каждым тестом. Включает обход конструктора GUI."""
        print("\n" + "=" * 50)
        print("--- НАЧАЛО НАСТРОЙКИ ТЕСТА ---")

        self.context = MockAppContext()

        # 1. Патчим конструктор ctk.CTkFrame
        try:
            self.parent_init_patch = patch.object(FBSMode.__bases__[0], '__init__', MagicMock(return_value=None))
            self.parent_init_patch.start()
            print("Стадия: ctk.CTkFrame.__init__ успешно заглушен.")
        except Exception as e:
            print(f"ВНИМАНИЕ: Не удалось заглушить ctk.CTkFrame.__init__: {e}")

        # 2. Патчим setup_ui на уровне класса
        self.setup_ui_patch = patch.object(FBSMode, 'setup_ui', MagicMock())
        self.setup_ui_patch.start()
        print("Стадия: FBSMode.setup_ui успешно заглушен.")

        # 3. Создаем экземпляр.
        self.fbs_instance = FBSMode(MagicMock(), MagicMock(), self.context)
        print("Стадия: Экземпляр FBSMode создан.")

        # 4. ПРИНУДИТЕЛЬНОЕ ПРИСВОЕНИЕ МОК-ОБЪЕКТОВ
        self.fbs_instance.api_wb = MockWildberriesFBSAPI(self.context.wb_api_token)
        self.fbs_instance.api_ozon = MockOzonFBSAPI(self.context.ozon_client_id, self.context.ozon_api_key)
        self.fbs_instance.label_printer = MockLabelPrinter(self.context.printer_name)

        # Инициализация необходимых переменных состояния
        self.fbs_instance.ozon_assemblies = {}
        self.fbs_instance.fbs_df = pd.DataFrame()
        self.fbs_instance.active_ozon_assembly = None
        self.fbs_instance.selected_row_index = None  # Инициализируем None

        # Мокируем оставшиеся методы
        self.fbs_instance.start_auto_focus = MagicMock()
        self.fbs_instance.show_log = MagicMock()
        self.fbs_instance.update_table = MagicMock()
        self.fbs_instance.save_data_to_context = MagicMock()
        self.fbs_instance.load_orders = MagicMock()

        print("--- НАСТРОЙКА ЗАВЕРШЕНА ---")

    def tearDown(self):
        """Очистка после каждого теста."""
        # Обязательно останавливаем все патчи!
        try:
            self.parent_init_patch.stop()
            self.setup_ui_patch.stop()
        except AttributeError:
            pass
        print("--- ОЧИСТКА ВЫПОЛНЕНА ---")
        print("=" * 50)

    # ----------------------------------------------------------------
    # ТЕСТИРОВАНИЕ ЛОГИКИ WILDHBERRIES
    # ----------------------------------------------------------------
    def test_finalize_wb_assembly_success(self):
        print("ТЕСТ: test_finalize_wb_assembly_success (WB Финализация)")
        row_data = {
            "Маркетплейс": "Wildberries",
            "Номер заказа": 10001,
            "Код маркировки": "KI_Z_CODE_001",
            "ID сборочного задания": 9876543
        }

        self.fbs_instance.finalize_wb_assembly(row_data)

        # 1. Проверка API: Получение стикера (тип ZPL)
        self.fbs_instance.api_wb.get_stickers.assert_called_once_with(
            [10001], type="zpl", width=58, height=40
        )
        print("    [ОК] 1. WB API get_stickers вызван с правильными параметрами.")

        # 2. Проверка Печати: Должен быть вызван метод ZPL печати
        self.fbs_instance.label_printer.print_wb_ozon_label.assert_called_once_with(
            'WB_ZPL_LABEL_BASE64_DATA', '192.168.1.100'
        )
        print("    [ОК] 2. LabelPrinter print_wb_ozon_label вызван с данными ZPL.")

        # 3. Проверка лога
        self.fbs_instance.show_log.assert_called()
        print("    [ОК] 3. show_log вызван.")
        print("ТЕСТ: test_finalize_wb_assembly_success успешно завершен. ✅")

    # ----------------------------------------------------------------
    # ТЕСТИРОВАНИЕ ЛОГИКИ OZON
    # ----------------------------------------------------------------
    def test_finalize_ozon_assembly_success(self):
        print("ТЕСТ: test_finalize_ozon_assembly_success (Ozon Финализация)")
        POSTING_NUMBER = "P123456"
        # Возвращаем к строковому типу, чтобы избежать проблем с сериализацией API
        OZON_PRODUCT_ID_MARKED = '1001'
        OZON_PRODUCT_ID_UNMARKED = '1002'

        # 1. Mock the main DataFrame (fbs_df) - Необходим для поиска заказа
        self.fbs_instance.fbs_df = pd.DataFrame([{
            "Маркетплейс": "Ozon",
            "Номер заказа": POSTING_NUMBER,
            "ID сборочного задания": 9999,
            "Статус": "awaiting_packaging"
        }])

        # Устанавливаем выбранный индекс строки (имитация клика в GUI)
        self.fbs_instance.selected_row_index = 0

        # 2. Имитируем состояние активной сборки (с маркировкой)
        assembly_state = OrderAssemblyState(POSTING_NUMBER, [
            {'product_id': OZON_PRODUCT_ID_MARKED, 'name': 'Т1', 'quantity': 1, 'is_marked': True},
            {'product_id': OZON_PRODUCT_ID_UNMARKED, 'name': 'Т2', 'quantity': 1, 'is_marked': False}
        ])

        # 3. Полностью имитируем сканирование и финализацию данных
        for p in assembly_state.products:
            p['is_processed'] = True
            p['scanned_barcode'] = 'MOCK_BARCODE_X'
            if p['is_marked']:
                p['scanned_cis'] = 'MOCK_CIS_X'

        # 4. Устанавливаем флаг завершенности
        assembly_state.is_complete = True

        # 5. Устанавливаем состояние в экземпляре FBSMode
        self.fbs_instance.ozon_assemblies[POSTING_NUMBER] = assembly_state
        self.fbs_instance.active_ozon_assembly = assembly_state

        self.fbs_instance.finalize_ozon_assembly(POSTING_NUMBER)

        # 1. Проверяем вызов to_assembly_with_cis (для маркированного товара)
        self.fbs_instance.api_ozon.to_assembly_with_cis.assert_called_once_with(
            posting_number=POSTING_NUMBER,
            products=[
                # product_id теперь строковый
                {'product_id': OZON_PRODUCT_ID_MARKED, 'cis': ['MOCK_CIS_X']}
            ]
        )
        print("    [ОК] 1. Ozon API to_assembly_with_cis вызван с правильными параметрами.")

        # Проверяем, что set_posting_state_to_assembly не был вызван
        self.fbs_instance.api_ozon.set_posting_state_to_assembly.assert_not_called()

        # 2. Проверка API: Получение стикера Ozon
        self.fbs_instance.api_ozon.get_stickers.assert_called_once_with(
            posting_number=POSTING_NUMBER
        )
        print("    [ОК] 2. Ozon API get_stickers вызван.")

        # 3. Проверка Печати
        self.fbs_instance.label_printer.print_wb_ozon_label.assert_called_once_with(
            'OZON_PDF_LABEL_BASE64_DATA', '192.168.1.100'
        )
        print("    [ОК] 3. LabelPrinter print_wb_ozon_label вызван с данными Ozon.")

        print("ТЕСТ: test_finalize_ozon_assembly_success успешно завершен. ✅")


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.TestLoader().loadTestsFromTestCase(FBSModeTest)
    runner.run(suite)