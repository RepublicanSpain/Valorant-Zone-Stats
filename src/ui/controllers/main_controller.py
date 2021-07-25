from PySide2.QtCore import QObject, Slot, Signal, SignalInstance, QSettings

from threading import Thread
from typing import Optional, List, Tuple

from src.ui.views.main_view import MainView
from src.models.models import PlayerData, Match
from src.services.services import ApiService, MatchService, MapService, AnalyticsService
from src.utils import get_executable_relative_path
from src.ui.controllers.general_tab.general_controller import GeneralController
from src.ui.controllers.map_tab.map_controller import MapController
from src.ui.controllers.map_tab.map_list_controller import MapListController
from src.ui.controllers.map_tab.map_filters_controller import MapFiltersController
from src.ui.controllers.map_tab.map_analytics_controller import MapAnalyticsController


class AnalyzeMatchesWorker(QObject):
    progress: SignalInstance = Signal(float)
    result: SignalInstance = Signal()
    finished: SignalInstance = Signal()

    def __init__(self, matches: List[Match], analytics_service: AnalyticsService, puuid: str):
        super().__init__(None)
        self.matches: List[Match] = matches
        self.analytics_service: AnalyticsService = analytics_service
        self.puuid: str = puuid
        self.thread: Optional[Thread] = None

    def start(self):
        self.thread = Thread(target=self.run)
        self.thread.start()

    def run(self):
        self.analytics_service.analyze_and_store(self.matches, self.puuid)
        self.result.emit()
        self.finished.emit()


class MainController(QObject):

    def __init__(self, main_view: MainView):
        super().__init__()

        self.player_data: PlayerData = PlayerData()
        self.settings: QSettings = QSettings(get_executable_relative_path('settings.ini'), QSettings.IniFormat)
        self._init_settings()

        self.main_view: MainView = main_view
        self.main_view.set_player_data(self.player_data)
        self.main_view.set_map_tab_enabled(False)
        self.main_view.tabs.currentChanged.connect(self.on_tab_changed)

        self._init_services()
        self._init_controllers()

    def _init_settings(self):
        if not self.settings.contains('region'):
            self.settings.setValue('region', ApiService.get_regions()[0])

    def _init_controllers(self):
        self._init_general_controller()
        self._init_map_controller()
        self._init_map_list_controller()
        self._init_map_filters_controller()
        self._init_map_analytics_controller()

    def _init_general_controller(self):
        self.general_controller: GeneralController = GeneralController(self.main_view.general_tab,
                                                                       player_data=self.player_data,
                                                                       api_service=self.api_service,
                                                                       match_service=self.match_service,
                                                                       settings=self.settings)
        self.general_controller.matches_fetched.connect(self.on_matches_fetched)
        self.general_controller.region_changed.connect(self.on_region_changed)

    def _init_map_controller(self):
        self.map_controller: MapController = MapController(self.main_view.map_tab.map_canvas)

    def _init_map_list_controller(self):
        self.map_list_controller: MapListController = MapListController(self.main_view.map_tab.map_list_view,
                                                                        self.map_service)
        self.map_list_controller.map_selected.connect(self.draw_stats)

    def _init_map_filters_controller(self):
        self.map_filters_controller: MapFiltersController = MapFiltersController(
            self.main_view.map_tab.map_filters_view)
        self.map_filters_controller.player_side_changed.connect(self.draw_stats)

    def _init_map_analytics_controller(self):
        self.map_analytics_controller: MapAnalyticsController = MapAnalyticsController(
            self.main_view.map_tab.map_analytics_view)

    def _init_services(self):
        self.api_service: ApiService = ApiService(self.settings.value('region', ApiService.get_regions()[0]))
        self.match_service: MatchService = MatchService(self.api_service)

        self.map_service: MapService = MapService()
        self.map_service.load_maps()

        self.analytics_service: AnalyticsService = AnalyticsService(self.match_service, self.map_service)

    def draw_stats(self):
        current_map_id: str = self.map_service.get_map_names()[self.map_list_controller.get_current_map_display_name()]
        is_analyzed: bool = self.analytics_service.is_analyzed()

        if is_analyzed:
            stats: Tuple = self.analytics_service.get_map_side_stats(
                map_id=current_map_id,
                side=self.map_filters_controller.get_side()
            )
            self.map_controller.store_map_stats(
                self.map_service.get_map(current_map_id), *stats
            )
            self.map_analytics_controller.show_analytics(self.analytics_service.get_map_analytics(current_map_id))
        else:
            self.map_controller.store_map_stats(self.map_service.get_map(current_map_id), None, None)

        self.map_controller.render_map_zones(with_stats=is_analyzed)

    @Slot()
    def on_matches_fetched(self):
        def on_finish_analysis():
            self.worker.thread.join()
            self.worker.deleteLater()
            del self.worker
            self.main_view.set_map_tab_enabled(True)
            self.player_data.unload_info_from_matches()

        self.worker = AnalyzeMatchesWorker(self.player_data.available_matches, self.analytics_service,
                                           self.api_service.puuid)
        self.worker.result.connect(self.draw_stats)
        self.worker.finished.connect(on_finish_analysis)
        self.worker.start()

    @Slot(str)
    def on_region_changed(self, region: str):
        self.settings.setValue('region', region)
        self.api_service.set_region(region)

    @Slot(int)
    def on_tab_changed(self, tab_index: int):
        if tab_index == self.main_view.map_tab_id:
            self.draw_stats()

    def show(self):
        self.main_view.show()
