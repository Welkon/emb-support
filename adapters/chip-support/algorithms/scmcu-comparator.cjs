'use strict';

const shared = require('../core/shared.cjs');

function normalizeMode(options) {
  return options['target-vdd'] !== undefined ? 'bandgap-monitor' : 'threshold';
}

function normalizeSource(value, fallback, table, label, aliases) {
  const normalized = String(value || fallback || '')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_');
  const resolved = shared.resolveAliasValue(normalized, aliases || {}) || normalized;

  if (!table[resolved]) {
    const suggestions = shared.uniqueDisplayValues([
      String(value || '').trim(),
      fallback,
      ...Object.keys(table || {})
    ]);
    throw new Error(
      suggestions.length > 0
        ? `Unsupported ${label}: ${value}. Try ${suggestions.join(', ')}`
        : `Unsupported ${label}: ${value}`
    );
  }

  return resolved;
}

function calculateReference(item, level, vdd) {
  return (
    (item.offset_numerator / item.offset_denominator) * vdd +
    ((level + item.step_base) / item.step_denominator) * vdd
  );
}

module.exports = {
  run(options, binding) {
    const params = binding.params || {};
    const mode = normalizeMode(options);
    const negativeSourceAliases = {
      ...(params.negative_source_aliases || {}),
      ...shared.buildProjectSignalAliases({
        direction: 'input',
        keywords: ['cmp', 'comparator', 'compare'],
        target: params.default_negative_source || ''
      })
    };
    const positiveSourceAliases = {
      ...(params.positive_source_aliases || {})
    };
    const vdd =
      mode === 'bandgap-monitor'
        ? shared.parsePositiveNumber(options['target-vdd'], 'target-vdd')
        : shared.parsePositiveNumber(options.vdd, 'vdd');
    const targetThreshold =
      options['target-threshold-v'] !== undefined
        ? shared.parsePositiveNumber(options['target-threshold-v'], 'target-threshold-v')
        : options['target-ratio'] !== undefined
          ? shared.parsePositiveNumber(options['target-ratio'], 'target-ratio') * vdd
          : mode === 'bandgap-monitor'
            ? params.bandgap_voltage
            : null;

    if (!targetThreshold) {
      throw new Error(
        'comparator-threshold requires --target-threshold-v or --target-ratio; bandgap-monitor mode can use --target-vdd'
      );
    }

    const positiveSource = normalizeSource(
      options['positive-source'],
      mode === 'bandgap-monitor' ? 'vr' : params.default_positive_source,
      params.positive_sources || {},
      'positive source',
      positiveSourceAliases
    );
    const negativeSource = normalizeSource(
      options['negative-source'],
      mode === 'bandgap-monitor' ? 'bandgap' : params.default_negative_source,
      params.negative_sources || {},
      'negative source',
      negativeSourceAliases
    );

    if (positiveSource !== 'vr' && negativeSource !== 'vr') {
      return {
        status: 'unsupported',
        notes: ['SC8F072 comparator-threshold requires internal VR as either positive or negative input.']
      };
    }

    const inverse = shared.parseBoolean(options.inverse, false);
    const outputEnable = shared.parseBoolean(options['output-enable'], false);
    const candidates = [];

    (params.internal_reference_cases || []).forEach(item => {
      for (let level = 0; level <= 15; level += 1) {
        const vref = calculateReference(item, level, vdd);
        const errorVolts = vref - targetThreshold;

        candidates.push({
          rbias_h: item.rbias_h,
          rbias_l: item.rbias_l,
          rbias_bits: `${item.rbias_h}${item.rbias_l}`,
          level: level,
          level_bits: level.toString(2).padStart(4, '0'),
          formula: item.formula,
          vref_v: shared.roundNumber(vref, 6),
          error_v: shared.roundNumber(errorVolts, 6),
          error_pct: shared.roundNumber((errorVolts / targetThreshold) * 100, 6),
          register_hints: {
            cmpcon0: `CMPCON0: CMPPS=${params.positive_sources[positiveSource].cmp_ps}, CMPNS=${params.negative_sources[negativeSource].cmp_ns}, CMPNV=${inverse ? 1 : 0}, CMPOEN=${outputEnable ? 1 : 0}, CMPEN=1`,
            cmpcon1: `CMPCON1: AN_EN=1, RBIAS_H=${item.rbias_h}, RBIAS_L=${item.rbias_l}, LVDS=${level.toString(2).padStart(4, '0')}`
          }
        });
      }
    });

    candidates.sort((left, right) => Math.abs(left.error_v) - Math.abs(right.error_v));

    return {
      status: 'ok',
      outputs: {
        chip: params.chip || '',
        peripheral: params.peripheral || '',
        mode,
        vdd: shared.roundNumber(vdd, 6),
        target_threshold_v: shared.roundNumber(targetThreshold, 6),
        positive_source: positiveSource,
        negative_source: negativeSource,
        best: candidates[0],
        candidates: candidates.slice(0, 8)
      },
      notes: [
        `${params.chip || 'target'} comparator positive inputs: ${Object.keys(params.positive_sources || {}).join(', ')}`,
        `Negative inputs: ${Object.keys(params.negative_sources || {}).join(', ')}`,
        'Internal VR reference set by RBIAS_H/RBIAS_L and LVDS<3:0>.',
        'In bandgap-monitor mode, recommend positive=VR, negative=1.2V BG.'
      ]
    };
  }
};
