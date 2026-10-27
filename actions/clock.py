"""
Local time, date, and timezone engine for JARVIS.
Uses standard library datetime and zoneinfo modules to provide fast, offline
answers for local system time/date as well as world timezones without querying
Ollama or web search.
"""

import datetime
import os
import re
from typing import Optional, Tuple
import zoneinfo

# Known location to IANA timezone mappings
CITY_COUNTRY_TIMEZONES = {
    # Japan & East Asia
    "tokyo": "Asia/Tokyo",
    "japan": "Asia/Tokyo",
    "kyoto": "Asia/Tokyo",
    "osaka": "Asia/Tokyo",
    "seoul": "Asia/Seoul",
    "korea": "Asia/Seoul",
    "south korea": "Asia/Seoul",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "china": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong",
    "taipei": "Asia/Taipei",
    "taiwan": "Asia/Taipei",
    "singapore": "Asia/Singapore",
    "bangkok": "Asia/Bangkok",
    "thailand": "Asia/Bangkok",
    "hanoi": "Asia/Ho_Chi_Minh",
    "vietnam": "Asia/Ho_Chi_Minh",
    "jakarta": "Asia/Jakarta",
    "indonesia": "Asia/Jakarta",
    "manila": "Asia/Manila",
    "philippines": "Asia/Manila",
    "kuala lumpur": "Asia/Kuala_Lumpur",
    "malaysia": "Asia/Kuala_Lumpur",

    # South Asia (Default Region)
    "india": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata",
    "calcutta": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "new delhi": "Asia/Kolkata",
    "mumbai": "Asia/Kolkata",
    "bombay": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata",
    "bengaluru": "Asia/Kolkata",
    "chennai": "Asia/Kolkata",
    "hyderabad": "Asia/Kolkata",
    "pune": "Asia/Kolkata",
    "ahmedabad": "Asia/Kolkata",
    "karachi": "Asia/Karachi",
    "islamabad": "Asia/Karachi",
    "lahore": "Asia/Karachi",
    "pakistan": "Asia/Karachi",
    "dhaka": "Asia/Dhaka",
    "bangladesh": "Asia/Dhaka",
    "colombo": "Asia/Colombo",
    "sri lanka": "Asia/Colombo",
    "kathmandu": "Asia/Kathmandu",
    "nepal": "Asia/Kathmandu",

    # Middle East
    "dubai": "Asia/Dubai",
    "abu dhabi": "Asia/Dubai",
    "uae": "Asia/Dubai",
    "united arab emirates": "Asia/Dubai",
    "riyadh": "Asia/Riyadh",
    "saudi arabia": "Asia/Riyadh",
    "doha": "Asia/Qatar",
    "qatar": "Asia/Qatar",
    "kuwait": "Asia/Kuwait",
    "tehran": "Asia/Tehran",
    "iran": "Asia/Tehran",
    "baghdad": "Asia/Baghdad",
    "iraq": "Asia/Baghdad",
    "istanbul": "Europe/Istanbul",
    "turkey": "Europe/Istanbul",
    "ankara": "Europe/Istanbul",
    "jerusalem": "Asia/Jerusalem",
    "tel aviv": "Asia/Jerusalem",
    "israel": "Asia/Jerusalem",

    # Europe
    "london": "Europe/London",
    "uk": "Europe/London",
    "united kingdom": "Europe/London",
    "england": "Europe/London",
    "scotland": "Europe/London",
    "ireland": "Europe/Dublin",
    "dublin": "Europe/Dublin",
    "paris": "Europe/Paris",
    "france": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "germany": "Europe/Berlin",
    "munich": "Europe/Berlin",
    "frankfurt": "Europe/Berlin",
    "rome": "Europe/Rome",
    "italy": "Europe/Rome",
    "milan": "Europe/Rome",
    "madrid": "Europe/Madrid",
    "spain": "Europe/Madrid",
    "barcelona": "Europe/Madrid",
    "amsterdam": "Europe/Amsterdam",
    "netherlands": "Europe/Amsterdam",
    "brussels": "Europe/Brussels",
    "belgium": "Europe/Brussels",
    "vienna": "Europe/Vienna",
    "austria": "Europe/Vienna",
    "zurich": "Europe/Zurich",
    "geneva": "Europe/Zurich",
    "switzerland": "Europe/Zurich",
    "stockholm": "Europe/Stockholm",
    "sweden": "Europe/Stockholm",
    "oslo": "Europe/Oslo",
    "norway": "Europe/Oslo",
    "copenhagen": "Europe/Copenhagen",
    "denmark": "Europe/Copenhagen",
    "helsinki": "Europe/Helsinki",
    "finland": "Europe/Helsinki",
    "athens": "Europe/Athens",
    "greece": "Europe/Athens",
    "lisbon": "Europe/Lisbon",
    "portugal": "Europe/Lisbon",
    "warsaw": "Europe/Warsaw",
    "poland": "Europe/Warsaw",
    "prague": "Europe/Prague",
    "czech republic": "Europe/Prague",
    "moscow": "Europe/Moscow",

    # North America
    "new york": "America/New_York",
    "new york city": "America/New_York",
    "nyc": "America/New_York",
    "boston": "America/New_York",
    "washington": "America/New_York",
    "washington dc": "America/New_York",
    "miami": "America/New_York",
    "atlanta": "America/New_York",
    "chicago": "America/Chicago",
    "houston": "America/Chicago",
    "dallas": "America/Chicago",
    "austin": "America/Chicago",
    "denver": "America/Denver",
    "phoenix": "America/Phoenix",
    "los angeles": "America/Los_Angeles",
    "la": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "sf": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "las vegas": "America/Los_Angeles",
    "san diego": "America/Los_Angeles",
    "california": "America/Los_Angeles",
    "toronto": "America/Toronto",
    "montreal": "America/Toronto",
    "ottawa": "America/Toronto",
    "vancouver": "America/Vancouver",
    "calgary": "America/Edmonton",
    "edmonton": "America/Edmonton",
    "mexico city": "America/Mexico_City",
    "mexico": "America/Mexico_City",
    "honolulu": "Pacific/Honolulu",
    "hawaii": "Pacific/Honolulu",
    "anchorage": "America/Anchorage",
    "alaska": "America/Anchorage",

    # South America
    "sao paulo": "America/Sao_Paulo",
    "rio de janeiro": "America/Sao_Paulo",
    "brazil": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "argentina": "America/Argentina/Buenos_Aires",
    "santiago": "America/Santiago",
    "chile": "America/Santiago",
    "bogota": "America/Bogota",
    "colombia": "America/Bogota",
    "lima": "America/Lima",
    "peru": "America/Lima",

    # Oceania
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth",
    "adelaide": "Australia/Adelaide",
    "auckland": "Pacific/Auckland",
    "wellington": "Pacific/Auckland",
    "new zealand": "Pacific/Auckland",

    # Africa
    "cairo": "Africa/Cairo",
    "egypt": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg",
    "cape town": "Africa/Johannesburg",
    "south africa": "Africa/Johannesburg",
    "nairobi": "Africa/Nairobi",
    "kenya": "Africa/Nairobi",
    "lagos": "Africa/Lagos",
    "nigeria": "Africa/Lagos",
    "casablanca": "Africa/Casablanca",
    "morocco": "Africa/Casablanca",

    # Standards
    "utc": "UTC",
    "gmt": "UTC",
    "zulu": "UTC",
}

