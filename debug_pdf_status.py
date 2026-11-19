import hashlib, io, json, re
import pdfplumber, requests
from updater import HEADERS, find_bn_resource_link

url,label=find_bn_resource_link()
r=requests.get(url,headers=HEADERS,timeout=45,allow_redirects=True)
r.raise_for_status()
data=r.content
print("DEBUG_SOURCE",url,label,"bytes",len(data),"sha256",hashlib.sha256(data).hexdigest(),flush=True)
with pdfplumber.open(io.BytesIO(data)) as pdf:
    found=[]
    for pn,page in enumerate(pdf.pages,1):
        text=page.extract_text() or ""
        if "podstawy ekonomii" in text.casefold():
            found.append(pn)
            print("DEBUG_PAGE",pn,"size",page.width,page.height,"chars",len(page.chars),"rects",len(page.rects),"curves",len(page.curves),flush=True)
            print("DEBUG_TEXT_BEGIN",flush=True)
            print(text,flush=True)
            print("DEBUG_TEXT_END",flush=True)
            words=page.extract_words(x_tolerance=2,y_tolerance=3,keep_blank_chars=False,use_text_flow=False)
            marker_words=[i for i,w in enumerate(words) if re.search(r"zwolnienie|lekars",w["text"],re.I)]
            print("DEBUG_MARKER_WORDS",len(marker_words),flush=True)
            for i in marker_words:
                for w in words[max(0,i-12):min(len(words),i+16)]:
                    print(f"W {w['top']:.1f} {w['x0']:.1f}-{w['x1']:.1f} {w['text']}",flush=True)
                print("MARKER_CONTEXT_END",flush=True)
            print("DEBUG_RED_RECTS_BEGIN",flush=True)
            for rect in page.rects:
                stroke=rect.get("stroking_color"); fill=rect.get("non_stroking_color")
                is_red=(isinstance(stroke,(tuple,list)) and len(stroke)>=3 and stroke[0]>.65 and stroke[1]<.4 and stroke[2]<.4) or (isinstance(fill,(tuple,list)) and len(fill)>=3 and fill[0]>.75 and fill[1]<.65 and fill[2]<.65)
                if is_red:
                    print("RECT",json.dumps({k:rect.get(k) for k in ("x0","x1","top","bottom","width","height","linewidth","stroking_color","non_stroking_color","fill","stroke")},default=str),flush=True)
            print("DEBUG_RED_RECTS_END",flush=True)
            print("DEBUG_RED_CURVES_BEGIN",flush=True)
            for curve in page.curves:
                stroke=curve.get("stroking_color"); fill=curve.get("non_stroking_color")
                is_red=(isinstance(stroke,(tuple,list)) and len(stroke)>=3 and stroke[0]>.65 and stroke[1]<.4 and stroke[2]<.4) or (isinstance(fill,(tuple,list)) and len(fill)>=3 and fill[0]>.75 and fill[1]<.65 and fill[2]<.65)
                if is_red:
                    print("CURVE",json.dumps({k:curve.get(k) for k in ("x0","x1","top","bottom","linewidth","stroking_color","non_stroking_color","fill","stroke","pts")},default=str),flush=True)
            print("DEBUG_RED_CURVES_END",flush=True)
    print("DEBUG_FOUND_PAGES",found,flush=True)
