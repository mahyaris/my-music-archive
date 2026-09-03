from __future__ import annotations
import base64, json, os, re
from collections import Counter, defaultdict
from pathlib import Path
import pandas as pd
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITERATIONS = 310_000
MOJIBAKE_MARKERS = ('Ã','Â','â€','â€™','â€œ','â€\x9d','ðŸ','â€“','â€”')
ID_COLUMNS = ['ArtistMBID','AlbumMBID','TrackMBID']
LASTFM_PLACEHOLDER_HASH = '2a96cbd8b46e442fc41c2b86b821562f'


def fix_text(v):
    if not isinstance(v, str) or not any(m in v for m in MOJIBAKE_MARKERS):
        return v
    try:
        candidate = v.encode('latin1').decode('utf8')
        if candidate.count('�') <= v.count('�'):
            return candidate
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return v


def clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    for c in ['Artist','Album','Track']:
        if c not in df.columns:
            df[c] = ''
        df[c] = df[c].fillna('').map(fix_text).astype(str).str.strip()
    for c in ID_COLUMNS:
        if c not in df.columns:
            df[c] = ''
        df[c] = df[c].fillna('').astype(str).replace('nan','').str.strip()
    df['TimestampUTC'] = pd.to_numeric(df['TimestampUTC'], errors='coerce').fillna(0).astype('int64')
    # The export contains a small legacy block numbered 1..N instead of real Unix timestamps.
    df['HasValidDate'] = df['TimestampUTC'] >= 315532800  # 1980-01-01
    df['ParsedDate'] = pd.to_datetime(df['TimestampUTC'].where(df['HasValidDate']), unit='s', utc=True, errors='coerce')
    return df


def derive_key(password: str, salt: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password.encode())


def encrypt_obj(obj, key: bytes, out: Path):
    payload = json.dumps(obj, ensure_ascii=False, separators=(',',':')).encode('utf8')
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, payload, None)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'iv':base64.b64encode(iv).decode(),'ciphertext':base64.b64encode(ct).decode()}, separators=(',',':')), encoding='utf8')


def decrypt_obj(path: Path, key: bytes):
    env = json.loads(path.read_text(encoding='utf8'))
    iv = base64.b64decode(env['iv'])
    ct = base64.b64decode(env['ciphertext'])
    return json.loads(AESGCM(key).decrypt(iv, ct, None).decode('utf8'))


def _nonnull_mode(series: pd.Series) -> str:
    s = series.fillna('').astype(str)
    s = s[(s != '') & (s != 'nan')]
    if s.empty:
        return ''
    return str(s.value_counts().index[0])


def _id_maps(df: pd.DataFrame):
    artist = df.groupby('Artist')['ArtistMBID'].agg(_nonnull_mode).to_dict()
    album = df[df.Album != ''].groupby(['Artist','Album'])['AlbumMBID'].agg(_nonnull_mode).to_dict()
    track = df.groupby(['Artist','Track'])['TrackMBID'].agg(_nonnull_mode).to_dict()
    track_album = df[df.Album != ''].groupby(['Artist','Track'])['Album'].agg(_nonnull_mode).to_dict()
    return artist, album, track, track_album


def top_rows(g, fields, n=20, id_maps=None):
    work = g
    for f in fields:
        if f in ['Artist','Album','Track']:
            work = work[work[f] != '']
    x = work.groupby(fields, dropna=False).size().sort_values(ascending=False).head(n)
    rows=[]
    artist_ids, album_ids, track_ids, track_album = id_maps or ({},{},{},{})
    for idx,count in x.items():
        vals = idx if isinstance(idx,tuple) else (idx,)
        d = {k:(v if isinstance(v,str) else str(v)) for k,v in zip(fields,vals)}
        d['count'] = int(count)
        if fields == ['Artist']:
            name=d['Artist']; d={'name':name,'count':d['count'],'mbid':artist_ids.get(name,'')}
        elif fields == ['Artist','Album']:
            a=d['Artist']; name=d['Album']; d={'name':name,'artist':a,'count':d['count'],'mbid':album_ids.get((a,name),'')}
        elif fields == ['Artist','Track']:
            a=d['Artist']; name=d['Track']; d={'name':name,'artist':a,'album':track_album.get((a,name),''),'count':d['count'],'mbid':track_ids.get((a,name),'')}
        rows.append(d)
    return rows


