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
