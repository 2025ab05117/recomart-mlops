"""Generate the RecoMart DOCX report from config/report_final.yaml."""
from __future__ import annotations
import argparse, fnmatch, json, re, shutil, sqlite3, subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence
import yaml
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_CONFIG=ROOT/"config/report_final.yaml"
BLUE,DARK,MUTED=RGBColor(46,116,181),RGBColor(31,77,120),RGBColor(89,89,89)
WIDTH,INDENT=9360,120
class ReportError(RuntimeError): pass

def load_config(path):
    cfg=yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for key in ("report","format","team","sections","artifacts","validation"):
        if key not in cfg: raise ReportError(f"Missing configuration section: {key}")
    ids=[s["id"] for s in cfg["sections"] if s.get("enabled",True)]
    if ids!=cfg["validation"].get("required_section_ids",[]): raise ReportError("Enabled section order differs from validation.required_section_ids")
    return cfg

def field(p,instruction,display=""):
    r=p.add_run(); a=OxmlElement("w:fldChar"); a.set(qn("w:fldCharType"),"begin")
    b=OxmlElement("w:instrText"); b.set(qn("xml:space"),"preserve"); b.text=instruction
    c=OxmlElement("w:fldChar"); c.set(qn("w:fldCharType"),"separate"); d=OxmlElement("w:t"); d.text=display
    e=OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"),"end"); r._r.extend((a,b,c,d,e))

def setup(doc,cfg,date):
    f,r=cfg["format"],cfg["report"]; sec=doc.sections[0]
    if str(f["page_size"]).upper()!="A4": raise ReportError("Only A4 is supported")
    portrait=str(f["orientation"]).lower()=="portrait"; sec.orientation=WD_ORIENT.PORTRAIT if portrait else WD_ORIENT.LANDSCAPE
    sec.page_width,sec.page_height=((Cm(21),Cm(29.7)) if portrait else (Cm(29.7),Cm(21)))
    sec.top_margin=sec.bottom_margin=sec.left_margin=sec.right_margin=Inches(1)
    normal=doc.styles["Normal"]; normal.font.name=f["body_font"]; normal.font.size=Pt(f["body_font_size"]); normal.paragraph_format.space_after=Pt(6); normal.paragraph_format.line_spacing=1.1
    for n,s,c,b,a in (("Heading 1",16,BLUE,16,8),("Heading 2",13,BLUE,12,6),("Heading 3",12,DARK,8,4)):
        st=doc.styles[n]; st.font.name=f["heading_font"]; st.font.size=Pt(s); st.font.bold=True; st.font.color.rgb=c; st.paragraph_format.space_before=Pt(b); st.paragraph_format.space_after=Pt(a); st.paragraph_format.keep_with_next=True
    for n in ("List Bullet","List Number"):
        st=doc.styles[n]; st.font.name=f["body_font"]; st.font.size=Pt(f["body_font_size"]); st.paragraph_format.left_indent=Inches(.5); st.paragraph_format.first_line_indent=Inches(-.25)
    cap=doc.styles["Caption"]; cap.font.name=f["body_font"]; cap.font.size=Pt(9); cap.font.italic=True; cap.font.color.rgb=MUTED; cap.paragraph_format.alignment=WD_ALIGN_PARAGRAPH.CENTER
    code=doc.styles.add_style("Code Block",WD_STYLE_TYPE.PARAGRAPH); code.font.name="Consolas"; code.font.size=Pt(8.5); code.paragraph_format.left_indent=Inches(.25)
    if f.get("include_header"):
        p=sec.header.paragraphs[0]; p.alignment=WD_ALIGN_PARAGRAPH.RIGHT; p.add_run(f"{r['title']} | Generated {date}")
    if f.get("include_footer"):
        p=sec.footer.paragraphs[0]; p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        if f.get("include_page_numbers"): p.add_run("Page "); field(p,"PAGE","1")
    up=OxmlElement("w:updateFields"); up.set(qn("w:val"),"true"); doc.settings._element.append(up)

def heading(doc,n,title):
    if n>1: doc.add_page_break()
    doc.add_heading(f"{n}. {title}",1)

def margins(cell):
    pr=cell._tc.get_or_add_tcPr(); mar=OxmlElement("w:tcMar"); pr.append(mar)
    for edge,value in (("top",80),("bottom",80),("start",120),("end",120)):
        x=OxmlElement(f"w:{edge}"); x.set(qn("w:w"),str(value)); x.set(qn("w:type"),"dxa"); mar.append(x)

