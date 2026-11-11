"""`sanitize_content_html` — belt-and-braces cleanup for recurring page-body
failure modes (CDN script tags, fabricated SRI hashes, unclosed
<script>/<style>, raw control chars in JS strings). Runs on every body
before it can reach GCS."""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


# Belt-and-braces cleanup for agent-emitted body fragments. The agent
# prompt forbids `<script src=>` / `<link>` / `integrity=` / `<\/script>`,
# but LLM hallucinations recur (one dataset shipped with both a fabricated
# SRI hash on Leaflet AND `<\/script>` JSON-escape in every script-end tag,
# silently breaking all viz). These regexes catch the same classes of bug
# at the staging boundary so a regression on the prompt side never reaches
# production. Each rule logs a WARNING when it fires.
#
# Comments and raw-text end tags are matched the way the HTML tokenizer
# ends them, not just in their canonical spelling: a comment also closes at
# `--!>` (and `<!-->` / `<!--->` are empty comments), and an end tag is
# `</script` + whitespace, `/` or `>`, then anything up to `>`
# (`</script >`, `</script foo>`, `</SCRIPT>`).
HTML_COMMENT_RE = r"<!--(?:-?>|.*?--!?>)"
SCRIPT_END_RE = r"</script(?:[\t\n\f\r /][^>]*)?>"
_STYLE_END = r"</style(?:[\t\n\f\r /][^>]*)?>"
_HTML_COMMENT = re.compile(HTML_COMMENT_RE, re.DOTALL)
_SCRIPT_END_ESCAPED = re.compile(r"<\\/script(\s*)>", re.IGNORECASE)
_INTEGRITY_ATTR = re.compile(r'\s+integrity\s*=\s*"[^"]*"', re.IGNORECASE)
_CROSSORIGIN_ATTR = re.compile(r'\s+crossorigin(?:\s*=\s*"[^"]*")?', re.IGNORECASE)
_CDN_HOSTS = r"(?:[\w-]+\.)*(?:unpkg\.com|cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com)"
_SCRIPT_CDN_TAG = re.compile(
    rf'<script\b[^>]*\bsrc\s*=\s*"https?://{_CDN_HOSTS}[^"]*"[^>]*>\s*(?:{SCRIPT_END_RE})?',
    re.IGNORECASE,
)
_LINK_CDN_TAG = re.compile(
    rf'<link\b[^>]*\bhref\s*=\s*"https?://{_CDN_HOSTS}[^"]*"[^>]*/?>',
    re.IGNORECASE,
)
# Cloudflare "Email Address Obfuscation": when the agent web_fetches a
# gov.il page that sits behind Cloudflare with that feature on, the source
# HTML has real mailto:s rewritten to `<a href="/cdn-cgi/l/email-protection
# #HEX"><span class="__cf_email__" data-cfemail="HEX">[email protected]</span></a>`
# (a client-side JS on Cloudflare decodes it). govil.ai is NOT behind
# Cloudflare, so any such link the agent copies verbatim 404s on click and
# the address never renders. The real address is XOR-encoded in the HEX
# (first byte = key). Decode it back to a plain mailto: link on ingest.
_CF_EMAIL_ANCHOR = re.compile(
    r"<a\b[^>]*?/cdn-cgi/l/email-protection[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL
)
_CF_EMAIL_HEX = re.compile(r'data-cfemail="([0-9a-fA-F]{4,})"', re.IGNORECASE)
_CF_SCRIPT_TAG = re.compile(
    r'<script\b[^>]*\bsrc\s*=\s*"[^"]*cdn-cgi[^"]*"[^>]*>\s*(?:' + SCRIPT_END_RE + ")?",
    re.IGNORECASE,
)


def _decode_cfemail(hex_str: str) -> str | None:
    """Decode a Cloudflare `data-cfemail` hex string to a plain address."""
    try:
        raw = bytes.fromhex(hex_str)
    except ValueError:
        return None
    if len(raw) < 2:
        return None
    key = raw[0]
    email = "".join(chr(b ^ key) for b in raw[1:])
    return email if "@" in email else None


