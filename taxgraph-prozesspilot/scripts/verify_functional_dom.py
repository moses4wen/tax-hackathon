"""Offline Chromium DOM + real TestClient API harness. No browser network bypass."""
import os, sys, json, tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from fastapi.testclient import TestClient
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
out=Path(os.environ.get('QA_OUTPUT_DIR',tempfile.mkdtemp(prefix='pilot-qa-')))
out.mkdir(parents=True,exist_ok=True)
os.environ['DATABASE_PATH']=tempfile.mkdtemp(prefix='dom-test-')+'/db.sqlite'
os.environ.pop('APP_ENV',None);os.environ.pop('APP_PASSWORD',None)
from app.storage import init_db,connect
from app.auth import create_user
from app.server import app
init_db()
with connect() as c:
 for user,role in [('author','editor'),('reader','viewer'),('reviewer','reviewer')]:create_user(c,user,'demo',role,'playwright-synthetic-password-123')
os.environ['APP_ENV']='production'
html=(root/'app/static/functional.html').read_text()
import re
html=re.sub(r'<link[^>]+>', '', html)
html=re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.S)
css=(root/'app/static/functional.css').read_text();js=(root/'app/static/functional.js').read_text()
report={'mode':'offline DOM with TestClient transport; not live-network deployment QA','console_errors':[],'checks':[]}
with TestClient(app) as client, sync_playwright() as p:
 browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
 def login(user):
  page=browser.new_page(viewport={'width':1480,'height':1050})
  page.on('pageerror',lambda e:report['console_errors'].append(str(e)))
  def backend(path,options):
   if not path.startswith('/api/'):raise ValueError('Fixture transport only serves the owned API')
   response=client.request(options.get('method','GET'),path,content=options.get('body'),headers={'Content-Type':'application/json'},auth=(user,'playwright-synthetic-password-123'))
   return {'body':response.text,'status':response.status_code}
  page.expose_function('testBackend',backend)
  page.set_content(html)
  page.add_style_tag(content=css)
  page.add_script_tag(content="window.fetch=async(path,options={})=>{const r=await window.testBackend(path,options);return new Response(r.body,{status:r.status,headers:{'Content-Type':'application/json'}});};")
  page.add_script_tag(content=js)
  page.wait_for_function("document.querySelector('#facts .fact')!==null")
  return page
 page=login('author')
 assert page.locator('#newProcess').is_visible()
 page.locator('[data-tab=case]').click();page.locator('#sampleNegative').click();page.locator('#saveInputs').click()
 page.wait_for_function("document.querySelector('#toast').textContent.includes('gespeichert.')")
 assert page.locator('#error').is_hidden(),page.locator('#error').inner_text()
 page.locator('#run').click();page.locator('#result').wait_for()
 assert page.locator('#runStatus').inner_text()=='Fachliche Freigabe offen'
 assert 'c_aufstockung' in page.locator('#path').inner_text()
 assert page.locator('#graph .node').count()==24
 assert page.locator('#approve').is_hidden()
 page.locator('#pathOnly').check();page.screenshot(path=str(out/'functional-author.png'),full_page=False)
 report['checks'].append('Author negative-net-assets saved and executed; graph path and no approval permission')
 page.close()
 page=login('reader')
 assert page.locator('#newProcess').is_hidden();assert page.locator('#editorTab').is_hidden()
 page.locator('[data-tab=case]').click();assert page.locator('#run').is_hidden();assert page.locator('#facts input').first.is_disabled()
 page.locator('[data-tab=history]').click();page.locator('#runList button').first.click();page.locator('#result').wait_for()
 assert page.locator('#approve').is_hidden()
 report['checks'].append('Viewer published-process and historical-run display; no writes')
 page.close()
 page=login('reviewer');page.locator('[data-tab=history]').click();page.locator('#runList button').first.click();page.locator('#result').wait_for()
 page.on('dialog',lambda d:d.accept('Synthetischer Testfall und Rechenspur im DOM geprueft.'))
 page.locator('#approve').click();page.wait_for_function("document.querySelector('#approvals').textContent.includes('approved')")
 assert page.locator('#error').is_hidden()
 page.screenshot(path=str(out/'functional-reviewer.png'),full_page=False)
 report['checks'].append('Reviewer approval, attribution and replay displayed')
 page.close();browser.close()
report['passed']=not report['console_errors'];(out/'browser-dom-qa.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
