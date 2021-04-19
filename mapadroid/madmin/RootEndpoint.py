import json
from abc import ABC
from typing import Any, Optional

from aiohttp import web
from aiohttp.abc import Request
from aiohttp.helpers import sentinel
from aiohttp.typedefs import LooseHeaders
from aiohttp_session import get_session
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from mapadroid.db.DbWrapper import DbWrapper
from mapadroid.db.model import Base
from mapadroid.mad_apk import AbstractAPKStorage
from mapadroid.madmin.api import apiException
from mapadroid.utils.json_encoder import MADEncoder
from mapadroid.utils.MappingManager import MappingManager
from mapadroid.utils.updater import DeviceUpdater
from mapadroid.websocket.WebsocketServer import WebsocketServer


class RootEndpoint(web.View, ABC):
    # TODO: Add security etc in here (abstract) to enforce security true/false
    # If we really need more methods, we can just define them abstract...
    def __init__(self, request: Request):
        super().__init__(request)
        self._commit_trigger: bool = False
        self._session: Optional[AsyncSession] = None

    async def _iter(self):
        db_wrapper: DbWrapper = self._get_db_wrapper()
        async with db_wrapper as session:
            self._session = session
            with logger.contextualize(ip=self._get_request_address(), name="endpoint"):
                response = await self.__generate_response(session)
            return response

    async def __generate_response(self, session: AsyncSession):
        try:
            logger.debug("Waiting for response to {}", self.request.url)
            response = await super()._iter()
            logger.success("Got response to {}", self.request.url)
            if self._commit_trigger:
                logger.debug("Awaiting commit")
                await session.commit()
                logger.info("Done committing")
            # else:
            #    await session.rollback()
        except Exception as e:
            logger.warning("Exception occurred in request!. Details: " + str(e))
            logger.exception("Issue with request to {}", self.request.url)
            await session.rollback()
            # TODO: Get previous URL...
            raise web.HTTPFound("/")
        return response

    def _save(self, instance: Base):
        """
        Creates or updates
        :return:
        """
        self._commit_trigger = True
        self._session.add(instance)
        # await self._session.flush(instance)

    def _delete(self, instance: Base):
        """
        Deletes the instance from the DB
        :param instance:
        :return:
        """
        self._commit_trigger = True
        self._session.delete(instance)

    def _get_request_address(self) -> str:
        if "CF-Connecting-IP" in self.request.headers:
            address = self.request.headers["CF-Connecting-IP"]
        elif "X-Forwarded-For" in self.request.headers:
            address = self.request.headers["X-Forwarded-For"]
        else:
            address = self.request.remote
        return address

    async def _add_notice_message(self, message: str) -> None:
        # TODO: Handle accordingly
        session = await get_session(self.request)
        session["notice"] = message

    async def _redirect(self, redirect_to: str, commit: bool = False):
        if commit:
            await self._session.commit()
        else:
            await self._session.rollback()
        raise web.HTTPFound(redirect_to)

    def _get_db_wrapper(self) -> DbWrapper:
        return self.request.app['db_wrapper']

    def _get_storage_obj(self) -> AbstractAPKStorage:
        return self.request.app['storage_obj']

    def _get_mad_args(self):
        return self.request.app['mad_args']

    def _get_mapping_manager(self) -> MappingManager:
        return self.request.app['mapping_manager']

    def _get_ws_server(self) -> WebsocketServer:
        return self.request.app['websocket_server']

    def _convert_to_json_string(self, content) -> str:
        try:
            return json.dumps(content, cls=MADEncoder)
        except Exception as err:
            raise apiException.FormattingError(err)

    def _get_instance_id(self):
        db_wrapper: DbWrapper = self._get_db_wrapper()
        return db_wrapper.get_instance_id()

    def _get_device_updater(self) -> DeviceUpdater:
        return self.request.app['device_updater']

    def _json_response(self, data: Any = sentinel, *, text: Optional[str] = None, body: Optional[bytes] = None,
                       status: int = 200, reason: Optional[str] = None, headers: Optional[LooseHeaders] = None,
                       content_type: str = "application/json") -> web.Response:
        if data is not sentinel:
            if text or body:
                raise ValueError("only one of data, text, or body should be specified")
            else:
                text = json.dumps(data, indent=None, cls=MADEncoder)
        return web.Response(
            text=text,
            body=body,
            status=status,
            reason=reason,
            headers=headers,
            content_type=content_type,
        )
