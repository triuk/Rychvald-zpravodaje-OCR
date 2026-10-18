#!/usr/bin/env python3
"""Generate new raster sources and hold a blinded oracle until explicit publication.

No model inference is performed. Expected random values are held only in this
owned host process, never written to a file before a validated publication.
The source commitment and original sample boxes are public before any AI turn.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import secrets
import sys
import time
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.service import Application


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def normalized(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New durable proof directory.')
    parser.add_argument('--root', type=Path, required=True, help='New synthetic proof registry.')
    parser.add_argument('--real-source', type=Path, required=True, help='Original public municipal scan.')
    args = parser.parse_args()
    output, registry = args.output.resolve(), args.root.resolve()
    if output.exists() or registry.exists():
        parser.error('Choose new proof and registry paths; earlier evidence is preserved.')
    output.mkdir(parents=True)
    from PIL import Image, ImageDraw, ImageFont
    import fitz
    font_path = '/usr/share/fonts/noto/NotoSerif-Regular.ttf'
    font = ImageFont.truetype(font_path, 40)
    heading = ImageFont.truetype(font_path, 48)
    code = secrets.token_hex(4).upper()
    hour, minute = 6 + secrets.randbelow(12), secrets.randbelow(60)
    names = ['Vacková', 'Černá', 'Šimková', 'Novotná', 'Žáková']
    lines = [
        ['RYCHVALDSKÝ ZPRAVODAJ', 'Výprava číslo R-' + code,
         'Koordinátor: Žofie ' + secrets.choice(names), f'Odjezd 17. 10. 2026 v {hour:02d}:{minute:02d}',
         f'Vstupné {100 + secrets.randbelow(800)} Kč.', 'Tato věta obsahuje tiskovou chibu.', 'Článek pokračuje na straně 2.'],
        ['Pokračování výpravy R-' + code, 'Seznam rezervací',
         f'Skupina A: {12 + secrets.randbelow(70)} osob', f'Skupina B: {12 + secrets.randbelow(70)} osob',
         'Kontakt: Jana Šťastná', 'Kontrolní kód: ' + secrets.token_hex(5).upper()]]
    samples, images = [], []
    for index, texts in enumerate(lines, 1):
        image = Image.new('RGB', (1400, 1000 if index == 1 else 900), 'white')
        draw = ImageDraw.Draw(image)
        for row, text in enumerate(texts):
            position, used = (55, 55 + row * 120), heading if row == 0 else font
            draw.text(position, text, fill='black', font=used)
            box = draw.textbbox(position, text, font=used)
            samples.append({'id': f'original-{index}-{row + 1}', 'page': index,
                'bbox': [box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4], 'expected': text,
                'expected_origin': 'Fresh source raster generated before AI; random literal held in host memory; original pixel box from source font layout.'})
        path = output / f'synthetic-source-{index}.png'
        image.save(path)
        images.append(path)
    source = output / 'novy-synteticky-sken.pdf'
    with fitz.open() as document:
        for path in images:
            with Image.open(path) as image:
                page = document.new_page(width=image.width * .24, height=image.height * .24)
                page.insert_image(page.rect, filename=str(path))
        document.save(source)
    actual_source = args.real_source.resolve()
    real_hash = sha(actual_source)
    with fitz.open(actual_source) as original:
        raster = original[1].get_pixmap(dpi=300, alpha=False)
        image = Image.frombytes('RGB', (raster.width, raster.height), raster.samples)
    region = [1070, 290, 2600, 540]
    crop = image.crop(region)
    original_crop = output / 'real-source-page-2-original-crop.png'
    crop.save(original_crop)
    real_pdf = output / 'novy-obtizny-vyrez.pdf'
    with fitz.open() as document:
        page = document.new_page(width=crop.width * .24, height=crop.height * .24)
        page.insert_image(page.rect, filename=str(original_crop))
        document.save(real_pdf)
    app = Application(registry)
    cases = []
    try:
        profile = app.dispatch('inspect_profile', {'path': str(ROOT / 'profiles/faithful-reading.json')})['data']
        for kind, path in [('synthetic', source), ('difficult', real_pdf)]:
            imported = app.dispatch('import_sources', {'path': str(path)})
            if not imported['ok']:
                raise RuntimeError(str(imported['error']))
            edition = next(e for e in imported['data']['editions'] if e['source_sha256'] == sha(path))
            run = app.dispatch('create_run', {'edition_id': edition['edition_id'], 'name': 'Skutečné první čtení · ' + kind,
                'profile_path': profile['path'], 'profile_sha256': profile['sha256']})
            if not run['ok']:
                raise RuntimeError(str(run['error']))
            cases.append({'kind': kind, 'source': str(path), 'source_sha256': sha(path),
                'run_id': run['data']['project']['run_id'], 'work': str(registry / run['data']['artifacts']['workspace']['path']),
                'profile_sha256': profile['sha256']})
    finally:
        app.close()
    commitment = hashlib.sha256(canonical(samples)).hexdigest()
    disclosure = {'schema_version': 1, 'registry': str(registry), 'cases': cases,
        'synthetic_oracle': {'sha256': commitment, 'canonicalization': 'UTF-8 JSON ensure_ascii=false,sort_keys=true,separators=(comma,colon)',
            'state': 'held_only_in_owned_host_process_until_validated_publication', 'sample_boxes': [{k: s[k] for k in ('id', 'page', 'bbox')} for s in samples]},
        'synthetic_source_images': [{'path': str(p), 'sha256': sha(p)} for p in images],
        'difficult_provenance': {'original_source': str(actual_source), 'original_sha256': real_hash, 'page': 2,
            'render_dpi': 300, 'original_bbox': region, 'crop': str(original_crop), 'crop_sha256': sha(original_crop)},
        'model_destination': 'Pinned local Codex app-server; managed ChatGPT account; gpt-6.1-sol/high; no API key.',
        'generator_sha256': sha(Path(__file__)), 'font': {'path': font_path, 'sha256': sha(Path(font_path))},
        'publication_control': str(output / 'publication-control.json')}
    save(output / 'source-disclosure.json', disclosure)
    print(json.dumps({'disclosure': str(output / 'source-disclosure.json'), 'sha256': sha(output / 'source-disclosure.json'),
        'oracle_commitment': commitment, 'state': 'waiting_for_explicit_validated_publication_control'}), flush=True)
    synthetic = cases[0]
    control = output / 'publication-control.json'
    while not control.exists():
        time.sleep(.5)
    control_value = json.loads(control.read_text())
    if control_value['run_id'] != synthetic['run_id'] or not control_value['reading_complete']:
        raise RuntimeError('Host-only publication control does not identify a validated synthetic reading.')
    work = Path(synthetic['work'])
    publication = json.loads((work / 'reading-publication.json').read_text())
    if publication['review_sha256'] != sha(work / 'review.json') or publication['review_sha256'] != control_value['review_sha256']:
        raise RuntimeError('The controlled publication does not match the native published review.')
    proposal = registry / control_value['proposal_path']
    if publication['proposal_sha256'] != sha(proposal) or sha(proposal) != control_value['proposal_sha256']:
        raise RuntimeError('The controlled publication does not match the validated model-authored proposal.')
    if hashlib.sha256(canonical(samples)).hexdigest() != commitment:
        raise RuntimeError('The original independent oracle commitment changed.')
    review = json.loads((work / 'review.json').read_text())
    expected = normalized(' '.join(sample['expected'] for sample in samples))
    observed = normalized(' '.join(line['text'] for line in review['lines']))
    # Reveal only after native publication and its original pre-AI commitment check.
    save(output / 'independent-source-samples.json', samples)
    result = {'oracle_commitment': commitment, 'commitment_verified': True,
        'validated_publication_control': control_value, 'synthetic_oracle_exact_match': expected == observed,
        'expected': expected, 'observed': observed,
        'printed_mistake_preserved': 'tiskovou chibu.' in observed,
        'publisher_error_recorded': any(record.get('printed') in ('chibu', 'chibu.', 'tiskovou chibu.') or
            'chibu' in record.get('printed', '') for record in review['publisher_errors'])}
    save(output / 'independent-oracle-result.json', result)
    print(json.dumps({k: result[k] for k in ['commitment_verified', 'synthetic_oracle_exact_match', 'printed_mistake_preserved', 'publisher_error_recorded']}), flush=True)
    return 0 if all(result[k] for k in ['synthetic_oracle_exact_match', 'printed_mistake_preserved', 'publisher_error_recorded']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
