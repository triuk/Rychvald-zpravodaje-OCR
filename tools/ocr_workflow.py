"""Parameterized OCR workflow using freshly reviewed source data.

OCR candidates still require visual proofreading and fresh paragraph/geometry
decisions. Instructions: docs/ocr-workflow.md.
"""
from pathlib import Path
import argparse,collections,concurrent.futures,copy,difflib,hashlib,json,re,subprocess,sys
from importlib.metadata import version
from ocr_quality import (load, dump, sha, bindings, check_bindings, validate_review,
                         update_line, article_text, technical_failures, snapshot,
                         doctor, validate_run, bbox, unique)

FONT_PATH='/usr/share/fonts/noto/NotoSerif-Regular.ttf'
FONT=None
SEGMENTATION_EVENTS=[]
def run(command):
 p=subprocess.run(command,capture_output=True,text=True)
 if p.returncode:raise RuntimeError(f'{command!r}: {p.stderr}')
 return p
def recognize_cached(command,prefix,image,outputs,version):
 cache=Path(str(prefix)+'-cache.json')
 identity={'command':command,'image_sha256':sha(image),'tesseract':version}
 if cache.exists():
  stored=load(cache)
  if stored.get('identity')==identity and all(Path(str(prefix)+suffix).is_file() and sha(str(prefix)+suffix)==stored.get('outputs',{}).get(suffix) for suffix in outputs):return True
 result=run(command);Path(str(prefix)+'.log').write_text(result.stderr,encoding='utf-8')
 dump(cache,{'identity':identity,'outputs':{suffix:sha(str(prefix)+suffix) for suffix in outputs}})
 return False
def width(s):return max(1,FONT.getlength(s))
def union(bs):return [min(b[0] for b in bs),min(b[1] for b in bs),max(b[2] for b in bs),max(b[3] for b in bs)]
def parse_hocr(path,page,prefix,offset=(0,0)):
 def box(title,key='bbox'):
  m=re.search(r'(?:^|; )'+key+r' (\d+) (\d+) (\d+) (\d+)',title)
  if not m:raise ValueError(f'Missing {key}: {title}')
  a,b,c,d=map(int,m.groups());return [a+offset[0],b+offset[1],c+offset[0],d+offset[1]]
 tree=etree.parse(str(path));lines=[]
 for i,line in enumerate(tree.xpath('//*[contains(concat(" ",@class," ")," ocr_line ") or contains(concat(" ",@class," ")," ocr_header ")]'),1):
  words=[]
  for w in line.xpath('.//*[contains(concat(" ",@class," ")," ocrx_word ")]'):
   chars=[{'text':c.text or '', 'ocr_bbox':box(c.get('title'),'x_bboxes')} for c in w.xpath('.//*[contains(concat(" ",@class," ")," ocrx_cinfo ")]')]
   words.append({'text':''.join(c['text'] for c in chars),'ocr_bbox':box(w.get('title')),'chars':chars})
  lines.append({'id':f'{prefix}-{i:02}','page':page,'ocr_bbox':box(line.get('title')),'words':words,'text':' '.join(w['text'] for w in words)})
 return lines
def prepare(a):
 source=Path(a.source).resolve();w=Path(a.work).resolve()
 if (w/'input-manifest.json').exists():raise ValueError('Use a new work directory; preserve the previous run')
 if a.dpi<=0:raise ValueError('DPI must be positive')
 d=fitz.open(source)
 if d.needs_pass:raise ValueError('PDF requires a password; no password handling was implemented')
 if not len(d):raise ValueError('Empty PDF')
 for name in ['raster','ocr','crops','checks','construction','output/pdf','output/text']:(w/name).mkdir(parents=True,exist_ok=True)
 records=[]
 for n,p in enumerate(d,1):
  target=w/'raster'/f'page-{n}.png';p.get_pixmap(dpi=a.dpi).save(target)
  im=Image.open(target);size=im.size;im.thumbnail((1250,1800));im.save(w/'raster'/f'overview-{n}.png')
  records.append({'page':n,'rect':list(p.rect),'mediabox':list(p.mediabox),'cropbox':list(p.cropbox),'rotation':p.rotation,'raster_size':size,'raster_sha256':sha(target),'existing_text_characters':len(p.get_text().strip())})
 manifest={'source':str(source),'source_sha256':sha(source),'pages':records,'dpi':a.dpi,'transform':'none','content_inputs':'source raster only',
  'versions':{'Python':sys.version,'PyMuPDF':fitz.VersionBind,'Tesseract':run(['tesseract','--version']).stdout.splitlines()[0],**{name:version(name) for name in ['Pillow','numpy','lxml','reportlab','fonttools']}},'ocr':{'language':a.language,'psm':[3,11],'hocr_char_boxes':1}}
 dump(w/'input-manifest.json',manifest)
 def recognize(job):
  n,psm=job;prefix=w/'ocr'/f'page-{n}-psm{psm}'
  cmd=['tesseract',str(w/'raster'/f'page-{n}.png'),str(prefix),'-l',a.language,'--psm',str(psm),'-c','hocr_char_boxes=1','hocr','tsv','txt','makebox']
  result=run(cmd);prefix.with_suffix('.log').write_text(result.stderr)
  return {'page':n,'psm':psm,'command':cmd}
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:commands=list(pool.map(recognize,[(n,s) for n in range(1,len(d)+1) for s in [3,11]]))
 dump(w/'ocr-commands.json',commands)
 lines=[]
 for n in range(1,len(d)+1):lines.extend(parse_hocr(w/'ocr'/f'page-{n}-psm3.hocr',n,f'p{n}-full'))
 dump(w/'fresh-lines.json',lines)
 print(f'Prepared {len(d)} pages; {len(commands)} OCR runs; existing text counts are in the manifest')
