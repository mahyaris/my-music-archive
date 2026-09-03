from pathlib import Path
import base64, json, os, time, urllib.parse, urllib.request
import pandas as pd

from archive_lib import decrypt_obj, derive_key, encrypt_obj, clean_frame, build_summary, shard_rows
from enrich_metadata import (
    LASTFM, MB, get_json, largest_image, parse_year, audiodb_artist_images,
    enrich_artist_photo, usable_artist_image, musicbrainz_release_year
)

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'


def api_page(username,key,page=1,from_ts=None):
    q={'method':'user.getrecenttracks','user':username,'api_key':key,'format':'json','limit':200,'page':page}
    if from_ts: q['from']=str(from_ts)
    req=urllib.request.Request(
        'https://ws.audioscrobbler.com/2.0/?'+urllib.parse.urlencode(q),
        headers={'User-Agent':'MyMusicArchive/2.4'}
    )
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.load(r)


def _mode_nonempty(series):
    s=series.fillna('').astype(str)
    s=s[(s!='')&(s!='nan')]
    return str(s.value_counts().index[0]) if not s.empty else ''


def enrich_new_metadata(metadata, fresh, api_key):
    """Enrich only artists/albums seen in the newly fetched scrobbles.

    This keeps scheduled updates fast while ensuring newly discovered music gets
    artwork, tags, release decades and geography without a manual enrichment run.
    """
    metadata=metadata or {'artists':{},'albums':{}}
    metadata.setdefault('artists',{})
    metadata.setdefault('albums',{})

    artist_mbid=fresh.groupby('Artist')['ArtistMBID'].agg(_mode_nonempty).to_dict()
    album_rows=fresh[fresh.Album!='']
    album_mbid=album_rows.groupby(['Artist','Album'])['AlbumMBID'].agg(_mode_nonempty).to_dict() if not album_rows.empty else {}

    for name in sorted(x for x in fresh.Artist.unique() if x):
        current=metadata['artists'].get(name,{})
        mbid=current.get('mbid') or artist_mbid.get(name,'')

        if not current.get('lastfmFetched'):
            try:
                p={'method':'artist.getinfo','api_key':api_key,'format':'json','autocorrect':1}
                if mbid: p['mbid']=mbid
                else: p['artist']=name
                a=get_json(LASTFM,p).get('artist',{})
                tags=[t.get('name','').strip() for t in (a.get('tags',{}).get('tag') or []) if t.get('name')]
                mbid=a.get('mbid') or mbid
                current.update({'image':largest_image(a.get('image')),'tags':tags[:8],'mbid':mbid,'lastfmFetched':True})
                current.pop('lastfmError',None)
            except Exception as e:
                print(f'  Last.fm artist enrichment failed: {name}: {e}')
                current['lastfmFetched']=False
                current['lastfmError']=str(e)

        if mbid and not current.get('geoFetched'):
            try:
                a=get_json(MB+urllib.parse.quote(mbid),{'fmt':'json'},delay=1.05)
                area=a.get('area') or a.get('begin-area') or {}
                current['country']=area.get('name','')
                current['geoFetched']=True
                current['geoStatus']='ok' if current['country'] else 'no-country'
                current.pop('geoError',None)
            except Exception as e:
                print(f'  MusicBrainz geo enrichment failed: {name}: {e}')
                current['geoFetched']=False
                current['geoError']=str(e)

        if not current.get('audioDbFetched'):
            try:
                square,wide,audio_id=audiodb_artist_images(mbid,name)
                if square:
                    current['image']=square
                    current['imageSource']='theaudiodb-thumb'
                if wide: current['imageWide']=wide
                if audio_id: current['audioDbId']=audio_id
                current['audioDbFetched']=True
                current['audioDbStatus']='ok' if square else 'no-image'
                current.pop('audioDbError',None)
            except Exception as e:
                print(f'  TheAudioDB artist enrichment failed: {name}: {e}')
                current['audioDbFetched']=False
                current['audioDbError']=str(e)

        if not usable_artist_image(current.get('image')) and not current.get('photoFetched'):
            current=enrich_artist_photo(current,mbid,name)
        elif usable_artist_image(current.get('image')) and not current.get('photoFetched'):
            current['photoFetched']=True
            current['photoStatus']='existing-image'

        metadata['artists'][name]=current

    for artist,album in sorted(set(map(tuple,album_rows[['Artist','Album']].to_numpy()))):
        key=f'{artist}|||{album}'
        current=metadata['albums'].get(key,{})
        if not current.get('lastfmFetched'):
            try:
                mbid=current.get('mbid') or album_mbid.get((artist,album),'')
                p={'method':'album.getinfo','api_key':api_key,'format':'json','autocorrect':1}
                if mbid: p['mbid']=mbid
                else: p.update({'artist':artist,'album':album})
                a=get_json(LASTFM,p).get('album',{})
                tags=[t.get('name','').strip() for t in (a.get('toptags',{}).get('tag') or []) if t.get('name')]
                current.update({
                    'image':largest_image(a.get('image')),
                    'tags':tags[:8],
                    'releaseYear':parse_year(a.get('releasedate')),
                    'mbid':a.get('mbid') or mbid,
                    'lastfmFetched':True
                })
                current.pop('lastfmError',None)
            except Exception as e:
                print(f'  Last.fm album enrichment failed: {artist} — {album}: {e}')
                current['lastfmFetched']=False
                current['lastfmError']=str(e)
        mbid=current.get('mbid') or album_mbid.get((artist,album),'')
        if not current.get('releaseYear') and not current.get('releaseYearFetched'):
            try:
                year,status=musicbrainz_release_year(mbid,artist,album)
                if year: current['releaseYear']=int(year)
                current['releaseYearFetched']=True
                current['releaseYearStatus']=status
                current.pop('releaseYearError',None)
            except Exception as e:
                print(f'  MusicBrainz release-year enrichment failed: {artist} — {album}: {e}')
                current['releaseYearFetched']=False
                current['releaseYearError']=str(e)
        elif current.get('releaseYear') and not current.get('releaseYearFetched'):
            current['releaseYearFetched']=True
            current['releaseYearStatus']='lastfm'
        metadata['albums'][key]=current

    return metadata


