'use strict';

const shared = require('../core/shared.cjs');

function normalizeKey(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[_\s-]+/g, '');
}

function normalizeClockSource(value, params) {
  const normalized = normalizeKey(value || params.default_clock_source || 'fsys_div4');
  const aliases = params.clock_source_aliases || {};
  if (aliases[normalized]) {
    return aliases[normalized];
  }

  const sources = params.clock_sources || {};
  const matched = Object.keys(sources).find(key => normalizeKey(key) === normalized);
  return matched || normalized;
}

function resolveTimerVariant(options, params) {
  const variants = params.timer_variants || {};
  const defaultTimer = params.default_timer || Object.keys(variants)[0] || '';
  const normalized = normalizeKey(options.timer || defaultTimer);
  const matched = Object.keys(variants).find(key => normalizeKey(key) === normalized);

  if (matched) {
    return variants[matched];
  }

  if (!matched && Object.keys(variants).length > 0) {
    throw new Error(`Unsupported timer variant: ${options.timer}`);
  }

  return params;
}

function normalizeEdge(value) {
  const normalized = String(value || 'rising').trim().toLowerCase();
  if (['rising', 'rise', 'up'].includes(normalized)) return 'rising';
  if (['falling', 'fall', 'down'].includes(normalized)) return 'falling';
  throw new Error(`Unsupported timer edge: ${value}`);
}

function resolvePrescalers(options, params) {
  if (options.prescaler !== undefined) {
    return [shared.parsePositiveNumber(options.prescaler, 'prescaler')];
  }
  return (params.prescalers || []).slice();
}

function resolvePostscalers(options, params) {
  if (options.postscaler !== undefined) {
    return [shared.parsePositiveNumber(options.postscaler, 'postscaler')];
  }
  return (params.postscalers || [1]).slice();
}

function calculateTmr0Candidate(clockHz, source, sourceKey, prescaler, edge, targetSeconds, params) {
  const effectiveClockHz = clockHz / (source.input_divider || 1) / prescaler;
  const countsExact = targetSeconds * effectiveClockHz;
  const counts = Math.round(countsExact);

  if (counts < 1 || counts > 256) {
    return null;
  }

  const reload = 256 - counts;
  const actualSeconds = counts / effectiveClockHz;
  const errorSeconds = actualSeconds - targetSeconds;
  const optionHint =
    prescaler === 1
      ? `OPTION_REG: T0LSE_EN=${source.option_t0lse_en}, T0CS=${source.option_t0cs}, T0SE=${source.supports_edge ? (edge === 'falling' ? 1 : 0) : 0}, PSA=1`
      : `OPTION_REG: T0LSE_EN=${source.option_t0lse_en}, T0CS=${source.option_t0cs}, T0SE=${source.supports_edge ? (edge === 'falling' ? 1 : 0) : 0}, PSA=0, PS=${params.prescaler_bits[String(prescaler)]}`;

  return {
    clock_source: sourceKey,
    clock_hz: clockHz,
    effective_clock_hz: shared.roundNumber(effectiveClockHz, 6),
    prescaler,
    timer_bits: 8,
    counts,
    reload,
    reload_hex: shared.formatHex(reload, 2),
    actual_us: shared.roundNumber(actualSeconds * 1000000, 6),
    actual_hz: shared.roundNumber(1 / actualSeconds, 6),
    error_us: shared.roundNumber(errorSeconds * 1000000, 6),
    error_pct: shared.roundNumber((errorSeconds / targetSeconds) * 100, 6),
    register_hints: {
      option_reg: optionHint,
      timer: `${params.timer_register} = ${reload}; // ${shared.formatHex(reload, 2)}`,
      interrupt: `${params.interrupt_flag} = 0; ${params.interrupt_enable} = 1;`,
      global: 'GIE = 1;'
    }
  };
}

