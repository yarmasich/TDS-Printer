import ts from 'typescript';
import { readFile } from 'node:fs/promises';
export async function resolve(specifier, context, next) {
  if (specifier.startsWith('@/')) specifier = new URL('../src/' + specifier.slice(2), import.meta.url).href;
  if (specifier.startsWith('file:') || specifier.startsWith('.')) {
    const url = new URL(specifier, context.parentURL).href;
    if (!/\.[a-z]+$/.test(url)) return {url: url + '.ts', shortCircuit:true};
  }
  return next(specifier, context);
}
export async function load(url, context, next) {
  if (url.endsWith('.ts')) {
    const source = (await readFile(new URL(url), 'utf8')).replace('import.meta.env.VITE_API_BASE_URL', 'undefined');
    return {format:'module', source:ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText,shortCircuit:true};
  }
  return next(url, context);
}