def regions(a):
 w=Path(a.work);m=load(w/'input-manifest.json');regions=load(a.regions)
 unique(regions,'region')
 tesseract_version=run(['tesseract','--version']).stdout.splitlines()[0]
 ids=[r['id'] for r in regions]
 if len(ids)!=len(set(ids)):raise ValueError('Duplicate region IDs')
 for r in regions:
  if not re.fullmatch(r'[A-Za-z0-9_-]+',r['id']):raise ValueError('Use simple region IDs')
  if not 1<=r['page']<=len(m['pages']):raise ValueError('Invalid page')
  bbox(r['bbox'],r['page'],m)
 def recognize(original):
  r=copy.deepcopy(original);crop=w/'crops'/(r['id']+'.png');prefix=w/'ocr'/r['id']
  Image.open(w/'raster'/f"page-{r['page']}.png").crop(r['bbox']).save(crop)
  cmd=['tesseract',str(crop),str(prefix),'-l',m['ocr']['language'],'--psm',str(r['psm']),'-c','hocr_char_boxes=1','hocr','tsv','txt']
  reused=recognize_cached(cmd,prefix,crop,['.hocr','.tsv','.txt'],tesseract_version);r['command']=cmd
  r['lines']=parse_hocr(prefix.with_suffix('.hocr'),r['page'],r['id'],r['bbox'][:2])
  for line in r['lines']:line['region']=r['id']
  return r,reused
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:recognized=list(pool.map(recognize,regions))
 results=[r for r,reused in recognized]
 dump(w/'regions.json',regions);dump(w/'local-candidates.json',results)
 print(f'OCR candidates for {len(results)} regions; {sum(reused for r,reused in recognized)} cached')
def targeted(a):
 w=Path(a.work);m=load(w/'input-manifest.json');results=[];cached=0
 targets=load(a.targets);unique(targets,'target');tesseract_version=run(['tesseract','--version']).stdout.splitlines()[0]
 for t in targets:
  if not re.fullmatch(r'[A-Za-z0-9_-]+',t['id']):raise ValueError('Use simple target IDs')
  bbox(t['bbox'],t['page'],m)
  im=Image.open(w/'raster'/f"page-{t['page']}.png").crop(t['bbox']).convert('L')
  bg=np.asarray(im.filter(ImageFilter.GaussianBlur(12)),dtype=float)
  normalized=Image.fromarray(np.uint8(np.clip(np.asarray(im,dtype=float)/np.maximum(bg,1)*235,0,255)))
  for name,image in [('raw',im),('normalized',normalized)]:
   path=w/'crops'/f"{t['id']}-{name}.png";image.save(path);prefix=w/'ocr'/f"{t['id']}-{name}"
   cmd=['tesseract',str(path),str(prefix),'-l',m['ocr']['language'],'--psm',str(t['psm']),'txt','tsv']
   reused=recognize_cached(cmd,prefix,path,['.txt','.tsv'],tesseract_version)
   cached+=reused
   results.append({**t,'variant':name,'command':cmd,'candidate':prefix.with_suffix('.txt').read_text(),'returncode':0})
 previous=load(w/'targeted-candidates.json') if (w/'targeted-candidates.json').exists() else []
 replaced={t['id'] for t in targets}
 dump(w/'targeted-candidates.json',[r for r in previous if r['id'] not in replaced]+results);print(f'{len(results)} targeted raw/supporting OCR candidates; {cached} cached')
def draft(a):
 w=Path(a.work);target=Path(a.review)
 if target.exists():raise ValueError('Preserve the existing review; choose another filename')
 candidates=load(w/'local-candidates.json');lines=[];units=[]
 for region in candidates:
  for line in region['lines']:
   lines.append({'id':line['id'],'candidate_id':line['id'],'page':line['page'],'text':line['text'],'selection_region':line['ocr_bbox'],'source_crop':f"crops/{region['id']}.png",'text_status':'candidate','decision_basis':'not yet visually reviewed'})
   units.append({'id':line['id'],'page':line['page'],'article':region['id'],'tag':'P','line_ids':[line['id']]})
 dump(target,{'source_sha256':load(w/'input-manifest.json')['source_sha256'],'lines':lines,'units':units,'dropped_candidates':[],'unresolved':[],'publisher_errors':[],'risk_register':[]})
 print('Created a candidate draft. Paragraphs and visual confirmation still require fresh review.')
