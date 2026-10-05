"""Streaming chat server for a Lambda function URL (`python -m api.stream_server`).

API Gateway buffers responses, so POST /v1/chat/stream only streams when the
app runs behind a function URL in RESPONSE_STREAM mode with the AWS Lambda Web
Adapter, which forwards HTTP to a local server. Importing `api.lambda_handler`
first loads the SSM secrets (database URL, API keys) exactly as the buffered
function does, then hands the same FastAPI app to uvicorn. Not used locally:
`uvicorn api.main:app` already streams. Deployment steps: docs/ARCHITECTURE.md,
"Chat streaming"; infra/chat_stream.tf (off by default).
"""

import os

from api.lambda_handler import app


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        log_level="warning",
        lifespan="off",
    )


if __name__ == "__main__":
    main()
