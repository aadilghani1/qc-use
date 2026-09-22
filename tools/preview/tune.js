// DialKit is used only in the local design preview, never in a real QA run.
const root=DialKit.createDialRoot({theme:'light',position:'bottom-right'});
const kit=DialKit.createDialKit('qc-use preview',{
  motion:[180,0,300,10], radius:[14,0,24,1],
  accent:{type:'color',default:'#287852'},
  replay:{type:'action'}
},{id:'qc-use-preview',defaultCollapsed:true,onAction(action){if(action==='replay')location.reload()}});
kit.subscribe(values=>{
  const style=document.documentElement.style;
  style.setProperty('--motion',values.motion+'ms');
  style.setProperty('--radius',values.radius+'px');
  style.setProperty('--accent',values.accent);
});
window.addEventListener('pagehide',()=>{kit.destroy();root.destroy()},{once:true});
