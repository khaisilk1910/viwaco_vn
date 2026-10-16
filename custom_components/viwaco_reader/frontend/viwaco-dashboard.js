/* VIWACO Reader Dashboard 1.6.0 — standalone Lovelace card, no third-party JS.
   History and customer profile come from the authenticated Home Assistant
   WebSocket. Cookie and ASP.NET VIEWSTATE are never transmitted to the browser.
   Contact details can be hidden on screen; this is not an access control. */
const E = (x) => String(x ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (x) => new Intl.NumberFormat('vi-VN').format(Number(x || 0));
const money = (x) => `${num(x)} đ`;
const amount = (x) => Number(x || 0);
const periodKey = (x) => { const [m,y]=String(x).split('/'); return `${y}-${String(m).padStart(2,'0')}`; };
const fmtPeriod = (x) => `T${String(x || '').split('/')[0] || '—'}`;
const trustedArchiveUrl = (value) => /^\/local\/viwaco_reader\/[a-f0-9]{20}\/20\d{2}\/20\d{2}-(0[1-9]|1[0-2])(?:_p\d{2})?\.(?:png|pdf)$/.test(String(value||'')) ? value : null;
const trustedBillUrl = (value) => { try { const u = new URL(value); return u.protocol === 'https:' && u.hostname === 'hoadon.viwaco.vn' ? u.href : null; } catch { return null; } };

const VW_PALETTES = Object.freeze({
  ocean: {name:'Ocean · Xanh biển', colors:['#102a56','#144f8d','#078aa8','#268cff','#04c7b0']},
  cyan: {name:'Cyan · Xanh ngọc', colors:['#07505a','#087a8f','#10a6b2','#04bcd4','#00c8b5']},
  blue: {name:'Blue · Xanh dương', colors:['#163365','#1458b3','#2189e6','#338cff','#00b0e5']},
  indigo: {name:'Indigo · Chàm', colors:['#23265e','#3943a1','#6168cc','#6962dd','#33a6d8']},
  violet: {name:'Violet · Tím', colors:['#382064','#59379e','#8859c2','#9364ee','#e173d3']},
  rose: {name:'Rose · Hồng', colors:['#602548','#963d73','#c95d90','#e06aa8','#ed9bba']},
  orange: {name:'Orange · Cam', colors:['#763117','#bb5c20','#df8930','#ef9638','#e5b362']},
  amber: {name:'Amber · Hổ phách', colors:['#65430d','#9b6d16','#c99328','#dda72c','#b6a84f']},
  green: {name:'Green · Xanh lá', colors:['#17452f','#236c43','#399960','#48b376','#6abf88']},
  teal: {name:'Teal · Xanh lục lam', colors:['#073f43','#12686b','#158989','#12aa9e','#46c9b4']},
  slate: {name:'Slate · Trung tính', colors:['#253141','#34455c','#506779','#6e8197','#48a0ae']}
});
const vwOpacity = value => Number.isFinite(Number(value)) ? Math.max(0,Math.min(100,Math.round(Number(value)))) : 100;
const vwBool = (value, defaultValue=true) => value === undefined ? defaultValue : value !== false;
class ViwacoOverviewCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this._meters = null;
    this._busy = false;
    this._mode = 'month';
    this._showPrivate = false;
    this._meterId = '*';
    this._year = null;
    this._loadPromise = null;
    this._connectedTimer = null;
  }
  setConfig(config) {
    if (!config || typeof config !== 'object') throw new Error('Invalid VIWACO card configuration');
    this._config = { ...config };
    // Empty or * means all meters. Retain interactive selection unless the
    // persisted customer_id changed in the editor.
    const configuredId = String(config.customer_id || '*');
    if (this._initialConfigMeter !== configuredId) {
      this._meterId = configuredId;
      this._initialConfigMeter = configuredId;
    }
    this._render();
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._meters && !this._loadPromise) this._load();
  }
  static getStubConfig() { return {palette:'ocean',background_opacity:100,show_customer:true,show_history:true,compact_mobile:true}; }
  static getConfigElement() { return document.createElement('viwaco-overview-card-editor'); }
  getCardSize() { return 13; }
  getGridOptions() { return {columns: 12, min_columns: 12, rows:'auto'}; }
  connectedCallback() {
    if (!this._connectedTimer) this._connectedTimer = setInterval(() => this._load(), 120000);
  }
  disconnectedCallback() {
    if (this._connectedTimer) clearInterval(this._connectedTimer);
    this._connectedTimer = null;
  }
  async _load() {
    if (!this._hass || this._loadPromise) return;
    this._loadPromise = this._hass.callWS({type:'viwaco_reader/history'});
    try {
      this._meters = await this._loadPromise;
      this._error = null;
    } catch(error) {
      this._error = 'Không lấy được lịch sử từ VIWACO Reader. Kiểm tra integration và quyền truy cập.';
    } finally {
      this._loadPromise = null;
      this._render();
    }
  }
  _allRecords() {
    const selected = (this._meters || []).filter(m => this._meterId === '*' || m.customer_id === this._meterId);
    const index = new Map();
    for (const meter of selected) for (const invoice of meter.invoices || []) {
      const key = periodKey(invoice.period);
      let r = index.get(key);
      if (!r) { r = {key, period:invoice.period, usage:0, total:0, paid:0, due:0, payment_date:null, invoice_url:null}; index.set(key,r); }
      r.usage += amount(invoice.usage_m3);
      r.total += amount(invoice.total_vnd);
      r.paid += amount(invoice.paid_vnd);
      r.due += Math.max(0, amount(invoice.total_vnd)-amount(invoice.paid_vnd));
      if (this._meterId !== '*') { r.payment_date = invoice.payment_date; r.invoice_url = trustedBillUrl(invoice.invoice_url); }
    }
    return Array.from(index.values()).sort((a,b) => a.key.localeCompare(b.key));
  }
  _years(rows) { return [...new Set(rows.map(r => Number(r.key.slice(0,4))))].sort((a,b)=>b-a); }
  _annual(rows) {
    const map = new Map();
    rows.forEach(r => {
      const y = +r.key.slice(0,4);
      if (!map.has(y)) map.set(y, {year:y, usage:0,total:0,paid:0,due:0,months:0});
      const a = map.get(y); a.usage+=r.usage; a.total+=r.total; a.paid+=r.paid; a.due+=r.due; a.months++;
    });
    return [...map.values()].sort((a,b) => a.year-b.year);
  }
  _bars(items, key, unit, kind) {
    const max = Math.max(1, ...items.map(i=>amount(i[key])));
    if (!items.length) return '<div class="no-data">Chưa có dữ liệu</div>';
    return `<div class="chart-scroll" tabindex="0" aria-label="Biểu đồ ${key==='usage'?'lượng nước':'tiền nước'}, cuộn ngang trên điện thoại"><div class="bars ${kind}">${items.map(i=>{
      const val = amount(i[key]);
      const label = i.month !== undefined ? `T${i.month}` : String(i.year);
      const ratio = Math.max(1, Math.round(val / max * 100));
      const display = key === 'usage' ? `${num(val)} m³` : money(val);
      return `<div class="bar-wrap" title="${E(label + ': ' + display)}"><span class="bar-val">${key==='usage'?num(val):num(Math.round(val/1000))}</span><div class="bar-rail"><div class="bar" style="height:${ratio}%"></div></div><span class="bar-label">${E(label)}</span></div>`;
    }).join('')}</div></div><div class="axis-note">${E(unit)} · Vuốt ngang để xem đủ các kỳ trên điện thoại</div>`;
  }
  _render() {
    if (!this.shadowRoot) return;
    const rows = this._allRecords();
    const years = this._years(rows);
    if (!years.includes(this._year)) this._year = years[0] ?? new Date().getFullYear();
    const year = this._year;
    const ym = rows.filter(r => r.key.startsWith(`${year}-`));
    const yearData = new Map(ym.map(r=>[+r.key.slice(5),r]));
    const months = Array.from({length:12},(_,idx)=>({month:idx+1, ...(yearData.get(idx+1) || {usage:0,total:0,paid:0,due:0})}));
    const annual = this._annual(rows);
    const graphItems = this._mode==='month' ? months : annual.slice(-8);
    const selectedMeters = (this._meters||[]).filter(m=>this._meterId==='*'||m.customer_id===this._meterId);
    const summary = ym.reduce((s,r)=>({usage:s.usage+r.usage,total:s.total+r.total,paid:s.paid+r.paid,due:s.due+r.due,months:s.months+1}),{usage:0,total:0,paid:0,due:0,months:0});
    const previous = annual.find(a=>a.year===year-1);
    const delta = previous?.usage ? (summary.usage-previous.usage)/previous.usage*100 : null;
    const current = selectedMeters.map(m=>({meter:m,reading:(m.readings||[])[0],invoice:(m.invoices||[])[0]}));
    const recentRows = selectedMeters.flatMap(m => (m.recent_months||[]).map(r => ({...r, name:m.name, customer_id:m.customer_id})));
    const customerErrors = selectedMeters.filter(m=>m.last_error);
    const healthLabels = {valid:'Phiên hợp lệ', cached:'Dữ liệu cache', offline:'Mất kết nối', expired:'Cookie hết hạn', initializing:'Đang khởi tạo'};
    const monthBills = ym.slice().reverse();
    const heroTitle = this._config?.title?.trim() || (this._meterId === '*' ? 'Tổng quan tất cả đồng hồ' : (selectedMeters[0]?.name || 'Đồng hồ nước'));
    const palette = VW_PALETTES[this._config?.palette] || VW_PALETTES.ocean;
    const opacity = vwOpacity(this._config?.background_opacity);
    const showCustomer = vwBool(this._config?.show_customer);
    const showHistory = vwBool(this._config?.show_history);
    const compactMobile = vwBool(this._config?.compact_mobile);
    const allInvoiceRows = selectedMeters.flatMap(m => {
      const readings = new Map((m.readings || []).map(r => [r.period, r]));
      return (m.invoices || []).map(inv => ({meter:m, inv, reading:readings.get(inv.period), archive:inv.archive || {}}));
    }).sort((a,b) => periodKey(b.inv.period).localeCompare(periodKey(a.inv.period)));
    const totalArchived = selectedMeters.reduce((n,m)=>n + Number(m.archived_months || 0), 0);
    const syncing = selectedMeters.filter(m=>m.archive_status?.running);
    const archiveSummary = syncing.length ? syncing.map(m=>`${E(m.name)}: ${num(m.archive_status.done)} / ${num(m.archive_status.total)} kỳ`).join(' · ') : `${num(totalArchived)} kỳ đã có thông tin lưu trữ`;
    const historyRowsHtml = allInvoiceRows.map(({meter,inv,reading,archive}) => {
      const d = archive.details || {};
      const pdf = trustedArchiveUrl(archive.pdf_url);
      const png = trustedArchiveUrl(archive.png_urls?.[0]);
      const detail = d.total_vnd !== undefined ? `<details class="invoice-details"><summary>Xem</summary>
         <div><b>Tiền nước trước thuế:</b> ${d.water_charge_vnd==null?'—':money(d.water_charge_vnd)}</div>
         <div><b>Phí BVMT (${E(d.environment_fee_rate_percent || '—')}%):</b> ${d.environment_fee_vnd==null?'—':money(d.environment_fee_vnd)}</div>
         <div><b>VAT (${E(d.vat_rate_percent || '—')}%):</b> ${d.vat_vnd==null?'—':money(d.vat_vnd)}</div>
         <div><b>Tiền đồng hồ:</b> ${d.meter_charge_vnd==null?'—':money(d.meter_charge_vnd)}</div>
         <div><b>Giảm trừ:</b> ${d.discount_vnd==null?'—':money(d.discount_vnd)}</div>
         <div><b>Hóa đơn phát hành:</b> ${E(d.invoice_date || '—')}</div>
         <div><b>Tình trạng phát hành:</b> ${E(d.invoice_status || '—')}</div>
         ${(d.tariffs || []).map(t=>`<div><b>${E(t.tariff)}:</b> ${num(t.quantity_m3)} m³ × ${money(t.unit_price_vnd)} = ${money(t.amount_vnd)}</div>`).join('')}
        </details>` : '<span class="muted">Chưa tải chi tiết</span>';
      return `<tr>${this._meterId==='*'?`<td>${E(meter.name)}</td>`:''}
        <td><b>${E(inv.period)}</b></td><td>${num(inv.usage_m3)} m³</td>
        <td>${reading?num(reading.previous_m3):'—'}</td><td>${reading?num(reading.current_m3):'—'}</td>
        <td><b>${money(inv.total_vnd)}</b></td><td>${money(inv.paid_vnd)}</td>
        <td>${E(inv.payment_date||'—')}</td><td>${detail}</td>
        <td>${pdf?`<a class="link" href="${E(pdf)}" target="_blank" rel="noopener noreferrer">PDF ↗</a>`:'—'}</td>
        <td>${png?`<a class="link" href="${E(png)}" target="_blank" rel="noopener noreferrer">PNG ↗</a>`:'—'}</td>
        <td>${trustedBillUrl(inv.invoice_url)?`<a class="link" href="${E(trustedBillUrl(inv.invoice_url))}" target="_blank" rel="noopener noreferrer">VIWACO ↗</a>`:'—'}</td></tr>`;
    }).join('');
    const opts = `<option value="*" ${this._meterId==='*'?'selected':''}>Tất cả đồng hồ</option>`+(this._meters||[]).map(m=>`<option value="${E(m.customer_id)}" ${m.customer_id===this._meterId?'selected':''}>${E(m.name)} · ${E(m.customer_id)}</option>`).join('');
    const yearsOpt = years.map(y=>`<option value="${y}" ${y===year?'selected':''}>Năm ${y}</option>`).join('');
    this.shadowRoot.innerHTML = `
<style>
:host { --vw-hero1:${palette.colors[0]}; --vw-hero2:${palette.colors[1]}; --vw-hero3:${palette.colors[2]}; --vw-blue:${palette.colors[3]}; --vw-teal:${palette.colors[4]}; --vw-surface-opacity:${opacity}%; --vw-hero-font:${opacity<40?'var(--primary-text-color,#e4effb)':'#ffffff'}; }

:host{display:block;min-width:0;font-family:inherit;color:var(--primary-text-color,#172b4d);--vw-ink:#1c3150;--vw-purple:#7473ee;--vw-card:var(--card-background-color,#fff)}
ha-card{display:block;min-width:0;container-type:inline-size;overflow:hidden;border-radius:20px;padding:0;background:color-mix(in srgb,var(--vw-card) var(--vw-surface-opacity),transparent);border:1px solid color-mix(in srgb,var(--divider-color,#dce5ef) var(--vw-surface-opacity),transparent);box-shadow:0 10px 30px rgba(13,46,89,.05)}
*{box-sizing:border-box}.pad{padding:24px}.hero{position:relative;background:linear-gradient(115deg,color-mix(in srgb,var(--vw-hero1) var(--vw-surface-opacity),transparent),color-mix(in srgb,var(--vw-hero2) var(--vw-surface-opacity),transparent) 55%,color-mix(in srgb,var(--vw-hero3) var(--vw-surface-opacity),transparent));color:var(--vw-hero-font);padding:28px 28px 31px;overflow:hidden}.hero:after{content:"";position:absolute;width:410px;height:410px;border:1px solid rgba(255,255,255,.09);border-radius:50%;right:-100px;top:-220px;box-shadow:0 0 0 70px rgba(255,255,255,.025),0 0 0 150px rgba(255,255,255,.02)}
.topline{position:relative;z-index:1;display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap}.brand{display:flex;align-items:center;gap:12px}.brand img{width:51px;height:51px;object-fit:contain;background:rgba(255,255,255,.12);border-radius:17px;padding:5px}.supertitle{font-size:10px;letter-spacing:2.4px;text-transform:uppercase;color:var(--vw-hero-font);opacity:.85;font-weight:800}.hero h1{margin:4px 0;font-size:clamp(21px,3vw,30px);font-weight:850;letter-spacing:-.7px}.hero .small{color:var(--vw-hero-font);opacity:.85;font-size:12px}.top-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button,select{font:inherit}.transparent-btn{background:rgba(255,255,255,.11);border:1px solid rgba(255,255,255,.23);color:var(--vw-hero-font);border-radius:12px;padding:9px 13px;font-size:13px;cursor:pointer}.transparent-btn:hover{background:rgba(255,255,255,.22)}.solid-btn{border:none;background:white;color:#134c77;font-weight:800;border-radius:12px;padding:10px 14px;font-size:12px;cursor:pointer;text-decoration:none}.header-caption{position:relative;z-index:1;margin:15px 0 0;font-size:12px;color:var(--vw-hero-font);opacity:.85}
.filters{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:19px}.control-set{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.control-set select{background:var(--card-background-color,#fff);color:var(--primary-text-color,#243b57);border:1px solid var(--divider-color,#d6dfe7);border-radius:11px;padding:10px 12px;max-width:320px;font-size:13px}.seg{display:flex;gap:3px;padding:4px;background:var(--secondary-background-color,#eef3f9);border-radius:12px}.seg button{border:none;background:transparent;color:var(--secondary-text-color,#73829d);font-weight:750;font-size:12px;padding:8px 13px;border-radius:9px;cursor:pointer}.seg button.active{background:var(--card-background-color,#fff);color:var(--primary-text-color,#182e4d);box-shadow:0 2px 7px rgba(20,55,90,.10)}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:24px}.kpi{border:1px solid var(--divider-color,#e4eaf1);background:color-mix(in srgb,var(--secondary-background-color,#f8fafc) var(--vw-surface-opacity),transparent);padding:19px 17px;border-radius:17px;min-width:0}.kpi:nth-child(1){background:linear-gradient(145deg,rgba(32,140,255,.12),rgba(35,161,255,.025));border-color:rgba(32,140,255,.20)}.kpi:nth-child(2){background:linear-gradient(145deg,rgba(2,191,168,.12),rgba(2,191,168,.025));border-color:rgba(2,191,168,.19)}.kpi:nth-child(3){background:linear-gradient(145deg,rgba(116,115,238,.10),rgba(116,115,238,.02));border-color:rgba(116,115,238,.17)}.kpi:nth-child(4){background:linear-gradient(145deg,rgba(249,169,44,.13),rgba(249,169,44,.02));border-color:rgba(249,169,44,.20)}
.kpi .mini{font-size:11px;color:var(--secondary-text-color,#637792);font-weight:750}.kpi b{display:block;font-weight:850;letter-spacing:-.4px;font-size:clamp(19px,2.5cqi,29px);line-height:1.3;white-space:normal;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.kpi small{font-size:11px;color:var(--secondary-text-color,#8694a5)}.kpi .mini-mark{display:inline-flex;width:29px;height:29px;border-radius:10px;justify-content:center;align-items:center;margin-bottom:9px;background:rgba(40,135,255,.12);color:#1989ed;font-size:16px}.kpi:nth-child(2) .mini-mark{color:#04aa94;background:rgba(2,191,168,.14)}.kpi:nth-child(3) .mini-mark{color:#7675ea;background:rgba(116,115,238,.13)}.kpi:nth-child(4) .mini-mark{color:#cf8a1e;background:rgba(249,169,44,.16)}
.block{margin:18px 0 24px}.section-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:13px;flex-wrap:wrap}.section-head h2{font-size:16px;font-weight:850;letter-spacing:-.25px;margin:0}.section-head span{font-size:11px;color:var(--secondary-text-color,#8695aa)}.graph-row{display:grid;grid-template-columns:1fr 1fr;gap:13px}.graph{border:1px solid var(--divider-color,#e1e8f0);border-radius:17px;padding:17px 17px 13px;min-width:0}.graph-heading{font-size:12px;font-weight:780;display:flex;align-items:center;gap:7px}.dot{width:10px;height:10px;border-radius:50%;display:inline-block;background:var(--vw-blue)}.teal .dot{background:var(--vw-teal)}.bars{height:167px;display:flex;align-items:end;gap:7px;border-bottom:1px solid var(--divider-color,#e2e8f0);padding:19px 3px 0;margin-top:5px}.bar-wrap{flex:1;min-width:0;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:5px}.bar-val{font-size:9px;color:var(--secondary-text-color,#758499);white-space:nowrap;max-width:100%;overflow:hidden}.bar-rail{height:109px;display:flex;width:100%;align-items:end;justify-content:center}.bar{width:72%;min-width:5px;max-width:28px;border-radius:5px 5px 0 0;background:linear-gradient(180deg,color-mix(in srgb,var(--vw-blue),white 38%),var(--vw-blue));transition:height .25s ease}.teal .bar{background:linear-gradient(180deg,color-mix(in srgb,var(--vw-teal),white 38%),var(--vw-teal))}.bar-label{font-size:10px;color:var(--secondary-text-color,#748398);padding:5px 0 3px}.axis-note{text-align:right;font-size:10px;margin-top:8px;color:var(--secondary-text-color,#9aa7b6)}
.meters{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.meter{background:color-mix(in srgb,var(--secondary-background-color,#f8fafc) var(--vw-surface-opacity),transparent);border:1px solid var(--divider-color,#e2e8f1);border-radius:16px;padding:16px;min-width:0}.meter-head{display:flex;align-items:center;justify-content:space-between;gap:5px}.meter-head strong{font-size:13px}.pill{font-size:10px;color:#008d72;border:1px solid rgba(0,188,143,.24);background:rgba(0,190,142,.1);padding:4px 8px;border-radius:20px}.pill.off{color:#d17e28;background:rgba(255,163,34,.09);border-color:rgba(255,163,34,.2)}.meter-sub{font-size:10px;color:var(--secondary-text-color,#7b8ca5);margin-top:4px}.meter-reading{font-size:24px;font-weight:850;margin:13px 0 3px;color:var(--primary-text-color,#182f4e)}.meter-reading small{font-size:12px;font-weight:450;color:var(--secondary-text-color,#8794a5)}.meter-line{display:flex;justify-content:space-between;gap:8px;font-size:11px;margin-top:8px}.meter-line span{color:var(--secondary-text-color,#71839b)}
.table-scroll{overflow:auto;max-width:100%;-webkit-overflow-scrolling:touch;scrollbar-width:thin;border:1px solid var(--divider-color,#e2e8ef);border-radius:14px}table{border-collapse:collapse;width:100%;font-size:12px;white-space:nowrap}th{background:var(--secondary-background-color,#f5f8fb);color:var(--secondary-text-color,#73829b);text-align:left;padding:12px 13px;font-size:11px}td{padding:12px 13px;border-top:1px solid var(--divider-color,#edf1f5)}th:nth-child(n+2),td:nth-child(n+2){text-align:right}td b{font-weight:790}a.link{color:var(--info-color,#1b89da);text-decoration:none}.yearly td:first-child{font-weight:750}.no-data{padding:25px;color:var(--secondary-text-color,#7d8996);text-align:center}.error{padding:14px;border-radius:12px;background:rgba(244,97,69,.07);color:#bd4a41;margin-bottom:15px}.customer-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.customer-card{border:1px solid var(--divider-color,#e2e8ef);background:color-mix(in srgb,var(--secondary-background-color,#f7fafc) var(--vw-surface-opacity),transparent);border-radius:16px;padding:17px;min-width:0}.customer-header{font-size:14px;font-weight:850;margin:0 0 12px}.customer-grid{display:grid;grid-template-columns:minmax(110px,.5fr) minmax(0,1fr);gap:10px;font-size:12px}.customer-grid .key{color:var(--secondary-text-color,#73829b)}.customer-grid .val{font-weight:650;min-width:0;overflow-wrap:anywhere}.privacy-btn{border:1px solid var(--divider-color,#d5e2ee);border-radius:10px;padding:8px 12px;font-size:12px;background:var(--secondary-background-color,#eff5fa);color:var(--primary-text-color,#243650);cursor:pointer}.history-table{max-height:590px;overflow:auto;border-radius:14px;border:1px solid var(--divider-color,#ddd)}.history-table thead th{position:sticky;top:0;z-index:2;background:var(--card-background-color,#fff)}.invoice-details{min-width:125px;max-width:250px;line-height:1.8}.invoice-details summary{color:var(--primary-color,#2388c4);cursor:pointer;font-weight:750}.invoice-details b{font-weight:600}.muted{opacity:.55}.archive-tools{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px}.archive-btn{border:1px solid var(--divider-color,#ddd);border-radius:11px;padding:9px 12px;background:var(--secondary-background-color,#f3f7fb);color:var(--primary-text-color,#163455);cursor:pointer;font-weight:700;font-size:12px}.archive-btn:hover{filter:brightness(.96)}.archive-note{font-size:11px;opacity:.76;line-height:1.6}.footer{margin-top:13px;color:var(--secondary-text-color,#8d9aaa);font-size:10px;line-height:1.6}.empty{padding:35px 10px;text-align:center;color:var(--secondary-text-color,#718198)}
/* Container queries respond to the actual card width, including HA Sections
   and the editor preview, rather than only the browser viewport. */
.chart-scroll{max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:thin}.chart-scroll:focus-visible{outline:2px solid var(--vw-blue)}
.recent-mobile{display:none}.recent-mini{background:color-mix(in srgb,var(--secondary-background-color,#edf3f9) var(--vw-surface-opacity),transparent);border:1px solid var(--divider-color,#dce5ef);border-radius:14px;padding:14px}.recent-mini-top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px}.recent-mini-top b{font-size:15px}.recent-mini-top span{font-size:11px;color:var(--secondary-text-color,#73829b)}.recent-mini-stats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.recent-mini-stats div{min-width:0}.recent-mini-stats small{display:block;color:var(--secondary-text-color,#77869b);font-size:11px}.recent-mini-stats strong{display:block;font-size:15px;overflow-wrap:anywhere;line-height:1.45}
@container(max-width:850px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.meters{grid-template-columns:repeat(2,minmax(0,1fr))}.customer-list{grid-template-columns:1fr}.graph-row{grid-template-columns:1fr}}
@container(max-width:560px){.pad{padding:14px}.hero{padding:20px 15px 23px}.topline{align-items:flex-start}.top-actions{width:100%;display:grid;grid-template-columns:1fr 1fr}.top-actions button,.top-actions a{width:100%;min-width:0;text-align:center;padding:11px 8px;font-size:11px}.brand img{width:42px;height:42px;border-radius:12px}.hero h1{font-size:clamp(19px,5cqi,25px);line-height:1.2;letter-spacing:0}.supertitle{font-size:9px;letter-spacing:1.5px}.filters{flex-direction:column;align-items:stretch}.control-set{display:grid;grid-template-columns:minmax(0,1fr) auto;width:100%}.control-set select{min-width:0;max-width:100%;width:100%;padding:10px 6px}.seg{width:100%}.seg button{flex:1}.kpis{gap:8px;margin-bottom:18px}.kpi{padding:13px 11px;border-radius:13px}.kpi b{font-size:clamp(18px,4.4cqi,24px);margin:6px 0}.kpi .mini{font-size:10px;line-height:1.4;min-height:27px}.kpi small{font-size:10px;line-height:1.4;display:block}.kpi .mini-mark{width:24px;height:24px;margin-bottom:5px}.block{margin:17px 0 21px}.section-head h2{font-size:14px}.section-head span{font-size:10px}.graph{padding:13px 11px}.bars{min-width:570px;gap:8px}.bars .bar-val{font-size:10px}.bars .bar-label{font-size:11px}.meter{padding:14px}.meters{grid-template-columns:1fr}.meter-line{font-size:12px}.customer-grid{grid-template-columns:minmax(100px,.65fr) minmax(0,1fr)}.recent-mobile{display:grid;grid-template-columns:1fr;gap:9px}.recent-desktop{display:none}.footer{font-size:10px}.archive-tools button{flex:1}.archive-note{overflow-wrap:anywhere}table{font-size:12px}th,td{padding:11px 10px}.history-table{max-height:450px}}
@container(max-width:560px){.mobile-full .recent-mobile{display:none}.mobile-full .recent-desktop{display:block}}
@container(max-width:350px){.kpis{grid-template-columns:1fr}.kpi .mini{min-height:0}.top-actions{grid-template-columns:1fr}.control-set{grid-template-columns:1fr}.customer-grid{grid-template-columns:1fr;gap:3px}.customer-grid .val{margin-bottom:8px}}
</style>
<ha-card class="${compactMobile?'mobile-compact':'mobile-full'}">
<div class="hero"><div class="topline"><div class="brand"><img src="/viwaco_reader/icon.png" alt=""/><div><div class="supertitle">VIWACO • WATER ANALYTICS</div><h1>${E(heroTitle)}</h1><div class="small">Trực quan hóa chỉ số, lượng nước và chi phí · không theo thời gian thực</div></div></div><div class="top-actions"><button class="transparent-btn" id="reload">↻ Cập nhật</button><a class="solid-btn" href="/config/integrations/integration/viwaco_reader">⚙ Quản lý đồng hồ ↗</a></div></div><div class="header-caption">${selectedMeters.length} đồng hồ đang xem · ${summary.months} kỳ hóa đơn trong năm ${year} · Phạm vi dữ liệu: ${selectedMeters.length===1 ? (selectedMeters[0].history_all ? `Tất cả (${selectedMeters[0].history_available_months || "?"} tháng nguồn)` : `${selectedMeters[0].history_months} tháng gần nhất`) : "Theo cấu hình từng đồng hồ"}</div></div>
<div class="pad">
${this._error ? `<div class="error">${E(this._error)}</div>`:''}
${customerErrors.length ? `<div class="error"><strong>Cảnh báo đồng bộ:</strong> ${customerErrors.map(m=>`${E(m.name)} (${E(m.customer_id)}): ${E(m.last_error)}`).join(' • ')}. Xem Thông báo của Home Assistant và System → Logs.</div>` : ''}
<div class="filters"><div class="control-set"><select id="meter" aria-label="Chọn đồng hồ">${opts}</select><select id="year" aria-label="Chọn năm">${yearsOpt || `<option>${year}</option>`}</select></div><div class="seg"><button id="monthly" class="${this._mode==='month'?'active':''}">Theo tháng</button><button id="yearly" class="${this._mode==='year'?'active':''}">Theo năm</button></div></div>
${!this._meters?.length ? `<div class="empty">Chưa có đồng hồ VIWACO. Vào Settings → Devices & services → Add integration để thêm mã khách hàng.</div>` : `
<div class="kpis">
  <div class="kpi"><span class="mini-mark">💧</span><div class="mini">TIÊU THỤ NĂM ${year}</div><b>${num(summary.usage)} <small>m³</small></b><small>${delta===null?'Tổng nước các kỳ trong năm':`${delta>=0?'Tăng':'Giảm'} ${Math.abs(delta).toFixed(1)}% so với năm trước`}</small></div>
  <div class="kpi"><span class="mini-mark">₫</span><div class="mini">TỔNG TIỀN NĂM ${year}</div><b>${num(summary.total)} <small>đ</small></b><small>${summary.months} kỳ đã có hóa đơn</small></div>
  <div class="kpi"><span class="mini-mark">✓</span><div class="mini">ĐÃ THANH TOÁN THEO BẢNG</div><b>${num(summary.paid)} <small>đ</small></b><small>Ghi nhận trên Invoice.aspx</small></div>
  <div class="kpi"><span class="mini-mark">! </span><div class="mini">CHÊNH LỆCH CHƯA TRẢ</div><b>${num(summary.due)} <small>đ</small></b><small>Không thay thế tra cứu công nợ</small></div>
</div>
<div class="block"><div class="section-head"><h2>${this._mode==='month'?'So sánh theo tháng • '+year:'So sánh theo năm'}</h2><span>Nước và tiền dùng trục tỷ lệ riêng</span></div>
<div class="graph-row"><div class="graph"><div class="graph-heading"><i class="dot"></i> Lượng nước tiêu thụ (m³)</div>${this._bars(graphItems,'usage','m³','blue')}</div><div class="graph teal"><div class="graph-heading"><i class="dot"></i> Tiền nước (nghìn đồng)</div>${this._bars(graphItems,'total','nghìn đồng','teal')}</div></div></div>
<div class="block"><div class="section-head"><h2>3 kỳ hóa đơn gần nhất</h2><span>Dữ liệu theo kỳ hóa đơn, chỉ số khớp tháng</span></div>
<div class="recent-mobile">${recentRows.length?recentRows.map(r=>`<article class="recent-mini"><div class="recent-mini-top"><b>${E(r.period)}</b><span>${E(r.name)}</span></div><div class="recent-mini-stats"><div><small>Nước đã dùng</small><strong>${num(r.usage_m3)} m³</strong></div><div><small>Tiền nước</small><strong>${money(r.total_vnd)}</strong></div><div><small>Chỉ số trước</small><strong>${r.previous_m3==null?'—':num(r.previous_m3)+' m³'}</strong></div><div><small>Chỉ số sau</small><strong>${r.current_m3==null?'—':num(r.current_m3)+' m³'}</strong></div></div></article>`).join(''):'Chưa có dữ liệu'}</div><div class="table-scroll recent-desktop"><table><thead><tr>${this._meterId==='*'?'<th>Đồng hồ</th>':''}<th>Tháng</th><th>Tiêu thụ</th><th>Tiền nước</th><th>Chỉ số trước</th><th>Chỉ số sau</th></tr></thead><tbody>${recentRows.length?recentRows.map(r=>`<tr>${this._meterId==='*'?`<td>${E(r.name)}</td>`:''}<td><b>${E(r.period)}</b></td><td>${num(r.usage_m3)} m³</td><td>${money(r.total_vnd)}</td><td>${r.previous_m3===null?'—':num(r.previous_m3)+' m³'}</td><td>${r.current_m3===null?'—':num(r.current_m3)+' m³'}</td></tr>`).join(''):`<tr><td colspan="6">Chưa có dữ liệu</td></tr>`}</tbody></table></div></div>
<div class="block"><div class="section-head"><h2>Chỉ số đồng hồ gần nhất</h2><span>Giá trị ghi theo ngày đọc cuối cùng</span></div><div class="meters">${current.map(({meter,reading,invoice})=>`
<div class="meter"><div class="meter-head"><strong>${E(meter.name)}</strong><span class="pill ${meter.available?'':'off'}">${meter.available?'Đã đồng bộ':'Chưa cập nhật'}</span></div><div class="meter-sub">KH ${E(meter.customer_id)} · ${E(meter.meter_serial || 'Chưa có serial')}</div><div class="meter-reading">${reading?num(reading.current_m3):'—'} <small>m³</small></div><div class="meter-line"><span>Ngày đọc</span><b>${E(reading?.read_date||'—')}</b></div><div class="meter-line"><span>Tiêu thụ kỳ mới nhất</span><b>${reading?num(reading.usage_m3)+' m³':'—'}</b></div><div class="meter-line"><span>Hóa đơn gần nhất</span><b>${invoice?money(invoice.total_vnd):'—'}</b></div><div class="meter-line"><span>Hóa đơn điện tử</span>${trustedBillUrl(invoice?.invoice_url) ? `<a class="link" target="_blank" rel="noopener noreferrer" href="${E(trustedBillUrl(invoice.invoice_url))}">Xem hóa đơn ↗</a>` : `<b>—</b>`}</div></div>`).join('')}</div></div>
${showCustomer ? `<div class="block"><div class="section-head"><h2>Hồ sơ khách hàng</h2><button class="privacy-btn" id="private-toggle" type="button">${this._showPrivate?'Ẩn địa chỉ và số điện thoại':'Hiện địa chỉ và số điện thoại'}</button></div><div class="customer-list">${selectedMeters.map(m=>{
const c=m.customer||{};
const fields=[
  ['Mã khách hàng', c.customer_id||m.customer_id],
  ['Tên khách hàng', c.name||'Chưa có dữ liệu'],
  ['Địa chỉ sử dụng nước', this._showPrivate ? (c.address||'Chưa có dữ liệu') : 'Đang ẩn trên màn hình'],
  ['Số điện thoại', this._showPrivate ? (c.phone||'Chưa có dữ liệu') : 'Đang ẩn trên màn hình'],
  ['Đơn vị cấp nước', 'Công ty Cổ phần VIWACO'],
  ['Serial / loại đồng hồ', m.meter_serial||'Chưa có dữ liệu'],
  ['Sổ đọc',m.reading_book||'Chưa có dữ liệu'],
  ['Kỳ hóa đơn gần nhất',m.invoices?.[0]?.period||'Chưa có dữ liệu'],
];
return `<div class="customer-card"><div class="customer-header">${E(m.name)} · ${E(c.name||'Chưa có tên khách hàng')}</div><div class="customer-grid">${fields.map(([label,value])=>`<span class="key">${E(label)}</span><span class="val">${E(value)}</span>`).join('')}</div></div>`;
}).join('')}</div><div class="footer">Địa chỉ và số điện thoại có thể được ẩn để tránh lộ trên màn hình dùng chung. Người dùng có quyền truy cập Home Assistant phù hợp vẫn có thể đọc dữ liệu qua các entity và WebSocket.</div></div>` : ''}
<div class="block"><div class="section-head"><h2>Chi tiết hóa đơn theo tháng · ${year}</h2><span>${monthBills.length} kỳ hóa đơn</span></div><div class="table-scroll"><table><thead><tr><th>Kỳ</th><th>Nước (m³)</th><th>Tiền nước</th><th>Đã trả</th><th>Còn lại*</th><th>Đã trả ngày</th><th>Hóa đơn ĐT</th></tr></thead><tbody>${monthBills.length?monthBills.map(r=>`<tr><td><b>${E(r.period)}</b></td><td>${num(r.usage)}</td><td><b>${money(r.total)}</b></td><td>${money(r.paid)}</td><td>${money(r.due)}</td><td>${E(r.payment_date||"—")}</td><td>${r.invoice_url?`<a class="link" target="_blank" rel="noopener noreferrer" href="${E(r.invoice_url)}">Xem ↗</a>`:"—"}</td></tr>`).join(''):`<tr><td colspan="7" class="no-data">Chưa có hóa đơn trong năm này</td></tr>`}</tbody></table></div></div>
${showHistory ? `<div class="block"><div class="section-head"><h2>Toàn bộ lịch sử đồng hồ và hóa đơn</h2><span>${allInvoiceRows.length} kỳ · tất cả các năm</span></div>
<div class="archive-tools"><button class="archive-btn" id="syncdetails">↻ Đọc chi tiết mọi kỳ</button><button class="archive-btn" id="syncfiles">⬇ Lưu toàn bộ PDF + PNG</button><span class="archive-note">${archiveSummary}</span></div>
<div class="archive-note" style="margin:12px 0">Dữ liệu cơ bản hiển thị đầy đủ từ lịch sử VIWACO. Cột chi tiết và tệp PDF/PNG chỉ xuất hiện sau khi tải lưu trữ. File trong /local có thể xem mà không cần đăng nhập Home Assistant.</div>
<div class="history-table table-scroll"><table><thead><tr>${this._meterId==='*'?'<th>Đồng hồ</th>':''}<th>Kỳ</th><th>Nước</th><th>Chỉ số trước</th><th>Chỉ số sau</th><th>Tiền</th><th>Thanh toán</th><th>Ngày trả</th><th>Phí/thuế/định mức</th><th>PDF</th><th>PNG</th><th>Web</th></tr></thead><tbody>${historyRowsHtml || '<tr><td>Chưa có dữ liệu</td></tr>'}</tbody></table></div></div>
` : ''}
<div class="block"><div class="section-head"><h2>Tổng hợp theo năm</h2><span>So sánh dài hạn</span></div><div class="table-scroll"><table class="yearly"><thead><tr><th>Năm</th><th>Số kỳ</th><th>Nước (m³)</th><th>Tiền nước</th><th>Đã trả</th><th>Còn lại*</th></tr></thead><tbody>${annual.slice().reverse().map(a=>`<tr><td>${a.year}</td><td>${a.months}</td><td><b>${num(a.usage)}</b></td><td><b>${money(a.total)}</b></td><td>${money(a.paid)}</td><td>${money(a.due)}</td></tr>`).join('')}</tbody></table></div></div>
<div class="footer">* "Còn lại" = max(0, tiền hóa đơn − tiền đã thanh toán) theo từng kỳ; không phải số liệu công nợ chính thức của VIWACO. Dữ liệu lấy từ kỳ đã ghi số/hóa đơn; không phải đồng hồ thông minh đo liên tục. Biểu đồ tính từ lịch sử thực tế, không nhân số kỳ chưa có hóa đơn để ước tính.</div>`}
</div>
</ha-card>`;
    this.shadowRoot.querySelector('#private-toggle')?.addEventListener('click',()=>{this._showPrivate=!this._showPrivate;this._render();});
    this.shadowRoot.querySelector('#meter')?.addEventListener('change',ev=>{this._meterId=ev.target.value;this._render();});
    this.shadowRoot.querySelector('#year')?.addEventListener('change',ev=>{this._year=+ev.target.value;this._render();});
    this.shadowRoot.querySelector('#monthly')?.addEventListener('click',()=>{this._mode='month';this._render();});
    this.shadowRoot.querySelector('#yearly')?.addEventListener('click',()=>{this._mode='year';this._render();});
    const archiveAction = async (mode) => {
      if (!this._hass || this._busy) return;
      const selected = this._meterId==='*' ? 'tất cả đồng hồ' : `đồng hồ ${this._meterId}`;
      const text = mode === 'both' ? `Lưu PDF và PNG của TẤT CẢ các kỳ đã có cho ${selected}? File có thể rất lớn, và /local không yêu cầu đăng nhập.` : `Đọc chi tiết mọi kỳ hóa đơn của ${selected}? (Không tạo file công khai)`;
      if (!window.confirm(text)) return;
      this._busy = true;
      try {
        const data = {mode, year:0, max_invoices:0, overwrite:false};
        if (this._meterId !== '*') data.customer_id = this._meterId;
        await this._hass.callService('viwaco_reader','archive_invoices',data);
        this._error = `Đã gửi yêu cầu lưu trữ ${selected}. Tiến độ cập nhật trên trang; xem thêm Thông báo trong Home Assistant.`;
        await this._load();
        setTimeout(()=>this._load(),5000);
      } catch (err) { this._error = 'Không khởi động được tải hóa đơn: kiểm tra System → Logs.'; this._render(); }
      finally { this._busy = false; }
    };
    this.shadowRoot.querySelector('#syncdetails')?.addEventListener('click',()=>archiveAction('details'));
    this.shadowRoot.querySelector('#syncfiles')?.addEventListener('click',()=>archiveAction('both'));
    this.shadowRoot.querySelector('#reload')?.addEventListener('click',async(ev)=>{
      if (this._busy || !this._hass) return;
      this._busy=true; ev.currentTarget.textContent='Đang cập nhật…';
      try {
        const data = this._meterId==='*'?{}:{customer_id:this._meterId};
        await this._hass.callService('viwaco_reader','refresh',data);
        await this._load();
      } catch(err) { this._error='Không thể cập nhật. Kiểm tra Cookie và trạng thái integration.';this._render(); }
      finally { this._busy=false; }
    });
  }
}
/* Lovelace visual editor: Home Assistant calls setConfig and hass; updates
   emit config-changed with a complete new config. No YAML required. */
