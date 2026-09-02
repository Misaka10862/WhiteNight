# Sticker dependency review

Date: 2026-09-01

| Dependency | Locked version | Integrity source | License | Conclusion |
|---|---:|---|---|---|
| `Pillow` | `12.3.0` | `uv.lock` package hashes | HPND | Compatible; used only for deterministic local PNG slicing and alpha cropping. |

The direct declaration does not upgrade the existing locked package.  Sticker files remain
runtime data under `data/stickers/` and are excluded from Git.

Native QQ delivery does not depend on the PNG bytes at send time.  OneBot receives only a
validated `mface`/`market_face` segment with the registered QQ identifiers.
