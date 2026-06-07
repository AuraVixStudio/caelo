# Caelo packages & marketplace (M16)

Caelo's extensibility (M14) — **skills, slash commands, MCP server configs, and
project templates** — can be packaged, shared, and installed. This is the
distribution layer: *cheap, accessible, shareable*, with **zero hosted
infrastructure**. The registry is just a git repo; packages are plain files.

> Security is a foundation, not an add-on. A package from a stranger (especially an
> MCP config or a command with an action) is potentially executable code. Caelo
> keeps the same regime as M14: **declared permissions, explicit consent, sandbox,
> no auto-run.** The marketplace never lowers that bar.

---

## The package format (`.caelopkg`)

A package is a single file: a ZIP archive named `<id>-<version>.caelopkg` with

```
manifest.json          # metadata + declared permissions + integrity (at the root)
payload/…              # the actual content (depends on type)
```

### `manifest.json`

```json
{
  "schema": 1,
  "id": "renpy-new-scene",
  "name": "Ren'Py — New Scene",
  "version": "1.0.0",
  "type": "skill",
  "author": "you",
  "description": "Scaffold a new Ren'Py scene.",
  "requires": { "app": ">=1.0", "model": "" },
  "permissions": {
    "tools": [],
    "starts_process": false,
    "writes_files": false,
    "network": false
  },
  "source": "https://github.com/you/your-packages",
  "integrity": "sha256:<hex over the payload>"
}
```

- **`type`** — one of `skill`, `command`, `mcp`, `template`.
- **`requires.app`** — an app-version requirement: `">=1.0"`, `"1.x"`, `"*"`,
  or an exact `"1.2.0"`. Checked on import and update (incompatible packages are
  flagged, not silently installed).
- **`permissions`** — the author's honest declaration of what the package can do.
  It is shown on the consent card before install. `starts_process` (an MCP server),
  `writes_files` (a template), `network`, and the `tools` it uses.
- **`integrity`** — `sha256:` of the payload (a canonical hash of the sorted
  `payload/` files). Caelo recomputes it on import; a mismatch means the payload
  was modified after signing and **installation is refused**.

### Payload by type

| Type | `payload/` contents |
|------|---------------------|
| `skill` | `SKILL.md` (+ optional resource files) → installs to the skills dir |
| `command` | `command.json` (the slash-command definition) → added to your commands |
| `mcp` | `server.json` (a server config, **without** secrets) → added **disabled** |
| `template` | `template.json` + `files/…` (the project tree) → "New project from template" |

---

## Security model (what import does — and doesn't do)

Importing a package **never runs anything**:

- **Skills** install **disabled** — they are not injected into the agent until you
  enable them in Extensions → Skills.
- **MCP servers** install **disabled** — starting a server runs an arbitrary command,
  so it stays a separate, explicit, gated action (Extensions → MCP → Start, with a
  confirmation). Autostart never touches an imported server.
- **Commands** are only prompt templates; running one is your action, and any
  mutating action still goes through the agent's permission gate.
- **Templates** only write files when *you* create a project from them, and they
  never overwrite existing files (conflicts are reported and kept).

Before anything installs, Caelo shows a **consent card** (`/packages/inspect`) with
the manifest, the **declared permissions**, the **risk level**, the **integrity
check**, compatibility, and warnings. High-risk packages (anything that can run a
process) require an explicit "I trust this package" acknowledgement.

Hard limits guard against abuse: package size, unpacked size (zip-bomb), file count,
and path safety (Zip-Slip / `..` rejected).

---

## Building & exporting a package

The easiest way is in the app: **Extensions → Marketplace → Export** is wired into
each panel —

- Skills: the **Share** button on any skill.
- Commands: the **Share** button on any command.
- MCP servers: the **Share** button (secrets — `authorization`/`env` values — are
  stripped; the importer supplies their own).
- Templates: the **Share** button in Marketplace → Templates.

This downloads a `<id>-<version>.caelopkg` you can hand to anyone. Programmatically,
`POST /packages/export {type, ref}` returns the same bundle (base64).

---

## The registry (git-based, no hosted service)

A registry is a single JSON index in a git repo. The default is configurable in the
app (Marketplace → Browse → *Registry URL*); leave it blank for the project default.

```json
{
  "packages": [
    {
      "id": "renpy-new-scene",
      "type": "skill",
      "name": "Ren'Py — New Scene",
      "version": "1.0.0",
      "author": "you",
      "description": "Scaffold a new Ren'Py scene.",
      "url": "https://raw.githubusercontent.com/you/your-packages/main/renpy-new-scene-1.0.0.caelopkg",
      "source": "https://github.com/you/your-packages",
      "requires": { "app": ">=1.0" }
    }
  ]
}
```

`url` points at the downloadable `.caelopkg` (a raw GitHub URL works). Caelo fetches
the index (https-only, size-capped), shows entries with **installed / update /
incompatible** badges, and installs the same way as a local file — through the
consent card.

See [`registry.example.json`](registry.example.json) for a complete sample.

---

## Publishing & submitting

1. **Export** your package (above).
2. **Host** the `.caelopkg` somewhere raw-fetchable (a GitHub repo of your own works
   well — commit the file, use its `raw.githubusercontent.com` URL).
3. **Submit** it to the community registry by opening a
   [Package submission issue](../../issues/new?template=package-submission.md) (or a
   PR adding your entry to the registry repo's `registry.json`).

itch.io-style sharing also works with **no registry at all**: just send someone the
`.caelopkg` file and they import it.

---

## Curation, featured packages & reporting

- **Featured / curated:** the registry repo maintains a curated list; well-documented,
  honestly-scoped packages with a clear author can be promoted. Open a Discussion to
  nominate one.
- **Reporting a problematic package:** use the
  [package report issue](../../issues/new?template=package-report.md) for malicious,
  misleading, or broken packages. Maintainers triage these and remove offending
  entries from the registry; the package's `source` is recorded so its origin is
  traceable.
- **A malicious package can't run silently:** MCP servers import disabled, integrity
  is verified, and every tool call the agent makes is auditable (Extensions → Hooks →
  audit log). Uninstall from Marketplace → Installed at any time.

---

## Versioning & updates

Installed packages are tracked with their version. Marketplace → Installed →
**Check for updates** compares them against the registry and flags newer versions
(`has_update`) and any that have become incompatible with your app version. Updating
is a re-import (through the consent card) of the newer `.caelopkg`.
