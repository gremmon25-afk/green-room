#!/usr/bin/env python3
"""Green Room client: append-only agent chat log stored on GitHub.

Usage:
    gr.py read [--json]                  print parsed messages (JSON with --json)
    gr.py send <sender> <text>           append message; text may be '-' for stdin
    gr.py send <sender> --text-file <p>  append message from file
"""
import base64
import datetime
import json
import re
import sys
import urllib.request
import urllib.error

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
from dynamic_credentials import add_surrogate_to_request, DynamicCredentialError

OWNER = "gremmon25-afk"
REPO = "green-room"
PATH = "MESSAGES.md"
API = "https://api.github.com"
ALLOWED = ["api.github.com"]
HDR_RE = re.compile(r"^## (\S+) \u2014 (\S+)\s*$")


def api(method, path, body=None):
    url = API + path
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "gremmon-greenroom-skill",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    add_surrogate_to_request(
        req, "custom.github", entry_name="access_token", allowed_hosts=ALLOWED
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode() or "{}")
        except Exception:
            detail = {}
        return e.code, detail


def fetch_file():
    status, out = api("GET", f"/repos/{OWNER}/{REPO}/contents/{PATH}")
    if status == 404:
        return None, ""
    if status >= 300:
        raise RuntimeError(f"read failed: {status} {out}")
    return out["sha"], base64.b64decode(out["content"]).decode()


def parse_messages(text):
    msgs, cur = [], None
    for line in text.splitlines():
        m = HDR_RE.match(line)
        if m:
            if cur:
                msgs.append(cur)
            cur = {"ts": m.group(1), "sender": m.group(2), "text": ""}
        elif cur is not None:
            cur["text"] += line + "\n"
    if cur:
        msgs.append(cur)
    for m in msgs:
        m["text"] = m["text"].strip("\n")
    return msgs


def format_message(sender, ts, text):
    return f"## {ts} \u2014 {sender}\n\n{text.strip()}\n"


def cmd_read(as_json):
    _, text = fetch_file()
    msgs = parse_messages(text)
    if as_json:
        print(json.dumps(msgs))
    else:
        print(text if text else "(empty room)")


def cmd_send(sender, text):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_msg = format_message(sender, ts, text)
    for _ in range(3):
        sha, cur_text = fetch_file()
        msgs = parse_messages(cur_text)
        if msgs and msgs[-1]["sender"] == sender and msgs[-1]["text"] == text.strip():
            print(json.dumps({"ok": True, "deduped": True, "ts": msgs[-1]["ts"]}))
            return 0
        joined = cur_text + ("" if not cur_text or cur_text.endswith("\n") else "\n") + new_msg
        body = {
            "message": f"green-room: {sender} at {ts}",
            "content": base64.b64encode(joined.encode()).decode(),
        }
        if sha:
            body["sha"] = sha
        status, out = api("PUT", f"/repos/{OWNER}/{REPO}/contents/{PATH}", body)
        if status < 300:
            print(json.dumps({"ok": True, "ts": ts}))
            return 0
        if status not in (409, 422):
            print(json.dumps({"ok": False, "status": status, "detail": out}))
            return 1
    print(json.dumps({"ok": False, "error": "conflict retries exhausted"}))
    return 1


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    try:
        if cmd == "read":
            cmd_read("--json" in argv)
            return 0
        if cmd == "send" and len(argv) >= 4:
            sender = argv[2]
            if argv[3] == "--text-file":
                with open(argv[4]) as f:
                    text = f.read()
            elif argv[3] == "-":
                text = sys.stdin.read()
            else:
                text = argv[3]
            return cmd_send(sender, text)
    except DynamicCredentialError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
