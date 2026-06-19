# Caelo package registry — publishing guide

The Caelo Marketplace (**Extensions → Marketplace → Browse**) reads a git/GitHub-hosted
JSON index — there is **no hosted service**. By default Caelo points at:

```
https://raw.githubusercontent.com/AuraVixStudio/caelo-packages/main/registry.json
```

(see `config.PACKAGES_REGISTRY_URL`). Until that repo exists with a `registry.json` on
`main`, Browse returns a graceful 404 — importing a `.caelopkg` directly (Import tab) and
BYO-registry (paste any raw URL into the Registry URL field) both work without it.

## Publish the registry (one-time)

1. Create the GitHub repo **`AuraVixStudio/caelo-packages`** (public).
2. Copy [`registry.starter.json`](registry.starter.json) into its root as **`registry.json`**
   and commit to `main`. Browse now loads (empty list, no 404).

## Add a package

1. Build a bundle in Caelo: a panel's **Share** button (Skills/Commands/MCP/Templates)
   exports a `.caelopkg` (a ZIP with `manifest.json` + `payload/`, sha256 integrity, secrets
   stripped). See [`PACKAGES.md`](PACKAGES.md).
2. Upload the `.caelopkg` to the `caelo-packages` repo (e.g. `skills/<id>-<version>.caelopkg`).
3. Add an entry to `registry.json` `packages` — each needs at minimum `id` + `type`
   (`skill` | `command` | `mcp` | `template`) and a raw `url`:

```json
{
  "id": "my-skill",
  "type": "skill",
  "name": "My skill",
  "version": "1.0.0",
  "author": "AuraVix Studio",
  "description": "What it does.",
  "url": "https://raw.githubusercontent.com/AuraVixStudio/caelo-packages/main/skills/my-skill-1.0.0.caelopkg",
  "source": "https://github.com/AuraVixStudio/caelo-packages",
  "requires": { "app": ">=1.0" }
}
```

Entries with a missing `id` or an invalid `type` are skipped (the parser is tolerant).
A fully populated example lives in [`registry.example.json`](registry.example.json).

## Security model (unchanged from M14/M16)

Install runs nothing: skills/MCP import **disabled**, commands are prompt templates,
templates only write files via *New project*. Caelo refuses install without explicit
consent and on integrity mismatch (tamper). Keep secrets out of bundles — export strips
`authorization`/`env`.
