---
name: Report a problematic package
about: Flag a community package that is malicious, broken, or misrepresents what it does
title: "[report] <package id>"
labels: ["package", "report"]
---

<!--
Use this to report a package in the registry that is harmful or misleading.

⚠️ If the issue is a SECURITY VULNERABILITY in Caelo itself (not a third-party
package), do NOT use this form — follow SECURITY.md and report privately.

For a malicious package, you may also want to stop using it immediately:
Extensions → Marketplace → Installed → Uninstall. MCP packages import disabled,
so an unstarted server cannot run; uninstalling removes the config.
-->

## Package

- **Id / name:**
- **Type:** <!-- skill | command | mcp | template -->
- **Where you got it:** <!-- registry entry, direct URL, file from someone -->
- **Version:**

## What is wrong

<!-- Pick what applies and describe it concretely. -->

- [ ] Runs unexpected commands / starts a process it didn't declare
- [ ] Exfiltrates data / contacts the network without declaring it
- [ ] Payload does not match the declared permissions (integrity / honesty)
- [ ] Contains secrets or someone else's data
- [ ] Broken / does not work as described
- [ ] License / attribution problem
- [ ] Other:

## Evidence

<!-- Manifest snippet, the payload file(s) of concern, audit-log lines
     (Extensions → Hooks → audit), or steps to reproduce. -->

## Severity

<!-- low (broken) | medium (misleading) | high (malicious / runs code) -->
