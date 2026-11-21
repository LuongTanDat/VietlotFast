"""Verified historical corrections must not leak to other draw identities."""
import unittest
from unittest import mock
import tempfile
from pathlib import Path
import backend.live_results as lr

class VerifiedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.result = {'key':'LOTO_6_45','ky':'2','date':'20/07/2016','time':'','main':[2,17,33,37,38,45],'special':None,'sourceUrl':'https://www.minhchinh.com/archive.html','jackpot':12000000000}
        self.identity = '20/07/2016||2,17,33,37,38,45|'
        self.evidence = {'sourceKy':'2','canonicalKy':'1','verifiedBy':'vietlott.vn','sourceUrl':'https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/645?id=00001&nocatche=1','jackpot':12357724500,'prizeHit':'','prizeHitKnown':True,'prizeWinnerCounts':{'jackpot':0,'first':3,'second':222,'third':4242}}

    def test_only_exact_observed_identity_is_corrected_without_mutation(self):
        original = dict(self.result)
        corrected = lr.apply_verified_history_correction(self.result,{self.identity:self.evidence})
        self.assertEqual(corrected['ky'],'1')
        self.assertEqual(corrected['jackpot'],12357724500)
        self.assertEqual(corrected['prizeWinnerCounts']['third'],4242)
        self.assertEqual(self.result,original)
        for changes in [{'date':'22/07/2016'},{'ky':'1'},{'main':[3,4,14,20,25,35]},{'sourceUrl':'https://other.example/archive'}]:
            row = {**self.result,**changes}
            self.assertIs(lr.apply_verified_history_correction(row,{self.identity:self.evidence}),row)
        for changes in [{'canonicalKy':'0'},{'verifiedBy':'unknown'}]:
            self.assertIs(lr.apply_verified_history_correction(self.result,{self.identity:{**self.evidence,**changes}}),self.result)

    def test_stale_metadata_writer_keeps_verified_corrections(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'meta.json'
            existing = {'verifiedSourceCorrections':{self.identity:self.evidence}}
            with mock.patch.object(lr,'read_canonical_meta',return_value=existing),mock.patch.object(lr,'get_canonical_meta_path',return_value=path):
                lr.write_canonical_meta('LOTO_6_45',{'type':'LOTO_6_45'})
            import json
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['verifiedSourceCorrections'],existing['verifiedSourceCorrections'])
