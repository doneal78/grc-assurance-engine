"""Fetch one public trust-center URL for human review.

The standard library performs the GET. Nothing in this module scores a
vendor or marks a page verified. A caller supplies ``open_url`` and
``resolver`` in tests so pytest does not use the live network. An
injected opener replaces the socket. The production opener is the one
that pins it.

Each hop resolves the hostname once. Every address is checked against
the blocklist below. The TCP connection uses only an address from that
check. The Host header, TLS SNI, and certificate hostname check use the
original hostname. A redirect is resolved and pinned again. Environment
proxies are not used.

The pin stops a later lookup from moving the connection onto a private,
loopback, or metadata address. It is not a full egress sandbox. A
public address can still be an unexpected host, and a host firewall
remains the outer control.
"""

import http.client
import ipaddress
import re
import socket
import ssl
import urllib.error
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

MAX_BYTES = 65536
EXCERPT_CHARS = 600
SUMMARY_CHARS = 240
TIMEOUT_SECONDS = 8
MAX_REDIRECTS = 3
USER_AGENT = "GRCAssuranceEngine/portfolio (trust-center review fetch)"

REFUSAL = (
    "Trust center URL cannot be fetched: the host is a private, link-local, or metadata address."
)
REDIRECTS = {301, 302, 303, 307, 308}

_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".localdomain", ".internal")
_TEXT_TYPES = {
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/problem+json",
}


