-- BenriSpace "Ask BenriSpace" chat migration. NOT yet applied.
-- Additive only, idempotent. Mirrored into contracts/schema.sql.
-- Run by hand after review; the API works without it (the per-visitor chat limit is
-- simply skipped while the table is missing, see api/chat.py).
--
-- chat_usage: messages per anonymous visitor per day. visitor_hash is a salted
-- sha256 of the client IP (never the IP itself); the API allows 15 messages a day.
-- Each statement below is a single statement (one per semicolon).

create table if not exists chat_usage (
    visitor_hash text not null,
    day          date not null,
    count        int not null default 0,
    primary key (visitor_hash, day)
);
