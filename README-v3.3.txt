My Music Archive v3.3 patch

Fixes:
- Explorer always sorts scrobbles newest-first by Unix timestamp.
- Explorer labels a truncated result as "latest 1,000" instead of "first 1,000".
- GitHub Actions runs update_archive.py with unbuffered Python output (-u), so progress appears live.
- index.html cache-busts app.js as v3.3.

Files to overwrite:
- assets/app.js
- index.html
- .github/workflows/update.yml

No enrichment or archive rebuild is required.