class ViwacoOverviewCardEditor extends HTMLElement {
  constructor(){ super(); this.attachShadow({mode:'open'}); this._config={}; this._meters=[]; this._loaded=false; }
  setConfig(config){this._config={...config};this._render();}
  set hass(hass){this._hass=hass; if(!this._loaded && hass?.callWS){this._loaded=true;
    hass.callWS({type:'viwaco_reader/history'}).then(list=>{
      this._meters=Array.isArray(list)?list.map(m=>({id:m.customer_id,name:m.name})):[];this._render();
    }).catch(()=>{this._meters=[];this._render();});
  }}
  _change(key,value){
    this._config={...this._config,[key]:value};
    this.dispatchEvent(new CustomEvent('config-changed',{
      detail:{config:{...this._config,type:'custom:viwaco-overview-card'}},bubbles:true,composed:true
    }));
  }
  _render(){
    const c=this._config||{};const current=VW_PALETTES[c.palette]?c.palette:'ocean';
    const op=vwOpacity(c.background_opacity);
    const names=[{id:'*',name:'Tất cả đồng hồ'},...this._meters];
    if(c.customer_id && !names.some(m=>m.id===c.customer_id))names.push({id:String(c.customer_id),name:String(c.customer_id)});
    this.shadowRoot.innerHTML=`<style>
    :host{display:block;color:var(--primary-text-color,#e6edf4);font-family:inherit;font-size:14px}
    *{box-sizing:border-box}.editor{display:grid;gap:18px;padding:6px 1px 16px}
    .field{display:grid;gap:6px;min-width:0}.field label{font-size:12px;font-weight:650;color:var(--secondary-text-color,#b2bfcb)}
    input[type=text],select{width:100%;max-width:100%;background:var(--input-fill-color,var(--secondary-background-color,#30343b));color:var(--primary-text-color,#fff);border:1px solid var(--divider-color,#60656d);border-radius:10px;padding:12px;font:inherit;min-height:44px}
    input:focus-visible,select:focus-visible{outline:2px solid var(--primary-color,#03a9f4);outline-offset:1px}
    .hint{font-size:11px;color:var(--secondary-text-color,#9ba9bc);line-height:1.5}
    .range-row{display:flex;align-items:center;gap:12px}.range-row input{width:100%;min-width:0;accent-color:var(--primary-color,#039bdf);cursor:pointer}
    .range-value{min-width:62px;text-align:center;padding:9px;background:var(--secondary-background-color,#333a40);border-radius:9px;font-variant-numeric:tabular-nums}
    .section-name{font-size:13px;font-weight:750;padding:0 0 9px;border-bottom:1px solid var(--divider-color,#46515c)}
    .checks{display:grid;gap:14px}.check{display:flex;align-items:center;gap:11px;font-size:13px;cursor:pointer}.check input{width:17px;height:17px;accent-color:var(--primary-color,#039bdf)}
    .swatch{display:inline-block;vertical-align:middle;margin-right:8px;width:11px;height:11px;border-radius:100%;background:linear-gradient(135deg,#1e85ee,#17bda9)}
    .palette-preview{display:flex;gap:4px;align-items:center}.palette-preview i{height:14px;border-radius:4px;flex:1}
    </style><div class="editor">
      <div class="section-name">Nội dung hiển thị</div>
      <div class="field"><label for="title">Tiêu đề thẻ</label><input id="title" type="text" maxlength="100" placeholder="Tổng quan nước & tiền" value="${E(c.title||'')}"/></div>
      <div class="field"><label for="customer">Chọn đồng hồ</label><select id="customer">${names.map(m=>`<option value="${E(m.id)}" ${String(c.customer_id||'*')===m.id?'selected':''}>${E(m.name)}${m.id==='*'?'':' · '+E(m.id)}</option>`).join('')}</select></div>
      <div class="section-name">Giao diện và màu sắc</div>
      <div class="field"><label for="palette">Mẫu màu</label><select id="palette">${Object.entries(VW_PALETTES).map(([key,p])=>`<option value="${key}" ${current===key?'selected':''}>${E(p.name)}</option>`).join('')}</select>
      <div class="palette-preview">${VW_PALETTES[current].colors.map(color=>`<i style="background:${color}"></i>`).join('')}</div></div>
      <div class="field"><label for="opacity">Độ đậm nền thẻ</label><div class="range-row"><input id="opacity" type="range" min="0" max="100" step="5" value="${op}" aria-valuetext="${op} phần trăm"/><output class="range-value" for="opacity">${op}%</output></div><div class="hint">0%: trong suốt · 100%: nền đầy đủ. Chữ và số liệu vẫn giữ độ rõ.</div></div>
      <div class="section-name">Bố cục</div>
      <div class="checks">
        <label class="check"><input type="checkbox" id="show_customer" ${vwBool(c.show_customer)?'checked':''}/>Hiển thị hồ sơ khách hàng</label>
        <label class="check"><input type="checkbox" id="show_history" ${vwBool(c.show_history)?'checked':''}/>Hiển thị toàn bộ lịch sử hóa đơn</label>
        <label class="check"><input type="checkbox" id="compact_mobile" ${vwBool(c.compact_mobile)?'checked':''}/>Dùng thẻ tóm tắt 3 tháng trên điện thoại</label>
      </div>
      <div class="hint">Bản xem trước ở bên phải được cập nhật khi thay đổi cấu hình. Bảng lịch sử dài vẫn có thể cuộn ngang trên màn hình nhỏ.</div>
    </div>`;
    const one=id=>this.shadowRoot.getElementById(id);
    one('title')?.addEventListener('change',ev=>this._change('title',ev.target.value.trim()));
    one('customer')?.addEventListener('change',ev=>this._change('customer_id',ev.target.value==='*'?'':ev.target.value));
    one('palette')?.addEventListener('change',ev=>{this._change('palette',ev.target.value);this._render();});
    one('opacity')?.addEventListener('input',ev=>{const output=one('opacity')?.nextElementSibling;if(output)output.textContent=ev.target.value+'%';});
    one('opacity')?.addEventListener('change',ev=>this._change('background_opacity',vwOpacity(ev.target.value)));
    for(const id of ['show_customer','show_history','compact_mobile'])one(id)?.addEventListener('change',ev=>this._change(id,ev.target.checked));
  }
}
if (!customElements.get('viwaco-overview-card-editor')) customElements.define('viwaco-overview-card-editor',ViwacoOverviewCardEditor);
if (!customElements.get('viwaco-overview-card')) customElements.define('viwaco-overview-card', ViwacoOverviewCard);
window.customCards = window.customCards || [];
if (!window.customCards.some(c => c.type === 'viwaco-overview-card')) window.customCards.push({type:'viwaco-overview-card',name:'VIWACO Water Analytics',description:'Dashboard nước & tiền, 11 mẫu màu, chỉnh độ trong suốt và tối ưu điện thoại',preview:false});
