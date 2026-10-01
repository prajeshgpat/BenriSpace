export type ApiErrorKind =
  | "invalid-request"
  | "unresolvable-address"
  | "not-found"
  | "network"
  | "timeout"
  | "server"
  | "invalid-response";

interface ApiErrorOptions {
  status?: number;
  code?: string;
  cause?: unknown;
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly code?: string;

  constructor(kind: ApiErrorKind, message: string, options: ApiErrorOptions = {}) {
    super(message, { cause: options.cause });
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status;
    this.code = options.code;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}
