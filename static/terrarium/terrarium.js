// mossity.com terrarium: rendering and interaction. The mycelium itself is
// simulated in Go (myco/), compiled to WebAssembly.
(()=>{
const cv=document.getElementById('c'),ctx=cv.getContext('2d');
const R=Math.random,TAU=Math.PI*2;
const rnd=(a,b)=>a+R()*(b-a), pick=a=>a[(R()*a.length)|0];
const clamp=(v,a=0,b=1)=>v<a?a:v>b?b:v;
const easeOut=t=>1-Math.pow(1-t,3);
const easeBack=t=>{const c=1.5;return 1+(c+1)*Math.pow(t-1,3)+c*Math.pow(t-1,2)};
function shade(hex,a){const n=parseInt(hex.slice(1),16);let r=n>>16,g=(n>>8)&255,b=n&255;
  if(a<0){r*=1+a;g*=1+a;b*=1+a}else{r+=(255-r)*a;g+=(255-g)*a;b+=(255-b)*a}
  return `rgb(${r|0},${g|0},${b|0})`}

/* ---------- content ---------- */
const CARDS={
  about:{k:'Gymnopilus · about',t:"Hi, I'm Ben.",label:'About Ben',p:"Aka @mossity aka @benmoss on various parts of the web."},
  github:{k:'Macrolepiota · code',t:'GitHub',p:'Code, experiments, and half-finished things.',href:'https://github.com/benmoss',cta:'github.com/benmoss →'},
  bluesky:{k:'Entoloma hochstetteri · social',t:'Bluesky',href:'https://bsky.app/profile/mossity.com',cta:'@mossity.com →'},
  mycomatch:{k:'Amanita muscaria · mycomatch',t:'Mycomatch',p:"A trainer for identifying mushrooms from real iNaturalist observations. Still a work in progress.",href:'https://mycomatch.mossity.com/',cta:'mycomatch.mossity.com →'},
  colophon:{k:'Mycena · colophon',t:'How this jar works',p:'Hyphae wander through soil and rotting wood, branch, and fruit where they get dense enough. Turkey tail shelves show up on the log, and as the mycelium eats it the bark sloughs off and the wood bleaches. At night the Mycena glow and the mycelium gives off a little foxfire. Tap anywhere in the jar to sow spores.'}
};
const SPECIES={
  mycena:{shape:'conic',tall:1.15,glow:true,spore:'245,240,225',H:[.05,.09],R:[5,8],sw:[1.1,1.6],curve:[-.25,.25],
    pal:{cap:'#b48656',hi:'#e8cfa4',dark:'#6e4a2c',stipe:'#dccbaa',gill:'#eadfca'}},
  brown:{shape:'dome',flat:.6,bulb:true,spore:'150,100,62',H:[.045,.075],R:[8.5,13],sw:[2.4,3.4],curve:[-.12,.12],
    pal:{cap:'#8a5a34',hi:'#c99d6e',dark:'#4e301a',stipe:'#e6d7b8',gill:'#d9c6a2'}}
};
const LINKS=[
  {key:'bluesky',f:.1,shape:'conic',tall:1.05,spore:'245,175,200',Hf:.13,Rf:.044,sw:2.8,
    pal:{cap:'#2d64d2',hi:'#86acf3',dark:'#163a86',stipe:'#5b86d6',gill:'#b9c6e8'}},
  {key:'about',f:.35,shape:'dome',flat:.62,bulb:true,spore:'205,110,50',Hf:.17,Rf:.07,sw:5,
    pal:{cap:'#c0622c',hi:'#eda56b',dark:'#6e3212',stipe:'#e2c79a',gill:'#d79a55'}},
  {key:'colophon',f:.53,shape:'conic',tall:1.2,glow:true,spore:'245,240,225',Hf:.1,Rf:.03,sw:1.9,
    pal:{cap:'#cfa24c',hi:'#f4dc95',dark:'#7e5a1c',stipe:'#e8d6ae',gill:'#efe2c4'}},
  {key:'github',f:.76,shape:'dome',flat:.42,umbo:true,scales:true,ring:true,bulb:true,spore:'250,248,240',Hf:.2,Rf:.075,sw:3.6,
    pal:{cap:'#e6dcc6',hi:'#fbf6ea',dark:'#9a8462',stipe:'#eee4d0',gill:'#f1eadb'}},
  {key:'mycomatch',f:.92,shape:'dome',flat:.5,warts:true,scales:true,ring:true,bulb:true,spore:'250,248,240',Hf:.14,Rf:.05,sw:3,
    pal:{cap:'#c8231a',hi:'#f0603c',dark:'#7a1008',stipe:'#efe9dc',gill:'#f4efe4'}}
];
const TT=['#eee0c2','#8a6b4e','#4b3a2e','#a48c6c','#5d6e7a','#33271e'];

/* ---------- state ---------- */
let W,H,DPR,L,back,backBase,front,frontBase,glass,myc,mctx,mglow,gctx,rotShown=-1;
// how far the rotten log has slumped (0..1), and when it started to
let collapseC=0,collapseAt=null,stageShown=0;
const COLLAPSE_S=120;
// The pre-rendered set (blender/terrarium.py), or null to draw it procedurally.
let SET=null;
let spores=[],mush=[],brackets=[],flies=[],sown=0,MAXM,T=0;
// prefers-reduced-motion: no swaying, flickering or ambient spore puffs, and
// the link mushrooms start fully grown
const RM=matchMedia('(prefers-reduced-motion: reduce)');let still=RM.matches;
RM.addEventListener('change',e=>{still=e.matches});
let night=(()=>{const h=new Date().getHours();return h<7||h>=18})(),nightA=night?1:0;

function mk(){const c=document.createElement('canvas');c.width=W*DPR;c.height=H*DPR;const x=c.getContext('2d');x.setTransform(DPR,0,0,DPR,0,0);return[c,x]}

/* ---------- geometry ---------- */
function layout(){
  DPR=Math.min(2,window.devicePixelRatio||1);W=innerWidth;H=innerHeight;
  cv.width=W*DPR;cv.height=H*DPR;
  const top=Math.max(110,H*.14),bot=Math.max(54,H*.07),avail=H-top-bot,narrow=W<600&&!SET;
  // Phones get a taller jar with more soil, since the soil is where things happen.
  // The rendered set has fixed proportions, so it scales to fit instead.
  const aspect=SET?SET.jar.h/2:narrow?1.5:1.05;
  const jw=SET?Math.min(W*.9,780,avail/aspect):Math.min(W*.9,780),jh=Math.min(avail,jw*aspect);
  const cx=W/2,yb=top+(avail+jh)/2,ytop=yb-jh,domeH=Math.min(jw*.3,jh*.34);
  const x0=cx-jw/2,x1=cx+jw/2,yw=ytop+domeH,ground=yb-jh*(SET?SET.jar.ground/SET.jar.h:narrow?.4:.34);
  const r=clamp(jh*.075,24,46);
  L={cx,yb,ytop,domeH,x0,x1,yw,jw,jh,ground,r,ax:x0+jw*.2,bx:x0+jw*.6,ly:ground-r*.5,cr:18,gy:yb-jh*.055,s:jw/600};
  L.sm=Math.max(.8,L.s);
  if(SET)setGeometry();
}
// Lines the rendered layers up with the layout and reads the soil and wood
// shapes out of the id layer, so the sim and the mushrooms follow the render.
function setGeometry(){
  const f=SET.frame,u=L.jw/2;
  L.img=[L.cx+f.x0*u,L.yb-f.z1*u,(f.x1-f.x0)*u,(f.z1-f.z0)*u];
  // one shape per collapse stage too, with the stage's id crop over its box
  L.geo=[readId()];if(SET.collapse)for(const s of SET.collapse.stages)L.geo.push(readId(s));
  const g=L.geo[0];L.id=g.id;L.soilTop=g.soilTop.slice();L.woodTop=g.woodTop.slice();stageShown=0;
}
function readId(stage){
  const c=document.createElement('canvas');c.width=W;c.height=H;
  const x=c.getContext('2d',{willReadFrequently:true});x.imageSmoothingEnabled=false;
  x.drawImage(SET.id,...L.img);if(stage)x.drawImage(stage.id,...boxRect(SET.collapse.box));
  const px=x.getImageData(0,0,W,H).data,id=new Uint8Array(W*H);
  for(let i=0;i<W*H;i++)id[i]=px[i*4]>128?1:px[i*4+1]>128?2:0;
  const soilTop=new Float32Array(W).fill(Infinity),woodTop=new Float32Array(W).fill(Infinity);
  for(let cx=0;cx<W;cx++)for(let cy=0;cy<H;cy++){const k=id[cy*W+cx];
    if(k===1&&soilTop[cx]===Infinity)soilTop[cx]=cy;if(k===2&&woodTop[cx]===Infinity)woodTop[cx]=cy}
  return{id,soilTop,woodTop};
}
// a box in the set's units [x0, z0, x1, z1] on the page
const boxRect=b=>{const u=L.jw/2;return[L.cx+b[0]*u,L.yb-b[3]*u,(b[2]-b[0])*u,(b[3]-b[1])*u]};
const idAt=(x,y)=>{x|=0;y|=0;return x<0||y<0||x>=W||y>=H?0:L.id[y*W+x]};
const col=(a,x)=>{x|=0;return x<0||x>=W?Infinity:a[x]};
function surface(x){
  if(SET){const y=col(L.soilTop,x);return y===Infinity?L.ground:y}
  return L.ground+Math.sin(x*.021)*4+Math.sin(x*.057+1.3)*2.5}
function logTop(x){if(SET)return col(L.woodTop,x);const{ax,bx,ly,r}=L;
  if(x<ax-r)return Infinity;
  if(x<ax)return ly-Math.sqrt(Math.max(0,r*r-(ax-x)**2));
  if(x<=bx)return ly-r;
  const u=(x-bx)/(r*.4);if(u>=1)return Infinity;return ly-r*Math.sqrt(1-u*u)}
const surfaceTop=x=>Math.min(surface(x),logTop(x));
function inLog(x,y){if(SET)return idAt(x,y)===2;const{ax,bx,ly,r}=L;
  if(x>bx){const u=(y-ly)/r;if(Math.abs(u)>=1)return false;return x<bx+r*.4*Math.sqrt(1-u*u)}
  const dx=Math.max(ax-x,0);return dx*dx+(y-ly)**2<r*r}
function domeY(x){const u=(x-L.cx)/(L.jw/2);if(Math.abs(u)>=1)return L.yw;return L.yw-L.domeH*Math.sqrt(1-u*u)}
const inJar=(x,y,m=5)=>x>L.x0+m&&x<L.x1-m&&y<L.yb-m&&y>domeY(x)+m;
const inSub=(x,y)=>SET?idAt(x,y)!==0:inJar(x,y,4)&&y<L.gy-2&&(y>surface(x)||inLog(x,y));
function jarPath(c,i=0){const{x0,x1,yb,yw,cx,jw,domeH,cr}=L;const a=x0+i,b=x1-i,y=yb-i;
  c.beginPath();c.moveTo(a,yw);c.ellipse(cx,yw,jw/2-i,domeH-i,0,Math.PI,TAU);
  c.lineTo(b,y-cr);c.quadraticCurveTo(b,y,b-cr,y);c.lineTo(a+cr,y);c.quadraticCurveTo(a,y,a,y-cr);c.closePath()}
function logPath(c){const{ax,bx,ly,r}=L;c.beginPath();c.moveTo(bx,ly-r);c.lineTo(ax,ly-r);c.arc(ax,ly,r,-Math.PI/2,Math.PI/2,true);c.lineTo(bx,ly+r);c.closePath()}

/* ---------- static layers ---------- */
// The log rotting (blender/terrarium.py): stages of the log alone, faded in
// over the backdrop one after another as the mycelium eats the wood. Rot moves
// slowly, so the backdrop is recomposed only when it has changed visibly.
function drawRoom(){
  const{box,day,night:nt}=SET.room,u=L.jw/2,r=[L.cx+box[0]*u,L.yb-box[3]*u,(box[2]-box[0])*u,(box[3]-box[1])*u];
  ctx.fillStyle='#0b0d0b';ctx.fillRect(0,0,W,H);
  if(nightA<1)ctx.drawImage(day,...r);
  if(nightA>0){ctx.globalAlpha=nightA;ctx.drawImage(nt,...r);ctx.globalAlpha=1}
}
function composeRot(r){
  const key=r+collapseC*10;
  if(!SET||!SET.rot||!backBase||Math.abs(key-rotShown)<.01)return;rotShown=key;
  const[c,x]=mk(),{box,imgs}=SET.rot,f=r*imgs.length;
  x.setTransform(1,0,0,1,0,0);x.drawImage(backBase,0,0);x.setTransform(DPR,0,0,DPR,0,0);
  for(let k=0;k<imgs.length&&f>k;k++){x.globalAlpha=clamp(f-k);x.drawImage(imgs[k],...boxRect(box))}
  x.globalAlpha=1;back=c;front=frontBase;
  const C=SET.collapse;if(!C||collapseC<=0)return;
  // collapse stages replace their whole box, back and front
  // on whole device pixels, or the box's antialiased edge shows as a line
  const sn=v=>Math.round(v*DPR)/DPR,[bx,by,bw,bh]=boxRect(C.box),fb=[sn(bx),sn(by),sn(bx+bw)-sn(bx),sn(by+bh)-sn(by)];
  const[fc,fx]=mk(),fk=collapseC*C.stages.length;
  fx.setTransform(1,0,0,1,0,0);fx.drawImage(frontBase,0,0);fx.setTransform(DPR,0,0,DPR,0,0);
  C.stages.forEach((s,k)=>{const a=clamp(fk-k);if(a>0){swapIn(x,s.back,fb,a);swapIn(fx,s.front,fb,a)}});
  front=fc;
}
// crossfades r of x toward img: what's there goes to 1-a, then img adds a
function swapIn(x,img,r,a){
  x.save();x.globalAlpha=a;x.globalCompositeOperation='destination-out';x.fillStyle='#000';x.fillRect(...r);
  x.globalCompositeOperation='lighter';x.drawImage(img,...r);x.restore()}
// The rotten log slumps once the wood is gone: the log's outline moves
// between the stages' shapes, the sim loses the wood that isn't there any
// more, and the hyphae drawn in it go too.
function applyCollapse(){
  const C=SET&&SET.collapse;if(!C||!L.geo||L.geo.length<=C.stages.length)return;
  const f=collapseC*C.stages.length,i=Math.min(Math.floor(f),C.stages.length-1),t=f-i,a=L.geo[i],b=L.geo[i+1];
  const mix=(p,q)=>p===Infinity||q===Infinity?(t<.5?p:q):p+(q-p)*t;
  for(let x=0;x<W;x++){L.woodTop[x]=mix(a.woodTop[x],b.woodTop[x]);L.soilTop[x]=mix(a.soilTop[x],b.soilTop[x])}
  const k=Math.round(f);if(k===stageShown)return;
  const old=L.id;L.id=L.geo[k].id;stageShown=k;
  if(myco)myco.reshape(buildMask().m);
  const c=document.createElement('canvas');c.width=W;c.height=H;const x=c.getContext('2d'),im=x.createImageData(W,H);
  for(let j=0;j<W*H;j++)if(old[j]&&!L.id[j])im.data[j*4+3]=255;
  x.putImageData(im,0,0);
  for(const g of[mctx,gctx]){g.globalCompositeOperation='destination-out';g.drawImage(c,0,0,W,H);g.globalCompositeOperation='source-over'}
}
function drawBack(){
  const[c,x]=mk();back=c;
  // the rendered room is drawn under this each frame, so day can fade to night
  if(SET&&SET.room){x.drawImage(SET.back,...L.img);backBase=c;rotShown=-1;return}
  let g=x.createRadialGradient(L.cx,L.yb-L.jh*.45,10,L.cx,L.yb-L.jh*.45,Math.max(W,H)*.75);
  g.addColorStop(0,'#1e2b20');g.addColorStop(.55,'#0f1611');g.addColorStop(1,'#060907');
  x.fillStyle=g;x.fillRect(0,0,W,H);
  for(let i=0;i<36;i++){const bx=R()*W,by=R()*H*.85,br=rnd(10,46),bg=x.createRadialGradient(bx,by,0,bx,by,br);
    bg.addColorStop(0,`rgba(${R()<.5?'170,200,130':'220,185,120'},${rnd(.02,.055)})`);bg.addColorStop(1,'rgba(0,0,0,0)');
    x.fillStyle=bg;x.beginPath();x.arc(bx,by,br,0,TAU);x.fill()}
  // shadow + wooden base
  x.fillStyle='rgba(0,0,0,.5)';x.beginPath();x.ellipse(L.cx,L.yb+22,L.jw*.6,14,0,0,TAU);x.fill();
  if(SET){x.drawImage(SET.back,...L.img);backBase=c;rotShown=-1;return}
  const p0=L.x0-14,p1=L.x1+14;
  g=x.createLinearGradient(0,L.yb,0,L.yb+20);g.addColorStop(0,'#5d412b');g.addColorStop(1,'#26190f');
  x.fillStyle=g;x.beginPath();x.roundRect?x.roundRect(p0,L.yb-2,p1-p0,20,5):x.rect(p0,L.yb-2,p1-p0,20);x.fill();
  x.strokeStyle='rgba(0,0,0,.28)';x.lineWidth=1;
  for(let i=0;i<4;i++){const yy=L.yb+3+i*4;x.beginPath();x.moveTo(p0+5,yy);for(let xx=p0+5;xx<p1-5;xx+=12)x.lineTo(xx,yy+Math.sin(xx*.04+i*2)*.9);x.stroke()}
  // interior
  x.save();jarPath(x);x.clip();
  g=x.createLinearGradient(0,L.ytop,0,L.ground);g.addColorStop(0,'rgba(150,190,160,.045)');g.addColorStop(1,'rgba(120,160,110,.1)');
  x.fillStyle=g;x.fillRect(L.x0,L.ytop,L.jw,L.jh);
  drawLog(x);drawSoil(x);drawTwig(x);
  x.restore();
}
// A dead twig stuck in the soil between the colophon and github mushrooms,
// leaning up over the colophon one, with some lichen.
function drawTwig(x){
  const bx=L.x0+L.jw*.69,by=surface(bx)+6,len=Math.min(L.jh*.5,L.jw*.5,(by-L.yw)*.95),ang=W<600?-.25:-.36;
  const tx=bx+Math.sin(ang)*len,ty=by-Math.cos(ang)*len,w=clamp(3.2*L.sm,2.4,5);
  const mx=(bx+tx)/2-len*.06,my=(by+ty)/2;
  x.lineCap='round';
  for(const[c,lw,o]of[['#2a1d12',w,0],['#5a4330',w*.55,-.8]]){x.strokeStyle=c;x.lineWidth=lw;
    x.beginPath();x.moveTo(bx+o,by);x.quadraticCurveTo(mx+o,my,tx+o,ty);x.stroke()}
  const at=t=>[(1-t)*(1-t)*bx+2*(1-t)*t*mx+t*t*tx,(1-t)*(1-t)*by+2*(1-t)*t*my+t*t*ty];
  for(const[t0,dir,l]of[[.45,-1,.28],[.68,1,.22],[.82,-1,.16]]){const[px,py]=at(t0),a=ang+dir*rnd(.5,.8),ll=len*l;
    x.strokeStyle='#3b2b1d';x.lineWidth=w*.5;x.beginPath();x.moveTo(px,py);
    x.quadraticCurveTo(px+Math.sin(a)*ll*.5+dir*3,py-Math.cos(a)*ll*.5,px+Math.sin(a)*ll,py-Math.cos(a)*ll);x.stroke()}
  for(let i=0;i<26;i++){const[px,py]=at(rnd(.15,.95));
    x.fillStyle=pick(['rgba(160,180,140,.85)','rgba(190,200,160,.8)','rgba(120,150,110,.8)']);
    x.beginPath();x.ellipse(px+rnd(-w,w)*.8,py+rnd(-2,2),rnd(1.2,2.6)*L.sm,rnd(.8,1.6)*L.sm,rnd(0,3),0,TAU);x.fill()}
}
function drawLog(x){
  const{ax,bx,ly,r}=L;
  x.save();logPath(x);
  let g=x.createLinearGradient(0,ly-r,0,ly+r);g.addColorStop(0,'#6c4e37');g.addColorStop(.35,'#4a3424');g.addColorStop(1,'#1d140c');
  x.fillStyle=g;x.fill();x.clip();
  for(let i=0;i<80;i++){const yy=rnd(ly-r,ly+r),xs=rnd(ax-r,bx),len=rnd(20,90);
    x.strokeStyle=`rgba(${R()<.6?'14,8,4':'135,105,78'},${rnd(.15,.45)})`;x.lineWidth=rnd(.6,2);
    x.beginPath();x.moveTo(xs,yy);for(let t=0;t<=len;t+=6)x.lineTo(xs+t,yy+Math.sin((xs+t)*.08+i)*1.2);x.stroke()}
  for(let i=0;i<10;i++){x.fillStyle=`rgba(${R()<.5?'18,10,5':'150,120,85'},${rnd(.15,.3)})`;
    x.beginPath();x.ellipse(rnd(ax,bx),rnd(ly-r*.6,ly+r*.3),rnd(6,22),rnd(3,8),rnd(-.3,.3),0,TAU);x.fill()}
  x.restore();
  // cut face
  x.fillStyle='#8c6b4a';x.beginPath();x.ellipse(bx,ly,r*.4,r,0,0,TAU);x.fill();
  x.strokeStyle='#33220f';x.lineWidth=2.5;x.stroke();
  for(let k=1;k<7;k++){x.strokeStyle=`rgba(70,45,25,${.25+k*.05})`;x.lineWidth=.8;
    x.beginPath();x.ellipse(bx+k*.3,ly+k*.4,r*.4*(1-k*.13),r*(1-k*.13),0,0,TAU);x.stroke()}
  x.strokeStyle='rgba(40,25,12,.75)';x.lineWidth=1.2;x.beginPath();x.moveTo(bx,ly);x.lineTo(bx+r*.1,ly-r*.5);x.lineTo(bx+r*.04,ly-r*.86);x.stroke();
  x.fillStyle='rgba(45,28,14,.45)';x.beginPath();x.ellipse(bx-r*.1,ly+r*.35,r*.13,r*.22,0,0,TAU);x.fill();
}
function drawSoil(x){
  const{x0,x1,yb,ground,gy}=L;
  x.beginPath();x.moveTo(x0,yb);for(let xx=x0;xx<=x1+3;xx+=3)x.lineTo(xx,surface(xx));x.lineTo(x1,yb);x.closePath();
  let g=x.createLinearGradient(0,ground-6,0,yb);g.addColorStop(0,'#4a3424');g.addColorStop(.15,'#35261a');g.addColorStop(1,'#19110b');
  x.fillStyle=g;x.fill();x.save();x.clip();
  for(let i=0;i<L.jw*3;i++){x.fillStyle=`rgba(${R()<.5?'0,0,0':'125,98,72'},${rnd(.1,.35)})`;x.fillRect(rnd(x0,x1),rnd(ground,yb),rnd(.6,1.8),rnd(.6,1.6))}
  for(let i=0;i<L.jw*.12;i++){const pr=rnd(1.5,4.5);x.fillStyle=`hsl(${rnd(20,40)},${rnd(8,20)}%,${rnd(20,36)}%)`;
    x.beginPath();x.ellipse(rnd(x0,x1),rnd(ground+8,gy),pr,pr*rnd(.6,.9),rnd(0,3),0,TAU);x.fill()}
  // roots
  x.strokeStyle='rgba(150,115,80,.25)';x.lineWidth=.8;
  for(let i=0;i<6;i++){let rx=rnd(x0,x1),ry=surface(rx)+2;x.beginPath();x.moveTo(rx,ry);
    for(let j=0;j<12;j++){rx+=rnd(-6,6);ry+=rnd(3,8);if(ry>gy)break;x.lineTo(rx,ry)}x.stroke()}
  // drainage gravel
  x.fillStyle='rgba(0,0,0,.4)';x.fillRect(x0,gy-3,L.jw,4);
  for(let i=0;i<L.jw*.55;i++){const xx=rnd(x0,x1),yy=rnd(gy,yb+3),pr=rnd(2.5,5.5);
    x.fillStyle=`hsl(${rnd(30,210)},${rnd(3,10)}%,${rnd(26,50)}%)`;x.beginPath();x.ellipse(xx,yy,pr,pr*rnd(.65,.95),rnd(0,3),0,TAU);x.fill();
    x.fillStyle='rgba(255,255,255,.1)';x.beginPath();x.arc(xx-pr*.3,yy-pr*.3,pr*.35,0,TAU);x.fill()}
  x.restore();
}
function drawFront(){
  const[c,x]=mk();front=frontBase=c;if(SET){x.drawImage(SET.front,...L.img);return}
  x.save();jarPath(x);x.clip();
  for(let i=0;i<34;i++){const xx=rnd(L.ax-L.r*.6,L.bx-4),yy=rnd(L.ly-L.r*.9,L.ground-4);if(!inLog(xx,yy))continue;
    x.fillStyle=`rgba(${rnd(150,185)|0},${rnd(180,205)|0},${rnd(148,170)|0},${rnd(.3,.65)})`;x.beginPath();x.arc(xx,yy,rnd(1.5,5)*L.sm,0,TAU);x.fill()}
  const leafC=['#7a4a22','#9a6a2c','#5e3a1e','#b0803a','#6b5a2a','#8c3f1f'];
  for(let i=0;i<L.jw*.09;i++){const xx=rnd(L.x0+8,L.x1-8),yy=surfaceTop(xx)+rnd(-1,2.5),lr=rnd(5,11)*L.sm;
    x.save();x.translate(xx,yy);x.rotate(rnd(-.35,.35));x.globalAlpha=rnd(.75,1);x.fillStyle=pick(leafC);
    x.beginPath();x.ellipse(0,0,lr,lr*rnd(.28,.42),0,0,TAU);x.fill();
    x.strokeStyle='rgba(0,0,0,.3)';x.lineWidth=.6;x.beginPath();x.moveTo(-lr,0);x.lineTo(lr,0);x.stroke();x.restore()}
  const mossC=['#4f6b2c','#6c8a36','#3d5524','#88a344','#5d7d2f'];
  const n=Math.round(L.jw*.06);
  for(let i=0;i<n;i++){const onLog=R()<.45,cx=onLog?rnd(L.ax-L.r*.4,L.bx):rnd(L.x0+8,L.x1-8),w=rnd(10,26)*L.sm;
    for(let j=0;j<w*2.2;j++){const xx=cx+rnd(-w,w),f=1-Math.abs(xx-cx)/w*.6;
      x.fillStyle=pick(mossC);x.beginPath();x.arc(xx,surfaceTop(xx)+rnd(-4.5,1.5)*L.sm*f,rnd(1.2,3)*L.sm,0,TAU);x.fill()}
    for(let j=0;j<3;j++){const xx=cx+rnd(-w*.6,w*.6),yy=surfaceTop(xx)-2,hh=rnd(5,11)*L.sm,ex=xx+rnd(-2,2);
      x.strokeStyle='rgba(170,120,60,.8)';x.lineWidth=.7;x.beginPath();x.moveTo(xx,yy);x.quadraticCurveTo(xx+1,yy-hh*.6,ex,yy-hh);x.stroke();
      x.fillStyle='#a2763a';x.beginPath();x.ellipse(ex,yy-hh,1.1,1.8,0,0,TAU);x.fill()}}
  x.restore();
}
function drawGlass(){
  const[c,x]=mk();glass=c;if(SET){x.drawImage(SET.glass,...L.img);return}
  x.save();jarPath(x);x.clip();
  let g=x.createLinearGradient(L.x0+L.jw*.05,0,L.x0+L.jw*.13,0);
  g.addColorStop(0,'rgba(255,255,255,0)');g.addColorStop(.5,'rgba(230,245,235,.075)');g.addColorStop(1,'rgba(255,255,255,0)');
  x.fillStyle=g;x.fillRect(L.x0,L.ytop,L.jw*.2,L.jh);
  g=x.createLinearGradient(L.x1-L.jw*.1,0,L.x1-L.jw*.06,0);
  g.addColorStop(0,'rgba(255,255,255,0)');g.addColorStop(.5,'rgba(230,245,235,.04)');g.addColorStop(1,'rgba(255,255,255,0)');
  x.fillStyle=g;x.fillRect(L.x1-L.jw*.12,L.ytop,L.jw*.1,L.jh);
  x.restore();
  // condensation, densest under the dome
  x.save();jarPath(x,3);x.clip();
  for(let i=0;i<L.jw*.5;i++){const xx=rnd(L.x0+4,L.x1-4),f=R(),yy=domeY(xx)+4+f*f*(L.ground-L.yw)*.7,dr=rnd(.5,2.1)*(1-f*.5);
    x.fillStyle=`rgba(225,240,232,${rnd(.05,.13)})`;x.beginPath();x.arc(xx,yy,dr,0,TAU);x.fill();
    if(dr>1.3){x.fillStyle='rgba(255,255,255,.22)';x.beginPath();x.arc(xx-dr*.35,yy-dr*.35,dr*.3,0,TAU);x.fill()}}
  x.restore();
  jarPath(x);x.strokeStyle='rgba(215,235,225,.3)';x.lineWidth=1.6;x.stroke();
  jarPath(x,4);x.strokeStyle='rgba(215,235,225,.07)';x.lineWidth=1;x.stroke();
  x.strokeStyle='rgba(240,250,245,.17)';x.lineWidth=3;x.lineCap='round';
  x.beginPath();x.ellipse(L.cx,L.yw,L.jw/2-14,L.domeH-12,0,Math.PI*1.12,Math.PI*1.3);x.stroke();
  x.fillStyle='rgba(200,225,215,.16)';x.strokeStyle='rgba(220,240,230,.35)';x.lineWidth=1.2;
  x.beginPath();x.ellipse(L.cx,L.ytop-5,Math.max(12,L.jw*.035),7,0,0,TAU);x.fill();x.stroke();
}

/* ---------- mycelium (Go/wasm, see myco/) ---------- */
// SEGCAP covers the worst case per call: MaxAdvance (8) x MaxTips (220).
// FADE matches Go's BioDecay (1e-4/frame): old hyphae die back on screen as
// they do in the sim. Applied in steps so 8-bit alpha doesn't leave a haze.
const CELL=2,SEGCAP=4096,FADE_EVERY=12,FADE=.07;
const segBuf=new Float32Array(SEGCAP*5),segBytes=new Uint8Array(segBuf.buffer);
let myco=null,mycoState='loading';
function buildMask(){
  const gw=Math.ceil(W/CELL),gh=Math.ceil(H/CELL),m=new Uint8Array(gw*gh);
  for(let cy=0;cy<gh;cy++){const y=(cy+.5)*CELL;if(y<L.ytop||y>=L.gy-2)continue;
    for(let cx=0;cx<gw;cx++){const x=(cx+.5)*CELL;if(!inJar(x,y,4))continue;
      if(inLog(x,y))m[cy*gw+cx]=2;else{const s=surface(x);if(y>s)m[cy*gw+cx]=y-s<5?3:1}}}
  return{gw,gh,m};
}
function drawSegs(n){
  if(!n)return;const P=[new Path2D(),new Path2D(),new Path2D()];
  for(let i=0;i<n;i++){const o=i*5,w=segBuf[o+4],b=w<1?0:w<1.5?1:2;P[b].moveTo(segBuf[o],segBuf[o+1]);P[b].lineTo(segBuf[o+2],segBuf[o+3])}
  for(let b=0;b<3;b++){
    mctx.lineWidth=[.6,1,1.5][b];mctx.strokeStyle=`rgba(236,230,212,${[.16,.21,.28][b]})`;mctx.stroke(P[b]);
    gctx.lineWidth=[1.1,1.5,2.1][b];gctx.stroke(P[b])}
}
function initMyco(){
  if(!myco||!L)return;
  const{gw,gh,m}=buildMask();
  const err=myco.init(gw,gh,CELL,m,(R()*2**31)|0);
  if(err){console.error('myco.init',err);return}
  const seeds=[[L.ax+(L.bx-L.ax)*.45,L.ly],[L.x0+L.jw*.1,L.ground+L.jh*.12],[L.x0+L.jw*.82,L.ground+L.jh*.1],[L.cx,L.ground+L.jh*.18]];
  for(const[x,y]of seeds)myco.seed(x,y,3);
  drawSegs(myco.warm(30,segBytes));
}
function fadeMyco(){
  for(const c of[mctx,gctx]){c.save();c.setTransform(1,0,0,1,0,0);c.globalCompositeOperation='destination-out';
    c.fillStyle=`rgba(0,0,0,${FADE})`;c.fillRect(0,0,c.canvas.width,c.canvas.height);c.restore()}
}
function onFruit(f){
  for(let i=0;i+3<f.length;i+=4){const x=f[i],y=f[i+1],kind=f[i+2];
    if(f[i+3])spawnBracket(x,y);else spawnMush(x,surfaceTop(x),kind)}
}
async function loadMyco(){
  try{
    if(!('WebAssembly' in window)||!window.Go)throw new Error('no wasm');
    const go=new Go(),url='/terrarium/myco.wasm';
    let res;
    try{res=await WebAssembly.instantiateStreaming(fetch(url),go.importObject)}
    catch(_){res=await WebAssembly.instantiate(await(await fetch(url)).arrayBuffer(),go.importObject)}
    go.run(res.instance);
    myco=window.myco;mycoState='ok';initMyco();
  }catch(e){console.error(e);mycoState='failed'}
}

/* ---------- fruiting bodies ---------- */
function makeMush(o){
  const m=Object.assign({t:0,age:0,wilt:0,phase:rnd(0,TAU),lean:rnd(-.08,.08),curve:0,wdir:R()<.5?-1:1,nextPuff:rnd(4,9),life:rnd(45,110)},o);
  if(m.scales===true){m.scales=[];for(let i=0;i<14;i++){const sx=rnd(-.75,.75),sy=rnd(.18,Math.sqrt(1-sx*sx)*.85);m.scales.push([sx,sy,rnd(-.4,.4)])}}
  return m;
}
function spawnMush(x,y,kind){
  if(x<L.x0+16||x>L.x1-16)return;
  if(mush.filter(m=>!m.link).length>=MAXM)return;
  for(const m of mush)if(Math.abs(m.x-x)<(m.link?36:18)*L.sm)return;
  const myc=R()<(kind===2?.75:.45),sp=myc?SPECIES.mycena:SPECIES.brown;
  mush.push(makeMush({sprite:(myc?'mycena':'brown')+(R()<.5?'':'2'),shape:sp.shape,tall:sp.tall,flat:sp.flat,pal:sp.pal,glow:sp.glow,spore:sp.spore,bulb:sp.bulb,x,y,
    H:L.jh*rnd(...sp.H),R:rnd(...sp.R)*L.sm,sw:rnd(...sp.sw)*L.sm,curve:rnd(...sp.curve),delay:0,dur:rnd(7,12)}));
}
function spawnBracket(x,y){
  if(brackets.length>=5)return;
  for(const b of brackets)if(Math.hypot(b.x-x,b.y-y)<32*L.sm)return;
  for(const m of mush)if(Math.abs(m.x-x)<14&&Math.abs(m.y-y)<20)return;
  const b={x,y,y0:y,top0:logTop(x),R:rnd(13,20)*L.sm,n:R()<.5?2:3,t:0,dur:rnd(8,14),dx:rnd(.4,.7)*(R()<.5?-1:1)};
  // shelves hang down and step sideways; keep the whole cluster on the log
  const ex=b.x+(b.n-1)*b.dx*b.R,ey=b.y+(b.n-1)*b.R*.45+b.R*.6;
  if(!inLog(b.x-b.R,b.y)||!inLog(b.x+b.R,b.y)||!inLog(ex,ey))return;
  brackets.push(b);
}
function geom(m){
  const g=clamp((m.t-m.delay)/m.dur);
  const eh=easeOut(clamp((g-.06)/.75)),cg=easeBack(clamp((g-.18)/.82));
  const h=m.H*eh,Rr=m.R*(.3+.7*cg);
  const sway=still?0:Math.sin(T*.55+m.phase)*.025+Math.sin(T*1.3+m.phase*2)*.008;
  const th=m.lean+sway+m.wilt*1.1*m.wdir;
  const capH=m.shape==='conic'?Rr*m.tall:Rr*(m.flat||.6);
  return{g,h,R:Rr,cg,th,capH,tx:m.x+Math.sin(th)*h,ty:m.y-Math.cos(th)*h};
}
function drawMush(m){
  const G=m.G=geom(m);if(G.g<=0)return;
  const S=SET&&SET.mush[m.sprite];if(S)return drawMushSprite(m,G,S);
  const c=ctx;c.save();c.globalAlpha=1-m.wilt;c.translate(m.x,m.y);c.rotate(G.th);
  if(G.g<.08){const pr=Math.max(1.5,m.R*.35*(G.g/.08));c.fillStyle=m.pal.stipe;c.beginPath();c.ellipse(0,-pr*.6,pr*.8,pr,0,0,TAU);c.fill();c.restore();return}
  const h=G.h,Rr=G.R,wb=m.sw*1.25*(.5+.5*clamp(G.cg)),wt=m.sw*(.6+.4*clamp(G.cg)),cu=m.curve*h;
  const sg=c.createLinearGradient(-wb,0,wb,0);sg.addColorStop(0,shade(m.pal.stipe,-.3));sg.addColorStop(.45,m.pal.stipe);sg.addColorStop(1,shade(m.pal.stipe,-.4));
  c.fillStyle=sg;c.beginPath();c.moveTo(-wb,0);c.quadraticCurveTo(cu-wt,-h*.5,-wt,-h);c.lineTo(wt,-h);c.quadraticCurveTo(cu+wt,-h*.5,wb,0);c.closePath();c.fill();
  if(m.bulb){c.beginPath();c.ellipse(0,-wb*.4,wb*1.35,wb*.9,0,0,TAU);c.fill()}
  if(m.ring&&G.cg>.5){c.fillStyle=shade(m.pal.stipe,-.12);c.beginPath();c.ellipse(0,-h*.72,wt*2.1,wt*.7,0,0,TAU);c.fill()}
  c.translate(0,-h);c.rotate(m.wilt*.6*m.wdir);
  if(m.shape==='conic'){const ch=Rr*m.tall;
    const gr=c.createRadialGradient(-Rr*.25,-ch*.7,Rr*.1,0,-ch*.4,Rr*1.3);gr.addColorStop(0,m.pal.hi);gr.addColorStop(.6,m.pal.cap);gr.addColorStop(1,m.pal.dark);
    c.fillStyle=gr;c.beginPath();c.moveTo(-Rr,Rr*.12);c.bezierCurveTo(-Rr*.95,-ch*.55,-Rr*.38,-ch,0,-ch);c.bezierCurveTo(Rr*.38,-ch,Rr*.95,-ch*.55,Rr,Rr*.12);c.quadraticCurveTo(0,-Rr*.1,-Rr,Rr*.12);c.fill();
    c.strokeStyle='rgba(0,0,0,.18)';c.lineWidth=.6;
    for(let i=-3;i<=3;i++){c.beginPath();c.moveTo(i*Rr*.07,-ch*.8);c.quadraticCurveTo(i*Rr*.2,-ch*.3,i*Rr*.3,Rr*.05);c.stroke()}
  }else{
    const ry=Rr*(m.flat||.6)*(1.3-.3*clamp(G.cg));
    c.fillStyle=m.pal.gill;c.beginPath();c.ellipse(0,0,Rr*.96,Rr*.17,0,0,Math.PI);c.fill();
    c.strokeStyle='rgba(0,0,0,.22)';c.lineWidth=.5;
    for(let k=-.85;k<=.86;k+=.1){c.beginPath();c.moveTo(k*Rr*.95,0);c.lineTo(k*Rr*.35,Rr*.15*Math.sqrt(Math.max(0,1-k*k))+1);c.stroke()}
    const gr=c.createRadialGradient(-Rr*.3,-ry*.75,Rr*.05,0,-ry*.3,Rr*1.15);gr.addColorStop(0,m.pal.hi);gr.addColorStop(.55,m.pal.cap);gr.addColorStop(1,m.pal.dark);
    c.fillStyle=gr;c.beginPath();c.ellipse(0,0,Rr,ry,0,Math.PI,TAU);c.quadraticCurveTo(0,Rr*.08,-Rr,0);c.fill();
    if(m.scales){c.fillStyle=m.warts?'#f1ece0':m.pal.dark;for(const s of m.scales){c.beginPath();c.ellipse(s[0]*Rr,-s[1]*ry,Rr*.06,Rr*.032,s[2],0,TAU);c.fill()}}
    if(m.umbo){c.fillStyle=shade(m.pal.dark,-.2);c.beginPath();c.ellipse(0,-ry*.93,Rr*.17,ry*.12,0,0,TAU);c.fill()}
  }
  c.restore();
}
// Rendered mushrooms (blender/terrarium.py): a strip of frames from pinhead to
// open cap, crossfaded by growth. Frames sit at growth times S.t, packed where
// the shape changes fastest. Each frame records where its cap is, so the
// glow, labels, taps and spore puffs follow it. A strip's stem is 1 unit long
// at maturity, so it's scaled to make that m.H px.
function drawMushSprite(m,G,S){
  const g=clamp(G.g),ts=S.t;let i=0;while(i<S.n-2&&ts[i+1]<=g)i++;
  const u=clamp((g-ts[i])/(ts[i+1]-ts[i])),k=m.H/S.ppu;
  const a=S.f[i],b=S.f[i+1],mix=j=>a[j]+(b[j]-a[j])*u,h=mix(0);
  G.h=h*k;G.R=mix(1)*k;G.capH=mix(2)*k;
  G.tx=m.x+Math.sin(G.th)*G.h;G.ty=m.y-Math.cos(G.th)*G.h;
  const c=ctx,al=1-m.wilt;c.save();c.translate(m.x,m.y);c.rotate(G.th);
  // Frames are far apart in time, so stretch the bare middle of each one's
  // stem to today's length and the cap rises smoothly instead of in steps.
  // Strip px: base at S.ay, y grows down.
  const frame=(j,alpha)=>{
    const x=j*S.fw,hj=S.f[j][0],d=h-hj,y0=S.ay-.15*hj,y1=S.ay-.5*hj,dx=-S.ax*k,dw=S.fw*k;
    c.globalAlpha=alpha;
    c.drawImage(S.img,x,y0,S.fw,S.fh-y0,dx,(y0-S.ay)*k,dw,(S.fh-y0)*k);
    c.drawImage(S.img,x,0,S.fw,y1,dx,(-S.ay-d)*k,dw,y1*k);
    c.drawImage(S.img,x,y1-.5,S.fw,y0-y1+1,dx,(y1-.5-S.ay-d)*k,dw,(y0-y1+1+d)*k);
  };
  frame(i,al);frame(i+1,al*u);
  c.restore();
}
function drawGlow(m){
  const G=m.G;if(!G||G.g<.3)return;
  const a=nightA*(1-m.wilt)*clamp((G.g-.3)/.5)*(still?.85:.75+.25*Math.sin(T*1.7+m.phase));
  const cx=G.tx+Math.sin(G.th)*G.capH*.45,cy=G.ty-Math.cos(G.th)*G.capH*.45,rr=G.R*3.2+6;
  const g=ctx.createRadialGradient(cx,cy,0,cx,cy,rr);
  g.addColorStop(0,`rgba(170,255,150,${.55*a})`);g.addColorStop(.25,`rgba(110,235,120,${.25*a})`);g.addColorStop(1,'rgba(60,200,90,0)');
  ctx.fillStyle=g;ctx.beginPath();ctx.arc(cx,cy,rr,0,TAU);ctx.fill();
}
function drawBracket(b){
  const g=easeOut(clamp(b.t/b.dur));if(g<=0)return;
  const S=SET&&SET.mush['turkey'+b.n];if(S)return drawBracketSprite(b,g,S);
  for(let j=b.n-1;j>=0;j--){const cx=b.x+j*b.dx*b.R,cy=b.y+j*b.R*.45,r=b.R*g*(1-j*.15);
    for(let k=0;k<TT.length;k++){const f=1-k*.15;ctx.fillStyle=TT[k];ctx.beginPath();ctx.ellipse(cx,cy,r*f,r*.6*f,0,0,Math.PI);ctx.fill()}
    ctx.strokeStyle='rgba(30,20,12,.5)';ctx.lineWidth=.6;ctx.beginPath();ctx.ellipse(cx,cy,r,r*.6,0,0,Math.PI);ctx.stroke()}
}
// Rendered brackets: frames of the shelves growing, each scaled between
// frames to the interpolated size of the top shelf so the growth is smooth.
// Mirrored when the tiers step left.
function drawBracketSprite(b,g,S){
  const f=g*(S.n-1),i=Math.min(S.n-2,f|0),u=f-i,ra=S.f[i][0],rb=S.f[i+1][0],r=ra+(rb-ra)*u;
  const k=b.R/S.f[S.n-1][0],c=ctx;c.save();c.translate(b.x,b.y);c.scale(b.dx<0?-k:k,k);
  const frame=(j,rj,alpha)=>{const s=r/rj;c.globalAlpha=alpha;
    c.drawImage(S.img,j*S.fw,0,S.fw,S.fh,-S.ax*s,-S.ay*s,S.fw*s,S.fh*s)};
  frame(i,ra,1);frame(i+1,rb,u);
  c.restore();
}
function drawLabels(){
  ctx.textAlign='center';ctx.textBaseline='bottom';ctx.font='500 11px "JetBrains Mono",ui-monospace,monospace';
  for(const m of mush){if(!m.link||!m.G)continue;const a=clamp((m.G.g-.75)/.25);if(a<=0)continue;
    const G=m.G,d=G.capH+10,lx=G.tx+Math.sin(G.th)*d,ly=G.ty-Math.cos(G.th)*d;
    ctx.globalAlpha=a;ctx.strokeStyle='rgba(239,230,210,.35)';ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(lx,ly-1);ctx.lineTo(lx,ly+5);ctx.stroke();
    ctx.shadowColor='rgba(0,0,0,.8)';ctx.shadowBlur=6;ctx.fillStyle='#efe6d2';ctx.fillText(m.link,lx,ly-3);ctx.shadowBlur=0}
  ctx.globalAlpha=1;
}

/* ---------- fireflies (night only) ---------- */
function makeFlies(){flies=[];const n=W<600?4:7;
  for(let i=0;i<n;i++){const x=rnd(L.x0+30,L.x1-30);flies.push({x,y:rnd(domeY(x)+30,L.ground-L.jh*.18),vx:0,vy:0,ph:rnd(0,TAU),f:rnd(.5,.9)})}}
function updateFlies(k){for(const f of flies){
  f.vx+=(R()-.5)*.05*k;f.vy+=(R()-.5)*.04*k;const d=Math.pow(.97,k);f.vx*=d;f.vy*=d;f.x+=f.vx*k;f.y+=f.vy*k;
  const lo=domeY(f.x)+24,hi=surfaceTop(f.x)-30;
  if(f.x<L.x0+20){f.x=L.x0+20;f.vx=Math.abs(f.vx)}if(f.x>L.x1-20){f.x=L.x1-20;f.vx=-Math.abs(f.vx)}
  if(f.y<lo){f.y=lo;f.vy=Math.abs(f.vy)}if(f.y>hi){f.y=hi;f.vy=-Math.abs(f.vy)}}}
function drawFlies(){if(nightA<.05||still)return;
  for(const f of flies){const b=Math.pow(Math.max(0,Math.sin(T*f.f+f.ph)),10)*nightA;if(b<.01)continue;
    const g=ctx.createRadialGradient(f.x,f.y,0,f.x,f.y,14);
    g.addColorStop(0,`rgba(235,255,150,${.9*b})`);g.addColorStop(.2,`rgba(190,240,110,${.35*b})`);g.addColorStop(1,'rgba(150,220,90,0)');
    ctx.fillStyle=g;ctx.beginPath();ctx.arc(f.x,f.y,14,0,TAU);ctx.fill()}}

/* ---------- spores ---------- */
function addSpore(x,y,vx,vy,col){spores.push({x,y,vx,vy,col,age:0,life:rnd(5,11),sz:rnd(.7,1.6)})}
function puff(m,n){const G=m.G;if(!G)return;
  for(let i=0;i<n;i++)addSpore(G.tx+rnd(-G.R*.7,G.R*.7),G.ty+rnd(0,3),rnd(-.9,.9),rnd(-.25,.8),m.spore)}
function updateSpores(k,dt){
  for(let i=spores.length-1;i>=0;i--){const s=spores[i];
    s.vx+=(R()-.5)*.05*k;s.vy+=((R()-.5)*.05+.004)*k;const d=Math.pow(.985,k);s.vx*=d;s.vy*=d;
    s.x+=s.vx*k;s.y+=s.vy*k;s.age+=dt;
    if(s.x<L.x0+6){s.x=L.x0+6;s.vx=Math.abs(s.vx)}if(s.x>L.x1-6){s.x=L.x1-6;s.vx=-Math.abs(s.vx)}
    const dy=domeY(s.x)+6;if(s.y<dy){s.y=dy;s.vy=Math.abs(s.vy)}
    const st=surfaceTop(s.x);
    if(s.y>=st-1){if(myco&&R()<.3)myco.sow(s.x,1);spores.splice(i,1);continue}
    if(s.age>s.life)spores.splice(i,1)}
}
function drawSpores(){
  ctx.globalCompositeOperation='lighter';
  for(const s of spores){const a=(1-s.age/s.life)*.8;
    if(nightA>.05){ctx.fillStyle=`rgba(${s.col},${a*.12*nightA})`;ctx.beginPath();ctx.arc(s.x,s.y,s.sz*4,0,TAU);ctx.fill()}
    ctx.fillStyle=`rgba(${s.col},${a})`;ctx.beginPath();ctx.arc(s.x,s.y,s.sz,0,TAU);ctx.fill()}
  ctx.globalCompositeOperation='source-over';
}

/* ---------- setup ---------- */
function init(){
  syncTheme();layout();drawBack();drawFront();drawGlass();
  [myc,mctx]=mk();[mglow,gctx]=mk();
  mctx.strokeStyle='rgba(236,230,212,.17)';mctx.lineWidth=.7;
  gctx.strokeStyle='rgba(140,255,170,.32)';gctx.lineWidth=1.2;
  spores=[];mush=[];brackets=[];MAXM=W<600?9:15;makeFlies();
  initMyco();applyCollapse();
  LINKS.forEach((d,i)=>{const x=L.x0+L.jw*d.f;
    mush.push(makeMush({sprite:d.key,shape:d.shape,tall:d.tall,flat:d.flat,pal:d.pal,glow:d.glow,spore:d.spore,bulb:d.bulb,ring:d.ring,umbo:d.umbo,scales:d.scales,warts:d.warts,
      x,y:surfaceTop(x),link:d.key,H:clamp(L.jh*d.Hf,38,150),R:clamp(L.jw*d.Rf,10,46),sw:clamp(d.sw*L.sm,1.6,7),
      curve:rnd(-.06,.06),lean:rnd(-.05,.05),delay:.5+i*.8,dur:SET?5.5+R()*1.5:3.4+R()}))});
  if(still)for(const m of mush)m.t=m.delay+m.dur;
}

/* ---------- loop ---------- */
let last=performance.now(),statT=0,fadeT=0;
const statsEl=document.getElementById('stats');
function frame(now){
  const dt=Math.min(.05,(now-last)/1000);last=now;T+=dt;const k=dt*60;
  nightA+=((night?1:0)-nightA)*Math.min(1,dt*2.5);
  if(myco){const r=myco.step(k,segBytes);if(r){drawSegs(r.n);onFruit(r.fruits)}
    fadeT+=dt;if(fadeT>=FADE_EVERY){fadeT=0;fadeMyco()}}
  for(let i=mush.length-1;i>=0;i--){const m=mush[i];m.t+=dt;const g=m.G?m.G.g:0;
    if(g>=1&&m.wilt===0&&!still){m.nextPuff-=dt;if(m.nextPuff<=0){m.nextPuff=rnd(4,10);puff(m,(3+R()*4)|0)}}
    if(!m.link&&g>=1){m.age+=dt;if(m.age>m.life){m.wilt+=dt/5;if(m.wilt>=1){mush.splice(i,1)}}}}
  for(const b of brackets)b.t+=dt;
  // things on the log ride it down as it slumps
  if(collapseC>0){for(const m of mush)m.y=surfaceTop(m.x);
    for(const b of brackets){const t=logTop(b.x),g=L.ground;if(t<g&&b.top0<g)b.y=Math.min(g-(g-b.y0)*(g-t)/(g-b.top0),g-((b.n-1)*.45+.6)*b.R)}}
  updateSpores(k,dt);updateFlies(k);

  ctx.setTransform(DPR,0,0,DPR,0,0);ctx.globalAlpha=1;ctx.globalCompositeOperation='source-over';
  if(SET&&SET.room)drawRoom();
  ctx.drawImage(back,0,0,W,H);ctx.drawImage(myc,0,0,W,H);ctx.drawImage(front,0,0,W,H);
  for(const b of brackets)drawBracket(b);
  for(const m of mush)drawMush(m);
  if(nightA>.01){
    ctx.fillStyle=`rgba(3,6,14,${.62*nightA})`;ctx.fillRect(0,0,W,H);
    ctx.globalCompositeOperation='lighter';
    ctx.globalAlpha=nightA*(still?.32:.32+.1*Math.sin(T*.7));ctx.drawImage(mglow,0,0,W,H);ctx.globalAlpha=1;
    for(const m of mush)if(m.glow)drawGlow(m);
    drawFlies();
    ctx.globalCompositeOperation='source-over'}
  drawSpores();
  // rendered glass is reflections only, which add light rather than cover
  if(SET)ctx.globalCompositeOperation='screen';
  ctx.drawImage(glass,0,0,W,H);ctx.globalCompositeOperation='source-over';
  drawLabels();placeKeys();
  statT+=dt;if(statT>.5){statT=0;const fb=mush.filter(m=>m.G&&m.G.g>.3).length+brackets.length;
    const st=myco&&myco.stats();
    // most of the wood goes in the first few minutes; front-load the look of it
    if(st&&collapseAt===null&&st.wood<.1)collapseAt=T;
    if(collapseAt!==null){collapseC=clamp((T-collapseAt)/COLLAPSE_S);applyCollapse()}
    if(st)composeRot(collapseC>0?1:Math.pow(clamp((1-st.wood)/.9),.7));
    statsEl.textContent=st?(W<520?`${Math.round(st.length).toLocaleString()} mm hyphae · ${st.tips} tips · ${fb} fruiting`:`${Math.round(st.length).toLocaleString()} mm of hyphae · ${st.tips} tips · ${fb} fruiting bodies · ${sown} spores sown`):mycoState==='failed'?'the mycelium failed to load':'germinating…'}
  requestAnimationFrame(frame);
}

/* ---------- keyboard ---------- */
// The canvas is invisible to keyboards and screen readers, so each link
// mushroom gets a real button that follows its cap. Pointers still go through
// the canvas, which hit-tests wild mushrooms and sows spores too.
const keys=document.getElementById('keys'),keyBtn={};
for(const d of LINKS){const b=document.createElement('button');b.type='button';
  b.setAttribute('aria-label',CARDS[d.key].label||CARDS[d.key].t);b.style.visibility='hidden';
  b.onclick=()=>{const m=mush.find(m=>m.link===d.key);if(m&&!still)puff(m,34);opener=b;openCard(d.key)};
  keys.appendChild(b);keyBtn[d.key]=b}
// the buttons and cards carry the links now; the fallback list would repeat them
document.querySelector('nav.sr').hidden=true;
function placeKeys(){
  for(const m of mush){if(!m.link)continue;const b=keyBtn[m.link],G=m.G,on=G&&G.g>=.5;
    b.style.visibility=on?'visible':'hidden';if(!on)continue;
    const r=Math.round(Math.max(16,G.R+6)),cx=G.tx+Math.sin(G.th)*G.capH*.4,cy=G.ty-Math.cos(G.th)*G.capH*.4;
    const t=`translate(${Math.round(cx-r)}px,${Math.round(cy-r)}px)`;
    if(b.style.transform!==t){b.style.transform=t;b.style.width=b.style.height=2*r+'px'}}
}

/* ---------- interaction ---------- */
const card=document.getElementById('card');
function openCard(key){const d=CARDS[key];
  document.getElementById('cardK').textContent=d.k;document.getElementById('cardT').textContent=d.t;const cp=document.getElementById('cardP');cp.textContent=d.p||'';cp.style.display=d.p?'':'none';
  const a=document.getElementById('cardA');if(d.href){a.href=d.href;a.textContent=d.cta;a.style.display=''}else a.style.display='none';
  card.classList.add('open');
  // keyboard users land in the card; pointer users keep their place
  if(opener)(d.href?a:document.getElementById('cardX')).focus({preventScroll:true})}
let opener=null;
const closeCard=()=>{if(!card.classList.contains('open'))return;card.classList.remove('open');
  if(opener){opener.focus();opener=null}};
document.getElementById('cardX').onclick=closeCard;
addEventListener('keydown',e=>{if(e.key==='Escape')closeCard()});
function hit(x,y){let best=null,bd=1e9;
  for(const m of mush){const G=m.G;if(!G||G.g<.5||m.wilt>.3)continue;
    const cx=G.tx+Math.sin(G.th)*G.capH*.4,cy=G.ty-Math.cos(G.th)*G.capH*.4,d=Math.hypot(x-cx,y-cy),rr=Math.max(18,G.R+12);
    if(d<rr&&(m.link?d-8:d)<bd){bd=m.link?d-8:d;best=m}}
  return best}
cv.addEventListener('pointerdown',e=>{
  if(!L)return;
  const x=e.clientX,y=e.clientY;
  if(card.classList.contains('open')){closeCard();return}
  opener=null;const m=hit(x,y);
  if(m){puff(m,m.link?34:16);if(m.link)openCard(m.link);return}
  if(inJar(x,y,8)){sown+=16;for(let i=0;i<16;i++)addSpore(x+rnd(-4,4),y+rnd(-4,4),rnd(-.8,.8),rnd(-.6,.5),'235,225,200')}
});
cv.addEventListener('pointermove',e=>{if(!L)return;cv.style.cursor=hit(e.clientX,e.clientY)?'pointer':inJar(e.clientX,e.clientY,8)?'crosshair':'default'});
const nb=document.getElementById('nightBtn');
// dark text only over the rendered room's daylight; the procedural jar is dark
const syncTheme=()=>document.body.classList.toggle('day',!night&&!!(SET&&SET.room));
const setBtn=()=>{nb.textContent=night?'☀︎ day':'☾ night';syncTheme()};setBtn();
nb.onclick=()=>{night=!night;setBtn()};
let rt;addEventListener('resize',()=>{clearTimeout(rt);rt=setTimeout(init,220)});

async function loadSet(){
  if(new URLSearchParams(location.search).get('set')==='0')return;
  // phones get the taller portrait jar
  const base='/terrarium/set/',dir=innerWidth<600?'portrait/':'';
  const img=n=>new Promise((ok,no)=>{const i=new Image();i.onload=()=>ok(i);i.onerror=no;i.src=base+n});
  const json=async n=>(await fetch(base+n)).json();
  const[meta,sheet,room]=await Promise.all([json(dir+'set.json'),json('mush.json'),json('room.json')]);
  // one room for both: it's the same windowsill whichever jar stands on it
  const[back,front,glass,id,day,night]=await Promise.all(['back.webp','front.webp','glass.webp','id.png'].map(n=>dir+n).concat('room-day.webp','room-night.webp').map(img));
  const mush={};
  await Promise.all(Object.entries(sheet).map(async([k,v])=>{mush[k]={...v,img:await img(`mush/${k}.webp`)}}));
  // too late: the procedural jar is already up, and switching mid-run would reset it
  if(L)return;
  SET={...meta,back,front,glass,id,mush,room:{box:room.box,day,night}};
  // the log starts fresh, so its rot stages can arrive later
  json(dir+'rot.json').then(async r=>{SET.rot={box:r.box,imgs:await Promise.all(Array.from({length:r.n},(_,k)=>img(`${dir}rot${k+1}.webp`)))}})
    .catch(e=>console.warn('rot stages',e));
  json(dir+'collapse.json').then(async c=>{
    const stages=await Promise.all(Array.from({length:c.n},async(_,k)=>{const n=`${dir}collapse${k+1}`;
      const[back,front,id]=await Promise.all([img(n+'.webp'),img(n+'-front.webp'),img(n+'-id.png')]);return{back,front,id}}));
    SET.collapse={box:c.box,stages};if(L&&L.geo)for(const s of stages)L.geo.push(readId(s))})
    .catch(e=>console.warn('collapse stages',e));
}
loadMyco();
// Give the rendered set a moment to load; draw the procedural jar if it can't.
Promise.race([loadSet().catch(e=>console.warn('terrarium set',e)),new Promise(r=>setTimeout(r,8000))]).then(()=>{
  init();requestAnimationFrame(t=>{last=t;frame(t)})});
})();
