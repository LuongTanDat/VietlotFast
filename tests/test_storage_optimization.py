"""Scope guards, benchmark gate, and actual byte-preserving NTFS SQLite I/O."""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

from scripts import optimize_lotto_storage as storage


class StorageOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='storage-tests-',dir=storage.ROOT/'runtime')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in ['config','runtime','Bin']:(self.root/name).mkdir()
        shutil.copy2(storage.ROOT/'config/storage-policy.json',self.root/'config/storage-policy.json')

    def test_scope_and_policy_fail_closed(self):
        for path in ['.git/config','frontend/index.html','runtime/../.git/index','runtime2/file','../outside']:
            with self.assertRaises((ValueError,OSError)):storage.managed(self.root,path)
        self.assertEqual(storage.managed(self.root,'runtime/new.db'),self.root/'runtime/new.db')
        valid=storage.policy(self.root)
        invalid=dict(valid,managedRoots=['runtime','Bin','.git'])
        (self.root/'config/storage-policy.json').write_text(json.dumps(invalid),encoding='utf-8')
        with self.assertRaises(ValueError):storage.policy(self.root)

    def test_no_traversal_to_external_links(self):
        external=self.root/'unmanaged';external.mkdir();(external/'keep').write_text('keep')
        link=self.root/'runtime/link'
        link.mkdir()
        # Exercise link rejection even on Windows accounts without symlink privileges.
        with patch.object(Path,'is_symlink',lambda path:path==link):
            with self.assertRaises(ValueError):storage.managed(self.root,link/'keep')
            result=storage.inventory(self.root)
        self.assertEqual(result['files'],[])
        self.assertEqual(len(result['errors']),1)

    def test_eligibility_and_matching_benchmark_required(self):
        settings=storage.policy(self.root)
        item=dict(path='runtime/data.db',logicalBytes=2*1024**2,compressed=False)
        self.assertTrue(storage.eligible(item,settings))
        for suffix in ['.db-wal','.db-shm','.lock','.tmp','.part']:
            self.assertFalse(storage.eligible(dict(item,path='runtime/file'+suffix),settings))
        self.assertFalse(storage.eligible(dict(item,compressed=True),settings))
        report=self.root/'runtime/benchmark.json'
        base=dict(ok=True,kind='ntfs-sqlite-benchmark-v1',root=str(self.root.resolve()),fingerprint=storage.fingerprint(settings),logicalBytesUnchanged=True,sqliteReadsWritesWal='passed',sampleCount=4,classificationOutputsMatch=True,classificationWithinPolicy=True,indexedPageMilliseconds={'compressed.db':1},maximumCompressedPageMilliseconds=10)
        report.write_text(json.dumps(base),encoding='utf-8')
        storage.verify_benchmark(report,self.root.resolve(),settings)
        for patch in [dict(ok=False),dict(root=str(self.root.parent)),dict(fingerprint='old')]:
            report.write_text(json.dumps({**base,**patch}),encoding='utf-8')
            with self.assertRaises(ValueError):storage.verify_benchmark(report,self.root.resolve(),settings)

    def test_indexed_counts_do_not_parse_large_ticket_arrays_and_preserve_legacy_and_bao(self):
        from ai.prediction_effectiveness import TICKET_COUNT_SQL
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE predictions(prediction_id TEXT PRIMARY KEY,tickets_json TEXT)')
            db.execute('CREATE TABLE counts(prediction_id TEXT PRIMARY KEY,ticket_count INTEGER,chunk_size INTEGER)')
            db.executemany('INSERT INTO predictions VALUES(?,?)',[('large','must not be parsed'),('small','[{},{}]'),('bao','[]'),('legacy','[{},{}]')])
            db.executemany('INSERT INTO counts VALUES(?,?,?)',[('large',1000000,1000),('small',2,0),('bao',324630,0)])
            rows=db.execute(f'SELECT pr.prediction_id,{TICKET_COUNT_SQL} FROM predictions pr LEFT JOIN counts ti ON ti.prediction_id=pr.prediction_id ORDER BY pr.prediction_id').fetchall()
            self.assertEqual(dict(rows),dict(large=1000000,small=2,bao=0,legacy=2))

    @unittest.skipUnless(os.name=='nt','NTFS integration')
    def test_native_compression_preserves_bytes_and_rowids_and_wal_then_undo(self):
        storage.require_ntfs(self.root)
        database=self.root/'runtime/trial.db';log=self.root/'runtime/compact.log'
        payload=json.dumps([dict(main=[1,2,3,4,5],seed=str(i)) for i in range(12000)])
        with closing(sqlite3.connect(database)) as db:
            db.execute('CREATE TABLE events(id TEXT PRIMARY KEY,value TEXT)')
            db.execute('INSERT INTO events(rowid,id,value) VALUES(311,?,?)',('receipt',payload))
            db.commit()
        before=storage.digest(database)
        storage.compact(self.root,database,log,force=True)
        self.assertEqual(before,storage.digest(database))
        self.assertLess(storage.allocated(database),database.stat().st_size*.6)
        with closing(sqlite3.connect(database)) as db:
            self.assertEqual(db.execute('SELECT rowid,id,value FROM events').fetchone(),(311,'receipt',payload))
            db.execute('PRAGMA journal_mode=WAL')
            for i in range(10):
                db.execute('INSERT INTO events VALUES(?,?)',(str(i),'new'))
                db.commit()
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],11)
        with closing(sqlite3.connect(database)) as db:db.execute('PRAGMA journal_mode=DELETE')
        changed=storage.digest(database)
        storage.compact(self.root,database,log,undo=True)
        self.assertEqual(changed,storage.digest(database))
        self.assertFalse(storage.info(database)['compressed'])

    def test_undo_rejects_out_of_scope_before_mutating_anything(self):
        report=self.root/'runtime/report.json'
        report.write_text(json.dumps(dict(root=str(self.root.resolve()),kind='ntfs-storage-apply-v1',changes=[dict(path='.git/config')],directories=[])),encoding='utf-8')
        if os.name!='nt':self.skipTest('Windows only')
        with self.assertRaises(ValueError):storage.undo(report,self.root/'runtime/undo.json',self.root)