class _Extractor(HTMLParser):
    """Visible text and the title, skipping script and style."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._parts = []
        self._title = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        elif tag == "title" and self._skip == 0:
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self._title.append(data)
        else:
            self._parts.append(data)

    def text(self):
        return _clean(" ".join(self._parts))

    def title(self):
        return _clean(" ".join(self._title))


def fetch_url_problems(url):
    """Return syntax and address problems. An empty list means the URL may be fetched.

    Name resolution is separate. This function does not contact the network.
    """
    text = (url or "").strip()
    if not text:
        return ["Trust center URL is required."]
    if not text.isprintable() or any(character.isspace() for character in text) or "\\" in text:
        return ["Trust center URL contains unsupported characters."]
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ["Trust center URL must start with http:// or https:// and include a host."]
    if parsed.username or parsed.password or "@" in parsed.netloc:
        return ["Trust center URL must not include a username or password."]
    try:
        host = parsed.hostname
    except ValueError:
        return ["Trust center URL has an invalid host."]
    if not host or "%" in host:
        return ["Trust center URL has an invalid host."]
    host = host.rstrip(".").lower()
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        return [REFUSAL]
    if host.isdigit() or re.fullmatch(r"0x[0-9a-f]+", host):
        return [REFUSAL]
    numeric = _numeric_host(host)
    if numeric is not None:
        return numeric
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return []
    if not _public_ip(ip):
        return [REFUSAL]
    return []


def fetch_trust_center(url, *, open_url=None, resolver=None, clock=None,
                       timeout=TIMEOUT_SECONDS, max_bytes=MAX_BYTES, max_redirects=MAX_REDIRECTS):
    """GET one URL and return a review record. HTTP failures stay in the record.

    ``refused`` is true only when the URL itself must not be requested.
    A later redirect to a blocked address is a failed fetch, not a refusal
    of the caller's original URL. ``open_url(url, timeout)`` returns
    ``(status, headers, body)`` and replaces the pinned socket. The
    production opener receives the addresses this function already
    checked and does not resolve the name again. ``resolver(host)``
    returns IP strings. Each redirect resolves its host again.
    """
    stamp = _stamp(clock)
    custom = open_url is not None
    opener = open_url or _default_open
    lookup = resolver or _system_resolver
    gate = _screen(url, lookup)
    if gate["action"] == "refuse":
        return _result(url, stamp, ok=False, refused=True, error=gate["error"])
    if gate["action"] == "fail":
        return _result(url, stamp, ok=False, refused=False, error=gate["error"])

    current = url
    pins = gate["addresses"]
    seen = set()
    for hop in range(max_redirects + 1):
        if current in seen:
            return _result(url, stamp, ok=False, refused=False,
                           error="The trust center URL redirected in a loop.")
        seen.add(current)
        if hop:
            again = _screen(current, lookup)
            if again["action"] != "allow":
                detail = again["error"]
                return _result(url, stamp, ok=False, refused=False,
                               error=f"The trust center redirect was refused. {detail}")
            pins = again["addresses"]
        try:
            if custom:
                opened = opener(current, timeout)
            else:
                opened = opener(current, timeout, pins)
        except TimeoutError:
            return _result(url, stamp, ok=False, refused=False,
                           error="The trust center request timed out.")
        except (urllib.error.URLError, OSError) as exc:
            return _result(url, stamp, ok=False, refused=False,
                           error=f"The trust center request failed ({_short(exc)}).")
        status, headers, body = _opened(opened)
        if status in REDIRECTS:
            location = _header(headers, "location")
            if not location:
                return _result(url, stamp, ok=False, refused=False, http_status=status,
                               error=f"HTTP {status} redirect had no location.")
            current = urljoin(current, location.strip())
            continue
        if status < 200 or status >= 300:
            return _result(url, stamp, ok=False, refused=False, http_status=status,
                           error=f"HTTP {status}.")
        summary, excerpt, content_type, size = _summarize(body or b"", headers, max_bytes)
        return _result(url, stamp, ok=True, refused=False, http_status=status,
                       final_url=current, content_type=content_type, summary=summary,
                       excerpt=excerpt, byte_length=size)
    return _result(url, stamp, ok=False, refused=False,
                   error="The trust center URL had too many redirects.")


def _screen(url, resolver):
    """Resolve once and return the addresses a later connect may use.

    A literal address is not resolved. A name is passed to ``resolver``
    once. Every result is checked. One blocked result refuses the hop,
    so the caller does not connect to a public sibling from the same
    answer. The returned strings are the normalized addresses.
    """
    problems = fetch_url_problems(url)
    if problems:
        return {"action": "refuse", "error": problems[0]}
    host = urlparse(url).hostname.rstrip(".").lower()
    literal = _parse_ip(host)
    if literal is not None:
        return {"action": "allow", "addresses": [str(literal)]}
    try:
        addresses = list(resolver(host))
    except OSError:
        return {"action": "fail", "error": "The trust center host could not be resolved."}
    if not addresses:
        return {"action": "fail", "error": "The trust center host could not be resolved."}
    pins = []
    for address in addresses:
        ip = _parse_ip(address)
        if ip is None:
            return {"action": "refuse", "error": REFUSAL}
        if not _public_ip(ip):
            return {
                "action": "refuse",
                "error": "Trust center URL resolves to a private, link-local, or metadata address.",
            }
        pins.append(str(ip))
    return {"action": "allow", "addresses": list(dict.fromkeys(pins))}


def _numeric_host(host):
    labels = host.split(".")
    if not labels or not all(label.isdigit() for label in labels):
        return None
    if len(labels) != 4 or any(len(label) > 1 and label.startswith("0") for label in labels):
        return [REFUSAL]
    try:
        ip = ipaddress.IPv4Address(host)
    except ValueError:
        return [REFUSAL]
    if not _public_ip(ip):
        return [REFUSAL]
    return []


def _parse_ip(value):
    """Return a normalized address, or None when ``value`` is not an IP.

    An IPv4-mapped IPv6 address is unwrapped to the IPv4 address so the
    blocklist and the socket see the same target. A zone index is dropped
    before parsing.
    """
    text = str(value).split("%", 1)[0].strip()
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _public_ip(ip):
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (ip.is_multicast or ip.is_reserved or ip.is_unspecified or ip.is_loopback
            or ip.is_link_local or ip.is_private or not ip.is_global):
        return False
    return True


def _system_resolver(host):
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos if info[4]]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection that dials ``pin`` and keeps ``host`` for the Host header."""

    def __init__(self, host, port, pin, timeout):
        super().__init__(host, port, timeout=timeout)
        self._pin = pin

    def connect(self):
        self.sock = _connect_ip(self._pin, self.port, self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that dials ``pin`` and verifies ``host``.

    SNI and certificate hostname matching use the URL hostname. The TCP
    peer is the pinned address, not a second lookup of that name.
    """

    def __init__(self, host, port, pin, timeout):
        super().__init__(host, port, timeout=timeout)
        self._pin = pin

    def connect(self):
        sock = _connect_ip(self._pin, self.port, self.timeout)
        context = ssl.create_default_context()
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = True
        try:
            context.set_alpn_protocols(["http/1.1"])
        except NotImplementedError:
            pass
        try:
            self.sock = context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def _connect_ip(ip_text, port, timeout):
    """Connect to an address that has already been parsed as an IP.

    ``socket.create_connection`` asks ``getaddrinfo`` again. Dialing the
    parsed address with ``socket.connect`` does not, including when the
    text is a numeric literal.
    """
    ip = _parse_ip(ip_text)
    if ip is None:
        raise OSError("The trust center host has no pinned address.")
    family = socket.AF_INET6 if isinstance(ip, ipaddress.IPv6Address) else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        if timeout is not None:
            sock.settimeout(timeout)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        sock.connect((str(ip), int(port)))
    except BaseException:
        sock.close()
        raise
    return sock


def _default_open(url, timeout, addresses=None):
    """GET ``url`` through a pinned socket.

    ``addresses`` is the checked set for this hop. A name without that
    set is not resolved here. An IP literal may be dialed when this
    function is called directly, which is how the loopback test reads
    a local page. Production fetches pass the screened addresses, and
    those are checked again before the socket is created.
    """
    return _pinned_get(url, timeout, addresses)


def _pinned_get(url, timeout, addresses):
    scheme, host, port, path, pins = _request_target(url, addresses)
    last_error = None
    for pin in pins:
        try:
            return _one_pin(scheme, host, port, path, pin, timeout)
        except TimeoutError:
            raise
        except ssl.SSLError:
            raise
        except http.client.HTTPException as exc:
            raise OSError(_short(exc) or "The trust center response could not be read.") from exc
        except OSError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise OSError("The trust center host has no pinned address.")


def _request_target(url, addresses):
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise OSError("The trust center URL must start with http:// or https://.")
    if not parsed.hostname:
        raise OSError("The trust center URL has an invalid host.")
    host = parsed.hostname.rstrip(".").lower()
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    pins = _pins_for_connect(host, addresses)
    return scheme, host, port, path, pins


def _pins_for_connect(host, addresses):
    if addresses is None:
        literal = _parse_ip(host)
        if literal is None:
            raise OSError("The trust center host has no pinned address.")
        return [str(literal)]
    pins = []
    for address in addresses:
        ip = _parse_ip(address)
        if ip is None or not _public_ip(ip):
            raise OSError(REFUSAL)
        pins.append(str(ip))
    if not pins:
        raise OSError("The trust center host has no pinned address.")
    return list(dict.fromkeys(pins))


def _one_pin(scheme, host, port, path, pin, timeout):
    connection_class = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
    connection = connection_class(host, port, pin, timeout)
    try:
        connection.request(
            "GET",
            path,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html, text/plain, application/json;q=0.8, */*;q=0.1",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        body = response.read(MAX_BYTES + 1)
        headers = {key: value for key, value in response.getheaders()}
        return int(response.status), headers, body
    finally:
        connection.close()


def _opened(value):
    status, headers, body = value[0], value[1], value[2]
    return int(status), headers or {}, body or b""


def _header(headers, name):
    if not headers:
        return None
    try:
        pairs = headers.items()
    except AttributeError:
        return None
    wanted = name.lower()
    for key, value in pairs:
        if str(key).lower() == wanted and value:
            return str(value)
    return None


def _summarize(body, headers, max_bytes):
    content_type = _header(headers, "content-type") or ""
    raw = body[:max_bytes]
    truncated = len(body) > max_bytes
    if not _is_text(content_type, raw):
        kind = content_type.split(";", 1)[0].strip() or "unknown type"
        summary = f"Non-text response ({kind}, {len(raw)} bytes). The bytes were not stored as a control document."
        if truncated:
            summary += " The download was truncated."
        return summary, "", content_type or None, len(raw)
    text = _decode(raw, content_type)
    base = content_type.split(";", 1)[0].strip().lower()
    if "html" in base or text.lstrip()[:1] == "<":
        parser = _Extractor()
        try:
            parser.feed(text)
            parser.close()
            visible = parser.text()
            title = parser.title()
        except Exception:
            visible = _clean(text)
            title = ""
    else:
        visible = _clean(text)
        title = ""
    excerpt = visible[:EXCERPT_CHARS]
    if title and visible:
        summary = _clean(f"{title}. {visible}")
    else:
        summary = title or visible
    summary = summary[:SUMMARY_CHARS]
    if not summary:
        summary = "The response had no readable text."
    if truncated:
        note = " The download was truncated."
        summary = summary[: max(0, SUMMARY_CHARS - len(note))] + note
    return summary, excerpt, content_type or None, len(raw)


def _is_text(content_type, body):
    if b"\x00" in body[:1024]:
        return False
    base = content_type.split(";", 1)[0].strip().lower()
    if not base:
        return True
    if base.startswith("text/") or base in _TEXT_TYPES:
        return True
    return base.endswith("+json") or base.endswith("+xml")


def _decode(body, content_type):
    charset = "utf-8"
    lowered = content_type.lower()
    if "charset=" in lowered:
        charset = lowered.split("charset=", 1)[1].split(";", 1)[0].strip().strip('"').strip("'") or "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _clean(value):
    collapsed = " ".join((value or "").split())
    return "".join(character for character in collapsed if character.isprintable())


def _stamp(clock):
    moment = clock if isinstance(clock, datetime) else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.isoformat()


def _short(exc):
    reason = getattr(exc, "reason", None)
    text = " ".join(str(reason if reason is not None else exc).split())
    return (text or exc.__class__.__name__)[:240]


def _result(url, stamp, *, ok, refused, error=None, http_status=None, final_url=None,
            content_type=None, summary=None, excerpt=None, byte_length=None):
    return {
        "ok": ok,
        "refused": refused,
        "requested_url": url,
        "final_url": final_url,
        "http_status": http_status,
        "fetched_at": stamp,
        "content_type": content_type,
        "summary": summary,
        "excerpt": excerpt,
        "byte_length": byte_length,
        "error": error,
    }
