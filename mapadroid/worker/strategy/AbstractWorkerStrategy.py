import asyncio
import os
import time
from abc import ABC, abstractmethod
from typing import Optional, Any, List, Tuple

from loguru import logger

from mapadroid.data_handler.MitmMapper import MitmMapper
from mapadroid.db.DbWrapper import DbWrapper
from mapadroid.db.helper.TrsStatusHelper import TrsStatusHelper
from mapadroid.db.model import SettingsWalkerarea, SettingsArea
from mapadroid.geofence.geofenceHelper import GeofenceHelper
from mapadroid.mapping_manager.MappingManager import MappingManager
from mapadroid.mapping_manager.MappingManagerDevicemappingKey import MappingManagerDevicemappingKey
from mapadroid.ocr.pogoWindows import PogoWindows
from mapadroid.ocr.screenPath import WordToScreenMatching
from mapadroid.ocr.screen_type import ScreenType
from mapadroid.utils.collections import Location, ScreenCoordinates
from mapadroid.utils.geo import get_distance_of_two_points_in_meters, get_lat_lng_offsets_by_distance
from mapadroid.utils.madConstants import WALK_AFTER_TELEPORT_SPEED
from mapadroid.utils.madGlobals import InternalStopWorkerException, application_args, PositionType, \
    WebsocketWorkerRemovedException, TransportType, ScreenshotType
from mapadroid.websocket.AbstractCommunicator import AbstractCommunicator
from mapadroid.worker.WorkerState import WorkerState


