import aiohttp_jinja2

from mapadroid.madmin.AbstractRootEndpoint import AbstractRootEndpoint


class StatisticsSpawnsEndpoint(AbstractRootEndpoint):
    """
    "/statistics_spawns"
    """

    # TODO: Auth
    @aiohttp_jinja2.template('statistics/spawn_statistics.html')
    async def get(self):
        return {
            "title": "MAD Spawnpoint Statistics",
            "time": self._get_mad_args().madmin_time,
            "responsive": str(self._get_mad_args().madmin_noresponsive).lower()
        }
