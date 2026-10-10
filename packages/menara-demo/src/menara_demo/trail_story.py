"""Trail narration: the backend gathers the facts, a model only writes them up.

A trail is cell level (a tower position, accurate to about a kilometre or more), so the model is never asked to know
the world. It is given each stop, the hour of day, and the known sites (from sites-mcp) near each tower, and told to use
only those. In the demo data the sites are synthetic (hospital, clinic, police, school, enterprise). All data is synthetic.
"""

from __future__ import annotations

import json
from typing import Any

from menara_agent.loop import ChatClient
from menara_core.geo import bbox_around, haversine_km

from menara_demo.app_types import Hub

NEARBY_KM = 2.5
MAX_NEARBY = 5

RULES = (
    "You write a short, plain-language story of one subscriber's day from FACTS. Rules: "
    "1) Use only the places listed under nearby_sites; never invent or recall other place names. "
    "2) Locations are cell level and only accurate to about a kilometre or more, so say 'near' a place, never 'at' it, "
    "and call a visit likely, not certain. "
    "3) A long stay overnight or in the evening on one tower is probably home; a long daytime stay is probably work or study. "
    "4) If a tower has no known site nearby, say there is no known site near it instead of guessing. "
    "5) Mention times as written in the facts. Keep it to a short paragraph or a few bullets. "
    "6) All of this is synthetic demo data; add one closing line saying so."
)


class StoryError(Exception):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _parse(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except ValueError as error:
        raise StoryError("Unexpected reply from a tool", 502) from error
    data = parsed.get("data") if isinstance(parsed, dict) else None
    if not isinstance(data, dict):
        raise StoryError("Unexpected reply from a tool", 502)
    return data


async def build_facts(hub: Hub, msisdn_hash: str, window_min: int) -> dict[str, Any]:
    try:
        trail = _parse(await hub.call("user_get_trail", {"msisdn_hash": msisdn_hash, "window_min": window_min}))
    except StoryError:
        raise
    except Exception as error:
        message = str(error)
        raise StoryError(message, 404 if "not found" in message.lower() else 400) from error

    segments: list[dict[str, Any]] = []
    positions: dict[str, tuple[float, float]] = {}
    for seg in trail["segments"]:
        hour = int(str(seg["arrived_at"])[11:13])
        positions[seg["enodeb_name"]] = (seg["cell_lat"], seg["cell_lng"])
        segments.append(
            {
                "tower": seg["enodeb_name"],
                "arrived_at": seg["arrived_at"],
                "left_at": seg["left_at"],
                "minutes": seg["duration_min"],
                "hour": hour,
                "part_of_day": part_of_day(hour),
                "current": seg["current"],
            }
        )

    towers: list[dict[str, Any]] = []
    for tower, (lat, lng) in positions.items():
        box = bbox_around(lat, lng, NEARBY_KM)
        found = _parse(
            await hub.call(
                "sites_list_in_bbox",
                {"min_lat": box[0], "min_lng": box[1], "max_lat": box[2], "max_lng": box[3], "limit": 50},
            )
        )["sites"]
        nearby = sorted(
            (
                {"name": s["name"], "kind": s["kind"], "distance_km": round(haversine_km(lat, lng, s["lat"], s["lng"]), 2)}
                for s in found
            ),
            key=lambda s: s["distance_km"],
        )
        towers.append({"tower": tower, "nearby_sites": [s for s in nearby if s["distance_km"] <= NEARBY_KM][:MAX_NEARBY]})

    return {
        "window_start": trail["window_start"],
        "segments": segments,
        "towers": towers,
        "precision": "cell level (tower position)",
        "note": "no known site" if not any(t["nearby_sites"] for t in towers) else "",
    }


async def tell(llm: ChatClient, facts: dict[str, Any]) -> str:
    user = (
        "FACTS (JSON). A tower with an empty nearby_sites list has no known site nearby.\n"
        + json.dumps(facts, indent=1)
        + "\nWrite the story now."
    )
    reply = await llm.complete([{"role": "system", "content": RULES}, {"role": "user", "content": user}], [])
    return (reply.content or "").strip()