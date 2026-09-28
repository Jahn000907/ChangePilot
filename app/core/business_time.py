"""One business calendar and user-visible time zone for ChangePilot."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

BUSINESS_TIME_ZONE = ZoneInfo("Asia/Shanghai")


def current_business_date() -> date:
    """Use the Shanghai calendar day for current effective business facts."""
    return datetime.now(UTC).astimezone(BUSINESS_TIME_ZONE).date()


def shanghai_datetime(value: datetime) -> datetime:
    """Convert stored UTC timestamps to the user-facing business time zone."""
    if value.tzinfo is None:
        raise ValueError("timestamp must include a time zone")
    return value.astimezone(BUSINESS_TIME_ZONE)
