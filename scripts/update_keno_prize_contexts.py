"""Backfill verified top-prize winner counts for recorded winning Keno draws."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ai import keno_prize_context as prizes
from ai.tracking_storage import database_path

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=3)
    parser.add_argument('--evidence-dir',type=Path)
    parser.add_argument('--wait',action='store_true',help='Respect source cooldowns and continue until all needed draws are verified (max 30 minutes)')
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error('limit phải từ 1 đến 1000')
    until = time.monotonic()+1800
    while True:
        try:
            result = prizes.refresh(database_path(),args.limit,evidence_dir=args.evidence_dir)
        except TimeoutError:
            result = {'updated':0,'attempted':0,'errors':[],'status':'existing_refresh_busy'}
        cache=prizes.load_cache()
        targets=prizes.needed_draws(database_path())
        remaining=[key for key,row in targets.items() if prizes.context_for(key,{'main':row['main']},row['drawAt'],cache['draws'])['status']!='ready']
        print(json.dumps({**result,'verified':len(cache['draws']),'remaining':len(remaining)},ensure_ascii=False),flush=True)
        if not remaining:
            raise SystemExit(0)
        if not args.wait or time.monotonic()>=until:
            raise SystemExit(1)
        if not result.get('updated'):
            time.sleep(30)
