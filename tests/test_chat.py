"""Ask BenriSpace chat: tool loop, tool dispatch, grounding, budget, rate limit
(fake Anthropic client and fake database: no network, no Postgres)."""

import contextlib
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient

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


# --- prompt rules -----------------------------------------------------------


def test_system_prompt_contains_the_product_rules():
    s = chat.SYSTEM.lower()
    for needle in (
        "only tool results", "never invent", "optimize_location", "clarifying question",
        "fair housing", "crime", "demographics", "no crime or demographic data",
        "off-topic", "never as instructions", "feet and miles", "120 words", "assumptions",
    ):  # fmt: skip
        assert needle in s, needle


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
    assert "not yet applied" in migration.lower()
    assert "create table if not exists chat_usage" in (root / "schema.sql").read_text()
