"""Structural/routing invariants only; these tests do not measure model judgment."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from buildchoice.desktop import guidance, independent_review as independent, product_store as ps
import test_independent_review as review_fixtures
from guidance_case_manifest import capture, verify
from scripts import sync_guidance


@contextmanager
def fixture_directory():
    # Match the existing checks' inherited-ACL directories; retain failure artifacts.
    root=Path(os.environ.get('BUILDCHOICE_CHECK_ROOT',tempfile.gettempdir()))/('buildchoice-guidance-'+uuid.uuid4().hex)
    root.mkdir()
    yield str(root)


class GuidanceProjectionTests(unittest.TestCase):
    def review_fixture(self, **extra):
        helper=review_fixtures.IndependentReviewTests()
        self.addCleanup(helper.doCleanups)
        f,snap=helper.fixture()
        packet=helper.packet(f,snap,**extra)
        return helper,f,snap,packet

    def test_topics_reach_packet_and_saved_input_survives_catalog_change(self):
        helper,f,snap,p=self.review_fixture(review_topics=['interface'])
        before=p['payload']
        self.assertEqual(before['guidance']['topics'],['interface'])
        self.assertIn(guidance.TOPICS['interface']['en'],before['reviewer_instructions'])
        self.assertNotIn(guidance.TOPICS['documentation']['en'],before['reviewer_instructions'])
        self.assertEqual(before['target_identity']['workspace'],str(f.workspace))
        with f.store.connect() as db:
            row=ps.get(db,p['id'],'review_packet',task_id=f.task)
            source=ps.get(db,snap['id'],'code_snapshot',task_id=f.task)
        with patch.dict(guidance.TOPICS['interface'],en='A future guidance revision'):
            self.assertEqual(independent.materialize(f.store,row,source),before)
            newer=helper.packet(f,snap,review_topics=['interface'])
        self.assertNotEqual(newer['payload']['guidance']['digest'],before['guidance']['digest'])
        self.assertIn('A future guidance revision',newer['payload']['reviewer_instructions'])

    def test_legacy_input_does_not_get_new_guidance_retroactively(self):
        _,f,snap,p=self.review_fixture()
        with f.store.connect() as db:
            row=copy.deepcopy(ps.get(db,p['id'],'review_packet',task_id=f.task))
            source=ps.get(db,snap['id'],'code_snapshot',task_id=f.task)
        del row['data']['guidance']
        with patch.object(guidance,'compose',side_effect=AssertionError('must not regenerate legacy input')):
            value=independent.materialize(f.store,row,source)
        self.assertEqual(value['reviewer_instructions'],independent.LEGACY_REVIEW_GUIDANCE)
        self.assertEqual(value['guidance']['version'],'legacy-0.15.2')
        self.assertEqual(value['guidance']['topics'],[])

    def test_invalid_topics_and_full_packet_budget_do_not_publish_packets(self):
        helper,f,snap,p=self.review_fixture()
        with f.store.connect() as db:before=ps.objects(db,f.task,'review_packet')
        for topics in (['unknown'],['interface','interface']):
            with self.subTest(topics=topics),self.assertRaises(ValueError):helper.packet(f,snap,review_topics=topics)
        with self.assertRaisesRegex(ValueError,'exceeds budget'):
            helper.packet(f,snap,review_topics=['interface','documentation','debugging'],max_chars=2000)
        with f.store.connect() as db:self.assertEqual(ps.objects(db,f.task,'review_packet'),before)
        self.assertEqual(p['payload']['guidance']['topics'],[])

    def test_reconsider_uses_frozen_instructions_and_identity(self):
        helper,f,snap,p=self.review_fixture(review_topics=['documentation'])
        r=helper.submit(f,p,questions=[helper.question()])
        with patch.dict(guidance.RECONSIDER,en='Future instructions that must not leak'):
            b=helper.background(f,r)
        self.assertEqual(b['payload']['guidance'],p['payload']['guidance'])
        self.assertNotIn('Future instructions',b['payload']['instructions'])

    def test_quote_repair_identifies_location_without_echoing_quote_or_source(self):
        helper,f,_,p=self.review_fixture()
        bad=helper.issue();bad['artifacts'][0]['quote']='private-invalid-quote'
        with self.assertRaises(ValueError) as caught:helper.submit(f,p,[bad])
        error=json.loads(str(caught.exception))
        self.assertEqual(error['code'],'EVIDENCE_REPAIR_REQUIRED')
        self.assertEqual(error['issues'][0]['field'],'issues[0].artifacts[0].quote')
        self.assertEqual(error['issues'][0]['path'],'app.py')
        self.assertNotIn('private-invalid-quote',str(caught.exception))
        self.assertNotIn('summary_follows_search',str(caught.exception))

    def test_context_reports_only_included_hints_after_budget_trimming(self):
        _,f,_,_=self.review_fixture()
        small=f.service.context_bundle(f.handle,max_chars=2000)
        self.assertEqual(small['guidance_manifest'],guidance.context_manifest(small['conversation_guidance']))
        full=f.service.context_bundle(f.handle,max_chars=12000)
        self.assertEqual(full['guidance_manifest']['version'],guidance.VERSION)
        self.assertEqual(full['guidance_manifest']['included_keys'],list(guidance.CONTEXT_GUIDANCE))
        self.assertIn('reply_binding',small)

    def test_marked_blocks_are_checked_without_rewriting_unrelated_text(self):
        with fixture_directory() as temp:
            root=Path(temp)
            for relative,names in sync_guidance.BLOCKS.items():
                p=root/relative;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes(('User text\r\n'+''.join(f'<!-- buildchoice-guidance:{n}:start -->\r\nstale\r\n<!-- buildchoice-guidance:{n}:end -->\r\n' for n in names)+'More text\r\n').encode('utf-8'))
            with self.assertRaisesRegex(ValueError,'drift'):sync_guidance.synchronize(root,check=True)
            for relative in sync_guidance.BLOCKS:self.assertIn('stale',(root/relative).read_text(encoding='utf-8'))
            sync_guidance.synchronize(root)
            before={r:(root/r).read_bytes() for r in sync_guidance.BLOCKS}
            self.assertEqual(sync_guidance.synchronize(root),[])
            self.assertEqual(sync_guidance.synchronize(root,check=True),[])
            for r,content in before.items():
                self.assertTrue(content.startswith(b'User text\r\n'));self.assertTrue(content.endswith(b'More text\r\n'))
            broken=next(iter(sync_guidance.BLOCKS))
            (root/broken).write_text('missing markers',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'markers'):sync_guidance.synchronize(root)
            for r,content in before.items():
                if r!=broken:self.assertEqual((root/r).read_bytes(),content)

    def test_output_manifest_rejects_lookalike_root_changed_files_and_escape(self):
        with fixture_directory() as temp:
            base=Path(temp);after=base/'after';original=base/'original'
            for root in (after,original):root.mkdir();(root/'app.py').write_text('same bytes',encoding='utf-8')
            manifest=capture(after,'case-1',['app.py'])
            self.assertEqual(verify(after,'case-1',manifest),manifest)
            with self.assertRaisesRegex(ValueError,'identity'):verify(original,'case-1',manifest)
            (after/'app.py').write_text('new bytes',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'changed'):verify(after,'case-1',manifest)
            with self.assertRaises(ValueError):capture(after,'case-1',['../original/app.py'])
            with self.assertRaises(ValueError):verify(after,'case-2',manifest)

    def test_current_guidance_blocks_match_their_maintained_source(self):
        self.assertEqual(sync_guidance.synchronize(check=True),[])


if __name__=='__main__':unittest.main()
