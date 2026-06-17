import re
from datetime import datetime, date, time, timedelta, timezone
from typing import List, Dict, Any, Optional

# IST timezone (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

def parse_time_to_minutes(time_str: str) -> Optional[int]:
    if not time_str:
        return None
    time_str = time_str.strip().upper()
    # Support "05:00 AM" or "5:00 AM" or "12:00 PM"
    am_pm_match = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM)$", time_str)
    if am_pm_match:
        hours = int(am_pm_match.group(1))
        minutes = int(am_pm_match.group(2))
        period = am_pm_match.group(3)
        if period == 'PM' and hours != 12:
            hours += 12
        if period == 'AM' and hours == 12:
            hours = 0
        return hours * 60 + minutes
    # Support "17:00" or "05:00"
    match24 = re.match(r"^(\d{1,2}):(\d{2})", time_str)
    if match24:
        hours = int(match24.group(1))
        minutes = int(match24.group(2))
        return hours * 60 + minutes
    return None

def format_minutes_to_am_pm(minutes: int) -> str:
    hours = minutes // 60
    mins = minutes % 60
    period = "AM"
    if hours >= 12:
        period = "PM"
        if hours > 12:
            hours -= 12
    if hours == 0:
        hours = 12
    return f"{hours:02d}:{mins:02d} {period}"

def get_day_name(d: date) -> str:
    # d.weekday() is 0 for Monday, 6 for Sunday
    return DAY_NAMES[d.weekday()]

