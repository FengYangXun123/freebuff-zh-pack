# freebuff-zh-pack — Chinese localization for Freebuff Desktop

Unofficial Simplified Chinese patch for Freebuff Desktop. Runtime injection into the local shell — no server-side changes, no network access, fully reversible.

> Current target: **Freebuff Desktop 0.0.206** (Windows x64) · see `manifests/compat-matrix.md` · English below is a summary; the Chinese README is authoritative.

## What it does

Since 0.0.201 the Freebuff Desktop UI comes from the freebuff.com web app; the vendor ships no Chinese locale. This pack injects a runtime translation layer into the local shell's `app.asar`:

- **6,386 dictionary entries**: 3,946 maintained here (`zh-main` 1184 + `zh-remote` 2762), plus the vocabulary of [Kfowever/freebuff-zh-patch](https://github.com/Kfowever/freebuff-zh-patch) (3,978 entries, MIT, credited in `licenses/`) injected as a second layer; 6,386 after deduplication (v0.11.12 sync added 558 net entries; our wording wins on overlaps)
- **Two layers share one merged dictionary** — our wording wins, the community layer fills gaps; React re-render races cannot diverge wording
- **Chat content untouched**: only UI attributes and text nodes are processed; user input, conversations and code blocks are physically excluded

## Three safeguards

| Safeguard | Protects against | Behavior |
|---|---|---|
| **Fuse pre-check** | upstream enabling asar integrity validation | Reads the Electron fuse bits in the binary; refuses to install when validation is ON (forced injection would brick the app) |
| **Runtime self-check** | injection script failing silently | The payload is executed under a minimal DOM stub before anything is written; failures abort the install |
| **Baseline integrity** | polluted or half-patched state | First install backs up the pristine `app.asar` (`.zhorig`); restore is a hash-verified byte-level copy |

## Install (Windows x64)

1. Download `freebuff-zh-pack-vX.Y.Z.zip` from [Releases](../../releases) and unzip
2. Fully quit Freebuff (including tray)
3. Run `安装.cmd` and pick from the menu: `1` install · `2` status · `3` check updates · `4` restore English
4. Launch Freebuff — the UI is now Chinese

**Dependencies**: Python 3.9+ and Node.js 18+ (both free; the launcher auto-detects Python and validates it). CLI: `python install.py --install|--status|--check-update|--restore`, exit codes documented in README.md.

## Compatibility

- **0.0.206**: verified with v0.1.2 — official package sha512 matches `latest.yml`, fuse still OFF/ON, sandbox install against pristine asar passed (6,386 entries, all gates green); pristine sha `b768b8c7…` / patched `563c9a0e…`
- 0.0.205: verified with v0.1.1 (clean-install round trip on real hardware; earlier dictionary snapshot)
- 0.0.204: verified with v0.1.0 (earlier dictionary snapshot)
- 0.0.196–0.0.203: untested, expected to work (dictionary covers that range)
- Newer versions: installer warns but proceeds — worst case is untranslated residue, never a broken app
- Hard refusals (no override): asar integrity fuse ON, or unexpected app architecture

Remote copy (freebuff.com web deployment) updates on its own schedule; new server-side strings may appear in English for a few days until the dictionary catches up. Server-side ads and promo banners are out of scope.

macOS / Linux: not supported yet (unverified = unreleased). `install.py` is written platform-neutral; mac adaptation is demand-driven — +1 in the issues if you want it.

## Disclaimer & credits

Non-official community patch; modifies only local `resources/app.asar`; no network access, no data upload, no server-side changes. Freebuff and related marks belong to their owners; this project is not affiliated with upstream. Provided as-is, no warranty. Full text in [NOTICE.md](NOTICE.md) — which also credits [Kfowever/freebuff-zh-patch](https://github.com/Kfowever/freebuff-zh-patch) (MIT, license text included) as the source of the second vocabulary layer. This project's own code and dictionaries are MIT-licensed.

模式参考（非代码引用）：[javaht/claude-desktop-zh-cn](https://github.com/javaht/claude-desktop-zh-cn)、[antigravity-cn-community](https://github.com/antigravity-cn-community/Antigravity-Chinese-Localization)
