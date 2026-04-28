async def prepare_call_context(metadata: dict, system_prompt: str) -> str:
    """
    Spinny AI Voice Agent — Pre-Call Function (v7.2)
    Scenario-based routing from SQL-Script.md with EXACT Hindi dialogues.
    FULLY EXPANDED — no compaction, every dialogue and instruction is spelled out.

    Routes using:
      1. milestone_data.milestone.name (fresh_lead / verified_lead)
      2. milestone_data.status.name (uar_broken_transaction / uar_shortlist / other)
      3. comment.milestone from Robo Call Summary (null / minimal_engagement / preference_collected / car_pitched)
      4. comment.disposition from Robo Call Summary (null / out_of_city / will_check_then_tell / etc.)
      5. City type (multi-hub / single-hub) from dedicated 'city' field
      6. Preferences availability + budget priority logic
      7. liked_cars_id availability via Spinny API
    """
    import json
    import logging
    from datetime import datetime, timedelta
    from num2words import num2words

    logger = logging.getLogger(__name__)

    # ═══════════════════════════════════════════════════════════════════════════
    # CONSTANTS
    # ═══════════════════════════════════════════════════════════════════════════

    MULTI_HUB_CITIES = {
        "bangalore", "bengaluru", "chennai", "delhi", "delhi-ncr",
        "ghaziabad", "hyderabad", "mumbai", "pune",
    }

    ALLOWED_PREF_FIELDS = [
        "make", "max_price",
        "transmission", "fuel_type",
    ]

    # ═══════════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _g(key: str, default=None):
        """Safe get from flat dot-key metadata."""
        val = metadata.get(key, default)
        if val is None or str(val).strip() in ("", "null", "None", "none", "undefined", "{}"):
            return default
        return val

    def _now_ist() -> datetime:
        """Return current datetime in IST (UTC+5:30)."""
        try:
            import time as _time
            utc_now = datetime(*_time.gmtime()[:6])
        except Exception:
            utc_now = datetime.utcnow()
        return utc_now + timedelta(hours=5, minutes=30)

    def _parse_to_ist(raw_time) -> datetime | None:
        """Parse a datetime string and convert to IST.
        Handles:
          - UTC inputs: '...Z', '...+0000', '...+00:00' → adds +5:30
          - IST inputs: '...+05:30', '...+0530' → already IST, no shift
          - Naive (no tz suffix, no Z): assumed already IST, no shift
        """
        if not raw_time:
            return None
        raw = str(raw_time).strip()
        try:
            is_utc = False
            cleaned = raw

            if raw.endswith("Z"):
                cleaned = raw[:-1]
                is_utc = True
            elif raw.endswith("+0000") or raw.endswith("+00:00"):
                cleaned = raw.rsplit("+", 1)[0]
                is_utc = True
            elif raw.endswith("+0530") or raw.endswith("+05:30"):
                cleaned = raw.rsplit("+", 1)[0]
                is_utc = False
            elif "+" in raw and raw.index("+") > 10:
                cleaned = raw[:raw.index("+", 10)]
                is_utc = True
            else:
                is_utc = False

            if "T" in cleaned:
                dt = datetime.fromisoformat(cleaned)
            else:
                dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")

            if is_utc:
                return dt + timedelta(hours=5, minutes=30)
            return dt

        except Exception:
            return None
						
    def _format_price(price) -> str:
        """Format price (in rupees) into Hinglish words (lakhs/crore/hazaar)."""
        if not price:
            return ""
        try:
            price = float(str(price).replace(",", ""))
        except (ValueError, TypeError):
            return str(price)
        if price >= 10000000:
            v = price / 10000000
            return f"{v:.2f}".rstrip("0").rstrip(".") + " crore"
        elif price >= 100000:
            v = price / 100000
            return f"{v:.2f}".rstrip("0").rstrip(".") + " lakh"
        elif price >= 1000:
            return f"{price / 1000:.0f} hazaar"
        return str(int(price))

    def _format_price_lakhs(price_in_lakhs) -> str:
        """Format a price already in lakhs."""
        if not price_in_lakhs:
            return ""
        try:
            val = float(str(price_in_lakhs).replace(",", ""))
        except (ValueError, TypeError):
            return str(price_in_lakhs)
        return f"{val:.2f}".rstrip("0").rstrip(".") + " lakh"

    def _to_words(val):
        """Convert a numeric value to Indian English words.
        Example: 2018 -> 'two thousand and eighteen', 45000 -> 'forty-five thousand'."""
        try:
            if val is None:
                return "NA"
            s = str(val).strip()
            if s == "" or s == "NA":
                return "NA"
            filtered = ''.join(ch for ch in s if ch.isdigit() or ch in '.-')
            if filtered == "":
                return s
            num = int(float(filtered))
            try:
                return num2words(num, lang='en_IN')
            except Exception:
                return str(num)
        except Exception:
            try:
                return str(val)
            except Exception:
                return "NA"
    
    def _format_td_time_in_hindi(dt: datetime) -> str:
        try:
            from num2words import num2words

            day_word = num2words(dt.day, lang='hi')
            month = dt.strftime("%B")

            hour = int(dt.strftime("%I"))
            minute = int(dt.strftime("%M"))

            hour_word = num2words(hour, lang='hi')

            if minute == 0:
                time_word = f"{hour_word} बजे"
            else:
                minute_word = num2words(minute, lang='hi')
                time_word = f"{hour_word} {minute_word} बजे"

            return f"{day_word} {month} {time_word}"

        except Exception:
            return dt.strftime("%d %B %I:%M %p")

    def _km_to_words(val):
        """Convert km/mileage to words, rounded to nearest thousand.
        Example: 20365 -> 'twenty thousand', 8500 -> 'nine thousand'."""
        try:
            if val is None:
                return "NA"
            s = str(val).strip()
            if s == "" or s == "NA":
                return "NA"
            filtered = ''.join(ch for ch in s if ch.isdigit() or ch in '.-')
            if filtered == "":
                return s
            num = int(float(filtered))
            rounded = round(num / 1000) * 1000
            if rounded == 0:
                rounded = 1000  # minimum 1 thousand for very low values
            try:
                return num2words(rounded, lang='en_IN')
            except Exception:
                return str(rounded)
        except Exception:
            try:
                return str(val)
            except Exception:
                return "NA"

    def _today_tomorrow_dayafter():
        """Return formatted date strings for today, tomorrow, day-after (IST)."""
        now = _now_ist()
        return (
            now.strftime("%d %B %Y"),
            (now + timedelta(days=1)).strftime("%d %B %Y"),
            (now + timedelta(days=2)).strftime("%d %B %Y"),
        )

    # ── City ──────────────────────────────────────────────────────────────────

    def _get_city() -> str:
        """Get city from the dedicated 'city' field in the API payload, fallback to hub_name."""
        city = _g("city", "")
        if city:
            return str(city).strip()
        hub = _g("hub_name", "")
        if hub:
            parts = hub.split(",")
            if len(parts) > 1:
                return parts[-1].strip().split()[0]
        return ""

    def _is_multi_hub(city: str) -> bool:
        """Check if a city is a multi-hub city."""
        return city.lower().strip() in MULTI_HUB_CITIES

    # ── Preference Resolution ─────────────────────────────────────────────────

    def _resolve_pref(field: str, default=None):
        """Resolve a preference field: agent > customer > default."""
        agent_val = _g(f"preferences.agent_filter_data.{field}")
        if agent_val is not None:
            return agent_val
        customer_val = _g(f"preferences.customer_filter_data.{field}")
        if customer_val is not None:
            return customer_val
        return default

    def _build_resolved_preferences() -> dict:
        """Build a dict of resolved preferences (agent > customer), only allowed fields."""
        _prefs_out = {}
        for field in ALLOWED_PREF_FIELDS:
            val = _resolve_pref(field)
            if val is not None:
                _prefs_out[field] = val
        return _prefs_out

    def _has_preferences(prefs: dict) -> bool:
        """Check if any preferences are available."""
        return len(prefs) > 0

    def _pref_fuel(prefs: dict) -> str:
        """Get fuel type from prefs as string."""
        fuel = prefs.get("fuel_type")
        if fuel:
            if isinstance(fuel, list):
                return ", ".join(str(f) for f in fuel) if fuel else ""
            return str(fuel)
        return ""

    def _pref_trans(prefs: dict) -> str:
        """Get transmission from prefs as string."""
        trans = prefs.get("transmission")
        if trans:
            if isinstance(trans, list):
                return ", ".join(str(t) for t in trans) if trans else ""
            return str(trans)
        return ""

    def _pref_make(prefs: dict) -> str:
        """Get make/model from prefs as string."""
        make = prefs.get("make")
        if make:
            if isinstance(make, list):
                return ", ".join(str(m) for m in make) if make else ""
            return str(make)
        return ""

    def _has_model(prefs: dict) -> bool:
        """Check if model/make is available in prefs."""
        make = prefs.get("make")
        if make:
            if isinstance(make, list):
                return len(make) > 0
            return True
        return False

    def _prefs_to_context_block(prefs: dict) -> str:
        """Format resolved preferences as a context block for the prompt."""
        lines = []
        label_map = {
            "max_price": "max_price (lakhs)",
            "fuel_type": "fuel_type",
            "transmission": "transmission",
            "make": "make",
        }
        for key in ALLOWED_PREF_FIELDS:
            val = prefs.get(key)
            if val:
                lines.append(f"{label_map.get(key, key)} = {val}")
        return "\n".join(lines) if lines else "No preferences available."

    # ── Budget Priority ───────────────────────────────────────────────────────

    def _get_effective_budget(prefs: dict) -> str:
        """
        Budget priority:
        - If comment.milestone != minimal_engagement AND Robo Call Summary has budget → that wins
        - If comment.milestone == minimal_engagement → preference budget only
        - Else → preference budget
        """
        _, robo_data = _find_latest_robo_summary()
        cm = robo_data.get("milestone", "") if robo_data else ""

        if cm and cm != "minimal_engagement" and robo_data:
            robo_budget = robo_data.get("budget", "")
            if robo_budget and str(robo_budget).strip() not in ("", "null", "None"):
                return _format_price(robo_budget)

        max_price = prefs.get("max_price")
        if max_price:
            return _format_price_lakhs(max_price)
        return ""

    # ── Robo Call Summary ─────────────────────────────────────────────────────

    def _find_latest_robo_summary() -> tuple:
        """
        Scan comments 0→4.
        Find the FIRST comment containing a valid Robo Call Summary.
        Handles all formats:
          - 'Robo Call Summary: {"milestone": ...}'        (JSON with double quotes)
          - "Robo Call Summary: [{'milestone': ...}]"      (list with single quotes)
          - 'Robo Call Summary: None'                      (skip)
        Return (index, parsed_dict) or (None, None) if not found.
        IMPORTANT: Do NOT check the 'user' field. Only check comment text prefix.
        """
        for i in range(5):
            comment = _g(f"comments.{i}.comment", "")
            if not comment:
                continue
            comment = str(comment).strip()
            if not comment.startswith("Robo Call Summary"):
                continue
            # Strip prefix to get payload
            payload = comment[len("Robo Call Summary"):].lstrip(": ").strip()
            if not payload or payload.lower() == "none":
                continue
            # Try parsing as-is, then with single-quote fix
            import ast as _ast_inner
            for loader_fn in (_ast_inner.literal_eval, json.loads):
                try:
                    parsed = loader_fn(payload)
                    # Unwrap list: [{...}] → {...}
                    if isinstance(parsed, list) and len(parsed) > 0:
                        parsed = parsed[0]
                    if isinstance(parsed, dict) and parsed.get("milestone"):
                        return i, parsed
                except Exception:
                    continue
        return None, None

    def _get_comment_milestone() -> str:
        """Get milestone from the latest Robo Call Summary."""
        _, robo_data = _find_latest_robo_summary()
        if robo_data:
            m = str(robo_data.get("milestone", "")).lower().strip()
            if m in ("preferences_collected", "preference_collected"):
                return "preference_collected"
            if m in ("cars_pitched", "car_pitched"):
                return "car_pitched"
            if m == "minimal_engagement":
                return "minimal_engagement"
        return ""

    def _get_comment_disposition() -> str:
        """Get disposition from the latest Robo Call Summary."""
        _, robo_data = _find_latest_robo_summary()
        if robo_data:
            d = str(robo_data.get("disposition", "")).lower().strip()
            return d
        return ""

    def _get_liked_cars_ids() -> list:
        """Get liked_cars_id list from the latest Robo Call Summary."""
        _, robo_data = _find_latest_robo_summary()
        if robo_data:
            liked = robo_data.get("liked_cars_id", "")
            if liked and str(liked).strip():
                return [cid.strip() for cid in str(liked).split(",") if cid.strip()]
        return []

    def _get_pitched_cars_ids() -> list:
        """Get pitched_cars_id list from the latest Robo Call Summary."""
        _, robo_data = _find_latest_robo_summary()
        if robo_data:
            pitched = robo_data.get("pitched_car_ids", "")
            if pitched and str(pitched).strip():
                return [cid.strip() for cid in str(pitched).split(",") if cid.strip()]
        return []

    def _get_rejected_cars_ids() -> list:
        """Get rejected_cars_id list from the latest Robo Call Summary."""
        _, robo_data = _find_latest_robo_summary()
        if robo_data:
            rejected = robo_data.get("rejected_car_ids", "")
            if rejected and str(rejected).strip():
                return [cid.strip() for cid in str(rejected).split(",") if cid.strip()]
        return []

    async def _fetch_liked_cars_info() -> list:
        """Fetch info for all liked car IDs from the Robo Call Summary
        using Inventory API (parallel via _fetch_car_details_from_inventory).
        Adds backward-compatible 'booked' key for S11-S13 checks."""
        liked_ids = _get_liked_cars_ids()
        if not liked_ids:
            return []
        cars = await _fetch_car_details_from_inventory(liked_ids)
        for car in cars:
            car["booked"] = not car.get("available", True)
        return cars

    # ── Inventory API helpers (rich car details) ────────────────────────────────
    # ── Interested Cars helper (broken_transaction / shortlist) ───────────────
    def _get_interested_cars(source_filter: str) -> list[dict]:
        """Scan interested_cars.0 to interested_cars.4 and return entries
        matching the given source_filter ('dealrequest' or 'shortlist').
        Returns list of dicts: {'lead_id': str, 'source': str, 'index': int}.
        Index 0 is the latest activity — iterate 0→4 only."""
        results = []
        for i in range(5):  # 0 to 4 only
            source = _g(f"interested_cars.{i}.source", "")
            lead_id = _g(f"interested_cars.{i}.lead_id", "")
            if source and lead_id and str(source).strip().lower() == source_filter.lower():
                results.append({
                    "lead_id": str(lead_id).strip(),
                    "source": str(source).strip().lower(),
                    "index": i,
                })
        return results

    # Source A (car_pitched / pref_collected): liked_cars_id from Robo Call Summary
    # Source B (uar_broken_transaction):       car_1.lead_id / car_2.lead_id / car_3.lead_id
    # Source C (interested_cars):              interested_cars.n.lead_id filtered by source

    _inventory_cache = {}   # car_id → cached API result (avoids duplicate calls)

    INVENTORY_AUTH = (
        "Bearer eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICI1ZXNlRkd5"
        "TkZleWZjMWhnNHVPWGVJUmJhYzJrUUV1VVprQURnVF92bGRRIn0.eyJleHAiOjE3ODc4"
        "MTMyNjMsImlhdCI6MTc1NjI3NzI2MywianRpIjoiYzEzZjkxNjUtMzIwYS00Nzc1LTlk"
        "OWUtODEwMjZiOGRmOTcyIiwiaXNzIjoiaHR0cHM6Ly9zc28uc3Bpbm55LmNvbS9hdXRo"
        "L3JlYWxtcy9pbnRlcm5hbCIsImF1ZCI6WyJzcC1kZW1hbmQtYWdncmVnYXRvciIsInNw"
        "aW5ueS13ZWItYmFja2VuZCIsInNwLWRlbWFuZC1nYXRld2F5Iiwic3AtaW5zcGVjdGlv"
        "bnMiLCJzcC12aXNpdHMiLCJzcC1hcHAtaHViIiwiYWNjb3VudCJdLCJzdWIiOiI4MTZm"
        "MzIxYS0xMTRhLTRiNDYtYmM2Mi0xOGU2YmQyN2Q4YzAiLCJ0eXAiOiJCZWFyZXIiLCJh"
        "enAiOiJzcC12b2ljZWJvdC1haSIsImFjciI6IjEiLCJyZWFsbV9hY2Nlc3MiOnsicm9s"
        "ZXMiOlsic3RhZmYtdXNlciIsIm9mZmxpbmVfYWNjZXNzIiwidW1hX2F1dGhvcml6YXRp"
        "b24iLCJkZWZhdWx0LXJvbGVzLWludGVybmFsIl19LCJyZXNvdXJjZV9hY2Nlc3MiOnsi"
        "YWNjb3VudCI6eyJyb2xlcyI6WyJtYW5hZ2UtYWNjb3VudCIsIm1hbmFnZS1hY2NvdW50"
        "LWxpbmtzIiwidmlldy1wcm9maWxlIl19fSwic2NvcGUiOiJvZmZsaW5lX2FjY2VzcyBl"
        "eHRlcm5hbC1lbWFpbCBwcm9maWxlIGVtYWlsIHNwaW5ueV91c2VyX2lkIHNwaW5ueS1i"
        "YWNrZW5kLS1hZG1pbi1zY29wZSIsImNsaWVudEhvc3QiOiIxNjMuMTE2LjIxMi41NiIs"
        "ImVtYWlsX3ZlcmlmaWVkIjpmYWxzZSwiZ3JvdXBzIjpbIi9pc19zdGFmZnVzZXIiXSwi"
        "cHJlZmVycmVkX3VzZXJuYW1lIjoic2VydmljZS1hY2NvdW50LXNwLXZvaWNlYm90LWFp"
        "IiwiY2xpZW50QWRkcmVzcyI6IjE2My4xMTYuMjEyLjU2IiwiY2xpZW50X2lkIjoic3At"
        "dm9pY2Vib3QtYWkifQ.C7234IARnXpmfb9GrhogHL21LGXAZ-eP7d1ZP0gMRxEJ1QGVi2"
        "j9cdljkhU3t9JwcidZNdLEoCaY0EKcs4jTusDt6zH-i07KGhg3y5Rtf4zL4HjoQnV5tA"
        "AQ1HULM8Ie2OABe8QNihl1UHF9LhfASpUcWXViDTGrEYA8ltq0kQRZ1Y0FLcarWMm0GY"
        "38iVEvy1_HQ4MT-b715MAFtKo6L2v7Ee4N4kv-gLWMtmJIQyXOlvUGrf4GvWYPFaikD6"
        "R_BfCqNj7lN2godRFSCCbCV7L2NZYJFu2TnkY6gtFTimgAr226DGczp-dsTcNKUBnzxR8"
        "VXFAdTCwahM6e2UO0Xg"
    )
    INVENTORY_HEADERS = {
        "auth-type": "Keycloak",
        "Keycloak-Authorization": INVENTORY_AUTH,
    }
    INVENTORY_URL = "https://sales-api.spinnyworks.in/sda/api/hub/allcars/inventory_data/"

    def _get_car_slot_ids() -> list[str]:
        """Get car IDs from car_1.lead_id, car_2.lead_id, car_3.lead_id.
        Used for uar_broken_transaction — the cars the user browsed when booking."""
        ids = []
        for prefix in ("car_1", "car_2", "car_3"):
            lead_id = _g(f"{prefix}.lead_id")
            if lead_id:
                ids.append(str(lead_id).strip())
        return ids

    async def _fetch_single_car_from_inventory(client, car_id: str) -> dict | None:
        """Fetch a single car's details from Inventory API.
        Uses _inventory_cache to avoid duplicate API calls for the same car_id.
        Returns a fresh dict copy each time so callers can mutate safely."""
        cid = str(car_id).strip()
        if cid in _inventory_cache:
            cached = _inventory_cache[cid]
            return dict(cached) if cached else None
        try:
            resp = await client.get(
                url=INVENTORY_URL,
                params={"page_size": 30, "car_status": "available", "id": car_id},
                headers=INVENTORY_HEADERS,
            )
            if resp.status_code != 200:
                logger.warning(f"Inventory API {resp.status_code} for car_id={car_id}")
                _inventory_cache[cid] = None
                return None
            inv_results = resp.json().get("data", {}).get("results", [])
            if not inv_results:
                result = {"car_id": car_id, "available": False}
                _inventory_cache[cid] = result
                return dict(result)
            listing   = inv_results[0]
            hub       = listing.get("hub", {}) or {}
            result = {
                "car_id":       car_id,
                "available":    True,
                "make":         listing.get("make", "NA"),
                "model":        listing.get("model", "NA"),
                "year":         listing.get("make_year", ""),
                "color":        listing.get("color", "NA"),
                "price":        listing.get("listing_price", 0),
                "transmission": listing.get("transmission_type", "NA"),
                "owners":       listing.get("owners", "NA"),
                "mileage":      listing.get("mileage", 0),
                "fuel_type":    listing.get("fuel_type", "NA"),
                "body_type":    listing.get("body_type", "NA"),
                "hub_id":       hub.get("id", "NA"),
                "hub_name":     hub.get("display_name", "NA"),
            }
            _inventory_cache[cid] = result
            return dict(result)
        except Exception as e:
            logger.warning(f"Inventory fetch failed for {car_id}: {e}")
            _inventory_cache[cid] = None
            return None

    async def _fetch_car_details_from_inventory(car_ids: list[str]) -> list[dict]:
        """For each car_id: call Inventory API for core details.
        Returns list of dicts. Cars not in available inventory are marked available=False.
        Uses asyncio.gather for PARALLEL fetching — max 3 cars in ~300ms instead of ~900ms."""
        import httpx
        import asyncio as _asyncio
        if not car_ids:
            return []
        async with httpx.AsyncClient(timeout=6.0) as client:
            tasks = [_fetch_single_car_from_inventory(client, cid) for cid in car_ids]
            results = await _asyncio.gather(*tasks, return_exceptions=True)
        return [r for r in results if isinstance(r, dict)]

    def _format_inventory_car_summary(car: dict) -> str:
        """Format one car dict from _fetch_car_details_from_inventory into a summary block."""
        if not car.get("available", True):
            return f"car_lead_id = {car['car_id']}\nStatus = BOOKED / UNAVAILABLE"
        return (
            f"car_lead_id = {car['car_id']}\n"
            f"Make Model = {car.get('make','')} {car.get('model','')}\n"
            f"Make Year = {_to_words(car.get('year',''))}\n"
            f"Colour = {car.get('color','')}\n"
            f"Number of Owners = {car.get('owners','')} owner(s)\n"
            f"Kilometers Driven = {_km_to_words(car.get('mileage',0))} km\n"
            f"Fuel Type = {car.get('fuel_type','')}\n"
            f"Body Type = {car.get('body_type','')}\n"
            f"Hub Name = {car.get('hub_name','')}\n"
            f"hub_id = {car.get('hub_id','')}"
        )

    def _build_whatsapp_cars_info(cars: list[dict]) -> str:
        """
        Builds the {whatsapp_cars_info} block for car_pitched scenarios.
        Contains rich details (year, colour, price, transmission, fuel, availability)
        for each car previously sent on WhatsApp.
        Injected via {whatsapp_cars_info} placeholder — only populated when cm=car_pitched.
        """
        if not cars:
            return "व्हाट्सऐप पर भेजी गई कार्स की जानकारी उपलब्ध नहीं है।"

        lines = []
        for i, c in enumerate(cars, 1):
            car_id   = c.get("car_id", "")
            make     = c.get("make", "NA")
            model    = c.get("model", "NA")
            year     = _to_words(c.get("year", ""))
            colour   = c.get("color", "NA")
            # Try API price first; fall back to car_1/car_2/car_3 metadata
            _raw_price = c.get("price", 0)
            if not _raw_price:
                for _slot in ("car_1", "car_2", "car_3"):
                    if str(_g(f"{_slot}.lead_id", "")) == str(car_id):
                        _raw_price = _g(f"{_slot}.price", 0)
                        break
            price    = _format_price(_raw_price)
            fuel     = c.get("fuel_type", "NA")
            trans    = c.get("transmission", "NA")
            owners   = c.get("owners", "NA")
            mileage  = _km_to_words(c.get("mileage", 0))
            hub_name = c.get("hub_name", "NA")
            avail    = "उपलब्ध है" if c.get("available", True) else "बुक हो चुकी है"

            block = (
                f"कार {i} (car_lead_id = {car_id}):\n"
                f"  {year} की {make} {model}\n"
                f"  Colour: {colour}\n"
                f"  Price: {price}\n"
                f"  Fuel: {fuel} | Transmission: {trans}\n"
                f"  Owners: {owners} | Mileage: {mileage} km\n"
                f"  Hub: {hub_name}\n"
                f"  Status: {avail}"
            )
            lines.append(block)

        return "\n\n".join(lines)

    def _build_pitched_cars_greeting_segment(cars: list[dict]) -> str:
        """
        Build the dynamic 'pitched cars' greeting segment for car_pitched scenarios
        (S17, S_CAR_PITCHED_NO_WHATSAPP).
    
        Returns the segment that follows "Spinny {city} team से।" — already starts
        with "आप ..." and ends with the test drive question. Returns empty string
        if cars cannot be resolved (caller should fall back to generic greeting).
    
        Output examples:
          1 available car:
            "आप 2020 की Honda City explore कर रहे थे, इस पे test drive book कर दूँ?"
          2+ available cars:
            "आप 2020 की Honda City और 2019 की Maruti Swift cars explore कर रहे थे
             — उनमें से किसी पे test drive लेना चाहेंगे?"
          Mixed (some booked):
            "आप 2020 की Honda City और 2019 की Maruti Swift cars explore कर रहे थे,
             हालांकि Maruti Swift अभी book हो चुकी है — Honda City पे test drive
             book कर दूँ?"
          All booked:
            "आप 2020 की Honda City explore कर रहे थे, हालांकि वो अभी book हो चुकी
             है। क्या मैं similar cars दिखा दूँ?"
        """
        if not cars:
            return ""
    
        def _full_label(c):
            yr = _to_words(c.get("year", ""))
            mk = c.get("make", "")
            md = c.get("model", "")
            return f"{yr} की {mk} {md}".strip()
    
        def _short_label(c):
            mk = c.get("make", "")
            md = c.get("model", "")
            return f"{mk} {md}".strip()
    
        def _join_with_aur(items):
            if not items:
                return ""
            if len(items) == 1:
                return items[0]
            if len(items) == 2:
                return f"{items[0]} और {items[1]}"
            return ", ".join(items[:-1]) + f", और {items[-1]}"
    
        available = [c for c in cars if c.get("available", True)]
        booked    = [c for c in cars if not c.get("available", True)]
    
        avail_full   = [_full_label(c) for c in available]
        avail_short  = [_short_label(c) for c in available]
        all_full     = [_full_label(c) for c in cars]
        booked_short = [_short_label(c) for c in booked]
    
        # Case 1: All cars booked → no TD push, pivot to similar cars
        if not available:
            if len(booked) == 1:
                return (
                    f'आप {all_full[0]} explore कर रहे थे, '
                    f'हालांकि वो अभी book हो चुकी है। '
                    f'क्या मैं similar cars दिखा दूँ?'
                )
            return (
                f'आप {_join_with_aur(all_full)} cars explore कर रहे थे, '
                f'हालांकि वो अभी book हो चुकी हैं। '
                f'क्या मैं similar cars दिखा दूँ?'
            )
    
        # Case 2: Single available car, nothing booked → direct single-car TD push
        if len(available) == 1 and not booked:
            return (
                f'आप {avail_full[0]} explore कर रहे थे, '
                f'इस पे test drive book कर दूँ?'
            )
    
        # Case 3: Multiple available, nothing booked → multi-car TD ask
        if not booked:
            return (
                f'आप {_join_with_aur(avail_full)} cars explore कर रहे थे '
                f'— उनमें से किसी पे test drive लेना चाहेंगे?'
            )
    
        # Case 4: Mixed — list all, note booked separately, push TD on available
        booked_join = _join_with_aur(booked_short)
        booked_verb = "है" if len(booked) == 1 else "हैं"
        booked_note = f'हालांकि {booked_join} अभी book हो चुकी {booked_verb}'
    
        if len(available) == 1:
            return (
                f'आप {_join_with_aur(all_full)} cars explore कर रहे थे, '
                f'{booked_note} — {avail_short[0]} पे test drive book कर दूँ?'
            )
        return (
            f'आप {_join_with_aur(all_full)} cars explore कर रहे थे, '
            f'{booked_note} — बाकी में से किसी पे test drive लेना चाहेंगे?'
        )

    # ── Scheduled visits scanner ──────────────────────────────────────────────
    # Scans all_visits.0..2 and their test_drives.0..2 for scheduled status.
    # Returns list of dicts with visit + car details for use in system prompt.

    def _scan_scheduled_visits() -> list[dict]:
        """
        Scan all_visits.n.test_drives.m.status_name for
        'testdrive-lifecycle-testdrive-lifecycle-testdrive-scheduled'.
        For each found: collect scheduled_time, at_home, hub_name, sell_lead_id.
        Returns list of dicts.
        """
        scheduled = []
        SCHEDULED_STATUS = "testdrive-lifecycle-testdrive-lifecycle-testdrive-scheduled"
        for v in range(3):  # visits 0, 1, 2
            for td in range(3):  # test drives 0, 1, 2
                status_key = f"all_visits.{v}.test_drives.{td}.status_name"
                td_status = _g(status_key, "")
                if not td_status:
                    continue
                if SCHEDULED_STATUS in str(td_status).lower():
                    raw_time  = _g(f"all_visits.{v}.scheduled_time", "")
                    at_home   = str(_g(f"all_visits.{v}.at_home", "false")).lower() == "true"
                    hub_name  = _g(f"all_visits.{v}.hub_name", "")
                    how_to_reach = _g(f"all_visits.{v}.how_to_reach", "")
                    sell_lead_id = _g(f"all_visits.{v}.test_drives.{td}.sell_lead_id", "")
                    visit_id  = _g(f"all_visits.{v}.id", "")
                    cancelled = str(_g(f"all_visits.{v}.test_drives.{td}.cancelled", "false")).lower() == "true"
                    if cancelled:
                        continue
                    # Parse scheduled_time (already IST — no shift needed)
                    dt = _parse_to_ist(raw_time)
                    if dt:
                        now_ist = _now_ist()
                        is_today = dt.date() == now_ist.date()
                        is_tomorrow = dt.date() == (now_ist + timedelta(days=1)).date()
                        time_readable = dt.strftime("%I:%M %p").lstrip("0")
                        if is_today:
                            day_label = "आज"
                        elif is_tomorrow:
                            day_label = "कल"
                        else:
                            day_label = dt.strftime("%d %B")
                        time_full = f"{day_label} {time_readable}"
                    else:
                        time_full = raw_time or "scheduled time"
                        is_today = False
                    scheduled.append({
                        "visit_index":  v,
                        "td_index":      td,
                        "visit_id":      visit_id,
                        "sell_lead_id":  str(sell_lead_id),
                        "at_home":       at_home,
                        "hub_name":      hub_name,
                        "how_to_reach":  how_to_reach,
                        "time_full":     time_full,
                        "is_today":      is_today,
                        "raw_time":      raw_time,
                    })
        return scheduled

    async def _build_scheduled_visits_block(scheduled_visits: list) -> str:
        """
        Builds a human-readable context block for all currently scheduled test drives.
        Fetches car details from inventory API for each scheduled car.
        Injected via {scheduled_visits_block} placeholder in system prompt.
        """
        if not scheduled_visits:
            return "No test drives are currently scheduled."

        lines = []
        for i, visit in enumerate(scheduled_visits, 1):
            td_type = "Home Test Drive" if visit["at_home"] else "Hub Test Drive"
            lines.append(f"=== Scheduled Test Drive {i} ===")
            lines.append(f"Type: {td_type}")
            lines.append(f"Time: {visit['time_full']}")
            if not visit["at_home"] and visit["hub_name"]:
                lines.append(f"Hub: {visit['hub_name']}")
            if visit["how_to_reach"]:
                lines.append(f"How to reach: {visit['how_to_reach']}")
            # Fetch car details from inventory
            if visit["sell_lead_id"]:
                try:
                    car_details = await _fetch_car_details_from_inventory([visit["sell_lead_id"]])
                    if car_details:
                        c = car_details[0]
                        if c.get("available", True):
                            lines.append(
                                f"Car: {_to_words(c.get('year',''))} {c.get('make','')} {c.get('model','')} "
                                f"| {c.get('fuel_type','')} {c.get('transmission','')} "
                                f"| {_format_price(c.get('price',0))} "
                                f"| {c.get('owners','')} owner(s) "
                                f"| Colour: {c.get('color','')}"
                            )
                            lines.append(f"sell_lead_id: {visit['sell_lead_id']}")
                        else:
                            lines.append(f"Car (sell_lead_id={visit['sell_lead_id']}): UNAVAILABLE")
                    else:
                        lines.append(f"Car (sell_lead_id={visit['sell_lead_id']}): details not available")
                except Exception as e:
                    lines.append(f"Car (sell_lead_id={visit['sell_lead_id']}): fetch failed ({e})")
            lines.append("")
        return "\n".join(lines)

    # ── Pre-call preference section builder ───────────────────────────────────
    # Injected via {pre_call_pref_section} placeholder in the system prompt.
    # Returns ONLY the text relevant to this scenario so LLM never sees other cases.

    def _build_pre_call_pref_section(
        comment_milestone: str,
        multi_hub: bool,
        resolved_prefs: dict,
        effective_budget: str,
        fuel_str: str,
        trans_str: str,
        model_str: str,
        city_str: str,
    ) -> str:
        has_model  = bool(model_str.strip())
        has_budget = bool(effective_budget.strip()) if effective_budget else False
        filter_str = " ".join(filter(None, [fuel_str.strip(), trans_str.strip()]))

        # Case A: preference_collected / car_pitched
        if comment_milestone in ("preference_collected", "car_pitched"):
            if not resolved_prefs:
                return "No preferences from previous call.\nMove to Section 4.1 (Full Preference Collection)."
            if has_model and has_budget:
                return (
                    f'Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> '
                    f'आप {model_str} जैसी कार्स {effective_budget} लाख के बजट में देख रहे थे। '
                    f'<break time="0.3s" /> क्या preferences वही हैं, या कुछ चेंज करना है?"\n'
                    "Wait for user response.\n"
                    "- If user dont want to change → all confirmed → strictly execute get_cars_according_to_user_specifications function\n"
                    " check car count: if car count ≤ 10 → move to SECTION 6 — CAR PITCHING) | if car count > 10 move to Section 4.2 Partial Preference Collection\n"
                    "- User changes preference → update that preference, re-execute get_cars_according_to_user_specifications function and check car count"
                )
            if has_budget:
                pref_line = f"{effective_budget} लाख के बजट में {filter_str}".strip()
                return (
                    f'Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> '
                    f'आप {pref_line} वाली कार्स देख रहे थे। '
                    f'<break time="0.3s" /> क्या preferences वही हैं?"\n'
                    "Wait for user response.\n"
                    "- If user dont want to change → all confirmed → strictly execute get_cars_according_to_user_specifications function\n"
                    " check car count: if car count ≤ 10 → move to SECTION 6 — CAR PITCHING) | if car count > 10 move to Section 4.2 Partial Preference Collection and collect other preferences like specific car model and remaining pref\n"
                    "- User changes preference → update that preference, re- execute get_cars_according_to_user_specifications function and check car count"
                )
            return (
                f'Bot: "पिछली बार आपसे बात हुई थी — आप {filter_str} कार देख रहे थे। '
                f'<break time="0.3s" /> क्या preferences वही हैं, और बजट क्या है?"\n'
                "Wait for user. Capture budget → strictly execute get_cars_according_to_user_specificationsfunction and check car count.\n"
                " check car count: if car count ≤ 10 move to move to SECTION 6 — CAR PITCHING) | if car count > 10 move to Section 4.2 Partial Preference Collection\n"
                "- User changes preference → update that preference, re-execute get_cars_according_to_user_specifications function and check car count and continue till car count is less than 10"
            )

        # Case B: minimal_engagement
        if comment_milestone == "minimal_engagement":
            if not resolved_prefs:
                return "No preferences available.\nMove to Section 4.1 (Full Preference Collection)."
            if multi_hub:
                return (
                    f'Ask locality first:\n'
                    f'Bot: "आप {city_str} में कौन से area से बात कर रहे हैं?"\n'
                    f'After locality confirmed:\n'
                    f'Bot: "जैसे कि मैं देख पा रही हूँ कि आप {effective_budget} लाख के बजट में, '
                    f'{filter_str} कार्स देख रहे हैं — <break time="0.3s" /> '
                    f'क्या इन preferences में आप कुछ चेंज या add करना चाहेंगे?"\n'
                    "- If user dont want to change → all confirmed → strictly execute get_cars_according_to_user_specifications function\n"
                    " check car count: if car count ≤ 10 → move to SECTION 6 — CAR PITCHING) | if car count > 10 move to Section 4.2 Partial Preference Collection and collect other preferences like specific car model and remaining pref\n"
                    "- User changes preference → update that preference, re-execute get_cars_according_to_user_specifications function and check car count and continue till car count is less than 1"
                )
            return (
                f'Bot: "जैसे कि मैं देख पा रही हूँ कि आप {effective_budget} लाख के बजट में, '
                f'{filter_str} कार्स देख रहे हैं — <break time="0.3s" /> '
                f'क्या इन preferences में आप कुछ चेंज या add करना चाहेंगे?"\n'
                "Wait for response. \n"
                "- If user dont want to change → all confirmed → strictly execute get_cars_according_to_user_specifications function and\n"
                " check car count: if car count ≤ 10 → move to SECTION 6 — CAR PITCHING) | if car count > 10 move to→ Section 4.2 Partial Preference Collection and collect other preferences like specific car model and remaining pref\n"
                "- User changes preference → update that preference, re-execute get_cars_according_to_user_specifications function and check car count and continue till car count is less than 1"
            )

        # Case C: fresh / no robo call
        if not resolved_prefs:
            return "No preferences in metadata.\nMove to Section 4.1 (Full Preference Collection)."
        if multi_hub:
            return (
                f'Ask locality first:\n'
                f'Bot: "आप {city_str} में कौन से area से बात कर रहे हैं?"\n'
                f'After locality confirmed:\n'
                f'Bot: "क्या आप {effective_budget} लाख के बजट में, {filter_str} कार्स देख रहे?"\n'
                "Wait for response. \n"
                "- If user dont want to change → all confirmed → strictly execute get_cars_according_to_user_specifications function\n"
                " check car count: if car count ≤ 10 → move to SECTION 6 — CAR PITCHING) | if car count > 10 move to Section 4.2 Partial Preference Collection and collect other preferences like specific car model and remaining pref\n"
                "- User changes preference → update that preference, re- execute get_cars_according_to_user_specifications function and check car count and continue till car count is less than 1"
            )
        return (
            f'Bot: "क्या आप {effective_budget} लाख के बजट में, {filter_str} कार्स देख रहे?"\n'
            "Wait for response. \n"
            "- If user dont want to change → all confirmed → strictly execute get_cars_according_to_user_specifications function\n"
            " check car count: if car count ≤ 10 move to SECTION 6 — CAR PITCHING) | if car count > 10 move to Section 4.2 Partial Preference Collection and collect other preferences like specific car model and remaining pref\n"
            "- User changes preference → update that preference, re- execute get_cars_according_to_user_specifications function and check car count and continue till car count is less than 1"
        )

    # ── Format Helpers ────────────────────────────────────────────────────────

    def _format_car(prefix: str) -> str:
        """Format car_1 or car_2 or car_3 into a readable string."""
        make = _g(f"{prefix}.make")
        model = _g(f"{prefix}.model")
        if not make and not model:
            return "none"
        parts = []
        if make:
            parts.append(str(make).title())
        if model:
            parts.append(str(model).title())
        fuel = _g(f"{prefix}.fuel")
        if fuel:
            parts.append(f"({fuel})")
        price = _g(f"{prefix}.price")
        if price:
            parts.append(f"- {_format_price(price)}")
        hub = _g(f"{prefix}.hub_name")
        if hub:
            parts.append(f"@ {hub}")
        return " ".join(parts)

    def _build_exchange_context() -> str:
        """Build exchange context from exchange_lead fields."""
        make = _g("exchange_lead.0.make")
        model = _g("exchange_lead.0.model")
        if not make and not model:
            return "none"
        parts = []
        year = _g("exchange_lead.0.make_year")
        if year:
            parts.append(_to_words(year))
        if make:
            parts.append(str(make).title())
        if model:
            parts.append(str(model).title())
        info = " ".join(parts)
        offered = _g("exchange_lead.0.offered_price")
        if offered:
            info += f" | Offered: {_format_price(offered)}"
        return info

    def _format_visit_time_ist() -> tuple:
        """
        Parse visit scheduled_time → IST.
        Returns: (formatted_time_str, day_label, is_today)
        e.g. ("6:21 PM", "आज", True) or ("6:21 PM", "27 March", False)
        """
        raw = _g("visit_data.scheduled_time", _g("visit_time"))
        visit_ist = _parse_to_ist(raw)
        if not visit_ist:
            return ("शेड्यूल्ड टाइम", "", False)
        now_ist = _now_ist()
        is_today = visit_ist.date() == now_ist.date()
        time_str = visit_ist.strftime("%I:%M %p").lstrip("0")
        if is_today:
            day_label = "आज"
        elif visit_ist.date() == (now_ist + timedelta(days=1)).date():
            day_label = "कल"
        else:
            day_label = visit_ist.strftime("%d %B")
        return (time_str, day_label, is_today)

    def _build_previous_interactions() -> str:
        """
        Build a context block from ALL comments (both Robo Call Summary and plain text).
        Format:
        [0] [VOICE AI, date]: milestone=..., disposition=...
        [1] [commenter, date]: plain text gist
        """
        interactions = []
        for i in range(5):
            comment = _g(f"comments.{i}.comment", "")
            if not comment:
                continue
            commenter = _g(f"comments.{i}.user", "unknown")
            date = _g(f"comments.{i}.submit_date", "")
            comment_str = str(comment).strip()
            if comment_str.startswith("Robo Call Summary"):
                json_start = comment_str.find("{")
                if json_start != -1:
                    try:
                        rd = json.loads(comment_str[json_start:])
                        entry = f"[{i}] [VOICE AI, {date}]: milestone={rd.get('milestone','')}, disposition={rd.get('disposition','')}"
                        if rd.get("budget"):
                            entry += f", budget={rd['budget']}"
                        if rd.get("pitched_cars_id"):
                            entry += f", pitched_cars={rd['pitched_cars_id']}"
                        if rd.get("liked_cars_id"):
                            entry += f", liked_cars={rd['liked_cars_id']}"
                        if rd.get("rejected_cars_id"):
                            entry += f", rejected_cars={rd['rejected_cars_id']}"
                        if rd.get("summary"):
                            entry += f"\n    Summary: {rd['summary']}"
                        interactions.append(entry)
                        continue
                    except json.JSONDecodeError:
                        pass
            gist = comment_str[:300] + ("..." if len(comment_str) > 300 else "")
            interactions.append(f"[{i}] [{commenter}, {date}]: {gist}")
        return "\n".join(interactions) if interactions else "No previous interactions."

    # ═══════════════════════════════════════════════════════════════════════════
    # SCENARIO ROUTING — EXACT Hindi from SQL-Script.md
    # FULLY EXPANDED — every dialogue, every instruction, every branch spelled out
    # ═══════════════════════════════════════════════════════════════════════════

    async def _route_scenario(city: str, is_multi: bool, prefs: dict, budget: str, scheduled_visits: list) -> tuple:
        """
        Route to the correct scenario based on milestone × status × comment.milestone × comment.disposition.
        Returns (greeting, full_script, scenario_id).
        """
        milestone = str(_g("milestone_data.milestone.name", "")).lower().strip()
        task = str(_g("milestone_data.task.name", "")).lower().strip()
        # Normalize the long status workflow string to a short token:
        #   buy-request-workflow-...-uar-broken-transaction → uar_broken_transaction
        #   buy-request-workflow-...-uar-shortlist          → uar_shortlist
        #   buy-request-workflow-...-uar-strong             → uar_strong (notify-me etc, NOT shortlist)
        #   buy-request-workflow-...-hub-visit-scheduled    → hub_visit_scheduled
        #   buy-request-workflow-...-uar-weak or anything else → (treated as no activity)
        _raw_status = str(_g("milestone_data.status.name", "")).lower().strip()
        if "uar-broken-transaction" in _raw_status or _raw_status == "uar_broken_transaction":
            status = "uar_broken_transaction"
        elif "uar-shortlist" in _raw_status or _raw_status == "uar_shortlist":
            status = "uar_shortlist"
        elif "uar-strong" in _raw_status or _raw_status == "uar_strong":
            status = "uar_shortlist"  # route to same scenarios, but interested_cars lookup skipped
        elif "hub-visit-scheduled" in _raw_status or _raw_status == "hub_visit_scheduled":
            status = "hub_visit_scheduled"
        else:
            status = _raw_status  # uar-weak and others → no special routing
        cm = _get_comment_milestone()
        cd = _get_comment_disposition()
        has_prefs = _has_preferences(prefs)
        fuel = _pref_fuel(prefs)
        trans = _pref_trans(prefs)
        model = _pref_make(prefs)

        # ══════════════════════════════════════════════════════════════════════
        # EARLY GUARD: Active upcoming visit → skip S1-S17, go straight to TDC
        # If the customer has a scheduled (non-cancelled) future visit,
        # TDC takes priority over whatever cm/cd says.
        # The cm/cd reflects the LAST call, but a visit may have been
        # scheduled AFTER that call (e.g. customer self-scheduled on website).
        # ══════════════════════════════════════════════════════════════════════
        if (len(scheduled_visits) > 0
                or (milestone == "lead_verified" and task in ("call_to_confirm_the_visit", "visit_followup"))
                or status == "hub_visit_scheduled"):

            sv = scheduled_visits  # shorthand

            # ── DUAL TD: two simultaneously scheduled test drives ─────────────
            if len(sv) >= 2:
                v1, v2 = sv[0], sv[1]
                def _td_label(v):
                    return "Home TD" if v["at_home"] else v.get("hub_name", "hub")
                dt1 = _parse_to_ist(v1["raw_time"])
                dt2 = _parse_to_ist(v2["raw_time"])
                spoken_time1 = _format_td_time_in_hindi(dt1) if dt1 else v1["time_full"]
                spoken_time2 = _format_td_time_in_hindi(dt2) if dt2 else v2["time_full"]
                greeting = (
                    f'Hello. <break time="0.5s" /> मैं Priya बोल रही हूँ Spinny से। '
                    f'आपके दो टेस्ट ड्राइव शेड्यूल्ड हैं — '
                    f'{spoken_time1} को {_td_label(v1)} '
                    f'और {spoken_time2} को {_td_label(v2)}। '
                    f'<break time="0.5s" /> क्या आप दोनों के बारे में बात करना चाहेंगे?'
                )
                script = f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: TDC_DUAL — Two test drives are scheduled simultaneously.
