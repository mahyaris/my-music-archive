from __future__ import annotations
import argparse, getpass, json, os, random, re, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
import pandas as pd
from archive_lib import clean_frame

UA='MyMusicArchive/2.0 (personal Last.fm dashboard)'
LASTFM='https://ws.audioscrobbler.com/2.0/'
MB='https://musicbrainz.org/ws/2/artist/'
MB_RELEASE='https://musicbrainz.org/ws/2/release/'
MB_RELEASE_GROUP='https://musicbrainz.org/ws/2/release-group/'
WIKIDATA='https://www.wikidata.org/w/api.php'
WIKIPEDIA='https://en.wikipedia.org/w/api.php'
COMMONS_REDIRECT='https://commons.wikimedia.org/wiki/Special:Redirect/file/'
AUDIODB='https://www.theaudiodb.com/api/v1/json/123/'
LASTFM_PLACEHOLDER_HASH='2a96cbd8b46e442fc41c2b86b821562f'


def get_json(url, params=None, delay=.25, attempts=4):
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept':'application/json'})
    retryable={429,500,502,503,504}
    for attempt in range(1, attempts+1):
        try:
            with urllib.request.urlopen(req,timeout=30) as r:
                data=json.load(r)
            if delay: time.sleep(delay)
            return data
        except urllib.error.HTTPError as e:
            if e.code not in retryable or attempt >= attempts:
                raise
            retry_after=e.headers.get('Retry-After') if e.headers else None
            try:
                server_wait=float(retry_after) if retry_after is not None else 0.0
            except ValueError:
                server_wait=0.0
            # Some MusicBrainz 503 responses currently advertise Retry-After: 0.
            # Retrying immediately only increases pressure on the service, so enforce
            # a real exponential backoff plus a little jitter.
            backoff=min(2 ** attempt, 16)
            wait=max(server_wait, backoff) + random.uniform(0.25, 0.9)
            print(f'    HTTP {e.code}; retrying in {wait:.1f}s ({attempt}/{attempts})...')
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt >= attempts:
                raise
            wait=min(2 ** attempt, 12)
            print(f'    Temporary network error; retrying in {wait:.0f}s ({attempt}/{attempts})...')
            time.sleep(wait)
    raise RuntimeError('Request failed after retries')


def largest_image(images):
    vals=[]
    for x in images or []:
        u=(x.get('#text') or '').strip()
        if u: vals.append(u)
    return vals[-1] if vals else ''


def usable_artist_image(url):
    url=(url or '').strip()
    return bool(url) and LASTFM_PLACEHOLDER_HASH not in url


def _wikidata_qid_from_relations(relations):
    for rel in relations or []:
        url=((rel.get('url') or {}).get('resource') or '').strip()
        if rel.get('type') == 'wikidata' or 'wikidata.org/wiki/Q' in url:
            m=re.search(r'/wiki/(Q\d+)',url)
            if m: return m.group(1)
    return ''


def _commons_image_url(filename, width=1200):
    if not filename: return ''
    # Special:Redirect/file generates a browser-friendly thumbnail while keeping
    # the original Wikimedia Commons file attribution/licensing page discoverable.
    return COMMONS_REDIRECT + urllib.parse.quote(filename, safe='') + f'?width={int(width)}'


def wikimedia_artist_image(qid):
    """Return (image_url, source_status) for a Wikidata entity.

    Prefer Wikidata P18. If P18 is absent, fall back to the lead image from the
    entity's English Wikipedia article when one exists.
    """
    if not qid: return '', 'no-wikidata'
    data=get_json(WIKIDATA,{
        'action':'wbgetentities','ids':qid,'props':'claims|sitelinks',
        'sitefilter':'enwiki','format':'json'
    },delay=.15)
    ent=(data.get('entities') or {}).get(qid,{})
    claims=ent.get('claims') or {}
    p18=claims.get('P18') or []
    if p18:
        try:
            filename=p18[0]['mainsnak']['datavalue']['value']
            if filename: return _commons_image_url(filename), 'wikidata-p18'
        except (KeyError,TypeError,IndexError):
            pass
    title=((ent.get('sitelinks') or {}).get('enwiki') or {}).get('title')
    if title:
        page=get_json(WIKIPEDIA,{
            'action':'query','prop':'pageimages','piprop':'thumbnail',
            'pithumbsize':1200,'redirects':1,'titles':title,'format':'json'
        },delay=.15)
        pages=((page.get('query') or {}).get('pages') or {})
        for rec in pages.values():
            src=((rec.get('thumbnail') or {}).get('source') or '').strip()
            if src: return src, 'wikipedia-lead'
    return '', 'no-image'


