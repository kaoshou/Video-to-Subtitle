import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require = createRequire(new URL('../../website/package.json', import.meta.url));
const {JSDOM} = require('jsdom');
const script = readFileSync(new URL('../../assets/evercam_player/js/evercam-modern.js', import.meta.url), 'utf8');

function player(config, {standalone = true, preferences = {}, blockedStorage = false} = {}) {
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
  if (standalone) w.VTS_PLAYER_CONFIG = config; else w.config = config;
  w.EVERCAM_SUBTITLES = {tracks:['zh-TW','en'].map(language => ({language, cues:[{start:0,end:1,text:'<script>hi</script>'}]}))};
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