def splits(text,b,mask,line_id=None):
 # Raster-valley and width-aware refit algorithm.
 x0,y0,x1,y1=map(int,b);x1=max(x0+len(text),x1)
 patch=mask[max(0,y0):max(1,y1),max(0,x0):x1];proj=patch.sum(axis=0).astype(float)
 weights=np.array([width(c) for c in text]);expected=np.cumsum(weights)/sum(weights)*(x1-x0);cuts=[x0]
 for i,target in enumerate(expected[:-1]):
  center=x0+target;radius=max(2,min(9,(x1-x0)/max(1,len(text))*.38))
  lo=max(cuts[-1]+1,int(center-radius));hi=min(x1-(len(text)-i-1),int(center+radius)+1)
  if hi<=lo:cut=max(cuts[-1]+1,min(x1-(len(text)-i-1),round(center)))
  else:
   choices=np.arange(lo,hi);indexes=np.clip(choices-x0,0,max(0,len(proj)-1))
   costs=(proj[indexes] if len(proj) else np.zeros(len(choices)))+np.abs(choices-center)*.35
   cut=int(choices[np.argmin(costs)])
  cuts.append(cut)
 cuts.append(x1);relative=[v-x0 for v in cuts]
 if len(proj) and proj.sum() and any(proj[a:z].sum()==0 for a,z in zip(relative,relative[1:])):
  length=x1-x0;prefix=np.r_[0,np.cumsum(proj)];target_widths=weights/sum(weights)*length;states={0:(0.0,[])}
  for i,target in enumerate(target_widths):
   next_states={};wanted=expected[i]
   endpoints=[length] if i==len(text)-1 else range(max(i+1,int(wanted-max(6,target*1.3))),min(length-(len(text)-i-1),int(wanted+max(6,target*1.3)))+1)
   for end in endpoints:
    choices=[]
    for start,(cost,path) in states.items():
     if start>=end:continue
     ink=prefix[min(end,len(proj))]-prefix[min(start,len(proj))];penalty=35 if ink==0 else 0
     boundary=proj[min(end,len(proj)-1)]/max(1,y1-y0) if end<length else 0
     score=cost+((end-start-target)/max(2,target))**2*5+boundary*3+penalty;choices.append((score,path+[end]))
    if choices:next_states[end]=min(choices,key=lambda v:v[0])
   states=next_states
  if length in states:
   old=cuts[:];cuts=[x0]+[x0+v for v in states[length][1]]
   SEGMENTATION_EVENTS.append({'line':line_id,'text':text,'region':list(b),'original_cuts':old,'refitted_cuts':cuts,'status':'approximation_not_a_glyph_identity_proof'})
 return [[cuts[i],y0,cuts[i+1],y1] for i in range(len(text))]
def token_boxes(text,old,b,mask):
 tokens=text.split();result=[None]*len(tokens);source=[w['text'] for w in old]
 for tag,i,j,a,z in difflib.SequenceMatcher(None,source,tokens,autojunk=False).get_opcodes():
  if tag=='equal':
   for oi,ni in zip(range(i,j),range(a,z)):result[ni]=(old[oi]['ocr_bbox'],'ocr_token')
  elif a<z:
   if i<j:
    bounds=union([v['ocr_bbox'] for v in old[i:j]])
    if i==0 and source and len(''.join(tokens[a:z]))>len(''.join(source[i:j])):bounds[0]=min(bounds[0],b[0]+2)
    if j==len(old) and len(''.join(tokens[a:z]))>len(''.join(source[i:j]))+1:bounds[2]=max(bounds[2],b[2])
   else:
    left=old[i-1]['ocr_bbox'][2]+2 if i else b[0];right=old[i]['ocr_bbox'][0]-2 if i<len(old) else b[2]
    bounds=[left,b[1],max(left+z-a,right),b[3]]
   lengths=[width(t) for t in tokens[a:z]];total=sum(lengths);x=bounds[0]
   for ni,l in zip(range(a,z),lengths):
    end=x+(bounds[2]-bounds[0])*l/total;result[ni]=([x,bounds[1],end,bounds[3]],'corrected_token_extent_approximation');x=end
 if not old or source!=tokens:
  x0,y0,x1,y1=map(int,b);proj=mask[y0:y1,x0:x1].sum(axis=0);ink=np.where(proj>0)[0];runs=[]
  if len(ink):
   begin=last=int(ink[0]);gap=max(4,round((y1-y0)*.16))
   for x in ink[1:]:
    if x-last>gap:runs.append([begin,last+1]);begin=int(x)
    last=int(x)
   runs.append([begin,last+1])
  if len(runs)==len(tokens):result=[([x0+a,y0,x0+z,y1],'raster_word_gaps') for a,z in runs]
 return tokens,result
