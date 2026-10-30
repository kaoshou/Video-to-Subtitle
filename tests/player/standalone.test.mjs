import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require = createRequire(new URL('../../website/package.json', import.meta.url));
const {JSDOM} = require('jsdom');
const script = readFileSync(new URL('../../assets/evercam_player/js/evercam-modern.js', import.meta.url), 'utf8');

function player(config, {standalone = true, preferences = {}, blockedStorage = false, subtitles} = {}) {
  const html = readFileSync(new URL(`../../assets/${standalone ? 'standalone_player' : 'evercam_player'}/index.html`, import.meta.url), 'utf8');
  const dom = new JSDOM(html, {url:'https://local.invalid/', runScripts:'outside-only', pretendToBeVisual:true});
  const w = dom.window;
  w.matchMedia = () => ({matches:false});
  w.VTTCue = class { constructor(start, end, text) { this.startTime=start; this.endTime=end; this.text=text; } };
  const tracks = [];
  // jsdom has no media engine; these doubles only expose the browser text-track boundary.
  w.document.querySelector('video').addTextTrack = () => {
    const cueList = [];
    const track = {mode:'disabled', get cues(){return this.mode === 'disabled' ? null : cueList;},
      activeCues:[], addCue(c) {cueList.push(c);}, addEventListener(){}};
    tracks.push(track); return track;
  };
  w.document.querySelector('video').play = () => Promise.resolve();
  if (standalone) w.VTS_PLAYER_CONFIG = config; else w.config = config;
  w.EVERCAM_SUBTITLES = subtitles || {tracks:['zh-TW','en'].map(language => ({language, cues:[{start:0,end:1,text:'<script>hi</script>'}]}))};
  for (const [key,value] of Object.entries(preferences)) w.localStorage.setItem(key,value);
  if (blockedStorage) Object.defineProperty(w, 'localStorage', {get(){throw new Error('denied');}});
  w.eval(script);
  return {dom, w, tracks};
}

// jsdom has no layout engine. Model only list/row geometry, leaving real
// player handlers, pagination, active cues and scrollTop changes intact.
function transcriptViewport(w, height = () => 100) {
  const list = w.document.querySelector('#transcript-list');
  Object.defineProperty(list, 'clientHeight', {get:height});
  list.getBoundingClientRect = () => ({top:0,bottom:height(),height:height()});
  const original = w.HTMLElement.prototype.getBoundingClientRect;
  w.HTMLElement.prototype.getBoundingClientRect = function () {
    if (!this.matches('.transcript-item')) return original.call(this);
    const index = [...list.querySelectorAll('.transcript-item')].indexOf(this);
    const top = index * 40 - list.scrollTop;
    return {top,bottom:top+40,height:40};
  };
  return list;
}

function followControl(w) {
  const checkbox = w.document.querySelector('#transcript-follow');
  assert.ok(checkbox, 'viewer can opt in to transcript playback following');
  return checkbox;
}

function setFollowing(w, checked) {
  const checkbox = followControl(w);
  checkbox.checked = checked;
  checkbox.dispatchEvent(new w.Event('change'));
}

function showTranscript(w, standalone) {
  if (w.document.querySelector('#transcript-panel').hidden) {
    w.document.querySelector(standalone ? '#transcript-toggle' : '#transcript-tab').click();
  }
}

function changeValue(w, selector, value) {
  const control=w.document.querySelector(selector);
  assert.ok(control, `Missing viewer control ${selector}`);
  control.value=value; control.dispatchEvent(new w.Event('change'));
  return control;
}

test('reading controls are opt-in, preserve captions, restore defaults and survive blocked storage', t => {
  for (const standalone of [true,false]) {
    const {dom,w}=player({mode:standalone?'standalone':undefined,title:'course',defaultSubtitle:'zh-TW'},
      {standalone,blockedStorage:true}); t.after(()=>dom.window.close());
    const settings=w.document.querySelector('#reading-settings');
    assert.ok(settings, 'Reading settings are available without replacing the player');
    assert.equal(settings.open,false);
    assert.equal(w.document.body.dataset.readingContrast,'normal');
    const originalCaption=w.document.querySelector('#caption-text').style.fontSize;
    changeValue(w,'#reading-font-size','150');
    changeValue(w,'#reading-line-height','2');
    changeValue(w,'#reading-contrast','high');
    assert.equal(w.document.querySelector('#transcript-list').style.getPropertyValue('--reading-size'),'1.5');
    assert.equal(w.document.querySelector('#transcript-list').style.getPropertyValue('--reading-line-height'),'2');
    assert.equal(w.document.body.dataset.readingContrast,'high');
    assert.equal(w.document.querySelector('#caption-text').style.fontSize,originalCaption);
    w.document.querySelector('#reading-reset').click();
    assert.equal(w.document.body.dataset.readingContrast,'normal');
    assert.equal(w.document.querySelector('#reading-font-size').value,'100');
    assert.equal(w.document.querySelector('#reading-line-height').value,'1.5');
  }
});

