# Pallas community plugin template

A root-level, copyable community plugin skeleton. It uses the public `pallas.api.*` API and the layout supported by the community Git installer.

## Start here

1. Copy this directory to a new repository; keep the plugin package at repository root.
2. Replace `example_plugin` and `YOUR_ORG` in the Python package, `community-index.entry.json`, and this README. Choose a unique plugin ID (`a-z`, `0-9`, `_`, starting with a lowercase letter).
3. Replace the example name, description, author, and tags. Add the entry's optional `min_pallas_version` only when you have confirmed the plugin's actual minimum; otherwise omit it. Update the changelog before each release.
4. Choose and add a license before publishing; this template does not choose one for you.
5. Run `python -m unittest discover -s tests -v` and `python tools/check_release.py --tag v0.1.0` before tagging.

The example command is `ping`; it replies `Pong.`. Add your own handlers and command declarations in `__init__.py` and `handlers.py`. Keep each command ID aligned across permissions, limits, menu metadata, and matcher registration.

## Release and listing

For a release, set the same formal `X.Y.Z` version in `__init__.py`, `community-index.entry.json`, and the first versioned heading in `CHANGELOG.md`, then push a matching `vX.Y.Z` tag. The `release-check.yml` workflow only checks these values; it does not publish, write to another repository, or require secrets.

The included CI and tag check are usable as copied. **Index listing remains manual**: after publishing the repository, submit a PR to `PallasBot/community-plugin-index` with the entry fields from `community-index.entry.json` and update that index's `updated_at`. Automatic index updates are not supported for arbitrary community plugins. The index's `ref` defaults to `main`, so it does not pin installed code to a release tag.

See [Pallas community plugin author guide](https://PallasBot.github.io/Pallas-Bot-Docs/guide/community-plugin-author) for author checks and the index PR process.
