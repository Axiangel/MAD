from aiohttp import web

from mapadroid.madmin.endpoints.routes.control.AbstractControlEndpoint import \
    AbstractControlEndpoint
from mapadroid.madmin.functions import uploaded_files


class GetUploadedFilesEndpoint(AbstractControlEndpoint):
    """
    "/get_uploaded_files"
    """

    # TODO: Auth
    async def get(self) -> web.Response:
        # TODO: Async exec?
        return self._json_response(uploaded_files(self._datetimeformat, self._get_device_updater().return_commands()))
