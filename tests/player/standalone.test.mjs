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
  w.document.querySelector(standalone ? '#transcript-toggle' : '#transcript-tab').click();
}

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

test('standalone metadata is text, chapter card is hidden', () => {
  const {dom,w} = player({mode:'standalone', packageId:'a', title:'<script>title</script>', organization:'單位', description:'第一行\n<em>原文</em>', defaultSubtitle:'en'});
  assert.equal(w.document.title,'<script>title</script>');
  assert.equal(w.document.querySelector('.chapter-card').hidden,true);
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

test('standalone player hides transcript sidebar initially and retains searches when reopened', () => {
  for (const standalone of [true]) {
    const {dom,w}=player({mode:standalone?'standalone':undefined,title:'course',defaultSubtitle:'zh-TW'}, {standalone,subtitles:searchable});
    const toggle=w.document.querySelector('#transcript-toggle');
    const panel=w.document.querySelector('#transcript-panel');
    assert.ok(toggle, 'viewer can expand the transcript with a button');
    assert.equal(panel.hidden,true);
    assert.equal(toggle.getAttribute('aria-expanded'),'false');
    toggle.click();
    assert.equal(panel.hidden,false);
    assert.equal(w.document.querySelector('.chapter-card').hidden,false);
    assert.equal(toggle.getAttribute('aria-expanded'),'true');
    const input=w.document.querySelector('#transcript-search');
    assert.equal(w.document.activeElement,input);
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
  w.document.querySelector('#transcript-toggle').click();
  assert.equal(w.document.querySelector('#transcript-tab').getAttribute('aria-selected'),'true');
  assert.equal(w.document.querySelector('#chapters-panel').hidden,true);
  assert.equal(w.document.querySelector('#transcript-panel').hidden,false);
  assert.equal(w.document.querySelector('.chapter-card').hidden,false);
  dom.window.close();
});
