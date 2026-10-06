"""MCP server: BenriSpace as a connector for Claude (claude.ai, the desktop app, Claude Code).

    POST https://api.benrispace.com/mcp      JSON-RPC 2.0, MCP "Streamable HTTP" transport

Stateless and JSON-only, which suits Lambda: every request is answered with one JSON body
(no SSE stream, no session id), GET returns 405 as the spec allows for servers that do not
stream. Supported methods: initialize, ping, tools/list, tools/call, and empty
resources/list and prompts/list. Notifications get 202.

The tools are the ones Ask Benri uses (api/chat.py TOOLS, run through the same
`run_tool`, which never raises and rounds floats) plus two map features the chat has no tool
for: `travel_area` (how far you can get) and `triangulate` (where several travel-time areas
overlap). Everything is read-only and needs no login; API Gateway throttling applies.
Densities and place counts are internal and are not returned, same as the web app.
"""

from __future__ import annotations

import json
from typing import Any

from api.chat import TOOLS as CHAT_TOOLS
from api.chat import ToolError, run_tool, tool_geocode

SERVER_NAME = "benrispace"
SERVER_TITLE = "BenriSpace"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")  # newest first

INSTRUCTIONS = (
    "BenriSpace scores how convenient any place in the New York metro (New York, New Jersey "
    "and Connecticut, about two hours around the city) is, out of 100, from 13 factors: "
    "groceries, gym, cafes, restaurants, bars, shopping, gas & convenience, transit, schools, "
    "traffic, noise corridor, airport and recreation. Scores are on one scale for the whole "
    "region, measured by what is within a short walk (or a short drive in car-dependent "
    "areas). Use geocode first when you only have an address. Distances are in feet and "
    "miles. Scores are estimates from open data; suggest checking anything important in "
    "person. Link https://benrispace.com/app for the map."
)

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}

_PLACE = {
    "address": {"type": "string", "description": "Street address or place name (or give lat/lon)."},
    "latitude": {"type": "number"},
    "longitude": {"type": "number"},
}

EXTRA_TOOLS: list[dict] = [
    {
        "name": "travel_area",
        "description": (
            "How far you can get from a place in a number of minutes by walking, train "
            "(transit) or car, on the real road and rail network. Returns the reachable area "
            "in square miles and whether it is routed or a straight-line estimate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_PLACE,
                "mode": {"type": "string", "enum": ["walk", "transit", "drive"]},
                "minutes": {"type": "integer", "minimum": 5, "maximum": 120},
            },
            "required": ["mode", "minutes"],
        },
    },
    {
        "name": "triangulate",
        "description": (
            "Find the best-scoring places within reach of 2-4 anchors at once (for example "
            "work within 30 minutes by train and family within 45 minutes by car). Each anchor "
            "gets a travel-time area; returns where they overlap (or their union) and the "
            "top-scoring spots there."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "anchors": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            **_PLACE,
                            "mode": {"type": "string", "enum": ["walk", "transit", "drive"]},
                            "maxTravelMinutes": {"type": "integer", "minimum": 5, "maximum": 120},
                        },
                        "required": ["label", "mode", "maxTravelMinutes"],
                    },
                },
                "combineMode": {"type": "string", "enum": ["intersect", "union"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["anchors"],
        },
    },
]


def _point(args: dict) -> tuple[float, float]:
    lat, lon = args.get("latitude"), args.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return float(lat), float(lon)
    address = str(args.get("address") or "").strip()
    if not address:
        raise ToolError("Give an address or latitude and longitude.")
    found = tool_geocode({"query": address}, None)
    return found["latitude"], found["longitude"]


def tool_travel_area(args: dict) -> dict:
    from api.triangulate import anchor_cells, shape_for
    from common.db import get_connection

    lat, lon = _point(args)
    mode = args.get("mode")
    if mode not in ("walk", "transit", "drive"):
        raise ToolError("mode must be walk, transit or drive")
    with get_connection() as conn:
        cells, minutes, method = anchor_cells(conn, lat, lon, mode, int(args.get("minutes") or 15))
    shape = shape_for(cells, None, mode, minutes, method, lat)
    return {
        "latitude": lat,
        "longitude": lon,
        "mode": mode,
        "minutes": minutes,
        "areaSqMi": shape["area_sq_mi"],
        "method": "routed" if method == "network" else "straight-line estimate",
        "mapUrl": f"https://benrispace.com/app?center={lat:.5f},{lon:.5f}&z=13",
    }