def _entity_top(g, kind, allowed, id_maps):
    if not allowed:
        return None
    if kind == 'artist':
        x = g[g.Artist.isin(allowed)]
        rows = top_rows(x,['Artist'],1,id_maps)
    elif kind == 'album':
        mask = pd.MultiIndex.from_frame(g[['Artist','Album']]).isin(allowed)
        rows = top_rows(g[mask],['Artist','Album'],1,id_maps)
    else:
        mask = pd.MultiIndex.from_frame(g[['Artist','Track']]).isin(allowed)
        rows = top_rows(g[mask],['Artist','Track'],1,id_maps)
    return rows[0] if rows else None


def _streak_days(g: pd.DataFrame) -> int:
    days = sorted(set(g.ParsedDate.dt.date))
    if not days: return 0
    best=cur=1
    for a,b in zip(days,days[1:]):
        if (b-a).days == 1:
            cur += 1; best=max(best,cur)
        else:
            cur = 1
    return best


def _row_fact(row):
    if row is None: return None
    return {
        'date': row.ParsedDate.isoformat(),
        'artist': row.Artist,
        'album': row.Album,
        'track': row.Track,
    }


def _decorate_with_metadata(row, metadata, kind):
    if not row or not metadata: return row
    if kind == 'artist':
        md = metadata.get('artists',{}).get(row.get('name',''),{})
    elif kind == 'album':
        md = metadata.get('albums',{}).get(f"{row.get('artist','')}|||{row.get('name','')}",{})
    else:
        # Track cards use their most common album's art.
        md = metadata.get('albums',{}).get(f"{row.get('artist','')}|||{row.get('album','')}",{})
    if md:
        image = md.get('image')
        if kind == 'artist' and image and LASTFM_PLACEHOLDER_HASH in image:
            image = ''
        fallback = md.get('fallbackImage') if kind == 'artist' else ''
        image = image or fallback
        if image: row['image'] = image
        # Preserve a second URL so the browser can recover if a remote artist
        # photo fails to hotlink. Album art is an especially reliable fallback.
        if fallback and fallback != image:
            row['fallbackImage'] = fallback
        if md.get('tags'): row['tags'] = md['tags'][:5]
        if md.get('releaseYear'): row['releaseYear'] = md['releaseYear']
        if md.get('country'): row['country'] = md['country']
    return row


def _weighted_tags(g: pd.DataFrame, metadata, n=8):
    if not metadata: return [], 0.0
    artist_counts = g.Artist.value_counts()
    scores=Counter(); covered=0
    for artist,count in artist_counts.items():
        md=metadata.get('artists',{}).get(artist,{})
        tags=md.get('tags') or []
        if not tags: continue
        covered += int(count)
        for rank,tag in enumerate(tags[:5]):
            scores[tag] += float(count) * (1.0 / (rank + 1))
    total=max(sum(scores.values()),1)
    rows=[{'name':name,'score':round(score,3),'share':round(score/total*100,2)} for name,score in scores.most_common(n)]
    return rows, round(covered/len(g)*100,1) if len(g) else 0.0


def _tag_timeline(g: pd.DataFrame, metadata, top_tags):
    if not metadata or not top_tags: return []
    tag_names=[x['name'] for x in top_tags[:6]]
    out=[]
    for m in range(1,13):
        gm=g[g.ParsedDate.dt.month==m]
        scores=Counter()
        for artist,count in gm.Artist.value_counts().items():
            tags=(metadata.get('artists',{}).get(artist,{}) or {}).get('tags') or []
            for rank,tag in enumerate(tags[:5]):
                if tag in tag_names:
                    scores[tag] += float(count)*(1.0/(rank+1))
        out.append({'month':m, **{tag:round(scores.get(tag,0),2) for tag in tag_names}})
    return out


