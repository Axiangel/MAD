from typing import Optional

from aiohttp import web
from aiohttp_jinja2.helpers import url_for
from loguru import logger

from mapadroid.db.helper.TrsStatusHelper import TrsStatusHelper
from mapadroid.madmin.endpoints.routes.control.AbstractControlEndpoint import \
    AbstractControlEndpoint
from mapadroid.utils.MappingManager import DeviceMappingsEntry


class ClearGameDataEndpoint(AbstractControlEndpoint):
    """
    "/clear_game_data"
    """

    # TODO: Auth
    async def get(self):
        origin: Optional[str] = self.request.query.get("origin")
        useadb_raw: Optional[str] = self.request.query.get("adb")
        useadb: bool = True if useadb_raw is not None else False
        # origin_logger = get_origin_logger(self._logger, origin=origin)
        devicemapping: Optional[DeviceMappingsEntry] = await self._get_mapping_manager().get_devicemappings_of(origin)
        if not devicemapping:
            logger.warning("Device {} not found.", origin)
            return web.Response(text="Failed clearing game data.")
        # origin_logger.info('MADmin: Clear game data for device')
        if (useadb and
                await self._adb_connect.send_shell_command(devicemapping.device_settings.adbname, origin,
                                                           "pm clear com.nianticlabs.pokemongo")):
            pass
            # origin_logger.info('MADmin: ADB shell command successfully')
        else:
            temp_comm = self._get_ws_server().get_origin_communicator(origin)
            await temp_comm.reset_app_data("com.nianticlabs.pokemongo")
        raise web.HTTPFound(url_for("get_phonescreens"))
