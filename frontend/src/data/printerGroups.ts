import type { Printer } from '@/api/types';
import { modelsForBrand, settingsForModel } from './printerModels';

type GroupablePrinter = Pick<Printer, 'model' | 'protocol' | 'dpi'>;
type PrinterGroup<T> = {
  key: 'cable' | 'qr' | 'other';
  title: string;
  emptyMessage: string;
  printers: T[];
};
const knownModels = new Set([
  ...modelsForBrand('panduit'),
  ...modelsForBrand('brother'),
].map(model => model.value));

/** Presentation follows driver capabilities; names and brands do not determine routing. */
export function groupPrinters<T extends GroupablePrinter>(printers: readonly T[]): PrinterGroup<T>[] {
  const groups: [PrinterGroup<T>, PrinterGroup<T>, PrinterGroup<T>] = [
    {key: 'cable', title: 'Cable labels', emptyMessage: 'No cable label printers configured.', printers: []},
    {key: 'qr', title: 'QR labels', emptyMessage: 'No QR label printers configured.', printers: []},
    {key: 'other', title: 'Other printers', emptyMessage: 'No other printers configured.', printers: []},
  ];
  for (const printer of printers) {
    const model = printer.model ?? 'custom';
    // A newer server can return an unknown model. Fall back without throwing.
    const protocol = knownModels.has(model)
      ? settingsForModel(model, {protocol: printer.protocol, dpi: printer.dpi ?? 300}).protocol
      : printer.protocol;
    const index = protocol === 'brother_ql' ? 1 : ['epl2', 'ezpl', 'jscript'].includes(protocol) ? 0 : 2;
    groups[index].printers.push(printer);
  }
  return groups.filter(group => group.key !== 'other' || group.printers.length > 0);
}
