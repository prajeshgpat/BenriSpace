"""AWS Lambda entry point (`api.lambda_handler.handler`): the FastAPI app
behind API Gateway HTTP API (payload format 2.0), adapted by Mangum.
"""

import os

DATABASE_URL_SSM_PARAM_ENV = "DATABASE_URL_SSM_PARAM"


def load_database_url_from_ssm() -> None:
    """Resolve DATABASE_URL from the SSM SecureString named by
    DATABASE_URL_SSM_PARAM. A no-op when that variable is unset (local dev,
    tests), so normal .env/environment behaviour is untouched.

    Raises instead of returning on any failure: common.config falls back to
    a localhost URL when DATABASE_URL is missing, which on Lambda would
    surface as a confusing connection-refused on the first query rather
    than as the misconfiguration it is.
    """
    param_name = os.environ.get(DATABASE_URL_SSM_PARAM_ENV)
    if not param_name:
        return

    try:
        # Imported lazily: boto3 comes from the Lambda runtime and is not a
        # dependency of the app anywhere else.
        import boto3
        from botocore.config import Config

        # Lambda's init phase is capped at 10s; botocore's defaults (60s
        # timeouts, several retries) would turn an unreachable SSM endpoint
        # into an opaque init timeout instead of this error.
        client = boto3.client(
            "ssm",
            config=Config(connect_timeout=3, read_timeout=3, retries={"total_max_attempts": 2}),
        )
        response = client.get_parameter(Name=param_name, WithDecryption=True)
        value = response["Parameter"]["Value"]
    except Exception as exc:
        raise RuntimeError(
            f"Could not read the database URL from SSM parameter {param_name!r} "
            f"(named by ${DATABASE_URL_SSM_PARAM_ENV}): {type(exc).__name__}: {exc}"
        ) from exc

    if not value.strip():
        raise RuntimeError(
            f"SSM parameter {param_name!r} (named by ${DATABASE_URL_SSM_PARAM_ENV}) is empty."
        )
    os.environ["DATABASE_URL"] = value


LOCATIONIQ_SSM_PARAM_ENV = "LOCATIONIQ_API_KEY_SSM_PARAM"


def load_locationiq_key_from_ssm() -> None:
    """Optional: address suggestions fall back to Photon without the key, so
    unlike the database URL any failure here is logged (error type only,
    never the value) and ignored. An unset or placeholder parameter means
    "not configured yet"."""
    param_name = os.environ.get(LOCATIONIQ_SSM_PARAM_ENV)
    if not param_name:
        return
    try:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "ssm",
            config=Config(connect_timeout=3, read_timeout=3, retries={"total_max_attempts": 2}),
        )
        value = client.get_parameter(Name=param_name, WithDecryption=True)["Parameter"]["Value"]
    except Exception as exc:  # noqa: BLE001 - optional secret, any failure means Photon
        print(f"LocationIQ key not loaded from SSM ({type(exc).__name__}); using Photon")
        return
    if value.strip() and not value.startswith("placeholder"):
        os.environ["LOCATIONIQ_API_KEY"] = value.strip()


# Must run before anything imports common.config, which reads DATABASE_URL
# from the environment at import time.
load_database_url_from_ssm()
load_locationiq_key_from_ssm()

from mangum import Mangum

from api.main import app

# lifespan="off": the app registers no startup/shutdown handlers, and
# Mangum would otherwise run the ASGI lifespan protocol on every invocation.
handler = Mangum(app, lifespan="off")