def calculate_temple_status(
    timings_settings: Optional[List[Dict[str, Any]]],
    legacy_opening_time: Optional[str],
    legacy_closing_time: Optional[str],
    today_date: date,
    current_minutes: int,
    day_offset: int = 0
) -> Dict[str, Any]:
    """
    Computes temple status for a given date and time (current_minutes from midnight).
    Supports regular & special timings, daily sessions, and multi-session calculations.
    Returns: { "status": "Open" | "Closed" | "Opening Soon" | "Closing Soon", "label": str, "time_value": int }
    """
    target_date = today_date + timedelta(days=day_offset)
    day_name = get_day_name(target_date)
    
    # 1. Resolve timing windows for target_date
    resolved_windows = []
    
    if timings_settings:
        # Check for active special timings first
        special_timings = []
        regular_timings = []
        for t in timings_settings:
            is_special = t.get("is_special", False)
            if is_special:
                eff_from_str = t.get("effective_from")
                eff_to_str = t.get("effective_to")
                if eff_from_str and eff_to_str:
                    try:
                        eff_from = date.fromisoformat(eff_from_str)
                        eff_to = date.fromisoformat(eff_to_str)
                        if eff_from <= target_date <= eff_to:
                            special_timings.append(t)
                    except ValueError:
                        pass
            else:
                day_req = t.get("day_of_week", "Daily")
                req_days = [d.strip().lower() for d in day_req.split(",") if d.strip()]
                if "daily" in req_days or day_name.lower() in req_days:
                    regular_timings.append(t)
                    
        if special_timings:
            # Special timings override regular timings completely for this day
            # Sort special timings by priority descending
            special_timings.sort(key=lambda x: (int(x.get("priority", 0)), x.get("opening_time")), reverse=True)
            resolved_windows = special_timings
        else:
            resolved_windows = regular_timings
            
    # Fallback to legacy profile timings if no windows resolved
    if not resolved_windows and legacy_opening_time and legacy_closing_time:
        resolved_windows = [{
            "session_name": "Darshan Hours",
            "opening_time": legacy_opening_time,
            "closing_time": legacy_closing_time,
            "day_of_week": "Daily"
        }]
        
    # Parse windows to absolute minutes
    parsed_windows = []
    for w in resolved_windows:
        op_mins = parse_time_to_minutes(w.get("opening_time", ""))
        cl_mins = parse_time_to_minutes(w.get("closing_time", ""))
        if op_mins is not None and cl_mins is not None:
            # Handle closing time crossing midnight
            if cl_mins < op_mins:
                cl_mins += 24 * 60
            parsed_windows.append({
                "session_name": w.get("session_name", "Darshan"),
                "opening_time": op_mins,
                "closing_time": cl_mins,
                "orig_opening_time": w.get("opening_time"),
                "orig_closing_time": w.get("closing_time")
            })
            
    # Sort windows by opening time
    parsed_windows.sort(key=lambda x: x["opening_time"])
    
    # 2. Compute status
    # If calculating for today (day_offset == 0)
    if day_offset == 0:
        # Check if currently inside any open window
        for w in parsed_windows:
            if w["opening_time"] <= current_minutes < w["closing_time"]:
                # Inside window! Is it closing soon?
                cl_diff = w["closing_time"] - current_minutes
                if cl_diff <= 30:
                    return {
                        "status": "Closing Soon",
                        "label": f"Closing Soon | Closes in {cl_diff} Minutes",
                        "dot": "🟠",
                        "session_name": w["session_name"],
                        "closes_at_mins": w["closing_time"]
                    }
                else:
                    cl_display = format_minutes_to_am_pm(w["closing_time"] % (24 * 60))
                    return {
                        "status": "Open",
                        "label": f"Open | Closes at {cl_display}",
                        "dot": "🟢",
                        "session_name": w["session_name"],
                        "closes_at_mins": w["closing_time"]
                    }
                    
        # If not inside any open window, look for the next upcoming window today
        for w in parsed_windows:
            if current_minutes < w["opening_time"]:
                op_diff = w["opening_time"] - current_minutes
                if op_diff <= 30:
                    return {
                        "status": "Opening Soon",
                        "label": f"Opening Soon | Opens in {op_diff} Minutes",
                        "dot": "🟡",
                        "session_name": w["session_name"],
                        "opens_at_mins": w["opening_time"]
                    }
                else:
                    op_display = format_minutes_to_am_pm(w["opening_time"] % (24 * 60))
                    return {
                        "status": "Closed",
                        "label": f"Closed | Opens at {op_display}",
                        "dot": "🔴",
                        "session_name": w["session_name"],
                        "opens_at_mins": w["opening_time"]
                    }
                    
    else:
        # For future days, if there are any windows, the first one is when it opens
        if parsed_windows:
            w = parsed_windows[0]
            op_display = format_minutes_to_am_pm(w["opening_time"] % (24 * 60))
            day_prefix = "tomorrow" if day_offset == 1 else f"on {day_name}"
            return {
                "status": "Closed",
                "label": f"Closed | Opens {day_prefix} at {op_display}",
                "dot": "🔴",
                "session_name": w["session_name"],
                "opens_at_mins": w["opening_time"]
            }
            
    return None

def resolve_full_temple_status(
    timings_settings: Optional[List[Dict[str, Any]]],
    legacy_opening_time: Optional[str],
    legacy_closing_time: Optional[str],
    today_date: date,
    current_minutes: int
) -> Dict[str, Any]:
    """
    Scans today and the next 7 days to find the active or next opening timing window.
    """
    # Try today first
    status_today = calculate_temple_status(
        timings_settings, legacy_opening_time, legacy_closing_time, today_date, current_minutes, day_offset=0
    )
    if status_today:
        return status_today
        
    # Scan next 7 days
    for offset in range(1, 8):
        status_future = calculate_temple_status(
            timings_settings, legacy_opening_time, legacy_closing_time, today_date, current_minutes, day_offset=offset
        )
        if status_future:
            return status_future
            
    # Default fallback
    return {
        "status": "Closed",
        "label": "Closed",
        "dot": "🔴",
        "session_name": "Darshan"
    }

