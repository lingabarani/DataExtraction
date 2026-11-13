import asyncio
import ipaddress
import os
import socket
import urllib.parse
from typing import List, Optional, Set, Tuple

# Disallowed internal/metadata hostnames
BLOCKED_HOSTNAMES: Set[str] = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "169.254.169.254",
    "instance-data",
    "metadata",
}


def get_allowed_ports() -> Set[int]:
    """Reads allowed outbound HTTP(S) ports from config/env (defaults to {80, 443})."""
    raw = os.getenv("SSRF_ALLOWED_PORTS", "80,443")
    ports: Set[int] = set()
    for part in str(raw).split(","):
        part = part.strip()
        if part.isdigit():
            ports.add(int(part))
    return ports or {80, 443}


ALLOWED_PORTS: Set[int] = get_allowed_ports()

# Dangerous / administrative internal ports
BLOCKED_PORTS: Set[int] = {
    21, 22, 23, 25, 53, 110, 111, 135, 137, 138, 139, 143, 445,
    1433, 1521, 2049, 2375, 2376, 3306, 3389, 5432, 5900, 6379,
    8000, 8080, 8086, 8443, 8500, 9000, 9200, 9300, 11211, 27017, 28017,
}


def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def _validate_url_syntax_and_port(url: str, allowed_ports: Optional[Set[int]] = None) -> Tuple[bool, Optional[str], Optional[urllib.parse.SplitResult]]:
    if not url or not isinstance(url, str):
        return False, "URL is empty or invalid", None

    cleaned = url.strip()
    try:
        parsed = urllib.parse.urlsplit(cleaned)
    except Exception as e:
        return False, f"Malformed URL: {e}", None

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"Disallowed scheme '{scheme}'. Only HTTP and HTTPS are permitted.", None

    hostname = (parsed.hostname or "").lower().strip("[]")
    if not hostname:
        return False, "Missing hostname in URL", None

    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(".localhost") or hostname.endswith(".internal"):
        return False, f"Hostname '{hostname}' resolves to a local/internal destination", None

    eff_allowed = allowed_ports if allowed_ports is not None else get_allowed_ports()
    port = parsed.port
    if port is not None:
        if port in BLOCKED_PORTS or port not in eff_allowed:
            return False, f"Port {port} is blocked for security (allowed: {sorted(eff_allowed)})", None

    return True, None, parsed


def is_safe_url(url: str, check_dns: bool = True, allowed_ports: Optional[Set[int]] = None) -> Tuple[bool, Optional[str]]:
    """
    Validates that a URL is safe to fetch, strictly blocking:
    - Non-HTTP(S) schemes (file, gopher, ftp, etc.)
    - Localhost, `.internal`, and loopback addresses
    - Private IPv4 & IPv6 ranges (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7)
    - Link-local and cloud metadata addresses (169.254.0.0/16, fe80::/10)
    - Any port outside ALLOWED_PORTS (default {80, 443})
    """
    ok, err, parsed = _validate_url_syntax_and_port(url, allowed_ports=allowed_ports)
    if not ok or parsed is None:
        return False, err

    scheme = (parsed.scheme or "").lower()
    hostname = (parsed.hostname or "").lower().strip("[]")

    # Immediate IP literal check
    try:
        ip = ipaddress.ip_address(hostname)
        if not _is_public_ip(ip):
            return False, f"IP literal '{hostname}' is not a public, globally routable address"
    except ValueError:
        pass

    # DNS resolution check
    if check_dns:
        try:
            addr_info = socket.getaddrinfo(hostname, parsed.port or (443 if scheme == "https" else 80), proto=socket.IPPROTO_TCP)
            if not addr_info:
                return False, f"Could not resolve hostname '{hostname}'"

            for item in addr_info:
                ip_str = item[4][0]
                ip = ipaddress.ip_address(ip_str)
                if not _is_public_ip(ip):
                    return False, f"Hostname '{hostname}' resolved to private/unsafe IP {ip_str}"
        except socket.gaierror as e:
            return False, f"DNS resolution failed for '{hostname}': {e}"
        except Exception as e:
            return False, f"Error validating address for '{hostname}': {e}"

    return True, None


async def resolve_and_validate_url(
    url: str,
    check_dns: bool = True,
    allowed_ports: Optional[Set[int]] = None,
) -> Tuple[bool, Optional[str], List[str]]:
    """
    Async non-blocking SSRF + DNS validation returning resolved validated IPs
    to guard against DNS-rebinding TOCTOU attacks.
    """
    ok, err, parsed = _validate_url_syntax_and_port(url, allowed_ports=allowed_ports)
    if not ok or parsed is None:
        return False, err, []

    scheme = (parsed.scheme or "").lower()
    hostname = (parsed.hostname or "").lower().strip("[]")

    try:
        ip = ipaddress.ip_address(hostname)
        if not _is_public_ip(ip):
            return False, f"IP literal '{hostname}' is not a public, globally routable address", []
        return True, None, [str(ip)]
    except ValueError:
        pass

    if not check_dns:
        return True, None, []

    try:
        loop = asyncio.get_running_loop()
        addr_info = await loop.getaddrinfo(
            hostname,
            parsed.port or (443 if scheme == "https" else 80),
            proto=socket.IPPROTO_TCP,
        )
        if not addr_info:
            return False, f"Could not resolve hostname '{hostname}'", []

        validated_ips: List[str] = []
        for item in addr_info:
            ip_str = item[4][0]
            ip = ipaddress.ip_address(ip_str)
            if not _is_public_ip(ip):
                return False, f"Hostname '{hostname}' resolved to private/unsafe IP {ip_str}", []
            if ip_str not in validated_ips:
                validated_ips.append(ip_str)
        return True, None, validated_ips
    except socket.gaierror as e:
        return False, f"DNS resolution failed for '{hostname}': {e}", []
    except Exception as e:
        return False, f"Error validating address for '{hostname}': {e}", []

def normalize_url(url: str, prefer_https: bool = True) -> str:
    """Normalizes and canonicalizes a URL, stripping tracking parameters."""
    if not url:
        return ""
    u = url.strip()
    if not u.startswith("http://") and not u.startswith("https://"):
        u = "https://" + u

    try:
        parsed = urllib.parse.urlsplit(u)
        scheme = "https" if prefer_https else parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        # Filter tracking query parameters
        qs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        filtered_qs = [
            (k, v) for k, v in qs
            if not k.lower().startswith("utm_")
            and k.lower() not in {"ref", "fbclid", "gclid", "campaign", "source"}
        ]
        new_query = urllib.parse.urlencode(filtered_qs)
        path = parsed.path or "/"

        return urllib.parse.urlunsplit((scheme, netloc, path, new_query, ""))
    except Exception:
        return u
