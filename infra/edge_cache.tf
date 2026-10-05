# Cloudflare edge caching for the GET endpoints that already send Cache-Control
# (docs/PLANNED.md Wave 1). NOT APPLIED and off by default: with enable_edge_cache = false this
# file creates nothing.
#
# Cloudflare only caches proxied (orange-cloud) records. The api record in api_gateway.tf is
# DNS-only today; var.enable_edge_cache turns the proxy on for it and creates the ruleset below.
# Before applying:
#   * set the zone's SSL/TLS mode to "Full (strict)" (API Gateway presents an ACM certificate
#     for api.<domain>), and
#   * run `terraform plan` and check that the only DNS change is proxied false -> true.
# Rollback: set enable_edge_cache = false and apply (the record goes back to DNS-only).
#
# "Respect origin" TTL: the API decides freshness (max-age=300 for cells / area / score /
# places / similar / improve, 86400 for /v1/map/scores). Responses without Cache-Control
# (POST, errors, /v1/chat, /v1/optimize) are never stored. The cache key includes the full
# query string (Cloudflare's default), which carries every parameter that changes a response.

variable "enable_edge_cache" {
  description = "Proxy api.<domain> through Cloudflare and cache GET responses at the edge."
  type        = bool
  default     = false
}

resource "cloudflare_ruleset" "api_edge_cache" {
  count = var.enable_edge_cache ? 1 : 0

  zone_id     = local.cloudflare_zone_id
  name        = "${var.project} API edge cache"
  description = "Cache GET /v1 responses that send Cache-Control (Terraform)"
  kind        = "zone"
  phase       = "http_request_cache_settings"

  rules = [
    {
      action      = "set_cache_settings"
      description = "Cache read-only API GETs; honour the origin's Cache-Control"
      enabled     = true
      expression  = "(http.host eq \"${local.api_domain}\" and http.request.method eq \"GET\" and starts_with(http.request.uri.path, \"/v1/\") and not starts_with(http.request.uri.path, \"/v1/chat\") and not starts_with(http.request.uri.path, \"/v1/optimize\") and not starts_with(http.request.uri.path, \"/v1/feedback\"))"
      action_parameters = {
        cache = true
        edge_ttl = {
          mode = "respect_origin"
        }
        browser_ttl = {
          mode = "respect_origin"
        }
      }
    },
  ]
}
