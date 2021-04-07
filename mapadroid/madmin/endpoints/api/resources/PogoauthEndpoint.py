from typing import Dict, Optional, Set

from mapadroid.db.helper.SettingsPogoauthHelper import SettingsPogoauthHelper
from mapadroid.db.model import Base, SettingsPogoauth
from mapadroid.db.resource_definitions.Pogoauth import Pogoauth
from mapadroid.madmin.endpoints.api.resources.AbstractResourceEndpoint import \
    AbstractResourceEndpoint


class PogoauthEndpoint(AbstractResourceEndpoint):
    def _attributes_to_ignore(self) -> Set[str]:
        return {"account_id", "guid"}

    async def _fetch_all_from_db(self, **kwargs) -> Dict[int, Base]:
        return await SettingsPogoauthHelper.get_all_mapped(self._session, self._get_instance_id())

    def _resource_info(self) -> Dict:
        return Pogoauth.configuration

    async def _fetch_from_db(self, identifier, **kwargs) -> Optional[Base]:
        return await SettingsPogoauthHelper.get(self._session, self._get_instance_id(), identifier)

    async def _create_instance(self, identifier):
        auth: SettingsPogoauth = SettingsPogoauth()
        auth.instance_id = self._get_instance_id()
        auth.account_id = identifier
        return auth
