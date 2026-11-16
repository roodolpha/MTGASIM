# Code signing policy

Brewbench publishes its Windows installer from this public repository, built by GitHub Actions
(`.github/workflows/release.yml`) on every version tag. Nothing is built or signed by hand.

**Status:** applying to the SignPath Foundation open-source programme. Once approved, Windows releases will use
free code signing provided by [SignPath.io](https://signpath.io/), certificate by
[SignPath Foundation](https://signpath.org/). Until then, releases are unsigned and Windows SmartScreen may warn
about an unknown publisher.

**What gets signed:** `brewbench-setup-*.exe` and the files it installs (`brewbench.exe`, `brewbench-cli.exe`),
built from this repository's source. Third-party components bundled by PyInstaller keep their own signatures, if
they have any. Forge and Java are not shipped in the installer; the app downloads them from their official
releases on first run.

**Team roles**
- Committers and reviewers: [roodolpha](https://github.com/roodolpha)
- Approvers: [roodolpha](https://github.com/roodolpha)

Every signing request is approved by hand. Everyone with commit or approval rights uses multi-factor
authentication on GitHub and SignPath.

**Privacy:** the app sends nothing anywhere unless you turn on sharing. What it does send, and to where, is in
[PRIVACY.md](PRIVACY.md).