def segment(a):
 global FONT
 FONT=ImageFont.truetype(a.font,100);w=Path(a.work);m=load(w/'input-manifest.json');review=load(a.review)
 validate_review(w,review);SEGMENTATION_EVENTS.clear()
 if review['source_sha256']!=m['source_sha256']:raise ValueError('Review belongs to another source')
 candidates={l['id']:l for r in load(w/'local-candidates.json') for l in r['lines']}
 lines={};masks={};geometry=[];unsupported=[];reconstructions=[];references=[]
 for info in m['pages']:
  n=info['page'];im=Image.open(w/'raster'/f'page-{n}.png').convert('L')
  masks[n]=np.asarray(im,dtype=float)<np.asarray(im.filter(ImageFilter.GaussianBlur(12)),dtype=float)*.80
 for entry in review['lines']:
  line=copy.deepcopy(entry);key=line['id'];page=line['page'];mask=masks[page]
  if key in lines:raise ValueError('Duplicate reviewed line')
  if line['text_status'] not in ['visually_confirmed','partially_unresolved']:raise ValueError(f'{key}: still a candidate')
  raw=candidates.get(line.get('candidate_id',key));b=line['selection_region'];cells=[]
  if raw:references.append(raw['id'])
  fields=line.get('fields',[{'text':line['text'],'bbox':b}])
  for fi,field in enumerate(fields):
   fb=field['bbox'];words=[x for x in (raw['words'] if raw else []) if fb[0]<=sum(x['ocr_bbox'][::2])/2<fb[2]]
   tokens,boxes=token_boxes(field['text'],words,fb,mask)
   normal=[x['ocr_bbox'] for x in words if len(x['text'])>=2 and x['ocr_bbox'][3]-x['ocr_bbox'][1]>12]
   nh=float(np.median([v[3]-v[1] for v in normal])) if normal else 0
   for ti,(token,(bounds,origin)) in enumerate(zip(tokens,boxes)):
    explicit=field.get('token_boxes',{}).get(str(ti));tb=list(explicit or bounds)
    if explicit:origin='fresh_visual_token_override'
    tb=[max(fb[0],tb[0]),max(fb[1],tb[1]),min(fb[2],tb[2]),min(fb[3],tb[3])]
    if tb[2]<=tb[0] or tb[3]<=tb[1]:raise ValueError(f'{key}: invalid token extent')
    if not explicit and nh and tb[3]-tb[1]>nh*1.45:
     tb[1]=max(fb[1],float(np.median([v[1] for v in normal]))-3);tb[3]=min(fb[3],float(np.median([v[3] for v in normal]))+2)
    if origin not in ['ocr_token','fresh_visual_token_override']:
     x0,y0,x1,y1=map(int,tb);supported=np.where(mask[y0:y1,x0:x1].sum(axis=0)>=2)[0]
     if len(supported):tb[0]=x0+int(supported[0]);tb[2]=x0+int(supported[-1])+1
    if token=='-' and not explicit:
     x0,y0,x1,y1=map(int,tb);yy,xx=np.where(mask[y0:y1,x0:x1])
     if len(xx) and xx.max()-xx.min()+1>1.8*(yy.max()-yy.min()+1):tb=[x0+int(xx.min()),y0+int(yy.min()),x0+int(xx.max())+1,y0+int(yy.max())+1]
    pieces=[x for x in re.split(r'(\[NEČITELNÉ\])',token) if x];surrogate=field.get('placeholder_surrogates',{}).get(str(ti),'?')
    pw=[width(surrogate if x=='[NEČITELNÉ]' else x) for x in pieces];px=tb[0];tc=[]
    for pi,(piece,pwidth) in enumerate(zip(pieces,pw)):
     end=px+(tb[2]-tb[0])*pwidth/sum(pw);pb=field.get('piece_boxes',{}).get(str(ti),{}).get(str(pi),[px,tb[1],end,tb[3]])
     placeholder=piece=='[NEČITELNÉ]'
     boxes_chars=[[pb[0]+(pb[2]-pb[0])*j/len(piece),pb[1],pb[0]+(pb[2]-pb[0])*(j+1)/len(piece),pb[3]] for j in range(len(piece))] if placeholder else splits(piece,pb,mask,key)
     for ci,(char,cb) in enumerate(zip(piece,boxes_chars)):
      override=field.get('character_boxes',{}).get(f'{ti}:{pi}:{ci}')
      if override:cb=override
      x0,y0,x1,y1=map(int,cb);yy,xx=np.where(mask[y0:y1,x0:x1])
      hull=[x0+int(xx.min()),y0+int(yy.min()),x0+int(xx.max())+1,y0+int(yy.max())+1] if len(xx) and not placeholder else None
      cell={'text':char,'selection_bbox':cb,'candidate_ink_bbox':hull,'ink_assignment_status':'not_verified','geometry_origin':'placeholder_region' if placeholder else 'fresh_visual_character_override' if override else 'token_raster_valley_approximation','geometry_status':'region_only' if placeholder else 'requires_character_review','synthetic_space':False}
      if hull is None and not placeholder:unsupported.append({'line':key,'text':char,'selection_bbox':cb,'status':'open_geometry_uncertainty'})
      tc.append(cell)
     px=end
    if cells:
     prev=cells[-1]['selection_bbox'];nxt=tc[0]['selection_bbox'];sb=[prev[2],prev[1],prev[2]+max(1,min(7,nxt[0]-prev[2])),prev[3]]
     cells.append({'text':' ','selection_bbox':sb,'synthetic_space':True,'geometry_origin':'logical_word_separator','geometry_status':'intentional_space'})
    cells.extend(tc);geometry.append({'line':key,'field':fi,'token':ti,'text':token,'selection_bbox':tb,'origin':origin,'status':'approximation_requires_character_review'})
  if ''.join(c['text'] for c in cells)!=' '.join(line['text'].split()):raise ValueError(f'{key}: fields/text mismatch')
  line['cells']=cells;line['geometry_status']='approximation_requires_character_review';lines[key]=line
  if raw and line['text'].replace('\t',' ')!=raw['text']:
   reconstructions.append({'line':key,'page':page,'candidate':raw['text'],'adopted':line['text'],'source_crop':line.get('source_crop'),'basis':line.get('decision_basis','not recorded'),'status':line['text_status']})
 dropped=review.get('dropped_candidates',[])
 if set(candidates)-set(references)!={x['id'] for x in dropped}:raise ValueError('Account for every local OCR candidate as a reviewed line or an explicitly dropped candidate')
 pages=[{'page':x['page'],'units':[]} for x in m['pages']];used=[]
 for spec in review['units']:
  unit={k:v for k,v in spec.items() if k!='line_ids'};unit['lines']=[copy.deepcopy(lines[k]) for k in spec['line_ids']];used.extend(spec['line_ids'])
  if not unit['lines'] or any(l['page']!=unit['page'] for l in unit['lines']):raise ValueError('Units are page-local; split cross-page units')
  for line in unit['lines'][:-1]:
   if line.get('join_after') not in ['space','typesetting_hyphen','literal_hyphen','none']:raise ValueError('Record each line join explicitly')
  pages[unit['page']-1]['units'].append(unit)
 if len(used)!=len(set(used)) or set(used)!=set(lines):raise ValueError('Each reviewed line must occur in exactly one logical unit')
 unresolved=review.get('unresolved',[])
 if sum(l['text'].count('[NEČITELNÉ]') for l in lines.values())!=len(unresolved):raise ValueError('Unresolved marker/register mismatch')
 dump(w/'pages.json',pages);dump(w/'reviewed-lines.json',list(lines.values()));dump(w/'geometry.json',geometry)
 dump(w/'segmentation-events.json',SEGMENTATION_EVENTS);dump(w/'checks/unsupported-cells.json',unsupported)
 dump(w/'unresolved.json',unresolved);dump(w/'publisher-errors.json',review.get('publisher_errors',[]))
 dump(w/'reconstructions.json',reconstructions);dump(w/'risk-register.json',review.get('risk_register',[]))
 anomalies=[]
 for key,line in lines.items():
  c=line['cells'];b=line['selection_region']
  tiny=[i for i,x in enumerate(c) if not x['synthetic_space'] and x['geometry_origin']!='placeholder_region' and x['selection_bbox'][2]-x['selection_bbox'][0]<1]
  overlaps=[i for i,(x,y) in enumerate(zip(c,c[1:])) if not x['synthetic_space'] and not y['synthetic_space'] and x['selection_bbox'][2]>y['selection_bbox'][0]+1]
  outside=[i for i,x in enumerate(c) if x['selection_bbox'][0]<b[0]-2 or x['selection_bbox'][2]>b[2]+2]
  if tiny or overlaps or outside:anomalies.append({'line':key,'tiny':tiny,'overlaps':overlaps,'outside':outside})
 dump(w/'checks/geometry-anomalies.json',anomalies)
 dump(w/'segmented-review.json',review)
 inputs=bindings(review=a.review,segmented_review=w/'segmented-review.json',candidates=w/'local-candidates.json',manifest=w/'input-manifest.json',font=a.font,
                 **{f'raster_{p["page"]}':w/'raster'/f'page-{p["page"]}.png' for p in m['pages']},
                 **{f'proof_{i}':w/path for i,path in enumerate(sorted({r['source_crop'] for r in review['lines']} | {r['source_crop'] for name in ['unresolved','risk_register','publisher_errors'] for r in review.get(name,[]) if r.get('source_crop')}))})
 dump(w/'segment-manifest.json',{'inputs':inputs,'pages_sha256':sha(w/'pages.json'),'tool_sha256':sha(__file__)})
 print(f'{len(pages)} pages, {len(lines)} reviewed lines; geometry remains approximate')
