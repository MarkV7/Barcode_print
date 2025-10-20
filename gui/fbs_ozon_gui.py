from gui.fbs_wb_gui import *

class FBSModeOzon(FBSModeWB):
    """
    Виджет для сборки заказов Wildberries (FBS).
    Включает логику сканирования, ручной сборки, создания поставки и печати этикеток.
    """

    def __init__(self, parent, font, app_context):
        super().__init__(parent, font, app_context)
        self.pattern = r'^WB-GI-[0-9]+$'
        self.marketplace = 'Ozon'