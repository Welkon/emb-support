'use strict';

const shared = require('../core/shared.cjs');

function normalizeClockSource(value, params) {
  const normalized = String(value || params.default_clock_source || 'sysclk')
    .trim()
    .toLowerCase()
    .replace(/[_\s-]+/g, '');
  const aliases = params.clock_source_aliases || {};
  return aliases[normalized] || normalized;
}

function normalizeOutputPin(value, params) {
  const normalized = String(value || params.default_output_pin || 'pa3')
    .trim()
    .toLowerCase()
    .replace(/[_\s-]+/g, '');
  if (!params.output_pins || !params.output_pins[normalized]) {
    throw new Error(`Unsupported output pin: ${value}`);
  }
  return normalized;
}

function normalizeResolution(value, params) {
  const normalized = String(value || params.default_resolution || 'auto').trim().toLowerCase();
  if (['auto', 'both'].includes(normalized)) {
    return (params.resolutions || []).slice();
  }
  const numeric = Number(String(normalized).replace(/bit/g, ''));
  if (!(params.resolutions || []).includes(numeric)) {
    throw new Error(`Unsupported resolution: ${value}`);
  }
  return [numeric];
}

function calculateDutyRegister(targetDuty, denominatorBase) {
  const maxRegister = denominatorBase - 1;
  const exact = (targetDuty / 100) * denominatorBase - 1;
  const register = Math.max(0, Math.min(maxRegister, Math.round(exact)));
  const actualDuty = ((register + 1) / denominatorBase) * 100;

  return {
    register,
    actualDuty
  };
}

module.exports = {
  run(options, binding) {
    const params = binding.params || {};
    const clockSource = normalizeClockSource(options['clock-source'] || options.source, params);
    if (!params.clock_sources || !params.clock_sources[clockSource]) {
      throw new Error(`Unsupported clock source: ${clockSource}`);
    }

    const outputPin = normalizeOutputPin(options['output-pin'] || options.pin, params);
    const clockHz = shared.parsePositiveNumber(
      options['clock-hz'] || options.clock_hz || options.sysclk_hz,
      'clock-hz'
    );
    const targetHz = shared.parsePositiveNumber(options['target-hz'], 'target-hz');
    const targetDuty = shared.parsePositiveNumber(
      options['target-duty'] !== undefined ? options['target-duty'] : 50,
      'target-duty'
    );
    const inverse = shared.parseBoolean(options.inverse, false);
    const resolutions = normalizeResolution(options.resolution, params);

    const candidates = [];

    resolutions.forEach(bitWidth => {
      const denominatorBase = bitWidth === 8 ? 256 : 64;
      const duty = calculateDutyRegister(targetDuty, denominatorBase);

      (params.prescalers || []).forEach(prescaler => {
        for (let divider = params.divider_min; divider <= params.divider_max; divider += 1) {
          const actualHz = clockHz / (denominatorBase * prescaler * divider);
          candidates.push({
            resolution_bits: bitWidth,
            clock_source: clockSource,
            clock_hz: clockHz,
            output_pin: outputPin,
            inverse,
            prescaler,
            divider,
            register_value: duty.register,
            register_hex: shared.formatHex(duty.register, 2),
            actual_hz: shared.roundNumber(actualHz, 6),
            actual_duty: shared.roundNumber(duty.actualDuty, 6),
            freq_error_pct: shared.roundNumber(((actualHz - targetHz) / targetHz) * 100, 6),
            duty_error_pct: shared.roundNumber(duty.actualDuty - targetDuty, 6),
            register_hints: {
              counter: `${params.counter_register} = 0;`,
              period: `${params.period_register} = ${duty.register}; // ${shared.formatHex(duty.register, 2)}`,
              scale: `$ ${params.scale_macro} ${bitWidth}BIT,/${prescaler},/${divider};`,
              mode: `$ ${params.mode_macro} ${params.clock_sources[clockSource].macro},${params.output_pins[outputPin].macro},PWM${inverse ? ',Inverse' : ''};`
            }
          });
        }
      });
    });

    candidates.sort((left, right) => {
      const leftScore = Math.abs(left.freq_error_pct) + Math.abs(left.duty_error_pct);
      const rightScore = Math.abs(right.freq_error_pct) + Math.abs(right.duty_error_pct);
      return leftScore - rightScore;
    });

    return {
      status: 'ok',
      outputs: {
        chip: params.chip || '',
        peripheral: params.peripheral || '',
        target_hz: shared.roundNumber(targetHz, 6),
        target_duty: shared.roundNumber(targetDuty, 6),
        best: candidates[0],
        candidates: candidates.slice(0, 10)
      },
      notes: [
        `${params.chip || 'target'} ${params.peripheral || 'pwm'} output pins: ${Object.keys(params.output_pins || {}).join(', ')}`,
        'Frequency and duty-cycle register formulas from this device family TM2/PWM model parameters.'
      ]
    };
  }
};
