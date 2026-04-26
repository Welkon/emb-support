'use strict';

const shared = require('../core/shared.cjs');

function normalizeClockSource(value, params) {
  const normalized = String(value || params.default_clock_source || 'fhsi')
    .trim()
    .toLowerCase()
    .replace(/[_\s-]+/g, '');
  const aliases = params.clock_source_aliases || {};
  return aliases[normalized] || normalized;
}

function normalizeOutputPin(value, params) {
  const normalized = String(value || params.default_output_pin || '')
    .trim()
    .toLowerCase()
    .replace(/[_\s]+/g, '-');
  const aliases = {
    ...(params.output_pin_aliases || {}),
    ...shared.buildProjectSignalAliases({
      direction: 'output',
      keywords: ['pwm', 'dimming'],
      target: params.default_output_pin || ''
    })
  };
  const resolved = shared.resolveAliasValue(normalized, aliases) || aliases[normalized] || normalized;
  if (!params.output_pins || !params.output_pins[resolved]) {
    const suggestions = shared.uniqueDisplayValues([
      String(value || '').trim(),
      params.default_output_pin,
      ...Object.values(params.output_pins || {}).map(item => String((item && item.pin) || '').toUpperCase()),
      ...Object.keys(params.output_pins || {})
    ]);
    throw new Error(
      suggestions.length > 0
        ? `Unsupported output pin: ${value}. Try ${suggestions.join(', ')}`
        : `Unsupported output pin: ${value}`
    );
  }
  return resolved;
}

function buildPeriodHints(period, outputPinConfig) {
  const low = period & 0xff;
  const high = (period >> 8) & 0x03;

  if (outputPinConfig.channel === 4) {
    return {
      period_low: `PWMT4L = ${low}; // ${shared.formatHex(low, 2)}`,
      period_high: `PWMTH<3:2> = ${high.toString(2).padStart(2, '0')}`
    };
  }

  return {
    period_low: `PWMTL = ${low}; // ${shared.formatHex(low, 2)}`,
    period_high: `PWMTH<1:0> = ${high.toString(2).padStart(2, '0')}`
  };
}

function buildDutyHints(duty, outputPinConfig) {
  const low = duty & 0xff;
  const high = (duty >> 8) & 0x03;

  return {
    duty_low: `${outputPinConfig.duty_low_register} = ${low}; // ${shared.formatHex(low, 2)}`,
    duty_high: `${outputPinConfig.duty_high_register} ${outputPinConfig.duty_high_bits} = ${high.toString(2).padStart(2, '0')}`
  };
}

module.exports = {
  run(options, binding) {
    const params = binding.params || {};
    const clockSource = normalizeClockSource(options['clock-source'] || options.source, params);
    const source = (params.clock_sources || {})[clockSource];
    if (!source) {
      throw new Error(`Unsupported clock source for algorithm ${binding.algorithm}: ${clockSource}`);
    }

    const outputPinKey = normalizeOutputPin(options['output-pin'] || options.pin, params);
    const outputPin = params.output_pins[outputPinKey];
    const clockHz = shared.parsePositiveNumber(
      options['clock-hz'] || options.clock_hz || options.fhsi_hz || options.sysclk_hz,
      'clock-hz'
    );
    const targetHz = shared.parsePositiveNumber(options['target-hz'], 'target-hz');
    const targetDuty = shared.parsePositiveNumber(
      options['target-duty'] !== undefined ? options['target-duty'] : 50,
      'target-duty'
    );

    const candidates = [];

    (params.dividers || []).forEach(divider => {
      const exactPeriod = clockHz / (targetHz * divider) - 1;
      const period = Math.round(exactPeriod);

      if (period < 0 || period > 1023) {
        return;
      }

      const exactDuty = ((targetDuty / 100) * (period + 1)) - 1;
      const duty = Math.max(0, Math.min(period, Math.round(exactDuty)));
      const actualHz = clockHz / ((period + 1) * divider);
      const actualDuty = ((duty + 1) / (period + 1)) * 100;

      candidates.push({
        clock_source: clockSource,
        clock_hz: clockHz,
        output_pin: outputPin.pin,
        output_group: outputPin.group,
        channel: outputPin.channel,
        divider,
        period_value: period,
        period_hex: shared.formatHex(period, 4),
        duty_value: duty,
        duty_hex: shared.formatHex(duty, 4),
        actual_hz: shared.roundNumber(actualHz, 6),
        actual_duty: shared.roundNumber(actualDuty, 6),
        freq_error_pct: shared.roundNumber(((actualHz - targetHz) / targetHz) * 100, 6),
        duty_error_pct: shared.roundNumber(actualDuty - targetDuty, 6),
        register_hints: {
          io_group: `PWMCON1: PWMIO_SEL=${outputPin.group_bits} (group ${outputPin.group.toUpperCase()} -> ${outputPin.pin}/${outputPin.channel_label})`,
          ...buildPeriodHints(period, outputPin),
          ...buildDutyHints(duty, outputPin),
          enable: `PWMCON0: CLKDIV=${source.divider_bits[String(divider)]} (/${divider}), ${outputPin.enable_bit}=1`
        }
      });
    });

    candidates.sort((left, right) => {
      const leftScore = Math.abs(left.freq_error_pct) + Math.abs(left.duty_error_pct);
      const rightScore = Math.abs(right.freq_error_pct) + Math.abs(right.duty_error_pct);
      return leftScore - rightScore;
    });

    if (candidates.length === 0) {
      return {
        status: 'unsupported',
        notes: [
          'No 10-bit PWM configuration found that meets the target frequency.',
          'Check clock-hz, target-hz, or output channel.'
        ]
      };
    }

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
        `${params.chip || 'target'} 10-bit PWM clock is fixed from FHSI; system clock divider does not affect PWM frequency.`,
        `Supported PWM outputs: ${Object.values(params.output_pins || {}).map(item => item.pin).join(', ')}`,
        'PWM0~PWM3 share a period register; PWM4 uses an independent period register.',
        'At 0% target duty, keeping PWM enabled may still produce a minimum pulse; disable PWMEN for pure low output.'
      ]
    };
  }
};
