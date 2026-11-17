"""Auto-assign a custom role (Sprout) to new Roblox community members.

Required environment variables:
  ROBLOX_KEY       Open Cloud API key (Groups memberships read + write)
  GROUP_ID         your community ID (the number in the community URL)
  SPROUT_ROLE_ID   Role ID of the custom Sprout role (Roles > Sprout > Settings)
Optional:
  INCLUDE_EXISTING=1   also assign the role to current members on the first run
  POLL_SECONDS=300     how often to check for new members
"""
import json
import os
import sys
import time

import requests

KEY = os.environ.get("ROBLOX_KEY")
GROUP = os.environ.get("GROUP_ID")
ROLE = os.environ.get("SPROUT_ROLE_ID", "921902016")
INCLUDE_EXISTING = os.environ.get("INCLUDE_EXISTING") == "1"
POLL = int(os.environ.get("POLL_SECONDS", "300"))
STATE = "seen.json"

if not (KEY and GROUP and ROLE):
    sys.exit("Set ROBLOX_KEY, GROUP_ID and SPROUT_ROLE_ID first.")

API = "https://apis.roblox.com/cloud/v2"
HEAD = {"x-api-key": KEY, "Content-Type": "application/json"}
ROLE_PATH = f"groups/{GROUP}/roles/{ROLE}"
DEFAULT_ROLE = os.environ.get("DEFAULT_ROLE_ID", "12884901889")  # the locked default role ("new")


def call(method, url, **kw):
    r = None
    for _ in range(5):
        r = requests.request(method, url, headers=HEAD, timeout=30, **kw)
        if r.status_code == 429:  # rate limited
            time.sleep(10)
            continue
        break
    return r


def members():
    token = ""
    while True:
        r = call("GET", f"{API}/groups/{GROUP}/memberships",
                 params={"maxPageSize": 100, "pageToken": token})
        r.raise_for_status()
        data = r.json()
        yield from data.get("groupMemberships", [])
        token = data.get("nextPageToken")
        if not token:
            break


def eligible(m):
    """True only for members who have nothing but the default role."""
    roles = [r for r in (m.get("roles") or [m.get("role")]) if r]
    if ROLE_PATH in roles:
        return False
    return all(r.endswith(f"/roles/{DEFAULT_ROLE}") for r in roles)


def load_seen():
    try:
        with open(STATE) as f:
            return set(json.load(f))
    except FileNotFoundError:
        return None


ONCE = os.environ.get("RUN_ONCE") == "1"  # check once and exit (for GitHub Actions)

seen = set() if ONCE else load_seen()
print("Checking once." if ONCE else f"Running. Checking every {POLL} seconds.")

while True:
    try:
        current = list(members())
        if seen is None:
            # First run: skip everyone already in the community unless asked otherwise.
            seen = set() if INCLUDE_EXISTING else {m["path"] for m in current}
        for m in current:
            path = m["path"]
            if path in seen:
                continue
            if not eligible(m):  # already Sprout, or has another role: leave alone
                seen.add(path)
                continue
            r = call("PATCH", f"{API}/{path}", json={"role": ROLE_PATH})
            print(time.strftime("%H:%M:%S"), path, r.status_code, r.text[:200])
            if r.ok:
                seen.add(path)  # failed ones are retried next round
        if not ONCE:
            with open(STATE, "w") as f:
                json.dump(sorted(seen), f)
    except Exception as e:
        print("error:", e)
        if ONCE:
            sys.exit(1)
    if ONCE:
        break
    time.sleep(POLL)