def enrich_artist_photo(current, mbid, name):
    """Populate a real artist image from MusicBrainz -> Wikidata/Wikipedia.

    Last.fm currently returns no useful artist photography to third-party API
    clients in practice, even though album artwork remains available. This path
    is deliberately separate from album art enrichment.
    """
    if usable_artist_image(current.get('image')):
        current['photoFetched']=True
        current.setdefault('photoStatus','existing-image')
        return current
    # Last.fm's generic star placeholder is not an artist photo. Remove it so
    # the dashboard can use Wikimedia or the album-cover fallback instead.
    if current.get('image') and not usable_artist_image(current.get('image')):
        current['image']=''
    if not mbid:
        current['photoFetched']=True
        current['photoStatus']='no-mbid'
        return current
    try:
        mb=get_json(MB+urllib.parse.quote(mbid),{'fmt':'json','inc':'url-rels'},delay=1.05)
        # Reuse this request to fill geography if the previous run could not.
        if not current.get('country'):
            area=mb.get('area') or mb.get('begin-area') or {}
            if area.get('name'): current['country']=area.get('name','')
        qid=_wikidata_qid_from_relations(mb.get('relations'))
        current['wikidata']=qid
        if not qid:
            current['photoFetched']=True
            current['photoStatus']='no-wikidata-relation'
            return current
        image,status=wikimedia_artist_image(qid)
        if image:
            current['image']=image
            current['imageSource']=status
        current['photoFetched']=True
        current['photoStatus']='ok' if image else status
        current.pop('photoError',None)
    except Exception as e:
        print(f'  Artist photo failed: {name}: {e}')
        # Keep False so a later rerun retries transient failures.
        current['photoFetched']=False
        current['photoError']=str(e)
    return current




def audiodb_artist_images(mbid, name):
    """Return curated (square_thumb, wide_thumb, artist_id) from TheAudioDB.

    TheAudioDB is used before Wikimedia because its artist artwork fields are
    purpose-built for music apps. The public v1 test key is documented by
    TheAudioDB; requests are paced below its free 30 req/min limit.
    """
    if mbid:
        url=AUDIODB+'artist-mb.php'
        params={'i':mbid}
    else:
        url=AUDIODB+'search.php'
        params={'s':name}
    data=get_json(url,params,delay=2.15,attempts=4)
    rows=data.get('artists') or []
    if not rows:
        return '', '', ''
    # MBID lookup is exact. Name search returns a single record on the free API;
    # still prefer an exact case-insensitive name when available.
    rec=rows[0]
    target=(name or '').casefold().strip()
    for row in rows:
        if (row.get('strArtist') or '').casefold().strip()==target:
            rec=row; break
    square=(rec.get('strArtistThumb') or rec.get('strArtistWideThumb') or rec.get('strArtistFanart') or '').strip()
    wide=(rec.get('strArtistWideThumb') or rec.get('strArtistFanart') or rec.get('strArtistThumb') or '').strip()
    return square, wide, (rec.get('idArtist') or '')


def parse_year(value):
    if not value: return None
    m=re.search(r'\b(18|19|20)\d{2}\b',str(value))
    return int(m.group(0)) if m else None


def _mb_release_group_year(group):
    if not group: return None
    return parse_year(group.get('first-release-date') or group.get('first_release_date'))


def musicbrainz_release_year(mbid, artist, album):
    """Resolve an album's original release year from MusicBrainz.

    Prefer cheap direct MBID lookups. This avoids leaning on the MusicBrainz
    indexed-search service for every album, which is more prone to transient
    503 responses. Only fall back to title/artist search when direct lookup
    cannot identify a release year.
    Returns (year, status).
    """
    mbid=(mbid or '').strip()
    if mbid:
        # The Last.fm AlbumMBID can be either a release-group MBID or a release
        # MBID. Try release-group first; a 404 simply means it is the other type.
        try:
            group=get_json(MB_RELEASE_GROUP+urllib.parse.quote(mbid),
                           {'fmt':'json'},delay=1.15,attempts=5)
            year=_mb_release_group_year(group)
            if year: return year, 'musicbrainz-release-group'
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise

        try:
            release=get_json(MB_RELEASE+urllib.parse.quote(mbid),
                             {'fmt':'json','inc':'release-groups'},delay=1.15,attempts=5)
            # Prefer the release group's first-release date when exposed; the
            # release date is a useful fallback for edition-specific MBIDs.
            year=_mb_release_group_year(release.get('release-group') or {}) \
                 or parse_year(release.get('date'))
            if year: return year, 'musicbrainz-release'
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise

    # No usable MBID: use one indexed search by album title + artist. This is the
    # fallback path rather than the default path, substantially reducing load.
    aq=(artist or '').replace('\\','\\\\').replace('"','\\"')
    lq=(album or '').replace('\\','\\\\').replace('"','\\"')
    query=f'releasegroup:"{lq}" AND artist:"{aq}"'
    data=get_json(MB_RELEASE_GROUP,{'query':query,'fmt':'json','limit':8},delay=1.15,attempts=5)
    rows=data.get('release-groups') or []
    target_album=(album or '').casefold().strip()
    target_artist=(artist or '').casefold().strip()
    best=None
    for row in rows:
        title=(row.get('title') or '').casefold().strip()
        credits=' '.join((c.get('name') or (c.get('artist') or {}).get('name') or '') for c in (row.get('artist-credit') or [])).casefold()
        score=(2 if title==target_album else 0)+(2 if target_artist and target_artist in credits else 0)+float(row.get('score') or 0)/100.0
        if best is None or score>best[0]: best=(score,row)
    if best:
        year=_mb_release_group_year(best[1])
        if year: return year, 'musicbrainz-title-search'
    return None, 'no-release-year'