test('reading preferences are validated and reused without changing follow or language', t => {
  const {dom,w}=player({mode:'standalone',title:'course',defaultSubtitle:'en'},
    {preferences:{'vts.readingAppearance':JSON.stringify({size:'200',lineHeight:'1.8',contrast:'high'})}});
  t.after(()=>dom.window.close());
  assert.ok(w.document.querySelector('#reading-font-size'), 'Reading settings must load saved values');
  assert.equal(w.document.querySelector('#reading-font-size').value,'200');
  assert.equal(w.document.querySelector('#reading-line-height').value,'1.8');
  assert.equal(w.document.body.dataset.readingContrast,'high');
  assert.equal(w.document.querySelector('#transcript-follow').checked,false);
  assert.equal(w.document.querySelector('#transcript-language').value,'en');
  const invalid=player({mode:'standalone'}, {preferences:{'vts.readingAppearance':'{"size":"99999","contrast":"red","lineHeight":"0"}'}});
  t.after(()=>invalid.dom.window.close());
  assert.equal(invalid.w.document.querySelector('#reading-font-size').value,'100');
  assert.equal(invalid.w.document.body.dataset.readingContrast,'normal');
});

async function downloadedText(w, button) {
  let blob,filename;
  // Only the browser's disk-download boundary is replaced. Read the actual
  // production Blob using FileReader, keeping all transcript generation real.
  w.URL.createObjectURL=value=>{blob=value;return 'blob:synthetic-download';};
  w.URL.revokeObjectURL=()=>{};
  const click=w.HTMLAnchorElement.prototype.click;
  w.HTMLAnchorElement.prototype.click=function(){filename=this.download;};
  try { button.click(); } finally { w.HTMLAnchorElement.prototype.click=click; }
  assert.ok(blob,'The download must contain a generated document');
  const text=await new Promise((resolve,reject)=>{
    const reader=new w.FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsText(blob);
  });
  return {text,filename,blob};
}