def export(a):
 w=Path(a.work);m=load(w/'input-manifest.json');source=Path(a.source).resolve()
 if sha(source)!=m['source_sha256']:raise ValueError('Wrong source hash')
 if any(p['existing_text_characters'] for p in m['pages']) and not a.allow_existing_text:raise ValueError('Source already contains text. Resolve the text-layer handling explicitly; --allow-existing-text keeps it and can cause duplicate extraction')
 pages=load(a.pages);out=Path(a.pdf);txt=Path(a.txt)
 segmentation=load(w/'segment-manifest.json');check_bindings(segmentation['inputs'])
 if sha(a.pages)!=segmentation['pages_sha256'] or sha(__file__)!=segmentation['tool_sha256']:raise ValueError('Re-run segment after changing pages or segmentation code')
 if out.resolve()==source or txt.resolve()==source or out.resolve()==txt.resolve():raise ValueError('Keep source and output paths separate')
 if (w/'output-manifest.json').exists():
  previous=load(w/'output-manifest.json')
  if any(path.exists() and str(path.resolve())!=previous[name] for name,path in [('pdf',out),('txt',txt)]):raise ValueError('Refuse to replace an unrelated output')
  print(f'Archived previous export: {snapshot(w)}')
 elif out.exists() or txt.exists():raise ValueError('Refuse to overwrite an existing output without its manifest')
 out.parent.mkdir(parents=True,exist_ok=True);txt.parent.mkdir(parents=True,exist_ok=True)
 # For a rotated source, author the unchanged
 # F mechanism in unrotated page coordinates, then restore source rotations.
 rotations=[p['rotation'] for p in m['pages']]
 if any(rotations):
  authoring=fitz.open(source);converted=copy.deepcopy(pages);factor=72/m['dpi']
  for sp,data in zip(authoring,converted):
   matrix=sp.derotation_matrix
   for unit in data['units']:
    for line in unit['lines']:
     for cell in line['cells']:
      box=fitz.Rect([v*factor for v in cell['selection_bbox']])*matrix
      cell['selection_bbox']=[v/factor for v in box]
   sp.set_rotation(0)
  temporary=w/'construction/unrotated-source.pdf';authoring.save(temporary);authoring.close()
  layer_result=w/'construction/unrotated-result.pdf'
  create_pdf(converted,temporary,layer_result,work_dir=w/'construction',raster_dpi=m['dpi'])
  final=fitz.open(layer_result)
  for sp,rotation in zip(final,rotations):sp.set_rotation(rotation)
  final.save(out,garbage=0,deflate=False);final.close()
  for actual,changed in zip(pages,converted):
   for u,v in zip(actual['units'],changed['units']):u['pdf_text']=v['pdf_text']
 else:create_pdf(pages,source,out,work_dir=w/'construction',raster_dpi=m['dpi'])
 dump(w/'exported-pages.json',pages)
 txt.write_text(article_text(pages),encoding='utf-8')
 dump(w/'exported-review.json',load(w/'segmented-review.json'))
 dump(w/'export-inputs.json',{'segmentation':segmentation,'review':load(w/'segmented-review.json'),
                             'samples':load(w/'samples.json') if (w/'samples.json').exists() else None})
 inputs=bindings(**{name:record['path'] for name,record in segmentation['inputs'].items()},pages=a.pages,
                 exported_pages=w/'exported-pages.json',exported_review=w/'exported-review.json',export_inputs=w/'export-inputs.json')
 dump(w/'output-manifest.json',{'source':str(source),'source_sha256':sha(source),'pdf':str(out.resolve()),'pdf_sha256':sha(out),'txt':str(txt.resolve()),'txt_sha256':sha(txt),'inputs':inputs,'status':'exported','ui_clipboard_tested':False,'tool_sha256':sha(__file__),'generator_sha256':sha(Path(__file__).with_name('ocr_f_layer.py'))})
 print(f'Exported {len(pages)} pages; PDF {sha(out)}')
