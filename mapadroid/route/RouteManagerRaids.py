from typing import List, Optional

from mapadroid.db.DbWrapper import DbWrapper
from mapadroid.db.model import SettingsAreaRaidsMitm, SettingsRoutecalc
from mapadroid.geofence.geofenceHelper import GeofenceHelper
from mapadroid.route.RouteManagerBase import RouteManagerBase
from mapadroid.utils.logging import LoggerEnums, get_logger
from mapadroid.worker.WorkerType import WorkerType

logger = get_logger(LoggerEnums.routemanager)


class RouteManagerRaids(RouteManagerBase):
    def __init__(self, db_wrapper: DbWrapper, area: SettingsAreaRaidsMitm, coords, max_radius, max_coords_within_radius,
                 geofence_helper: GeofenceHelper, routecalc: SettingsRoutecalc,
                 joinqueue=None, use_s2: bool = False, s2_level: int = 15, mon_ids_iv: Optional[List[int]] = None):
        RouteManagerBase.__init__(self, db_wrapper=db_wrapper, area=area, coords=coords,
                                  max_radius=max_radius,
                                  max_coords_within_radius=max_coords_within_radius,
                                  geofence_helper=geofence_helper,
                                  routecalc=routecalc, use_s2=use_s2, s2_level=s2_level,
                                  joinqueue=joinqueue, mon_ids_iv=mon_ids_iv
                                  )
        self._settings: SettingsAreaRaidsMitm = area
        self.remove_from_queue_backlog = area.remove_from_queue_backlog
        self.delay_after_timestamp_prio = area.delay_after_prio_event
        self.starve_route = area.starve_route
        self.init_mode_rounds = area.init_mode_rounds
        self.init = area.init

    def _priority_queue_update_interval(self):
        return 300

    def _get_coords_after_finish_route(self):
        self._init_route_queue()
        return True

    def _recalc_route_workertype(self):
        self.recalc_route(self._max_radius, self._max_coords_within_radius, 1, delete_old_route=True,
                          in_memory=False)
        self._init_route_queue()

    def _retrieve_latest_priority_queue(self):
        # TODO: pass timedelta for timeleft on raids that can be ignored.
        # e.g.: a raid only has 5mins to go, ignore those
        return self.db_wrapper.get_next_raid_hatches(self.geofence_helper)

    def _delete_coord_after_fetch(self) -> bool:
        return False

    def _get_coords_post_init(self):
        # TODO: GymHelper.get_locations_in_fence
        coords = self.db_wrapper.gyms_from_db(self.geofence_helper)
        if self._settings.including_stops:
            self.logger.info("Include stops in coords list too!")
            coords.extend(self.db_wrapper.stops_from_db(self.geofence_helper))

        return coords

    def _cluster_priority_queue_criteria(self) -> float:
        return self._settings.priority_queue_clustering_timedelta \
            if self._settings.priority_queue_clustering_timedelta is not None else 600

    def _start_routemanager(self):
        with self._manager_mutex:
            if not self._is_started:
                self._is_started = True
                self.logger.info("Starting routemanager")
                if self._mode != WorkerType.IDLE:
                    self._start_priority_queue()
                    self._start_check_routepools()
                    self._init_route_queue()
        return True

    def _quit_route(self):
        self.logger.info("Shutdown Route")
        self._is_started = False
        self._round_started_time = None

    def _check_coords_before_returning(self, lat, lng, origin):
        return True

    async def _change_init_mapping(self) -> None:
        self._settings.init = False
        # TODO: Add or merge? Or first fetch the data? Or just toggle using the helper?
        await session.merge(self._settings)
