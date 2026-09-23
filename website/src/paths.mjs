const base = '/Video-to-Subtitle/';

export function routeFor(page) {
  if (page === 'home') return base;
  if (page === 'guide') return `${base}guide/`;
  throw new TypeError(`Unsupported page: ${page}`);
}

export function assetPath(name) {
  if (!/^[a-z0-9][a-z0-9._-]*$/i.test(name)) throw new TypeError(`Unsafe asset: ${name}`);
  return `${base}assets/${name}`;
}