TD 1: {v1['time_full']} — {'Home Test Drive' if v1['at_home'] else 'Hub: ' + v1.get('hub_name','')}
  sell_lead_id: {v1['sell_lead_id']}
TD 2: {v2['time_full']} — {'Home Test Drive' if v2['at_home'] else 'Hub: ' + v2.get('hub_name','')}
  sell_lead_id: {v2['sell_lead_id']}

Handle both TDs in conversation. Customer may ask about either.
Car details for each are in {{scheduled_visits_block}}.
Handle: confirm / reschedule / cancel / hub address for each TD separately."""
                return greeting, script, "TDC_DUAL"

            # ── SINGLE TD ─────────────────────────────────────────────────────
            elif len(sv) == 1:
                v = sv[0]
                if v["at_home"]:
                    dt = _parse_to_ist(v["raw_time"])
                    spoken_time = _format_td_time_in_hindi(dt) if dt else v["time_full"]
                    # Home test drive
                    greeting = (
                        f'Hello. <break time="0.5s" /> मैं Priya बात कर रही हूँ Spinny से। '
                        f'आपने हमारे साथ {spoken_time} के लिए '
                        f'एक Home Test Drive बुक की है। '
                        f'<break time="0.5s" /> क्या आप उसके बारे में details जानना चाहेंगे?'
                    )
                    script = f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: TDC_HOME
TD at Home | Time: {v['time_full']} | sell_lead_id: {v['sell_lead_id']}
Car details: see {{scheduled_visits_block}}
Confirm availability. RM will call 2 hrs prior.
Handle: reschedule / car change / cancel / policy questions."""
                    return greeting, script, "TDC_HOME"
                else:
                    # Hub test drive
                    hub = v.get("hub_name", "our hub")
                    time_full = v["time_full"]
                    dt = _parse_to_ist(v["raw_time"])
                    spoken_time = _format_td_time_in_hindi(dt) if dt else time_full
                    is_today = v["is_today"]
                    if is_today:
                        greeting = (
                            f'Hello. <break time="0.5s" /> मैं spinny से प्रिया बोल रही हूँ। '
                            f'आपका {spoken_time} को {hub} पे Test Drive शेड्यूल्ड है। '
                            f'<break time="0.4s" /> क्या आप आज आएंगे?'
                        )
                    else:
                        greeting = (
                            f'Hello. <break time="0.5s" /> मैं spinny से प्रिया बोल रही हूँ। '
                            f'आपका {spoken_time} को {hub} पे Test Drive शेड्यूल्ड है। '
                            f'<break time="0.4s" /> क्या आप आएंगे?'
                        )
                    script = f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: TDC_HUB ({'TODAY' if is_today else time_full})