# Ambiguous multi-timezone locations requiring user clarification
AMBIGUOUS_LOCATIONS = {
    "us": "The United States spans multiple timezones, Sir. Could you specify a city, such as New York, Chicago, Denver, or Los Angeles?",
    "usa": "The United States spans multiple timezones, Sir. Could you specify a city, such as New York, Chicago, Denver, or Los Angeles?",
    "united states": "The United States spans multiple timezones, Sir. Could you specify a city, such as New York, Chicago, Denver, or Los Angeles?",
    "america": "The United States spans multiple timezones, Sir. Could you specify a city, such as New York, Chicago, Denver, or Los Angeles?",
    "canada": "Canada spans multiple timezones, Sir. Could you specify a city, such as Toronto, Vancouver, or Montreal?",
    "australia": "Australia spans multiple timezones, Sir. Could you specify a city, such as Sydney, Melbourne, or Perth?",
    "russia": "Russia spans multiple timezones, Sir. Could you specify a city, such as Moscow, Yekaterinburg, or Vladivostok?",
    "springfield": "There are several locations named Springfield, Sir. Could you specify the state or country?",
}

# Regex patterns for time, date, and day
RE_TIME = re.compile(
    r"^(?:(?:can\s+you\s+|could\s+you\s+|please\s+)?(?:"
    r"tell\s+me\s+(?:the\s+)?(?:current\s+)?time|"
    r"what(?:\x27s|\s+is)\s+(?:the\s+)?time(?:\s+(?:is\s+it|right\s+now|currently|now))?|"
    r"what\s+time\s+is\s+it(?:\s+(?:right\s+now|now|currently))?|"
    r"what(?:\x27s|\s+is)\s+(?:the\s+)?current\s+time|"
    r"current\s+time|"
    r"time\s+right\s+now|"
    r"the\s+time\s+right\s+now|"
    r"what(?:\x27s|\s+is)\s+the\s+time|"
    r"time"
    r"))(?:\s+(?:in|at|for)\s+(.+))?$",
    re.IGNORECASE,
)

