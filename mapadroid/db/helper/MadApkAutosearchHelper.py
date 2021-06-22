from datetime import datetime
from typing import Optional, List, Dict

from sqlalchemy import and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from mapadroid.db.model import MadApkAutosearch
from mapadroid.mad_apk.apk_enums import APKType, APKArch


class MadApkAutosearchHelper:
    @staticmethod
    async def get_all(session: AsyncSession) -> List[MadApkAutosearch]:
        stmt = select(MadApkAutosearch)
        res = await session.execute(stmt)
        return res.scalars().all()

    @staticmethod
    async def delete(session: AsyncSession, package: APKType, architecture: Optional[APKArch] = None) -> None:
        stmt = delete(MadApkAutosearch).where(MadApkAutosearch.usage == package.value)
        if architecture is not None:
            stmt.where(MadApkAutosearch.arch == architecture.value)
        await session.execute(stmt)

    @staticmethod
    async def insert_or_update(session: AsyncSession, package: APKType, architecture: APKArch, data: Dict) -> None:
        autosearch_entry: MadApkAutosearch = MadApkAutosearch()
        autosearch_entry.arch = architecture.value
        autosearch_entry.usage = package.value
        await session.merge(autosearch_entry)
        # TODO: Ensure values are fetches...
        autosearch_entry.last_checked = datetime.utcnow()
        for key, value in data.items():
            setattr(autosearch_entry, key, value)
        session.add(autosearch_entry)
        await session.flush([autosearch_entry])

    @staticmethod
    async def get(session: AsyncSession, package: APKType, architecture: APKArch) -> Optional[MadApkAutosearch]:
        stmt = select(MadApkAutosearch).where(and_(MadApkAutosearch.usage == package.value,
                                                   MadApkAutosearch.arch == architecture.value))
        res = await session.execute(stmt)
        return res.scalar().first()
