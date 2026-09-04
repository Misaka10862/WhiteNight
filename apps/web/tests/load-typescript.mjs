import fs from 'node:fs'
import { createRequire } from 'node:module'
import ts from 'typescript'

// Reuse the project's compiler so node:test also runs on supported Node 20.
export function loadTypescript(url) {
  const { outputText } = ts.transpileModule(fs.readFileSync(url, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  })
  const module = { exports: {} }
  new Function('module', 'exports', 'require', outputText)(module, module.exports, createRequire(url))
  return module.exports
}
