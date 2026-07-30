#!/usr/bin/env python3
"""Write a release version into the files that carry one.

The release workflow derives the version from commit history, so these files
would otherwise hold whatever was last typed by hand. They had drifted three
releases behind (0.6.0 against tag v0.9.0) by the time this was added.

Edits are surgical rather than a parse-and-redump, so an unrelated formatting
change never rides along with a release commit. Both files are checked for
exactly one version site: a second one would mean this script silently updates
half of them.
"""

import argparse
import json
import re
import sys
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
VERSION_PATTERN = re.compile(r"\A\d+\.\d+\.\d+\Z")

PLUGIN_VERSION_FIELD = re.compile(r'("version"\s*:\s*)"[^"]*"')
SERVER_VERSION_ASSIGNMENT = re.compile(r'^SERVER_VERSION = "[^"]*"$', re.M)
PAGE_VERSION_BADGE = re.compile(r'(<span class="badge v">v)[^<]*(</span>)')


def replace_once(path, pattern, replacement):
    """Apply `pattern` exactly once, or fail loudly."""
    text = path.read_text(encoding="utf-8")
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise SystemExit(
            f"{path}: expected exactly one version site, found {len(matches)}"
        )
    return text, pattern.sub(replacement, text, count=1)


def set_plugin_version(root, version):
    path = root / ".codex-plugin" / "plugin.json"
    _, updated = replace_once(path, PLUGIN_VERSION_FIELD, rf'\g<1>"{version}"')
    json.loads(updated)  # never write something that is not valid JSON
    path.write_text(updated, encoding="utf-8")
    return path


def set_server_version(root, version):
    path = root / "skills" / "database-cli" / "scripts" / "database-mcp"
    _, updated = replace_once(
        path, SERVER_VERSION_ASSIGNMENT, f'SERVER_VERSION = "{version}"'
    )
    path.write_text(updated, encoding="utf-8")
    return path


def set_page_version(root, version):
    """The landing page shows a version badge; keep it off the stale list too."""
    path = root / "docs" / "index.html"
    _, updated = replace_once(path, PAGE_VERSION_BADGE, rf"\g<1>{version}\g<2>")
    path.write_text(updated, encoding="utf-8")
    return path


def current_version(root):
    """Version the tree currently declares, or None if it cannot be read."""
    path = root / ".codex-plugin" / "plugin.json"
    try:
        declared = json.loads(path.read_text(encoding="utf-8")).get("version", "")
    except (OSError, ValueError):
        return None
    return declared if VERSION_PATTERN.match(str(declared)) else None


def as_tuple(version):
    return tuple(int(part) for part in version.split("."))


def set_version(root, version, only_if_newer=False):
    if not VERSION_PATTERN.match(version):
        raise SystemExit(f"not a major.minor.patch version: {version!r}")
    if only_if_newer:
        current = current_version(root)
        # A hotfix is usually branched from an older tag, so propagating its
        # version to a main that has already moved on would be a downgrade.
        if current and as_tuple(version) <= as_tuple(current):
            return []
    return [
        set_plugin_version(root, version),
        set_server_version(root, version),
        set_page_version(root, version),
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="Release version, without a leading 'v'.")
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="Repository root. Overridable so the behaviour can be tested on a copy.",
    )
    parser.add_argument(
        "--only-if-newer",
        action="store_true",
        help="Do nothing when the tree already declares this version or a newer one. "
             "Used when propagating a hotfix version onto a branch that may be ahead.",
    )
    args = parser.parse_args(argv)

    written = set_version(args.root, args.version, only_if_newer=args.only_if_newer)
    if not written:
        print(f"已声明 {current_version(args.root)}，不回退到 {args.version}")
        return 0
    for path in written:
        print(f"{path.relative_to(args.root)} -> {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