test('reading downloads contain the whole selected language, not search results or the first page', async t => {
  for (const standalone of [true,false]) {
    const cues=Array.from({length:260},(_,i)=>({start:i*2,end:i*2+1,text:`English unique${i} <img src=x onerror=alert(1)>`}));
    const {dom,w}=player({mode:standalone?'standalone':undefined,title:'課程 <script>alert(1)</script>',defaultSubtitle:'zh-TW',
      index:[{time:0,title:'第一章 <b>原樣</b>'},{time:300,title:'第二章'}]},
      {standalone,subtitles:{tracks:[{language:'zh-TW',cues:[{start:0,end:1,text:'不是英文內容'}]},{language:'en',cues}]}});
    t.after(()=>dom.window.close());
    const htmlButton=w.document.querySelector('#transcript-download-html');
    assert.ok(htmlButton,'A full reading-version download is provided');
    showTranscript(w,standalone); changeValue(w,'#transcript-language','en');
    const search=w.document.querySelector('#transcript-search');search.value='unique2';search.dispatchEvent(new w.Event('input'));
    const result=await downloadedText(w,htmlButton);
    const reading=new JSDOM(result.text);t.after(()=>reading.window.close());
    const doc=reading.window.document;
    assert.equal(doc.documentElement.lang,'en');
    assert.equal(doc.querySelector('title').lang,'zh-TW','Fixed Chinese document labels identify their language');
    assert.ok([...doc.querySelectorAll('header p')].every(p=>p.lang==='zh-TW'));
    assert.equal(doc.querySelector('article').lang,'zh-TW','The Chinese accessible name has its own language');
    assert.equal(doc.querySelector('article > div').lang,'en','Transcript content retains its selected language');
    assert.match(doc.querySelector('h1').textContent,/課程 <script>/);
    assert.equal(doc.querySelectorAll('script,img,iframe').length,0,'Subtitle text never becomes active HTML');
    for (const index of [0,150,259]) assert.ok(doc.body.textContent.includes(`unique${index} `));
    assert.ok(!doc.body.textContent.includes('不是英文內容'));
    assert.equal(doc.querySelectorAll('time').length,0,'Reading defaults omit timestamp clutter');
    if (!standalone) assert.ok([...doc.querySelectorAll('h2')].some(h=>h.textContent==='第二章'));
    assert.ok(!/[\\/:*?"<>|]/.test(result.filename),'Generated filenames are portable');
    const timestamps=w.document.querySelector('#reading-timestamps');timestamps.checked=true;
    const timed=await downloadedText(w,htmlButton);assert.match(timed.text,/<time\b/);
    const plain=await downloadedText(w,w.document.querySelector('#transcript-download-txt'));
    assert.match(plain.blob.type,/text\/plain/);assert.ok(plain.text.includes('unique259 '));
    assert.ok(plain.text.includes('<img src=x onerror=alert(1)>'),'Plain text preserves literal content');
  }
});

test('empty selected tracks disable downloads without preventing reading settings', t => {
  const {dom,w}=player({mode:'standalone',defaultSubtitle:'en'}, {subtitles:{tracks:[
    {language:'en',cues:[{start:0,end:1,text:'hello'}]},{language:'zh-TW',cues:[]}]}});
  t.after(()=>dom.window.close());
  const button=w.document.querySelector('#transcript-download-html');assert.ok(button);
  assert.equal(button.disabled,false);changeValue(w,'#transcript-language','zh-TW');
  assert.equal(button.disabled,true);assert.equal(w.document.querySelector('#transcript-download-txt').disabled,true);
  assert.equal(w.document.querySelector('#reading-font-size').disabled,false);
});

test('Escape closes settings from form controls and returns focus without changing playback', t => {
  const {dom,w}=player({mode:'standalone',defaultSubtitle:'en'});t.after(()=>dom.window.close());
  const caption=w.document.querySelector('#caption-button');caption.click();
  const selected=w.document.activeElement;
  selected.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
  assert.equal(w.document.querySelector('#caption-menu').hidden,true,'Escape works even when a menu button has focus');
  assert.equal(w.document.activeElement,caption);
  showTranscript(w,true);const details=w.document.querySelector('#reading-settings');assert.ok(details);details.open=true;
  const select=w.document.querySelector('#reading-font-size');select.focus();
  select.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
  assert.equal(details.open,false);assert.equal(w.document.activeElement,details.querySelector('summary'));
});

test('player shortcuts respect focus, modifiers and typing; seek slider exposes understandable time', t => {
  const {dom,w}=player({mode:'standalone',duration:120,defaultSubtitle:'en'});t.after(()=>dom.window.close());
  const video=w.document.querySelector('video');video.currentTime=30;
  w.document.body.dispatchEvent(new w.KeyboardEvent('keydown',{key:'m',bubbles:true}));
  assert.equal(video.muted,false,'Single-character shortcuts are not global screen-reader conflicts');
  const stage=w.document.querySelector('#video-stage');stage.focus();
  assert.equal(w.document.activeElement,stage,'Keyboard users can enter the player');
  stage.dispatchEvent(new w.KeyboardEvent('keydown',{key:'m',bubbles:true}));assert.equal(video.muted,true);
  stage.dispatchEvent(new w.KeyboardEvent('keydown',{key:'m',ctrlKey:true,bubbles:true}));assert.equal(video.muted,true);
  video.dispatchEvent(new w.Event('timeupdate'));
  assert.match(w.document.querySelector('#seek-slider').getAttribute('aria-valuetext'),/0:30.*2:00/);
  const field=w.document.querySelector('#transcript-search');field.focus();
  field.dispatchEvent(new w.KeyboardEvent('keydown',{key:'m',bubbles:true}));assert.equal(video.muted,true);
});

test('clicking the video establishes playback focus and controls retain scoped shortcuts', t => {
  for (const standalone of [true, false]) {
    const {dom,w}=player({mode:standalone?'standalone':undefined,duration:120},{standalone});
    t.after(()=>dom.window.close());
    const doc=w.document, video=doc.querySelector('video'), stage=doc.querySelector('#video-stage');
    video.click();
    assert.equal(doc.activeElement,stage,'A mouse-started session can immediately use playback keys');
    const button=doc.querySelector('#play-toggle');button.focus();
    const press=(target,key,extra={})=>target.dispatchEvent(new w.KeyboardEvent('keydown',
      {key,bubbles:true,cancelable:true,...extra}));
    press(button,'m');assert.equal(video.muted,true);
    press(button,'m',{repeat:true});assert.equal(video.muted,true,'Holding a toggle key must not flicker');
    press(button,'f');assert.equal(stage.classList.contains('is-frame-fullscreen'),true);
    press(button,'Escape');assert.equal(stage.classList.contains('is-frame-fullscreen'),false);
    assert.equal(press(button,'Enter'),true,'Native button activation remains available');
    assert.equal(press(button,' ',{code:'Space'}),true,'Space on a button uses that button');
    const range=doc.querySelector('#volume-slider');range.focus();press(range,'m');
    assert.equal(video.muted,true,'Form and range controls keep their own keyboard behavior');
    doc.querySelector('#caption-button').click();press(doc.activeElement,'m');
    assert.equal(video.muted,true,'Subtitle dialog controls do not trigger playback letters');
  }
});

test('chapter and help navigation reveal their destinations and establish useful focus', t => {
  const {dom,w}=player({title:'course',index:[{time:0,title:'開始'},{time:10000,title:'操作'}]},
    {standalone:false});t.after(()=>dom.window.close());
  const doc=w.document;
  doc.querySelector('a[href="#transcript-heading"]').click();
  const links=[...doc.querySelectorAll('a[href="#chapters-heading"]')];
  assert.ok(links.length,'Chapter navigation is discoverable without traversing every player control');
  for (const link of links) {
    link.click();assert.equal(doc.querySelector('#chapters-panel').hidden,false);
    assert.equal(doc.activeElement,doc.querySelector('#chapters-heading'));
    doc.querySelector('a[href="#transcript-heading"]').click();
  }
  const help=doc.querySelector('#player-help');assert.ok(help);assert.equal(help.open,false);
  doc.querySelector('a[href="#player-help"]').click();
  assert.equal(help.open,true);assert.equal(doc.activeElement,help.querySelector('summary'));
  help.querySelector('summary').focus();
  doc.activeElement.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
  assert.equal(help.open,false);assert.equal(doc.activeElement,help.querySelector('summary'));
});

test('every transcript navigation entry opens the standalone panel, including empty subtitles', t => {
  const {dom,w}=player({mode:'standalone'},{subtitles:{tracks:[]}});t.after(()=>dom.window.close());
  const doc=w.document;
  const links=[...doc.querySelectorAll('a[href="#transcript-heading"]')];
  assert.ok(links.length,'The keyboard skip link offers transcript navigation');
  for (const link of links) {
    link.click();assert.equal(doc.querySelector('.chapter-card').hidden,false);
    assert.equal(doc.querySelector('#transcript-panel').hidden,false);
    assert.equal(doc.activeElement,doc.querySelector('#transcript-heading'));
    doc.querySelector('#transcript-toggle').click();
  }
  assert.ok([...doc.querySelectorAll('a[href="#chapters-heading"]')].every(link=>link.hidden),
    'Plain MP4 does not offer a nonexistent chapter index');
});

test('access keys target the player, chapters, transcript and help without a visible navigation bar', t => {
  for (const standalone of [true,false]) {
    const {dom,w}=player({mode:standalone?'standalone':undefined,index:[{time:0,title:'開始'}]}, {standalone});
    t.after(()=>dom.window.close());const doc=w.document;
    assert.equal(doc.querySelector('.player-navigation'),null,'Default layout has no quick-navigation bar');
    for (const [key,href] of [['c','#video-stage'],['i','#chapters-heading'],['t','#transcript-heading'],['h','#player-help']]) {
      const link=doc.querySelector(`a[href="${href}"]`);assert.ok(link);
      assert.equal(link.accessKey,standalone&&key==='i'?'':key);
      if (!(standalone&&key==='i')) {
        assert.equal(link.classList.contains('player-skip-link'),true,'Access keys use focus-revealed skip links');
        link.click();
        assert.equal(doc.activeElement,href==='#player-help'?doc.querySelector('#player-help > summary'):doc.querySelector(href));
      }
    }
  }
});

test('documented navigation combinations work across platforms without intercepting AltGr or composition', t => {
  for (const platform of ['Win32','MacIntel']) {
    const {dom,w}=player({index:[{time:0,title:'開始'}]},{standalone:false});
    t.after(()=>dom.window.close());const doc=w.document;
    Object.defineProperty(w.navigator,'platform',{value:platform,configurable:true});
    const press=(key,modifiers)=>doc.activeElement.dispatchEvent(new w.KeyboardEvent('keydown',
      {key,bubbles:true,cancelable:true,...modifiers}));
    const modifiers=platform==='MacIntel'?{ctrlKey:true,altKey:true}:{altKey:true};
    for (const [key,target] of [['c','#video-stage'],['i','#chapters-heading'],['t','#transcript-heading'],['h','#player-help > summary']]) {
      press(key,modifiers);assert.equal(doc.activeElement,doc.querySelector(target));
    }
    doc.querySelector('#transcript-search').focus();const input=doc.activeElement;
    for(const extra of [{isComposing:true},{repeat:true},{metaKey:true}]) {
      press('c',{...modifiers,...extra});assert.equal(doc.activeElement,input);
    }
    if(platform==='Win32') {
      press('c',{ctrlKey:true,altKey:true});assert.equal(doc.activeElement,input,'AltGr keeps input intact');
      press('c',{altKey:true,shiftKey:true});assert.equal(doc.activeElement,doc.querySelector('#video-stage'),'Firefox combination works');
    }
  }
});

test('menu openers support the expected down arrow while input methods are left alone', t => {
  const {dom,w}=player({mode:'standalone'});t.after(()=>dom.window.close());
  for (const [buttonId,menuId] of [['speed-button','speed-menu'],['caption-button','caption-menu']]) {
    const button=w.document.getElementById(buttonId),menu=w.document.getElementById(menuId);
    button.focus();button.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));
    assert.equal(menu.hidden,false);assert.ok(menu.contains(w.document.activeElement));
    w.document.activeElement.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    assert.equal(w.document.activeElement,button);
    button.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowDown',isComposing:true,bubbles:true}));
    assert.equal(menu.hidden,true);
  }
});

