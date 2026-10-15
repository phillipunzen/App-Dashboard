"""Bounded metadata fetching with DNS-pinned connections and redirect validation."""
import base64
import http.client
import gzip
import zlib
import io
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 4_000_000
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', 'fc00::/7',
))


class FetchError(ValueError):
    pass


def normalize_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Bitte eine gültige URL mit maximal 2048 Zeichen eingeben.')
    value = value.strip()
    if not value:
        raise ValueError('Bitte eine URL eingeben.')
    if '://' not in value:
        value = 'https://' + value
    try:
        parts = urlsplit(value)
        if (parts.scheme not in ('http', 'https') or not parts.hostname
                or parts.username is not None or parts.password is not None
                or any(ord(c) < 33 or ord(c) == 127 for c in value)):
            raise ValueError()
        host = parts.hostname.encode('idna').decode('ascii')
        if any(c in host for c in ('\\', '%')):
            raise ValueError()
        port = parts.port
        authority = f'[{host}]' if ':' in host else host
        if port is not None:
            if port < 1:
                raise ValueError()
            authority += f':{port}'
        return urlunsplit((parts.scheme, authority, parts.path or '/', parts.query, parts.fragment))
    except (ValueError, UnicodeError):
        raise ValueError('Bitte eine gültige HTTP- oder HTTPS-URL ohne Zugangsdaten eingeben.') from None


def resolve_target(host, port, allow_private):
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchError('Der Hostname konnte nicht aufgelöst werden.') from exc
    if not addresses:
        raise FetchError('Der Hostname konnte nicht aufgelöst werden.')
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global and not (allow_private and any(ip in network for network in PRIVATE_NETWORKS)):
            raise FetchError('Die Adresse ist für den automatischen Abruf gesperrt. Private Netze lassen sich in der Server-Konfiguration freigeben.')
    return addresses[0][4][0]


class PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, target, timeout):
        super().__init__(host, port, timeout=timeout)
        self.target = target

    def connect(self):
        self.sock = socket.create_connection((self.target, self.port), self.timeout)


class PinnedHTTPSConnection(PinnedHTTPConnection):
    default_port = 443

    def connect(self):
        super().connect()
        self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=self.host)


def fetch(url, allow_private=False, limit=1_000_000, deadline=None):
    deadline = deadline or time.monotonic() + 12
    for _ in range(4):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError('Der Abruf hat zu lange gedauert.')
        url = normalize_url(url)
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == 'https' else 80)
        target = resolve_target(parts.hostname, port, allow_private)
        cls = PinnedHTTPSConnection if parts.scheme == 'https' else PinnedHTTPConnection
        connection = cls(parts.hostname, port, target, min(4, remaining))
        try:
            path = urlunsplit(('', '', parts.path or '/', parts.query, ''))
            connection.request('GET', path, headers={
                'User-Agent': 'AppHafen/1.0 (+self-hosted dashboard)',
                'Accept': 'text/html,image/*;q=0.9,*/*;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
            })
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise FetchError('Die Anwendung liefert eine ungültige Weiterleitung.')
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise FetchError(f'Die Anwendung antwortet mit HTTP {response.status}.')
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError('Der Abruf hat zu lange gedauert.')
                if connection.sock:
                    connection.sock.settimeout(min(4, remaining))
                chunk = response.read1(min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise FetchError('Die Antwort ist zu groß.')
            raw = b''.join(chunks)
            encoding = response.getheader('Content-Encoding', '').lower().strip()
            try:
                if encoding == 'gzip':
                    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                        raw = compressed.read(limit + 1)
                elif encoding == 'deflate':
                    raw = zlib.decompressobj().decompress(raw, limit + 1)
                elif encoding not in ('', 'identity'):
                    raise FetchError('Die Komprimierung wird nicht unterstützt.')
            except (OSError, EOFError, zlib.error) as exc:
                raise FetchError('Die Antwort ist ungültig komprimiert.') from exc
            if len(raw) > limit:
                raise FetchError('Die entpackte Antwort ist zu groß.')
            return raw, response.getheader('Content-Type', ''), url
        except (OSError, http.client.HTTPException) as exc:
            raise FetchError('Die Anwendung ist nicht erreichbar oder ihr TLS-Zertifikat ist ungültig.') from exc
        finally:
            connection.close()
    raise FetchError('Die Anwendung leitet zu oft weiter.')


def clean_icon(raw):
    if len(raw) > 256_000:
        raise ValueError('Das Logo darf maximal 250 KB groß sein.')
    try:
        with Image.open(io.BytesIO(raw)) as picture:
            picture.thumbnail((192, 192))
            picture = picture.convert('RGBA')
            output = io.BytesIO()
            picture.save(output, format='PNG', optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning, ValueError):
        raise ValueError('Das Logo muss ein gültiges PNG-, JPEG-, GIF-, WebP- oder ICO-Bild sein.') from None


def decode_icon(value):
    if not value:
        return None
    if not isinstance(value, str) or len(value) > 350_000:
        raise ValueError('Das Logo ist zu groß.')
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        raise ValueError('Das Logo ist ungültig.') from None
    return clean_icon(raw)


def discover(url, allow_private=False):
    url = normalize_url(url)
    result = {'url': url, 'name': urlsplit(url).hostname, 'description': '', 'icon': None, 'warning': None}
    deadline = time.monotonic() + 18
    try:
        raw, content_type, final_url = fetch(url, allow_private, deadline=deadline)
        if 'html' not in content_type.lower():
            raise FetchError('Unter dieser URL wurde keine HTML-Seite gefunden.')
        soup = BeautifulSoup(raw, 'html.parser')
        title = soup.find('meta', attrs={'property': 'og:title'})
        title = title.get('content') if title else (soup.title.get_text(' ', strip=True) if soup.title else None)
        description = soup.find('meta', attrs={'name': lambda v: v and v.lower() == 'description'})
        if not description:
            description = soup.find('meta', attrs={'property': 'og:description'})
        if title:
            result['name'] = title.strip()[:100]
        if description:
            result['description'] = (description.get('content') or '').strip()[:500]
        candidates = []
        for link in soup.find_all('link', href=True):
            rel = [r.lower() for r in link.get('rel', [])]
            if 'apple-touch-icon' in rel or 'icon' in rel:
                candidates.append(urljoin(final_url, link['href']))
        candidates.append(urljoin(final_url, '/favicon.ico'))
        for candidate in list(dict.fromkeys(candidates))[:4]:
            try:
                raw, _, _ = fetch(candidate, allow_private, limit=256_000, deadline=deadline)
                result['icon'] = base64.b64encode(clean_icon(raw)).decode('ascii')
                break
            except (ValueError, OSError):
                continue
        if not result['icon']:
            result['warning'] = 'Kein geeignetes Favicon gefunden. Du kannst ein Logo hochladen oder das Buchstaben-Icon verwenden.'
    except (ValueError, OSError):
        result['warning'] = 'Automatischer Abruf nicht möglich. Name und Beschreibung kannst du selbst ergänzen.'
    return result
