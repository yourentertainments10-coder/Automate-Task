// Runs after `vite build`: stamps a unique version into dist/sw.js so every
// deploy is a detectable update for installed PWAs.
import { readFileSync, writeFileSync } from 'node:fs'

const path = new URL('./dist/sw.js', import.meta.url)
const version = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)
writeFileSync(path, readFileSync(path, 'utf8').replaceAll('__BUILD_VERSION__', version))
console.log('sw.js stamped with version', version)
