// Keep developer-tool identity/settings while replacing generated files.
const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')

const variant = process.argv[2]
if (!['dev', 'build'].includes(variant)) throw new Error('Expected dev or build')
const root = path.resolve(__dirname, '..')
const output = path.join(root, 'dist', variant, 'mp-weixin')
const configs = new Map(['project.config.json', 'project.private.config.json'].map(name => {
  const file = path.join(output, name)
  return [file, fs.existsSync(file) ? fs.readFileSync(file) : null]
}))

// A structural page change must reload its JS and WXML together. Hot reload
// kept an old render function against the new template in the local simulator.
function disableHotReload(bytes) {
  const config = bytes ? JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/, '')) : {}
  config.setting = { ...config.setting, compileHotReLoad: false }
  return Buffer.from(JSON.stringify(config, null, 2) + '\n')
}
if (variant === 'dev') {
  const privateFile = path.join(output, 'project.private.config.json')
  configs.set(privateFile, disableHotReload(configs.get(privateFile)))
  fs.mkdirSync(output, { recursive: true })
  fs.writeFileSync(privateFile, configs.get(privateFile))
}

let result
try {
  const args = [path.join(root, 'node_modules/@dcloudio/vite-plugin-uni/bin/uni.js'), 'build', '-p', 'mp-weixin', '--outDir', output]
  if (variant === 'dev') args.push('--mode', 'development')
  result = spawnSync(process.execPath, args, { cwd: root, stdio: 'inherit' })
} finally {
  fs.mkdirSync(output, { recursive: true })
  for (const [file, bytes] of configs) if (bytes) fs.writeFileSync(file, bytes)
}
if (result.error) throw result.error
process.exitCode = result.status ?? 1
