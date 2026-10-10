import hashlib
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

from PIL import Image


def test_sample_evaluation_reuses_saved_ocr_and_preserves_source_catalog(tmp_path):
    samples, libraries = tmp_path/'samples', tmp_path/'libraries'
    samples.mkdir(); libraries.mkdir()
    photo = BytesIO(); Image.new('RGB',(100,60),'white').save(photo,format='JPEG')
    data=photo.getvalue(); (samples/'qr.jpg').write_bytes(data); (samples/'photo.jpg').write_bytes(data)
    with sqlite3.connect(libraries/'jlcparts.db') as db:
        db.execute("CREATE TABLE jlc_components(lcsc INTEGER PRIMARY KEY,mfr TEXT,manufacturer TEXT,package TEXT,category TEXT,description TEXT,library_type TEXT)")
        db.execute("CREATE TABLE lcsc_components(lcsc INTEGER PRIMARY KEY,image TEXT,url_slug TEXT)")
        db.execute("INSERT INTO jlc_components VALUES(6119867,'CGA0603X7R104K500JT','TDK','0603','Capacitors','100nF','base')")
    catalog_hash=hashlib.sha256((libraries/'jlcparts.db').read_bytes()).hexdigest()
    evidence=tmp_path/'saved.json'
    evidence.write_text(json.dumps([
        {'filename':'qr.jpg','scan':{'label':{'is_jlc_qr':True,'pc':'C6119867','pm':'CGA0603X7R104K500JT','qty':7},'ocr':None}},
        {'filename':'photo.jpg','scan':{'label':{'is_jlc_qr':False,'image_sha256':hashlib.sha256(data).hexdigest()},
          'ocr':{'api_version':'1','engine':'paddleocr-vl-llama.cpp','status':'incomplete','error':'ocr_incomplete','lines':[{'text':'Unknown model'}]}}},
    ]))
    output=tmp_path/'report.json'
    command=[sys.executable,'scripts/evaluate_scan_samples.py','--samples',str(samples),'--saved-scans',str(evidence),
             '--library-dir',str(libraries),'--output',str(output),'--work-dir',str(tmp_path/'runs')]
    result=subprocess.run(command,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode == 0,result.stderr+result.stdout
    report=json.loads(output.read_text())
    assert report['summary']['ocr_calls'] == 0
    assert report['summary']['imported'] == 1
    assert report['summary']['needs_review'] == 1
    assert report['summary']['qr_quantity'] == 7
    assert hashlib.sha256((libraries/'jlcparts.db').read_bytes()).hexdigest() == catalog_hash
    # The complete output is also an input artifact for later text-only evaluations.
    repeated = command.copy()
    repeated[repeated.index('--saved-scans')+1] = str(output)
    result=subprocess.run(repeated,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode == 0,result.stderr+result.stdout
    assert json.loads(output.read_text())['summary'] == report['summary']

    entries=json.loads(evidence.read_text())
    entries[1]['scan']['ocr']['engine']='PP-OCRv4'
    evidence.write_text(json.dumps(entries))
    result=subprocess.run(command,cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    assert result.returncode != 0
    assert 'llama.cpp OCR evidence required' in result.stderr
    assert hashlib.sha256((libraries/'jlcparts.db').read_bytes()).hexdigest() == catalog_hash
