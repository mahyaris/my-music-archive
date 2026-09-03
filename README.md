# My Music Archive — v2.5

A private-by-cryptography Last.fm history dashboard for GitHub Pages. The visual direction mixes Spotify/Last.fm presentation with deeper personal analytics.

## What's new in v2

### Years
Each year now has its own mini-report with:
- percentage of **new artists**, **new albums** and **new tracks** compared with everything you had heard previously
- the top new artist / album / track for that year
- first scrobble of the year
- busiest date
- longest daily listening streak
- deepest one-day artist rabbit hole
- weekly scrobbles compared with the previous year
- a 24-hour radial **Listening Clock**
- year-specific top artists, albums and tracks
- optional Last.fm tag/genre timeline

### Artists / Albums / Tracks
The first 15 are now presented as a visual Hall of Fame rather than only a table. When enrichment metadata is present, cards use artwork and tags. The pages also include contextual/fun insights before the searchable deep catalog.

## Privacy model

GitHub Pages itself is public on a free personal account. The project therefore publishes only the application shell plus **AES-256-GCM encrypted listening data**. Your password is not stored in the site. The browser derives a key locally with PBKDF2-SHA256 and decrypts the archive in memory.

The optional metadata cache (`cache/metadata.json`) is deliberately ignored by Git. When you rebuild the archive, that metadata is embedded into `data/metadata.enc.json`, so artist/album names from the enrichment cache are not exposed in the public repository.

This is client-side encryption, not server-side access control. A later Streamlit version can add real account authentication.

## 1. Install dependencies

Python 3.11+ is recommended.

```powershell
python -m pip install pandas cryptography
```

## 2. Optional but recommended: add artwork, genres, geography and release years

Your Last.fm CSV does **not** contain genres, artist countries or album release years. v2 can enrich the most important artists/albums using:
- Last.fm `artist.getInfo` — artist imagery/tags
- Last.fm `album.getInfo` — album art, tags and release dates
- MusicBrainz — artist area/country when a MusicBrainz artist ID is available

Run:

```powershell
python scripts\enrich_metadata.py "C:\Users\yaghm\Downloads\lastfm_scrobbles.csv"
```

It will prompt for your Last.fm API key with hidden input. The key is not written into the project.

The MusicBrainz geography pass is deliberately rate-limited, so the first enrichment can take several minutes. If you want the artwork/tags/release dates first and do not care about the map yet:

```powershell
python scripts\enrich_metadata.py "C:\Users\yaghm\Downloads\lastfm_scrobbles.csv" --skip-geo
```

You can run it again later without `--skip-geo`; the cache prevents successful Last.fm lookups from being downloaded again.

## 3. Build/rebuild the encrypted archive

Run:

```powershell
python scripts\build_archive.py "C:\Users\yaghm\Downloads\lastfm_scrobbles.csv"
```

Use the **same archive password** you chose previously if this is replacing v1.

If `cache/metadata.json` exists, the build automatically uses it. Otherwise the core dashboard still works; the year-specific Tags panel and the Overview Artist Map / Music by Decade panels show explanatory notes until enrichment is done.

The build:
- fixes common UTF-8/Latin-1 mojibake
- keeps the legacy invalid-timestamp block separate from dated history
- calculates discovery rates and year-level facts
- creates all visual analytics
- splits raw scrobbles into encrypted year shards
- encrypts summary and optional enrichment metadata

## 4. Preview locally

From the repository folder:

```powershell
python -m http.server 8000
```

Open:

```text
http://localhost:8000
```

Keep that PowerShell window open while using the site. Press **Ctrl+C** to stop the server.

## 5. GitHub Pages

Create a public GitHub repository such as `my-music-archive`, push the project to `main`, then choose **GitHub Actions** under **Settings → Pages**. The included `pages.yml` workflow deploys the static app.

Do **not** commit the original CSV. `.gitignore` blocks CSV files and the unencrypted metadata cache.

## 6. Daily updates

Add these repository secrets under **Settings → Secrets and variables → Actions**:
- `ARCHIVE_PASSWORD`
- `LASTFM_API_KEY`
- `LASTFM_USERNAME`

The included workflow checks Last.fm once per day and encrypts new scrobbles into the archive.

The automatic updater enriches newly encountered artists and albums and preserves the encrypted metadata archive. It also fills release-year metadata for new albums so Music by Decade stays current.

## Metadata coverage

Tags, the artist map and music-by-decade are enrichment-based. The dashboard displays a coverage percentage so it does not imply that metadata exists for 100% of the relevant scrobbles. The global Artist Map and Music by Decade panels live on Overview; yearly pages keep only year-specific tags.

The country map is loaded from a public GeoJSON file at runtime after you unlock the archive. If the map asset cannot load, the dashboard falls back to a country ranking rather than breaking Overview.


## v2.2 artist-photo enrichment

v2.2 fixes artist cards that showed placeholders even though album artwork worked. Last.fm artist API imagery is not relied on for photography; artist images are resolved from MusicBrainz relationships to Wikidata/Wikipedia. If no reusable artist photo is available, the dashboard falls back to that artist's most-scrobbled enriched album cover instead of an empty star card. Existing `cache/metadata.json` from v2/v2.1 can be reused; rerun `enrich_metadata.py`, then `build_archive.py`.


## v2.3 artist image update
Artist cards now prefer TheAudioDB's dedicated Artist Thumb artwork, then fall back to Wikimedia, then to the artist's most-played album cover. The browser no longer forces `no-referrer` on image requests, and artist cards retain an album-art fallback if a remote photo fails. Existing `cache/metadata.json` can be reused; rerun `enrich_metadata.py`, then `build_archive.py`.

## v2.4 production notes

Before the first GitHub publish, rebuild the archive once with v2.4. The encrypted yearly shards now retain MusicBrainz IDs, allowing the scheduled updater to enrich newly discovered artists and albums automatically.

The daily updater now:
- downloads only scrobbles newer than the newest encrypted timestamp;
- enriches newly encountered artists/albums with Last.fm, MusicBrainz, TheAudioDB and Wikimedia fallbacks;
- re-encrypts both listening data and metadata;
- commits only the `data/` directory.

The raw CSV, local metadata cache and environment files remain excluded by `.gitignore`.


## v2.5 overview consolidation

- All-time Podium now shows seven artists so the desktop five-column mosaic has no empty cell.
- Artist Map moved from each Year page to Overview and now emphasizes the top country separately from the other represented countries.
- Music by Decade moved alongside the global Artist Map on Overview.
- The three headline insight cards, Rediscovered and Forgotten Favorites are now part of Overview.
- The separate Insights navigation/page was removed.
- Rediscovered and Forgotten Favorites inherit artist artwork when enrichment metadata is available.

## v2.6 geography and release-era fix

- Artist Map country colors are applied through explicit map regions, with country-name normalization for common GeoJSON naming differences.
- The #1 country uses a dedicated maximum-contrast color; other represented countries use high-contrast blue/cyan tiers. Hover is neutral rather than pink.
- The map legend is removed. The footer now lists the top three countries and their scrobble counts.
- Music by Decade now fills missing album release years from MusicBrainz because Last.fm frequently returns album artwork while leaving `releasedate` empty.
- Existing `cache/metadata.json` is reused. Rerun `enrich_metadata.py` once with v2.6, then rebuild the archive. Only albums missing release-year metadata trigger the MusicBrainz fallback; for a few hundred albums this can take roughly 10–15 minutes because MusicBrainz requests are deliberately rate-limited.
