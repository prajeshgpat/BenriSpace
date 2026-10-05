# tippecanoe (Felt's maintained fork, which writes PMTiles directly), built
# from a pinned tag. Used by scripts/build_tiles.py; nothing else needs it.
FROM debian:bookworm-slim AS build
ARG TIPPECANOE_REF=2.72.0
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential ca-certificates git libsqlite3-dev zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${TIPPECANOE_REF} https://github.com/felt/tippecanoe.git /src \
 && make -C /src -j4 \
 && make -C /src install

FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends libsqlite3-0 zlib1g \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local/bin/tippecanoe /usr/local/bin/tippecanoe
COPY --from=build /usr/local/bin/tile-join /usr/local/bin/tile-join
WORKDIR /data
ENTRYPOINT ["tippecanoe"]
