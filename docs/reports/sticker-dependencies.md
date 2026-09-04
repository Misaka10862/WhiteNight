# Sticker dependency review

Date: 2026-09-03

| Dependency | Locked version | Integrity source | License | Conclusion |
|---|---:|---|---|---|
| `Pillow` | `12.3.0` | `uv.lock` package hashes | HPND | Compatible; used only for deterministic local PNG slicing and alpha cropping. |

The direct declaration does not upgrade the existing locked package.  Sticker files remain
runtime data under `data/stickers/` and are excluded from Git.

Native QQ delivery does not depend on the PNG bytes at send time.  Marketplace faces use a
validated `mface`/`market_face` segment with registered QQ identifiers.  Personal saved faces use
NapCat's validated `image` segment with `sub_type=1` and the account-owned QQ expression URL;
NapCat renders that transport as its animated-face type.
