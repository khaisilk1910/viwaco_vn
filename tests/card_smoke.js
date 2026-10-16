const fs = require('fs');
const vm = require('vm');
class FakeElement { attachShadow(){ this.shadowRoot = {innerHTML:'',querySelector(){return null}}; return this.shadowRoot; } }
global.HTMLElement = FakeElement;
global.window = {customCards:[]};
const map = new Map();
global.customElements = {get(name){return map.get(name)},define(name,klass){map.set(name,klass)}};
const filename = __dirname + '/../custom_components/viwaco_reader/frontend/viwaco-dashboard.js';
vm.runInThisContext(fs.readFileSync(filename,'utf8'),{filename});
const Klass = customElements.get('viwaco-overview-card');
const c = new Klass();
c._meters = [{customer_id:'000000001',name:'Test Water',available:true,last_error:null,
  archive_status:{running:false, done:1,total:1,errors:0},archived_months:1,
  recent_months:[{period:'10/2026',usage_m3:17,total_vnd:177445,previous_m3:1377,current_m3:1394}],
  invoices:[{period:'10/2026',usage_m3:17,total_vnd:177445,paid_vnd:177445,invoice_url:'https://hoadon.viwaco.vn/tra-cuu/?code=4A6D1300',archive:{
  pdf_url:'/local/viwaco_reader/abcdefabcdefabcdefab/2026/2026-10.pdf',png_urls:['/local/viwaco_reader/abcdefabcdefabcdefab/2026/2026-10.png'],
  details:{water_charge_vnd:154300,environment_fee_vnd:15430,vat_vnd:7715,total_vnd:177445,tariffs:[{tariff:'SH1',quantity_m3:10,unit_price_vnd:8500,amount_vnd:85000}]}}}],
  readings:[{period:'10/2026',read_date:'2026-10-08',current_m3:1394,previous_m3:1377,usage_m3:17}],customer:{name:'Sample'}}];
c._render();
for (const expected of ['Toàn bộ lịch sử đồng hồ và hóa đơn','Lưu toàn bộ PDF + PNG','Phí BVMT','PDF ↗','PNG ↗','SH1','1.394']) {
 if (!c.shadowRoot.innerHTML.includes(expected)) throw new Error('Expected string missing: '+expected);
}
console.log('Card smoke test passed; HTML characters = ' + c.shadowRoot.innerHTML.length);
