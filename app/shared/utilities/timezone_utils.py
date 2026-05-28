from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

try:
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


def local_to_utc(dt: datetime | None) -> datetime | None:
    """
    Treat naive datetime as IST and convert to UTC.
    If the datetime is already timezone-aware, convert it to UTC.
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)

    return dt.astimezone(timezone.utc)


def utc_to_ist(dt: datetime | None) -> datetime | None:
    """
    Convert UTC datetime to IST for frontend display.
    """
    if dt is None:
        return None

    return dt.astimezone(IST)
