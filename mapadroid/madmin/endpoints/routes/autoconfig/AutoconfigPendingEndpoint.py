from typing import List, Tuple

import aiohttp_jinja2
from aiohttp.abc import Request

from mapadroid.db.helper.AutoconfigRegistrationHelper import AutoconfigRegistrationHelper
from mapadroid.db.model import AutoconfigRegistration, SettingsDevice
from mapadroid.madmin.AbstractRootEndpoint import AbstractRootEndpoint
from mapadroid.utils.autoconfig import AutoConfIssueGenerator


class AutoconfigPendingEndpoint(AbstractRootEndpoint):
    def __init__(self, request: Request):
        super().__init__(request)

    # TODO: Auth
    @aiohttp_jinja2.template('autoconfig_pending.html')
    async def get(self):
        ac_issues = AutoConfIssueGenerator(self._session, self._get_instance_id(), self._get_mad_args(),
                                           self._get_storage_obj())
        issues_warning, issues_critical = ac_issues.get_issues()
        pending_entries: List[Tuple[AutoconfigRegistration, SettingsDevice]] = \
            await AutoconfigRegistrationHelper.get_pending(self._session, self._get_instance_id())

        return {"subtab": "autoconf_dev",
                "pending": pending_entries,
                "issues_warning": issues_warning,
                "issues_critical": issues_critical
                }
