'use strict';

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
    throw new Error(`Unsupported LEDC timer: ${value}`);
  }
  return matched;
}

function normalizeChannel(value, params) {
  const defaultChannel = params.default_channel || 'pwm0';
  const normalized = normalizeKey(value || defaultChannel);
  const aliases = params.channel_aliases || {};
  const resolved = aliases[normalized] || normalized;
  const matched = (params.channels || []).find(item => normalizeKey(item) === normalizeKey(resolved));
  if (!matched) {
    throw new Error(`Unsupported LEDC channel: ${value}`);
  }
  return matched;
}

function normalizeOutputPin(value, params) {
  const normalized = normalizeKey(value || params.default_output_pin || '');
  const aliases = {
    ...(params.output_pin_aliases || {}),
    ...shared.buildProjectSignalAliases({
      direction: 'output',
      keywords: ['pwm', 'ledc', 'output'],
      target: params.default_output_pin || ''
    })
  };
  const resolved = shared.resolveAliasValue(normalized, aliases) || aliases[normalized] || normalized;
  const matched = Object.keys(params.output_pins || {}).find(key => normalizeKey(key) === normalizeKey(resolved));

  if (!matched) {
    const suggestions = shared.uniqueDisplayValues([
      String(value || '').trim(),
      params.default_output_pin,
      ...Object.keys(params.output_pins || {})
    ]);
    throw new Error(
      suggestions.length > 0
        ? `Unsupported output pin: ${value}. Try ${suggestions.join(', ')}`
        : `Unsupported output pin: ${value}`
    );
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

  throw new Error('pwm-calc requires --clock-hz when the selected clock source has no default_hz');
}

function resolveDutyPercent(options) {
  const duty = shared.parseNumber(
    options['target-duty'] !== undefined ? options['target-duty'] : 50,
    'target-duty'
  );
  if (duty < 0 || duty > 100) {
    throw new Error('target-duty must be within 0..100');
  }
  return duty;
}

function buildResolutionList(options, params) {
  if (options['duty-resolution'] !== undefined || options.resolution !== undefined) {
    return [parseInteger(options['duty-resolution'] !== undefined ? options['duty-resolution'] : options.resolution, 'duty-resolution')];
  }

  const min = parseInteger(params.duty_resolution_min || 1, 'duty_resolution_min');
  const max = parseInteger(params.duty_resolution_max || 14, 'duty_resolution_max');
  const values = [];

  for (let resolution = min; resolution <= max; resolution += 1) {
    values.push(resolution);
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
    const channel = normalizeChannel(options.channel, params);
    const outputPinKey = normalizeOutputPin(options['output-pin'] || options.pin, params);
    const outputPin = params.output_pins[outputPinKey];
    const clockHz = resolveClockHz(options, source);
    const targetHz = shared.parsePositiveNumber(options['target-hz'], 'target-hz');
    const targetDuty = resolveDutyPercent(options);
    const dividerStep = 1 / (2 ** (params.divider_fractional_bits || 8));
    const dividerMin = Number(params.divider_min || 1);
    const dividerMax = Number(params.divider_max || ((2 ** (params.divider_integer_bits || 10)) - dividerStep));
    const candidates = [];

    buildResolutionList(options, params).forEach(dutyResolution => {
      const dutySteps = 2 ** dutyResolution;
      const dividerExact = clockHz / (targetHz * dutySteps);
      const divider = Math.round(dividerExact / dividerStep) * dividerStep;

      if (divider < dividerMin || divider > dividerMax) {
        return;
      }

      const actualHz = clockHz / (divider * dutySteps);
      const dutyCode = Math.max(0, Math.min(dutySteps, Math.round((targetDuty / 100) * dutySteps)));
      const actualDuty = (dutyCode / dutySteps) * 100;
      const dividerInteger = Math.floor(divider);
      const dividerFraction = Math.round((divider - dividerInteger) / dividerStep);

      candidates.push({
        timer,
        channel,
        clock_source: clockSourceKey,
        clock_hz: clockHz,
        output_pin: outputPin.pin,
        gpio_matrix: true,
        duty_resolution_bits: dutyResolution,
        divider: shared.roundNumber(divider, 8),
        divider_integer: dividerInteger,
        divider_fraction: dividerFraction,
        target_steps: dutySteps,
        duty_code: dutyCode,
        actual_hz: shared.roundNumber(actualHz, 6),
        actual_duty: shared.roundNumber(actualDuty, 6),
        freq_error_pct: shared.roundNumber(((actualHz - targetHz) / targetHz) * 100, 9),
        duty_error_pct: shared.roundNumber(actualDuty - targetDuty, 9),
        register_hints: {
          timer_select: `timer = ${timer}`,
          channel: `channel = ${channel}`,
          clock_source: `clk_src = ${source.label || clockSourceKey}`,
          divider: `divider = ${dividerInteger} + ${dividerFraction}/256`,
          duty_resolution: `duty_resolution = ${dutyResolution} bits`,
          duty: `duty_code = ${dutyCode}`,
          gpio_matrix: `${channel} -> ${outputPin.pin}`
        }
      });
    });

    candidates.sort((left, right) => {
      return (
        (Math.abs(left.freq_error_pct) + Math.abs(left.duty_error_pct)) -
          (Math.abs(right.freq_error_pct) + Math.abs(right.duty_error_pct)) ||
        right.duty_resolution_bits - left.duty_resolution_bits ||
        left.divider - right.divider
      );
    });

    if (candidates.length === 0) {
      return {
        status: 'unsupported',
        notes: [
          'No LEDC PWM configuration found that meets the target frequency.',
          'Check clock-hz, clock-source, target-hz, duty-resolution, or output pin.'
        ]
      };
    }

    const notes = [
      `${params.chip || 'target'} LEDC provides ${(params.timers || []).length || 4} timers and ${(params.channels || []).length || 6} channels.`,
      `Supported clock sources: ${Object.keys(params.clock_sources || {}).join(', ')}`,
      'Frequency formula: f_pwm = source_clock / (divider * 2^duty_resolution).',
      'LEDC output is routed through the GPIO matrix; not bound to fixed PWM pins.'
    ];
    if (clockSourceKey === 'rc_fast_clk') {
      notes.push('RC_FAST clock can maintain PWM output during Light-sleep mode.');
    }
    if (outputPin && Array.isArray(outputPin.notes) && outputPin.notes.length > 0) {
      notes.push(...outputPin.notes);
    }

    return {
      status: 'ok',
      outputs: {
        chip: params.chip || '',
        peripheral: params.peripheral || 'ledc',
        target_hz: shared.roundNumber(targetHz, 6),
        target_duty: shared.roundNumber(targetDuty, 6),
        best: candidates[0],
        candidates: candidates.slice(0, 10)
      },
      notes
    };
  }
};
