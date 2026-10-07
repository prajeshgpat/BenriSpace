"""Ask BenriSpace chat: tool loop, tool dispatch, grounding, budget, rate limit
(fake Anthropic client and fake database: no network, no Postgres)."""

import contextlib
import json
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api import chat, main


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool(name, input_, id_="tu_1"):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def resp(content, stop="end_turn", tokens=(100, 50)):
    return SimpleNamespace(
        content=content,
        stop_reason=stop,
        usage=SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1]),
    )


class FakeAnthropic:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        # Snapshot: the loop mutates the same message list afterwards.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]


class FakeDB:
    """Stands in for get_connection(): records SQL, serves spend and the counter."""

    def __init__(self, spend=0.0, count=1, missing_table=False):
        self.spend, self.count, self.missing_table = spend, count, missing_table
        self.sql: list[str] = []

    @contextlib.contextmanager
    def connect(self):
        yield FakeConn(self)


class FakeConn:
    def __init__(self, db):
        self.db = db
        self._row = None

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.db.sql.append(sql)
        if "chat_usage" in sql:
            if self.db.missing_table:
                raise psycopg.errors.UndefinedTable("no chat_usage")
            self._row = {"count": self.db.count}
        elif "sum(cost_usd)" in sql:
            self._row = {"spend": self.db.spend}

    def fetchone(self):
        return self._row

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(chat, "get_connection", fake.connect)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CHAT_IP_SALT", "pepper")
    return fake


def body(*messages, context=None):
    msgs = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": m}
        for i, m in enumerate(messages)
    ]
    out = {"messages": msgs}
    if context:
        out["context"] = context
    return chat.ChatRequest.model_validate(out)


OPT_PAYLOAD = {
    "results": [
        {
            "neighborhood": "Darien, Connecticut",
            "areaLabel": None,
            "latitude": 41.07,
            "longitude": -73.47,
            "weeklyMinutes": 140,
            "overallScore": 61,
            "stops": [
                {
                    "for": "Trader Joe's",
                    "name": "Trader Joe's",
                    "minutes": 8,
                    "distance": "2.1 mi",
                    "mode": "drive",
                    "estimated": True,
                },
            ],
        }
    ],
    "assumptions": ["Assumed 5 work trips/week by car"],
    "unresolved": [],
}


@pytest.fixture
def optimize_tool(monkeypatch):
    seen = []

    def fake(args, context):
        seen.append(args)
        return OPT_PAYLOAD

    monkeypatch.setitem(chat.TOOL_IMPL, "optimize_location", fake)
    return seen


# --- the loop ---------------------------------------------------------------


def test_tool_loop_dispatches_and_builds_results_deterministically(db, optimize_tool):
    anchors = [{"kind": "address", "query": "1 Stamford Forum, Stamford CT"}]
    client = FakeAnthropic(
        [
            resp(
                [text("Let me check."), tool("optimize_location", {"anchors": anchors})], "tool_use"
            ),
            resp([text("Darien, Connecticut looks best: about 140 minutes of travel a week.")]),
        ]
    )
    out = chat.run_chat(body("Find a place near my work"), lambda timeout: client)
    assert optimize_tool == [{"anchors": anchors}]
    assert out.reply.startswith("Darien, Connecticut looks best")
    assert out.limited is None
    assert [s.tool for s in out.sources] == ["optimize_location"]
    r = out.results[0]
    assert (r.label, r.score, r.weekly_minutes) == ("Darien, Connecticut", 61, 140)
    assert "Trader Joe's: 8 min" in r.why and "2.1 mi" in r.why
    # The second call carries the assistant blocks as-is and ONE user message of tool results.
    second = client.calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-1]["role"] == "user"
    block = second[-1]["content"][0]
    assert block["type"] == "tool_result" and block["tool_use_id"] == "tu_1"
    assert "is_error" not in block and "Darien" in block["content"]
    assert client.calls[0]["model"] == "claude-haiku-4-5" and client.calls[0]["max_tokens"] == 900
    assert {t["name"] for t in client.calls[0]["tools"]} == set(chat.TOOL_IMPL)