def check(a):
 w=Path(a.work);c=w/'checks';c.mkdir(parents=True,exist_ok=True);pages=load(a.pages);source=fitz.open(a.source);out=fitz.open(a.pdf)
 if len(source)!=len(out) or len(out)!=len(pages):raise ValueError('Page count mismatch')
 strip=lambda s:re.sub(r'\s','',s)
 result={'source_sha256':sha(a.source),'output_sha256':sha(a.pdf),'versions':{'PyMuPDF':fitz.VersionBind,'Poppler':run(['pdftotext','-v']).stderr.splitlines()[0]},'pages':[],'ui_clipboard':'not_tested'}
 result['source_identity_preserved']=result['source_sha256']==load(w/'input-manifest.json')['source_sha256']
 result['inputs']=bindings(source=a.source,pdf=a.pdf,txt=a.txt,pages=a.pages)
 q=subprocess.run(['qpdf','--check',a.pdf],capture_output=True,text=True);(c/'qpdf.txt').write_text(q.stdout+q.stderr);result['qpdf_returncode']=q.returncode
 reviewer=original=None
 if a.reviewer_root:
  sys.path.insert(0,str(Path(a.reviewer_root).resolve()));from app.pdf_document import PdfDocument
  reviewer=PdfDocument(a.pdf);original=PdfDocument(a.source)
 try:
  for n,(sp,op,data) in enumerate(zip(source,out,pages),1):
   expected='\n\n'.join(u['pdf_text'] for u in data['units'])+'\n';mu=op.get_text('text',sort=False)
   pop=run(['pdftotext','-f',str(n),'-l',str(n),'-raw',a.pdf,'-']).stdout.rstrip('\f')
   for name,value in [('expected',expected),('mupdf',mu),('poppler',pop)]:(c/f'{name}-page-{n}.txt').write_text(value,encoding='utf-8')
   im=sp.get_pixmap(dpi=150);final=op.get_pixmap(dpi=150);final.save(c/f'final-page-{n}.png')
   row={'page':n,'geometry_preserved':sp.rect==op.rect and sp.mediabox==op.mediabox and sp.cropbox==op.cropbox and sp.rotation==op.rotation,
    'source_content_streams_preserved':all(source.xref_stream(x)==out.xref_stream(x) for x in sp.get_contents()),
    'decoded_images_identical':[hashlib.sha256(source.xref_stream(x[0])).hexdigest() for x in sp.get_images()]==[hashlib.sha256(out.xref_stream(x[0])).hexdigest() for x in op.get_images()],
    'mupdf_render_identical':im.samples==final.samples,'mupdf_characters_equal':strip(expected)==strip(mu),'poppler_characters_equal':strip(expected)==strip(pop),
    'mupdf_literal_equal':expected==mu,'poppler_literal_equal':expected==pop,
    'mupdf_literal_diff':list(difflib.ndiff(expected.splitlines(keepends=True),mu.splitlines(keepends=True))),
    'poppler_literal_diff':list(difflib.ndiff(expected.splitlines(keepends=True),pop.splitlines(keepends=True)))}
   stream=b'\n'.join(out.xref_stream(x[0]) for x in op.get_xobjects() if x[1]=='fullpage')
   row.update({'BT':len(re.findall(rb'\bBT\b',stream)),'units':len(data['units']),'tags':stream.count(b' BDC'),'invisible':b'3 Tr' in stream,'no_ActualText':b'ActualText' not in stream,'no_Tz':not bool(re.search(rb'\bTz\b',stream))})
   if reviewer:
    rp=reviewer.render_page(n-1,1250);rs=original.render_page(n-1,1250)
    row['reviewer_render_identical']=rp.image_bytes==rs.image_bytes;row['reviewer_characters_equal']=strip(expected)==strip(rp.ocr['pdf_order'])
   result['pages'].append(row)
 finally:
  if reviewer:reviewer.close();original.close()
 for name,path in [('poppler-source',a.source),('poppler-final',a.pdf)]:run(['pdftoppm','-r','150','-png',path,str(c/name)])
 for n,row in enumerate(result['pages'],1):
  first=np.asarray(Image.open(c/f'poppler-source-{n}.png'));last=np.asarray(Image.open(c/f'poppler-final-{n}.png'));row['poppler_render_identical']=first.shape==last.shape and np.array_equal(first,last)
 result['txt_characters_equal_common_transcript']=strip(Path(a.txt).read_text())==strip(''.join(u['pdf_text'] for p in pages for u in p['units']))
 result['txt_literal_equal_common_transcript']=Path(a.txt).read_bytes()==article_text(pages).encode('utf-8')
 fonts={f[0]:f for p in out for f in p.get_fonts(full=True)}
 result['fonts']=[{'xref':x,'name':f[3],'embedded':bool(out.extract_font(x)[3])} for x,f in fonts.items()]
 result['construction_events']=dict(collections.Counter(e['type'] for e in load(w/'construction/construction-events.json')))
 dump(c/'technical.json',result)
 keys=['geometry_preserved','source_content_streams_preserved','decoded_images_identical','mupdf_render_identical','poppler_render_identical','mupdf_characters_equal','poppler_characters_equal']
 print(json.dumps({'pages':len(out),'qpdf_returncode':q.returncode,**{k:sum(bool(x[k]) for x in result['pages']) for k in keys},'literal_equal':sum(x['mupdf_literal_equal'] for x in result['pages']),'ui_clipboard':'not_tested'}))
 return 1 if technical_failures(result) else 0
