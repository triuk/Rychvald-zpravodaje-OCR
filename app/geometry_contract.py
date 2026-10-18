"""Source-independent samples, followed by diagnostic image decisions."""


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def array(items):
    return {'type': 'array', 'items': items}


STRING = {'type': 'string'}
IMAGE = obj({'path': STRING, 'sha256': STRING})
SAMPLE = obj({'id': STRING, 'page': {'type': 'integer'}, 'bbox': array({'type': 'number'}),
              'expected': STRING, 'expected_origin': STRING})
UNIT = obj({'id': STRING, 'article': STRING, 'page': {'type': 'integer'},
            'tag': STRING, 'line_ids': array(STRING)})
DECISION = obj({'id': STRING, 'status': {'type': 'string', 'enum': ['examined_approximate', 'open']},
    'reason': STRING, 'evidence': array(STRING)})
SOURCE_SCHEMA = obj({'source_sha256': STRING, 'samples': array(SAMPLE), 'basis': STRING})
GEOMETRY_SCHEMA = obj({'preparation_sha256': STRING, 'images_examined': array(IMAGE),
    'logical_units': array(UNIT), 'lines': array(DECISION), 'samples': array(DECISION),
    'geometry_status': {'type': 'string', 'enum': ['approximation_requires_character_review']},
    'remaining_risks': array(STRING)})
SOURCE_PROMPT = '''Choose independent pre-export geometry test expectations directly from the attached ORIGINAL source rasters.
This is targeted source-region measurement, not another complete OCR transcription. No OCR candidates, current review,
generated glyph cells or PDF/output extraction are available or allowed. For each page select clear source regions with
exact text and pixel boxes [x0,y0,x1,y1] relative to that original raster. Cover actual diacritics, punctuation, repeated
digits, small symbols, partial words and adjacent text where present. Preserve printed errors. Never guess a blurred or
clipped character: choose safely readable regions and explain excluded uncertainty in basis. Include at least one sample
per page; IDs ASCII letters/digits/_/-. Expected_origin states this original image examination. Call ctx_stats once.
SOURCE_GEOMETRY_PACKET\n'''
GEOMETRY_PROMPT = '''Examine ALL attached original rasters, native source/red-character overlays and green sample rectangles.
Check logical article/paragraph order and continuation against original source. The supplied logical_units must be returned
unchanged; if order needs correction record the exact issue as an open line decision, never silently rewrite a transcript.
Return an individual decision for EVERY required_lines ID and EVERY source sample ID. Evidence lists exact attached image
paths. Every unsupported cell/anomaly line MUST stay status open until corrected through a separately validated patch.
Check letters/diacritics, dots, dashes, repeated digits, whitespace and bleed into neighbors. A source sample's rectangle
must include its intended characters/diacritics and exclude neighbors; mark open with the specific offending boundary if not.
Do not adapt expected text/boxes to cells or later output. A generated box does not prove glyph identity. All unchanged
geometry remains approximation_requires_character_review; examined_approximate means inspected only, never verified.
Keep blurred/clipped source uncertainty and remaining risks explicit. No PDF exists yet, export validation and acceptance
remain separate. Call ctx_stats once. Return only schema JSON. GEOMETRY_PACKET\n'''