def _canonical_country(name):
    """Normalize MusicBrainz areas to sovereign-country labels for the map.

    MusicBrainz can return a subdivision such as England/Scotland as an
    artist's area. For a world-country map those must be aggregated into the
    United Kingdom, otherwise the leaderboard double-counts the same country.
    """
    name=(name or '').strip()
    aliases={
        'England':'United Kingdom','Scotland':'United Kingdom','Wales':'United Kingdom','Northern Ireland':'United Kingdom',
        'United States of America':'United States','USA':'United States','U.S.A.':'United States',
        'Russian Federation':'Russia','Türkiye':'Turkey','Czech Republic':'Czechia',
        'Republic of Korea':'South Korea','Korea, Republic of':'South Korea',
        'Iran, Islamic Republic of':'Iran','Viet Nam':'Vietnam',
    }
    return aliases.get(name,name)


def _artist_map(g: pd.DataFrame, metadata, n=20):
    if not metadata: return {'countries':[],'coverage':0}
    by=defaultdict(int); top_by_country={}; covered=0
    for artist,count in g.Artist.value_counts().items():
        md=metadata.get('artists',{}).get(artist,{})
        country=_canonical_country(md.get('country'))
        if not country: continue
        covered += int(count); by[country]+=int(count)
        if country not in top_by_country or count > top_by_country[country]['count']:
            top_by_country[country]={'name':artist,'count':int(count),'image':md.get('image','')}
    countries=[{'name':c,'count':v,'topArtist':top_by_country[c]} for c,v in sorted(by.items(),key=lambda kv:kv[1],reverse=True)[:n]]
    return {'countries':countries,'coverage':round(covered/len(g)*100,1) if len(g) else 0}


def _music_decades(g: pd.DataFrame, metadata):
    if not metadata: return {'decades':[],'coverage':0}
    by=Counter(); top={}; covered=0
    album_counts=g[g.Album!=''].groupby(['Artist','Album']).size().sort_values(ascending=False)
    for (artist,album),count in album_counts.items():
        md=metadata.get('albums',{}).get(f'{artist}|||{album}',{})
        ry=md.get('releaseYear')
        if not ry: continue
        covered += int(count)
        decade = 'Pre-1960' if int(ry) < 1960 else f"{int(ry)//10*10}s"
        by[decade]+=int(count)
        if decade not in top or count > top[decade]['count']:
            top[decade]={'name':album,'artist':artist,'count':int(count),'image':md.get('image',''),'releaseYear':int(ry)}
    order=lambda d: -1 if d=='Pre-1960' else int(re.match(r'(\d+)',d).group(1))
    rows=[{'decade':d,'count':by[d],'topAlbum':top[d]} for d in sorted(by,key=order)]
    return {'decades':rows,'coverage':round(covered/len(g)*100,1) if len(g) else 0}


def _prepare_artist_image_fallbacks(df: pd.DataFrame, metadata):
    """Use an artist's most-scrobbled enriched album cover when no photo exists.

    This prevents empty Hall of Fame cards for artists that have no reusable
    Wikimedia/Wikipedia image while keeping real artist photos as first choice.
    """
    if not metadata: return
    artists=metadata.get('artists',{})
    albums=metadata.get('albums',{})
    if not artists or not albums: return
    v=df[(df.Artist!='')&(df.Album!='')]
    if v.empty: return
    counts=v.groupby(['Artist','Album']).size().sort_values(ascending=False)
    done=set()
    for (artist,album),_ in counts.items():
        if artist in done: continue
        md=artists.get(artist)
        if not md:
            done.add(artist); continue
        artist_image=md.get('image') or ''
        if artist_image and LASTFM_PLACEHOLDER_HASH not in artist_image:
            done.add(artist); continue
        amd=albums.get(f'{artist}|||{album}',{})
        if amd.get('image'):
            md['fallbackImage']=amd['image']
            md['fallbackImageAlbum']=album
            done.add(artist)


