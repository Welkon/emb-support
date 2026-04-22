'use strict';

const shared = require('../core/shared.cjs');

function parseOptionalBit(value, label) {
  if (value === undefined || value === null || value === '') {
    return null;
  }

  const normalized = String(value).trim();
  if (normalized !== '0' && normalized !== '1') {
    throw new Error(`${label} must be 0 or 1`);
  }

  return Number(normalized);
}

module.exports = {
  run(options, binding) {
    const params = binding.params || {};
    const charging = shared.parseBoolean(options.charging, false);
    const chargingBias = Number(params.charging_voltage_bias || 0);
    const targetVoltage = shared.parsePositiveNumber(
      options['target-v'] || options['target-threshold-v'] || options.threshold_v,
      'target-v'
    );
    const searchTargetVoltage = charging && chargingBias > 0
      ? targetVoltage + chargingBias
      : targetVoltage;
    const statusBit = parseOptionalBit(
      options['status-bit'] !== undefined ? options['status-bit'] : options.status,
      'status-bit'
    );
    const min = shared.parsePositiveNumber(params.min_voltage, 'binding min_voltage');
    const step = shared.parsePositiveNumber(params.step_voltage, 'binding step_voltage');
    const levels = Number(params.level_count || 0);
    const max = shared.roundNumber(min + step * (levels - 1), 6);
    const candidates = [];

    for (let code = 0; code < levels; code += 1) {
      const threshold = min + step * code;
      const registerValue = code << Number(params.shift_bits || 0);
      const error = threshold - searchTargetVoltage;
      const actualBatteryEquivalent = charging && chargingBias > 0
        ? threshold - chargingBias
        : threshold;

      candidates.push({
        code,
        threshold_v: shared.roundNumber(threshold, 6),
        actual_battery_threshold_v: shared.roundNumber(actualBatteryEquivalent, 6),
        register_value: registerValue,
        register_hex: shared.formatHex(registerValue, 2),
        error_v: shared.roundNumber(error, 6),
        error_pct: shared.roundNumber((error / searchTargetVoltage) * 100, 6),
        register_hints: {
          write: `${params.register_name} = ${shared.formatHex(registerValue, 2)};`,
          comment: charging && chargingBias > 0
            ? `${shared.roundNumber(threshold, 2)}V sensed ~= ${shared.roundNumber(actualBatteryEquivalent, 2)}V battery`
            : `${shared.roundNumber(threshold, 2)}V`
        }
      });
    }

    candidates.sort((left, right) => Math.abs(left.error_v) - Math.abs(right.error_v));

    return {
      status: 'ok',
      outputs: {
        chip: params.chip || '',
        peripheral: params.peripheral || '',
        target_v: shared.roundNumber(targetVoltage, 6),
        charging,
        target_internal_v: shared.roundNumber(searchTargetVoltage, 6),
        range_v: {
          min,
          max,
          step
        },
        best: candidates[0],
        candidates: candidates.slice(0, 8),
        status: statusBit === null
          ? null
          : {
              bit: statusBit,
              meaning: statusBit === 1
                ? (charging && chargingBias > 0 ? params.status_when_set_charging || params.status_when_set : params.status_when_set)
                : (charging && chargingBias > 0 ? params.status_when_clear_charging || params.status_when_clear : params.status_when_clear)
            }
      },
      notes: [
        `${params.register_name} 使用 ${params.threshold_field || '[7:2]'} 编码阈值，当前按 ${min}V ~ ${max}V、步进 ${step}V 搜索。`,
        charging && chargingBias > 0
          ? `已按充电状态补偿内部检测偏高约 ${chargingBias}V；target-v 视为实际电池电压。`
          : '默认未启用充电偏移补偿。',
        params.interrupt_supported === false
          ? 'LVDC 不支持中断。'
          : '中断支持取决于器件实现。',
        params.wakeup_supported === false
          ? 'LVDC 不支持唤醒，只能轮询状态位。'
          : '唤醒支持取决于器件实现。'
      ]
    };
  }
};