def _deobfuscate_cf_email(match: re.Match) -> str:
    anchor = match.group(0)
    hex_match = _CF_EMAIL_HEX.search(anchor)
    email = _decode_cfemail(hex_match.group(1)) if hex_match else None
    if email:
        return f'<a href="mailto:{email}">{email}</a>'
    # No decodable address: neutralize the dead link, keep whatever text is
    # there rather than dropping content.
    inner = re.sub(r"<[^>]+>", "", anchor)
    return inner or ""


_OPEN_SCRIPT = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
_CLOSE_SCRIPT = re.compile(SCRIPT_END_RE, re.IGNORECASE)
_OPEN_STYLE = re.compile(r"<style\b[^>]*>", re.IGNORECASE)
_CLOSE_STYLE = re.compile(_STYLE_END, re.IGNORECASE)
_SCRIPT_BLOCK = re.compile(
    r"(<script\b[^>]*>)(.*?)(" + SCRIPT_END_RE + ")", re.IGNORECASE | re.DOTALL
)
_SCRIPT_DATA_TYPE = re.compile(
    r'\btype\s*=\s*"(?:application/(?:[a-z0-9-]+\+)?json|text/[a-z0-9-]+)"',
    re.IGNORECASE,
)


def _balance_raw_text_tag(
    body: str,
    opener: re.Pattern,
    closer: re.Pattern,
    name: str,
    *,
    tag: str,
) -> str:
    # `<script>` and `<style>` put the parser in a raw-text state until
    # the matching `</…>`; an unclosed opener swallows the rest of the
    # document (an unclosed <style> renders the page blank, an unclosed
    # <script> breaks the inline JS). No string edit can tell where the
    # block should have ended, so an imbalance fails the render and the
    # last-good page stays live.
    counted = _HTML_COMMENT.sub("", body)
    opens = len(opener.findall(counted))
    closes = len(closer.findall(counted))
    if opens != closes:
        raise ValueError(
            f"{tag}sanitizer: unbalanced <{name}> tags ({opens} opening, "
            f"{closes} closing); refusing to publish"
        )
    return body


_JS_CTRL_ESCAPES: dict[str, str] = {
    "\x08": "\\b",
    "\x09": "\\t",
    "\x0a": "\\n",
    "\x0b": "\\v",
    "\x0c": "\\f",
    "\x0d": "\\r",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}
for _i in list(range(0x08)) + [0x0e, 0x0f] + list(range(0x10, 0x20)):
    _JS_CTRL_ESCAPES.setdefault(chr(_i), f"\\u{_i:04x}")


def _escape_js_string_controls(script_body: str) -> tuple[str, int]:
    # Walk the script body tracking comment/string state and replace any raw
    # control char or line terminator inside `"…"` / `'…'` literals with its
    # JS escape. CKAN address fields routinely carry embedded LFs; when the
    # agent inlines a row array as a JS literal those LFs land *unescaped*
    # inside the string and V8 aborts the whole <script> with "Invalid or
    # unexpected token" — taking every chart and the Leaflet map down with
    # it (b2370286-… exhibited exactly this).
    out: list[str] = []
    i = 0
    n = len(script_body)
    count = 0
    while i < n:
        c = script_body[i]
        # Line comment — preserve verbatim.
        if c == "/" and i + 1 < n and script_body[i + 1] == "/":
            j = script_body.find("\n", i)
            if j < 0:
                j = n
            out.append(script_body[i:j])
            i = j
            continue
        # Block comment — preserve verbatim.
        if c == "/" and i + 1 < n and script_body[i + 1] == "*":
            j = script_body.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(script_body[i:j])
            i = j
            continue
        # Template literal — raw newlines are legal here, leave as-is. We do
        # not try to parse `${…}` interpolation; for the purpose of this
        # sanitizer it's enough to skip to the matching backtick honouring
        # backslash escape.
        if c == "`":
            out.append(c)
            i += 1
            while i < n:
                ch = script_body[i]
                if ch == "\\" and i + 1 < n:
                    out.append(script_body[i:i + 2])
                    i += 2
                    continue
                out.append(ch)
                i += 1
                if ch == "`":
                    break
            continue
        # `'…'` / `"…"` string — the only place we actually escape.
        if c == '"' or c == "'":
            quote = c
            out.append(quote)
            i += 1
            while i < n:
                ch = script_body[i]
                if ch == "\\" and i + 1 < n:
                    out.append(script_body[i:i + 2])
                    i += 2
                    continue
                if ch == quote:
                    out.append(quote)
                    i += 1
                    break
                esc = _JS_CTRL_ESCAPES.get(ch)
                if esc is not None:
                    out.append(esc)
                    count += 1
                    i += 1
                    continue
                out.append(ch)
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out), count


