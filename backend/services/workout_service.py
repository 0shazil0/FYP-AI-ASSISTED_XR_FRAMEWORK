"""
WorkoutX Exercise API Service
------------------------------
Fetches exercises from api.workoutxapp.com with in-memory caching (TTL 1 hour).

IMPORTANT – WorkoutX uses PATH-based filter endpoints, not query params:
  GET /v1/exercises                            → list all (query: limit, offset)
  GET /v1/exercises/bodyPart/:bodyPart         → filter by body part
  GET /v1/exercises/target/:target             → filter by target muscle
  GET /v1/exercises/equipment/:equipment       → filter by equipment
  GET /v1/exercises/name/:name                 → search by name

Gym machine → bodyPart mapping:
  Flat Bench Press Machine    → bodyPart=chest
  Incline Bench Press Machine → bodyPart=chest
  Lat Pulldown Machine        → bodyPart=back
  Leg Press Machine           → bodyPart=upper legs
"""

from __future__ import annotations

import asyncio
import time
import httpx
from typing import Any
from urllib.parse import quote

from config import WORKOUTX_API_URL, WORKOUTX_API_KEY, WORKOUTX_TIMEOUT

# ── Machine → API params mapping ─────────────────────────────────────────────
# Use bodyPart path-based lookups (most reliable endpoint)
MACHINE_MAP: dict[str, dict[str, str]] = {
    "flat bench press machine":    {"bodyPart": "chest"},
    "incline bench press machine": {"bodyPart": "chest"},
    "lat pulldown machine":        {"bodyPart": "back"},
    "leg press machine":           {"bodyPart": "upper legs"},
}

_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 3600.0  # 1 hour


def _cache_key(**kwargs: str) -> str:
    return "|".join(f"{k}={v}" for k, v in sorted(kwargs.items()) if v)


def _from_cache(key: str) -> list[dict] | None:
    if key in _CACHE:
        ts, data = _CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            return data
        del _CACHE[key]
    return None


def _to_cache(key: str, data: list[dict]) -> None:
    _CACHE[key] = (time.time(), data)


class WorkoutService:
    """Thin async wrapper around the WorkoutX API."""

    def __init__(self) -> None:
        self._headers = {"X-WorkoutX-Key": WORKOUTX_API_KEY}
        print(f"[WorkoutService] initialized  url={WORKOUTX_API_URL}  key={WORKOUTX_API_KEY[:12]}...")

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_for_machine(self, machine_label: str, limit: int = 3) -> list[dict]:
        """Return exercises for a detected gym machine label. Returns [] on error."""
        key = machine_label.strip().lower()
        params = MACHINE_MAP.get(key, {})
        if not params:
            # generic fallback — search by name keyword
            keyword = key.replace(" machine", "").strip()
            return await self.search(name=keyword, limit=limit)
        return await self.search(limit=limit, **params)

    async def search(
        self,
        *,
        bodyPart: str = "",
        equipment: str = "",
        target: str = "",
        name: str = "",
        limit: int = 3,
    ) -> list[dict]:
        """
        Search exercises using the correct WorkoutX path-based endpoints.
        Priority order: bodyPart > equipment > target > name > list all
        Results are cached for 1 hour.
        """
        ck = _cache_key(bodyPart=bodyPart, equipment=equipment, target=target, name=name)
        cached = _from_cache(ck)
        if cached is not None:
            print(f"[WorkoutService] cache hit  key={ck}")
            return cached[:limit]

        # ── Build correct path-based URL ─────────────────────────────────────
        # WorkoutX API uses /v1/exercises/<filter_type>/<value> — NOT query params
        query_params: dict = {"limit": 20}
        if bodyPart:
            endpoint = f"{WORKOUTX_API_URL}/exercises/bodyPart/{quote(bodyPart, safe='')}"
        elif equipment:
            endpoint = f"{WORKOUTX_API_URL}/exercises/equipment/{quote(equipment, safe='')}"
        elif target:
            endpoint = f"{WORKOUTX_API_URL}/exercises/target/{quote(target, safe='')}"
        elif name:
            endpoint = f"{WORKOUTX_API_URL}/exercises/name/{quote(name, safe='')}"
        else:
            endpoint = f"{WORKOUTX_API_URL}/exercises"
            query_params["offset"] = 0

        print(f"[WorkoutService] GET {endpoint}  params={query_params}")

        try:
            async with httpx.AsyncClient(timeout=WORKOUTX_TIMEOUT) as client:
                resp = await client.get(endpoint, headers=self._headers, params=query_params)
                print(f"[WorkoutService] response  status={resp.status_code}  url={resp.url}")
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            print(f"[WorkoutService] fetch FAILED: {exc}")
            return []

        # Handle paginated response structure
        exercises_list = []
        if isinstance(data, dict):
            # Check if it's a paginated response with 'data' key
            if 'data' in data and isinstance(data['data'], list):
                exercises_list = data['data']
            else:
                print(f"[WorkoutService] unexpected dict response structure: {list(data.keys())}")
                return []
        elif isinstance(data, list):
            # Direct list response
            exercises_list = data
        else:
            print(f"[WorkoutService] unexpected response type: {type(data)}")
            return []

        cleaned = [self._clean(ex) for ex in exercises_list if isinstance(ex, dict)]
        _to_cache(ck, cleaned)
        print(f"[WorkoutService] fetched {len(cleaned)} exercises  key={ck}")
        return cleaned[:limit]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _clean(ex: dict) -> dict:
        """Normalise one exercise entry for Unity consumption."""
        instructions = ex.get("instructions", [])
        if isinstance(instructions, list):
            instructions = [str(i) for i in instructions[:4]]   # cap at 4 steps
        else:
            instructions = []

        secondary = ex.get("secondaryMuscles", [])
        if isinstance(secondary, list):
            secondary = [str(m) for m in secondary[:3]]
        else:
            secondary = []

        return {
            "id":               str(ex.get("id", "")),
            "name":             str(ex.get("name", "Exercise")),
            "bodyPart":         str(ex.get("bodyPart", "")),
            "target":           str(ex.get("target", "")),
            "equipment":        str(ex.get("equipment", "")),
            "gifUrl":           str(ex.get("gifUrl", "")),
            "instructions":     instructions,
            "secondaryMuscles": secondary,
        }

    @staticmethod
    def build_suggestions(machine_label: str) -> list[str]:
        """Return 3 coach-voice suggestion chips for a detected machine."""
        name = machine_label.title()
        return [
            f"💪 Show me exercises for the {name}",
            f"📋 Guide me through a {name} workout",
            f"🎯 What muscles does the {name} target?",
        ]