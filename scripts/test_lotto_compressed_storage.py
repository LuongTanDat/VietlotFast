"""Run existing business regressions using disposable NTFS-compressed SQLite files."""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import optimize_lotto_storage as storage


def main():
    from tests import test_account_balances as fixtures
    output=ROOT/'runtime/logs/storage_optimization_20261106'
    output.mkdir(parents=True,exist_ok=True)
    scratch=output/'compressed-test-root';scratch.mkdir(exist_ok=True)
    storage.require_ntfs(ROOT)
    storage.compact(ROOT,scratch,output/'regression-compact.log')
    previous_temp=tempfile.tempdir
    tempfile.tempdir=str(scratch)
    original=fixtures.AccountBalanceTests.start_server.__func__
    checked=[]
    def start(cls):
        storage.compact(ROOT,cls.work,output/'regression-compact.log')
        storage.compact(ROOT,cls.work/'runtime',output/'regression-compact.log')
        original(cls)
        detail=storage.info(cls.work/'runtime/lotto_web.db')
        if not detail['compressed']:raise AssertionError('Fixture SQLite file did not inherit compression')
        checked.append({'fixture':cls.__name__,'database':detail})
    fixtures.AccountBalanceTests.start_server=classmethod(start)
    names=[
        'tests.test_card_transfers_web','tests.test_card_interest_web',
        'tests.test_financial_notifications','tests.test_account_card_web',
        'tests.test_wallet_history','tests.test_ticket_seeds',
        'tests.test_seed_lookup','tests.test_bao_display','tests.test_selected_ticket_class',
        'tests.test_storage_optimization'
    ]
    try:
        loaded=unittest.defaultTestLoader.loadTestsFromNames(names)
        def cases(suite):
            for item in suite:
                if isinstance(item,unittest.TestSuite):yield from cases(item)
                else:yield item
        # Avoid rerunning test classes imported by fixture modules and inherited base cases.
        suite=unittest.TestSuite(test for test in cases(loaded) if type(test).__module__ in names and test._testMethodName in type(test).__dict__)
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        report={'ok':result.wasSuccessful(),'testsRun':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'compressedJavaDatabases':checked,'tempDirectoriesInheritedCompression':bool(getattr(scratch.stat(),'st_file_attributes',0)&storage.COMPRESSED),'modules':names}
        storage.save(output/'compressed-regression.json',report)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0 if report['ok'] else 1
    finally:
        fixtures.AccountBalanceTests.start_server=classmethod(original)
        tempfile.tempdir=previous_temp


if __name__=='__main__':raise SystemExit(main())