def test_parallel_tool_blocks_return_one_user_message(db, monkeypatch):
    monkeypatch.setitem(
        chat.TOOL_IMPL,
        "geocode",
        lambda a, c: {"query": a["query"], "latitude": 1.0, "longitude": 2.0},
    )
    client = FakeAnthropic(
        [
            resp(
                [tool("geocode", {"query": "A"}, "t1"), tool("geocode", {"query": "B"}, "t2")],
                "tool_use",
            ),
            resp([text("Done.")]),
        ]
    )
    chat.run_chat(body("hi"), lambda timeout: client)
    results = client.calls[1]["messages"][-1]["content"]
    assert [b["tool_use_id"] for b in results] == ["t1", "t2"]


def test_tool_errors_are_marked_is_error_and_never_raise(db):
    client = FakeAnthropic(
        [
            resp(
                [
                    tool("nope", {}, "x1"),
                    tool("area_score", {"latitude": 999, "longitude": 0}, "x2"),
                ],
                "tool_use",
            ),
            resp([text("I could not look that up.")]),
        ]
    )
    out = chat.run_chat(body("score it"), lambda timeout: client)
    blocks = client.calls[1]["messages"][-1]["content"]
    assert all(b["is_error"] is True for b in blocks)
    assert out.sources[0].summary.startswith("nope could not answer")


def test_loop_is_capped_at_four_tool_rounds(db, monkeypatch):
    monkeypatch.setitem(chat.TOOL_IMPL, "geocode", lambda a, c: {"latitude": 1.0, "longitude": 2.0})
    client = FakeAnthropic([resp([tool("geocode", {"query": "x"})], "tool_use")])
    out = chat.run_chat(body("loop forever"), lambda timeout: client)
    assert len(client.calls) == chat.MAX_TOOL_ROUNDS + 1
    assert client.calls[-1]["tool_choice"] == {"type": "none"}
    assert out.limited is True and "could not" in out.reply


def test_only_last_six_turns_each_truncated(db):
    client = FakeAnthropic([resp([text("Okay.")])])
    msgs = [f"m{i}" for i in range(9)]
    msgs[-1] = "x" * 5000
    chat.run_chat(body(*msgs), lambda timeout: client)
    sent = client.calls[0]["messages"]
    assert len(sent) <= chat.MAX_TURNS and sent[0]["role"] == "user"
    assert len(sent[-1]["content"]) == chat.MAX_CONTENT_CHARS


def test_context_reaches_prompt_and_defaults_factors(db, monkeypatch):
    seen = {}
    monkeypatch.setitem(
        chat.TOOL_IMPL, "similar", lambda a, c: seen.update(factors=c.factors) or {"results": []}
    )
    client = FakeAnthropic(
        [
            resp([tool("similar", {"latitude": 1, "longitude": 2})], "tool_use"),
            resp([text("Nothing similar.")]),
        ]
    )
    ctx = {
        "address": "5 Main St, Hoboken NJ",
        "latitude": 40.7,
        "longitude": -74.0,
        "factors": ["grocery", "road"],
    }
    chat.run_chat(body("similar?", context=ctx), lambda timeout: client)
    assert seen["factors"] == ["grocery", "traffic"]  # alias canonicalised
    assert "5 Main St, Hoboken NJ" in client.calls[0]["system"]


