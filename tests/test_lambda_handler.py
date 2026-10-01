"""Tests for api/lambda_handler.py. No live AWS and no live Postgres:

- The SSM bootstrap is called directly against a botocore-Stubber'd SSM
  client, which validates the request/response shapes against the real
  service model without any network call or credentials.
- Anything that depends on *import order* (the bootstrap has to run before
  common.config reads DATABASE_URL) runs in a fresh subprocess. Re-importing
  api.main/common.config inside the pytest process would leave other test
  modules holding stale module objects; a subprocess cannot leak.
- The Mangum handler is exercised with API Gateway HTTP API (payload 2.0)
  events against routes that return before touching the database.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber

REPO_ROOT = Path(__file__).resolve().parent.parent
PARAM_NAME = "/benrispace/prod/database_url"
SSM_URL = "postgresql://user:secret@db.example.com:5432/postgres"
PARAM_ENV = "DATABASE_URL_SSM_PARAM"


@pytest.fixture
def lambda_handler(monkeypatch):
    """The module, imported with the SSM param unset so a first import here
    does no AWS work. DATABASE_URL is pinned through monkeypatch so that
    whatever a test's bootstrap call writes to os.environ is undone."""
    monkeypatch.delenv(PARAM_ENV, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://pre-existing/db")
    import api.lambda_handler

    return api.lambda_handler


@pytest.fixture
def ssm(monkeypatch):
    """A stubbed SSM client that boto3.client() hands out, plus the
    arguments boto3.client() was called with."""
    client = boto3.client(
        "ssm",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    client_calls = []

    def fake_client(*args, **kwargs):
        client_calls.append((args, kwargs))
        return client

    monkeypatch.setattr(boto3, "client", fake_client)
    with Stubber(client) as stubber:
        yield stubber, client_calls


def _parameter_response(value: str) -> dict:
    return {"Parameter": {"Name": PARAM_NAME, "Type": "SecureString", "Value": value}}


# --- SSM bootstrap ----------------------------------------------------------


def test_bootstrap_sets_database_url_from_the_decrypted_parameter(lambda_handler, ssm, monkeypatch):
    stubber, client_calls = ssm
    # expected_params makes the Stubber fail the call unless it asks for
    # exactly this parameter *with decryption* -- without it a SecureString
    # comes back as ciphertext.
    stubber.add_response(
        "get_parameter",
        _parameter_response(SSM_URL),
        expected_params={"Name": PARAM_NAME, "WithDecryption": True},
    )
    monkeypatch.setenv(PARAM_ENV, PARAM_NAME)

    lambda_handler.load_database_url_from_ssm()

    assert os.environ["DATABASE_URL"] == SSM_URL
    stubber.assert_no_pending_responses()
    assert client_calls[0][0] == ("ssm",)


def test_bootstrap_does_nothing_when_param_name_is_unset(lambda_handler, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("boto3 must not be touched when the param name is unset")

    monkeypatch.setattr(boto3, "client", fail)

    lambda_handler.load_database_url_from_ssm()

    assert os.environ["DATABASE_URL"] == "postgresql://pre-existing/db"


def test_bootstrap_treats_an_empty_param_name_as_unset(lambda_handler, monkeypatch):
    monkeypatch.setenv(PARAM_ENV, "")
    monkeypatch.setattr(boto3, "client", lambda *a, **k: pytest.fail("boto3 was called"))

    lambda_handler.load_database_url_from_ssm()

    assert os.environ["DATABASE_URL"] == "postgresql://pre-existing/db"


def test_bootstrap_raises_clearly_when_the_parameter_cannot_be_read(
    lambda_handler, ssm, monkeypatch
):
    stubber, _ = ssm
    stubber.add_client_error(
        "get_parameter", service_error_code="ParameterNotFound", http_status_code=400
    )
    monkeypatch.setenv(PARAM_ENV, PARAM_NAME)

    with pytest.raises(RuntimeError) as excinfo:
        lambda_handler.load_database_url_from_ssm()

    message = str(excinfo.value)
    assert PARAM_NAME in message
    assert PARAM_ENV in message
    assert "ParameterNotFound" in message
    # Not silently replaced by anything -- in particular not the localhost default.
    assert os.environ["DATABASE_URL"] == "postgresql://pre-existing/db"


def test_bootstrap_raises_when_the_parameter_is_blank(lambda_handler, ssm, monkeypatch):
    stubber, _ = ssm
    stubber.add_response("get_parameter", _parameter_response("  "))
    monkeypatch.setenv(PARAM_ENV, PARAM_NAME)

    with pytest.raises(RuntimeError, match="is empty"):
        lambda_handler.load_database_url_from_ssm()

    assert os.environ["DATABASE_URL"] == "postgresql://pre-existing/db"


# --- Cold-start import order (fresh interpreter) ----------------------------

_COLD_START_PRELUDE = """
import boto3

class FakeSSM:
    def get_parameter(self, **kwargs):
        assert kwargs == {{"Name": {param!r}, "WithDecryption": True}}, kwargs
        {body}

boto3.client = lambda *args, **kwargs: FakeSSM()
"""


def _run_cold_start(body: str, script: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env[PARAM_ENV] = PARAM_NAME
    env["PYTHONPATH"] = str(REPO_ROOT)
    prelude = _COLD_START_PRELUDE.format(param=PARAM_NAME, body=body)
    return subprocess.run(
        [sys.executable, "-c", prelude + script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_cold_start_resolves_database_url_before_config_is_imported():
    result = _run_cold_start(
        body=f'return {{"Parameter": {{"Value": {SSM_URL!r}}}}}',
        script=(
            "import api.lambda_handler\n"
            "import common.config, common.db\n"
            "print(common.config.DATABASE_URL)\n"
            "print(common.db.DATABASE_URL)\n"
            "print(callable(api.lambda_handler.handler))\n"
        ),
    )

    assert result.returncode == 0, result.stderr
    # If common.config had been imported before the bootstrap ran, these
    # would be the .env value or the localhost default instead.
    assert result.stdout.split() == [SSM_URL, SSM_URL, "True"]


def test_cold_start_fails_the_import_when_ssm_is_unreadable():
    result = _run_cold_start(
        body='raise PermissionError("AccessDeniedException: not authorized")',
        script="import api.lambda_handler\nprint('imported')\n",
    )

    assert result.returncode != 0
    assert "imported" not in result.stdout
    assert "RuntimeError" in result.stderr
    assert PARAM_NAME in result.stderr
    assert "AccessDeniedException" in result.stderr


# --- Mangum handler, API Gateway HTTP API payload 2.0 -----------------------


class _LambdaContext:
    function_name = "benrispace-api"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:benrispace-api"
    aws_request_id = "00000000-0000-0000-0000-000000000000"

    def get_remaining_time_in_millis(self) -> int:
        return 30_000


def _apigw_v2_event(
    method: str,
    path: str,
    query: str = "",
    headers: dict | None = None,
    body: str | None = None,
) -> dict:
    event = {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": query,
        "headers": {
            "accept": "*/*",
            "host": "api.benrispace.com",
            "x-forwarded-for": "203.0.113.10",
            "x-forwarded-port": "443",
            "x-forwarded-proto": "https",
            **(headers or {}),
        },
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "abc123",
            "domainName": "api.benrispace.com",
            "domainPrefix": "api",
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "203.0.113.10",
                "userAgent": "pytest",
            },
            "requestId": "req-id",
            "routeKey": "$default",
            "stage": "$default",
            "time": "30/Sep/2026:12:00:00 +0000",
            "timeEpoch": 1790769600000,
        },
        "isBase64Encoded": False,
    }
    if body is not None:
        event["body"] = body
    return event


def _invoke(lambda_handler, event: dict) -> dict:
    response = lambda_handler.handler(event, _LambdaContext())
    # What API Gateway requires of a payload-2.0 integration response.
    assert isinstance(response["statusCode"], int)
    assert isinstance(response["body"], str)
    assert response["isBase64Encoded"] is False
    return response


def test_handler_returns_the_apis_validation_error_for_score_without_params(lambda_handler):
    response = _invoke(lambda_handler, _apigw_v2_event("GET", "/v1/score"))

    assert response["statusCode"] == 400
    assert response["headers"]["content-type"] == "application/json"
    body = json.loads(response["body"])
    assert body["code"] == "invalid_request"
    assert body["message"] == "Provide address, or both lat and lon."


def test_handler_passes_the_query_string_through(lambda_handler):
    event = _apigw_v2_event("GET", "/v1/score", query="address=Newark&lat=40.7&lon=-74.1")

    response = _invoke(lambda_handler, event)

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["message"] == (
        "Provide either address or lat/lon, not both."
    )


def test_handler_passes_the_request_body_through(lambda_handler):
    event = _apigw_v2_event(
        "POST",
        "/v1/triangulate",
        headers={"content-type": "application/json"},
        body=json.dumps({"anchors": []}),
    )

    response = _invoke(lambda_handler, event)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["code"] == "invalid_request"
    assert body["message"].startswith("body.anchors")


def test_handler_serves_the_openapi_document(lambda_handler):
    response = _invoke(lambda_handler, _apigw_v2_event("GET", "/openapi.json"))

    assert response["statusCode"] == 200
    assert "/v1/score" in json.loads(response["body"])["paths"]


def test_handler_returns_404_for_a_path_outside_the_app(lambda_handler):
    response = _invoke(lambda_handler, _apigw_v2_event("GET", "/prod/v1/score"))

    assert response["statusCode"] == 404


def test_handler_applies_cors_for_the_production_origin(lambda_handler):
    event = _apigw_v2_event("GET", "/v1/score", headers={"origin": "https://benrispace.com"})

    response = _invoke(lambda_handler, event)

    assert response["headers"]["access-control-allow-origin"] == "https://benrispace.com"