def resolve_current_or_next_activity(
    activities_settings: Optional[List[Dict[str, Any]]],
    today_date: date,
    current_minutes: int,
    is_open: bool
) -> Optional[str]:
    """
    Finds the active activity or the next activity for today.
    """
    if not activities_settings:
        return None
        
    day_name = get_day_name(today_date)
    today_str = today_date.isoformat()
    
    # Filter active activities for today
    resolved_activities = []
    for a in activities_settings:
        is_special = a.get("is_special_schedule", False)
        if is_special:
            eff_from = a.get("effective_from")
            eff_to = a.get("effective_to")
            if eff_from and eff_to and eff_from <= today_str <= eff_to:
                resolved_activities.append(a)
        else:
            rep_days = a.get("repeat_days", [])
            if not rep_days:
                rep_days = ["Daily"]
            if "Daily" in rep_days or any(d.strip().lower() == day_name.lower() for d in rep_days):
                resolved_activities.append(a)
                
    # Parse times
    parsed_activities = []
    for a in resolved_activities:
        act_time = a.get("time")
        act_mins = parse_time_to_minutes(act_time) if act_time else None
        if act_mins is not None:
            parsed_activities.append({
                "activity_name": a.get("activity_name", ""),
                "time_mins": act_mins,
                "orig_time": act_time
            })
            
    if not parsed_activities:
        return None
        
    # Sort activities by time
    parsed_activities.sort(key=lambda x: x["time_mins"])
    
    # 1. Check if any activity is currently in Progress (starts within past 30 minutes)
    for a in parsed_activities:
        if 0 <= (current_minutes - a["time_mins"]) < 30:
            return f"{a['activity_name']} in Progress"
            
    # 2. Check for next upcoming activity today
    for a in parsed_activities:
        if current_minutes < a["time_mins"]:
            time_display = format_minutes_to_am_pm(a["time_mins"])
            return f"{a['activity_name']} at {time_display}"
            
    return None

def resolve_upcoming_festival(
    festivals: List[Any],
    today_date: date
) -> Optional[str]:
    """
    Determines if there is a current or upcoming festival within 14 days.
    Returns: e.g. "🔥 Bharani Utsavam in 3 Days" or None
    """
    if not festivals:
        return None
        
    active_festivals = [f for f in festivals if getattr(f, "is_active", True)]
    
    candidates = []
    for f in active_festivals:
        # Convert start/end dates
        start_dt = f.start_date
        end_dt = f.end_date
        if isinstance(start_dt, str):
            start_dt = date.fromisoformat(start_dt)
        if isinstance(end_dt, str):
            end_dt = date.fromisoformat(end_dt)
            
        emoji = "🎉"
        name_lower = f.name.lower()
        if "bharani" in name_lower or "utsavam" in name_lower or "festival" in name_lower:
            emoji = "🔥"
        elif any(k in name_lower for k in ["navarathri", "navratri", "deepa", "lakhadeepam", "karthika", "diwali"]):
            emoji = "🪔"
            
        if start_dt <= today_date <= end_dt:
            # Currently in progress
            candidates.append({
                "festival": f,
                "badge": f"{emoji} {f.name} in Progress",
                "days_diff": -1, # Active is highest priority
                "priority": getattr(f, "priority", 0)
            })
        elif today_date < start_dt:
            diff_days = (start_dt - today_date).days
            if diff_days <= 14:
                if diff_days == 1:
                    badge_text = f"{emoji} {f.name} Starts Tomorrow"
                else:
                    badge_text = f"{emoji} {f.name} in {diff_days} Days"
                candidates.append({
                    "festival": f,
                    "badge": badge_text,
                    "days_diff": diff_days,
                    "priority": getattr(f, "priority", 0)
                })
                
    if not candidates:
        return None
        
    # Sort candidates: active first (days_diff = -1), then closest start date, then highest priority
    candidates.sort(key=lambda x: (x["days_diff"], -int(x["priority"])))
    return candidates[0]["badge"]
