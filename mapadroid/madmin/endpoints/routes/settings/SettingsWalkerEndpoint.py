from typing import Dict, Optional

import aiohttp_jinja2
from aiohttp import web
from aiohttp.abc import Request
from aiohttp_jinja2.helpers import url_for

from mapadroid.db.helper.SettingsWalkerHelper import SettingsWalkerHelper
from mapadroid.db.model import SettingsWalker
from mapadroid.db.resource_definitions.Walker import Walker
from mapadroid.madmin.AbstractRootEndpoint import AbstractRootEndpoint


class SettingsWalkerEndpoint(AbstractRootEndpoint):
    """
    "/settings/walker"
    """

    def __init__(self, request: Request):
        super().__init__(request)

    # TODO: Auth
    async def get(self):
        identifier: Optional[str] = self.request.query.get("id")
        if identifier:
            return await self._render_single_element(identifier=identifier)
        else:
            return await self._render_overview()

    # TODO: Verify working
    @aiohttp_jinja2.template('settings_singlewalker.html')
    async def _render_single_element(self, identifier: str):
        # Parse the mode to send the correct settings-resource definition accordingly
        walker: Optional[SettingsWalker] = None
        if identifier == "new":
            pass
        else:
            walker: SettingsWalker = await SettingsWalkerHelper.get(self._session, self._get_instance_id(),
                                                                    int(identifier))
            if not walker:
                raise web.HTTPFound(url_for("settings_walkers"))

        settings_vars: Optional[Dict] = self._get_settings_vars()

        template_data: Dict = {
            'identifier': identifier,
            'base_uri': url_for('api_walker'),
            'redirect': url_for('settings_walkers'),
            'subtab': 'walker',
            'element': walker,
            'settings_vars': settings_vars,
            'method': 'POST' if not walker else 'PATCH',
            'uri': url_for('api_walker') if not walker else '%s/%s' % (url_for('api_walker'), identifier),
            # TODO: Above is pretty generic in theory...
        }
        return template_data

    @aiohttp_jinja2.template('settings_walkers.html')
    async def _render_overview(self):
        template_data: Dict = {
            'base_uri': url_for('api_walker'),
            'redirect': url_for('settings_walkers'),
            'subtab': 'walker',
            'section': await SettingsWalkerHelper.get_all_mapped(self._session, self._get_instance_id()),
        }
        return template_data

    def _get_settings_vars(self) -> Optional[Dict]:
        return Walker.configuration