TD at Hub: {hub} | Time: {time_full} | sell_lead_id: {v['sell_lead_id']}
Car details: see {{scheduled_visits_block}}
Confirm attendance. Share hub address if asked (in {{scheduled_visits_block}}).
Handle: RESCHEDULE / CAR CHANGE / CANCEL."""
                    return greeting, script, "TDC_HUB"

            else:
                # scheduled_visits is empty but task/status triggered TDC
                # Fall through to S1-S17 / FALLBACK below
                pass

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 14: verified_lead + uar_broken_transaction + comment.milestone set
        # SQL-Script.md Lines 453-478
        # milestone_data.milestone.name = verified_lead
        # milestone_data.status.name == uar_broken_transaction
        # comment.milestone = minimal_engagement || preference_collected || car_pitched
        # comment.disposition = any
        # ──────────────────────────────────────────────────────────────────────
        if (status == "uar_broken_transaction"
                and cm in ("minimal_engagement", "preference_collected", "car_pitched")):

            # ── Fetch broken-transaction car from interested_cars (source=dealrequest) ──
            
            _bt_car_info = None
            _bt_lead_id = _g("interested_cars.0.lead_id") or _g("car_1.lead_id")
            if _bt_lead_id:
                try:
                    _bt_fetched = await _fetch_car_details_from_inventory([_bt_lead_id])
                    if _bt_fetched and _bt_fetched[0].get("available", False):
                        _bt_car_info = _bt_fetched[0]
                except Exception as _bt_err:
                    logger.warning(f"Broken txn car fetch failed: {_bt_err}")

            if _bt_car_info:
                _bt_yr = _to_words(_bt_car_info.get("year", ""))
                _bt_mk = _bt_car_info.get("make", "")
                _bt_md = _bt_car_info.get("model", "")
                _bt_pr = _format_price(_bt_car_info.get("price", 0))
                _bt_pr_part = f" जिसकी price {_bt_pr} है" if _bt_pr else ""

                greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। पिछली बार आपसे बात हुई थी <break time="0.7s" /> मैं देख पा रही हूँ कि आप बुकिंग करने का ट्राय कर रहे थे। क्या मैं आपकी कुछ मदद कर दूँ?'

                script = f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: UAR_BROKEN_TRANSACTION + PREVIOUS_INTERACTION (comment.milestone={cm})
Broken-transaction car identified from interested_cars:
  car_id={_bt_car_info['car_id']}, {_bt_yr} {_bt_mk} {_bt_md}, price={_bt_pr}, colour={_bt_car_info.get('color','NA')}, fuel={_bt_car_info.get('fuel_type','NA')}, transmission={_bt_car_info.get('transmission','NA')}

If user agrees with help in booking:
Bot: "मैं देख पा रही हूँ कि आप {_bt_yr} की {_bt_mk} {_bt_md} बुक करने का ट्राय कर रहे थे {_bt_pr_part}। क्या मैं इसकी टेस्ट ड्राइव बुक कर दूं?"
Wait for users reply then based on users reply move to test drive scheduling block

If user wants details:
Share full car details from (Section 7) then push for test drive booking.

If user disagrees with help in booking, or denies booking a car, or says it was by mistake:
Bot: "कोई issue नहीं, आपको कभी भी हेल्प चाहिए हो तो आप कॉलबैक कर सकते हैं।"
proceed to callback time ending."""

            else:
                # Fallback: could not fetch car from interested_cars — use old flow
                greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। पिछली बार आपसे बात हुई थी <break time="0.7s" /> मैं देख पा रही हूँ कि आप बुकिंग करने का ट्राय कर रहे थे। क्या मैं आपकी कुछ मदद कर दूँ?'

                script = f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: UAR_BROKEN_TRANSACTION + PREVIOUS_INTERACTION (comment.milestone={cm})
