"""Import and named-run scenarios through the public WebUI application seam."""

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


class WebUIProfilesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='OCR import a profily ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.root = self.directory / 'evidence s mezerami'
        self.app = Application(self.root)

    def source(self, relative, content=b'source one'):
        path = self.directory / relative
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(b'%PDF-1.4\n' + content + b'\n%%EOF\n')
        return path

    def files(self):
        return {p.relative_to(self.root): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def profile(self, name='Věrné čtení', dpi=300):
        return {'schema_version': 1, 'name': name,
                'parameters': {'dpi': dpi, 'language': 'ces', 'model': 'gpt-6.1-sol',
                               'reasoning_effort': 'high'},
                'prompts': {'read': 'Přečti celý zdrojový sken včetně všech článků.',
                            'repair': 'Oprav pouze doložené nálezy podle skenu.',
                            'final_check': 'Porovnej výsledek se zdrojovým skenem.'}}

    def test_pdf_and_folder_import_reuse_content_and_preflight_invalid_inputs(self):
        first = self.source('incoming/zpravodaj.pdf')
        self.source('incoming/kopie.PDF')
        (first.parent / 'notes.txt').write_text('preserve note')
        original = first.read_bytes()
        imported = self.app.dispatch('import_sources', {'path': str(first.parent)})
        self.assertTrue(imported['ok'], imported)
        self.assertEqual(imported['data']['counts'], {'sources': 2, 'created': 1, 'reused': 1})
        self.assertEqual(len(imported['data']['editions']), 1)
        existing_run = imported['data']['editions'][0]['runs'][0]['run_id']
        again = self.app.dispatch('import_sources', {'path': str(first)})
        self.assertEqual(again['data']['counts'], {'sources': 1, 'created': 0, 'reused': 1})
        self.assertEqual(again['data']['editions'][0]['runs'][0]['run_id'], existing_run)
        collision = self.source('different/zpravodaj.pdf', b'source two')
        other = self.app.dispatch('import_sources', {'path': str(collision)})
        self.assertTrue(other['ok'], other)
        self.assertEqual(len(other['data']['editions']), 2)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual((first.parent / 'notes.txt').read_text(), 'preserve note')
        before = self.files()
        invalid_folder = self.source('bad folder/a.pdf', b'otherwise importable').parent
        (invalid_folder / 'z.pdf').write_bytes(b'not a PDF')
        rejected = self.app.dispatch('import_sources', {'path': str(invalid_folder)})
        self.assertFalse(rejected['ok'])
        self.assertEqual(rejected['error']['code'], 'invalid_source')
        self.assertEqual(self.files(), before)

    def test_named_runs_preserve_exact_profile_and_independent_history_after_restart(self):
        source = self.source('zpravodaj.pdf')
        edition = self.app.dispatch('import_sources', {'path': str(source)})['data']['editions'][0]
        path = self.directory / 'profil s mezerami.json'
        first_profile = self.profile()
        first_bytes = (json.dumps(first_profile, ensure_ascii=False, indent=2) + '\r\n').encode()
        path.write_bytes(first_bytes)
        preview = self.app.dispatch('inspect_profile', {'path': str(path)})
        self.assertTrue(preview['ok'], preview)
        self.assertEqual(preview['data']['profile'], first_profile)
        self.assertEqual(preview['data']['text'].encode(), first_bytes)
        first = self.app.dispatch('create_run', {'edition_id': edition['edition_id'],
                                  'name': 'První vizuální čtení', 'profile_path': str(path),
                                  'profile_sha256': preview['data']['sha256']})
        self.assertTrue(first['ok'], first)
        first = first['data']
        self.assertEqual(first['project']['run_name'], 'První vizuální čtení')
        self.assertEqual(first['project']['original_name'], 'zpravodaj.pdf')
        self.assertEqual(first['project']['phase'], 'registered')
        self.assertEqual(first['run']['profile'], first_profile)
        self.assertEqual(first['history'][0]['type'], 'run_created')
        first_id = first['project']['run_id']
        self.assertEqual(first['history'][0]['run_id'], first_id)
        snapshot = self.root / first['artifacts']['profile_snapshot']['path']
        first_history = self.root / first['artifacts']['history']['path']
        saved_history = first_history.read_bytes()
        self.assertEqual(snapshot.read_bytes(), first_bytes)

        second_profile = self.profile('Druhá varianta', dpi=400)
        second_profile['prompts']['read'] = 'Přečti celý sken s důrazem na tabulky.'
        path.write_text(json.dumps(second_profile, ensure_ascii=False))
        changed = self.app.dispatch('inspect_profile', {'path': str(path)})['data']
        second = self.app.dispatch('create_run', {'edition_id': edition['edition_id'],
                                   'name': 'Druhé vizuální čtení', 'profile_path': str(path),
                                   'profile_sha256': changed['sha256']})
        self.assertTrue(second['ok'], second)
        second = second['data']
        self.assertNotEqual(second['project']['run_id'], first_id)
        self.assertNotEqual(second['artifacts']['workspace'], first['artifacts']['workspace'])
        self.assertNotEqual(second['artifacts']['history'], first['artifacts']['history'])
        self.assertEqual(second['run']['profile'], second_profile)
        self.assertEqual(snapshot.read_bytes(), first_bytes)
        self.assertEqual(first_history.read_bytes(), saved_history)

        restarted = Application(self.root)
        reloaded = restarted.dispatch('select_run', {'run_id': first_id})['data']
        self.assertEqual(reloaded['run'], first['run'])
        self.assertEqual(reloaded['history'], first['history'])
        named = [run['run_name'] for e in restarted.dispatch('projects')['data']['editions']
                 for run in e['runs'] if 'run_name' in run]
        self.assertEqual(named, ['První vizuální čtení', 'Druhé vizuální čtení'])

    def test_invalid_changed_or_conflicting_run_conditions_never_publish_a_run(self):
        profile_path = self.directory / 'profile.json'
        profile_path.write_text(json.dumps(self.profile()))
        preview = self.app.dispatch('inspect_profile', {'path': str(profile_path)})['data']
        source = self.source('zpravodaj.pdf')
        edition = self.app.dispatch('import_sources', {'path': str(source)})['data']['editions'][0]
        payload = {'edition_id': edition['edition_id'], 'name': 'Pokus',
                   'profile_path': str(profile_path), 'profile_sha256': preview['sha256']}
        before = self.files()
        profile_path.write_text('{"schema_version": 1}')
        rejected = self.app.dispatch('inspect_profile', {'path': str(profile_path)})
        self.assertEqual(rejected['error']['code'], 'profile_invalid')
        self.assertEqual(self.files(), before)
        profile_path.write_text(json.dumps(self.profile(dpi=400)))
        self.assertEqual(self.app.dispatch('create_run', payload)['error']['code'], 'profile_changed')
        self.assertEqual(self.files(), before)
        preview = self.app.dispatch('inspect_profile', {'path': str(profile_path)})['data']
        payload['profile_sha256'] = preview['sha256']
        created = self.app.dispatch('create_run', payload)
        self.assertTrue(created['ok'], created)
        before = self.files()
        self.assertEqual(self.app.dispatch('create_run', {**payload, 'name': 'pOkUs'})['error']['code'],
                         'run_name_conflict')
        self.assertEqual(self.files(), before)
        managed_source = self.root / created['data']['artifacts']['source']['path']
        managed_source.write_bytes(b'%PDF-1.4\nchanged behind the registry\n%%EOF\n')
        before = self.files()
        changed_source = self.app.dispatch('create_run', {**payload, 'name': 'Nový pokus'})
        self.assertFalse(changed_source['ok'], changed_source)
        self.assertEqual(changed_source['error']['code'], 'source_changed')
        self.assertEqual(self.files(), before)

    def test_profile_inspection_rejects_ambiguous_parameters_without_creating_registry(self):
        path = self.directory / 'invalid profile.json'
        invalid_profiles = [b'{broken', b'\xff',
                            b'{"schema_version":1,"schema_version":1}']
        for parameters in [{'dpi': 0}, {'dpi': True}, {'language': ''},
                           {'model': ''}, {'reasoning_effort': 'silently-default'}, {'ignored_setting': 1}]:
            profile = self.profile()
            profile['parameters'].update(parameters)
            invalid_profiles.append(json.dumps(profile).encode())
        profile = self.profile()
        profile['prompts']['read'] = ''
        invalid_profiles.append(json.dumps(profile).encode())
        for content in invalid_profiles:
            with self.subTest(profile=content[:100]):
                path.write_bytes(content)
                result = self.app.dispatch('inspect_profile', {'path': str(path)})
                self.assertFalse(result['ok'], result)
                self.assertEqual(result['error']['code'], 'profile_invalid')
                self.assertFalse(self.root.exists())
        invalid_path = self.app.dispatch('inspect_profile', {'path': 'invalid\0profile.json'})
        self.assertFalse(invalid_path['ok'])
        self.assertEqual(invalid_path['error']['code'], 'profile_unreadable')
        self.assertFalse(self.root.exists())


if __name__ == '__main__':
    unittest.main()
