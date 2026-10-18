"""Look up coordinates of named places with OpenStreetMap's Nominatim service (open data, no API key).

Nominatim's usage policy asks for at most one request per second and an identifying User-Agent, so lookups
are spaced out and cached for the life of the process.
"""

import json
import threading
import time
import urllib.parse
import urllib.request

_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "agentic-logistic-handler/1.0 (+https://github.com/ibipul/agentic_logistic_handler)"
_MAX_PLACES = 25
_cache: dict[str, dict | None] = {}
_lock = threading.Lock()
_last_request = 0.0


def _lookup(name: str) -> dict | None:
    global _last_request
    with _lock:
        if name in _cache:
            return _cache[name]
        wait = 1.0 - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        query = urllib.parse.urlencode({"q": name, "format": "json", "limit": 1})
        req = urllib.request.Request(f"{_URL}?{query}", headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                hits = json.loads(res.read())
        finally:
            _last_request = time.monotonic()
        found = None
        if hits:
            found = {"lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]), "matched": hits[0].get("display_name", "")}
        _cache[name] = found
        return found


def locate_places(places: dict[str, str]) -> dict:
    """Find latitude/longitude for real-world places (cities, addresses) so the result can be drawn on a map.

    Call this once when the problem names real places. The coordinates are for the map, and for vehicle
    routing when the user gives no distances (pass them as locations with location_type "lat_lon";
    distances are then straight-line km). Never use them to invent shipping costs.

    Args:
        places: Each place name exactly as used in the problem data → text to search for, with region for
            clarity, e.g. {"Sacramento DC": "Sacramento, California", "Reno Plant": "Reno, Nevada"}.
    """
    pairs = [(str(k).strip(), str(v or k).strip()) for k, v in (places or {}).items() if str(k).strip()][:_MAX_PLACES]
    if not pairs:
        return {"status": "error", "stage": "locate", "message": "No place names were given.", "summary": "no places"}
    found, missing, failed = {}, [], None
    for name, query in pairs:
        try:
            hit = _lookup(query)
        except Exception as exc:  # network down, rate-limited: the page just shows the diagram instead of the map
            failed = f"{type(exc).__name__}: {exc}"
            break
        if hit:
            found[name] = hit
        else:
            missing.append(name)
    status = "ok" if found and not failed and not missing else ("error" if not found else "partial")
    summary = f"located {len(found)} of {len(pairs)} places" + (f" (lookup failed: {failed})" if failed else "")
    return {
        "status": status,
        "stage": "locate",
        "summary": summary,
        "places": found,
        "not_found": missing,
        "source": "OpenStreetMap Nominatim (open data, © OpenStreetMap contributors)",
        **({"message": f"Place lookup failed: {failed}. The result can still be shown as a diagram."} if failed else {}),
    }
