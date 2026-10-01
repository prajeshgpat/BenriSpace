# benrispace.com is registered at Cloudflare Registrar, which requires
# Cloudflare nameservers, so DNS stays at Cloudflare and Terraform manages the
# records there instead of delegating to Route 53. Every record pointing at
# AWS is DNS-only (proxied = false): ACM validation, API Gateway custom
# domains and Amplify all need to see AWS-issued certificates end to end.
data "cloudflare_zone" "main" {
  filter = {
    name = var.domain_name
  }
}

locals {
  cloudflare_zone_id = data.cloudflare_zone.main.id

  # Cloudflare's "automatic" TTL.
  cloudflare_auto_ttl = 1
}
