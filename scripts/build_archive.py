from pathlib import Path
import argparse, base64, getpass, json, os
import pandas as pd
from archive_lib import clean_frame, derive_key, encrypt_obj, build_summary, shard_rows, ITERATIONS

ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser(description='Bootstrap My Music Archive from a Last.fm CSV export.')
    ap.add_argument('csv')
    ap.add_argument('--out',default=str(ROOT/'data'))
    ap.add_argument('--metadata',default=str(ROOT/'cache'/'metadata.json'),help='Optional metadata cache created by enrich_metadata.py')
    args=ap.parse_args(); out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    password=os.getenv('ARCHIVE_PASSWORD') or getpass.getpass('Archive password (do not share it): ')
    if len(password)<12: raise SystemExit('Use a password of at least 12 characters.')
    print('Reading CSV…'); df=clean_frame(pd.read_csv(args.csv,low_memory=False))
    metadata=None; mp=Path(args.metadata)
    if mp.exists():
        print(f'Loading enrichment metadata: {mp}')
        metadata=json.loads(mp.read_text(encoding='utf8'))
    else:
        print('No enrichment metadata found; tags, artwork, geography and release-decade panels will stay optional.')
    print('Building aggregates…'); summary=build_summary(df,metadata=metadata); shards=shard_rows(df)
    salt=os.urandom(16); key=derive_key(password,salt)
    manifest={'version':3,'years':sorted(shards),'crypto':{'kdf':'PBKDF2-SHA256','iterations':ITERATIONS,'salt':base64.b64encode(salt).decode()},'metadataEnriched':bool(metadata)}
    (out/'manifest.json').write_text(json.dumps(manifest,separators=(',',':')),encoding='utf8')
    print('Encrypting summary…'); encrypt_obj(summary,key,out/'summary.enc.json')
    if metadata:
        print('Encrypting enrichment metadata…'); encrypt_obj(metadata,key,out/'metadata.enc.json')
    for y,rows in shards.items():
        print(f'Encrypting {y}: {len(rows):,} rows'); encrypt_obj(rows,key,out/f'year-{y}.enc.json')
    print(f'Done. {len(df):,} scrobbles processed; {len(shards)} dated year shards created.')

if __name__=='__main__': main()