test('starting with the central play button moves focus to a visible playback control', t => {
  const {dom,w}=player({mode:'standalone'});t.after(()=>dom.window.close());
  const doc=w.document,video=doc.querySelector('video'),central=doc.querySelector('#big-play');
  central.focus();
  // jsdom does not decode media: expose only the native playing-state boundary.
  Object.defineProperty(video,'paused',{value:false,configurable:true});
  video.dispatchEvent(new w.Event('play'));
  assert.equal(doc.activeElement,doc.querySelector('#play-toggle'));
  assert.equal(central.hidden,true,'An invisible central overlay must not remain in the Tab order');
  Object.defineProperty(video,'paused',{value:true,configurable:true});
  video.dispatchEvent(new w.Event('pause'));assert.equal(central.hidden,false);
});

test('skip-to-transcript reveals the correct panel and gives it a stable keyboard target', t => {
  for (const standalone of [true,false]) {
    const {dom,w}=player({mode:standalone?'standalone':undefined},{standalone});t.after(()=>dom.window.close());
    const skip=w.document.querySelector('a[href="#transcript-heading"]');assert.ok(skip,'Hidden-by-default transcripts remain keyboard-discoverable');
    skip.click();assert.equal(w.document.querySelector('#transcript-panel').hidden,false);
    assert.equal(w.document.querySelector('.chapter-card').hidden,false);
    assert.equal(w.document.activeElement,w.document.querySelector('#transcript-heading'));
  }
});

test('leaving a nonmodal settings panel closes it without pulling focus back', t => {
  const {dom,w}=player({mode:'standalone',defaultSubtitle:'en'});t.after(()=>dom.window.close());
  showTranscript(w,true);
  const details=w.document.querySelector('#reading-settings');details.open=true;
  w.document.querySelector('#reading-font-size').focus();
  const language=w.document.querySelector('#transcript-language');language.focus();
  assert.equal(details.open,false,'Tabbing out must not leave settings covering the next field');
  assert.equal(w.document.activeElement,language);
  w.document.querySelector('#caption-button').click();
  w.document.querySelector('#speed-button').focus();
  assert.equal(w.document.querySelector('#caption-menu').hidden,true);
  assert.equal(w.document.activeElement,w.document.querySelector('#speed-button'));
});