def table(doc,headers,rows,widths):
    if sum(widths)!=WIDTH: raise ReportError("Invalid table width")
    t=doc.add_table(rows=1,cols=len(headers),style="Table Grid"); t.autofit=False; t.alignment=WD_TABLE_ALIGNMENT.LEFT
    pr=t._tbl.tblPr
    for tag,value in (("w:tblW",WIDTH),("w:tblInd",INDENT)):
        x=OxmlElement(tag); x.set(qn("w:w"),str(value)); x.set(qn("w:type"),"dxa"); pr.append(x)
    grid=t._tbl.tblGrid
    for x in list(grid): grid.remove(x)
    for value in widths: x=OxmlElement("w:gridCol"); x.set(qn("w:w"),str(value)); grid.append(x)
    for i,value in enumerate(headers):
        t.rows[0].cells[i].text=str(value); sh=OxmlElement("w:shd"); sh.set(qn("w:fill"),"F2F4F7"); t.rows[0].cells[i]._tc.get_or_add_tcPr().append(sh)
        for run in t.rows[0].cells[i].paragraphs[0].runs: run.bold=True
    mark=OxmlElement("w:tblHeader"); mark.set(qn("w:val"),"true"); t.rows[0]._tr.get_or_add_trPr().append(mark)
    for values in rows:
        cells=t.add_row().cells
        for i,value in enumerate(values): cells[i].text="" if value is None else str(value)
    for row in t.rows:
        for i,cell in enumerate(row.cells):
            cell.vertical_alignment=WD_ALIGN_VERTICAL.CENTER; margins(cell); tc=cell._tc.get_or_add_tcPr().find(qn("w:tcW"))
            tc.set(qn("w:w"),str(widths[i])); tc.set(qn("w:type"),"dxa")
    doc.add_paragraph(); return t

def expand(patterns):
    found=[]
    for pattern in patterns: found.extend(p for p in ROOT.glob(pattern) if p.is_file())
    return list(dict.fromkeys(sorted(found,key=lambda p:str(p).lower())))

def clean(text):
    text=re.sub(r"!\[[^]]*\]\([^)]+\)","",text); text=re.sub(r"\[([^]]+)\]\([^)]+\)",r"\1",text)
    return text.replace("**","").replace("__","").replace(chr(96),"").strip()

def select(path,topics,rules):
    lines=path.read_text(encoding="utf-8",errors="replace").splitlines(); excluded={x.lower() for x in rules.get("exclude_headings",[])}
    chunks=[]; current=[]; title=""
    for line in lines:
        m=re.match(r"^(#{1,6})\s+(.+)$",line)
        if m:
            if current: chunks.append((title,current))
            title=clean(m.group(2)); current=[line]
        else: current.append(line)
    if current: chunks.append((title,current))
    terms=[x.lower() for x in topics]; chosen=[]
    for title,chunk in chunks:
        if title.lower() not in excluded and (not terms or any(x in " ".join(chunk).lower() for x in terms)): chosen+=chunk+[""]
    if not chosen: chosen=lines[:80]
    limit=int(rules.get("maximum_paragraphs_per_source",8)); out=[]; count=0
    for line in chosen:
        if line.strip() and (not out or not out[-1].strip()): count+=1
        if count>limit: break
        out.append(line)
    return out

