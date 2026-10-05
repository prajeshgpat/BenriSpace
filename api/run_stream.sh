#!/bin/sh
# Entry point for the streaming chat Lambda (infra/chat_stream.tf): the Lambda
# Web Adapter wrapper runs this, and the adapter forwards requests to the port.
exec python3 -m api.stream_server
