'use strict';
// @verified_against: ESP32-C3 TRM v1.0, Section 12 "GPTimer"
// @test_vector: clock-hz=80000000, prescaler=80, target-us=1000

const shared = require('../core/shared.cjs');

function normalizeKey(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[_\s-]+/g, '');
}

function parseInteger(value, label) {
  const numeric = shared.parsePositiveNumber(value, label);
  if (!Number.isInteger(numeric)) {
    throw new Error(`${label} must be an integer`);
  }
  return numeric;
}

function normalizeClockSource(value, params) {
  const normalized = normalizeKey(value || params.default_clock_source || 'apb_clk');
  const aliases = params.clock_source_aliases || {};
  if (aliases[normalized]) {
    return aliases[normalized];
  }

  const matched = Object.keys(params.clock_sources || {}).find(key => normalizeKey(key) === normalized);
  return matched || normalized;
}

function normalizeTimer(value, params) {
  const defaultTimer = params.default_timer || 'timer0';
  const normalized = normalizeKey(value || defaultTimer);
  const aliases = params.timer_aliases || {};
  const resolved = aliases[normalized] || normalized;
  const matched = (params.timers || []).find(item => normalizeKey(item) === normalizeKey(resolved));
  if (!matched) {
    throw new Error(`Unsupported timer: ${value}`);
  }
  return matched;
}

function resolveClockHz(options, source) {
  if (
    options['clock-hz'] !== undefined ||
    options.clock_hz !== undefined ||
    options.sysclk_hz !== undefined
  ) {
    return shared.parsePositiveNumber(
      options['clock-hz'] || options.clock_hz || options.sysclk_hz,
      'clock-hz'
    );
  }

  if (source && source.default_hz) {
    return shared.parsePositiveNumber(source.default_hz, 'clock-hz');
  }

  throw new Error('timer-calc requires --clock-hz when the selected clock source has no default_hz');
}

function resolveTargetSeconds(options) {
  if (options['target-us'] !== undefined) {
    return shared.parsePositiveNumber(options['target-us'], 'target-us') / 1000000;
  }

  if (options['target-hz'] !== undefined) {
    return 1 / shared.parsePositiveNumber(options['target-hz'], 'target-hz');
  }

  throw new Error('timer-calc requires --target-us or --target-hz');
}

function buildPrescalerList(options, params) {
  if (options.prescaler !== undefined) {
    return [parseInteger(options.prescaler, 'prescaler')];
  }

  const min = parseInteger(params.prescaler_min || 2, 'prescaler_min');
  const max = parseInteger(params.prescaler_max || 65536, 'prescaler_max');
  const values = [];

  for (let prescaler = min; prescaler <= max; prescaler += 1) {
    values.push(prescaler);
  }

  return values;
}

module.exports = {
  run(options, binding) {
    const params = binding.params || {};
    const clockSourceKey = normalizeClockSource(options['clock-source'] || options.source, params);
    const source = (params.clock_sources || {})[clockSourceKey];
    if (!source) {
      throw new Error(`Unsupported clock source for algorithm ${binding.algorithm}: ${clockSourceKey}`);
    }

    const timer = normalizeTimer(options.timer, params);
    const clockHz = resolveClockHz(options, source);
    const targetSeconds = resolveTargetSeconds(options);
    const autoReload = shared.parseBoolean(
      options['auto-reload'] !== undefined ? options['auto-reload'] : options.autoreload,
      params.default_auto_reload !== false
    );
    const safeMaxCount = Number.MAX_SAFE_INTEGER;
    const candidates = [];

    buildPrescalerList(options, params).forEach(prescaler => {
      const exactAlarmCount = (targetSeconds * clockHz) / prescaler;
      const alarmCount = Math.round(exactAlarmCount);

      if (alarmCount < 1 || alarmCount > safeMaxCount) {
        return;
      }

      const actualSeconds = (alarmCount * prescaler) / clockHz;
      const errorSeconds = actualSeconds - targetSeconds;

      candidates.push({
        timer,
        clock_source: clockSourceKey,
        clock_hz: clockHz,
        counter_bits: params.counter_bits || 54,
        prescaler,
        resolution_hz: shared.roundNumber(clockHz / prescaler, 6),
        alarm_count: alarmCount,
        auto_reload: autoReload,
        actual_us: shared.roundNumber(actualSeconds * 1000000, 6),
        actual_hz: shared.roundNumber(1 / actualSeconds, 6),
        error_us: shared.roundNumber(errorSeconds * 1000000, 6),
        error_pct: shared.roundNumber((errorSeconds / targetSeconds) * 100, 9),
        register_hints: {
          timer,
          clock_source: `clk_src = ${source.label || clockSourceKey}`,
          prescaler: `divider = ${prescaler}`,
          alarm: `alarm_count = ${alarmCount}`,
          auto_reload: `auto_reload = ${autoReload ? 'true' : 'false'}`
        }
      });
    });

    candidates.sort((left, right) => {
      return (
        Math.abs(left.error_us) - Math.abs(right.error_us) ||
        left.prescaler - right.prescaler ||
        right.alarm_count - left.alarm_count
      );
    });

    if (candidates.length === 0) {
      return {
        status: 'unsupported',
        notes: [
          'No GPTimer configuration found that meets the target period.',
          'Check clock-hz, clock-source, prescaler, or target period.'
        ]
      };
    }

    return {
      status: 'ok',
      outputs: {
        chip: params.chip || '',
        peripheral: params.peripheral || 'gptimer',
        target_us: shared.roundNumber(targetSeconds * 1000000, 6),
        best: candidates[0],
        candidates: candidates.slice(0, 10)
      },
      notes: [
        `${params.chip || 'target'} GPTimer provides ${(params.timers || []).length || 2} ${(params.counter_bits || 54)}-bit general-purpose timers.`,
        `Supported clock sources: ${Object.keys(params.clock_sources || {}).join(', ')}`,
        `Searching with prescaler range ${params.prescaler_min || 2}..${params.prescaler_max || 65536} and alarm_count model.`,
        'Period formula: actual = alarm_count * prescaler / source_clock.',
        autoReload ? 'Result computed as auto-reload periodic timer.' : 'Result computed as single-shot alarm trigger.'
      ]
    };
  }
};
