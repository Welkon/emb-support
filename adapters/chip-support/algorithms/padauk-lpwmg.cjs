'use strict';

const shared = require('../core/shared.cjs');

function normalizeToken(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[_\s-]+/g, '');
}

function normalizeClockSource(value, params) {
  const normalized = normalizeToken(value || params.default_clock_source || 'sysclk');
  const aliases = params.clock_source_aliases || {};
  return aliases[normalized] || normalized;
}

function normalizeChannel(value, params) {
  const aliases = params.channel_aliases || {};
  const normalized = normalizeToken(value || params.default_channel || 'lpwmg0');
  const resolved = aliases[normalized] || normalized;

  if (!params.channels || !params.channels[resolved]) {
    throw new Error(`Unsupported LPWMG channel: ${value}`);
  }

  return resolved;
}

function normalizeOutputPin(value) {
  return normalizeToken(value);
}

function parseDutyPercent(value) {
  const duty = value === undefined ? 50 : Number(value);
  if (!Number.isFinite(duty)) {
    throw new Error('target-duty must be a finite number');
  }
  if (duty < 0 || duty > 100) {
    throw new Error('target-duty must be within 0..100');
  }
  return duty;
}

function resolveChannelAndPin(options, params) {
  const requestedChannel = options.channel || options.block || options.peripheral;
  const requestedPin = options['output-pin'] || options.pin;
  const normalizedPin = requestedPin ? normalizeOutputPin(requestedPin) : '';

  if (requestedChannel) {
    const channel = normalizeChannel(requestedChannel, params);
    const channelParams = params.channels[channel];
    const outputPin = normalizedPin || normalizeOutputPin(channelParams.default_output_pin);
    if (!channelParams.output_pins || !channelParams.output_pins[outputPin]) {
      throw new Error(`Unsupported output pin ${requestedPin || outputPin} for ${channel}`);
    }

    return { channel, outputPin };
  }

  if (!normalizedPin) {
    const channel = normalizeChannel('', params);
    const channelParams = params.channels[channel];
    const outputPin = normalizeOutputPin(channelParams.default_output_pin);
    return { channel, outputPin };
  }

  const matches = Object.entries(params.channels || {})
    .filter(([, channelParams]) => channelParams.output_pins && channelParams.output_pins[normalizedPin])
    .map(([name]) => name);

  if (matches.length === 1) {
    return { channel: matches[0], outputPin: normalizedPin };
  }

  if (matches.length > 1) {
    throw new Error(`Ambiguous output pin ${requestedPin}; please also pass --channel`);
  }

  throw new Error(`Unsupported LPWMG output pin: ${requestedPin}`);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function encodeUpperCount(counterValue) {
  const high = (counterValue >> 2) & 0xFF;
  const low = (counterValue & 0x03) << 6;
  return {
    value: counterValue,
    high,
    low,
    high_hex: shared.formatHex(high, 2),
    low_hex: shared.formatHex(low, 2)
  };
}

function encodeDutyHalfSteps(halfSteps) {
  const encoded = halfSteps - 1;
  const dutyInteger = Math.floor(encoded / 2);
  const halfBit = encoded % 2;
  const high = (dutyInteger >> 2) & 0xFF;
  const low = ((dutyInteger & 0x03) << 6) | (halfBit << 5);
  const numerator = dutyInteger + halfBit * 0.5 + 0.5;

  return {
    half_steps: halfSteps,
    duty_integer: dutyInteger,
    half_bit: halfBit,
    numerator,
    high,
    low,
    high_hex: shared.formatHex(high, 2),
    low_hex: shared.formatHex(low, 2)
  };
}

function buildControlHint(channelParams, outputPinInfo) {
  return `$ ${channelParams.control_macro} ${channelParams.output_select_macro},${outputPinInfo.macro};`;
}

module.exports = {
  run(options, binding) {
    const params = binding.params || {};
    const clockSource = normalizeClockSource(options['clock-source'] || options.source, params);
    if (!params.clock_sources || !params.clock_sources[clockSource]) {
      throw new Error(`Unsupported clock source: ${clockSource}`);
    }

    const { channel, outputPin } = resolveChannelAndPin(options, params);
    const channelParams = params.channels[channel];
    const outputPinInfo = channelParams.output_pins[outputPin];
    const clockHz = shared.parsePositiveNumber(
      options['clock-hz'] || options.clock_hz || options.sysclk_hz,
      'clock-hz'
    );
    const targetHz = shared.parsePositiveNumber(options['target-hz'], 'target-hz');
    const targetDuty = parseDutyPercent(options['target-duty']);
    const inverse = shared.parseBoolean(options.inverse, false);
    const maxCounter = Number.isFinite(Number(params.max_counter)) ? Number(params.max_counter) : 1023;
    const candidates = [];

    (params.prescalers || []).forEach(prescaler => {
      const exactCounter = clockHz / (prescaler * targetHz) - 1;
      const rawCandidates = [...new Set([Math.floor(exactCounter), Math.ceil(exactCounter)])];

      rawCandidates.forEach(counterValue => {
        if (!Number.isFinite(counterValue)) {
          return;
        }
        if (counterValue < 0 || counterValue > maxCounter) {
          return;
        }

        const periodCounts = counterValue + 1;
        const actualHz = clockHz / (prescaler * periodCounts);
        const idealHalfSteps = (targetDuty / 100) * 2 * periodCounts;
        const clampedHalfSteps = clamp(Math.round(idealHalfSteps), 1, 2 * periodCounts);
        const upper = encodeUpperCount(counterValue);
        const duty = encodeDutyHalfSteps(clampedHalfSteps);
        const actualDuty = (duty.half_steps / (2 * periodCounts)) * 100;

        candidates.push({
          clock_source: clockSource,
          clock_hz: clockHz,
          channel,
          output_pin: outputPin,
          inverse,
          prescaler,
          upper_count: counterValue,
          period_counts: periodCounts,
          upper_registers: {
            [params.upper_limit_high_register]: upper.high_hex,
            [params.upper_limit_low_register]: upper.low_hex
          },
          duty_registers: {
            [channelParams.duty_high_register]: duty.high_hex,
            [channelParams.duty_low_register]: duty.low_hex
          },
          actual_hz: shared.roundNumber(actualHz, 6),
          actual_duty: shared.roundNumber(actualDuty, 6),
          freq_error_pct: shared.roundNumber(((actualHz - targetHz) / targetHz) * 100, 6),
          duty_error_pct: shared.roundNumber(actualDuty - targetDuty, 6),
          register_hints: {
            clock: `$ ${params.clock_control_register} Enable,/${prescaler},${params.clock_sources[clockSource].macro};`,
            upper_low: `${params.upper_limit_low_register} = ${upper.low_hex};`,
            upper_high: `${params.upper_limit_high_register} = ${upper.high_hex};`,
            control: buildControlHint(channelParams, outputPinInfo),
            duty_low: `${channelParams.duty_low_register} = ${duty.low_hex};`,
            duty_high: `${channelParams.duty_high_register} = ${duty.high_hex};`,
            polarity: inverse
              ? '如需反向极性，请在 LPWMGxC 宏中补 Inverse 选项；具体参数顺序以 IDE/手册为准。'
              : '默认按非反相输出生成。'
          }
        });
      });
    });

    if (candidates.length === 0) {
      return {
        status: 'unsupported',
        notes: [
          `${params.chip || 'target'} ${params.peripheral || 'lpwmg'} 在当前输入下找不到可行 prescaler/top 组合。`,
          `已搜索 prescaler: ${(params.prescalers || []).join(', ')}；counter 上限按 ${maxCounter} 处理。`
        ]
      };
    }

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
        `${params.chip || 'target'} ${params.peripheral || 'lpwmg'} 三个通道共享 ${params.upper_limit_high_register}/${params.upper_limit_low_register} 周期寄存器。`,
        `当前按 ${maxCounter + 1} 级周期计数与 half-step duty 模型搜索，占空比分子公式为 DB + DB0*0.5 + 0.5。`,
        `${channel} 可输出到: ${Object.keys(channelParams.output_pins || {}).join(', ')}`,
        '如果选择 IHRC*2，请把 clock-hz 传成倍频后的实际频率，并同步确认 code option PWM_source。'
      ]
    };
  }
};