RE_DATE = re.compile(
    r"^(?:(?:can\s+you\s+|could\s+you\s+|please\s+)?(?:"
    r"tell\s+me\s+(?:the\s+)?(?:today(?:\x27s)?\s+)?date|"
    r"what(?:\x27s|\s+is)\s+(?:the\s+)?(?:today(?:\x27s)?\s+)?date(?:\s+today)?|"
    r"what(?:\x27s|\s+is)\s+date\s+today|"
    r"what\s+date\s+is\s+it(?:\s+today)?|"
    r"today(?:\x27s)?\s+date|"
    r"the\s+date\s+today|"
    r"the\s+date|"
    r"date\s+today"
    r"))(?:\s+(?:in|at|for)\s+(.+))?$",
    re.IGNORECASE,
)

RE_DAY = re.compile(
    r"^(?:(?:can\s+you\s+|could\s+you\s+|please\s+)?(?:"
    r"what\s+day\s+(?:is\s+it(?:\s+today)?|is\s+today)|"
    r"what\s+is\s+(?:the\s+)?day(?:\s+today)?|"
    r"which\s+day\s+is\s+it(?:\s+today)?|"
    r"tell\s+me\s+(?:what\s+day\s+it\s+is|(?:the\s+)?day(?:\s+today)?)"
    r"))(?:\s+(?:in|at|for)\s+(.+))?$",
    re.IGNORECASE,
)


def get_local_timezone() -> zoneinfo.ZoneInfo:
    """
    Determines the system local timezone using zoneinfo.
    Defaults to Asia/Kolkata (the configured timezone for this Fedora system).
    """
    tz_env = os.environ.get("TZ")
    if tz_env:
        try:
            return zoneinfo.ZoneInfo(tz_env)
        except Exception:
            pass

    try:
        target = os.readlink("/etc/localtime")
        parts = target.split("zoneinfo/")
        if len(parts) > 1:
            tz_str = parts[1].strip()
            # Canonicalize Calcutta -> Kolkata
            if tz_str == "Asia/Calcutta":
                tz_str = "Asia/Kolkata"
            return zoneinfo.ZoneInfo(tz_str)
    except Exception:
        pass

    try:
        loc_tz = datetime.datetime.now().astimezone().tzinfo
        if loc_tz and hasattr(loc_tz, "key") and loc_tz.key:
            return zoneinfo.ZoneInfo(loc_tz.key)
    except Exception:
        pass

    return zoneinfo.ZoneInfo("Asia/Kolkata")