def samples(a):
 w=Path(a.work);m=load(w/'input-manifest.json');dpi=m['dpi'];doc=fitz.open(a.pdf);results=[]
 specs=load(a.samples);unique(specs,'sample');(w/'checks').mkdir(parents=True,exist_ok=True)
 output_hash=sha(a.pdf)
 for s in specs:
  if not re.fullmatch(r'[A-Za-z0-9_-]+',s['id']):raise ValueError('Use simple sample IDs')
  bbox(s['bbox'],s['page'],m)
  if not s.get('expected_origin'):raise ValueError('Record sample expectation origin')
  b=s['bbox'];n=s['page'];im=Image.open(w/'raster'/f'page-{n}.png')
  im.crop([b[0]-10,b[1]-10,b[2]+10,b[3]+10]).save(w/'checks'/f"{s['id']}-source.png")
  page=doc[n-1];clip=fitz.Rect([v*72/dpi for v in b])*page.derotation_matrix
  mu=page.get_text('text',clip=clip,sort=False)
  cmd=['pdftotext','-f',str(n),'-l',str(n),'-r',str(dpi),'-x',str(b[0]),'-y',str(b[1]),'-W',str(b[2]-b[0]),'-H',str(b[3]-b[1]),'-raw',a.pdf,'-'];pop=run(cmd).stdout
  strip=lambda x:re.sub(r'\s','',x)
  results.append({**s,'mupdf_literal':mu,'poppler_literal':pop,'mupdf_characters_pass':strip(mu)==strip(s['expected']),'poppler_characters_pass':strip(pop)==strip(s['expected']),'command':cmd,'operation':'extractor rectangle, not UI/clipboard','output_sha256':output_hash})
 dump(w/'checks/geometry-samples.json',{'inputs':bindings(pdf=a.pdf,samples=a.samples,manifest=w/'input-manifest.json'),'samples':results});print(f"Samples {len(results)}; MuPDF {sum(x['mupdf_characters_pass'] for x in results)}; Poppler {sum(x['poppler_characters_pass'] for x in results)}")
 return 0 if results and all(x['mupdf_characters_pass'] and x['poppler_characters_pass'] for x in results) else 1
