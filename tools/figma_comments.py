#!/usr/bin/env python3
"""Figma comments client for the figma-build review loop. Standard library only.

usage:
  figma_comments.py check  <file-url-or-key>
  figma_comments.py fetch  <file-url-or-key> [--all]
  figma_comments.py mark   <file-url-or-key> <comment_id>... --change "what changed"
  figma_comments.py reply  <file-url-or-key> <root_comment_id> "message"
  figma_comments.py selftest

fetch prints open threads as JSON: roots with their replies in order, minus resolved
threads and anything already in the handled ledger. mark adds ids to the ledger.
reply needs the "File comments: Write" scope.

There is deliberately no delete command. Comments are the review record.

Token:  $FIGMA_TOKEN_FILE, else ~/.figma-token (one line). Never printed.
Ledger: $FIGMA_LEDGER, else ./figma-comments-handled.json
"""
import json, os, re, ssl, sys, urllib.error, urllib.request
from datetime import datetime, timezone

API = "https://api.figma.com/v1"


def file_key(ref):
    m = re.search(r"figma\.com/(?:design|file|board|proto)/([A-Za-z0-9]+)", ref)
    m2 = re.search(r"/branch/([A-Za-z0-9]+)", ref)
    if m2:
        return m2.group(1)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9]{10,}", ref):
        return ref
    sys.exit(f"not a Figma file URL or key: {ref}")


def token():
    path = os.environ.get("FIGMA_TOKEN_FILE", os.path.expanduser("~/.figma-token"))
    try:
        t = open(path).read().strip()
    except OSError:
        sys.exit(f"no token at {path}. Save a Figma personal access token there (chmod 600).")
    if not t or "PASTE" in t.upper():
        sys.exit(f"{path} is empty or still a placeholder.")
    return t


def ssl_context():
    try:
        import certifi  # python.org builds on macOS ship without root certificates
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 headers={"X-Figma-Token": token(), "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            sys.exit("SSL certificate check failed: this Python has no root certificates. Run "
                     "'/Applications/Python 3.x/Install Certificates.command', or 'pip install certifi', "
                     "or use /usr/bin/python3.")
        sys.exit(f"network error: {e.reason}")


def ledger_path():
    return os.environ.get("FIGMA_LEDGER", "figma-comments-handled.json")


def load_ledger():
    try:
        return json.load(open(ledger_path()))
    except (OSError, ValueError):
        return {}


def save_ledger(led):
    tmp = ledger_path() + ".tmp"
    json.dump(led, open(tmp, "w"), indent=2, ensure_ascii=False)
    os.replace(tmp, ledger_path())


def open_threads(comments, handled, include_all=False):
    """Group flat comments into threads; drop resolved threads and handled comments."""
    roots = {c["id"]: dict(c, replies=[]) for c in comments if not c.get("parent_id")}
    for c in sorted((c for c in comments if c.get("parent_id")), key=lambda c: c.get("created_at", "")):
        if c["parent_id"] in roots:
            roots[c["parent_id"]]["replies"].append(c)
    out = []
    for r in sorted(roots.values(), key=lambda r: r.get("created_at", "")):
        if not include_all:
            if r.get("resolved_at"):
                continue
            new_replies = [x for x in r["replies"] if x["id"] not in handled]
            if r["id"] in handled and not new_replies:
                continue
            r = dict(r, replies=new_replies, root_handled=r["id"] in handled)
        out.append(r)
    return out