def tool_triangulate(args: dict) -> dict:
    from api import slim_areas
    from api.main import triangulate
    from api.schemas import TriangulateRequest
    from common.db import get_connection

    anchors = []
    for a in args.get("anchors") or []:
        if not isinstance(a, dict):
            raise ToolError("Each anchor must be an object")
        lat, lon = _point(a)
        anchors.append(
            {
                "label": str(a.get("label") or "Place")[:60],
                "latitude": lat,
                "longitude": lon,
                "mode": a.get("mode") or "drive",
                "maxTravelMinutes": a.get("maxTravelMinutes"),
            }
        )
    if not anchors:
        raise ToolError("Give at least one anchor")
    request = TriangulateRequest.model_validate(
        {
            "anchors": anchors,
            "combineMode": args.get("combineMode") or "intersect",
            "limit": min(int(args.get("limit") or 5), 10),
        }
    )
    response = triangulate(request)
    if not hasattr(response, "results"):
        raise ToolError("Could not resolve those anchors.")
    results = []
    with get_connection() as conn:
        for r in response.results:
            area = slim_areas.find_area(conn, r.latitude, r.longitude)
            results.append(
                {
                    "neighborhood": (area or {}).get("neighborhood"),
                    "latitude": r.latitude,
                    "longitude": r.longitude,
                    "score": round(r.composite_score),
                }
            )
    return {
        "anchors": [
            {
                "label": s.label,
                "mode": s.mode,
                "minutes": s.minutes,
                "areaSqMi": s.area_sq_mi,
                "routed": s.method == "network",
            }
            for s in response.isochrones
        ],
        "overlapSqMi": response.combined.area_sq_mi,
        "results": results,
    }


EXTRA_IMPL = {"travel_area": tool_travel_area, "triangulate": tool_triangulate}


def tool_list() -> list[dict]:
    """MCP tool descriptors (camelCase inputSchema) for every tool."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "inputSchema": t["input_schema"],
            "annotations": READ_ONLY,
        }
        for t in [*CHAT_TOOLS, *EXTRA_TOOLS]
    ]


def call_tool(name: str, args: Any) -> dict:
    """An MCP CallToolResult. Tool failures are results with isError, not protocol errors."""
    if name in EXTRA_IMPL:
        if not isinstance(args, dict):
            payload, is_error = {"error": "Tool input must be an object"}, True
        else:
            try:
                payload, is_error = EXTRA_IMPL[name](args), False
            except ToolError as exc:
                payload, is_error = {"error": str(exc)}, True
            except Exception as exc:  # noqa: BLE001 - logged, generic message to the client
                print(f"mcp: tool {name} failed ({type(exc).__name__})")
                payload, is_error = {"error": "That lookup failed. Try again."}, True
    else:
        payload, is_error = run_tool(name, args if args is not None else {}, None)
    text = json.dumps(payload, separators=(",", ":"), default=str)
    result: dict = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if isinstance(payload, dict) and not is_error:
        result["structuredContent"] = payload
    return result


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _negotiate(requested: Any) -> str:
    return requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]


def dispatch(method: str, params: Any) -> Any:
    params = params if isinstance(params, dict) else {}
    if method == "initialize":
        return {
            "protocolVersion": _negotiate(params.get("protocolVersion")),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": SERVER_TITLE, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tool_list()}
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str):
            raise RpcError(-32602, "tools/call needs a tool name")
        known = {t["name"] for t in [*CHAT_TOOLS, *EXTRA_TOOLS]}
        if name not in known:
            raise RpcError(-32602, f"Unknown tool: {name}")
        return call_tool(name, params.get("arguments"))
    if method == "resources/list":
        return {"resources": []}
    if method == "resources/templates/list":
        return {"resourceTemplates": []}
    if method == "prompts/list":
        return {"prompts": []}
    raise RpcError(-32601, f"Method not found: {method}")


def handle_message(message: Any) -> dict | None:
    """One JSON-RPC message in, its response out (None for a notification)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Invalid Request")
    method = message.get("method")
    is_request = "id" in message
    if not isinstance(method, str):
        # A response sent to the server (we never send requests): nothing to answer.
        return None if not is_request else _error(message.get("id"), -32600, "Invalid Request")
    if not is_request:
        return None  # notifications/initialized and friends
    try:
        result = dispatch(method, message.get("params"))
    except RpcError as exc:
        return _error(message["id"], exc.code, exc.message)
    return {"jsonrpc": "2.0", "id": message["id"], "result": result}


def handle_body(body: Any) -> Any:
    """The HTTP response body for a POSTed JSON value, or None when there is nothing to send
    (only notifications). Accepts a single message or a batch (older clients)."""
    if isinstance(body, list):
        if not body:
            return _error(None, -32600, "Invalid Request")
        out = [r for r in (handle_message(m) for m in body) if r is not None]
        return out or None
    return handle_message(body)


def _error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}
