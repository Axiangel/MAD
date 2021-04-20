from datetime import datetime
from typing import Optional

from aiohttp_jinja2.helpers import url_for

from mapadroid.db.helper.TrsEventHelper import TrsEventHelper
from mapadroid.madmin.endpoints.routes.control.AbstractControlEndpoint import \
    AbstractControlEndpoint


class SaveEventEndpoint(AbstractControlEndpoint):
    """
    "/save_event"
    """

    # TODO: Auth
    # TODO: get or post?
    async def post(self):
        # TODO: Verify str or int?
        event_id: Optional[str] = self._request.query.get("id")
        event_name: Optional[str] = self._request.query.get("event_name")
        # TODO: Verify str
        event_start_date: Optional[str] = self._request.query.get("event_start_date")
        event_start_time: Optional[str] = self._request.query.get("event_start_time")
        event_end_date: Optional[str] = self._request.query.get("event_end_date")
        event_end_time: Optional[str] = self._request.query.get("event_end_time")
        # TODO: Verify int
        event_lure_duration: Optional[int] = self._request.query.get("event_lure_duration")

        # default lure duration = 30 (min)
        if event_lure_duration == "":
            event_lure_duration = 30
        if event_name == "" or event_start_date == "" or event_start_time == "" or event_end_date == "" \
                or event_end_time == "":
            await self._add_notice_message('Error while adding this event')
            await self._redirect(str(url_for('events')))

        # TODO: Ensure working conversion
        # TODO: Use self._datetimeformat ?
        event_start = datetime.strptime(event_start_date + " " + event_start_time, '%Y-%m-%d %H:%M')
        event_end = datetime.strptime(event_end_date + " " + event_end_date, '%Y-%m-%d %H:%M')

        await TrsEventHelper.save(self._session, event_name, event_start=event_start,
                                  event_end=event_end,
                                  event_lure_duration=event_lure_duration, event_id=event_id)
        await self._add_notice_message('Successfully added this event')
        await self._redirect(str(url_for('events')), commit=True)