(Could not identify specific car from interested_cars — asking user)

If user disagrees with help in booking, or denies booking a car, or denies that they tried booking attempt by mistake:
Bot: "कोई issue नहीं, आपको कभी भी हेल्प चाहिए हो तो आप कॉलबैक कर सकते हैं।"

If user agrees with help in booking:
Bot: "आप प्लीज़ मुझे बताइए <break time="0.3s" /> आप कौन सी कार देख रहे थे?"

Wait for user reply, after user specify the car they were trying to book, check that against car_1, car_2, car_3 in metadata.

Bot: "जस्ट टू रिकन्फर्म <break time="0.3s" /> क्या आप {{price}} लाख की {{year}} {{model}} देख रहे थे?"

If customer agrees that the mapped car is correctly mapped:
Bot: "आप बताइए <break time="0.3s" /> आप इसके रिलेटेड डिटेल्स जानना चाहेंगे या फिर इसकी टेस्ट ड्राइव लेना चाहेंगे?"
Wait for users reply then based on users reply move to car details block / test drive scheduling block

If not able to map the cars in car_1, car_2, car_3:
Bot: "ठीक है, मैं आपकी प्रेफरेंस समझने के लिए कुछ डिटेल्स पूछ लेती हूँ ताकि मैं कार सर्च कर सकूँ।"
Wait for users response then proceed to SECTION 5 — CAR SEARCH"""

            return greeting, script, "S14_UAR_BROKEN_TXN_WITH_COMMENT"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 15: verified_lead + uar_shortlist + minimal_engagement
        # SQL-Script.md Lines 480-511
        # milestone_data.milestone.name = verified_lead
        # milestone_data.status.name == uar_shortlist
        # comment.milestone = minimal_engagement
        # comment.disposition = any
        # ──────────────────────────────────────────────────────────────────────
        if status == "uar_shortlist" and cm == "minimal_engagement":

            # ── Fetch shortlisted cars from interested_cars (source=shortlist) ──
            # Only look up interested_cars when actual uar-shortlist (not uar-strong/notify-me)
            _is_actual_shortlist = "uar-shortlist" in _raw_status or _raw_status == "uar_shortlist"
            _sl_entries = _get_interested_cars("shortlist") if _is_actual_shortlist else []
            _sl_cars_info = []
            if _sl_entries:
                _sl_ids = [e["lead_id"] for e in _sl_entries]
                try:
                    _sl_cars_info = await _fetch_car_details_from_inventory(_sl_ids)
                    _sl_cars_info = [c for c in _sl_cars_info if c.get("available", False)]
                except Exception as _sl_err:
                    logger.warning(f"Shortlist cars fetch failed: {_sl_err}")

            # Build the full script with every branch spelled out
            script_parts = []

            if _sl_cars_info:
                # Build car name list for greeting
                _sl_car_names = []
                for _sc in _sl_cars_info:
                    _sc_yr = _to_words(_sc.get("year", ""))
                    _sc_mk = _sc.get("make", "")
                    _sc_md = _sc.get("model", "")
                    _sl_car_names.append(f"{_sc_yr} {_sc_mk} {_sc_md}")

                if len(_sl_car_names) == 1:
                    _sl_cars_text = _sl_car_names[0]
                elif len(_sl_car_names) == 2:
                    _sl_cars_text = f"{_sl_car_names[0]} और {_sl_car_names[1]}"
                else:
                    _sl_cars_text = ", ".join(_sl_car_names[:-1]) + f", और {_sl_car_names[-1]}"

                greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। पहले भी आपसे कार related बात हुई थी. <break time="1s" /> अभी भी आप वेबसाइट पर कुछ कार्स एक्सप्लोर कर रहे थे। क्या कोई स्पेसिफिक कार आपको इंटरेस्टिंग लगी? मैं उसके related आपकी help कर दूँ?'

                script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: UAR_SHORTLIST + MINIMAL_ENGAGEMENT
Shortlisted cars identified from interested_cars:""")
                for _sc in _sl_cars_info:
                    _sc_st = "AVAILABLE" if _sc.get("available", True) else "BOOKED"
                    script_parts.append(f"""  car_id={_sc['car_id']}, {_to_words(_sc.get('year',''))} {_sc.get('make','')} {_sc.get('model','')}, price={_format_price(_sc.get('price',''))}, colour={_sc.get('color','NA')}, fuel={_sc.get('fuel_type','NA')}, transmission={_sc.get('transmission','NA')}, status={_sc_st}""")

                script_parts.append(f"""
If customer refuses help:
Bot: "कोई issue नहीं, आपको कभी भी हेल्प चाहिए हो तो आप कॉलबैक कर सकते हैं।"

If customer agrees for help:
Bot: "जैसे कि मैं देख पा रही हूँ आपने कुछ कार्स शॉर्टलिस्ट करी हैं जैसे {_sl_cars_text}। इनमें से किसी के बारे में और जानना चाहेंगे?"
Wait for customer response.

If customer asks about any of the shortlisted cars:
Share that car's full details from (Section 7) → then aggressive TD push

If customer wants to explore other options:""")

            else:
                # Fallback: no shortlist cars found — use original greeting
                greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। पहले भी आपसे कार related बात हुई थी. <break time="1s" /> अभी भी आप वेबसाइट पर कुछ कार्स एक्सप्लोर कर रहे थे। क्या कोई स्पेसिफिक कार आपको इंटरेस्टिंग लगी? मैं उसके related आपकी help कर दूँ?'

                script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: UAR_SHORTLIST + MINIMAL_ENGAGEMENT
(Could not identify shortlisted cars from interested_cars — asking user)

If customer refuses help:
Bot: "कोई issue नहीं, आपको कभी भी हेल्प चाहिए हो तो आप कॉलबैक कर सकते हैं।"

If customer agrees for help:""")

            # Common preference flow for both branches
            if has_prefs:
                script_parts.append("""
When preferences are available:""")
                if is_multi:
                    script_parts.append(f"""
If multihub city:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response
After users response:
Bot: "जैसे कि मैं देख पा रही हूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन preference में आप कुछ चेंज या add करना चाहेंगे?"
Wait for users response, and move to partial preferences flow""")
                else:
                    script_parts.append(f"""
If single hub city:
Bot: "जैसे कि मैं देख पा रही हूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन प्रेफरेंस में आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response, and move to partial preferences flow""")
            else:
                script_parts.append("""
When customer has no preferences:""")
                if is_multi:
                    script_parts.append(f"""
If multihub city:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response, then move to full preference collection""")
                else:
                    script_parts.append(f"""
If single hub city:
Bot: "आप {city} में ही car देख रहे हैं ना?"
Wait for users response, then move to full preference collection""")

            script = "\n".join(script_parts)
            return greeting, script, "S15_UAR_SHORTLIST_MINIMAL"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 16: verified_lead + uar_shortlist + preference_collected
        # SQL-Script.md Lines 513-532
        # milestone_data.milestone.name = verified_lead
        # milestone_data.status.name == uar_shortlist
        # comment.milestone = preferences_collected
        # comment.disposition = any
        # ──────────────────────────────────────────────────────────────────────
        if status == "uar_shortlist" and cm == "preference_collected":

            greeting = f'Hello. <break time="05s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। पहले भी आपसे कार related बात हुई थी, <break time="1s" /> अभी भी आप वेबसाइट पर कुछ कार्स एक्सप्लोर कर रहे थे। क्या कोई स्पेसिफिक कार आपको इंटरेस्टिंग लगी? मैं उसके रिलेटेड आपकी help कर दूँ?'

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: UAR_SHORTLIST + PREFERENCE_COLLECTED

If customer refuses help:
Bot: "कोई issue नहीं, आपको कभी भी हेल्प चाहिए हो तो आप कॉलबैक कर सकते हैं।"

If user agrees for help or wants to see options:""")

            if _has_model(prefs) and budget:
                script_parts.append(f"""
If model and budget in preferences:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {model} जैसी कार्स {budget} लाख के बजट में देख रहे थे।"
Wait for users response, after confirming budget and model move to car pitching flow""")

            if budget and not _has_model(prefs):
                script_parts.append(f"""
If only budget available:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {budget} लाख के बजट में {fuel} {trans} वाली कार्स देख रहे थे।"
Wait for users response, after confirming budget and transmission or fuel move to car pitching flow""")

            if not budget:
                script_parts.append("""
No budget or model available — collect preferences first then move to car pitching flow""")

            script = "\n".join(script_parts)
            return greeting, script, "S16_UAR_SHORTLIST_PREF_COLLECTED"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 17: verified_lead + uar_shortlist + car_pitched
        # SQL-Script.md Lines 534-581
        # milestone_data.milestone.name = verified_lead
        # milestone_data.status.name == uar_shortlist
        # comment.milestone = car_pitched
        # comment.disposition = any
        # ──────────────────────────────────────────────────────────────────────
        if status == "uar_shortlist" and cm == "car_pitched":

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। पहले भी आपसे कार related बात हुई थी, <break time="1s" /> अभी भी आप वेबसाइट पर कुछ कार्स एक्सप्लोर कर रहे थे। क्या कोई स्पेसिफिक कार आपको इंटरेस्टिंग लगी? मैं उसके रिलेटेड आपकी help कर दूँ?'

            liked_cars_info = await _fetch_liked_cars_info()

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: UAR_SHORTLIST + CAR_PITCHED

If customer refuses help:
Bot: "कोई issue नहीं, आपको कभी भी हेल्प चाहिए हो तो आप कॉलबैक कर सकते हैं।"

If customer agrees for help:
Bot: "आपको जो कार्स पहले भेजी थीं <break time="0.3s" /> उनमें से कोई कार आपको पसंद आ रही है या और कार्स दिखा दूँ?"
Wait for users response""")

            # NO branch — didn't like cars
            script_parts.append("""
1. If Customer says NO (didn't like cars) or ask for other cars:
Bot: "कोई बात नहीं, मैं आपको और कार्स दिखा देती हूँ।"
""")
            if _has_model(prefs) and budget:
                script_parts.append(f"""1.1 If model and budget is known:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {model} जैसी कार्स {budget} लाख के बजट में देख रहे थे। इसमें आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response to confirm, if user changes any pref change those preference and move to car pitching flow""")
            elif budget:
                script_parts.append(f"""1.2 If model is unknown, but budget is known and any of transmission or fuel is available or not available:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {budget} लाख के बजट में {fuel} {trans} वाली कार्स देख रहे थे। इसमें आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response to confirm, if user changes any pref change those preference and move to car pitching flow""")
            else:
                script_parts.append("""Budget unknown — ask for preferences:
Move to full preference collection → car pitching flow""")

            # YES branch — liked cars
            script_parts.append("""
2. If Customer says YES""")

            if not liked_cars_info:
                script_parts.append("""
No liked cars could be resolved from API:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH""")
            else:
                # Show liked cars info
                script_parts.append(f"""
--- Liked Cars Info (fetched from API, total: {len(liked_cars_info)}) ---""")
                for c in liked_cars_info:
                    st = "AVAILABLE" if not c.get("booked", True) else "BOOKED"
                    script_parts.append(f"""  car_id={c['car_id']}, {_to_words(c.get('year',''))} {c.get('make','')} {c.get('model','')}, price={_format_price(c.get('price',''))}, status={st}""")

                if len(liked_cars_info) == 1:
                    c = liked_cars_info[0]
                    year_model = f"{_to_words(c.get('year',''))} {c.get('make','')} {c.get('model','')}"
                    price_str = _format_price(c.get("price", ""))

                    script_parts.append(f"""
2.1 If single car in comments.liked_cars_id:""")
                    if not c.get("booked", True):
                        script_parts.append(f"""Bot: "आप प्लीज़ कन्फर्म कीजिए <break time="0.3s" /> क्या आप {price_str} वाली {year_model} के साथ आगे बढ़ना चाहेंगे?"
Wait for users response

2.1.1 If customer agrees to move ahead with this car:
Bot: "मैं आपको इस कार के डिटेल्स बता देती हूँ या टेस्ट ड्राइव शेड्यूल कर देती हूँ?"
Wait for users response then based on response move to car details pitch or test drive scheduling block""")
                    else:
                        script_parts.append(f"""NOTE: This car (car_id={c['car_id']}) is BOOKED.
Bot: "वो कार अभी booked हो चुकी है। क्या आप similar cars देखना चाहेंगे?"
→ confirm preferences → car pitching flow""")

                    script_parts.append(f"""
2.1.2 If customer says no, not this car and there are no more car to map:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH""")

                else:
                    # Multiple cars
                    car_descs = []
                    for c in liked_cars_info:
                        _yr = _to_words(c.get('year', ''))
                        _mk = c.get('make', '')
                        _md = c.get('model', '')
                        _pr = _format_price(c.get('price', ''))
                        _pr_part = f" जिसकी price {_pr} है" if _pr else ''
                        car_descs.append(f"{_yr} की {_mk} {_md}{_pr_part}")
                    cars_with_price = ", और ".join(car_descs)
                    booked_cars = [c for c in liked_cars_info if c.get("booked", True)]

                    script_parts.append(f"""
2.2 If multiple cars in comments.liked_cars_id:
Bot: "मुझे {len(liked_cars_info)} कार्स दिख रही हैं जिनके बारे में पिछली बार आपसे बात हुई थी <break time="0.3s" /> {cars_with_price} — क्या आप इनमें से किसी एक के साथ आगे बढ़ना चाहेंगे, या मैं आपको इनके डिटेल्स बता दूँ?"
Wait for users response then based on response move to car details pitch or test drive scheduling block if car is among these""")

                    if booked_cars:
                        booked_ids = [c["car_id"] for c in booked_cars]
                        script_parts.append(f"""NOTE: Cars {booked_ids} are BOOKED. If user picks a booked car, inform and offer alternatives.""")

                    script_parts.append(f"""
2.2.1 If customer says no, not any car among these and there are no more car to map:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH """)

            script = "\n".join(script_parts)
            return greeting, script, "S17_UAR_SHORTLIST_CAR_PITCHED"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 1: (verified_lead||fresh_lead) + uar_broken_transaction + null comment
        # SQL-Script.md Lines 1-35
        # milestone_data.milestone.name = verified_lead || fresh_lead
        # milestone_data.status.name = uar_broken_transaction
        # comment.milestone = null
        # comment.disposition = null
        # ──────────────────────────────────────────────────────────────────────
        if status == "uar_broken_transaction" and not cm and not cd:
            _bt_car_info = None
            _bt_lead_id = _g("interested_cars.0.lead_id") or _g("car_1.lead_id")
            if _bt_lead_id:
                try:
                    _bt_fetched = await _fetch_car_details_from_inventory([_bt_lead_id])
                    if _bt_fetched and _bt_fetched[0].get("available", False):
                        _bt_car_info = _bt_fetched[0]
                except Exception as _bt_err:
                    logger.warning(f"Broken txn car fetch failed: {_bt_err}")
            if _bt_car_info:
                _bt_yr = _to_words(_bt_car_info.get("year", ""))
                _bt_mk = _bt_car_info.get("make", "")
                _bt_md = _bt_car_info.get("model", "")
                _bt_pr = _format_price(_bt_car_info.get("price", 0))
                _bt_pr_part = f" जिसकी price {_bt_pr} है" if _bt_pr else ""

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। आप spinny पर कार्स देख रहे थे, इसलिए आपकी car selection में help करने के लिए call कर रहीहूँ, <break time="0.5s" /> क्या अभी दो मिनट बात हो सकती है?'

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: UAR_BROKEN_TRANSACTION + NO_PREVIOUS_ROBO_CALL
Broken-transaction car identified from interested_cars:
  car_id={_bt_car_info['car_id']}, {_bt_yr} {_bt_mk} {_bt_md}, price={_bt_pr}, colour={_bt_car_info.get('color','NA')}, fuel={_bt_car_info.get('fuel_type','NA')}, transmission={_bt_car_info.get('transmission','NA')}


