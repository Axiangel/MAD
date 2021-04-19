from typing import Optional

import aiohttp_jinja2

from mapadroid.madmin.endpoints.routes.control.AbstractControlEndpoint import \
    AbstractControlEndpoint


class InstallStatusEndpoint(AbstractControlEndpoint):
    """
    "/install_status"
    """

    # TODO: Auth
    # TODO: Also "post"?
    # TODO: nocache?
    @aiohttp_jinja2.template('installation_status.html')
    async def get(self):
        withautojobs_raw: Optional[str] = self.request.query.get('withautojobs')
        withautojobs: bool = True if withautojobs_raw == "True" else False
        return {"responsive": str(self._get_mad_args().madmin_noresponsive).lower(),
                "title": "Installation Status", "withautojobs": withautojobs}