def main():
    password=os.environ['ARCHIVE_PASSWORD']
    api=os.environ['LASTFM_API_KEY']
    username=os.environ['LASTFM_USERNAME']

    manifest=json.loads((DATA/'manifest.json').read_text())
    key=derive_key(password,base64.b64decode(manifest['crypto']['salt']))
    metadata=decrypt_obj(DATA/'metadata.enc.json',key) if (DATA/'metadata.enc.json').exists() else {'artists':{},'albums':{}}

    rows=[]
    for y in manifest['years']:
        rows.extend(decrypt_obj(DATA/f'year-{y}.enc.json',key))
    max_ts=max(r['ts'] for r in rows)
    print('Latest stored timestamp:',max_ts)

    new=[]
    page=1
    while True:
        res=api_page(username,api,page,from_ts=max_ts+1)
        tracks=res.get('recenttracks',{}).get('track',[])
        for t in tracks:
            if t.get('@attr',{}).get('nowplaying')=='true' or not t.get('date'):
                continue
            new.append({
                'TimestampUTC':int(t['date']['uts']),
                'DateUTC':t['date'].get('#text',''),
                'Artist':t['artist'].get('#text',''),
                'Album':t['album'].get('#text',''),
                'Track':t.get('name',''),
                'ArtistMBID':t['artist'].get('mbid',''),
                'AlbumMBID':t['album'].get('mbid',''),
                'TrackMBID':t.get('mbid','')
            })
        total_pages=int(res.get('recenttracks',{}).get('@attr',{}).get('totalPages','1'))
        if page>=total_pages: break
        page+=1
        time.sleep(.25)

    if not new:
        print('No new scrobbles.')
        return

    old=pd.DataFrame([{
        'TimestampUTC':r['ts'],
        'Artist':r.get('artist',''),
        'Album':r.get('album',''),
        'Track':r.get('track',''),
        'ArtistMBID':r.get('artistMbid',''),
        'AlbumMBID':r.get('albumMbid',''),
        'TrackMBID':r.get('trackMbid','')
    } for r in rows])
    fresh=clean_frame(pd.DataFrame(new))
    metadata=enrich_new_metadata(metadata,fresh,api)

    df=clean_frame(pd.concat([old,fresh],ignore_index=True).drop_duplicates(
        subset=['TimestampUTC','Artist','Album','Track']
    ))
    summary=build_summary(df,metadata=metadata)
    shards=shard_rows(df)

    manifest['version']=3
    manifest['years']=sorted(shards)
    manifest['metadataEnriched']=True
    (DATA/'manifest.json').write_text(json.dumps(manifest,separators=(',',':')))
    encrypt_obj(summary,key,DATA/'summary.enc.json')
    encrypt_obj(metadata,key,DATA/'metadata.enc.json')
    for y,r in shards.items():
        encrypt_obj(r,key,DATA/f'year-{y}.enc.json')
    print(f'Added {len(new):,} scrobbles; archive and metadata rebuilt.')


if __name__=='__main__':
    main()
