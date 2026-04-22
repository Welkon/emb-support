'use strict';

const shared = require('../core/shared.cjs');

function normalizeMode(options) {
  return options['target-vdd'] !== undefined ? 'bandgap-monitor' : 'threshold';
}

function normalizePositiveSource(value, params) {
  const normalized = String(value || params.default_positive_source || 'internal_ref')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_');

  if (!params.positive_sources || !params.positive_sources[normalized]) {
    throw new Error(`Unsupported positive source: ${value}`);
  }

  return normalized;
}

function normalizeNegativeSource(value, params, mode) {
  const fallback = mode === 'bandgap-monitor' ? 'bandgap' : params.default_negative_source || 'pa3';
  const normalized = String(value || fallback)
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_');

  if (!params.negative_sources || !params.negative_sources[normalized]) {
    throw new Error(`Unsupported negative source: ${value}`);
  }

  return normalized;
}

module.exports = {
  run(options, binding) {
    const params = binding.params || {};
    const mode = normalizeMode(options);
    const charging = shared.parseBoolean(options.charging, false);
    const chargingBias = Number(params.charging_voltage_bias || 0);
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

    const positiveSource = normalizePositiveSource(options['positive-source'], params);
    const negativeSource = normalizeNegativeSource(options['negative-source'], params, mode);
    const inverse = shared.parseBoolean(options.inverse, false);
    const syncTm2 = shared.parseBoolean(options['sync-tm2'], false);
    const outputToPa0 = shared.parseBoolean(options['output-pa0'], false);

    const candidates = [];

    (params.internal_reference_cases || []).forEach(item => {
      for (let n = 0; n <= 15; n += 1) {
        const numerator = item.base + n;
        const vref = (vdd * numerator) / item.denominator;
        const errorVolts = vref - targetThreshold;

        candidates.push({
          range_bits: item.bits,
          level_bits: n.toString(2).padStart(4, '0'),
          ratio: `${numerator}/${item.denominator}`,
          vref_v: shared.roundNumber(vref, 6),
          error_v: shared.roundNumber(errorVolts, 6),
          error_pct: shared.roundNumber((errorVolts / targetThreshold) * 100, 6),
          register_hints: {
            control: `$ ${params.control_macro} Enable${syncTm2 ? ',Sync_TM2' : ''}${inverse ? ',Inverse' : ''},${params.negative_sources[negativeSource].macro},${params.positive_sources[positiveSource].macro};`,
            select: outputToPa0
              ? `$ ${params.select_macro} Output,VDD*${numerator}/${item.denominator};`
              : `$ ${params.select_macro} VDD*${numerator}/${item.denominator};`
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
        best: candidates[0],
        candidates: candidates.slice(0, 8)
      },
      notes: [
        `${params.chip || 'target'} 比较器正输入支持: ${Object.keys(params.positive_sources || {}).join(', ')}`,
        `负输入支持: ${Object.keys(params.negative_sources || {}).join(', ')}`,
        charging && chargingBias > 0
          ? `充电状态下内部 bandgap/参考检测值可能比实际电池电压高约 ${chargingBias}V；当前结果未自动改写阈值，只给出风险提示。`
          : '默认未启用充电偏移提示。',
        params.bandgap_wakeup_supported === false
          ? 'bandgap 不支持比较器唤醒。'
          : 'bandgap 唤醒支持取决于器件配置。'
      ]
    };
  }
};
