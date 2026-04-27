#!/usr/bin/env python3
"""
Weekly blocklist delta generator.

Fetches upstream domain lists for each category, diffs them against the
domains already bundled in the Homenesty app, and writes an updated
delta.json. Apps fetch this file daily and apply only the diff, so the
bundled lists stay lean and updates reach users without an App Store release.

Upstream sources used:
  adult      — hagezi/porn + StevenBlack/porn
  gambling   — hagezi/gambling + StevenBlack/gambling
  socialMedia— hagezi/native.tiktok.extended
  violence   — no reliable public source: delta maintained manually
  drugs      — no reliable public source: delta maintained manually
  gaming     — no reliable public source: delta maintained manually
  streaming  — no reliable public source: delta maintained manually
"""

import json
import re
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Upstream sources per category
# Supports both hosts-format (0.0.0.0 domain) and plain domain-per-line.
# ---------------------------------------------------------------------------
UPSTREAM: dict[str, list[str]] = {
    "adult": [
        "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/porn.txt",
        "https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/porn/hosts",
    ],
    "gambling": [
        "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/gambling.txt",
        "https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/gambling/hosts",
    ],
    "socialMedia": [
        "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/domains/native.tiktok.extended.txt",
        "https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/fakenews-gambling-porn-social/hosts",
    ],
    # These categories have no reliable public upstream — kept as manual-only.
    "violence":   [],
    "drugs":      [],
    "gaming":     [],
    "streaming":  [],
}

CATEGORIES = list(UPSTREAM.keys())

# Bundled lists live in the main app repo at this base URL.
BUNDLE_BASE = (
    "https://raw.githubusercontent.com/BalmuNed/homenesty/main"
    "/HomenestyCore/Blocklists/Data"
)

DELTA_FILE = Path("delta.json")

# Domains we never want to block regardless of upstream (e.g. Apple services).
ALLOWLIST = {
    "apple.com", "icloud.com", "googleapis.com", "gstatic.com",
    "cloudflare.com", "cloudflare-dns.com", "fastly.com",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_lines(url: str) -> list[str]:
    """Download a URL and return clean, lowercase domain strings."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "homenesty-blocklist-bot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"    SKIP {url}: {e}")
        return []

    results = []
    for raw in text.splitlines():
        line = raw.strip().lower()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        # Strip hosts-file IP prefix: "0.0.0.0 domain" or "127.0.0.1 domain"
        m = re.match(r"^(?:0\.0\.0\.0|127\.0\.0\.1)\s+(\S+)", line)
        if m:
            line = m.group(1)
        # Skip invalid entries
        if (
            " " in line
            or "\t" in line
            or line in {"localhost", "localhost.localdomain", "broadcasthost", "ip6-localhost"}
            or not "." in line
        ):
            continue
        results.append(line)
    return results


def load_upstream(category: str) -> set[str]:
    sources = UPSTREAM.get(category, [])
    if not sources:
        return set()
    domains: set[str] = set()
    for url in sources:
        fetched = fetch_lines(url)
        print(f"    upstream {len(fetched):>7,} ← {url.split('/')[-1]}")
        domains.update(fetched)
    # Strip allowlisted roots and their subdomains
    domains = {
        d for d in domains
        if not any(d == a or d.endswith("." + a) for a in ALLOWLIST)
    }
    return domains


def load_bundle(category: str) -> set[str]:
    url = f"{BUNDLE_BASE}/{category}.txt"
    domains = set(fetch_lines(url))
    print(f"    bundle  {len(domains):>7,} ← {category}.txt")
    return domains


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    delta = json.loads(DELTA_FILE.read_text())
    current_version    = int(delta.get("version", 0))
    current_additions  = {c: set(delta.get("additions", {}).get(c, [])) for c in CATEGORIES}
    current_removals   = {c: set(delta.get("removals",  {}).get(c, [])) for c in CATEGORIES}

    new_additions: dict[str, set[str]] = {c: set() for c in CATEGORIES}
    new_removals:  dict[str, set[str]] = {c: set() for c in CATEGORIES}
    any_changed = False

    for cat in CATEGORIES:
        print(f"\n── {cat} ──")
        bundle   = load_bundle(cat)
        upstream = load_upstream(cat)

        if not upstream:
            # No upstream source — preserve existing delta as-is.
            new_additions[cat] = current_additions[cat]
            new_removals[cat]  = current_removals[cat]
            print(f"    no upstream — manual-only, delta preserved")
            continue

        # New additions: in upstream but not already covered by bundle or prior delta.
        already_covered = bundle | current_additions[cat]
        net_additions   = upstream - already_covered

        # Stale additions: were previously added via delta but dropped from upstream.
        stale = current_additions[cat] - upstream

        new_additions[cat] = (current_additions[cat] | net_additions) - stale
        new_removals[cat]  = current_removals[cat] | stale

        if net_additions or stale:
            print(f"    +{len(net_additions):,} new  -{len(stale):,} stale")
            any_changed = True
        else:
            print(f"    no changes")

    if not any_changed:
        print("\nNo changes — delta.json is already up to date.")
        return

    new_version = current_version + 1
    output = {
        "version": new_version,
        "additions": {c: sorted(new_additions[c]) for c in CATEGORIES},
        "removals":  {c: sorted(new_removals[c])  for c in CATEGORIES},
    }
    DELTA_FILE.write_text(json.dumps(output, indent=2) + "\n")
    print(f"\n✓  delta.json updated to version {new_version}")
    total_adds = sum(len(v) for v in new_additions.values())
    total_rems = sum(len(v) for v in new_removals.values())
    print(f"   total additions: {total_adds:,}  removals: {total_rems:,}")


if __name__ == "__main__":
    main()
