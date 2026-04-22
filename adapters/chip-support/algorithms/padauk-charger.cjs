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

function buildStatusEntry(bit, whenSet, whenClear) {
  if (bit === null) {
    return null;
  }

  return {
    bit,
    meaning: bit === 1 ? whenSet : whenClear
  };
}

function computeRequiredFullSeconds(capacityMah, params) {
  if (!Number.isFinite(capacityMah) || capacityMah <= 0) {
    return null;
  }

  const mahPerHour = Number(params.capacity_rule_mah_per_hour || 500);
  if (!Number.isFinite(mahPerHour) || mahPerHour <= 0) {
    return null;
  }

  return Math.ceil(capacityMah / mahPerHour) * 3600;
}

module.exports = {
  run(options, binding) {
    const params = binding.params || {};
    const targetCurrent = options['target-current-ma'] !== undefined
      ? shared.parsePositiveNumber(options['target-current-ma'], 'target-current-ma')
      : null;
    const chargeIndicator = parseOptionalBit(options['charge-indicator'], 'charge-indicator');
    const vccGreaterThanVbat = parseOptionalBit(options['vcc-greater-than-vbat'], 'vcc-greater-than-vbat');
    const vccNormal = parseOptionalBit(options['vcc-normal'], 'vcc-normal');
    const chargeCompleteIndicator = parseOptionalBit(
      options['charge-complete-indicator'],
      'charge-complete-indicator'
    );
    const v400Flag = parseOptionalBit(options['v400-flag'], 'v400-flag');
    const holdSeconds = options['hold-seconds'] !== undefined
      ? shared.parsePositiveNumber(options['hold-seconds'], 'hold-seconds')
      : null;
    const batteryCapacityMah = options['battery-capacity-mah'] !== undefined
      ? shared.parsePositiveNumber(options['battery-capacity-mah'], 'battery-capacity-mah')
      : null;
    const currentSteps = Array.isArray(params.current_steps_ma) ? params.current_steps_ma.slice() : [];

    let currentCandidates = [];
    if (targetCurrent !== null) {
      currentCandidates = currentSteps.map(current => ({
        current_ma: current,
        error_ma: shared.roundNumber(current - targetCurrent, 6),
        error_pct: shared.roundNumber(((current - targetCurrent) / targetCurrent) * 100, 6),
        register_hints: {
          control: `$ ${params.control_macro} ${current}mA;`
        }
      }));
      currentCandidates.sort((left, right) => Math.abs(left.error_ma) - Math.abs(right.error_ma));
    }

    const status = {
      charge_indicator: buildStatusEntry(
        chargeIndicator,
        params.status_bits && params.status_bits.charge_indicator && params.status_bits.charge_indicator.when_set,
        params.status_bits && params.status_bits.charge_indicator && params.status_bits.charge_indicator.when_clear
      ),
      vcc_greater_than_vbat: buildStatusEntry(
        vccGreaterThanVbat,
        params.status_bits && params.status_bits.vcc_greater_than_vbat && params.status_bits.vcc_greater_than_vbat.when_set,
        params.status_bits && params.status_bits.vcc_greater_than_vbat && params.status_bits.vcc_greater_than_vbat.when_clear
      ),
      vcc_normal: buildStatusEntry(
        vccNormal,
        params.status_bits && params.status_bits.vcc_normal && params.status_bits.vcc_normal.when_set,
        params.status_bits && params.status_bits.vcc_normal && params.status_bits.vcc_normal.when_clear
      ),
      charge_complete_indicator: buildStatusEntry(
        chargeCompleteIndicator,
        params.status_bits &&
          params.status_bits.charge_complete_indicator &&
          params.status_bits.charge_complete_indicator.when_set,
        params.status_bits &&
          params.status_bits.charge_complete_indicator &&
          params.status_bits.charge_complete_indicator.when_clear
      ),
      v400_flag: buildStatusEntry(
        v400Flag,
        params.status_bits && params.status_bits.v400_flag && params.status_bits.v400_flag.when_set,
        params.status_bits && params.status_bits.v400_flag && params.status_bits.v400_flag.when_clear
      )
    };

    const v5InputPresent = vccGreaterThanVbat === null || vccNormal === null
      ? null
      : (vccGreaterThanVbat === 1 && vccNormal === 1);
    const legacyQuickFull = chargeIndicator === null || v400Flag === null || holdSeconds === null
      ? null
      : (chargeIndicator === 1 && v400Flag === 1 && holdSeconds >= Number(params.legacy_full_hold_seconds || 1));
    const requiredFullSeconds = computeRequiredFullSeconds(batteryCapacityMah, params);
    const timedFull = v400Flag === null || holdSeconds === null || requiredFullSeconds === null
      ? null
      : (v400Flag === 1 && holdSeconds >= requiredFullSeconds);
    const pmb180bComplete = chargeCompleteIndicator === null
      ? null
      : (chargeCompleteIndicator === 0);

    let inferredState = null;
    if (v5InputPresent === true) {
      inferredState = '外部充电输入已接入且 VCC 电压正常。';
    } else if (v5InputPresent === false && vccNormal === 0) {
      inferredState = 'VCC 电压过低，充电器已关闭。';
    } else if (v5InputPresent === false && vccGreaterThanVbat === 0) {
      inferredState = 'VCC 未高于 VBAT，当前不满足正常充电输入条件。';
    }

    const fullCharge = {
      v5_input_present: v5InputPresent,
      legacy_chgctrl_v400_rule: legacyQuickFull,
      timed_v400_rule: timedFull,
      required_full_seconds: requiredFullSeconds,
      pmb180b_complete_indicator_rule: pmb180bComplete,
      final: pmb180bComplete !== null
        ? pmb180bComplete
        : (legacyQuickFull === true || timedFull === true ? true : null)
    };

    return {
      status: 'ok',
      outputs: {
        chip: params.chip || '',
        peripheral: params.peripheral || '',
        target_current_ma: targetCurrent,
        best: currentCandidates[0] || null,
        candidates: currentCandidates.slice(0, 8),
        status,
        inferred_state: inferredState,
        full_charge: fullCharge
      },
      notes: [
        `${params.control_macro} 当前支持离散充电电流档: ${currentSteps.join(', ')} mA。`,
        params.auto_start_note || '该充电模块是否上电自动工作取决于器件定义。',
        '5V 输入判定不要只看 CHG_TEMP.4，必须同时满足 CHG_TEMP.4 && CHG_TEMP.3。',
        'PMB180 老版本判满不能只看 CHG_CTRL.0，需结合 V400_FG 与持续时间。',
        'PMB180B 的 CHG_TEMP.1 语义按实测修正为: 高电平=充电中，低电平=充电完成。',
        '如果只传状态位，不传 target-current-ma，也可以当作状态解码器使用。'
      ]
    };
  }
};