test('choosing a caption or playback speed returns keyboard focus to its opener', t => {
  const {dom,w}=player({mode:'standalone',defaultSubtitle:'en'});t.after(()=>dom.window.close());
  for (const [opener, menu, value] of [['#caption-button','#caption-menu','zh-TW'],['#speed-button','#speed-menu','1.5']]) {
    w.document.querySelector(opener).click();
    const item=w.document.querySelector(`${menu} button[data-value="${value}"]`);item.focus();item.click();
    assert.equal(w.document.querySelector(menu).hidden,true);
    assert.equal(w.document.activeElement,w.document.querySelector(opener),'Hidden menu items must not retain focus');
  }
});

test('named player tool containers expose valid grouping semantics', t => {
  for (const standalone of [true,false]) {
    const {dom,w}=player({mode:standalone?'standalone':undefined},{standalone});t.after(()=>dom.window.close());
    for (const selector of ['.time-display',...(standalone?['.player-tools']:[])]) {
      assert.equal(w.document.querySelector(selector).getAttribute('role'),'group',`${selector} must not label a generic div`);
    }
  }
});

test('follow is opt-in and scrolls only the transcript when the current cue leaves view', t => {
  for (const standalone of [true,false]) {
    const {dom,w}=player({mode:standalone?'standalone':undefined,title:'course',defaultSubtitle:'zh-TW'},
                         {standalone,subtitles:searchable});
    t.after(()=>dom.window.close());
    const list=transcriptViewport(w);
    showTranscript(w,standalone);
    assert.equal(followControl(w).checked,false);
    const video=w.document.querySelector('video');
    video.currentTime=30.5; video.dispatchEvent(new w.Event('timeupdate'));
    assert.equal(list.scrollTop,0);
    const focused=w.document.activeElement;
    setFollowing(w,true);
    assert.equal(list.scrollTop,50);
    assert.match(w.document.querySelector('.transcript-item[aria-current="true"]').textContent,/索引的應用/);
    assert.equal(w.document.activeElement,focused, 'following never steals keyboard focus');
    assert.equal(w.document.documentElement.scrollTop,0);
    video.currentTime=31; video.dispatchEvent(new w.Event('timeupdate'));
    assert.equal(list.scrollTop,50, 'same visible cue does not move again');
    setFollowing(w,false);
    video.currentTime=1; video.dispatchEvent(new w.Event('timeupdate'));
    assert.equal(list.scrollTop,50, 'unchecking stops following');
  }
});

test('follow seeks far beyond the first page and back without rendering the entire transcript', t => {
  const cues=Array.from({length:10000},(_,i)=>({start:i*2,end:i*2+1,text:`段落 ${i}`}));
  for (const standalone of [true,false]) {
    const {dom,w}=player({mode:standalone?'standalone':undefined,title:'long',defaultSubtitle:'en'},
                         {standalone,subtitles:{tracks:[{language:'en',cues}]}});
    t.after(()=>dom.window.close());
    transcriptViewport(w); showTranscript(w,standalone); setFollowing(w,true);
    const video=w.document.querySelector('video');
    for (const [time,text] of [[18002.5,'段落 9001'],[10.5,'段落 5'],[19998.5,'段落 9999']]) {
      video.currentTime=time; video.dispatchEvent(new w.Event('seeked'));
      const active=w.document.querySelector('.transcript-item[aria-current="true"]');
      assert.ok(active, 'current cue must be present after seeking');
      assert.match(active.textContent,new RegExp(text+'$'));
      assert.ok(w.document.querySelectorAll('.transcript-item').length<=100, 'following remains bounded');
    }
  }
});

test('search suspends following and clearing search resumes at the current playback position', t => {
  const {dom,w}=player({mode:'standalone',title:'course',defaultSubtitle:'zh-TW'},{subtitles:searchable});
  t.after(()=>dom.window.close());
  const list=transcriptViewport(w); showTranscript(w,true); setFollowing(w,true);
  const input=w.document.querySelector('#transcript-search');
  input.value='索引'; input.dispatchEvent(new w.Event('input'));
  list.scrollTop=0;
  const video=w.document.querySelector('video');
  video.currentTime=30.5; video.dispatchEvent(new w.Event('timeupdate'));
  assert.equal(list.scrollTop,0);
  assert.equal(w.document.querySelectorAll('.transcript-item').length,2);
  const hint=w.document.querySelector('#transcript-follow-hint');
  assert.ok(hint); assert.equal(hint.hidden,false);
  assert.match(hint.textContent,/搜尋/);
  w.document.querySelector('#transcript-clear').click();
  assert.equal(list.scrollTop,50);
  assert.equal(hint.hidden,true);
  assert.equal(followControl(w).checked,true);
});

test('hidden transcript never scrolls or opens itself; reopening follows the current cue', t => {
  for (const standalone of [true,false]) {
    const {dom,w}=player({mode:standalone?'standalone':undefined,title:'course',defaultSubtitle:'zh-TW'},
                         {standalone,subtitles:searchable});
    t.after(()=>dom.window.close());
    const list=transcriptViewport(w); setFollowing(w,true);
    if (standalone) w.document.querySelector('#transcript-toggle').click();
    const video=w.document.querySelector('video');
    video.currentTime=30.5; video.dispatchEvent(new w.Event('timeupdate'));
    assert.equal(w.document.querySelector('#transcript-panel').hidden,true);
    assert.equal(list.scrollTop,0);
    showTranscript(w,standalone);
    assert.equal(list.scrollTop,50);
    w.document.querySelector(standalone?'#transcript-toggle':'#chapters-tab').click();
    video.currentTime=1; video.dispatchEvent(new w.Event('timeupdate'));
    assert.equal(list.scrollTop,50);
    showTranscript(w,standalone);
    assert.equal(list.scrollTop,0);
  }
});

