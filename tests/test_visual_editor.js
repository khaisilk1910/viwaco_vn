const fs = require('fs'), vm = require('vm');
const filename = __dirname+'/../custom_components/viwaco_reader/frontend/viwaco-dashboard.js';
const definitions = new Map();
class FakeElement {
  constructor(){this.events=[];}
  attachShadow(){return (this.shadowRoot={innerHTML:'',querySelector:()=>null,getElementById:()=>null});}
  dispatchEvent(event){this.events.push(event);return true;}
}
global.HTMLElement=FakeElement;
global.document={createElement:id=>new (definitions.get(id))()};
global.window={customCards:[]};
global.customElements={get:id=>definitions.get(id),define:(id,cls)=>definitions.set(id,cls)};
global.CustomEvent=class {constructor(type,opts){Object.assign(this,{type},opts);}};
vm.runInThisContext(fs.readFileSync(filename,'utf8'),{filename});
const Card=definitions.get('viwaco-overview-card');
const Editor=definitions.get('viwaco-overview-card-editor');
if (!Card || !Editor) throw new Error('Missing card or editor');
const stub=Card.getStubConfig();
if(stub.background_opacity!==100||stub.palette!=='ocean')throw new Error('Defaults missing');
if (!(Card.getConfigElement() instanceof Editor))throw new Error('Not a visual editor');
const editor=new Editor();editor.setConfig({type:'custom:viwaco-overview-card'});
for(const text of ['Chọn đồng hồ','Tiêu đề thẻ','Mẫu màu','Độ đậm nền thẻ','Hiển thị hồ sơ khách hàng','Rose · Hồng','Cyan · Xanh ngọc']){
 if (!editor.shadowRoot.innerHTML.includes(text)) throw new Error('Missing editor content: '+text);
}
editor._change('palette','rose');editor._change('background_opacity',35);
const event=editor.events.at(-1);
if(event.type!=='config-changed'||event.composed!==true||event.bubbles!==true||event.detail.config.palette!=='rose'||event.detail.config.background_opacity!==35)throw new Error('config-changed contract broken');
const card=new Card();card.setConfig({palette:'rose',title:'Nước nhà',background_opacity:35,show_customer:false,show_history:false});
if(!card.shadowRoot.innerHTML.includes('--vw-hero1:#602548'))throw new Error('Palette did not apply');
if(!card.shadowRoot.innerHTML.includes('--vw-surface-opacity:35%'))throw new Error('Opacity did not apply');
if(!card.shadowRoot.innerHTML.includes('@container(max-width:560px)'))throw new Error('Missing container query');
if(card.shadowRoot.innerHTML.includes('Hồ sơ khách hàng</h2>')||card.shadowRoot.innerHTML.includes('Toàn bộ lịch sử đồng hồ và hóa đơn</h2>'))throw new Error('Hidden section still shown');
if(card.shadowRoot.innerHTML.includes('Nước nhà')===false)throw new Error('Title not configured');
console.log('Visual editor tests passed (customCards, event, palette, opacity, responsive, content visibility)');
