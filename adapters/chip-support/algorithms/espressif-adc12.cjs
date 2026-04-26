'use strict';

const shared = require('../core/shared.cjs');

function normalizeKey(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[_\s-]+/g, '');
}

function normalizeReferenceSource(value, params) {
  const normalized = normalizeKey(value || params.default_reference_source || 'internal_vref');
  const aliases = params.reference_source_aliases || {};
  if (aliases[normalized]) {
    return aliases[normalized];
  }

  const matched = Object.keys(params.reference_sources || {}).find(key => normalizeKey(key) === normalized);
  return matched || normalized;
}

function normalizeAttenuation(value, params) {
  const normalized = normalizeKey(value || params.default_attenuation || '12db');
  const aliases = params.attenuation_aliases || {};
  if (aliases[normalized]) {
    return aliases[normalized];
  }

  const matched = Object.keys(params.attenuation_profiles || {}).find(key => normalizeKey(key) === normalized);
  return matched || normalized;
}

function normalizeChannel(value, params) {
  const normalized = normalizeKey(value || params.default_channel || 'adc1_ch0');
  const aliases = {
    ...(params.channel_aliases || {}),
    ...shared.buildProjectSignalAliases({
      direction: 'input',
      keywords: ['adc', 'sample', 'voltage', 'analog'],
      target: params.default_channel || ''
    })
  };
  const resolved = shared.resolveAliasValue(normalized, aliases) || aliases[normalized] || normalized;
  const matched = Object.keys(params.channels || {}).find(key => normalizeKey(key) === normalizeKey(resolved));

  if (!matched) {
    const suggestions = shared.uniqueDisplayValues([
      String(value || '').trim(),
      params.default_channel,
      ...Object.keys(params.channels || {})
    ]);
    throw new Error(
      suggestions.length > 0
        ? `Unsupported adc channel: ${value}. Try ${suggestions.join(', ')}`
        : `Unsupported adc channel: ${value}`
    );
  }

  return matched;
}

function normalizeResolution(value, params) {
  const numeric = Number(value || params.default_resolution || 12);
  if (!(params.supported_resolutions || []).includes(numeric)) {
    throw new Error(`Unsupported adc resolution: ${value}`);
  }
  return numeric;
}

module.exports = {
  run(options, binding) {
    const params = binding.params || {};
    const referenceSourceKey = normalizeReferenceSource(options['reference-source'], params);
    const referenceSource = (params.reference_sources || {})[referenceSourceKey];
    if (!referenceSource) {
      throw new Error(`Unsupported reference source for algorithm ${binding.algorithm}: ${referenceSourceKey}`);
    }

    const attenuationKey = normalizeAttenuation(options.attenuation || options['attenuation-db'], params);
    const attenuation = (params.attenuation_profiles || {})[attenuationKey];
    if (!attenuation) {
      throw new Error(`Unsupported attenuation: ${options.attenuation || options['attenuation-db']}`);
    }

    const channelKey = normalizeChannel(options.channel || options.source, params);
    const channel = params.channels[channelKey];
    const resolution = normalizeResolution(options.resolution, params);
    const maxCode = (2 ** resolution) - 1;
    const referenceV = Number(referenceSource.fixed_voltage);
    const fullScaleV = Number(attenuation.full_scale_v);
    const sampleCode =
      options['sample-code'] !== undefined || options.code !== undefined
        ? shared.parseNumber(options['sample-code'] !== undefined ? options['sample-code'] : options.code, 'sample-code')
        : null;
    const targetVoltage =
      options['target-voltage'] !== undefined
        ? shared.parseNumber(options['target-voltage'], 'target-voltage')
        : null;

    if (sampleCode === null && targetVoltage === null) {
      throw new Error('adc-scale requires --sample-code or --target-voltage');
    }

    if (sampleCode !== null && (!Number.isInteger(sampleCode) || sampleCode < 0 || sampleCode > maxCode)) {
      throw new Error(`sample-code must be an integer within 0..${maxCode}`);
    }

    const outputs = {
      chip: params.chip || '',
      peripheral: params.peripheral || 'adc12',
      reference_source: referenceSourceKey,
      reference_v: shared.roundNumber(referenceV, 6),
      attenuation: attenuationKey,
      input_range_v: {
        min: 0,
        max: shared.roundNumber(fullScaleV, 6)
      },
      resolution_bits: resolution,
      code_range: {
        min: 0,
        max: maxCode
      },
      channel: channel.name,
      gpio: channel.gpio
    };
    const notes = [
      `${params.chip || 'target'} SAR ADC computed using ${resolution}-bit result model.`,
      `Supported attenuation levels: ${Object.keys(params.attenuation_profiles || {}).join(', ')}`,
      'Voltage conversion: voltage = code / 4095 * full_scale (approximation).'
    ];

    if (channel.warning) {
      notes.push(channel.warning);
    }

    if (sampleCode !== null) {
      const convertedVoltage = (sampleCode / maxCode) * fullScaleV;
      outputs.sample_code = sampleCode;
      outputs.converted_voltage = shared.roundNumber(convertedVoltage, 6);
      outputs.converted_voltage_mv = shared.roundNumber(convertedVoltage * 1000, 3);
      outputs.register_hints = {
        channel: `channel = ${channel.name} (${channel.gpio})`,
        attenuation: `attenuation = ${attenuation.label}`,
        reference: `reference = ${referenceSource.label}`,
        range: `expected_input_range = 0 .. ${shared.roundNumber(fullScaleV, 6)} V`
      };
    }

    if (targetVoltage !== null) {
      const exactCode = (targetVoltage / fullScaleV) * maxCode;
      const clippedCode = Math.max(0, Math.min(maxCode, Math.round(exactCode)));
      outputs.target_voltage = shared.roundNumber(targetVoltage, 6);
      outputs.code_estimate = {
        exact: shared.roundNumber(exactCode, 6),
        rounded: clippedCode,
        rounded_hex: shared.formatHex(clippedCode, 3)
      };

      if (targetVoltage < 0 || targetVoltage > fullScaleV) {
        notes.push('target-voltage exceeds approximate range of current attenuation; result saturated to limit.');
      }
    }

    return {
      status: 'ok',
      outputs,
      notes
    };
  }
};
