import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fixture} from '../../scripts/smoke_accessibility_browser.mjs';

test('historical MP4 comparisons use their actual old template, while current output uses the canonical one', async t=>{
  const root=await mkdtemp(join(tmpdir(),'vts-template-baseline-'));
  t.after(()=>rm(root,{recursive:true,force:true}));
  const source=join(root,'source'),out=join(root,'fixtures'),media=join(root,'synthetic.mp4');
  await mkdir(join(source,'assets/evercam_player/css'),{recursive:true});
  await mkdir(join(source,'assets/evercam_player/js'),{recursive:true});
  await mkdir(join(source,'assets/standalone_player'),{recursive:true});
  await writeFile(join(source,'assets/evercam_player/index.html'),'<main>canonical</main><script src="config.js"></script>');
  await writeFile(join(source,'assets/standalone_player/index.html'),'<main>legacy toolbar</main><script src="player-config.js"></script>');
  await writeFile(media,'owned synthetic fixture bytes');
  const old=await fixture(out,source,'standalone',media,'-baseline');
  assert.match(await readFile(join(old,'index.html'),'utf8'),/legacy toolbar/);
  const current=await fixture(out,source,'standalone',media);
  const currentHtml=await readFile(join(current,'index.html'),'utf8');
  assert.match(currentHtml,/canonical/);assert.match(currentHtml,/src="player-config.js"/);
  await rm(join(source,'assets/standalone_player'),{recursive:true});
  const modern=await fixture(join(root,'modern'),source,'standalone',media,'-baseline');
  assert.match(await readFile(join(modern,'index.html'),'utf8'),/canonical/);
});
