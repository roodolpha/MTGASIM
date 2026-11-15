# Releasing

1. Bump the version in `brewbench/__init__.py` and `pyproject.toml`.
2. Commit, then tag and push: `git tag v0.3.0 && git push origin v0.3.0`.
3. GitHub Actions (`.github/workflows/release.yml`) runs the tests, builds the app with PyInstaller, wraps it in an
   Inno Setup installer and attaches `brewbench-setup-0.3.0.exe` to a new GitHub release.
4. Everyone's dashboard shows "Update available" once the release is published (it checks GitHub's latest release).

## Code signing (avoiding the "unknown publisher" warning)

Two free routes, and it's worth doing both:

* **Microsoft Store.** Registration is free for individual developers. Submit the MSIX the release workflow
  builds and the Store signs it for free, hosts it and updates it. One-off setup: create an individual account in
  Partner Center, reserve the app name, copy the package name, publisher and publisher display name from
  *Product identity* into the repo's Actions variables `STORE_PACKAGE_NAME`, `STORE_PUBLISHER` and
  `STORE_PUBLISHER_DISPLAY_NAME`, and add the logo PNGs under `packaging/msix/Assets/`.
* **SignPath Foundation** for the installer on GitHub releases: free for open-source projects with an OSI licence
  (GPL-3.0 qualifies) and a **public** repository. The certificate is issued to "SignPath Foundation", and the
  project has to publish a short code-signing policy page. Apply at signpath.org, then add their GitHub Action to
  `release.yml` before the upload step.

Paid fallback: an OV certificate from a CA (roughly £60-£300 a year). Azure Artifact Signing (about $10 a
month) is currently only open to individuals in the US and Canada.

## What the installer does

Installs per user into `%LOCALAPPDATA%\Programs\brewbench` (no admin prompt), adds a Start menu entry, and
optionally a desktop shortcut and "start with Windows" (runs in the background recording games). Java and Forge
are not bundled: the first-run screen downloads them into `%USERPROFILE%\.brewbench`, which keeps the installer
small and keeps Forge's GPL licence simple (users get Forge straight from its own releases).