def test_typed_address_is_geocoded_once_and_becomes_the_users_point(db, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "api.geocoding.geocode_address", lambda q, **k: calls.append(q) or (40.7357, -74.0336)
    )
    seen = {}
    monkeypatch.setitem(
        chat.TOOL_IMPL,
        "search_areas",
        lambda a, c: seen.update(near=(c.latitude, c.longitude)) or {"results": []},
    )
    client = FakeAnthropic(
        [resp([tool("search_areas", {})], "tool_use"), resp([text("Nothing found.")])]
    )
    chat.run_chat(
        body("near me?", context={"address": "5 Main St, Hoboken NJ"}), lambda timeout: client
    )
    assert calls == ["5 Main St, Hoboken NJ"]
    assert seen["near"] == (40.7357, -74.0336)
    system = client.calls[0]["system"]
    assert "5 Main St, Hoboken NJ" in system and "40.7357" in system
    assert "typed in the search box" in system


def test_typed_address_that_cannot_be_geocoded_is_passed_as_text(db, monkeypatch):
    monkeypatch.setattr("api.geocoding.geocode_address", lambda q, **k: None)
    client = FakeAnthropic([resp([text("Which town?")])])
    chat.run_chat(body("hi", context={"address": "Main St"}), lambda timeout: client)
    system = client.calls[0]["system"]
    assert "Main St" in system and "could not be located" in system