class AbstractWorkerStrategy(ABC):
    def __init__(self, area_id: int, communicator: AbstractCommunicator,
                 mapping_manager: MappingManager,
                 db_wrapper: DbWrapper, word_to_screen_matching: WordToScreenMatching,
                 pogo_windows_handler: PogoWindows,
                 walker: SettingsWalkerarea,
                 worker_state: WorkerState):
        self._area_id: int = area_id
        self._mapping_manager: MappingManager = mapping_manager
        self._communicator: AbstractCommunicator = communicator
        self._db_wrapper: DbWrapper = db_wrapper
        self._word_to_screen_matching: WordToScreenMatching = word_to_screen_matching
        self._pogo_windows_handler: PogoWindows = pogo_windows_handler
        self._walker: SettingsWalkerarea = walker
        self._worker_state: WorkerState = worker_state

    @property
    def walker(self) -> SettingsWalkerarea:
        return self._walker

    @walker.setter
    def walker(self, value: SettingsWalkerarea) -> None:
        raise RuntimeError("Replacing walker is not supported")

    @property
    def area_id(self) -> int:
        return self._area_id

    @area_id.setter
    def area_id(self, value: int) -> None:
        raise RuntimeError("Replacing area_id is not supported")

    @abstractmethod
    async def pre_work_loop(self) -> None:
        """
        Work to be done before the main while true work-loop
        Start off asyncio loops etc in here
        :return:
        """
        pass

    @abstractmethod
    async def pre_location_update(self) -> None:
        """
        Override to run stuff like update injections settings in MITM worker
        Runs before walk/teleport to the location previously grabbed
        :return:
        """
        pass

    @abstractmethod
    async def move_to_location(self) -> Tuple[int, Location]:
        """
        Location has previously been grabbed, the overridden function will be called.
        You may teleport or walk by your choosing
        Any post walk/teleport delays/sleeps have to be run in the derived, override method
        :return: Tuple consisting of timestamp of arrival and location
        """
        pass

    @abstractmethod
    async def post_move_location_routine(self, timestamp: int) -> None:
        """
        Routine called after having moved to a new location. MITM worker e.g. has to wait_for_data
        :param timestamp:
        :return:
        """
        pass

    @abstractmethod
    async def worker_specific_setup_start(self):
        """
        Routine preparing the state to scan. E.g. starting specific apps or clearing certain files
        Returns:
        """

    @abstractmethod
    async def worker_specific_setup_stop(self):
        """
        Routine destructing the state to scan. E.g. stopping specific apps or clearing certain files
        Returns:
        """

    async def grab_next_location(self) -> SettingsArea:
        logger.debug("Requesting next location from routemanager")
        # requesting a location is blocking (iv_mitm will wait for a prioQ item), we really need to clean
        # the workers up...
        if int(self._worker_state.current_sleep_duration) > 0:
            logger.info('Sleeping for {} seconds', self._worker_state.current_sleep_duration)
            await asyncio.sleep(int(self._worker_state.current_sleep_duration))
            self._worker_state.current_sleep_duration = 0

        await self._check_for_mad_job()

        self._worker_state.current_location = await self._mapping_manager.routemanager_get_next_location(
            self._area_id,
            self._worker_state.origin)
        return await self._mapping_manager.routemanager_get_settings(self._area_id)

    async def _check_for_mad_job(self):
        if await self.get_devicesettings_value(MappingManagerDevicemappingKey.JOB_ACTIVE, False):
            logger.info("Worker get a job - waiting")
            while await self.get_devicesettings_value(MappingManagerDevicemappingKey.JOB_ACTIVE,
                                                      False) and not self._worker_state.stop_worker_event.is_set():
                await asyncio.sleep(10)
            logger.info("Worker processed the job and go on ")

    async def health_check(self) -> bool:
        # check if pogo is topmost and start if necessary
        logger.debug4("_internal_health_check: Calling _start_pogo routine to check if pogo is topmost")
        pogo_started = False
        logger.debug4("Checking if we need to restart pogo")
        # Restart pogo every now and then...
        restart_pogo_setting = await self.get_devicesettings_value(MappingManagerDevicemappingKey.RESTART_POGO, 0)
        if restart_pogo_setting > 0:
            if self._worker_state.location_count > restart_pogo_setting:
                logger.info("scanned {} locations, restarting game", restart_pogo_setting)
                pogo_started = await self._restart_pogo()
                self._worker_state.location_count = 0
            else:
                pogo_started = await self.start_pogo()
        else:
            pogo_started = await self.start_pogo()

        logger.debug4("_internal_health_check: worker lock released")
        return pogo_started

    async def _walk_after_teleport(self, walk_distance_post_teleport) -> float:
        """
        Args:
            walk_distance_post_teleport:

        Returns:
            Distance walked in one way
        """
        lat_offset, lng_offset = get_lat_lng_offsets_by_distance(walk_distance_post_teleport)
        to_walk = get_distance_of_two_points_in_meters(float(self._worker_state.current_location.lat),
                                                       float(
                                                           self._worker_state.current_location.lng),
                                                       float(
                                                           self._worker_state.current_location.lat) + lat_offset,
                                                       float(self._worker_state.current_location.lng) + lng_offset)
        logger.info("Walking roughly: {:.2f}m", to_walk)
        await asyncio.sleep(0.3)
        await self._communicator.walk_from_to(self._worker_state.current_location,
                                              Location(self._worker_state.current_location.lat + lat_offset,
                                                       self._worker_state.current_location.lng + lng_offset),
                                              WALK_AFTER_TELEPORT_SPEED)
        logger.debug("Walking back")
        await asyncio.sleep(0.3)
        await self._communicator.walk_from_to(Location(self._worker_state.current_location.lat + lat_offset,
                                                       self._worker_state.current_location.lng + lng_offset),
                                              self._worker_state.current_location,
                                              WALK_AFTER_TELEPORT_SPEED)
        logger.debug("Done walking")
        return to_walk

    async def start_pogo(self) -> bool:
        """
        Routine to start pogo.
        Return the state as a boolean do indicate a successful start
        :return:
        """
        pogo_topmost = await self._communicator.is_pogo_topmost()
        if pogo_topmost:
            return True

        if not await self._communicator.is_screen_on():
            await self._communicator.start_app("de.grennith.rgc.remotegpscontroller")
            logger.info("Turning screen on")
            await self._communicator.turn_screen_on()
            await asyncio.sleep(
                await self.get_devicesettings_value(MappingManagerDevicemappingKey.POST_TURN_SCREEN_ON_DELAY, 7))

        cur_time = time.time()
        start_result = False
        attempts = 0
        while not pogo_topmost:
            attempts += 1
            if attempts > 10:
                logger.warning("_start_pogo failed 10 times")
                return False
            start_result = await self._communicator.start_app("com.nianticlabs.pokemongo")
            await asyncio.sleep(1)
            pogo_topmost = await self._communicator.is_pogo_topmost()

        if start_result:
            logger.success("startPogo: Started pogo successfully...")

        await self._wait_pogo_start_delay()
        return start_result

    async def set_devicesettings_value(self, key: MappingManagerDevicemappingKey, value: Optional[Any]):
        await self._mapping_manager.set_devicesetting_value_of(self._worker_state.origin, key, value)

    async def get_devicesettings_value(self, key: MappingManagerDevicemappingKey, default_value: Optional[Any] = None):
        logger.debug("Fetching devicemappings")
        try:
            value = await self._mapping_manager.get_devicesetting_value_of_device(self._worker_state.origin, key)
        except (EOFError, FileNotFoundError) as e:
            logger.warning("Failed fetching devicemappings with description: {}. Stopping worker", e)
            raise InternalStopWorkerException
        return value if value else default_value

    async def _wait_pogo_start_delay(self):
        delay_count: int = 0
        pogo_start_delay: int = await self.get_devicesettings_value(
            MappingManagerDevicemappingKey.POST_POGO_START_DELAY, 60)
        logger.info('Waiting for pogo start: {} seconds', pogo_start_delay)

        while delay_count <= pogo_start_delay:
            if not await self._mapping_manager.routemanager_present(self._area_id) \
                    or self._worker_state.stop_worker_event.is_set():
                logger.error("Killed while waiting for pogo start")
                raise InternalStopWorkerException
            await asyncio.sleep(1)
            delay_count += 1

    async def turn_screen_on_and_start_pogo(self):
        if not await self._communicator.is_screen_on():
            await self._communicator.start_app("de.grennith.rgc.remotegpscontroller")
            logger.info("Turning screen on")
            await self._communicator.turn_screen_on()
            await asyncio.sleep(
                await self.get_devicesettings_value(MappingManagerDevicemappingKey.POST_TURN_SCREEN_ON_DELAY, 2))
        # check if pogo is running and start it if necessary
        logger.info("turnScreenOnAndStartPogo: (Re-)Starting Pogo")
        await self.start_pogo()

    async def _ensure_pogo_topmost(self):
        logger.info('Checking pogo screen...')
        screen_type: ScreenType = ScreenType.UNDEFINED
        while not self._worker_state.stop_worker_event.is_set():
            # TODO: Make this not block the loop somehow... asyncio waiting for a thread?
            screen_type: ScreenType = await self._word_to_screen_matching.detect_screentype()
            if screen_type in [ScreenType.POGO, ScreenType.QUEST]:
                self._last_screen_type = screen_type
                self._login_error_count = 0
                logger.debug2("Found pogo or questlog to be open")
                break

            if screen_type != ScreenType.ERROR and self._last_screen_type == screen_type:
                self._same_screen_count += 1
                logger.info("Found {} multiple times in a row ({})", screen_type, self._same_screen_count)
                if self._same_screen_count > 3:
                    logger.warning("Screen is frozen!")
                    if self._same_screen_count > 4 or not await self._restart_pogo():
                        logger.warning("Restarting PoGo failed - reboot device")
                        await self._reboot()
                    break
            elif self._last_screen_type != screen_type:
                self._same_screen_count = 0

            # now handle all screens that may not have been handled by detect_screentype since that only clicks around
            # so any clearing data whatsoever happens here (for now)
            if screen_type == ScreenType.UNDEFINED:
                logger.error("Undefined screentype!")
            elif screen_type == ScreenType.BLACK:
                logger.info("Found Black Loading Screen - waiting ...")
                await asyncio.sleep(20)
            elif screen_type == ScreenType.CLOSE:
                logger.debug("screendetection found pogo closed, start it...")
                await self.start_pogo()
                self._worker_state.login_error_count += 1
            elif screen_type == ScreenType.GAMEDATA:
                logger.info('Error getting Gamedata or strange ggl message appears')
                self._worker_state.login_error_count += 1
                if self._worker_state.login_error_count < 2:
                    await self._restart_pogo_safe()
            elif screen_type == ScreenType.DISABLED:
                # Screendetection is disabled
                break
            elif screen_type == ScreenType.UPDATE:
                logger.warning(
                    'Found update pogo screen - sleeping 5 minutes for another check of the screen')
                # update pogo - later with new rgc version
                await asyncio.sleep(300)
            elif screen_type in [ScreenType.ERROR, ScreenType.FAILURE]:
                logger.warning('Something wrong with screendetection or pogo failure screen')
                self._worker_state.login_error_count += 1
            elif screen_type == ScreenType.NOGGL:
                logger.warning('Detected login select screen missing the Google'
                               ' button - likely entered an invalid birthdate previously')
                self._worker_state.login_error_count += 1
            elif screen_type == ScreenType.GPS:
                logger.warning("Detected GPS error - reboot device")
                await self._reboot()
                break
            elif screen_type == ScreenType.SN:
                logger.warning('Getting SN Screen - restart PoGo and later PD')
                await self._restart_pogo_safe()
                break
            elif screen_type == ScreenType.NOTRESPONDING:
                await self._reboot()
                break

            if self._worker_state.login_error_count > 1:
                logger.warning('Could not login again - (clearing game data + restarting device')
                await self.stop_pogo()
                await self._communicator.clear_app_cache("com.nianticlabs.pokemongo")
                if await self.get_devicesettings_value(MappingManagerDevicemappingKey.CLEAR_GAME_DATA, False):
                    logger.info('Clearing game data')
                    await self._communicator.reset_app_data("com.nianticlabs.pokemongo")
                self._login_error_count = 0
                await self._reboot()
                break

            self._last_screen_type = screen_type
        logger.info('Checking pogo screen is finished')
        if screen_type in [ScreenType.POGO, ScreenType.QUEST]:
            return True
        else:
            return False

    async def _restart_pogo_safe(self):
        logger.info("WorkerBase::_restart_pogo_safe restarting pogo the long way")
        await self.stop_pogo()
        await asyncio.sleep(1)
        if application_args.enable_worker_specific_extra_start_stop_handling:
            await self.worker_specific_setup_stop()
            await asyncio.sleep(1)
        await self._communicator.magisk_off()
        await asyncio.sleep(1)
        await self._communicator.magisk_on()
        await asyncio.sleep(1)
        await self._communicator.start_app("com.nianticlabs.pokemongo")
        await asyncio.sleep(25)
        await self.stop_pogo()
        await asyncio.sleep(1)
        return await self.start_pogo()

    async def _switch_user(self):
        logger.info('Switching User - please wait ...')
        await self.stop_pogo()
        await asyncio.sleep(5)
        await self._communicator.reset_app_data("com.nianticlabs.pokemongo")
        await self.turn_screen_on_and_start_pogo()
        if not self._ensure_pogo_topmost():
            logger.error('Kill Worker...')
            self._worker_state.stop_worker_event.set()
            return False
        logger.info('Switching finished ...')
        return True

    async def stop_pogo(self):
        attempts = 0
        stop_result = await self._communicator.stop_app("com.nianticlabs.pokemongo")
        pogo_topmost = await self._communicator.is_pogo_topmost()
        while pogo_topmost:
            attempts += 1
            if attempts > 10:
                return False
            stop_result = await self._communicator.stop_app("com.nianticlabs.pokemongo")
            await asyncio.sleep(1)
            pogo_topmost = await self._communicator.is_pogo_topmost()
        return stop_result

    async def _reboot(self, mitm_mapper: Optional[MitmMapper] = None):
        try:
            if await self.get_devicesettings_value(MappingManagerDevicemappingKey.REBOOT, True):
                start_result = await self._communicator.reboot()
            else:
                start_result = True
        except WebsocketWorkerRemovedException:
            logger.error("Could not reboot due to client already disconnected")
            start_result = False
        await asyncio.sleep(5)
        if mitm_mapper and self._walker:
            now_ts: int = int(time.time())
            await mitm_mapper.stats_collect_location_data(self._worker_state.origin,
                                                          self._worker_state.current_location, True,
                                                          now_ts, PositionType.REBOOT, 0,
                                                          self._walker.name, TransportType.TELEPORT,
                                                          now_ts)
        if await self.get_devicesettings_value(MappingManagerDevicemappingKey.REBOOT, True):
            async with self._db_wrapper as session, session:
                try:
                    await TrsStatusHelper.save_last_reboot(session, self._db_wrapper.get_instance_id(),
                                                           self._worker_state.device_id)
                    await session.commit()
                except Exception as e:
                    logger.warning("Failed saving restart-status of {}: {}", self._worker_state.origin, e)
        self._reboot_count = 0
        self._restart_count = 0
        # TODO: Reconsider...
        #  await self.stop_worker()
        return start_result

    async def _restart_pogo(self, clear_cache=True, mitm_mapper: Optional[MitmMapper] = None):
        successful_stop = await self.stop_pogo()
        async with self._db_wrapper as session, session:
            try:
                await TrsStatusHelper.save_last_restart(session, self._db_wrapper.get_instance_id(),
                                                        self._worker_state.device_id)
                await session.commit()
            except Exception as e:
                logger.warning("Failed saving restart-status of {}: {}", self._worker_state.origin, e)
        self._restart_count = 0
        logger.debug("restartPogo: stop game resulted in {}", str(successful_stop))
        if successful_stop:
            if clear_cache:
                await self._communicator.clear_app_cache("com.nianticlabs.pokemongo")
            await asyncio.sleep(1)
            if mitm_mapper and self._walker:
                now_ts: int = int(time.time())
                await mitm_mapper.stats_collect_location_data(self._worker_state.origin,
                                                              self._worker_state.current_location, True, now_ts,
                                                              PositionType.RESTART, 0, self._walker.name,
                                                              self._worker_state.last_transport_type, now_ts)
            return await self.start_pogo()
        else:
            logger.warning("Failed restarting PoGo - reboot device")
            return await self._reboot()

    async def _check_pogo_main_screen(self, max_attempts, again=False):
        logger.debug("_check_pogo_main_screen: Trying to get to the Mainscreen with {} max attempts...",
                     max_attempts)
        pogo_topmost = await self._communicator.is_pogo_topmost()
        if not pogo_topmost:
            return False

        if not await self._take_screenshot(
                delay_before=await self.get_devicesettings_value(MappingManagerDevicemappingKey.POST_SCREENSHOT_DELAY,
                                                                 1)):
            if again:
                logger.warning("_check_pogo_main_screen: failed getting a screenshot again")
                return False
        attempts = 0

        screenshot_path = await self.get_screenshot_path()
        if os.path.isdir(screenshot_path):
            logger.error("_check_pogo_main_screen: screenshot.png/.jpg is not a file/corrupted")
            return False

        logger.debug("_check_pogo_main_screen: checking mainscreen")
        while not await self._pogo_windows_handler.check_pogo_mainscreen(screenshot_path, self._worker_state.origin):
            logger.info("_check_pogo_main_screen: not on Mainscreen...")
            if attempts == max_attempts:
                # could not reach raidtab in given max_attempts
                logger.warning("_check_pogo_main_screen: Could not get to Mainscreen within {} attempts",
                               max_attempts)
                return False

            found: List[ScreenCoordinates] = await self._pogo_windows_handler.check_close_except_nearby_button(
                await self.get_screenshot_path(), self._worker_state.origin, close_raid=True)
            if found:
                logger.debug("_check_pogo_main_screen: Found (X) button (except nearby)")
                await self._communicator.click(found[0].x, found[0].y)
                await asyncio.sleep(2)
            else:
                button_coords: Optional[ScreenCoordinates] = await self._pogo_windows_handler \
                    .look_for_button(screenshot_path, 2.20, 3.01)
                if button_coords:
                    logger.debug("_check_pogo_main_screen: Found button (small)")
                    await self._communicator.click(button_coords.x, button_coords.y)
                    await asyncio.sleep(2)
                    return True
                button_coords = await self._pogo_windows_handler.look_for_button(screenshot_path, 1.05, 2.20)
                if button_coords:
                    logger.debug("_check_pogo_main_screen: Found button (big)")
                    await self._communicator.click(button_coords.x, button_coords.y)
                    await asyncio.sleep(2)
                    return True

            logger.debug("_check_pogo_main_screen: Previous checks found pop ups: {}", found)
            await self._take_screenshot(
                delay_before=await self.get_devicesettings_value(MappingManagerDevicemappingKey.POST_SCREENSHOT_DELAY,
                                                                 1))
            attempts += 1
        logger.debug("_check_pogo_main_screen: done")
        return True

    async def _take_screenshot(self, delay_after=0.0, delay_before=0.0, errorscreen: bool = False):
        logger.debug2("Taking screenshot...")
        await asyncio.sleep(delay_before)
        time_since_last_screenshot = time.time() - self._worker_state.last_screenshot_taken_at
        logger.debug4("Last screenshot taken: {}", str(self._worker_state.last_screenshot_taken_at))

        # TODO: area settings for jpg/png and quality?
        screenshot_type: ScreenshotType = ScreenshotType.JPEG
        if await self.get_devicesettings_value(MappingManagerDevicemappingKey.SCREENSHOT_TYPE, "jpeg") == "png":
            screenshot_type = ScreenshotType.PNG

        screenshot_quality: int = await self.get_devicesettings_value(MappingManagerDevicemappingKey.SCREENSHOT_QUALITY,
                                                                      80)

        take_screenshot = await self._communicator.get_screenshot(await self.get_screenshot_path(fileaddon=errorscreen),
                                                                  screenshot_quality, screenshot_type)

        if self._worker_state.last_screenshot_taken_at and time_since_last_screenshot < 0.5:
            logger.info("screenshot taken recently, returning immediately")
            return True
        elif not take_screenshot:
            logger.warning("Failed retrieving screenshot")
            return False
        else:
            logger.debug("Success retrieving screenshot")
            self._worker_state.last_screenshot_taken_at = time.time()
            await asyncio.sleep(delay_after)
            return True

    async def get_screenshot_path(self, fileaddon: bool = False) -> str:
        screenshot_ending: str = ".jpg"
        addon: str = ""
        if await self.get_devicesettings_value(MappingManagerDevicemappingKey.SCREENSHOT_TYPE, "jpeg") == "png":
            screenshot_ending = ".png"

        if fileaddon:
            addon: str = "_" + str(time.time())

        screenshot_filename = "screenshot_{}{}{}".format(str(self._worker_state.origin), str(addon), screenshot_ending)

        if fileaddon:
            logger.info("Creating debugscreen: {}", screenshot_filename)

        return os.path.join(application_args.temp_path, screenshot_filename)

    async def _get_vps_delay(self) -> int:
        return int(await self.get_devicesettings_value(MappingManagerDevicemappingKey.VPS_DELAY, 0))

    async def _update_screen_size(self):
        if self._worker_state.stop_worker_event.is_set():
            raise WebsocketWorkerRemovedException
        screen = await self._communicator.get_screensize()
        y_offset = await self._communicator.get_y_offset()
        if not screen or not y_offset:
            raise WebsocketWorkerRemovedException

        screen = screen.strip().split(' ')
        x_offset = await self.get_devicesettings_value(MappingManagerDevicemappingKey.SCREENSHOT_X_OFFSET, 0)
        # y_offset = await self.get_devicesettings_value(MappingManagerDevicemappingKey.SCREENSHOT_Y_OFFSET, 0)
        self._worker_state.resolution_calculator.screen_size_x = int(screen[0])
        self._worker_state.resolution_calculator.screen_size_y = int(screen[1])
        self._worker_state.resolution_calculator.x_offset = int(x_offset)
        self._worker_state.resolution_calculator.y_offset = int(y_offset)

        logger.debug('Get Screensize: X: {}, Y: {}, X-Offset: {}, Y-Offset: {}',
                     self._worker_state.resolution_calculator.screen_size_x,
                     self._worker_state.resolution_calculator.screen_size_y,
                     x_offset, y_offset)
        # self._resocalc.get_x_y_ratio(self, self._screen_x, self._screen_y, x_offset, y_offset)