def slim(c):
    meta = c.get("client_meta") or {}
    return {"id": c["id"], "author": (c.get("user") or {}).get("handle"), "created_at": c.get("created_at"),
            "message": c.get("message"), "node_id": meta.get("node_id"), "node_offset": meta.get("node_offset"),
            "canvas_xy": [meta["x"], meta["y"]] if "x" in meta else None, "order": c.get("order_id")}


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return
    cmd = argv[0]
    if cmd == "selftest":
        return selftest()
    if cmd == "delete":
        sys.exit("refused: this client never deletes comments. They are the review record.")
    if len(argv) < 2:
        sys.exit(__doc__)
    key = file_key(argv[1])

    if cmd == "check":
        code, data = call("GET", f"/files/{key}/comments")
        if code == 200:
            print(f"OK: token reads comments ({len(data.get('comments', []))} on file {key})")
        elif code == 403:
            sys.exit("HTTP 403: the token lacks 'File comments: Read', or this account cannot open the file.")
        elif code == 404:
            sys.exit("HTTP 404: no file with that key.")
        else:
            sys.exit(f"HTTP {code}")

    elif cmd == "fetch":
        code, data = call("GET", f"/files/{key}/comments")
        if code != 200:
            sys.exit(f"HTTP {code}. Run: figma_comments.py check {key}")
        handled = load_ledger().get(key, {})
        threads = open_threads(data.get("comments", []), handled, "--all" in argv)
        print(json.dumps([dict(slim(t), root_handled=t.get("root_handled", False),
                               replies=[slim(r) for r in t["replies"]]) for t in threads],
                         indent=2, ensure_ascii=False))
        print(f"{len(threads)} open thread(s); {len(handled)} comment(s) already handled", file=sys.stderr)

    elif cmd == "mark":
        if "--change" not in argv:
            sys.exit('mark needs --change "what changed"')
        i = argv.index("--change")
        ids, change = argv[2:i], " ".join(argv[i + 1:])
        if not ids or not change:
            sys.exit("mark needs at least one comment id and a --change description")
        led = load_ledger()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for cid in ids:
            led.setdefault(key, {})[cid] = {"handled_at": now, "change": change}
        save_ledger(led)
        print(f"marked {len(ids)} comment(s) as handled in {ledger_path()}")

    elif cmd == "reply":
        if len(argv) < 4:
            sys.exit('reply needs <root_comment_id> "message"')
        code, _ = call("POST", f"/files/{key}/comments", {"message": argv[3], "comment_id": argv[2]})
        if code == 200:
            print("replied")
        elif code == 403:
            sys.exit("HTTP 403: replying needs the 'File comments: Write' scope.")
        else:
            sys.exit(f"HTTP {code}")
    else:
        sys.exit(__doc__)


def selftest():
    c = lambda i, p=None, t="2026-01-01T00:00:0%d", res=None: {
        "id": i, "parent_id": p, "created_at": t % int(i[-1]), "resolved_at": res, "message": i,
        "client_meta": {"node_id": "1:2", "node_offset": {"x": 1, "y": 2}}}
    comments = [c("r1"), c("a2", "r1"), c("r3"), c("r4", res="2026-01-02"), c("a5", "r3"), c("a6", "r1")]
    # nothing handled: r1 (2 replies, in time order) and r3; resolved r4 dropped
    t = open_threads(comments, {})
    assert [x["id"] for x in t] == ["r1", "r3"], t
    assert [x["id"] for x in t[0]["replies"]] == ["a2", "a6"]
    # r1 and its replies handled, r3 handled but a new reply a5 is not -> only r3 with a5
    t = open_threads(comments, {"r1": 1, "a2": 1, "a6": 1, "r3": 1})
    assert [x["id"] for x in t] == ["r3"] and [x["id"] for x in t[0]["replies"]] == ["a5"]
    assert t[0]["root_handled"] is True
    # --all shows everything, resolved included
    assert len(open_threads(comments, {"r1": 1}, include_all=True)) == 3
    assert file_key("https://www.figma.com/design/AbC123xyz0/name?node-id=1-2") == "AbC123xyz0"
    assert file_key("https://www.figma.com/design/AbC123xyz0/branch/BrN456abc0/name") == "BrN456abc0"
    assert slim(comments[0])["node_offset"] == {"x": 1, "y": 2}
    print("selftest PASS")


if __name__ == "__main__":
    main(sys.argv[1:])
