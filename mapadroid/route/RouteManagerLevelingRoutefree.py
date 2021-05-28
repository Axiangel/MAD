from typing import List, Optional

from mapadroid.db.DbWrapper import DbWrapper
from mapadroid.db.helper.PokestopHelper import PokestopHelper
from mapadroid.db.helper.SettingsDeviceHelper import SettingsDeviceHelper
from mapadroid.db.model import SettingsAreaPokestop, SettingsRoutecalc, Pokestop
from mapadroid.geofence.geofenceHelper import GeofenceHelper
from mapadroid.route.RouteManagerBase import RoutePoolEntry
from mapadroid.route.RouteManagerLeveling import RouteManagerLeveling
from mapadroid.utils.collections import Location
from mapadroid.utils.logging import LoggerEnums, get_logger

logger = get_logger(LoggerEnums.routemanager)


class RouteManagerLevelingRoutefree(RouteManagerLeveling):
    def __init__(self, db_wrapper: DbWrapper, area: SettingsAreaPokestop, coords: Optional[List[Location]],
                 max_radius: int, max_coords_within_radius: int,
                 geofence_helper: GeofenceHelper, routecalc: SettingsRoutecalc,
                 joinqueue=None, mon_ids_iv: Optional[List[int]] = None):
        # TODO: Verify... used to be quests directly
        RouteManagerLeveling.__init__(self, db_wrapper=db_wrapper, area=area, coords=coords,
                                      max_radius=max_radius, max_coords_within_radius=max_coords_within_radius,
                                      geofence_helper=geofence_helper, routecalc=routecalc,
                                      joinqueue=joinqueue, mon_ids_iv=mon_ids_iv
                                      )
        self._level = True
        self.init = area.init

    async def _worker_changed_update_routepools(self):
        with self._manager_mutex and self._workers_registered_mutex:
            self.logger.info("Updating all routepools in level mode for {} origins", len(self._routepool))
            if len(self._workers_registered) == 0:
                self.logger.info("No registered workers, aborting __worker_changed_update_routepools...")
                return False

            any_at_all = False
            async with self.db_wrapper as session:
                for origin in self._routepool:
                    origin_local_list = []
                    entry: RoutePoolEntry = self._routepool[origin]

                    if len(entry.queue) > 0:
                        self.logger.debug("origin {} already has a queue, do not touch...", origin)
                        continue
                    current_worker_pos = entry.current_pos
                    unvisited_stops: List[Pokestop] = await PokestopHelper.get_nearby_increasing_range_within_area(
                        session,
                        geofence_helper=self.geofence_helper,
                        origin=origin,
                        location=current_worker_pos,
                        limit=30,
                        ignore_spinned=self._settings.ignore_spinned_stops,
                        max_distance=5)
                    if not unvisited_stops:
                        self.logger.info("There are no unvisited stops left in DB for {} - nothing more to do!", origin)
                        continue

                    for stop in unvisited_stops:
                        coord_location = Location(stop.latitude, stop.longitude)
                        if coord_location in self._coords_to_be_ignored:
                            self.logger.info('Already tried this Stop but it failed spinnable test, skip it')
                            continue
                        origin_local_list.append(coord_location)

                    if unvisited_stops:
                        self.logger.info("Recalc a route")
                        new_route = self._local_recalc_subroute(unvisited_stops)
                        origin_local_list.clear()
                        for coord in new_route:
                            origin_local_list.append(Location(coord["lat"], coord["lng"]))

                    # subroute is all stops unvisited
                    self.logger.info("Origin {} has {} unvisited stops for this route", origin, len(origin_local_list))
                    entry.subroute = origin_local_list
                    # let's clean the queue just to make sure
                    entry.queue.clear()
                    [entry.queue.append(i) for i in origin_local_list]
                    any_at_all = len(origin_local_list) > 0 or any_at_all
                    # saving new startposition of walker in db
                    newstartposition: Location = entry.queue[0]
                    await SettingsDeviceHelper.save_last_walker_position(session,
                                                                         instance_id=self.db_wrapper.get_instance_id(),
                                                                         origin=origin,
                                                                         location=newstartposition)
                return True

    async def _recalc_route_workertype(self):
        await self.recalc_route(self._max_radius, self._max_coords_within_radius, 1, delete_old_route=False,
                                in_memory=True)
        self._init_route_queue()

    async def _get_coords_after_finish_route(self) -> bool:
        with self._manager_mutex:
            if self._shutdown_route:
                self.logger.info('Other worker shutdown route - leaving it')
                return False

            await self._worker_changed_update_routepools()
            self._start_calc = False
            return True

    def _check_unprocessed_stops(self):
        with self._manager_mutex:
            # We finish routes on a per walker/origin level, so the route itself is always the same as long as at
            # least one origin is connected to it.
            return self._stoplist

    async def _start_routemanager(self):
        with self._manager_mutex:
            if not self._is_started:
                self._is_started = True
                self.logger.info("Starting routemanager")

                if self._shutdown_route:
                    self.logger.info('Other worker shutdown route - leaving it')
                    return False

                self._prio_queue = None
                self.delay_after_timestamp_prio = None
                self.starve_route = False
                await self._start_check_routepools()

                return True
        return True

    async def _recalc_stop_route(self, stops):
        self._clear_coords()
        self.add_coords_list(stops)
        self._overwrite_calculation = True
        await self._recalc_route_workertype()
        self._init_route_queue()

    def _quit_route(self):
        self.logger.info('Shutdown Route')
        if self._is_started:
            self._is_started = False
            self._round_started_time = None
            if self.init:
                self._first_started = False
            self._shutdown_route = False

        # clear not processed stops
        self._stops_not_processed.clear()
        self._coords_to_be_ignored.clear()
        self._stoplist.clear()

    def _check_coords_before_returning(self, lat, lng, origin):
        if self.init:
            self.logger.debug('Init Mode - coord is valid')
            return True
        stop = Location(lat, lng)
        self.logger.info('Checking Stop with ID {}', stop)
        if stop in self._coords_to_be_ignored:
            self.logger.info('Already tried this Stop and failed it')
            return False
        self.logger.info('DB knows nothing of this stop for {} lets try and go there', origin)
        return True
