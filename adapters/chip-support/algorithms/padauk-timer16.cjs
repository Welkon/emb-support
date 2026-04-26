'use strict';
// @verified_against: Padauk PMS150G Datasheet v1.2, Section 8 "Timer16"
// @test_vector: clock-hz=8000000, prescaler=16, target-us=1000, interrupt-edge=rising, interrupt-bit=10

const shared = require('../core/shared.cjs');

function normalizeClockSource(value, params) {
  const normalized = String(value || params.default_clock_source || 'sysclk')
    .trim()
    .toLowerCase()
    .replace(/[_\s-]+/g, '');

  const aliases = (params.clock_source_aliases || {});
  return aliases[normalized] || normalized;
}

function normalizeEdge(value) {
  const normalized = String(value || 'rising').trim().toLowerCase();
  if (['rising', 'rise', 'bit_r', 'up'].includes(normalized)) return 'rising';
  if (['falling', 'fall', 'bit_f', 'down'].includes(normalized)) return 'falling';
  throw new Error(`Unsupported timer interrupt edge: ${value}`);
}

function parseInterruptBits(value, params) {
  const supported = (params.interrupt_bits || []).slice();
  if (value === undefined || value === null || value === '') {
    return supported;
  }

  const values = Array.isArray(value) ? value : [value];
  return values.map(item => {
    const numeric = Number(String(item).replace(/bit/gi, ''));
    if (!supported.includes(numeric)) {
      throw new Error(`Unsupported interrupt bit: ${item}`);
    }
    return numeric;
  });
}

function calculateCandidate(clockHz, sourceKey, prescaler, interruptBit, edge, targetSeconds, params) {
  const countsExact = targetSeconds * (clockHz / prescaler);
  const threshold = edge === 'rising' ? 2 ** interruptBit : 2 ** (interruptBit + 1);
  const counts = Math.round(countsExact);

  if (counts < 1 || counts > threshold) {
    return null;
  }

  const reload = threshold - counts;
  const actualSeconds = counts / (clockHz / prescaler);
  const errorSeconds = actualSeconds - targetSeconds;

  return {
    clock_source: sourceKey,
    clock_hz: clockHz,
    prescaler,
    interrupt_bit: interruptBit,
    interrupt_edge: edge,
    threshold_counts: threshold,
    counts,
    reload,
    reload_hex: shared.formatHex(reload, 4),
    actual_us: shared.roundNumber(actualSeconds * 1000000, 6),
    actual_hz: shared.roundNumber(1 / actualSeconds, 6),
    error_us: shared.roundNumber(errorSeconds * 1000000, 6),
    error_pct: shared.roundNumber((errorSeconds / targetSeconds) * 100, 6),
    register_hints: {
      mode: `$ ${params.mode_macro} ${params.clock_sources[sourceKey].macro},/${prescaler},BIT${interruptBit};`,
      edge: edge === 'rising' ? '$ INTEGS BIT_R;' : '$ INTEGS BIT_F;',
      load: `stt16 ${reload}; // ${shared.formatHex(reload, 4)}`
    }
  };
}

function run(options, binding) {
  const params = binding.params || {};
  const sourceKey = normalizeClockSource(options['clock-source'] || options.source, params);
  const source = params.clock_sources && params.clock_sources[sourceKey];
  if (!source) {
    throw new Error(`Unsupported clock source for algorithm ${binding.algorithm}: ${sourceKey}`);
  }

  const clockHz = shared.parsePositiveNumber(
    options['clock-hz'] || options.clock_hz || options.sysclk_hz,
    'clock-hz'
  );
  const targetSeconds =
    options['target-us'] !== undefined
      ? shared.parsePositiveNumber(options['target-us'], 'target-us') / 1000000
      : options['target-hz'] !== undefined
        ? 1 / shared.parsePositiveNumber(options['target-hz'], 'target-hz')
        : null;

  if (!targetSeconds) {
    throw new Error('timer-calc requires --target-us or --target-hz');
  }

  const edge = normalizeEdge(options['interrupt-edge'] || options.edge || params.default_edge);
  const interruptBits = parseInterruptBits(options['interrupt-bit'] || options.bit, params);
  const prescalers =
    options.prescaler !== undefined
      ? [shared.parsePositiveNumber(options.prescaler, 'prescaler')]
      : (params.prescalers || []).slice();

  const candidates = [];

  prescalers.forEach(prescaler => {
    interruptBits.forEach(interruptBit => {
      const candidate = calculateCandidate(
        clockHz,
        sourceKey,
        prescaler,
        interruptBit,
        edge,
        targetSeconds,
        params
      );
      if (candidate) {
        candidates.push(candidate);
      }
    });
  });

  candidates.sort((left, right) => {
    return (
      Math.abs(left.error_us) - Math.abs(right.error_us) ||
      left.prescaler - right.prescaler ||
      left.interrupt_bit - right.interrupt_bit
    );
  });

  if (candidates.length === 0) {
    return {
      status: 'unsupported',
      notes: [
        'No configuration found that meets the target period.',
        'Check clock-hz, interrupt-edge, interrupt-bit, or target period.'
      ]
    };
  }

  return {
    status: 'ok',
    outputs: {
      chip: params.chip || '',
      peripheral: params.peripheral || '',
      target_us: shared.roundNumber(targetSeconds * 1000000, 6),
      best: candidates[0],
      candidates: candidates.slice(0, 8)
    },
    notes: [
      `${params.chip || 'target'} ${params.peripheral || 'timer'} supported prescalers: ${(params.prescalers || []).join(', ')}`,
      `Interrupt bit range: ${(params.interrupt_bits || []).map(item => `BIT${item}`).join(', ')}`,
      'Result computed for ISR reload-counter usage.'
    ]
  };
}

module.exports = {
  run
};
