export type ApiErrorKind =
  | "invalid-request"
  | "unresolvable-address"
  | "not-found"
  | "rate-limited"
  | "network"
  | "timeout"
  | "server"
  | "invalid-response";

interface ApiErrorOptions {
  status?: number;
  code?: string;
  retryAfterSeconds?: number;
  cause?: unknown;
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly code?: string;
  /** From the Retry-After header of a 429, when present. */
  readonly retryAfterSeconds?: number;

  constructor(kind: ApiErrorKind, message: string, options: ApiErrorOptions = {}) {
    super(message, { cause: options.cause });
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status;
    this.code = options.code;
    this.retryAfterSeconds = options.retryAfterSeconds;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}