If user agrees with help in booking:
Bot: "मैं देख पा रही हूँ कि आप {_bt_yr} की {_bt_mk} {_bt_md} बुक करने का ट्राय कर रहे थे {_bt_pr_part}। क्या मैं इसकी टेस्ट ड्राइव बुक कर दूं?"
Wait for users reply then based on users reply move to test drive scheduling block

If user disagree or dont want any help:
Bot: "आप अपना convenient time बता दीजिए, मैं उस time connect कर लूंगी।"
Wait for users response and capture callback time

If user denies about booking or doesn't want help with booking:""")

            if has_prefs:
                script_parts.append("""
1. If preferences are available:""")
                if is_multi:
                    script_parts.append(f"""
if multihub city:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response, after user specifies locality,
Bot: "जैसे कि मैं देख पा रही हूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन प्रेफरेंस में आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response then move to partial preference collection""")
                else:
                    script_parts.append(f"""
If single hub city:
Bot: "जैसे कि मैं देख पा रही हूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन प्रेफरेंस में आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response then move to partial preference collection""")
            else:
                script_parts.append("""
2. If preferences are not available:""")
                if is_multi:
                    script_parts.append(f"""
Ask locality if multihub city:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response collect locality specified by user then move to full preference collection""")
                else:
                    script_parts.append(f"""
Else for single hub city, confirm city:
Bot: "आप {city} में ही car देख रहे हैं ना?"
Wait for users response after confirming city then move to full preference collection""")

            script = "\n".join(script_parts)
            return greeting, script, "S1_UAR_BROKEN_TXN_NULL"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 2: fresh_lead + uar_shortlist + null comment
        # SQL-Script.md Lines 36-69
        # milestone_data.milestone.name = fresh_lead
        # milestone_data.status.name = uar_shortlist
        # comment.milestone = null
        # comment.disposition = null
        # ──────────────────────────────────────────────────────────────────────
        if milestone == "fresh_lead" and status == "uar_shortlist" and not cm and not cd:

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। आप spinny पर कार्स देख रहे थे, इसलिए आपकी car selection में help करने के लिए call कर रहीहूँ, <break time="0.4s" /> क्या अभी दो मिनट बात हो सकती है?'

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: FRESH_LEAD + UAR_SHORTLIST + NO_ROBO_CALL

If user disagree or dont want any help:
Bot: "आप अपना convenient time बता दीजिए, मैं उस time connect कर लूंगी।"
Wait for users response and capture callback time

If user agrees for help:""")

            if has_prefs:
                script_parts.append("""
1. If preferences are available:""")
                if is_multi:
                    script_parts.append(f"""
Ask locality If Multi hub:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response, after user specifies locality,
Bot: "क्या आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे?"
Wait for users response then move to partial preference collection""")
                else:
                    script_parts.append(f"""
If Single hub:
Bot: "मैं देख पा रही हूँ कि आप {city} में कुछ कार्स explore कर रहे थे।"
"क्या आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे?"
Wait for users response then move to partial preference collection""")
            else:
                script_parts.append("""
2. If preferences are not available:""")
                if is_multi:
                    script_parts.append(f"""
Ask locality if multihub city:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response collect locality specified by user then move to full preference collection""")
                else:
                    script_parts.append(f"""
Else for single hub city, confirm city:
Bot: "आप {city} में ही car देख रहे हैं ना?"
Wait for users response after confirming city then move to full preference collection""")

            script = "\n".join(script_parts)
            return greeting, script, "S2_FRESH_LEAD_UAR_SHORTLIST"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 3: fresh_lead + NOT(broken_txn/shortlist) + null comment — No Activity
        # SQL-Script.md Lines 71-103
        # milestone_data.milestone.name = fresh_lead
        # milestone_data.status.name != (uar_broken_transaction || uar_shortlist)
        # comment.milestone = null
        # comment.disposition = null
        # No Activity
        # ──────────────────────────────────────────────────────────────────────
        if (milestone == "fresh_lead"
                and status not in ("uar_broken_transaction", "uar_shortlist")
                and not cm and not cd):

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। आप spinny पर कार्स देख रहे थे, इसलिए आपकी car selection में help करने के लिए call कर रहीहूँ, <break time="0.4s" /> क्या अभी दो मिनट बात हो सकती है?'

            # NOTE: In Scenario 3 (No Activity) the mapping is SWAPPED in the doc:
            # "1. When customer has preferences available" → goes to FULL preference collection (locality/city first)
            # "2. When customer has no preferences" → shows existing prefs → partial
            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: FRESH_LEAD + NO_ACTIVITY (No previous robo call, no special status)

If user disagree or dont want any help or is busy:
Bot: "आप अपना convenient time बता दी जिए, मैं उस time connect कर लूंगी।"
Wait for users response and capture callback time

If user agrees to talk:""")

            # Branch 1: When customer has preferences available
            script_parts.append("""
1. When customer has preferences available:""")
            if is_multi:
                script_parts.append(f"""Ask locality if multihub city:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response collect locality specified by user then move to full preference collection""")
            else:
                script_parts.append(f"""Else for single hub city, confirm city:
Bot: "आप {city} में ही car देख रहे हैं ना?"
Wait for users response then move to full preference collection""")

            # Branch 2: When customer has no preferences
            script_parts.append("""
2. When customer has no preferences:""")
            if is_multi:
                script_parts.append(f"""If multihub:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response
After users response:
Bot: "जैसे कि मैं देख पा रहीहूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन preference में आप कुछ चेंज या add करना चाहेंगे?"
Wait for users response then move to partial preference collection""")
            else:
                script_parts.append(f"""If single hub:
Bot: "जैसे कि मैं देख पा रहीहूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन प्रेफरेंस में आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response then move to partial preference collection""")

            script = "\n".join(script_parts)
            return greeting, script, "S3_FRESH_LEAD_NO_ACTIVITY"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 4: verified_lead + minimal_engagement + generic dispositions
        # SQL-Script.md Lines 105-140
        # milestone_data.milestone.name = verified_lead
        # comment.milestone = minimal_engagement
        # comment.disposition = will_check_then_tell || td_timeline_2 || exchange_value_first || loan_clarity_needed || other
        # milestone_data.status.name != (uar_broken_transaction || uar_shortlist)
        # ──────────────────────────────────────────────────────────────────────
        if (milestone == "lead_verified" and cm == "minimal_engagement"
                and cd in ("will_check_then_tell", "td_timeline_2", "exchange_value_first", "loan_clarity_needed", "other")
                and status not in ("uar_broken_transaction", "uar_shortlist")):

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। पहले भी बात हुई थी, क्या अब कार सिलेक्शन में कुछ हेल्प चाहिए?'

            # Same swapped logic as Scenario 3
            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: VERIFIED_LEAD + MINIMAL_ENGAGEMENT + {cd.upper()}

If user disagree or dont want any help or is busy:
Bot: "आप अपना convenient time बता दी जिए, मैं उस time connect कर लूंगी।"
Wait for users response and capture callback time

If user agrees to talk or wants help:""")

            # Branch 1: When customer has preferences available
            script_parts.append("""
1. When customer has preferences available:""")
            if is_multi:
                script_parts.append(f"""Ask locality if multihub city:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response collect locality specified by user then move to full preference collection""")
            else:
                script_parts.append(f"""Else for single hub city, confirm city:
Bot: "आप {city} में ही car देख रहे हैं ना?"
Wait for users response then move to full preference collection""")

            # Branch 2: When customer has no preferences
            script_parts.append("""
2. When customer has no preferences:""")
            if is_multi:
                script_parts.append(f"""If multihub:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response
After users response:
Bot: "जैसे कि मैं देख पा रही हूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन preference में आप कुछ चेंज या add करना चाहेंगे?"
Wait for users response then move to partial preference collection""")
            else:
                script_parts.append(f"""If single hub:
Bot: "जैसे कि मैं देख पा रही हूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन प्रेफरेंस में आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response then move to partial preference collection""")

            script = "\n".join(script_parts)
            return greeting, script, f"S4_MINIMAL_{cd.upper()}"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 5: verified_lead + minimal_engagement + out_of_city
        # SQL-Script.md Lines 142-177
        # milestone_data.milestone.name = verified_lead
        # comment.milestone = minimal_engagement
        # comment.disposition = out_of_city
        # milestone_data.status.name != (uar_broken_transaction || uar_shortlist)
        # ──────────────────────────────────────────────────────────────────────
        if (milestone == "lead_verified" and cm == "minimal_engagement" and cd == "out_of_city"
                and status not in ("uar_broken_transaction", "uar_shortlist")):

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। पिछली बार बात हुई थी तो आप आउट of सिटी थे। क्या अब मैं आपको कार selection में help कर दूँ?'

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: VERIFIED_LEAD + MINIMAL_ENGAGEMENT + OUT_OF_CITY

If user disagree or dont want any help:
Bot: "आप अपना convenient time बता दीजिए, मैं उस time connect कर लूंगी।"
Wait for users response and capture callback time

If user agrees for help:""")

            # 1. When customer has no preferences
            script_parts.append("""
1. When customer has no preferences:""")
            if is_multi:
                script_parts.append(f"""Ask locality if multihub city:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response, then move to full preference collection""")
            else:
                script_parts.append(f"""Else for single hub city, confirm city:
Bot: "आप {city} में ही car देख रहे हैं ना?"
Wait for users response, then move to full preference collection""")

            # 2. When preferences are available
            script_parts.append("""
2. When preferences are available:""")
            if is_multi:
                script_parts.append(f"""If multihub:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response
After users response:
Bot: "जैसे कि मैं देख पा रही हूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन preference में आप कुछ चेंज या add करना चाहेंगे?"
Wait for users response, and move to partial preferences flow""")
            else:
                script_parts.append(f"""If single hub:
Bot: "जैसे कि मैं देख पा रही हूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन प्रेफरेंस में आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response, and move to partial preferences flow""")

            script = "\n".join(script_parts)
            return greeting, script, "S5_MINIMAL_OUT_OF_CITY"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 6: verified_lead + minimal_engagement + callback_requested
        # SQL-Script.md Lines 179-210
        # milestone_data.milestone.name = verified_lead
        # comment.milestone = minimal_engagement
        # comment.disposition = callback_requested
        # milestone_data.status.name != (uar_broken_transaction || uar_shortlist)
        # ──────────────────────────────────────────────────────────────────────
        if (milestone == "lead_verified" and cm == "minimal_engagement" and cd == "callback_requested"
                and status not in ("uar_broken_transaction", "uar_shortlist")):

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। आपने callback request की थी, <break time="0.4s" /> क्या अब थोड़ा टाइम है बात करने का?'

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: VERIFIED_LEAD + MINIMAL_ENGAGEMENT + CALLBACK_REQUESTED

If user disagree or dont want any help:
Bot: "आप अपना convenient time बता दीजिए, मैं उस time connect कर लूंगी।"
Wait for users response and capture callback time

If user agrees for help:""")

            # When customer has no preferences
            script_parts.append("""
When customer has no preferences:""")
            if is_multi:
                script_parts.append(f"""Ask locality if multihub city:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response, then move to full preference collection""")
            else:
                script_parts.append(f"""Else for single hub city, confirm city:
Bot: "आप {city} में ही car देख रहे हैं ना?"
Wait for users response, then move to full preference collection""")

            # When preferences are available
            script_parts.append("""
When preferences are available:""")
            if is_multi:
                script_parts.append(f"""If multihub:
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response
After users response:
Bot: "जैसे कि मैं देख पा रही हूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन preference में आप कुछ चेंज या add करना चाहेंगे?"
Wait for users response, and move to partial preferences flow""")
            else:
                script_parts.append(f"""If single hub:
Bot: "जैसे कि मैं देख पा रही हूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन प्रेफरेंस में आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response, and move to partial preferences flow""")

            script = "\n".join(script_parts)
            return greeting, script, "S6_MINIMAL_CALLBACK"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 7: preference_collected + out_of_city
        # SQL-Script.md Lines 212-234
        # milestone_data.milestone.name = verified_lead
        # comment.milestone = preference_collected
        # comment.disposition = out_of_city
        # milestone_data.status.name != (uar_broken_transaction || uar_shortlist)
        # ──────────────────────────────────────────────────────────────────────
        if (milestone == "lead_verified" and cm == "preference_collected" and cd == "out_of_city"
                and status not in ("uar_broken_transaction", "uar_shortlist")):

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। पिछली बार आपने अपनी प्रेफरेंस शेयर की थी, तब आप आउट ऑफ सिटी थे। <break time="0.4s" /> अब वापस आ गए हैं तो क्या मैं अवेलेबल कार ऑप्शन्स आपको बता दूँ?'

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: VERIFIED_LEAD + PREFERENCE_COLLECTED + OUT_OF_CITY

If user disagree or dont want any help:
Bot: "आप अपना convenient time बता दीजिए, मैं उस time connect कर लूंगी।"
Wait for users response and capture callback time

If user agrees for help:""")

            # 1. If model and budget in preferences
            if _has_model(prefs) and budget:
                script_parts.append(f"""
1. If model and budget in preferences:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {model} जैसी कार्स {budget} लाख के बजट में देख रहे थे।"
Wait for users response, after confirming budget and model move to car pitching flow""")

            # 2. If only budget available
            if budget and not _has_model(prefs):
                script_parts.append(f"""
