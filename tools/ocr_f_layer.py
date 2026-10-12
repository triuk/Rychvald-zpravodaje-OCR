"""Content-free F text-layer generator; supply fresh reviewed cells.

Input contract and verification: docs/ocr-f-construction.md.
This module carries no transcript, coordinates, or issue-specific exceptions.
"""
from pathlib import Path
import copy, json, re
import fitz
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

def make_font(cells,index,directory,metric_scale=1):
    builder=FontBuilder(1000,isTTF=True)
    names=['.notdef']+[f'cell{i}' for i in range(len(cells))]
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({0xE000+i:f'cell{i}' for i in range(len(cells))})
    glyphs={};metrics={}
    for name,width in [('.notdef',500)]+[(f'cell{i}',c['units_width']) for i,c in enumerate(cells)]:
        pen=TTGlyphPen(None)
        pen.moveTo((0,-metric_scale));pen.lineTo((width,-metric_scale));pen.lineTo((width,1000*metric_scale))
        pen.lineTo((0,1000*metric_scale));pen.closePath()
        glyphs[name]=pen.glyph();metrics[name]=(width,0)
    builder.setupGlyf(glyphs);builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=1000*metric_scale,descent=-metric_scale)
    name=f'OCRCells{index}'
    builder.setupNameTable({'familyName':name,'styleName':'Regular','uniqueFontIdentifier':name+'-1',
                           'fullName':name,'psName':name,'version':'Version 1.0'})
    builder.setupOS2(sTypoAscender=1000*metric_scale,sTypoDescender=-metric_scale,sTypoLineGap=0,
                    usWinAscent=1000*metric_scale,usWinDescent=metric_scale,sxHeight=1000*metric_scale,sCapHeight=1000*metric_scale)
    builder.setupPost();path=directory/f'cells-{index}.ttf';builder.save(path)
    pdfmetrics.registerFont(TTFont(f'OCRCells{index}',str(path)))