test('following uses selected transcript language even with captions off and preserves gaps', t => {
  const data={tracks:[...searchable.tracks.slice(0,1),{language:'en',cues:[
    {start:0,end:4,text:'Introduction'}, {start:12.5,end:17,text:'Database'}, {start:30,end:34,text:'English current'}]}]};
  const {dom,w,tracks}=player({mode:'standalone',title:'course',defaultSubtitle:'zh-TW'},{subtitles:data});
  t.after(()=>dom.window.close());
  const list=transcriptViewport(w); showTranscript(w,true); setFollowing(w,true);
  const video=w.document.querySelector('video');
  video.currentTime=30.5; video.dispatchEvent(new w.Event('timeupdate'));
  [...w.document.querySelectorAll('#caption-menu button')].find(b=>b.dataset.value==='off').click();
  const language=w.document.querySelector('#transcript-language');
  language.value='en'; language.dispatchEvent(new w.Event('change'));
  assert.match(w.document.querySelector('.transcript-item[aria-current="true"]').textContent,/English current/);
  assert.deepEqual(tracks.map(track=>track.mode),['disabled','disabled']);
  const position=list.scrollTop;
  video.currentTime=20; video.dispatchEvent(new w.Event('timeupdate'));
  assert.equal(w.document.querySelector('.transcript-item[aria-current="true"]'),null);
  assert.equal(list.scrollTop,position);
});

test('after a distant follow jump, manual browsing can reach earlier and later pages', t => {
  const cues=Array.from({length:1000},(_,i)=>({start:i*2,end:i*2+1,text:`段落 ${i}`}));
  const {dom,w}=player({mode:'standalone',title:'long',defaultSubtitle:'en'},
                       {subtitles:{tracks:[{language:'en',cues}]}});
  t.after(()=>dom.window.close());
  transcriptViewport(w); showTranscript(w,true); setFollowing(w,true);
  const video=w.document.querySelector('video');
  video.currentTime=1200.5; video.dispatchEvent(new w.Event('seeked'));
  setFollowing(w,false);
  const earlier=w.document.querySelector('#transcript-previous');
  assert.ok(earlier); assert.equal(earlier.hidden,false);
  earlier.click();
  assert.match(w.document.querySelector('.transcript-item').textContent,/段落 475$/);
  w.document.querySelector('#transcript-more').click();
  assert.equal(w.document.querySelectorAll('.transcript-item').length,200);
  assert.equal(video.currentTime,1200.5);
});

test('empty transcripts disable follow rather than creating an empty scrolling action', t => {
  for (const standalone of [true,false]) {
    const {dom,w}=player({mode:standalone?'standalone':undefined,title:'empty'}, {standalone,subtitles:{tracks:[]}});
    t.after(()=>dom.window.close());
    assert.equal(followControl(w).disabled,true);
  }
});

test('automatic paging preserves a retained focused cue instead of losing focus to the page', t => {
  const cues=Array.from({length:300},(_,i)=>({start:i*2,end:i*2+1,text:`段落 ${i}`}));
  const {dom,w}=player({mode:'standalone',title:'long',defaultSubtitle:'en'},
                       {subtitles:{tracks:[{language:'en',cues}]}});
  t.after(()=>dom.window.close());
  transcriptViewport(w); showTranscript(w,true); setFollowing(w,true);
  w.document.querySelectorAll('.transcript-item')[99].focus();
  const video=w.document.querySelector('video');
  video.currentTime=200.5; video.dispatchEvent(new w.Event('timeupdate'));
  assert.equal(w.document.activeElement.matches('.transcript-item'),true);
  assert.match(w.document.activeElement.textContent,/段落 99$/);
  assert.equal(w.document.querySelectorAll('.transcript-item').length,100);
  video.currentTime=480.5; video.dispatchEvent(new w.Event('seeked'));
  assert.equal(w.document.activeElement,followControl(w), 'a removed target has a persistent keyboard fallback');
  assert.equal(w.document.documentElement.scrollTop,0);
});

test('viewport shrink and orientation changes keep the same current cue visible', t => {
  const {dom,w}=player({mode:'standalone',title:'course',defaultSubtitle:'zh-TW'}, {subtitles:searchable});
  t.after(()=>dom.window.close());
  let height=100;
  const list=transcriptViewport(w,()=>height);
  showTranscript(w,true); setFollowing(w,true);
  const video=w.document.querySelector('video');
  video.currentTime=30.5; video.dispatchEvent(new w.Event('timeupdate'));
  assert.equal(list.scrollTop,50);
  height=50; w.dispatchEvent(new w.Event('resize'));
  assert.equal(list.scrollTop,75);
  height=100; list.scrollTop=0; w.dispatchEvent(new w.Event('orientationchange'));
  assert.equal(list.scrollTop,50);
  assert.equal(video.currentTime,30.5);
});

test('standalone metadata is text and transcript sidebar is visible without chapters', () => {
  const {dom,w} = player({mode:'standalone', packageId:'a', title:'<script>title</script>', organization:'單位', description:'第一行\n<em>原文</em>', defaultSubtitle:'en'});
  assert.equal(w.document.title,'<script>title</script>');
  assert.equal(w.document.querySelector('.chapter-card').hidden,false);
  assert.equal(w.document.querySelector('#course-title').children.length,0);
  assert.equal(w.document.querySelector('#course-description').textContent,'第一行\n<em>原文</em>');
  assert.equal(w.document.querySelector('#course-author').hidden,true);
  assert.equal(w.document.querySelector('#course-organization').hidden,false);
  dom.window.close();
});