2. If only budget available:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {budget} लाख के बजट में {fuel} {trans} वाली कार्स देख रहे थे।"
Wait for users response, after confirming budget and transmission or fuel move to car pitching flow""")

            if not budget:
                script_parts.append("""
No budget or model available — collect preferences first then move to car pitching flow""")

            script = "\n".join(script_parts)
            return greeting, script, "S7_PREF_COLLECTED_OUT_OF_CITY"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 8: preference_collected + will_check_then_tell
        # SQL-Script.md Lines 236-277
        # milestone_data.milestone.name = verified_lead
        # comment.milestone = preference_collected
        # comment.disposition = will_check_then_tell
        # milestone_data.status.name != (uar_broken_transaction || uar_shortlist)
        # ──────────────────────────────────────────────────────────────────────
        if (milestone == "lead_verified" and cm == "preference_collected" and cd == "will_check_then_tell"
                and status not in ("uar_broken_transaction", "uar_shortlist")):

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। <break time="0.5s" /> पिछली बार आपने अपनी प्रेफरेंस के अकॉर्डिंग whatsapp पर कुछ ऑप्शन्स शेयर करने को कहा था। क्या आपको उन ऑप्शन्स में से कुछ पसंद आया?'

            liked_cars_info = await _fetch_liked_cars_info()

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: VERIFIED_LEAD + PREFERENCE_COLLECTED + WILL_CHECK_THEN_TELL""")

            # NO branch
            script_parts.append("""
1. If Customer says NO didnt like cars:
Bot: "कोई बात नहीं, मैं आपको और कार्स दिखा देती हूँ।"
""")
            if _has_model(prefs) and budget:
                script_parts.append(f"""1.1 If model and budget is known:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {model} जैसी कार्स {budget} लाख के बजट में देख रहे थे। इसमें आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response to confirm, if user changes any pref change those preference and move to car pitching flow""")
            elif budget:
                script_parts.append(f"""1.2 If model is unknown, but budget is known and any of transmission or fuel is available or not available:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {budget} लाख के बजट में {fuel} {trans} वाली कार्स देख रहे थे। इसमें आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response to confirm, if user changes any pref change those preference and move to car pitching flow""")
            else:
                script_parts.append("""Budget unknown — ask for preferences:
Move to full preference collection → car pitching flow""")

            # YES branch
            script_parts.append("""
2. If Customer says YES""")

            if not liked_cars_info:
                script_parts.append("""
No liked cars could be resolved from API:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH """)
            else:
                script_parts.append(f"""
--- Liked Cars Info (fetched from API, total: {len(liked_cars_info)}) ---""")
                for c in liked_cars_info:
                    st = "AVAILABLE" if not c.get("booked", True) else "BOOKED"
                    script_parts.append(f"""  car_id={c['car_id']}, {_to_words(c.get('year',''))} {c.get('make','')} {c.get('model','')}, price={_format_price(c.get('price',''))}, status={st}""")

                if len(liked_cars_info) == 1:
                    c = liked_cars_info[0]
                    year_model = f"{_to_words(c.get('year',''))} {c.get('make','')} {c.get('model','')}"
                    price_str = _format_price(c.get("price", ""))

                    script_parts.append(f"""
2.1 If single car in comments.liked_cars_id:""")
                    if not c.get("booked", True):
                        script_parts.append(f"""Bot: "आप प्लीज़ कन्फर्म कीजिए <break time="0.4s" /> क्या आप {price_str} वाली {year_model} के साथ आगे बढ़ना चाहेंगे?"
Wait for users response

2.1.1 If customer agrees to move ahead with this car:
Bot: "मैं आपको इस कार के डिटेल्स बता देती हूँ या टेस्ट ड्राइव शेड्यूल कर देती हूँ?"
Wait for users response then based on response move to car details pitch or test drive scheduling block""")
                    else:
                        script_parts.append(f"""NOTE: This car (car_id={c['car_id']}) is BOOKED.
Bot: "वो कार अभी booked हो चुकी है। क्या आप similar cars देखना चाहेंगे?"
→ confirm preferences → car pitching flow""")

                    script_parts.append("""
2.1.2 If customer says no, not this car and there are no more car to map:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH """)

                else:
                    car_descs = []
                    for _c in liked_cars_info:
                        _yr = _to_words(_c.get('year', ''))
                        _mk = _c.get('make', '')
                        _md = _c.get('model', '')
                        _pr = _format_price(_c.get('price', ''))
                        _pr_part = f" जिसकी price {_pr} है" if _pr else ''
                        car_descs.append(f"{_yr} की {_mk} {_md}{_pr_part}")
                    cars_with_price = ", और ".join(car_descs)
                    booked_cars = [c for c in liked_cars_info if c.get("booked", True)]

                    script_parts.append(f"""
2.2 If multiple cars in comments.liked_cars_id:
Bot: "मुझे {len(liked_cars_info)} कार्स दिख रही हैं जिनके बारे में पिछली बार आपसे बात हुई थी <break time="0.3s" /> {cars_with_price} — क्या आप इनमें से किसी एक के साथ आगे बढ़ना चाहेंगे, या मैं आपको इनके डिटेल्स बता दूँ?"
Wait for users response then based on response move to car details pitch or test drive scheduling block if car is among these""")

                    if booked_cars:
                        booked_ids = [c["car_id"] for c in booked_cars]
                        script_parts.append(f"""NOTE: Cars {booked_ids} are BOOKED. If user picks a booked car, inform and offer alternatives.""")

                    script_parts.append("""
2.2.1 If customer says no, not any car among this two and there are no more car to map:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH""")

            script = "\n".join(script_parts)
            return greeting, script, "S8_PREF_COLLECTED_WILL_CHECK"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 9: preference_collected + callback_requested
        # SQL-Script.md Lines 279-299
        # milestone_data.milestone.name = verified_lead
        # comment.milestone = preference_collected
        # comment.disposition = callback_requested
        # milestone_data.status.name != (uar_broken_transaction || uar_shortlist)
        # ──────────────────────────────────────────────────────────────────────
        if (milestone == "lead_verified" and cm == "preference_collected" and cd == "callback_requested"
                and status not in ("uar_broken_transaction", "uar_shortlist")):

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। <break time="1s" /> आपने कॉलबैक रिक्वेस्ट की थी। क्या मैं अवेलेबल कार ऑप्शन्स आपको बता दूँ?'

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: VERIFIED_LEAD + PREFERENCE_COLLECTED + CALLBACK_REQUESTED

If user disagree or dont want any help:
Bot: "आप अपना convenient time बता दीजिए, मैं उस time connect कर लूंगी?"
Wait for users response and capture callback time

If user agrees for help or wants to see options:""")

            if _has_model(prefs) and budget:
                script_parts.append(f"""
If model and budget in preferences:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {model} जैसी कार्स {budget} लाख के बजट में देख रहे थे।"
Wait for users response, after confirming budget and model move to car pitching flow""")

            if budget and not _has_model(prefs):
                script_parts.append(f"""
If only budget available:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {budget} लाख के बजट में {fuel} {trans} वाली कार्स देख रहे थे।"
Wait for users response, after confirming budget and transmission or fuel move to car pitching flow""")

            if not budget:
                script_parts.append("""
No budget or model available — collect preferences first then move to car pitching flow""")

            script = "\n".join(script_parts)
            return greeting, script, "S9_PREF_COLLECTED_CALLBACK"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 10: preference_collected + td_timeline_2/exchange/loan/other
        # SQL-Script.md Lines 301-320
        # milestone_data.milestone.name = verified_lead
        # comment.milestone = preference_collected
        # comment.disposition = td_timeline_2 || exchange_value_first || loan_clarity_needed || other
        # milestone_data.status.name != (uar_broken_transaction || uar_shortlist)
        # ──────────────────────────────────────────────────────────────────────
        if (milestone == "lead_verified" and cm == "preference_collected"
                and cd in ("td_timeline_2", "exchange_value_first", "loan_clarity_needed", "other")
                and status not in ("uar_broken_transaction", "uar_shortlist")):

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। <break time="0.4s" /> पिछली बार आपने अपनी preferences share की थी, मैं आपको कार selection में help करने के लिए call कर रहीहूँ, <break time="0.4s" /> क्या अभी दो मिनट बात हो सकती है?'

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: VERIFIED_LEAD + PREFERENCE_COLLECTED + {cd.upper()}

If user disagree or dont want any help:
Bot: "आप अपना convenient time बता दीजिए, मैं उस time connect कर लूंगी?"
Wait for users response and capture callback time

If user agrees for help or wants to see options:""")

            if _has_model(prefs) and budget:
                script_parts.append(f"""
If model and budget in preferences:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {model} जैसी कार्स {budget} लाख के बजट में देख रहे थे।"
Wait for users response, after confirming budget and model move to car pitching flow""")

            if budget and not _has_model(prefs):
                script_parts.append(f"""
If only budget available:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {budget} लाख के बजट में {fuel} {trans} वाली कार्स देख रहे थे।"
Wait for users response, after confirming budget and transmission or fuel move to car pitching flow""")

            if not budget:
                script_parts.append("""
No budget or model available — collect preferences first then move to car pitching flow""")

            script = "\n".join(script_parts)
            return greeting, script, f"S10_PREF_COLLECTED_{cd.upper()}"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO S_CAR_PITCHED_NO_WHATSAPP:
        # cm = car_pitched, liked_cars_id = EMPTY, pitched_car_ids available
        # Cars were discussed on previous call but NOT sent on WhatsApp.
        # Uses pitched_car_ids (last 3) → parallel API fetch → dynamic car listing.
        # Greeting uses "बात हुई थी" instead of "शेयर की थीं".
        # milestone_data.milestone.name = lead_verified OR fresh_lead
        # comment.milestone = car_pitched
        # comment.disposition = any
        # milestone_data.status.name != (uar_broken_transaction || uar_shortlist)
        # ──────────────────────────────────────────────────────────────────────
        if (cm == "car_pitched"
                and not _get_liked_cars_ids()
                and status not in ("uar_broken_transaction", "uar_shortlist")):

            # Fetch last 3 pitched cars in parallel
            import asyncio as _asyncio_pitched
            _pitched_ids = _get_pitched_cars_ids()[-3:]  # cap at last 3
            _pitched_cars_info: list[dict] = []
            if _pitched_ids:
                try:
                    _pitched_cars_info = await _fetch_car_details_from_inventory(_pitched_ids)
                except Exception as _pitched_err:
                    logger.warning(f"Pitched cars fetch failed: {_pitched_err}")

            # Also try car_1/car_2/car_3 from metadata as final fallback
            if not _pitched_cars_info:
                _slot_ids = _get_car_slot_ids()
                if _slot_ids:
                    try:
                        _pitched_cars_info = await _fetch_car_details_from_inventory(_slot_ids)
                    except Exception as _slot_err:
                        logger.warning(f"Car slot fetch failed: {_slot_err}")

            # Filter to only available cars for the listing
            _available_pitched = [c for c in _pitched_cars_info if c.get("available", True)]

            _pitched_segment = _build_pitched_cars_greeting_segment(_pitched_cars_info)

            if _pitched_segment:
                greeting = (
                    f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ '
                    f'Spinny {city} team से। <break time="0.5s" /> {_pitched_segment}'
                )
            else:
                greeting = (
                    f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ '
                    f'Spinny {city} team से। पिछली बार कुछ कार्स के बारे में बात हुई थी '
                    f'— क्या उनमें से किसी के बारे में जानना चाहेंगे, या मैं कुछ और options दिखा दूँ?'
                )

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: S_CAR_PITCHED_NO_WHATSAPP
(Cars were discussed on previous call but not sent on WhatsApp)""")

            # ─── CASE A — Customer wants to know about previously discussed cars ───
            if _available_pitched:
                # Build dynamic car listing based on count
                _car_parts = []
                for _c in _available_pitched:
                    _yr = _to_words(_c.get("year", ""))
                    _mk = _c.get("make", "")
                    _md = _c.get("model", "")
                    _pr = _format_price(_c.get("price", 0))
                    _pr_part = f" जिसकी price {_pr} है" if _pr else ""
                    _car_parts.append(f"{_yr} की {_mk} {_md}{_pr_part}")

                if len(_car_parts) == 1:
                    _cars_line = f"{_car_parts[0]} — क्या आप इसके बारे में जानना चाहेंगे?"
                elif len(_car_parts) == 2:
                    _cars_line = f"{_car_parts[0]} और {_car_parts[1]} — इनमें से किस के बारे में जानना चाहेंगे?"
                else:
                    _joined = ", ".join(_car_parts[:-1])
                    _cars_line = f"{_joined}, और {_car_parts[-1]} — इनमें से किस के बारे में जानना चाहेंगे?"

                # Show fetched car details for context
                script_parts.append(f"""
─────────────────────────────────────
CASE A — Customer wants to know about previously discussed cars:
─────────────────────────────────────
--- Pitched Cars Info (fetched from API, total: {len(_available_pitched)}) ---""")
                for _i, _c in enumerate(_available_pitched, 1):
                    _st = "AVAILABLE" if _c.get("available", True) else "BOOKED"
                    script_parts.append(f"""  car_id={_c['car_id']}, {_to_words(_c.get('year',''))} {_c.get('make','')} {_c.get('model','')}, price={_format_price(_c.get('price',''))}, colour={_c.get('color','NA')}, fuel={_c.get('fuel_type','NA')}, transmission={_c.get('transmission','NA')}, status={_st}""")

                script_parts.append(f"""
Bot: "पिछली बार मैंने {_cars_line}"
Wait for customer to name a car.

if user asks about any car from this then share its info as:
Bot: "ये {{colour}} colour की {{make}} {{model}} {{fuel_type}} {{transmission}} कार है।.."
Then share full car details from (Section 7) → aggressive TD push

If car is BOOKED/UNAVAILABLE:
Bot: "वो कार अभी available नहीं है, किसी और ने book कर ली है।
     <break time=\"0.3s\" /> लेकिन मैं आपको उसी जैसी कार दिखाती हूँ।"
→ call get_cars_according_to_user_specifications with that car's attributes
→ Section 6 (Car Pitching)""")

                # Booked cars warning
                _booked_pitched = [_c for _c in _pitched_cars_info if not _c.get("available", True)]
                if _booked_pitched:
                    _booked_ids = [_c["car_id"] for _c in _booked_pitched]
                    script_parts.append(f"""
NOTE: Cars {_booked_ids} are BOOKED/UNAVAILABLE. If user picks one, inform and offer alternatives via get_cars_according_to_user_specifications.""")

            else:
                # No pitched cars could be fetched at all
                script_parts.append("""
─────────────────────────────────────
No pitched cars could be resolved from API.
─────────────────────────────────────
Skip directly to CASE B/C below.""")

            # ─── CASE B — Customer wants different/more cars ───
            # Use _build_pre_call_pref_section for pref available/not logic
            _pref_section = _build_pre_call_pref_section(
                comment_milestone=cm,
                multi_hub=is_multi,
                resolved_prefs=prefs,
                effective_budget=budget,
                fuel_str=fuel,
                trans_str=trans,
                model_str=model,
                city_str=city,
            )

            if has_prefs:
                script_parts.append(f"""
─────────────────────────────────────
CASE B — Customer wants different/more cars:
─────────────────────────────────────
Bot: "कोई बात नहीं, मैं आपको और options दिखा देती हूँ।"

{_pref_section}""")
            else:
                script_parts.append("""
─────────────────────────────────────
CASE B — Customer wants different/more cars (no preferences available):
─────────────────────────────────────
Bot: "कोई बात नहीं, मैं आपको और options दिखा देती हूँ।"
No preferences from previous call.
Move to Section 4.1 (Full Preference Collection).""")

            # ─── CASE C — Customer doesn't remember / vague response ───
            if has_prefs:
                script_parts.append(f"""
─────────────────────────────────────
CASE C — Customer doesn\'t remember / vague response:
─────────────────────────────────────
{_pref_section}""")
            else:
                script_parts.append("""