def render(doc,lines,seen,rules):
    i=0; buf=[]; code=[]; inside=False
    def flush():
        if buf:
            value=clean(" ".join(x.strip() for x in buf)); key=re.sub(r"\W+","",value.lower())
            if value and (not rules.get("avoid_duplicate_paragraphs") or key not in seen): doc.add_paragraph(value,"Normal"); seen.add(key)
            buf.clear()
    while i<len(lines):
        line=lines[i]; s=line.strip()
        if s.startswith(chr(96)*3):
            flush()
            if inside and code: doc.add_paragraph("\n".join(code),"Code Block"); code=[]
            inside=not inside; i+=1; continue
        if inside: code.append(line); i+=1; continue
        m=re.match(r"^(#{1,6})\s+(.+)$",line)
        if m: flush(); i+=1; continue
        if s.startswith("|") and i+1<len(lines) and re.match(r"^\|?[\s:|-]+\|?$",lines[i+1].strip()):
            flush(); raw=[s]; i+=2
            while i<len(lines) and lines[i].strip().startswith("|"): raw.append(lines[i].strip()); i+=1
            values=[[clean(c) for c in row.strip("|").split("|")] for row in raw]; n=len(values[0]); widths=[WIDTH//n]*n; widths[-1]+=WIDTH-sum(widths)
            table(doc,values[0],values[1:],widths); continue
        bullet=re.match(r"^\s*[-*+]\s+(.+)$",line); number=re.match(r"^\s*\d+[.)]\s+(.+)$",line)
        if bullet or number: flush(); doc.add_paragraph(clean((bullet or number).group(1)),style="List Bullet" if bullet else "List Number"); i+=1; continue
        if s: buf.append(line)
        else: flush()
        i+=1
    flush()

def sources(doc,patterns,topics,cfg,seen):
    files=expand(patterns)
    if not files and cfg["content_rules"].get("missing_source_behavior")!="continue": raise ReportError(f"No sources match {patterns}")
    for path in files: render(doc,select(path,topics,cfg["content_rules"]),seen,cfg["content_rules"])

def image(doc,path,caption,cfg):
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    shape=p.add_run().add_picture(str(path),width=Inches(float(cfg["format"]["image_max_width_inches"])))
    shape._inline.docPr.set("descr",caption); shape._inline.docPr.set("title",caption); doc.add_paragraph(caption,"Caption")

def find_screenshots(cfg):
    out=[]
    for directory in cfg.get("directories",[]):
        root=ROOT/directory
        if not root.exists(): continue
        files=root.rglob("*") if cfg.get("recursive") else root.glob("*")
        for path in files:
            if path.suffix.lower() not in {".png",".jpg",".jpeg"}: continue
            for mapping in cfg.get("mappings",[]):
                if fnmatch.fnmatch(path.name.lower(),mapping["pattern"].lower()): out.append((mapping["title"],path)); break
    return list(dict.fromkeys(out))

def find_eda(cfg):
    root=ROOT/cfg["root"]
    dates=sorted([p for p in root.glob(cfg["date_prefix"]+"*") if p.is_dir()],key=lambda p:p.name.removeprefix(cfg["date_prefix"]))
    if not dates:return None,[],{}
    hours=sorted([p for p in dates[-1].glob(cfg["hour_prefix"]+"*") if p.is_dir()],key=lambda p:p.name.removeprefix(cfg["hour_prefix"]))
    if not hours:return None,[],{}
    batches=sorted([p for p in hours[-1].glob(cfg["batch_prefix"]+"*") if p.is_dir()],key=lambda p:p.name.removeprefix(cfg["batch_prefix"]))
    if not batches:return None,[],{}
    batch=batches[-1]; images=[]
    for pattern in cfg.get("image_patterns",["*.png"]): images+=list(batch.glob(pattern))
    summary=batch/cfg.get("summary_file",""); data=json.loads(summary.read_text(encoding="utf-8")) if summary.is_file() else {}
    return batch.name.removeprefix(cfg["batch_prefix"]),sorted(set(images)),data

def find_features(cfg):
    db=next((ROOT/p for p in cfg.get("paths",[]) if (ROOT/p).is_file()),None)
    if not db:return None,[]
    result=[]
    with sqlite3.connect(db) as con:
        names=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for name in names:
            safe=name.replace('"','""'); info=con.execute(f'PRAGMA table_info("{safe}")').fetchall(); count=con.execute(f'SELECT COUNT(*) FROM "{safe}"').fetchone()[0]
            samples=[]
            if cfg.get("include_sample_rows"):
                cols=[x[1] for x in info]; samples=[dict(zip(cols,row)) for row in con.execute(f'SELECT * FROM "{safe}" LIMIT ?',(int(cfg.get("sample_row_limit",5)),))]
            result.append({"name":name,"rows":count,"columns":[f"{x[1]} ({x[2] or 'ANY'})" for x in info],"pk":[x[1] for x in info if x[5]],"samples":samples})
    return db,result

def find_dvc(cfg):
    path=ROOT/cfg["pipeline_file"]
    if not path.is_file(): return [], "", ""
    stages=[]
    for name,data in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("stages",{}).items():
        stages.append((name,data.get("cmd",""),"\n".join(map(str,data.get("deps",[]))),"\n".join(map(str,data.get("outs",[])))))
    status=dag=""
    if cfg.get("run_cli_when_available") and shutil.which("dvc"):
        for args,target in ((["dvc","status"],"status"),(["dvc","dag"],"dag")):
            try: value=(subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=30).stdout or "").strip()
            except Exception: value=""
            if target=="status": status=value
            else: dag=value
    return stages,status,dag

