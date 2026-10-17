#!/usr/bin/env python3
"""Bounded read-only public graph capture; no keys, cases, writes or JS execution."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

ORIGIN = 'https://34-38-10-198.sslip.io'
SLUG = 'einbringung_par20_umwstg'
LIMIT = 4_000_000

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

def fetch(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != urlparse(ORIGIN).netloc:
        raise ValueError('Unexpected origin')
    with build_opener(NoRedirect()).open(Request(url, headers={'Accept': 'application/json,text/html,*/*'}), timeout=12) as response:
        raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('Response too large')
        return raw.decode('utf-8')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = {'origin': ORIGIN, 'graph_id': SLUG, 'captured_at': datetime.now(timezone.utc).isoformat(),
              'status': 'UNAVAILABLE', 'auth_used': False, 'requests': [], 'api_literals': [], 'graph': None}
    try:
        page = fetch(ORIGIN + '/')
        result['requests'].append('/')
        sources = re.findall(r'<script[^>]+src=[\"\']([^\"\']+)', page)
        paths = set()
        for src in sources[:8]:
            url = urljoin(ORIGIN + '/', src)
            bundle = fetch(url)
            result['requests'].append(urlparse(url).path)
            for candidate in re.findall(r'[\"\'`](/[^\"\'`\s]{0,180})[\"\'`]', bundle):
                if 'graph' in candidate.lower() or 'api' in candidate.lower():
                    paths.add(candidate)
        result['api_literals'] = sorted(paths)
        result['status'] = 'ENDPOINTS_DISCOVERED'
        candidates = set()
        for path in paths:
            if 'graph' not in path.lower(): continue
            if '${' in path:
                path = re.sub(r'\$\{[^}]+\}', SLUG, path)
            if '{' in path or '?' in path or not path.startswith('/'): continue
            candidates.add(path)
            if path.rstrip('/').endswith('graphs'):
                candidates.add(path.rstrip('/') + '/' + SLUG)
        for path in sorted(candidates)[:10]:
            try:
                raw = fetch(ORIGIN + path)
                payload = json.loads(raw)
                result['requests'].append(path)
                possibilities = payload if isinstance(payload, list) else [payload]
                if isinstance(payload, dict):
                    for key in ('graph', 'graphs', 'data'):
                        value = payload.get(key)
                        if isinstance(value, dict): possibilities.append(value)
                        if isinstance(value, list): possibilities.extend(value)
                for candidate in possibilities:
                    if not isinstance(candidate, dict): continue
                    if not isinstance(candidate.get('nodes'), list) or not isinstance(candidate.get('edges'), list): continue
                    identity = str(candidate.get('id', candidate.get('name', candidate.get('slug', ''))))
                    if identity != SLUG and not path.rstrip('/').endswith('/' + SLUG): continue
                    result.update(status='CAPTURED', graph=candidate, source_path=path)
                    result['content_sha256'] = hashlib.sha256(json.dumps(candidate, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
                    break
                if result['graph'] is not None: break
            except (HTTPError, URLError, ValueError, TimeoutError):
                continue
    except (HTTPError, URLError, ValueError, TimeoutError) as exc:
        result['error_type'] = type(exc).__name__
    with open(args.output, 'w', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(result['status'])

if __name__ == '__main__':
    main()