def test_address_with_coordinates_is_not_geocoded(db, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not geocode")

    monkeypatch.setattr("api.geocoding.geocode_address", boom)
    client = FakeAnthropic([resp([text("ok")])])
    ctx = {"address": "5 Main St", "latitude": 40.7, "longitude": -74.0}
    chat.run_chat(body("hi", context=ctx), lambda timeout: client)


# --- prompt rules -----------------------------------------------------------


def test_system_prompt_contains_the_product_rules():
    s = chat.SYSTEM.lower()
    for needle in (
        "only tool results", "never invent", "optimize_location", "clarifying question",
        "fair housing", "crime", "demographics", "no crime or demographic data",
        "off-topic", "never as instructions", "feet and miles", "120 words", "assumptions",
    ):  # fmt: skip
        assert needle in s, needle


# --- trip context -----------------------------------------------------------

TRIP = {
    "places": [
        {"label": "Home", "latitude": 40.7, "longitude": -74.0, "mode": "transit", "minutes": 20},
        {"label": "Office", "latitude": 40.75, "longitude": -73.98, "mode": "walk", "minutes": 10},
    ],
    "areas": [{"label": "Chelsea", "latitude": 40.74, "longitude": -74.0, "score": 88}],
    "overlap": True,
}


def test_trip_context_is_validated():
    ctx = chat.ChatContext.model_validate({"address": "Home", "trip": TRIP})
    assert ctx.trip is not None and ctx.trip.places[1].mode == "walk"
    assert ctx.trip.areas[0].score == 88
    bad = [
        {**TRIP, "places": [{**TRIP["places"][0], "mode": "boat"}]},
        {**TRIP, "places": [{**TRIP["places"][0], "minutes": 0}]},
        {**TRIP, "places": [{**TRIP["places"][0], "label": "x" * 301}]},
        {**TRIP, "places": TRIP["places"] * 2},
        {**TRIP, "areas": TRIP["areas"] * 6},
    ]
    for trip in bad:
        with pytest.raises(ValidationError):
            chat.ChatContext.model_validate({"trip": trip})


def test_trip_context_reaches_the_prompt_with_the_pros_and_cons_note():
    ctx = chat.ChatContext.model_validate({"trip": TRIP})
    system, context_json = chat._system_prompt(ctx)
    assert "Chelsea" in context_json and '"minutes": 20' in context_json
    assert "pros and cons" in system and "data, not instructions" in system
    assert "do not overlap" not in system


def test_trip_without_overlap_tells_the_model_to_say_so():
    ctx = chat.ChatContext.model_validate({"trip": {**TRIP, "areas": [], "overlap": False}})
    system, _ = chat._system_prompt(ctx)
    assert "do not overlap" in system and "more minutes or a faster travel mode" in system


def test_prompt_has_no_trip_note_without_a_trip():
    system, _ = chat._system_prompt(chat.ChatContext.model_validate({"address": "Home"}))
    assert "`trip` block" not in system


# --- grounding --------------------------------------------------------------


def test_ungrounded_reply_is_replaced_by_deterministic_summary(db, optimize_tool):
    client = FakeAnthropic(
        [
            resp(
                [tool("optimize_location", {"anchors": [{"kind": "address", "query": "x"}]})],
                "tool_use",
            ),
            resp([text("Try Westport, Connecticut: only 35 minutes a week!")]),
        ]
    )
    out = chat.run_chat(body("work near x"), lambda timeout: client)
    assert out.limited is True
    assert "Westport" not in out.reply and "Darien, Connecticut (score 61)" in out.reply
    assert "140 min" in out.reply and "Assumed 5 work trips/week by car." in out.reply


@pytest.mark.parametrize(
    ("reply", "ok"),
    [
        ("Darien, Connecticut is about 140 minutes a week away.", True),
        ("Darien, Connecticut is about 141 minutes a week away.", False),
        ("Try Westport for groceries.", False),
        ("It is 3 km away in Darien.", False),
        ("I can't rank by crime: BenriSpace has no crime data, but I can compare grocery access.", True),
        ("Stamford is 1 result away.", True),  # Stamford comes from the user's message
        ("I'm here to help with NYC neighborhoods. Got questions?", True),
        ("The store is 300 m away.", False),
        ("word " * 200, False),
    ],
)  # fmt: skip
def test_validate_reply(reply, ok):
    payloads = [OPT_PAYLOAD]
    users = ["work at 1 Stamford Forum, Stamford CT"]
    assert chat.validate_reply(reply, payloads, users, "{}") is ok


def test_grounding_allows_user_and_context_names():
    assert chat.validate_reply(
        "Park Slope has transit score 80.", [{"s": 80}], ["Is Park Slope good?"], "{}"
    )
    assert not chat.validate_reply(
        "Park Slope has transit score 81.", [{"s": 80}], ["Is Park Slope good?"], "{}"
    )


# --- budget / rate limit / key ---------------------------------------------


def test_usage_is_logged_per_api_call_as_chat(db, optimize_tool):
    client = FakeAnthropic(
        [resp([tool("optimize_location", {"anchors": [{"kind": "address", "query": "x"}]})], "tool_use"),
         resp([text("Done.")])]
    )  # fmt: skip
    chat.run_chat(body("hi"), lambda timeout: client)
    inserts = [s for s in db.sql if "insert into llm_usage" in s]
    assert len(inserts) == 2 and "values (%s, %s, %s, %s, %s)" in inserts[0]


def test_budget_pause(db):
    db.spend = 99.0
    out = chat.handle_chat(body("hi"), None, "1.2.3.4", lambda t: pytest.fail("no model call"))
    assert out.reply == "Chat is paused for this month." and out.limited is True


def test_missing_key_is_503(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(chat.ChatHttpError) as e:
        chat.handle_chat(body("hi"), None, "1.2.3.4")
    assert (e.value.status, e.value.message) == (503, "Chat is unavailable.")


def test_rate_limit_429_and_visitor_hash(db):
    db.count = chat.DAILY_LIMIT + 1
    with pytest.raises(chat.ChatHttpError) as e:
        chat.handle_chat(
            body("hi"), "9.9.9.9, 10.0.0.1", "1.2.3.4", lambda t: pytest.fail("no call")
        )
    assert e.value.status == 429 and "tomorrow" in e.value.message
    a = chat.visitor_hash("9.9.9.9, 10.0.0.1", "1.1.1.1")
    assert a == chat.visitor_hash("9.9.9.9", "2.2.2.2") and "9.9.9.9" not in a
    assert a != chat.visitor_hash("8.8.8.8", None)


def test_last_allowed_message_passes(db):
    db.count = chat.DAILY_LIMIT
    client = FakeAnthropic([resp([text("Hello.")])])
    assert chat.handle_chat(body("hi"), None, "1.2.3.4", lambda t: client).reply == "Hello."


def test_missing_chat_usage_table_skips_limit(db):
    db.missing_table = True
    client = FakeAnthropic([resp([text("Hello.")])])
    assert chat.handle_chat(body("hi"), None, "1.2.3.4", lambda t: client).reply == "Hello."


def test_model_failure_is_503(db):
    class Boom:
        messages = SimpleNamespace(create=lambda **k: (_ for _ in ()).throw(TimeoutError()))

    with pytest.raises(chat.ChatHttpError) as e:
        chat.handle_chat(body("hi"), None, "1.2.3.4", lambda t: Boom())
    assert e.value.status == 503


# --- the route --------------------------------------------------------------


def test_route_shapes(db, monkeypatch):
    client = FakeAnthropic([resp([text("Hello there.")])])
    monkeypatch.setattr(chat, "make_client", lambda t: client)
    monkeypatch.setattr(chat, "handle_chat", chat.handle_chat)
    http = TestClient(main.app)
    ok = http.post("/v1/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert ok.status_code == 200 and ok.json()["reply"] == "Hello there."
    assert "results" in ok.json() and "limited" not in ok.json()
    bad = http.post("/v1/chat", json={"messages": []})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_request"
    bad = http.post("/v1/chat", json={"messages": [{"role": "assistant", "content": "x"}]})
    assert bad.status_code == 400
    db.count = 99
    limited = http.post("/v1/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"


# --- streaming --------------------------------------------------------------


def _frames(text_body):
    out = []
    for frame in text_body.strip().split("\n\n"):
        if frame.startswith(":"):
            continue
        event, data = frame.split("\n", 1)
        out.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_stream_emits_status_then_the_same_reply(db, optimize_tool, monkeypatch):
    anchors = [{"kind": "address", "query": "1 Stamford Forum, Stamford CT"}]
    client = FakeAnthropic(
        [
            resp([tool("optimize_location", {"anchors": anchors})], "tool_use"),
            resp([text("Darien, Connecticut looks best: about 140 minutes of travel a week.")]),
        ]
    )
    monkeypatch.setattr(chat, "make_client", lambda t: client)
    http = TestClient(main.app)
    payload = {"messages": [{"role": "user", "content": "Find a place near my work"}]}
    streamed = http.post("/v1/chat/stream", json=payload)
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    frames = _frames(streamed.text)
    kinds = [k for k, _ in frames]
    assert kinds[-1] == "reply" and kinds.count("reply") == 1 and "error" not in kinds
    statuses = [d for k, d in frames if k == "status"]
    assert any(d.get("tool") == "optimize_location" for d in statuses)
    assert frames[-1][1]["reply"].startswith("Darien, Connecticut looks best")
    assert frames[-1][1]["results"][0]["latitude"] == 41.07


def test_stream_reports_errors_as_events(db, monkeypatch):
    db.count = 99
    http = TestClient(main.app)
    streamed = http.post("/v1/chat/stream", json={"messages": [{"role": "user", "content": "hi"}]})
    assert streamed.status_code == 200
    ((kind, data),) = _frames(streamed.text)[-1:]
    assert kind == "error" and data["status"] == 429 and data["code"] == "rate_limited"
    bad = http.post("/v1/chat/stream", json={"messages": []})
    assert bad.status_code == 400


# --- tools on the real functions -------------------------------------------


def test_tool_dispatch_validates_factors_and_input():
    payload, err = chat.run_tool("search_areas", {"factors": ["nonsense"]}, None)
    assert err and "unknown factor" in payload["error"]
    payload, err = chat.run_tool("optimize_location", {"anchors": []}, None)
    assert err
    payload, err = chat.run_tool("geocode", "not a dict", None)
    assert err


def test_optimize_tool_wraps_engine(monkeypatch):
    from api.optimize import OptimizeResponse

    captured = {}

    def fake_optimize(conn, req):
        captured["req"] = req
        return OptimizeResponse.model_validate(
            {
                "results": [
                    {
                        "latitude": 1.0, "longitude": 2.0, "neighborhood": "Darien, Connecticut",
                        "weeklyMinutes": 90, "score": 70,
                        "anchors": [{"query": "gym", "kind": "category", "name": "Gym", "latitude": 1.0,
                                     "longitude": 2.0, "minutes": 5, "distanceLabel": "0.4 mi",
                                     "mode": "walk", "approx": False}],
                    }
                ],
                "assumptions": ["a"],
                "unresolved": [{"query": "z", "reason": "r"}],
            }
        )  # fmt: skip

    monkeypatch.setattr(chat, "optimize", fake_optimize)
    monkeypatch.setattr(chat, "get_connection", lambda: contextlib.nullcontext(object()))
    out = chat.tool_optimize_location(
        {"anchors": [{"kind": "address", "query": "w", "tripsPerWeek": 5}], "defaultMode": "walk"},
        None,
    )
    assert captured["req"].default_mode == "walk" and captured["req"].anchors[0].trips_per_week == 5
    assert out["results"][0]["stops"][0]["distance"] == "0.4 mi"
    assert out["unresolved"] == [{"query": "z", "reason": "r"}]
    assert "km" not in str(out).lower()


def test_migration_0010_is_additive_and_mirrored():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "contracts"
    migration = (root / "migrations" / "0010_chat.sql").read_text()
    code = "\n".join(l for l in migration.splitlines() if not l.lstrip().startswith("--"))
    statements = [s for s in code.split(";") if s.strip()]
    assert len(statements) == 1 and statements[0].strip().startswith(
        "create table if not exists chat_usage"
    )
    assert "primary key (visitor_hash, day)" in statements[0]
    assert "applied to production" in migration.lower()
    assert "create table if not exists chat_usage" in (root / "schema.sql").read_text()


def test_grounding_accepts_sums_differences_and_roundings():
    payloads = [{"a": {"minutes": 12.4, "score": 61}, "b": {"minutes": 33, "miles": 2.34}}]

    def ok(reply):
        return chat.validate_reply(reply, payloads, [], "{}")

    assert ok("That is 45 minutes in total.")  # 12.4 + 33 rounded
    assert ok("About 21 minutes less.")  # 33 - 12.4 rounded
    assert ok("Roughly 10 minutes.")  # 12.4 to the nearest 10
    assert ok("Around 2.3 miles.")  # one decimal
    assert ok("A score of 94 combined.")  # 61 + 33
    assert not ok("It takes 777 minutes.")  # invented
    assert not ok("A score of 58.")  # not derivable


def test_grounding_accepts_names_from_any_tool_string():
    payloads = [{"results": [{"neighborhood": "Park Slope, Brooklyn", "areaLabel": "Area bounded by Union St and 5th Ave"}]}]
    assert chat.validate_reply("Try Park Slope or the area by Union St.", payloads, [], "{}")
    assert not chat.validate_reply("Try Park Slope or Williamsburg.", payloads, [], "{}")


# --- brand lookups ----------------------------------------------------------


def test_system_prompt_requires_brand_lookup_by_name():
    s = chat.SYSTEM.lower()
    for needle in ("find_places", "near_brands", "planet fitness", "never substitute", "say so explicitly"):
        assert needle in s, needle
    assert "find_places" in {t["name"] for t in chat.TOOLS}
    props = next(t for t in chat.TOOLS if t["name"] == "search_areas")["input_schema"]["properties"]
    assert "near_brands" in props


PF = [
    {"name": "Planet Fitness", "brand": "Planet Fitness", "category": "gym",
     "latitude": 40.7300, "longitude": -74.0400},
    {"name": "Planet Fitness Hoboken", "brand": None, "category": "gym",
     "latitude": 40.7450, "longitude": -74.0300},
]  # fmt: skip


def test_find_places_returns_nearest_branches(monkeypatch):
    monkeypatch.setattr(chat, "get_connection", lambda: contextlib.nullcontext(object()))
    monkeypatch.setattr("common.places.places_by_brand_in_box", lambda conn, q, *box: list(PF))
    out, err = chat.run_tool(
        "find_places",
        {"query": "planet fitness", "near_latitude": 40.72, "near_longitude": -74.04},
        None,
    )
    assert not err
    assert [p["name"] for p in out["places"]] == ["Planet Fitness", "Planet Fitness Hoboken"]
    assert out["places"][0]["direction"] == "N" and "mi" in out["places"][0]["distance"]
    assert "note" not in out


def test_find_places_none_found_says_so(monkeypatch):
    monkeypatch.setattr(chat, "get_connection", lambda: contextlib.nullcontext(object()))
    monkeypatch.setattr("common.places.places_by_brand_in_box", lambda conn, q, *box: [])
    out, err = chat.run_tool(
        "find_places", {"query": "Nonesuch", "near_latitude": 40.72, "near_longitude": -74.04}, None
    )
    assert not err and out["places"] == [] and "No place matching" in out["note"]
    out, err = chat.run_tool("find_places", {"query": "x"}, None)
    assert err  # no point and no context


def test_search_areas_near_brands_attaches_branch_and_reranks(monkeypatch):
    from api.mapdata import MapTopResponse  # noqa: F401

    def area(lat, lon, score):
        return {"latitude": lat, "longitude": lon, "score": score, "neighborhood": None,
                "subScores": {}}  # fmt: skip

    class Top:
        def model_dump(self, **k):
            # A is higher scoring but far from any branch; B is slightly lower and next to one.
            return {"factors": ["transit"], "results": [area(40.80, -74.00, 80), area(40.7301, -74.04, 74)]}

    monkeypatch.setattr(chat, "get_connection", lambda: contextlib.nullcontext(object()))
    monkeypatch.setattr(chat, "find_top", lambda *a, **k: Top())
    monkeypatch.setattr(chat, "_scores_for", lambda sub, f: {})
    monkeypatch.setattr("common.places.places_by_brand_in_box", lambda conn, q, *box: list(PF))
    out, err = chat.run_tool("search_areas", {"near_brands": ["Planet Fitness"], "limit": 2}, None)
    assert not err
    first = out["results"][0]
    assert first["score"] == 74  # re-ranked above the 80-scoring area
    assert first["nearBrands"][0]["found"] and first["nearBrands"][0]["direction"]
    assert out["results"][1]["nearBrands"][0]["found"] is False or out["results"][1]["nearBrands"][0]["distanceLabel"]
    assert "points per mile" in out["rankingNote"]


def test_search_areas_near_brands_with_no_branch_is_flagged(monkeypatch):
    class Top:
        def model_dump(self, **k):
            return {"factors": ["transit"], "results": [
                {"latitude": 40.8, "longitude": -74.0, "score": 80, "neighborhood": None, "subScores": {}}]}  # fmt: skip

    monkeypatch.setattr(chat, "get_connection", lambda: contextlib.nullcontext(object()))
    monkeypatch.setattr(chat, "find_top", lambda *a, **k: Top())
    monkeypatch.setattr(chat, "_scores_for", lambda sub, f: {})
    monkeypatch.setattr("common.places.places_by_brand_in_box", lambda conn, q, *box: [])
    out, _ = chat.run_tool("search_areas", {"near_brands": ["Planet Fitness"]}, None)
    assert out["results"][0]["nearBrands"][0] == {
        "brand": "Planet Fitness", "found": False, "note": "No Planet Fitness within 5 miles"}  # fmt: skip