function calculateTmr2Candidate(clockHz, source, sourceKey, prescaler, postscaler, targetSeconds, params) {
  const effectiveClockHz = clockHz / (source.input_divider || 1) / prescaler;
  const countsExact = (targetSeconds * effectiveClockHz) / postscaler;
  const counts = Math.round(countsExact);

  if (counts < 1 || counts > 256) {
    return null;
  }

  const pr2 = counts - 1;
  const baseSeconds = counts / effectiveClockHz;
  const actualSeconds = baseSeconds * postscaler;
  const errorSeconds = actualSeconds - targetSeconds;

  return {
    timer: params.peripheral || '',
    clock_source: sourceKey,
    clock_hz: clockHz,
    effective_clock_hz: shared.roundNumber(effectiveClockHz, 6),
    prescaler,
    postscaler,
    timer_bits: 8,
    counts,
    period_register: pr2,
    period_register_hex: shared.formatHex(pr2, 2),
    base_period_us: shared.roundNumber(baseSeconds * 1000000, 6),
    actual_us: shared.roundNumber(actualSeconds * 1000000, 6),
    actual_hz: shared.roundNumber(1 / actualSeconds, 6),
    error_us: shared.roundNumber(errorSeconds * 1000000, 6),
    error_pct: shared.roundNumber((errorSeconds / targetSeconds) * 100, 6),
    register_hints: {
      period: `${params.period_register} = ${pr2}; // ${shared.formatHex(pr2, 2)}`,
      interrupt: `${params.interrupt_flag} = 0; ${params.interrupt_enable} = 1;`,
      control: `${params.control_register}: CLK_SEL=${source.clk_sel}, TOUTPS=${params.postscaler_bits[String(postscaler)]}, TMR2ON=1, T2CKPS=${params.prescaler_bits[String(prescaler)]}`,
      global: 'GIE = 1;'
    }
  };
}

module.exports = {
  run(options, binding) {
    const rootParams = binding.params || {};
    const params = resolveTimerVariant(options, rootParams);
    const sourceKey = normalizeClockSource(options['clock-source'] || options.source, params);
    const source = (params.clock_sources || {})[sourceKey];
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
    const prescalers = resolvePrescalers(options, params);
    const postscalers = resolvePostscalers(options, params);
    const candidates = [];

    prescalers.forEach(prescaler => {
      postscalers.forEach(postscaler => {
        const candidate =
          params.kind === 'tmr2-periodic'
            ? calculateTmr2Candidate(clockHz, source, sourceKey, prescaler, postscaler, targetSeconds, params)
            : calculateTmr0Candidate(clockHz, source, sourceKey, prescaler, edge, targetSeconds, params);
        if (candidate) {
          candidates.push(candidate);
        }
      });
    });

    candidates.sort((left, right) => {
      return (
        Math.abs(left.error_us) - Math.abs(right.error_us) ||
        left.prescaler - right.prescaler ||
        (left.postscaler || 1) - (right.postscaler || 1) ||
        (left.reload ?? left.period_register ?? 0) - (right.reload ?? right.period_register ?? 0)
      );
    });

    if (candidates.length === 0) {
      return {
        status: 'unsupported',
        notes: [
          `没有找到满足目标周期的 ${params.peripheral || 'timer'} 配置。`,
          '请检查 clock-hz、clock-source、prescaler、postscaler 或目标周期。'
        ]
      };
    }

    const notes = [
      `${params.chip || 'target'} ${params.peripheral || 'timer'} 支持的预分频: ${(params.prescalers || []).join(', ')}`,
      `支持的时钟源: ${Object.keys(params.clock_sources || {}).join(', ')}`
    ];
    if ((params.postscalers || []).length > 0) {
      notes.push(`支持的后分频: ${(params.postscalers || []).join(', ')}`);
    }
    if (params.kind === 'tmr2-periodic') {
      notes.push('TMR2 中断由 PR2 匹配后再经过后分频输出触发，结果按中断周期计算。');
      notes.push('TMR2 的基础计数周期为 (PR2 + 1) * prescaler / input_clock。');
    } else {
      notes.push('TMR0 无硬件自动重装载，当前结果按溢出后软件写回 TMR0 计算。');
      notes.push('当前结果未自动补偿“写 TMR0 后停计数 2 个指令周期”的误差。');
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
      notes
    };
  }
};
