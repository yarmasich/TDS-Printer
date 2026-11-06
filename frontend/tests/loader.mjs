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
const transpile = (source) => ts.transpileModule(source.replace('import.meta.env.VITE_API_BASE_URL', 'undefined'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText;
export async function load(url, context, next) {
  if (url.endsWith('.vue')) {
    // Only the plain <script> block loads: it holds the exported helpers, while
    // <script setup> means nothing without a mounted component and a DOM.
    const {parse} = await import('vue/compiler-sfc');
    const {descriptor} = parse(await readFile(new URL(url), 'utf8'), {filename:url});
    return {format:'module', source:transpile(descriptor.script?.content ?? ''),shortCircuit:true};
  }
  if (url.endsWith('.ts')) {
    return {format:'module', source:transpile(await readFile(new URL(url), 'utf8')),shortCircuit:true};
  }
  return next(url, context);
}
