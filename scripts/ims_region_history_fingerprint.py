"""Fingerprint pre-October business rows and active historical snapshots."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import create_app
from app.extensions import db


def fingerprint(connection):
    result={}
    tables={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ('ims_uploads','ims_facts','ims_summary','ims_raw_data','targets','ims_competition_data'):
        if table not in tables:continue
        digest=hashlib.sha256();count=0
        for row in connection.execute(f'SELECT * FROM {table} WHERE year<2026 OR (year=2026 AND month<10) ORDER BY id'):
            digest.update(json.dumps(row,ensure_ascii=True,separators=(',',':'),default=str).encode());digest.update(b'\n');count+=1
        result[table]={'rows':count,'sha256':digest.hexdigest()}
    for sets,rows in (('manager_region_snapshot_sets','manager_region_snapshots'),('representative_snapshot_sets','representative_snapshots')):
        if sets not in tables or rows not in tables:continue
        digest=hashlib.sha256();count=0
        sql=f"SELECT r.* FROM {rows} r JOIN {sets} s ON s.id=r.set_id WHERE s.status='ACTIVE' AND (s.year<2026 OR (s.year=2026 AND s.month<10)) ORDER BY r.id"
        for row in connection.execute(sql):
            digest.update(json.dumps(row,ensure_ascii=True,separators=(',',':'),default=str).encode());digest.update(b'\n');count+=1
        result[rows]={'rows':count,'sha256':digest.hexdigest()}
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline',type=Path,required=True);parser.add_argument('--compare',action='store_true');args=parser.parse_args()
    app=create_app()
    with app.app_context():
        path=Path(db.engine.url.database).resolve()
        with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as connection:
            connection.execute('PRAGMA query_only=ON')
            current=fingerprint(connection)
    if args.compare:
        previous=json.loads(args.baseline.read_text())
        changed=[table for table in set(previous)|set(current) if previous.get(table)!=current.get(table)]
        print('IMS_HISTORY_UNCHANGED|'+json.dumps(dict(result='FAIL' if changed else 'PASS',changed=changed,tables=current)))
        return 1 if changed else 0
    if args.baseline.exists():raise RuntimeError('Refusing to overwrite historical baseline')
    args.baseline.parent.mkdir(parents=True,exist_ok=True)
    args.baseline.write_text(json.dumps(current),encoding='utf-8')
    print('IMS_HISTORY_BASELINE|'+json.dumps(current))
    return 0


if __name__=='__main__':raise SystemExit(main())