test('configured track, saved off, invalid preference fallback and blocked storage', () => {
  for (const [preferences, blockedStorage, expected] of [
    [{},false,['disabled','hidden']],
    [{'vts.subtitle.a':'off'},false,['disabled','disabled']],
    [{'vts.subtitle.a':'missing'},false,['disabled','hidden']],
    [{'vts.subtitle.other':'zh-TW'},false,['disabled','hidden']],
    [{},true,['disabled','hidden']],
  ]) {
    const {dom,tracks} = player({mode:'standalone',packageId:'a',title:'same',defaultSubtitle:'en'}, {preferences,blockedStorage});
    assert.deepEqual(tracks.map(t=>t.mode),expected);
    dom.window.close();
  }
});

test('EverCam keeps chapter card and legacy preference key', () => {
  for (const index of [[],[{time:0,title:'第一章'}]]) {
    const {dom,w,tracks} = player({title:'old',index}, {standalone:false,preferences:{'evercam.subtitle.old':'en'}});
    assert.equal(w.document.querySelector('.chapter-card').hidden,false);
    assert.equal(w.document.querySelector('#chapter-empty').hidden,index.length>0);
    assert.deepEqual(tracks.map(t=>t.mode),['disabled','hidden']);
    dom.window.close();
  }
});

test('automatic standalone default is not an explicit viewer preference', () => {
  const {dom,w} = player({mode:'standalone',packageId:'fresh',title:'same',defaultSubtitle:'en'});
  assert.equal(w.localStorage.getItem('vts.subtitle.fresh'),null);
  const off = Array.from(w.document.querySelectorAll('#caption-menu button')).find(b=>b.textContent==='關閉');
  off.click();
  assert.equal(w.localStorage.getItem('vts.subtitle.fresh'),'off');
  dom.window.close();
});

const searchable = {tracks:[
  {language:'zh-TW', cues:[{start:0,end:4,text:'課程介紹'}, {start:12.5,end:17,text:'資料庫與索引'}, {start:30,end:34,text:'索引的應用'}]},
  {language:'en', cues:[{start:0,end:4,text:'Introduction'}, {start:12.5,end:17,text:'Database INDEX'}]}
]};

test('both player modes search transcript text and seek to the matching cue', () => {
  for (const standalone of [true,false]) {
    const {dom,w} = player({mode:standalone?'standalone':undefined,title:'course',defaultSubtitle:'zh-TW',index:[]}, {standalone,subtitles:searchable});
    const input = w.document.querySelector('#transcript-search');
    assert.ok(input, 'viewer can search the transcript');
    input.value = '索引'; input.dispatchEvent(new w.Event('input'));
    const results = [...w.document.querySelectorAll('.transcript-item')];
    assert.equal(results.length,2);
    assert.match(results[0].textContent,/0:12.*資料庫與索引/s);
    assert.equal(results[0].querySelector('mark').textContent,'索引');
    results[0].click();
    assert.equal(w.document.querySelector('video').currentTime,12.5);
    assert.equal(results[0].getAttribute('aria-current'),'true');
    dom.window.close();
  }
});

test('transcript language follows captions and can be searched while captions are off', () => {
  const {dom,w,tracks} = player({mode:'standalone',packageId:'a',title:'course',defaultSubtitle:'zh-TW'}, {subtitles:searchable});
  const language = w.document.querySelector('#transcript-language');
  assert.ok(language);
  const english = [...w.document.querySelectorAll('#caption-menu button')].find(b=>b.dataset.value==='en');
  english.click();
  assert.equal(language.value,'en');
  const input = w.document.querySelector('#transcript-search');
  input.value='index'; input.dispatchEvent(new w.Event('input'));
  assert.equal(w.document.querySelectorAll('.transcript-item').length,1);
  assert.equal(w.document.querySelector('.transcript-item mark').textContent,'INDEX');
  [...w.document.querySelectorAll('#caption-menu button')].find(b=>b.dataset.value==='off').click();
  assert.equal(language.value,'en');
  language.value='zh-TW'; language.dispatchEvent(new w.Event('change'));
  assert.deepEqual(tracks.map(t=>t.mode),['disabled','disabled']);
  assert.equal(w.document.querySelectorAll('.transcript-item').length,0);
  w.document.querySelector('#transcript-clear').click();
  assert.equal(input.value,'');
  assert.equal(w.document.querySelectorAll('.transcript-item').length,3);
  dom.window.close();
});

test('search treats HTML and regex characters as text and reports empty subtitles', () => {
  const data={tracks:[{language:'en',cues:[{start:5,end:9,text:'<img src=x onerror=alert(1)> .* ['}, {start:10,end:11,text:'other'}]}]};
  const {dom,w} = player({mode:'standalone',packageId:'a',title:'course',defaultSubtitle:'en'},{subtitles:data});
  const input=w.document.querySelector('#transcript-search');
  assert.ok(input);
  for(const query of ['.*','[','<img']){
    input.value=query; input.dispatchEvent(new w.Event('input'));
    assert.equal(w.document.querySelectorAll('.transcript-item').length,1);
    assert.equal(w.document.querySelector('#transcript-list img'),null);
    assert.equal(w.document.querySelector('.transcript-item mark').textContent,query);
  }
  dom.window.close();
  const empty=player({mode:'standalone',title:'empty'},{subtitles:{tracks:[]}});
  assert.equal(empty.w.document.querySelector('#transcript-search').disabled,true);
  assert.match(empty.w.document.querySelector('#transcript-status').textContent,/字幕/);
  empty.dom.window.close();
});

