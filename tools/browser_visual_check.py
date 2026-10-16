from playwright.sync_api import sync_playwright
from pathlib import Path
import base64
base=Path.cwd()
with sync_playwright() as p:
  browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  page=browser.new_page(viewport={'width':1300,'height':900},device_scale_factor=1)
  errors=[]
  page.on('pageerror',lambda err:errors.append(str(err)))
  root=Path(__file__).resolve().parents[1]
  html=(root/'preview_demo.html').read_text()
  script=(root/'custom_components/viwaco_reader/frontend/viwaco-dashboard.js').read_text()
  icon=base64.b64encode((root/'custom_components/viwaco_reader/brand/icon.png').read_bytes()).decode('ascii')
  script=script.replace('src="/viwaco_reader/icon.png"',f'src="data:image/png;base64,{icon}"')
  html=html.replace('<script src="./custom_components/viwaco_reader/frontend/viwaco-dashboard.js"></script>', '<script>'+script+'</script>')
  page.set_content(html,wait_until='load')
  page.wait_for_selector('#card .kpi')
  page.screenshot(path=str(base/'viwaco_v1_6_editor_desktop.png'),full_page=False)
  sel=page.locator('#editor').locator('select#palette')
  sel.select_option('rose')
  page.locator('#editor').locator('input#opacity').fill('55')
  page.locator('#editor').locator('input#opacity').dispatch_event('change')
  assert 'background_opacity:55%' not in page.locator('#card').evaluate('(node)=>node.shadowRoot.innerHTML') # theme variable differs
  html=page.locator('#card').evaluate('(node)=>node.shadowRoot.innerHTML')
  assert '--vw-surface-opacity:55%' in html and '--vw-hero1:#602548' in html
  editor_state=page.locator('#editor').evaluate('(node)=>node.shadowRoot.innerHTML')
  assert '55%' in editor_state
  page.set_viewport_size({'width':390,'height':844})
  page.wait_for_timeout(250)
  page.screenshot(path=str(base/'viwaco_v1_6_preview_mobile.png'),full_page=True)
  dims=page.locator('#card').evaluate('''(el)=>{ const root=el.shadowRoot;const k=root.querySelector('.kpis');const kp=[...root.querySelectorAll('.kpi')];const r=kp.map(e=>e.getBoundingClientRect());return {scroll:el.scrollWidth,client:el.clientWidth, cols:getComputedStyle(k).gridTemplateColumns, kpiWidths:r.map(e=>e.width),kpiRows:r.map(e=>Math.round(e.y)), recentMobile: getComputedStyle(root.querySelector('.recent-mobile')).display, chartScroll: getComputedStyle(root.querySelector('.chart-scroll')).overflowX}; }''')
  print('MOBILE DIMENSIONS',dims)
  assert dims['scroll']<=dims['client']+2, 'Card overflows viewport'
  assert len(set(dims['kpiRows']))==2, 'KPI responsive grid should have 2 rows'
  assert dims['recentMobile']=='grid'
  assert dims['chartScroll']=='auto'
  for width in [320,480,768,1024]:
    page.set_viewport_size({'width':width,'height':844})
    page.wait_for_timeout(80)
    sizes=page.locator('#card').evaluate('(el)=>({client:el.clientWidth, scroll:el.scrollWidth})')
    print('Width',width,sizes)
    assert sizes['scroll']<=sizes['client']+2, 'Card overflowing at '+str(width)
  print('Browser errors',errors)
  assert not errors
  browser.close()