def mode_nonempty(s):
    s=s.fillna('').astype(str); s=s[(s!='')&(s!='nan')]
    return str(s.value_counts().index[0]) if not s.empty else ''


def artist_candidates(df, per_year=35, overall=50):
    v=df[df.HasValidDate].copy(); v['Year']=v.ParsedDate.dt.year
    names=set(v.Artist.value_counts().head(overall).index)
    for _,g in v.groupby('Year'):
        names.update(g.Artist.value_counts().head(per_year).index)
    return [x for x in names if x]


def album_candidates(df, per_year=45, overall=70):
    v=df[(df.HasValidDate)&(df.Album!='')].copy(); v['Year']=v.ParsedDate.dt.year
    pairs=set(v.groupby(['Artist','Album']).size().sort_values(ascending=False).head(overall).index)
    for _,g in v.groupby('Year'):
        pairs.update(g.groupby(['Artist','Album']).size().sort_values(ascending=False).head(per_year).index)
    return sorted(pairs)


def main():
    ap=argparse.ArgumentParser(description='Fetch optional artwork, tags, release years and artist countries for the dashboard.')
    ap.add_argument('csv')
    ap.add_argument('--out',default=str(Path(__file__).resolve().parents[1]/'cache'/'metadata.json'))
    ap.add_argument('--skip-geo',action='store_true',help='Skip slower MusicBrainz country lookups.')
    args=ap.parse_args()
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    cache=json.loads(out.read_text(encoding='utf8')) if out.exists() else {'artists':{},'albums':{}}
    api=os.getenv('LASTFM_API_KEY') or getpass.getpass('Last.fm API key (input hidden): ').strip()
    if not api: raise SystemExit('Last.fm API key is required.')
    df=clean_frame(pd.read_csv(args.csv,low_memory=False))
    artist_mbid=df.groupby('Artist')['ArtistMBID'].agg(mode_nonempty).to_dict()
    album_mbid=df[df.Album!=''].groupby(['Artist','Album'])['AlbumMBID'].agg(mode_nonempty).to_dict()

    artists=artist_candidates(df)
    print(f'Artist metadata candidates: {len(artists)}')
    for i,name in enumerate(artists,1):
        current=cache['artists'].get(name,{})
        # v2.1 can recover old v2 failures: successful v2 Last.fm fetches always wrote
        # image/tags/mbid, while failed ones only wrote lastfmFetched=True.
        old_lastfm_failure = current.get('lastfmFetched') and not any(k in current for k in ('image','tags','mbid'))
        if not current.get('lastfmFetched') or old_lastfm_failure:
            try:
                p={'method':'artist.getinfo','api_key':api,'format':'json','autocorrect':1}
                mbid=artist_mbid.get(name,'')
                if mbid: p['mbid']=mbid
                else: p['artist']=name
                a=get_json(LASTFM,p).get('artist',{})
                tags=[t.get('name','').strip() for t in (a.get('tags',{}).get('tag') or []) if t.get('name')]
                current.update({'image':largest_image(a.get('image')),'tags':tags[:8],'mbid':a.get('mbid') or mbid,'lastfmFetched':True})
                current.pop('lastfmError',None)
            except Exception as e:
                print(f'  Last.fm artist failed: {name}: {e}')
                current['lastfmFetched']=False
                current['lastfmError']=str(e)
        if not args.skip_geo:
            mbid=current.get('mbid') or artist_mbid.get(name,'')
            # v2 marked geoFetched=True even after a failed request. If there is an MBID
            # but no country/status, retry it once under the corrected logic.
            old_geo_failure = current.get('geoFetched') and mbid and 'country' not in current and 'geoStatus' not in current
            if mbid and (not current.get('geoFetched') or old_geo_failure):
                try:
                    a=get_json(MB+urllib.parse.quote(mbid),{'fmt':'json'},delay=1.05)
                    area=a.get('area') or a.get('begin-area') or {}
                    current['country']=area.get('name','')
                    current['geoFetched']=True
                    current['geoStatus']='ok' if current['country'] else 'no-country'
                    current.pop('geoError',None)
                except Exception as e:
                    print(f'  MusicBrainz geo failed: {name}: {e}')
                    current['geoFetched']=False
                    current['geoError']=str(e)
            elif not mbid:
                current['geoFetched']=True
                current['geoStatus']='no-mbid'

        # Artist photography uses a music-specific source first. TheAudioDB has
        # curated Artist Thumb / WideThumb fields, which are usually a better fit
        # for a music dashboard than a generic Wikipedia lead image. This pass is
        # intentionally independent from the older photoFetched flag so v2.2
        # caches can be upgraded without throwing away existing metadata.
        mbid=current.get('mbid') or artist_mbid.get(name,'')
        if not current.get('audioDbFetched'):
            try:
                square,wide,audio_id=audiodb_artist_images(mbid,name)
                if square:
                    current['image']=square
                    current['imageSource']='theaudiodb-thumb'
                if wide:
                    current['imageWide']=wide
                if audio_id:
                    current['audioDbId']=audio_id
                current['audioDbFetched']=True
                current['audioDbStatus']='ok' if square else 'no-image'
                current.pop('audioDbError',None)
            except Exception as e:
                print(f'  TheAudioDB artist failed: {name}: {e}')
                current['audioDbFetched']=False
                current['audioDbError']=str(e)

        # Fall back to MusicBrainz -> Wikidata/Wikipedia only when TheAudioDB did
        # not supply an artist image. Existing successful Wikimedia cache entries
        # remain valid and transient failures are retryable.
        if not usable_artist_image(current.get('image')) and not current.get('photoFetched'):
            current=enrich_artist_photo(current,mbid,name)
        elif usable_artist_image(current.get('image')) and not current.get('photoFetched'):
            current['photoFetched']=True
            current['photoStatus']='existing-image'

        cache['artists'][name]=current
        if i%20==0:
            out.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding='utf8'); print(f'  Artists {i}/{len(artists)}')

    albums=album_candidates(df)
    print(f'Album metadata candidates: {len(albums)}')
    for i,(artist,album) in enumerate(albums,1):
        key=f'{artist}|||{album}'; current=cache['albums'].get(key,{})
        old_lastfm_failure = current.get('lastfmFetched') and not any(k in current for k in ('image','tags','releaseYear','mbid'))
        if not current.get('lastfmFetched') or old_lastfm_failure:
            try:
                p={'method':'album.getinfo','api_key':api,'format':'json','autocorrect':1}
                mbid=album_mbid.get((artist,album),'')
                if mbid: p['mbid']=mbid
                else: p.update({'artist':artist,'album':album})
                a=get_json(LASTFM,p).get('album',{})
                tags=[t.get('name','').strip() for t in (a.get('toptags',{}).get('tag') or []) if t.get('name')]
                current.update({'image':largest_image(a.get('image')),'tags':tags[:8],'releaseYear':parse_year(a.get('releasedate')),'mbid':a.get('mbid') or mbid,'lastfmFetched':True})
                current.pop('lastfmError',None)
            except Exception as e:
                print(f'  Last.fm album failed: {artist} — {album}: {e}')
                current['lastfmFetched']=False
                current['lastfmError']=str(e)
        # Last.fm reliably supplies album artwork but frequently leaves the
        # release date blank. Fill only missing years from MusicBrainz and cache
        # the result so later enrichment runs do not repeat hundreds of calls.
        mbid=current.get('mbid') or album_mbid.get((artist,album),'')
        if not current.get('releaseYear') and not current.get('releaseYearFetched'):
            try:
                year,status=musicbrainz_release_year(mbid,artist,album)
                if year: current['releaseYear']=int(year)
                current['releaseYearFetched']=True
                current['releaseYearStatus']=status
                current.pop('releaseYearError',None)
            except Exception as e:
                print(f'  MusicBrainz release year failed: {artist} — {album}: {e}')
                current['releaseYearFetched']=False
                current['releaseYearError']=str(e)
        elif current.get('releaseYear') and not current.get('releaseYearFetched'):
            current['releaseYearFetched']=True
            current['releaseYearStatus']='lastfm'

        cache['albums'][key]=current
        if i%25==0:
            out.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding='utf8'); print(f'  Albums {i}/{len(albums)}')

    out.write_text(json.dumps(cache,ensure_ascii=False,indent=2),encoding='utf8')
    print(f'Done. Metadata cache written to {out}')
    print('Re-run build_archive.py to embed the enriched metadata into the encrypted archive.')

if __name__=='__main__': main()