─────────────────────────────────────
CASE C — Customer doesn\'t remember / vague response:
─────────────────────────────────────
No preferences from previous call.
Move to Section 4.1 (Full Preference Collection).""")

            script = "\n".join(script_parts)
            return greeting, script, "S_CAR_PITCHED_NO_WHATSAPP"

                # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 11: car_pitched + generic dispositions
        # SQL-Script.md Lines 322-362
        # milestone_data.milestone.name = verified_lead
        # comment.milestone = car_pitched
        # comment.disposition = td_timeline_2 || exchange_value_first || loan_clarity_needed || other || will_check_then_tell
        # milestone_data.status.name != (uar_broken_transaction || uar_shortlist)
        # ──────────────────────────────────────────────────────────────────────
        if (milestone == "lead_verified" and cm == "car_pitched"
                and cd in ("td_timeline_2", "exchange_value_first", "loan_clarity_needed", "other", "will_check_then_tell")
                and status not in ("uar_broken_transaction", "uar_shortlist")):

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। <break time="0.4s" /> पिछली बार कुछ कार्स आपके साथ शेयर की थीं। क्या उन कार्स में से आपको कोई पसंद आई?'

            liked_cars_info = await _fetch_liked_cars_info()

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: VERIFIED_LEAD + CAR_PITCHED + {cd.upper()}""")

            # NO branch
            script_parts.append("""
1. If Customer says NO (didn't like cars):
Bot: "कोई बात नहीं, मैं आपको और कार्स दिखा देती हूँ।"
""")
            if _has_model(prefs) and budget:
                script_parts.append(f"""1.1 If model and budget is known:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {model} जैसी कार्स {budget} लाख के बजट में देख रहे थे। इसमें आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response to confirm, if user changes any pref change those preference and move to car pitching flow""")
            elif budget:
                script_parts.append(f"""1.2 If model is unknown, but budget is known and any of transmission or fuel is available or not available:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {budget} लाख के बजट में {fuel} {trans} वाली कार्स देख रहे थे। इसमें आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response to confirm, if user changes any pref change those preference and move to car pitching flow""")
            else:
                script_parts.append("""Budget unknown — ask for preferences:
Move to full preference collection → car pitching flow""")

            # YES branch
            script_parts.append("""
2. If Customer says YES""")

            if not liked_cars_info:
                script_parts.append("""
No liked cars could be resolved from API:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH""")
            else:
                script_parts.append(f"""
--- Liked Cars Info (fetched from API, total: {len(liked_cars_info)}) ---""")
                for c in liked_cars_info:
                    st = "AVAILABLE" if not c.get("booked", True) else "BOOKED"
                    script_parts.append(f"""  car_id={c['car_id']}, {_to_words(c.get('year',''))} {c.get('make','')} {c.get('model','')}, price={_format_price(c.get('price',''))}, status={st}""")

                if len(liked_cars_info) == 1:
                    c = liked_cars_info[0]
                    year_model = f"{_to_words(c.get('year',''))} {c.get('make','')} {c.get('model','')}"
                    price_str = _format_price(c.get("price", ""))

                    script_parts.append(f"""
2.1 If single car in comments.liked_cars_id:""")
                    if not c.get("booked", True):
                        script_parts.append(f"""Bot: "आप प्लीज़ कन्फर्म कीजिए <break time="0.3s" /> क्या आप {price_str} वाली {year_model} के साथ आगे बढ़ना चाहेंगे?"
Wait for users response

2.1.1 If customer agrees to move ahead with this car:
Bot: "मैं आपको इस कार के डिटेल्स बता देती हूँ या टेस्ट ड्राइव शेड्यूल कर देती हूँ?"
Wait for users response then based on response move to car details pitch or test drive scheduling block""")
                    else:
                        script_parts.append(f"""NOTE: This car (car_id={c['car_id']}) is BOOKED.
Bot: "वो कार अभी booked हो चुकी है। क्या आप similar cars देखना चाहेंगे?"
→ confirm preferences → car pitching flow""")

                    script_parts.append("""
2.1.2 If customer says no, not this car and there are no more car to map:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH""")

                else:
                    car_descs = []
                    for _c in liked_cars_info:
                        _yr = _to_words(_c.get('year', ''))
                        _mk = _c.get('make', '')
                        _md = _c.get('model', '')
                        _pr = _format_price(_c.get('price', ''))
                        _pr_part = f" जिसकी price {_pr} है" if _pr else ''
                        car_descs.append(f"{_yr} की {_mk} {_md}{_pr_part}")
                    cars_with_price = ", और ".join(car_descs)
                    booked_cars = [c for c in liked_cars_info if c.get("booked", True)]

                    script_parts.append(f"""
2.2 If multiple cars in comments.liked_cars_id:
Bot: "मुझे {len(liked_cars_info)} कार्स दिख रही हैं जिनके बारे में पिछली बार आपसे बात हुई थी <break time="0.3s" /> {cars_with_price} — क्या आप इनमें से किसी एक के साथ आगे बढ़ना चाहेंगे, या मैं आपको इनके डिटेल्स बता दूँ?"
Wait for users response then based on response move to car details pitch or test drive scheduling block if car is among these""")

                    if booked_cars:
                        booked_ids = [c["car_id"] for c in booked_cars]
                        script_parts.append(f"""NOTE: Cars {booked_ids} are BOOKED. If user picks a booked car, inform and offer alternatives.""")

                    script_parts.append("""
2.2.1 If customer says no, not any car among this two and there are no more car to map:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH""")

            script = "\n".join(script_parts)
            return greeting, script, f"S11_CAR_PITCHED_{cd.upper()}"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 12: car_pitched + td_timeline_2 (callback variant)
        # SQL-Script.md Lines 364-409
        # milestone_data.milestone.name = verified_lead
        # comment.milestone = car_pitched
        # comment.disposition = td_timeline_2
        # milestone_data.status.name != (uar_broken_transaction || uar_shortlist)
        #
        # NOTE: In SQL-Script.md this is described as car_pitched + td_timeline_2
        # The greeting references "आपने Callback request की थी।" — this is the
        # exact text from the doc line 370.
        # ──────────────────────────────────────────────────────────────────────
        if (milestone == "lead_verified" and cm == "car_pitched" and cd == "callback_requested"
                and status not in ("uar_broken_transaction", "uar_shortlist")):

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। <break time="0.5s" /> आपने Callback request की थी और मैंने पहले आपके साथ कुछ cars भी शेयर की थीं। क्या अभी उस पर बात कर सकते हैं?'

            liked_cars_info = await _fetch_liked_cars_info()

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: VERIFIED_LEAD + CAR_PITCHED + CALLBACK (TD_TIMELINE_2 variant from SQL-Script.md)

If user agrees to proceed:
Bot: "क्या उन कार्स में से आपको कोई पसंद आई?"
Wait for users response""")

            # NO branch
            script_parts.append("""
1. If Customer says NO (didn't like cars):
Bot: "कोई बात नहीं, मैं आपको और कार्स दिखा देती हूँ।"
""")
            if _has_model(prefs) and budget:
                script_parts.append(f"""1.1 If model and budget is known:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {model} जैसी कार्स {budget} लाख के बजट में देख रहे थे। इसमें आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response to confirm, if user changes any pref change those preference and move to car pitching flow""")
            elif budget:
                script_parts.append(f"""1.2 If model is unknown, but budget is known and any of transmission or fuel is available or not available:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.3s" /> आप {budget} लाख के बजट में {fuel} {trans} वाली कार्स देख रहे थे। इसमें आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response to confirm, if user changes any pref change those preference and move to car pitching flow""")
            else:
                script_parts.append("""Budget unknown — ask for preferences:
Move to full preference collection → car pitching flow""")

            # YES branch
            script_parts.append("""
2. If Customer says YES""")

            if not liked_cars_info:
                script_parts.append("""
No liked cars could be resolved from API:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH""")
            else:
                script_parts.append(f"""
--- Liked Cars Info (fetched from API, total: {len(liked_cars_info)}) ---""")
                for c in liked_cars_info:
                    st = "AVAILABLE" if not c.get("booked", True) else "BOOKED"
                    script_parts.append(f"""  car_id={c['car_id']}, {_to_words(c.get('year',''))} {c.get('make','')} {c.get('model','')}, price={_format_price(c.get('price',''))}, status={st}""")

                if len(liked_cars_info) == 1:
                    c = liked_cars_info[0]
                    year_model = f"{_to_words(c.get('year',''))} {c.get('make','')} {c.get('model','')}"
                    price_str = _format_price(c.get("price", ""))

                    script_parts.append(f"""
2.1 If single car in comments.liked_cars_id:""")
                    if not c.get("booked", True):
                        script_parts.append(f"""Bot: "आप प्लीज़ कन्फर्म कीजिए <break time="0.4s" /> क्या आप {price_str} वाली {year_model} के साथ आगे बढ़ना चाहेंगे?"
Wait for users response

2.1.1 If customer agrees to move ahead with this car:
Bot: "मैं आपको इस कार के डिटेल्स बता देती हूँ या टेस्ट ड्राइव शेड्यूल कर देती हूँ?"
Wait for users response then based on response move to car details pitch or test drive scheduling block""")
                    else:
                        script_parts.append(f"""NOTE: This car (car_id={c['car_id']}) is BOOKED.
Bot: "वो कार अभी booked हो चुकी है। क्या आप similar cars देखना चाहेंगे?"
→ confirm preferences → car pitching flow""")

                    script_parts.append("""
2.1.2 If customer says no, not this car and there are no more car to map:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH""")

                else:
                    car_descs = []
                    for _c in liked_cars_info:
                        _yr = _to_words(_c.get('year', ''))
                        _mk = _c.get('make', '')
                        _md = _c.get('model', '')
                        _pr = _format_price(_c.get('price', ''))
                        _pr_part = f" जिसकी price {_pr} है" if _pr else ''
                        car_descs.append(f"{_yr} की {_mk} {_md}{_pr_part}")
                    cars_with_price = ", और ".join(car_descs)
                    booked_cars = [c for c in liked_cars_info if c.get("booked", True)]

                    script_parts.append(f"""
2.2 If multiple cars in comments.liked_cars_id:
Bot: "मुझे {len(liked_cars_info)} कार्स दिख रही हैं जिनके बारे में पिछली बार आपसे बात हुई थी <break time="0.3s" /> {cars_with_price} — क्या आप इनमें से किसी एक के साथ आगे बढ़ना चाहेंगे, या मैं आपको इनके डिटेल्स बता दूँ?"
Wait for users response then based on response move to car details pitch or test drive scheduling block if car is among these""")

                    if booked_cars:
                        booked_ids = [c["car_id"] for c in booked_cars]
                        script_parts.append(f"""NOTE: Cars {booked_ids} are BOOKED. If user picks a booked car, inform and offer alternatives.""")

                    script_parts.append("""
2.2.1 If customer says no, not any car among this two and there are no more car to map:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH""")

            script = "\n".join(script_parts)
            return greeting, script, "S12_CAR_PITCHED_CALLBACK"

        # ──────────────────────────────────────────────────────────────────────
        # SCENARIO 13: car_pitched + out_of_city
        # SQL-Script.md Lines 411-451
        # milestone_data.milestone.name = verified_lead
        # comment.milestone = car_pitched
        # comment.disposition = out_of_city
        # milestone_data.status.name != (uar_broken_transaction || uar_shortlist)
        # ──────────────────────────────────────────────────────────────────────
        if (milestone == "lead_verified" and cm == "car_pitched" and cd == "out_of_city"
                and status not in ("uar_broken_transaction", "uar_shortlist")):

            greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। पिछली बार कुछ कार्स आपके साथ शेयर की थीं, तब आप आउट ऑफ सिटी थे। <break time="1s" /> क्या उन कार्स में से आपको कोई पसंद आई?'

            liked_cars_info = await _fetch_liked_cars_info()

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: VERIFIED_LEAD + CAR_PITCHED + OUT_OF_CITY""")

            # NO branch
            script_parts.append("""
1. If Customer says NO (didn't like cars):
Bot: "कोई बात नहीं, मैं आपको और कार्स दिखा देती हूँ।"
""")
            if _has_model(prefs) and budget:
                script_parts.append(f"""1.1 If model and budget is known:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.4s" /> आप {model} जैसी कार्स {budget} लाख के बजट में देख रहे थे। इसमें आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response to confirm, if user changes any pref change those preference and move to car pitching flow""")
            elif budget:
                script_parts.append(f"""1.2 If model is unknown, but budget is known and any of transmission or fuel is available or not available:
Bot: "पिछली बार आपसे बात हुई थी <break time="0.4s" /> आप {budget} लाख के बजट में {fuel} {trans} वाली कार्स देख रहे थे। इसमें आप कुछ चेंज या ऐड करना चाहेंगे?"
Wait for users response to confirm, if user changes any pref change those preference and move to car pitching flow""")
            else:
                script_parts.append("""Budget unknown — ask for preferences:
Move to full preference collection → car pitching flow""")

            # YES branch
            script_parts.append("""
2. If Customer says YES""")

            if not liked_cars_info:
                script_parts.append("""
No liked cars could be resolved from API:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed directly to SECTION 5 — CAR SEARCH""")
            else:
                script_parts.append(f"""
--- Liked Cars Info (fetched from API, total: {len(liked_cars_info)}) ---""")
                for c in liked_cars_info:
                    st = "AVAILABLE" if not c.get("booked", True) else "BOOKED"
                    script_parts.append(f"""  car_id={c['car_id']}, {_to_words(c.get('year',''))} {c.get('make','')} {c.get('model','')}, price={_format_price(c.get('price',''))}, status={st}""")

                if len(liked_cars_info) == 1:
                    c = liked_cars_info[0]
                    year_model = f"{_to_words(c.get('year',''))} {c.get('make','')} {c.get('model','')}"
                    price_str = _format_price(c.get("price", ""))

                    script_parts.append(f"""
2.1 If single car in comments.liked_cars_id:""")
                    if not c.get("booked", True):
                        script_parts.append(f"""Bot: "आप प्लीज़ कन्फर्म कीजिए <break time="0.4s" /> क्या आप {price_str} वाली {year_model} के साथ आगे बढ़ना चाहेंगे?"
Wait for users response

2.1.1 If customer agrees to move ahead with this car:
Bot: "मैं आपको इस कार के डिटेल्स बता देती हूँ या टेस्ट ड्राइव शेड्यूल कर देती हूँ?"
Wait for users response then based on response move to car details pitch or test drive scheduling block""")
                    else:
                        script_parts.append(f"""NOTE: This car (car_id={c['car_id']}) is BOOKED.
Bot: "वो कार अभी booked हो चुकी है। क्या आप similar cars देखना चाहेंगे?"
→ confirm preferences → car pitching flow""")

                    script_parts.append("""
2.1.2 If customer says no, not this car and there are no more car to map:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH""")

                else:
                    car_descs = []
                    for _c in liked_cars_info:
                        _yr = _to_words(_c.get('year', ''))
                        _mk = _c.get('make', '')
                        _md = _c.get('model', '')
                        _pr = _format_price(_c.get('price', ''))
                        _pr_part = f" जिसकी price {_pr} है" if _pr else ''
                        car_descs.append(f"{_yr} की {_mk} {_md}{_pr_part}")
                    cars_with_price = ", और ".join(car_descs)
                    booked_cars = [c for c in liked_cars_info if c.get("booked", True)]

                    script_parts.append(f"""
2.2 If multiple cars in comments.liked_cars_id:
Bot: "मुझे {len(liked_cars_info)} कार्स दिख रही हैं जिनके बारे में पिछली बार आपसे बात हुई थी <break time="0.3s" /> {cars_with_price} — क्या आप इनमें से किसी एक के साथ आगे बढ़ना चाहेंगे, या मैं आपको इनके डिटेल्स बता दूँ?"
Wait for users response then based on response move to car details pitch or test drive scheduling block if car is among these""")

                    if booked_cars:
                        booked_ids = [c["car_id"] for c in booked_cars]
                        script_parts.append(f"""NOTE: Cars {booked_ids} are BOOKED. If user picks a booked car, inform and offer alternatives.""")

                    script_parts.append("""
2.2.1 If customer says no, not any car among this two and there are no more car to map:
Bot: "Sorry, मैं अभी और सजेस्टेड कार्स मैप नहीं कर पा रही हूँ आपके लिए।
क्या आप प्लीज़ बताएंगे आप कौन से मॉडल और प्राइस range की कार देख रहे हैं?"
Wait for users response if user wants to specify car again then proceed to SECTION 5 — CAR SEARCH""")

            script = "\n".join(script_parts)
            return greeting, script, "S13_CAR_PITCHED_OUT_OF_CITY"

        # ──────────────────────────────────────────────────────────────────────
        # TDC_FOLLOWUP: visit_cancelled (from paste.txt)
        # milestone_data.milestone.name = verified_lead
        # milestone_data.task.name = visit_cancelled
        # ──────────────────────────────────────────────────────────────────────
        if milestone == "lead_verified" and task == "visit_cancelled":
            greeting = 'Hello. <break time="0.5s" /> मैं Priya बात कर रही हूँ Spinny से। मैं देख पा रही हूँ कि आपने हमारे साथ एक टेस्ट ड्राइव बुक की थी, पर वो cancel हो गई, <break time="0.7s" /> क्या मैं आपकी कुछ help कर सकती हूँ?'
            script = f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: TDC_FOLLOWUP
