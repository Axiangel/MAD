from typing import Optional

import aiohttp_jinja2

from mapadroid.madmin.AbstractRootEndpoint import AbstractRootEndpoint
from mapadroid.madmin.functions import get_quest_areas


class QuestsPubEndpoint(AbstractRootEndpoint):
    """
    "/quests_pub"
    """

    @aiohttp_jinja2.template('quests.html')
    async def get(self):
        fence: Optional[str] = self._request.query.get("fence")
        stop_fences = await get_quest_areas(self._get_mapping_manager(), self._session, self._get_instance_id())

        return {
            "pub": True,
            "title": "Show daily quests",
            "time": self._get_mad_args().madmin_time,
            "responsive": str(self._get_mad_args().madmin_noresponsive).lower(),
            "fence": fence,
            "stop_fences": stop_fences
        }