def find_mlflow(cfg):
    runs=[]
    for root in [ROOT/p for p in cfg.get("tracking_locations",[]) if (ROOT/p).is_dir()]:
        for meta in root.glob("*/*/meta.yaml"):
            data=yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
            if cfg.get("latest_successful_runs") and str(data.get("status")) not in ("3","FINISHED"): continue
            exp_meta=meta.parents[1]/"meta.yaml"; exp=yaml.safe_load(exp_meta.read_text(encoding="utf-8")) if exp_meta.is_file() else {}
            if cfg.get("experiment_name") and exp.get("name")!=cfg["experiment_name"]: continue
            folder=meta.parent; params={p.name:p.read_text(encoding="utf-8") for p in (folder/"params").glob("*")} if (folder/"params").is_dir() else {}; metrics={}
            if (folder/"metrics").is_dir():
                for p in (folder/"metrics").glob("*"):
                    try: metrics[p.name]=float(p.read_text(encoding="utf-8").splitlines()[-1].split()[1])
                    except (ValueError,IndexError): pass
            runs.append({"experiment":exp.get("name",""),"name":data.get("run_name",folder.name),"run_id":data.get("run_id",folder.name),"status":"FINISHED","params":params,"metrics":metrics,"start":int(data.get("start_time",0))})
    runs.sort(key=lambda x:x["start"],reverse=True)
    return runs[:max(1,int(cfg.get("runs_per_model",1))*2)]

