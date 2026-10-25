import type { Template } from '@/api/types';

/** Match render_label_png's operator-facing 180° Turn-Tell rotation. */
export function previewAreas(t: Omit<Template, 'id'>) {
  const turnTell = t.material_sku
    ? /^(R150X150|R200X150)/i.test(t.material_sku)
    : (t.bytes_per_row === 160 && t.height === 638) || /X150|X200X150/i.test(t.name);
  return (['left', 'right'] as const).map((label, index) => {
    const side = turnTell ? (index === 0 ? 'right' : 'left') : label;
    const x0 = t[`${side}_left`] + t.gap_left;
    const x1 = t[`${side}_right`] - t.gap_right;
    return {
      label: index === 0 ? 'Left label' : 'Right label',
      x: turnTell ? t.bytes_per_row * 8 - x1 : x0,
      y: t[`${side}_top`] + t.gap_top,
      width: x1 - x0,
      height: t[`${side}_bottom`] - t.gap_bottom - t[`${side}_top`] - t.gap_top,
    };
  });
}