def _escape_script_string_controls(body: str, *, tag: str) -> str:
    total = 0

    def handle(match: re.Match[str]) -> str:
        nonlocal total
        opener, inner, closer = match.group(1), match.group(2), match.group(3)
        # Skip data blocks (JSON-LD, application/json, etc.) — those aren't
        # parsed as JS, raw newlines are fine and "fixing" them would break
        # the JSON.
        if _SCRIPT_DATA_TYPE.search(opener):
            return match.group(0)
        new_inner, n = _escape_js_string_controls(inner)
        total += n
        return opener + new_inner + closer

    new_body = _SCRIPT_BLOCK.sub(handle, body)
    if total:
        log.warning(
            "%ssanitizer: escaped %d raw control char(s) in JS string literal(s)",
            tag, total,
        )
    return new_body


def sanitize_content_html(body: str, *, dataset_id: str = "") -> str:
    """Strip agent-output failure modes that recur as LLM hallucinations.

    Drops `<script src=>` / `<link href=>` to known CDNs (unpkg, jsdelivr,
    cdnjs) — the Nuxt shell pre-loads ECharts/Leaflet/MarkerCluster
    same-origin and the agent contract forbids external resource refs.
    Strips `integrity=` / `crossorigin=` attributes (any SRI hash the
    agent emits is fabricated; same-origin loads don't need either).
    Replaces `<\\/script>` (JSON string-escape) with `</script>` so the
    HTML parser actually closes the tag. Raises ValueError when
    `<script>`/`<style>` openers and closers don't balance (e4a5e2d7-…
    shipped without the trailing `</script>`, which let the parser swallow
    the page footer and the Nuxt config bootstrap, blanking every chart and
    breaking hydration).
    Escapes raw control chars (LF/CR/etc.) inside `"…"`/`'…'` JS string
    literals (b2370286-… inlined CKAN address fields containing embedded
    newlines as a JS array literal — V8 aborted the whole <script> on the
    first one, blanking 4 ECharts + the Leaflet map).

    Each transform logs a WARNING with a count and the dataset id so we
    can trace prompt regressions even when the sanitizer silently fixes
    them.
    """
    tag = f"[{dataset_id}] " if dataset_id else ""

    new_body, n = _SCRIPT_END_ESCAPED.subn(r"</script\1>", body)
    if n:
        log.warning("%ssanitizer: replaced %d <\\/script> -> </script>", tag, n)
    body = new_body

    new_body, n = _INTEGRITY_ATTR.subn("", body)
    if n:
        log.warning("%ssanitizer: stripped %d integrity= attribute(s)", tag, n)
    body = new_body

    new_body, n = _CROSSORIGIN_ATTR.subn("", body)
    if n:
        log.warning("%ssanitizer: stripped %d crossorigin attribute(s)", tag, n)
    body = new_body

    new_body, n = _SCRIPT_CDN_TAG.subn("", body)
    if n:
        log.warning("%ssanitizer: dropped %d <script src=CDN> tag(s)", tag, n)
    body = new_body

    new_body, n = _LINK_CDN_TAG.subn("", body)
    if n:
        log.warning("%ssanitizer: dropped %d <link href=CDN> tag(s)", tag, n)
    body = new_body

    new_body, n = _CF_EMAIL_ANCHOR.subn(_deobfuscate_cf_email, body)
    if n:
        log.warning("%ssanitizer: decoded %d Cloudflare email-protection link(s)", tag, n)
    body = new_body

    new_body, n = _CF_SCRIPT_TAG.subn("", body)
    if n:
        log.warning("%ssanitizer: dropped %d <script src=/cdn-cgi/> tag(s)", tag, n)
    body = new_body

    body = _balance_raw_text_tag(body, _OPEN_SCRIPT, _CLOSE_SCRIPT, "script", tag=tag)
    body = _balance_raw_text_tag(body, _OPEN_STYLE, _CLOSE_STYLE, "style", tag=tag)

    # Run after the balance check so every <script> has a closer the regex can find.
    body = _escape_script_string_controls(body, tag=tag)

    return body
