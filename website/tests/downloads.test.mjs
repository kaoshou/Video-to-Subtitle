import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {JSDOM} from 'jsdom';
import {renderHome} from '../src/content.mjs';

const latest='https://github.com/kaoshou/Video-to-Subtitle/releases/latest';
const base='https://github.com/kaoshou/Video-to-Subtitle/releases/download/';
const suffixes=['Windows_x64_Portable.zip','Windows_x64_Setup.exe','macOS_arm64.dmg'];
const release=version=>({tag_name:`v${version}`,draft:false,prerelease:false,
  assets:suffixes.map(suffix=>({name:`VideoToSubtitle_v${version}_${suffix}`,state:'uploaded',
    browser_download_url:`${base}v${version}/VideoToSubtitle_v${version}_${suffix}`}))});

async function page(t, data, {fail=false, ok=true}={}) {
  const dom=new JSDOM(renderHome(),{url:'https://kaoshou.github.io/Video-to-Subtitle/',runScripts:'outside-only'});
  t.after(()=>dom.window.close());
  const calls=[];
  // Only the remote GitHub API boundary is controlled. Real DOM links and
  // the shipped script decide which asset a viewer will actually download.
  dom.window.fetch=async url=>{calls.push(url);if(fail)throw new Error('network');return {ok,json:async()=>data};};
  const buttons=[...dom.window.document.querySelectorAll('.hero-actions a')];
  assert.equal(buttons.length,3);
  assert.ok(buttons.every(a=>a.href===latest),'Links must work without JavaScript and never pin a version');
  const script=await readFile(new URL('../src/downloads.js',import.meta.url),'utf8');
  await dom.window.eval(script);
  assert.deepEqual(calls,['https://api.github.com/repos/kaoshou/Video-to-Subtitle/releases/latest']);
  return buttons;
}

test('download links select the three versioned assets from the latest release, not source metadata', async t=>{
  for (const version of ['2.9.1','3.0.8']) {
    const buttons=await page(t,release(version));
    assert.deepEqual(buttons.map(a=>a.href),suffixes.map(s=>`${base}v${version}/VideoToSubtitle_v${version}_${s}`));
  }
});

test('offline, API errors, missing or untrusted assets retain the usable latest-release fallback', async t=>{
  for(const scenario of [
    {fail:true}, {ok:false}, {data:null}, {data:{...release('2.9.1'),draft:true}},
    {data:{...release('2.9.1'),prerelease:true}}, {data:{...release('2.9.1'),tag_name:'../../bad'}},
    {data:{...release('2.9.1'),assets:[]}},
    {data:{...release('2.9.1'),assets:release('2.9.1').assets.map(a=>({...a,browser_download_url:'https://attacker.invalid/'+a.name}))}}
  ]) {
    const buttons=await page(t,Object.hasOwn(scenario,'data')?scenario.data:release('2.9.1'),scenario);
    assert.ok(buttons.every(a=>a.href===latest));
  }
});

test('a missing platform asset does not prevent other valid downloads', async t=>{
  const data=release('2.9.1');data.assets.splice(1,1);
  const buttons=await page(t,data);
  assert.match(buttons[0].href,/Portable.zip$/);
  assert.equal(buttons[1].href,latest);
  assert.match(buttons[2].href,/arm64.dmg$/);
});