Probe reason for cancellation.
Offer reschedule / alternatives / re-qualify.
If interested → confirm preferences → TD SCHEDULING."""
            return greeting, script, "TDC_FOLLOWUP"

        # ──────────────────────────────────────────────────────────────────────
        # ──────────────────────────────────────────────────────────────────────
        # S_LEAD_VERIFIED_NO_HISTORY: lead_verified + no previous robo call
        # Applies when: milestone=lead_verified, cm is empty (no Robo Call Summary),
        # status is not uar_broken_transaction or uar_shortlist.
        # Handles both: preferences available (confirm + partial pref) and
        # no preferences (full preference collection).
        # ──────────────────────────────────────────────────────────────────────
        if milestone == "lead_verified" and not cm:

            greeting = f'Hello. मैं प्रिया बोल रही हूँ Spinny {city} team से। आपने spinny पे cars देखी थीं, इसलिए आपकी कार selection में help के लिए call किया। क्या अभी दो मिनट बात हो सकती है?'

            script_parts = []
            script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: S_LEAD_VERIFIED_NO_HISTORY (lead_verified, no Robo Call Summary, status={status})

If user disagrees or doesn't want help:
Bot: "आप अपना convenient time बता दीजिए, मैं उस time connect कर लूंगी।"
Wait for users response and capture callback time

If user agrees:""")

            if has_prefs:
                # Preferences available — confirm before proceeding
                script_parts.append("\n1. When preferences are available:")
                if is_multi:
                    script_parts.append(f"""Ask locality first (multi-hub city):
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response. After locality confirmed:
Bot: "जैसे कि मैं देख पा रही हूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन preferences में आप कुछ चेंज या add करना चाहेंगे?"
Wait for users response then move to partial preference collection or car pitching flow""")
                else:
                    script_parts.append(f"""Single hub city — confirm preferences directly:
Bot: "जैसे कि मैं देख पा रही हूँ कि आप {budget} लाख के बजट में, {fuel} {trans} कार्स देख रहे हैं, क्या इन preferences में आप कुछ चेंज या add करना चाहेंगे?"
Wait for users response then move to partial preference collection or car pitching flow""")
            else:
                # No preferences — full preference collection
                script_parts.append("\n2. When no preferences are available:")
                if is_multi:
                    script_parts.append(f"""Ask locality first (multi-hub city):
Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response, then move to full preference collection""")
                else:
                    script_parts.append(f"""Single hub city — confirm city and collect preferences:
Bot: "आप {city} में ही car देख रहे हैं ना?"
Wait for users response then move to full preference collection""")

            script = "\n".join(script_parts)
            return greeting, script, "S_LEAD_VERIFIED_NO_HISTORY"

        # FALLBACK — unmatched conditions
        # ──────────────────────────────────────────────────────────────────────
        greeting = f'Hello. <break time="0.5s" /> मैं प्रिया बोल रही हूँ Spinny {city} team से। आपने spinny पे cars देखी थीं, इसलिए आपकी कार selection में help के लिए call कर रहीहूँ। <break time="0.7s" /> क्या अभी दो मिनट बात हो सकती है?'

        script_parts = []
        script_parts.append(f"""Say this VERBATIM as your first utterance:
Bot: "{greeting}"
Then PAUSE and wait for customer response.

SCENARIO: FALLBACK (unmatched conditions — milestone={milestone}, task={task}, status={status}, cm={cm}, cd={cd})

If user disagree or dont want any help:
Bot: "आप अपना convenient time बता दीजिए, मैं उस time connect कर लूंगी।"
Wait for users response and capture callback time

If user agrees:""")

        if is_multi:
            script_parts.append(f"""Bot: "आप {city} में कौन से area से बात कर रहे हैं?"
Wait for users response, then move to full preference collection""")
        else:
            script_parts.append(f"""Bot: "आप {city} में ही car देख रहे हैं ना?"
Wait for users response, then move to full preference collection""")

        script = "\n".join(script_parts)
        return greeting, script, "FALLBACK"

    # ═══════════════════════════════════════════════════════════════════════════
    # MAIN LOGIC
    # ═══════════════════════════════════════════════════════════════════════════

    final_prompt = system_prompt

    # ── Step 1: Resolve basics ──
    logger.info("[PCF] Step 1 START")
    city = _get_city()
    logger.info(f"[PCF] city={city}")
    is_multi = _is_multi_hub(city)
    logger.info(f"[PCF] is_multi={is_multi}")
    logger.info("[PCF] calling _build_resolved_preferences")
    prefs = _build_resolved_preferences()
    logger.info(f"[PCF] prefs resolved, count={len(prefs)}")
    logger.info("[PCF] calling _get_effective_budget")
    budget = _get_effective_budget(prefs)
    logger.info(f"[PCF] budget={budget}")
    logger.info("[PCF] calling _get_comment_milestone")
    cm = _get_comment_milestone()
    logger.info(f"[PCF] cm={cm}")
    cd = _get_comment_disposition()
    logger.info(f"[PCF] cd={cd}")
    status = str(_g("milestone_data.status.name", "")).lower().strip()
    logger.info(f"[PCF] raw_status={status}")
    _, robo_data = _find_latest_robo_summary()
    logger.info("[PCF] Step 1 COMPLETE")

    # ── Step 2: Scan all_visits ──
    logger.info("[PCF] Step 2 START — scanning all_visits")
    scheduled_visits = _scan_scheduled_visits()
    logger.info(f"[PCF] scheduled_visits count={len(scheduled_visits)}")

    # ── Step 2a: Route scenario ──
    logger.info("[PCF] Step 2a START — routing")
    greeting, full_script, scenario_id = await _route_scenario(city, is_multi, prefs, budget, scheduled_visits)
    logger.info(f"[PCF] Step 2a COMPLETE — scenario={scenario_id}")

    metadata["added_scenario"] = scenario_id

    # ── Inbound call: inject acknowledgement after intro line ──
    # call_type = "inbound" → add "अच्छा लगा आपने call किया।" right after
    # "Spinny X team से।" (or "Spinny से।" for TDC) before the next sentence
    if str(_g("call_type", "")).lower() == "inbound" and "से।" in greeting:
        greeting = greeting.replace("से।", "से। अच्छा लगा आपने call किया।", 1)

    # ── Step 2b: Fetch inventory car details ──
    # Two separate fetches:
#   {inventory_car_details} — for uar_broken_transaction (car_1/car_2/car_3) or generic liked_cars
#   {whatsapp_cars_info}    — ONLY for cm=car_pitched; uses liked_cars_id from Robo Call Summary
#                             gives colour, price, transmission for previously sent WhatsApp cars

    inventory_car_details: list[dict] = []
    if "{inventory_car_details}" in final_prompt:
        try:
            ids_to_fetch = (
                _get_car_slot_ids()
                if status == "uar_broken_transaction"
                else _get_liked_cars_ids()
            )
            if ids_to_fetch:
                inventory_car_details = await _fetch_car_details_from_inventory(ids_to_fetch)
        except Exception as inv_err:
            logger.warning(f"Inventory fetch failed: {inv_err}")

    # Build scheduled visits block (visits already scanned in Step 2)
    scheduled_visits_block = await _build_scheduled_visits_block(scheduled_visits)

    # whatsapp_cars_info — only for car_pitched scenarios
    # 3-level fallback: liked_cars_id → pitched_car_ids → car_1/car_2/car_3
    whatsapp_cars_raw: list[dict] = []
    _whatsapp_source = "whatsapp"  # tracks source for greeting wording
    if cm == "car_pitched":
        try:
            wa_ids = _get_liked_cars_ids()
            if wa_ids:
                whatsapp_cars_raw = await _fetch_car_details_from_inventory(wa_ids)
                _whatsapp_source = "whatsapp"
            else:
                # Fallback to pitched_car_ids
                pitched_ids_fb = _get_pitched_cars_ids()[-3:]
                if pitched_ids_fb:
                    whatsapp_cars_raw = await _fetch_car_details_from_inventory(pitched_ids_fb)
                    _whatsapp_source = "pitched"
                else:
                    # Final fallback: car_1/car_2/car_3 from metadata
                    slot_ids_fb = _get_car_slot_ids()
                    if slot_ids_fb:
                        whatsapp_cars_raw = await _fetch_car_details_from_inventory(slot_ids_fb)
                        _whatsapp_source = "pitched"
        except Exception as wa_err:
            logger.warning(f"WhatsApp/pitched cars fetch failed: {wa_err}")

    # ── Step 3: Build context blocks ──
    ctx_lines = []
    ctx_lines.append(f"scenario = {scenario_id}")
    ctx_lines.append(f"city = {city}")
    ctx_lines.append(f"city_type = {'multi_hub' if is_multi else 'single_hub'}")
    ctx_lines.append(f"milestone = {_g('milestone_data.milestone.name', '')}")
    ctx_lines.append(f"task = {_g('milestone_data.task.name', '')}")
    ctx_lines.append(f"status = {_g('milestone_data.status.name', '')}")
    ctx_lines.append(f"comment_milestone = {cm or 'null'}")
    ctx_lines.append(f"comment_disposition = {cd or 'null'}")

    hub = _g("hub_name", "")
    if hub:
        ctx_lines.append(f"hub_name = {hub}")
    mm = _g("make_model", "")
    if mm:
        ctx_lines.append(f"make_model = {mm}")
    if budget:
        ctx_lines.append(f"effective_budget = {budget}")

    prefs_block = _prefs_to_context_block(prefs)
    if prefs_block != "No preferences available.":
        ctx_lines.append(f"\n--- Resolved Preferences (agent > customer) ---\n{prefs_block}")

    ctx_lines.append(f"\n--- Previous Interactions ---\n{_build_previous_interactions()}")

    liked_ids = _get_liked_cars_ids()
    if liked_ids:
        ctx_lines.append(f"\nliked_cars_id = {','.join(liked_ids)}")
    pitched_ids = _get_pitched_cars_ids()
    if pitched_ids:
        ctx_lines.append(f"pitched_cars_id = {','.join(pitched_ids)}")
    rejected_ids = _get_rejected_cars_ids()
    if rejected_ids:
        ctx_lines.append(f"rejected_cars_id = {','.join(rejected_ids)}")

    for prefix in ("car_1", "car_2", "car_3"):
        car_str = _format_car(prefix)
        if car_str != "none":
            ctx_lines.append(f"{prefix} = {car_str}")

    visit_status = _g("visit_data.status", "")
    if visit_status:
        time_str, day_label, is_today = _format_visit_time_ist()
        ctx_lines.append(f"\nvisit_status = {visit_status}")
        ctx_lines.append(f"visit_time_ist = {day_label} {time_str}")
        ctx_lines.append(f"visit_type = {_g('visit_type', _g('visit_data.visit_type', ''))}")

    exchange = _build_exchange_context()
    if exchange != "none":
        ctx_lines.append(f"\nexchange_context = {exchange}")

    # Scheduled visits summary in context block
    if scheduled_visits:
        ctx_lines.append(f"\n--- Scheduled Test Drives ---\n{scheduled_visits_block}")

    call_context_block = "\n".join(ctx_lines)

    # Flags block
    flag_lines = []
    flag_lines.append(f"scenario = {scenario_id}")
    flag_lines.append(f"city_type = {'multi_hub' if is_multi else 'single_hub'}")
    flag_lines.append(f"has_preferences = {len(prefs) > 0}")
    if budget:
        flag_lines.append(f"budget_set = true ({budget})")
    if prefs.get("fuel_type"):
        flag_lines.append(f"fuel_set = true ({prefs['fuel_type']})")
    if prefs.get("transmission"):
        flag_lines.append(f"transmission_set = true ({prefs['transmission']})")
    if prefs.get("make"):
        flag_lines.append(f"make_set = true ({prefs['make']})")
    if cm:
        flag_lines.append(f"comment_milestone = {cm}")
    if cd:
        flag_lines.append(f"comment_disposition = {cd}")
    if liked_ids:
        flag_lines.append(f"has_liked_cars = true (count={len(liked_ids)})")
    if exchange != "none":
        flag_lines.append("has_exchange_data = true")
    flags_block = "\n".join(flag_lines)

    # ── Step 4: Replace structural placeholders ──

    # Build scenario-specific pre-call preference section
    _fuel_str  = _pref_fuel(prefs)
    _trans_str = _pref_trans(prefs)
    _model_str = _pref_make(prefs)
    pre_call_pref_section = _build_pre_call_pref_section(
        comment_milestone=cm,
        multi_hub=is_multi,
        resolved_prefs=prefs,
        effective_budget=budget,
        fuel_str=_fuel_str,
        trans_str=_trans_str,
        model_str=_model_str,
        city_str=city,
    )

    # Build inventory car details block
    if inventory_car_details:
        inv_block = "\n\n".join(
            f"Car {i + 1}\n{_format_inventory_car_summary(c)}"
            for i, c in enumerate(inventory_car_details)
        )
    else:
        inv_block = "No car details available from inventory."

    # Build whatsapp cars info block (car_pitched scenarios only)
    whatsapp_cars_block = _build_whatsapp_cars_info(whatsapp_cars_raw)

    final_prompt = final_prompt.replace("{greeting}", greeting)
    final_prompt = final_prompt.replace("{call_context_block}", call_context_block)
    final_prompt = final_prompt.replace("{next_steps}", full_script)
    final_prompt = final_prompt.replace("{flags_block}", flags_block)
    final_prompt = final_prompt.replace("{opening_section}", full_script)
    final_prompt = final_prompt.replace("{preferences_block}", _prefs_to_context_block(prefs))

    # ── Step 5: Replace individual field placeholders ──
    today, tomorrow, day_after = _today_tomorrow_dayafter()
    time_str, day_label, is_today = _format_visit_time_ist()
    fuel = _pref_fuel(prefs)
    trans = _pref_trans(prefs)

    field_replacements = {
        "{scheduled_visits_block}": scheduled_visits_block,
        "{pre_call_pref_section}": pre_call_pref_section,
        "{whatsapp_cars_info}": whatsapp_cars_block,
        "{inventory_car_details}": inv_block,
        "{pref_max_price}": _format_price(prefs.get("max_price", "")),
        "{pref_min_price}": _format_price(prefs.get("min_price", "")),
        "{pref_fuel_type}": fuel,
        "{pref_transmission}": trans,
        "{pref_body_type}": str(prefs.get("body_type", "")),
        "{pref_make}": _pref_make(prefs),
        "{pref_no_of_owners}": str(prefs.get("no_of_owners", "")),
        "{budget}": budget,
        "{fuel}": fuel,
        "{transmission}": trans,
        "{model}": _pref_make(prefs),
        "{city}": city,
        "{hub_name}": _g("hub_name", ""),
        "{make_model}": _g("make_model", ""),
        "{car_price}": _format_price(_g("car_price", "")),
        "{body_type}": _g("body_type", ""),
        "{registration_year}": _to_words(_g("registration_year", "")),
        "{km_driven}": _km_to_words(_g("km_driven", "")),
        # "{owner_count}": str(_g("owner_count", "")),
        "{RTO}": _g("RTO", ""),
        "{user_id}": _g("user_id", ""),
        "{visit_id}": _g("visit_id", ""),
        "{visit_time}": f"{day_label} {time_str}",
        "{visit_day}": day_label,
        "{visit_time_clock}": time_str,
        "{visit_type}": _g("visit_type", ""),
        "{how_to_reach}": _g("how_to_reach", ""),
        "{lead_id}": _g("lead_id", ""),
        "{buylead}": str(_g("buylead", "")),
        "{car_1}": _format_car("car_1"),
        "{car_2}": _format_car("car_2"),
        "{car_3}": _format_car("car_3"),
        "{primary_car}": _g("make_model", ""),
        "{visit_status}": _g("visit_data.status", ""),
        "{exchange_context}": _build_exchange_context(),
        "{interested_in_loan}": str(_g("interested_in_loan", "false")),
        "{disposition}": cd,
        "{comment_milestone}": cm,
        "{previous_call_context}": _build_previous_interactions(),
        "{scenario_id}": scenario_id,
        "{today_date}": today,
        "{tomorrow_date}": tomorrow,
        "{day_after_tomorrow_date}": day_after,
        "{discount}": "no discount",
        "{discount_instruction}": "",
        "{token_amount}": "",
        "{slot_booking_instruction}": "",
        "{customer_name}": "aap",
    }

    for placeholder, value in field_replacements.items():
        if placeholder in final_prompt:
            final_prompt = final_prompt.replace(placeholder, str(value) if value else "")

    # ── Step 6: Log ──
    logger.info(
        f"prepare_call_context v7.2: scenario={scenario_id}, city={city}, "
        f"multi_hub={is_multi}, cm={cm}, cd={cd}, prefs={len(prefs)}, budget={budget}"
    )

    return final_prompt