def add_features(doc,items):
    if not items: doc.add_paragraph("Evidence not available at report-generation time."); return
    table(doc,("Table","Rows","Columns and Datatypes","Primary Key"),((x["name"],x["rows"],", ".join(x["columns"]),", ".join(x["pk"]) or "None") for x in items),(1700,900,5100,1660))
    for item in sorted(items,key=lambda x:x["rows"],reverse=True)[:3]:
        if not item["samples"]: continue
        doc.add_heading(f"Sample: {item['name']}",3); keys=list(item["samples"][0])[:5]; widths=[WIDTH//len(keys)]*len(keys); widths[-1]+=WIDTH-sum(widths)
        table(doc,keys,([str(row.get(k,""))[:80] for k in keys] for row in item["samples"]),widths)

def add_dvc(doc,data):
    stages,status,dag=data
    if not stages: doc.add_paragraph("Evidence not available at report-generation time."); return
    table(doc,("Stage","Command","Dependencies","Outputs"),stages,(1300,2900,2600,2560))
    if status: doc.add_heading("DVC Status",3); doc.add_paragraph(status,"Code Block")
    if dag: doc.add_heading("DVC DAG",3); doc.add_paragraph(dag,"Code Block")

def add_mlflow(doc,runs,cfg):
    if not runs: doc.add_paragraph("Evidence not available at report-generation time."); return
    options=cfg["artifacts"]["mlflow"]
    for run in runs:
        doc.add_heading(f"{run['experiment']} - {run['name']}",3); rows=[]
        if options.get("include_run_ids"): rows.append(("Run ID",run["run_id"]))
        rows.append(("Status",run["status"]))
        if options.get("include_parameters"): rows.append(("Parameters",", ".join(f"{k}={v}" for k,v in run["params"].items()) or "None"))
        if options.get("include_metrics"): rows.append(("Metrics",", ".join(f"{k}={v:.6g}" for k,v in run["metrics"].items()) or "None"))
        table(doc,("Field","Value"),rows,(1800,7560))

def generate(config_path=DEFAULT_CONFIG,overwrite=False):
    cfg=load_config(config_path.resolve()); output=(ROOT/cfg["report"]["output"]).resolve()
    if output.exists() and not overwrite: raise FileExistsError(f"Refusing to overwrite {output}")
    date=datetime.now().astimezone().strftime("%Y-%m-%d"); doc=Document(); setup(doc,cfg,date); seen=set()
    shots=find_screenshots(cfg["artifacts"]["screenshots"]); batch,eda_images,eda_summary=find_eda(cfg["artifacts"]["eda"])
    feature_db,features=find_features(cfg["artifacts"]["feature_store"]); dvc=find_dvc(cfg["artifacts"]["dvc"]); runs=find_mlflow(cfg["artifacts"]["mlflow"])
    enabled=[s for s in cfg["sections"] if s.get("enabled",True)]
    for number,section in enumerate(enabled,1):
        heading(doc,number,section["title"]); kind=section["type"]
        if kind=="title_page":
            for _ in range(4): doc.add_paragraph()
            for value,size,color,bold in ((cfg["report"]["institution"],12,MUTED,True),(cfg["report"]["title"],26,DARK,True),(cfg["report"]["subtitle"],15,BLUE,False)):
                p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; r=p.add_run(value); r.font.size=Pt(size); r.font.color.rgb=color; r.bold=bold
            values=(cfg["report"]["assignment"],f"Report Version: {cfg['report']['version']}")
            if cfg["report"].get("generated_date"): values+=(f"Generated: {date}",)
            for value in values: p=doc.add_paragraph(value); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        elif kind=="team_table":
            table(doc,("S. No.","Name","BITS ID / Email ID"),((m["serial_no"],m["name"],m["bits_id"]) for m in cfg["team"]),(1000,3300,5060))
            if cfg["format"].get("include_table_of_contents"):
                p=doc.add_paragraph(); r=p.add_run("Table of Contents"); r.bold=True; r.font.size=Pt(14); r.font.color.rgb=BLUE
                toc=doc.add_paragraph(); field(toc,'TOC \\o "1-3" \\h \\z \\u',"Update field in Word to refresh.")
        elif kind=="markdown":
            sources(doc,section.get("sources",[]),section.get("include_topics",[]),cfg,seen)
        elif kind=="markdown_and_pipeline":
            sources(doc,section.get("sources",[]),section.get("include_topics",[]),cfg,seen)
            if section.get("pipeline"):
                doc.add_heading("Pipeline Flow",2)
                for step in section["pipeline"]: doc.add_paragraph(step,"List Number")
        elif kind=="implementation":
            for i,sub in enumerate(section.get("subsections",[]),1):
                doc.add_heading(f"{number}.{i} {sub['title']}",2); sources(doc,sub.get("sources",[]),sub.get("include_topics",[]),cfg,seen)
                artifact=sub.get("artifact")
                if artifact=="feature_store": add_features(doc,features)
                elif artifact=="dvc": add_dvc(doc,dvc)
                elif artifact=="mlflow": add_mlflow(doc,runs,cfg)
        elif kind=="results":
            for i,item in enumerate(section.get("include",[]),1):
                doc.add_heading(f"{number}.{i} {item.replace('_',' ').title()}",2)
                if item=="screenshots":
                    if not shots: doc.add_paragraph("Evidence not available at report-generation time.")
                    for title,path in shots: image(doc,path,f"{title} - {path.name}",cfg)
                elif item=="latest_eda":
                    if batch: doc.add_paragraph(f"Selected latest partitioned EDA batch: {batch}.")
                    if eda_summary: table(doc,("Measure","Value"),((k,json.dumps(v) if isinstance(v,(dict,list)) else v) for k,v in eda_summary.items()),(3000,6360))
                    if not eda_images: doc.add_paragraph("Evidence not available at report-generation time.")
                    for path in eda_images: image(doc,path,f"{path.stem.replace('_',' ').title()} - EDA batch {batch}",cfg)
                elif item=="feature_store_summary":
                    if feature_db: doc.add_paragraph(f"Feature-store database: {feature_db.relative_to(ROOT)}")
                    add_features(doc,features)
                elif item=="dvc_summary": add_dvc(doc,dvc)
                elif item=="mlflow_summary": add_mlflow(doc,runs,cfg)
        else: raise ReportError(f"Unsupported section type: {kind}")
    output.parent.mkdir(parents=True,exist_ok=True); doc.save(output); validate(output,cfg)
    return output,{"eda_batch":batch,"screenshots":[p.name for _,p in shots],"feature_tables":[x["name"] for x in features],"dvc_stages":[x[0] for x in dvc[0]],"mlflow_runs":[x["run_id"] for x in runs]}

def validate(path,cfg):
    if cfg["validation"].get("require_output_file") and (not path.is_file() or path.stat().st_size==0): raise ReportError("Output missing or empty")
    doc=Document(path); actual=[p.text for p in doc.paragraphs if p.style.name=="Heading 1"]; expected=[f"{i}. {s['title']}" for i,s in enumerate([x for x in cfg["sections"] if x.get("enabled",True)],1)]
    if cfg["validation"].get("reject_additional_top_level_sections") and actual!=expected: raise ReportError("Top-level headings do not match YAML")
    if cfg["validation"].get("require_all_team_members"):
        text="\n".join(p.text for p in doc.paragraphs)+"\n"+"\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
        if any(m["name"] not in text or m["bits_id"] not in text for m in cfg["team"]): raise ReportError("A configured team member is absent")
    if any(x in "\n".join(p.text for p in doc.paragraphs) for x in ("{{","}}","<PLACEHOLDER>")): raise ReportError("Unresolved template marker")

def main(argv:Sequence[str]|None=None):
    parser=argparse.ArgumentParser(); parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG); parser.add_argument("--overwrite",action="store_true"); args=parser.parse_args(argv)
    output,evidence=generate(args.config,args.overwrite); print(json.dumps({"output":str(output),**evidence},indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
