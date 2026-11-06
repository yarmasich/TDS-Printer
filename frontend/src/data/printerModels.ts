import type { Printer, PrinterProtocol } from '@/api/types';

export type PrinterBrand = 'panduit' | 'brother' | 'custom';
type Model = Printer['model'];
type KnownModel = Exclude<Model, 'custom'>;
type Settings = Pick<Printer, 'protocol' | 'dpi'>;
type BrandSelection = Settings & { brand: PrinterBrand | null; model: Model | null };

export function changePrinterBrand(current: BrandSelection, brand: PrinterBrand | null): BrandSelection {
  // PrimeVue emits change even when the already selected option is clicked again.
  if (current.brand === brand) return { ...current };
  return { brand, model: brand === 'custom' ? 'custom' : null, protocol: 'epl2', dpi: 300 };
}

const profiles = {
  DP4300M: { brand: 'panduit', protocol: 'jscript', dpi: 300 },
  DP4300H: { brand: 'panduit', protocol: 'jscript', dpi: 300 },
  DP4600H: { brand: 'panduit', protocol: 'jscript', dpi: 600 },
  DP4300HD: { brand: 'panduit', protocol: 'jscript', dpi: 300 },
  TDP43ME: { brand: 'panduit', protocol: 'ezpl', dpi: 300 },
  'QL-1110NWBc': { brand: 'brother', protocol: 'brother_ql', dpi: 300 },
} satisfies Record<KnownModel, { brand: Exclude<PrinterBrand, 'custom'>; protocol: PrinterProtocol; dpi: number }>;

export function brandForModel(model: Model | undefined): PrinterBrand {
  return model && model !== 'custom' ? profiles[model]?.brand ?? 'custom' : 'custom';
}

export function modelsForBrand(brand: PrinterBrand | null): { label: string; value: Model }[] {
  if (brand === 'custom') return [{ label: 'Manual configuration', value: 'custom' }];
  return (Object.keys(profiles) as KnownModel[])
    .filter(model => profiles[model].brand === brand)
    .map(model => ({ label: model, value: model }));
}

export function settingsForModel(model: Model, current: Settings): Pick<Printer, 'model' | 'protocol' | 'dpi'> {
  if (model === 'custom') return { model, protocol: current.protocol, dpi: current.dpi };
  const profile = profiles[model];
  if (!profile) throw new Error('Unsupported printer model');
  return { model, protocol: profile.protocol, dpi: profile.dpi };
}

export function isValidPrinterSelection(brand: PrinterBrand | null, model: Model | null,
                                        protocol: PrinterProtocol, dpi: number): boolean {
  if (!brand || !model || brandForModel(model) !== brand) return false;
  if (model !== 'custom') return Object.prototype.hasOwnProperty.call(profiles, model);
  return ['epl2', 'ezpl', 'jscript'].includes(protocol) && [203, 300, 600].includes(dpi);
}