def build_summary(df: pd.DataFrame, metadata=None):
    _prepare_artist_image_fallbacks(df,metadata)
    valid=df[df.HasValidDate].copy()
    valid['Year']=valid.ParsedDate.dt.year.astype(int)
    valid['Hour']=valid.ParsedDate.dt.hour
    valid['DOW']=valid.ParsedDate.dt.dayofweek
    valid['Month']=valid.ParsedDate.dt.month
    valid['DateOnly']=valid.ParsedDate.dt.date
    total=len(df); years=sorted(valid.Year.unique().tolist())
    id_maps=_id_maps(df)

    topArtists=top_rows(df,['Artist'],100,id_maps)
    topAlbums=top_rows(df,['Artist','Album'],100,id_maps)
    topTracks=top_rows(df,['Artist','Track'],100,id_maps)

    # Artist span metadata.
    span=valid[valid.Artist!=''].groupby('Artist')['Year'].agg(['min','max'])
    for r in topArtists:
        if r['name'] in span.index:
            r['firstYear']=int(span.loc[r['name'],'min']); r['lastYear']=int(span.loc[r['name'],'max']); r['yearsActive']=int(r['lastYear']-r['firstYear']+1)
        _decorate_with_metadata(r,metadata,'artist')
    for r in topAlbums: _decorate_with_metadata(r,metadata,'album')
    for r in topTracks: _decorate_with_metadata(r,metadata,'track')

    first_artist_year=valid[valid.Artist!=''].groupby('Artist')['Year'].min()
    album_valid=valid[valid.Album!='']
    first_album_year=album_valid.groupby(['Artist','Album'])['Year'].min()
    first_track_year=valid[valid.Track!=''].groupby(['Artist','Track'])['Year'].min()

    yearly=[]; yearDetails={}; previous_discovery=None
    dow_labels=['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    for y in years:
        g=valid[valid.Year==y].copy(); sc=len(g)
        artists=set(g.loc[g.Artist!='','Artist'].unique())
        albums=set(map(tuple,g.loc[g.Album!='',['Artist','Album']].drop_duplicates().to_numpy()))
        tracks=set(map(tuple,g.loc[g.Track!='',['Artist','Track']].drop_duplicates().to_numpy()))
        new_artists={a for a in artists if int(first_artist_year.get(a,y))==y}
        new_albums={a for a in albums if int(first_album_year.get(a,y))==y}
        new_tracks={t for t in tracks if int(first_track_year.get(t,y))==y}
        discovery={
            'artists': {'count':len(new_artists),'percentage':round(len(new_artists)/len(artists)*100,1) if artists else 0},
            'albums': {'count':len(new_albums),'percentage':round(len(new_albums)/len(albums)*100,1) if albums else 0},
            'tracks': {'count':len(new_tracks),'percentage':round(len(new_tracks)/len(tracks)*100,1) if tracks else 0},
        }
        for k in discovery:
            prev=(previous_discovery or {}).get(k,{}).get('percentage')
            discovery[k]['delta']=round(discovery[k]['percentage']-prev,1) if prev is not None else None
        discovery['artists']['topItem']=_entity_top(g,'artist',new_artists,id_maps)
        discovery['albums']['topItem']=_entity_top(g,'album',new_albums,id_maps)
        discovery['tracks']['topItem']=_entity_top(g,'track',new_tracks,id_maps)
        for k,kind in [('artists','artist'),('albums','album'),('tracks','track')]:
            _decorate_with_metadata(discovery[k]['topItem'],metadata,kind)
        previous_discovery=discovery

        a=len(artists); top10=g.Artist.value_counts().head(10).sum()/sc*100 if sc else 0
        ta=g.Artist.value_counts().index[0] if sc else ''
        yearly.append({'year':int(y),'scrobbles':int(sc),'artists':int(a),'albums':int(len(albums)),'tracks':int(len(tracks)),'topArtist':ta,'top10Share':round(top10,3),'diversityPer1000':round(a/sc*1000,3) if sc else 0,
                       'newArtistPct':discovery['artists']['percentage'],'newAlbumPct':discovery['albums']['percentage'],'newTrackPct':discovery['tracks']['percentage']})

        ta_rows=top_rows(g,['Artist'],30,id_maps); al_rows=top_rows(g,['Artist','Album'],30,id_maps); tr_rows=top_rows(g,['Artist','Track'],30,id_maps)
        for r in ta_rows: _decorate_with_metadata(r,metadata,'artist')
        for r in al_rows: _decorate_with_metadata(r,metadata,'album')
        for r in tr_rows: _decorate_with_metadata(r,metadata,'track')

        dowc=g.DOW.value_counts(); hourc=g.Hour.value_counts()
        activity={'dayOfWeek':[{'label':dow_labels[i],'count':int(dowc.get(i,0))} for i in range(7)],'hour':[{'label':f'{i:02d}','count':int(hourc.get(i,0))} for i in range(24)]}
        busiest_dow=max(activity['dayOfWeek'],key=lambda x:x['count'])
        busiest_hour=max(activity['hour'],key=lambda x:x['count'])
        day_counts=g.groupby('DateOnly').size().sort_values(ascending=False)
        busiest_date={'date':str(day_counts.index[0]),'count':int(day_counts.iloc[0])} if len(day_counts) else None
        first_row=g.sort_values('ParsedDate').iloc[0] if sc else None
        last_row=g.sort_values('ParsedDate').iloc[-1] if sc else None
        artist_day=g.groupby(['DateOnly','Artist']).size().sort_values(ascending=False)
        rabbit=None
        if len(artist_day):
            (d,a_name),c=artist_day.index[0],int(artist_day.iloc[0]); rabbit={'date':str(d),'artist':a_name,'count':c}
        funFacts={
            'firstScrobble':_row_fact(first_row),
            'lastScrobble':_row_fact(last_row),
            'busiestDate':busiest_date,
            'longestDailyStreak':_streak_days(g),
            'deepestRabbitHole':rabbit,
            'weekendShare':round((g.DOW>=5).mean()*100,1) if sc else 0,
            'lateNightShare':round(g.Hour.between(0,5).mean()*100,1) if sc else 0,
        }
        topTags,tagCoverage=_weighted_tags(g,metadata)
        tagTimeline=_tag_timeline(g,metadata,topTags)
        yearDetails[str(y)]={
            'scrobbles':int(sc),'uniqueArtists':int(a),'uniqueAlbums':int(len(albums)),'uniqueTracks':int(len(tracks)),'top10Share':round(top10,3),
            'topArtists':ta_rows,'topAlbums':al_rows,'topTracks':tr_rows,'discovery':discovery,'funFacts':funFacts,'activity':activity,
            'busiestDay':busiest_dow,'busiestHour':busiest_hour,'topTags':topTags,'tagCoverage':tagCoverage,'tagTimeline':tagTimeline,
        }

    # Global activity.
    dowc=valid.DOW.value_counts(); hourc=valid.Hour.value_counts()
    activity={'dayOfWeek':[{'label':dow_labels[i],'count':int(dowc.get(i,0))} for i in range(7)],'hour':[{'label':f'{i:02d}','count':int(hourc.get(i,0))} for i in range(24)]}

    redis=[]; forgotten=[]; latest=max(years)
    for artist,g in valid.groupby('Artist'):
        if not artist: continue
        ys=sorted(g.Year.unique()); c=len(g); gaps=[b-a for a,b in zip(ys,ys[1:])]
        if gaps and max(gaps)>=3 and c>=20: redis.append({'name':artist,'count':int(c),'sub':f'{max(gaps)}-year gap'})
        if ys and ys[-1] <= latest-5 and c>=100: forgotten.append({'name':artist,'count':int(c),'sub':f'last played {ys[-1]}'})
    redis=sorted(redis,key=lambda r:r['count'],reverse=True); forgotten=sorted(forgotten,key=lambda r:r['count'],reverse=True)
    for r in redis: _decorate_with_metadata(r,metadata,'artist')
    for r in forgotten: _decorate_with_metadata(r,metadata,'artist')
    ay=valid.groupby(['Year','Artist']).size(); (oy,oa),oc=ay.idxmax(),int(ay.max())
    longest=max(topArtists,key=lambda r:(r.get('lastYear',0)-r.get('firstYear',0),r['count'])) if topArtists else None
    diverse=max(yearly,key=lambda r:r['diversityPer1000']) if yearly else None

    # Extra celebratory insights.
    album_years=valid[valid.Album!=''].groupby(['Artist','Album'])['Year'].nunique().sort_values(ascending=False)
    enduring_album=None
    if len(album_years):
        (ea,ean),ey=album_years.index[0],int(album_years.iloc[0]); cnt=int(((valid.Artist==ea)&(valid.Album==ean)).sum()); enduring_album={'name':ean,'artist':ea,'years':ey,'count':cnt}
    track_day=valid.groupby(['Artist','Track','DateOnly']).size().sort_values(ascending=False)
    binge_track=None
    if len(track_day):
        (ba,bt,bd),bc=track_day.index[0],int(track_day.iloc[0]); binge_track={'name':bt,'artist':ba,'date':str(bd),'count':bc}
    insights={'rediscovered':redis[:100],'forgotten':forgotten[:100],'biggestObsession':{'name':oa,'year':int(oy),'count':oc},'longestRunning':longest,'mostDiverseYear':diverse,'enduringAlbum':enduring_album,'biggestTrackBinge':binge_track}

    first=valid.ParsedDate.min(); latestdt=valid.ParsedDate.max()
    overview={'totalScrobbles':int(total),'datedScrobbles':int(len(valid)),'undatedScrobbles':int(total-len(valid)),'uniqueArtists':int(df[df.Artist!=''].Artist.nunique()),'uniqueAlbums':int(df[df.Album!=''].groupby(['Artist','Album']).ngroups),'uniqueTracks':int(df[df.Track!=''].groupby(['Artist','Track']).ngroups),'firstYear':int(min(years)),'latestYear':int(max(years)),'yearsTracked':len(years),'firstDate':first.isoformat(),'latestDate':latestdt.isoformat(),'metadataEnriched':bool(metadata)}
    artistMap=_artist_map(valid,metadata)
    musicByDecade=_music_decades(valid,metadata)
    return {'overview':overview,'yearly':yearly,'yearDetails':yearDetails,'topArtists':topArtists,'topAlbums':topAlbums,'topTracks':topTracks,'activity':activity,'insights':insights,'artistMap':artistMap,'musicByDecade':musicByDecade}


def shard_rows(df):
    valid=df[df.HasValidDate].copy(); valid['Year']=valid.ParsedDate.dt.year.astype(int)
    result={}
    for y,g in valid.groupby('Year'):
        result[int(y)]=[{
            'ts':int(r.TimestampUTC),
            'date':r.ParsedDate.strftime('%Y-%m-%d %H:%M'),
            'artist':r.Artist,
            'album':r.Album,
            'track':r.Track,
            'artistMbid':getattr(r,'ArtistMBID','') or '',
            'albumMbid':getattr(r,'AlbumMBID','') or '',
            'trackMbid':getattr(r,'TrackMBID','') or ''
        } for r in g.itertuples(index=False)]
    return result