test('large transcripts have bounded initial results with more results available', () => {
  const cues=Array.from({length:260},(_,i)=>({start:i*2,end:i*2+1,text:`字幕 ${i}`}));
  const {dom,w}=player({mode:'standalone',title:'large',defaultSubtitle:'en'},{subtitles:{tracks:[{language:'en',cues}]}});
  assert.ok(w.document.querySelector('#transcript-search'));
  assert.equal(w.document.querySelectorAll('.transcript-item').length,100);
  w.document.querySelector('#transcript-more').click();
  assert.equal(w.document.querySelectorAll('.transcript-item').length,200);
  const input=w.document.querySelector('#transcript-search');
  input.value='字幕 259'; input.dispatchEvent(new w.Event('input'));
  assert.equal(w.document.querySelectorAll('.transcript-item').length,1);
  assert.equal(w.document.querySelector('#transcript-more').hidden,true);
  dom.window.close();
});

test('standalone player shows transcript sidebar initially and retains searches when reopened', () => {
  for (const standalone of [true]) {
    const {dom,w}=player({mode:standalone?'standalone':undefined,title:'course',defaultSubtitle:'zh-TW'}, {standalone,subtitles:searchable});
    const toggle=w.document.querySelector('#transcript-toggle');
    const panel=w.document.querySelector('#transcript-panel');
    assert.ok(toggle, 'viewer can expand the transcript with a button');
    assert.equal(panel.hidden,false);
    assert.equal(w.document.querySelector('.chapter-card').hidden,false);
    assert.equal(w.document.body.classList.contains('standalone-transcript-open'),true);
    assert.equal(toggle.getAttribute('aria-expanded'),'true');
    const input=w.document.querySelector('#transcript-search');
    assert.notEqual(w.document.activeElement,input,'Loading the page must not steal keyboard focus');
    input.value='索引'; input.dispatchEvent(new w.Event('input'));
    toggle.click();
    assert.equal(panel.hidden,true);
    assert.equal(w.document.querySelector('.chapter-card').hidden,true);
    assert.equal(toggle.getAttribute('aria-expanded'),'false');
    toggle.click();
    assert.equal(panel.hidden,false);
    assert.equal(input.value,'索引');
    assert.equal(w.document.querySelectorAll('.transcript-item').length,2);
    dom.window.close();
  }
});

test('EverCam chapter and transcript tabs share the sidebar without changing playback', () => {
  const {dom,w}=player({title:'course',index:[{time:0,title:'介紹'}]}, {standalone:false,subtitles:searchable});
  const chapters=w.document.querySelector('#chapters-tab');
  const transcript=w.document.querySelector('#transcript-tab');
  assert.ok(chapters && transcript, 'viewer can switch chapter and transcript tabs');
  assert.equal(chapters.getAttribute('aria-selected'),'true');
  assert.equal(w.document.querySelector('#chapters-panel').hidden,false);
  assert.equal(w.document.querySelector('#transcript-panel').hidden,true);
  const video=w.document.querySelector('video'); video.currentTime=2;
  transcript.click();
  assert.equal(transcript.getAttribute('aria-selected'),'true');
  assert.equal(chapters.getAttribute('aria-selected'),'false');
  assert.equal(w.document.querySelector('#chapters-panel').hidden,true);
  assert.equal(w.document.querySelector('#transcript-panel').hidden,false);
  const input=w.document.querySelector('#transcript-search');
  input.value='索引'; input.dispatchEvent(new w.Event('input'));
  chapters.click(); transcript.click();
  assert.equal(input.value,'索引');
  assert.equal(w.document.querySelectorAll('.transcript-item').length,2);
  assert.equal(video.currentTime,2);
  transcript.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
  assert.equal(w.document.activeElement,chapters);
  assert.equal(chapters.getAttribute('aria-selected'),'true');
  assert.equal(transcript.tabIndex,-1);
  dom.window.close();
});

test('standalone reading sidebar offers transcript only, without empty chapters', () => {
  const {dom,w}=player({mode:'standalone',title:'course',defaultSubtitle:'zh-TW'},{subtitles:searchable});
  const chapters=w.document.querySelector('#chapters-tab');
  assert.ok(chapters);
  assert.equal(chapters.hidden,true);
  assert.equal(w.document.querySelector('#transcript-tab').getAttribute('aria-selected'),'true');
  assert.equal(w.document.querySelector('#chapters-panel').hidden,true);
  assert.equal(w.document.querySelector('#transcript-panel').hidden,false);
  assert.equal(w.document.querySelector('.chapter-card').hidden,false);
  dom.window.close();
});

test('standalone empty subtitles show an explanation rather than an empty right column', t => {
  const {dom,w}=player({mode:'standalone'}, {subtitles:{tracks:[]}});
  t.after(()=>dom.window.close());
  const doc=w.document;
  assert.equal(doc.querySelector('.chapter-card').hidden,false);
  assert.equal(doc.querySelector('#transcript-panel').hidden,false);
  assert.equal(doc.querySelector('#transcript-search').disabled,true);
  assert.ok(doc.querySelector('#transcript-status').textContent.trim());
});