def create_pdf(pages,source_path,output_path,*,work_dir,raster_dpi=300):
    assert raster_dpi>0
    factor=72/raster_dpi
    directory=Path(work_dir);directory.mkdir(parents=True,exist_ok=True)
    source=fitz.open(source_path);fonts=[[]];font_scales=[1];current_fonts={1:0}
    assert len(pages)==len(source)>0
    events=[]
    units_by_page=[]
    for page_index,data in enumerate(pages):
        assert data['page']==page_index+1
        units=[]
        for unit_index,unit in enumerate(data['units']):
            assert unit['tag'] in ('H1','H2','P')
            cells=[];lines=unit['lines']
            assert lines
            for i,line in enumerate(lines):
                assert line['cells']
                cells.extend(copy.deepcopy(line['cells']))
                if i<len(lines)-1:
                    join=line['join_after']
                    assert join in ('space','typesetting_hyphen','literal_hyphen','none')
                    events.append({'page':data['page'],'unit':unit_index,'line':i,'type':'line_join','join_after':join})
                    if join=='typesetting_hyphen':
                        assert cells[-1]['text']=='-', 'Typesetting hyphen must have its own final cell'
                        cells.pop()
                    elif join=='literal_hyphen':
                        assert cells[-1]['text']=='-', 'Literal hyphen must have its own final cell'
                    elif join=='space':
                        last=cells[-1]['selection_bbox']
                        cells.append({'text':' ','selection_bbox':[last[2],last[1],last[2]+.72/factor,last[3]]})
            unit['pdf_text']=''.join(c['text'] for c in cells)
            previous=None
            for cell_index,cell in enumerate(cells):
                assert len(cell['text'])==1
                x0,y0,x1,y1=[v*factor for v in cell['selection_bbox']]
                assert x1>=x0 and y1>y0
                # A minimum advance is a logged construction fallback,
                # never an independently verified source-geometry repair.
                if x1-x0<.02:
                    events.append({'page':data['page'],'unit':unit_index,'cell':cell_index,
                                   'type':'minimum_advance','bbox_points':[x0,y0,x1,y1]})
                x1=max(x0+.02,x1)
                metric_scale=1
                # Separate tightly adjacent repeated characters by font
                # metrics, preserving their page boxes and Unicode.
                if previous and previous['text']==cell['text']:
                    pb=previous['bbox_points']
                    if abs(y1-pb[3])<.1 and abs(x1-pb[2])<(y1-y0)*.1:
                        metric_scale=2
                        events.append({'page':data['page'],'unit':unit_index,'cell':cell_index,
                                       'type':'repeated_character_metric_scale','text':cell['text'],
                                       'bbox_points':[x0,y0,x1,y1],'metric_scale':metric_scale})
                size=(y1-y0)/(1.001*metric_scale)
                assert size>0 and x1>x0
                index=current_fonts.get(metric_scale)
                if index is None or len(fonts[index])>=6000:
                    index=len(fonts);fonts.append([]);font_scales.append(metric_scale);current_fonts[metric_scale]=index
                cell.update(font_index=index,font_cell=len(fonts[index]),size=size,
                            bbox_points=[x0,y0,x1,y1],units_width=max(1,int((x1-x0)/size*1000-1e-6)))
                fonts[index].append(cell);previous=cell
            units.append((unit,cells))
        units_by_page.append(units)
    assert any(fonts), 'No text cells supplied'
    (directory/'construction-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2)+'\n')
    for index,cells in enumerate(fonts):make_font(cells,index,directory,font_scales[index])
    draft=directory/'text-layer.pdf'
    writer=canvas.Canvas(str(draft),pagesize=source[0].rect[2:],pageCompression=1)
    writer._preamble='1 0 0 1 0 0 cm'
    for page,units in zip(source,units_by_page):
        writer.setPageSize((page.rect.width,page.rect.height))
        writer._preamble='1 0 0 1 0 0 cm'
        for mcid,(unit,cells) in enumerate(units):
            writer._code.append(f'/{unit["tag"]} << /MCID {mcid} >> BDC')
            obj=writer.beginText();obj.setTextRenderMode(3)
            for cell in cells:
                x0,y0,x1,y1=cell['bbox_points'];size=cell['size']
                obj.setFont(f'OCRCells{cell["font_index"]}',size)
                obj.setTextOrigin(x0,page.rect.height-y1+.001*size)
                obj.textOut(chr(0xE000+cell['font_cell']))
            writer.drawText(obj);writer._code.append('EMC')
        writer.showPage()
    writer.save()
    layer=fitz.open(draft);mapped=0
    for xref in range(1,layer.xref_length()):
        kind,value=layer.xref_get_key(xref,'ToUnicode')
        if kind!='xref':continue
        base=layer.xref_get_key(xref,'BaseFont')[1]
        match=re.search(r'OCRCells(\d+)',base)
        if not match:continue
        index=int(match[1]);cmap_xref=int(value.split()[0]);cmap=layer.xref_stream(cmap_xref).decode('ascii')
        def replace(m):
            nonlocal mapped
            code=int(m[2],16)-0xE000
            if not 0<=code<len(fonts[index]):return m[0]
            mapped+=1
            return m[1]+'<'+fonts[index][code]['text'].encode('utf-16-be').hex().upper()+'>'
        cmap=re.sub(r'(<[0-9A-Fa-f]+>\s*)<([EeFf][0-9A-Fa-f]{3})>',replace,cmap)
        layer.update_stream(cmap_xref,cmap.encode('ascii'))
    # ReportLab may expose the same glyph in multiple subsets on later pages.
    assert mapped>=sum(map(len,fonts)),(mapped,sum(map(len,fonts)))
    doc=fitz.open(source_path)
    def new(value):
        x=doc.get_new_xref();doc.update_object(x,value);return x
    root=new('<< >>');parent=new('<< >>');document=new('<< >>');elements=[];parent_pairs=[]
    for page,data in zip(doc,pages):
        original=page.get_contents()
        prefix=new('<< >>');doc.update_stream(prefix,b'/Artifact BMC\n')
        suffix=new('<< >>');doc.update_stream(suffix,b'\nEMC\n')
        doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{x} 0 R' for x in [prefix,*original,suffix])+']')
        page.show_pdf_page(page.rect,layer,page.number,overlay=True)
        forms=page.get_xobjects()
        # Fullpage names may be suffixed; the inner Form owns the MCIDs.
        form=next(x[0] for x in forms if x[1]=='fullpage')
        page_elements=[]
        for mcid,unit in enumerate(data['units']):
            element=new(f'<< /Type /StructElem /S /{unit["tag"]} /P {document} 0 R /Pg {page.xref} 0 R '
                        f'/K << /Type /MCR /Pg {page.xref} 0 R /Stm {form} 0 R /MCID {mcid} >> >>')
            page_elements.append(element);elements.append(element)
        parent_pairs.append(f'{page.number} ['+' '.join(f'{x} 0 R' for x in page_elements)+']')
        doc.xref_set_key(form,'StructParents',str(page.number))
        doc.xref_set_key(page.xref,'Tabs','/S')
    doc.update_object(parent,'<< /Nums ['+' '.join(parent_pairs)+'] >>')
    doc.update_object(document,f'<< /Type /StructElem /S /Document /P {root} 0 R /K ['+' '.join(f'{x} 0 R' for x in elements)+'] >>')
    doc.update_object(root,f'<< /Type /StructTreeRoot /K {document} 0 R /ParentTree {parent} 0 R /ParentTreeNextKey {len(doc)} >>')
    doc.xref_set_key(doc.pdf_catalog(),'StructTreeRoot',f'{root} 0 R')
    doc.xref_set_key(doc.pdf_catalog(),'MarkInfo','<< /Marked true >>');doc.xref_set_key(doc.pdf_catalog(),'Lang','(cs-CZ)')
    doc.set_metadata({'title':Path(source_path).stem+' - OCR',
                      'subject':'F cell-font construction; compatibility requires this export\'s own verification.',
                      'creator':'OCR F glyph-cell authoring','producer':'ReportLab + PyMuPDF '+fitz.VersionBind})
    doc.save(output_path,garbage=0,deflate=False)
    return doc