def sheets(a):
 w=Path(a.work);lines=load(a.lines);font=ImageFont.truetype(a.font,18)
 for offset in range(0,len(lines),20):
  subset=lines[offset:offset+20];sheet=Image.new('RGB',(1500,max(1,len(subset))*150),'white');d=ImageDraw.Draw(sheet)
  for row,line in enumerate(subset):
   b=line['selection_region'];bounds=[max(0,b[0]-8),max(0,b[1]-8),b[2]+8,b[3]+8]
   source=Image.open(w/'raster'/f"page-{line['page']}.png").convert('RGB').crop(bounds);overlay=source.copy();draw=ImageDraw.Draw(overlay)
   for cell in line['cells']:
    cb=cell['selection_bbox'];draw.rectangle([cb[0]-bounds[0],cb[1]-bounds[1],cb[2]-bounds[0],cb[3]-bounds[1]],outline='red',width=1)
   d.text((10,row*150),line['id']+' '+line['text'][:120],font=font,fill='black')
   for col,im in enumerate([source,overlay]):im.thumbnail((730,115));sheet.paste(im,(10+col*750,row*150+25))
  sheet.save(w/'checks'/f'geometry-review-{offset//20+1:03}.png')
 print(f'Rendered {(len(lines)+19)//20} diagnostic sheets; visual review has not been asserted')
def main():
 p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
 def sub(name,func):
  parser=s.add_parser(name);parser.set_defaults(func=func);parser.add_argument('--work',required=True);return parser
 x=s.add_parser('doctor');x.set_defaults(func=doctor);x.add_argument('--work');x.add_argument('--language',default='ces');x.add_argument('--font',default=FONT_PATH);x.add_argument('--sheet-font',default='/usr/share/fonts/TTF/DejaVuSans.ttf')
 x=sub('validate-review',lambda a:print(json.dumps(validate_review(a.work,load(a.review)))));x.add_argument('--review',required=True)
 x=sub('update-line',update_line);x.add_argument('--review',required=True);x.add_argument('--id',required=True);x.add_argument('--patch',required=True)
 sub('snapshot',lambda a:print(snapshot(a.work)))
 sub('validate-run',validate_run)
 x=sub('prepare',prepare);x.add_argument('--source',required=True);x.add_argument('--dpi',type=int,default=300);x.add_argument('--language',default='ces')
 x=sub('regions',regions);x.add_argument('--regions',required=True)
 x=sub('targeted',targeted);x.add_argument('--targets',required=True)
 x=sub('draft',draft);x.add_argument('--review',required=True)
 x=sub('segment',segment);x.add_argument('--review',required=True);x.add_argument('--font',default=FONT_PATH)
 x=sub('export',export)
 for name in ['source','pages','pdf','txt']:x.add_argument('--'+name,required=True)
 x.add_argument('--allow-existing-text',action='store_true')
 x=sub('check',check)
 for name in ['source','pages','pdf','txt']:x.add_argument('--'+name,required=True)
 x.add_argument('--reviewer-root')
 x=sub('samples',samples);x.add_argument('--pdf',required=True);x.add_argument('--samples',required=True)
 x=sub('sheets',sheets);x.add_argument('--lines',required=True);x.add_argument('--font',default='/usr/share/fonts/TTF/DejaVuSans.ttf')
 a=p.parse_args()
 if a.command in ('prepare','regions','targeted','draft','segment','export','check','samples','sheets'):
  global np,Image,ImageFilter,ImageFont,ImageDraw,etree,fitz,create_pdf
  import numpy as np
  from PIL import Image,ImageFilter,ImageFont,ImageDraw
  from lxml import etree
  import fitz
  from ocr_f_layer import create_pdf
 try:return a.func(a) or 0
 except (ValueError,KeyError,TypeError,OSError,RuntimeError) as error:
  print(str(error),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