def resolve_timezone(location_raw: Optional[str]) -> Tuple[Optional[zoneinfo.ZoneInfo], Optional[str], Optional[str]]:
    """
    Resolves a requested location string to a ZoneInfo object.
    Returns:
        (ZoneInfo, canonical_name, clarification_needed_msg)
    """
    if not location_raw:
        return get_local_timezone(), None, None

    clean_loc = location_raw.lower().strip().rstrip(".?!,").strip()
    clean_loc = re.sub(r"^(?:in|at|for)\s+", "", clean_loc)
    clean_loc = re.sub(r"^(?:the\s+|city\s+of\s+)", "", clean_loc)

    # 1. Check ambiguous multi-timezone entities
    if clean_loc in AMBIGUOUS_LOCATIONS:
        return None, clean_loc, AMBIGUOUS_LOCATIONS[clean_loc]

    # 2. Check canonical dictionary
    if clean_loc in CITY_COUNTRY_TIMEZONES:
        iana_name = CITY_COUNTRY_TIMEZONES[clean_loc]
        canonical_display = clean_loc.title()
        return zoneinfo.ZoneInfo(iana_name), canonical_display, None

    # 3. Check direct IANA timezone names (e.g. "Asia/Tokyo", "Europe/London")
    try:
        direct_tz = zoneinfo.ZoneInfo(location_raw.strip())
        return direct_tz, location_raw.strip(), None
    except Exception:
        pass

    # 4. Unknown location
    display_loc = clean_loc.title()
    clarification = f"I could not determine the timezone for '{display_loc}', Sir. Could you please specify the country or a major city?"
    return None, clean_loc, clarification


def parse_time_date_query(text: str) -> Optional[dict]:
    """
    Determines if spoken text is an inquiry about local or world time/date.
    Returns structured query dict if matched, else None.
    """
    clean = text.lower().strip()
    # Strip wake prefix
    clean = re.sub(r"^(?:(?:hey|hi|hello|ok|okay)\s+)?jarvis\s*[,:]?\s*", "", clean, flags=re.IGNORECASE).strip()
    clean = clean.rstrip(".?!,").strip()

    m_date = RE_DATE.match(clean)
    if m_date:
        loc = m_date.group(1).strip() if m_date.group(1) else None
        return {"type": "date", "location": loc, "raw": text}

    m_day = RE_DAY.match(clean)
    if m_day:
        loc = m_day.group(1).strip() if m_day.group(1) else None
        return {"type": "day", "location": loc, "raw": text}

    m_time = RE_TIME.match(clean)
    if m_time:
        loc = m_time.group(1).strip() if m_time.group(1) else None
        return {"type": "time", "location": loc, "raw": text}

    return None


def get_time_answer(location: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
    """
    Builds a concise, natural time response for local or specified timezone.
    Returns:
        (success: bool, spoken_text: str, pending_action: str | None)
    """
    tz, loc_name, clarification = resolve_timezone(location)
    if clarification:
        return False, clarification, "clarify_time_location"

    now = datetime.datetime.now(tz)
    time_str = now.strftime("%-I:%M %p")

    if loc_name:
        # Check if the date in target timezone differs from local
        local_now = datetime.datetime.now(get_local_timezone())
        if now.date() != local_now.date():
            day_str = now.strftime("%A")
            return True, f"It is {time_str} on {day_str} in {loc_name}, Sir.", None
        return True, f"It is {time_str} in {loc_name}, Sir.", None

    return True, f"The current time is {time_str}, Sir.", None


def get_date_answer(location: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
    """
    Builds a concise, natural date response.
    Returns:
        (success: bool, spoken_text: str, pending_action: str | None)
    """
    tz, loc_name, clarification = resolve_timezone(location)
    if clarification:
        return False, clarification, "clarify_time_location"

    now = datetime.datetime.now(tz)
    date_str = now.strftime("%A, %B %-d, %Y")

    if loc_name:
        return True, f"It is {date_str} in {loc_name}, Sir.", None

    return True, f"Today is {date_str}, Sir.", None


def get_day_answer(location: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
    """
    Builds a concise, natural day of week response.
    Returns:
        (success: bool, spoken_text: str, pending_action: str | None)
    """
    tz, loc_name, clarification = resolve_timezone(location)
    if clarification:
        return False, clarification, "clarify_time_location"

    now = datetime.datetime.now(tz)
    day_str = now.strftime("%A")

    if loc_name:
        return True, f"It is {day_str} in {loc_name}, Sir.", None

    return True, f"Today is {day_str}, Sir.", None
