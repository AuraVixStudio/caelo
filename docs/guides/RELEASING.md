# Cutting a release (Windows + Linux + macOS)

How a versioned Caelo release is assembled across three platforms. The signing model is
**mixed** on purpose:

- **Windows** — signed **locally** by the maintainer (Asseco SimplySign cert is cloud-based
  and non-exportable, so it can't live on a CI runner) and uploaded to the Release by hand.
- **Linux + macOS** — built **in CI** on their own runners (the PyInstaller sidecar is native
  per-OS, so cross-compiling is impractical). On a `v*` **tag** the CI publishes their binaries
  **and** the `latest-*.yml` auto-update feeds straight to the tag's Release.

One-time macOS Developer ID cert + GitHub secrets setup lives in
[`MACOS_SIGNING.md`](MACOS_SIGNING.md). This doc is the per-release checklist.

---

## 1. Bump the version + changelog (on `main`)

- `desktop/package.json` → `version` (single source of truth; the lockfile is not bumped).
- `CHANGELOG.md` → new `## [x.y.z] — <date>` section + the compare link at the bottom.
- Optionally mention user-facing changes in `README.md`.

Commit and push to `main`.

## 2. Tag the release → CI builds & publishes Linux + macOS

```bash
git tag vX.Y.Z && git push origin vX.Y.Z
```

The [`Release`](../../.github/workflows/release.yml) workflow runs on the tag and, per OS:

- **Linux** (`ubuntu-latest`) → `Caelo-x.y.z.AppImage` + `caelo-desktop_x.y.z_amd64.deb`
  (unsigned — normal for Linux) + `latest-linux.yml`.
- **macOS — arm64 only** (`macos-14` Apple Silicon → `Caelo-x.y.z-arm64.dmg`),
  **signed with Developer ID + notarized** when the `MAC_CSC_LINK`/`APPLE_*` secrets are set,
  + `latest-mac.yml`. (Intel/x64 is not built — see the gotcha below.)

Because it's a **tag** build, each mac/Linux job runs `electron-builder --publish always` and
uploads to a Release for the tag (created as a **draft** if it doesn't exist yet). A
`workflow_dispatch` (manual) run instead stays `--publish never` and only uploads artifacts —
use it to test the pipeline without touching a Release.

> Intel (`macos-13`) runners can queue for a long time at Apple — a mac job of ~15–40 min is
> normal.

Confirm in each mac job log: `Developer ID Application: …` (signed), `notarization successful`,
`stapling`.

## 3. Build + upload Windows locally

On the maintainer's machine with **SimplySign Desktop** active (virtual card in the Windows
cert store):

```powershell
cd desktop
npm run dist:full     # pack:sidecar (signed via CAELO_SIGN_THUMBPRINT) + build + electron-builder --win
```

Verify the signature, then upload to the same Release:

```powershell
Get-AuthenticodeSignature desktop\dist\Caelo-Setup-X.Y.Z.exe   # Status must be Valid
```
```bash
gh release upload vX.Y.Z \
  desktop/dist/Caelo-Setup-X.Y.Z.exe \
  desktop/dist/Caelo-Setup-X.Y.Z.exe.blockmap \
  desktop/dist/latest.yml
```

## 4. Publish

Write the release notes (mirror the CHANGELOG section), then publish the draft (or, if you
created the Release yourself first with `gh release create`, it's already published). Mark it
**Latest**.

---

## Gotchas learned the hard way

- **Repo must be public for end-user auto-update.** `electron-updater` can't read `latest*.yml`
  from a private repo without auth. Public since 2026-07-03.
- **macOS is arm64-only (no Intel/x64).** GitHub is retiring the Intel `macos-13` runner —
  in practice the job can sit queued for hours and never start (10 h, 2026-07-03), so it's
  dropped from the matrix (it would hang every release). Building x64 on the arm64 `macos-14`
  runner isn't a simple flag: the **PyInstaller sidecar can't cross-compile**, so a `--x64`
  build there ships an **arm64 sidecar** (broken on Intel). A real x64 build needs the sidecar
  built under **Rosetta** (`arch -x86_64` + x86_64 Python) — doable but **unverifiable without
  an Intel Mac**, so it's deferred (`PLAN_OTWARTE.md` J1-x64). If Intel is ever re-added,
  mind the **multi-arch feed collision**: each runner publishes its own `latest-mac.yml`
  (its arch only) and the second overwrites the first — the two would need merging.
- **Don't pin `arch` under `mac.target` in `electron-builder.yml`.** It overrides the per-runner
  CLI flag (`--mac --arm64` / `--x64`), making **every** runner build **both** arches — and the
  cross-built `.dmg` then ships a sidecar of the wrong architecture (broken). Arch must come
  from the CLI flag alone (fixed 2026-07-03).
- **`release.yml` needs `npm run build` before `electron-builder`.** Calling the binary directly
  skips the electron-vite build, so `out/main/index.js` is missing → "Application entry file …
  does not exist".
- **Empty `CSC_LINK` breaks the mac build.** With no signing secret, electron-builder treats the
  empty string as a cert path and fails; the build step `unset`s the empty signing vars → clean
  unsigned `.dmg`. Signing/notarization only kick in when `MAC_CSC_LINK` is present.
- **Generating the Developer ID CSR in Git Bash** needs `MSYS_NO_PATHCONV=1` or `/CN=…` is
  mangled into a Windows path (see [`MACOS_SIGNING.md`](MACOS_SIGNING.md)).
