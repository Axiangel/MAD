import os

import aiohttp_jinja2
from aiohttp_jinja2.helpers import url_for

from mapadroid.madmin.endpoints.routes.control.AbstractControlEndpoint import \
    AbstractControlEndpoint


class DeleteFileEndpoint(AbstractControlEndpoint):
    """
    "/delete_file"
    """

    # TODO: Auth
    @aiohttp_jinja2.template('uploaded_files.html')
    async def get(self):
        filename = self.request.query.get('filename')
        if not filename:
            await self._add_notice_message("Missing filename arg")
        # TODO: Async exec I/O?
        elif os.path.exists(os.path.join(self._get_mad_args().upload_path, filename)):
            os.remove(os.path.join(self._get_mad_args().upload_path, filename))
            await self._add_notice_message("File deleted successfully")
        await self._redirect(str(url_for('uploaded_files')))
