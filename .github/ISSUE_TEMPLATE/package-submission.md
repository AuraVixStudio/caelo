---
name: Package submission
about: Submit a Caelo package (skill / command / MCP config / project template) to the community registry
title: "[package] <your package name>"
labels: ["package", "submission"]
---

<!--
Caelo packages are shared as a single .caelopkg file (a ZIP with manifest.json +
payload/). The registry is just a git-based index — no hosted service. See
docs/guides/PACKAGES.md for the format and how to build a package (Extensions →
Marketplace → Export, or the /packages/export route).

By submitting you confirm the package is yours to share (or appropriately
licensed) and does not contain secrets, credentials, or malicious behavior.
-->

## Package

- **Name:**
- **Id:** <!-- [a-zA-Z0-9_-], unique per type -->
- **Type:** <!-- skill | command | mcp | template -->
- **Version:** <!-- e.g. 1.0.0 -->
- **Author:**
- **Source repo / download URL:** <!-- raw URL to the .caelopkg or its manifest -->

## What it does

<!-- One short paragraph. What problem does it solve? -->

## Declared permissions / tool-scope

<!-- Copy the "permissions" block from your manifest.json. Be honest about:
     starts_process (MCP servers), writes_files (templates), network, tools. -->

```json
{
  "permissions": { "tools": [], "starts_process": false, "writes_files": false, "network": false }
}
```

## Checklist

- [ ] The package imports cleanly in Caelo (Extensions → Marketplace → Import) and
      the consent card shows the permissions above.
- [ ] Integrity check passes (the bundle was not modified after export).
- [ ] No secrets, API keys, or personal data are included in the payload.
- [ ] For MCP packages: the server command is documented and the user must start it
      manually (it imports disabled).
- [ ] I have the right to share this and accept the project's Code of Conduct.
