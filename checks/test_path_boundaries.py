"""Synthetic paths only: exercise real Windows junctions on Python 3.11 too."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from buildchoice.desktop.audit import Ledger
from buildchoice.desktop.verification_inputs import artifact_directory


class PathBoundaryTests(unittest.TestCase):
    def setUp(self):
        base=Path(os.environ.get('BUILDCHOICE_CHECK_ROOT',tempfile.gettempdir()))
        self.workspace=base/('buildchoice-paths-'+uuid.uuid4().hex)
        self.workspace.mkdir()
        # Windows CI TEMP may use an 8.3 alias; match Ledger's canonical root
        # before mocking resolution so the intended private-path branch is exercised.
        self.workspace=self.workspace.resolve()
        self.ledger=Ledger(self.workspace)
        self.session=self.ledger.start('Boundary regression','Synthetic files only')['id']
        self.target=self.workspace/'.aws';self.target.mkdir()
        (self.target/'example.txt').write_text('SYNTHETIC_PRIVATE_DATA',encoding='utf-8')
        self.public=self.workspace/'public';self.public.mkdir()
        (self.public/'example.txt').write_text('PUBLIC_FIXTURE',encoding='utf-8')

    def junction(self,alias,target):
        # Avoid shell interpolation of paths; every target is test-owned.
        env={**os.environ,'BUILDCHOICE_TEST_LINK':str(alias),'BUILDCHOICE_TEST_TARGET':str(target)}
        subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-Command',
            'New-Item -ItemType Junction -Path $env:BUILDCHOICE_TEST_LINK -Target $env:BUILDCHOICE_TEST_TARGET -ErrorAction Stop | Out-Null'],
            env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,check=True,timeout=10)

    def test_ordinary_file_is_read_and_private_names_are_still_excluded(self):
        self.assertEqual(self.ledger.read(self.session,'public/example.txt')['content'],'PUBLIC_FIXTURE')
        with self.assertRaises(ValueError):self.ledger.read(self.session,'.aws/example.txt')
        for name in ('.env','.env.local'):
            (self.workspace/name).write_text('SYNTHETIC_ENV',encoding='utf-8')
            with self.assertRaises(ValueError):self.ledger.read(self.session,name)

    @unittest.skipUnless(os.name=='nt','Real NTFS junction regression')
    def test_windows_junctions_cannot_read_private_or_public_targets(self):
        for name,target in [('private-alias',self.target),('public-alias',self.public)]:
            with self.subTest(target=name):
                self.junction(self.workspace/name,target)
                with self.assertRaises(ValueError):self.ledger.read(self.session,name+'/example.txt')
        with self.ledger.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM sources').fetchone()[0],0)

    @unittest.skipUnless(os.name=='nt','Real NTFS junction regression')
    def test_windows_junction_cannot_redirect_verification_artifacts(self):
        self.junction(self.workspace/'.buildchoice_audit/verification_runs',self.public)
        store=type('Store',(),{'workspace':self.workspace})()
        with self.assertRaises(ValueError):artifact_directory(store,'exec-'+'1'*32,create=True)
        self.assertFalse((self.public/('exec-'+'1'*32)).exists())

    def test_resolved_private_path_is_rechecked_even_if_link_detection_misses(self):
        alias=self.workspace/'alias.txt'
        alias.write_text('PUBLIC_FIXTURE',encoding='utf-8')
        actual_resolve=Path.resolve
        def resolve(path,*args,**kwargs):
            if path==alias:return self.target/'example.txt'
            return actual_resolve(path,*args,**kwargs)
        with patch.object(Path,'resolve',resolve):
            with self.assertRaises(ValueError):self.ledger.read(self.session,'alias.txt')

    def test_symbolic_links_are_rejected(self):
        alias=self.workspace/'symlink'
        try:alias.symlink_to(self.public,target_is_directory=True)
        except OSError as error:self.skipTest('Symlink privilege unavailable: '+str(error))
        with self.assertRaises(ValueError):self.ledger.read(self.session,'symlink/example.txt')


if __name__=='__main__':unittest.main()
