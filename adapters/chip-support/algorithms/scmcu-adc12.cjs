'use strict';

const shared = require('../core/shared.cjs');

function normalizeReferenceSource(value, params) {
  const normalized = String(value || params.default_reference_source || 'vdd')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '');
  const aliases = params.reference_source_aliases || {};
  return aliases[normalized] || normalized;
}

function normalizeChannel(value, params) {
  const normalized = String(value || params.default_channel || 'an0')
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, '');
  const aliases = {
    ...(params.channel_aliases || {}),
    ...shared.buildProjectSignalAliases({
      direction: 'input',
      keywords: ['adc', 'sample', 'voltage', 'analog'],
      target: params.default_channel || ''
    })
  };
  const resolved = shared.resolveAliasValue(normalized, aliases) || aliases[normalized] || normalized;
  if (!params.channels || !params.channels[resolved]) {
    const suggestions = shared.uniqueDisplayValues([
      String(value || '').trim(),
      params.default_channel,
      ...Object.keys(params.channels || {}).map(item => item.toUpperCase())
    ]);
    throw new Error(
      suggestions.length > 0
        ? `Unsupported adc channel: ${value}. Try ${suggestions.join(', ')}`
        : `Unsupported adc channel: ${value}`
    );
  }
  return resolved;
}

function normalizeResolution(value, params) {
  const numeric = Number(value || params.default_resolution || 12);
  if (!(params.supported_resolutions || []).includes(numeric)) {
    throw new Error(`Unsupported adc resolution: ${value}`);
  }
  return numeric;
}

function resolveReferenceVoltage(options, sourceKey, source) {
  if (source.fixed_voltage) {
    return source.fixed_voltage;
  }

  return shared.parsePositiveNumber(
    options['reference-v'] || options.reference_v || options.vdd,
    'reference-v'
  );
}

module.exports = {
  run(options, binding) {
    const params = binding.params || {};
    const referenceSourceKey = normalizeReferenceSource(options['reference-source'], params);
    const referenceSource = (params.reference_sources || {})[referenceSourceKey];
    if (!referenceSource) {
      throw new Error(`Unsupported reference source for algorithm ${binding.algorithm}: ${referenceSourceKey}`);
    }

    const channelKey = normalizeChannel(options.channel || options.source, params);
    const channel = params.channels[channelKey];
    const resolution = normalizeResolution(options.resolution, params);
    const maxCode = (2 ** resolution) - 1;
    const referenceV = resolveReferenceVoltage(options, referenceSourceKey, referenceSource);
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

    if (sampleCode !== null && (sampleCode < 0 || sampleCode > maxCode)) {
      throw new Error(`sample-code must be within 0..${maxCode}`);
    }

    const outputs = {
      chip: params.chip || '',
      peripheral: params.peripheral || '',
      reference_source: referenceSourceKey,
      reference_v: shared.roundNumber(referenceV, 6),
      resolution_bits: resolution,
      code_range: {
        min: 0,
        max: maxCode
      },
      channel: channel.name
    };
    const notes = [
      `${params.chip || 'target'} ADC reference sources: ${Object.keys(params.reference_sources || {}).join(', ')}`,
      `${params.chip || 'target'} ADC channels: ${Object.keys(params.channels || {}).join(', ')}`
    ];

    if (sampleCode !== null) {
      const convertedVoltage = (sampleCode / maxCode) * referenceV;
      outputs.sample_code = sampleCode;
      outputs.converted_voltage = shared.roundNumber(convertedVoltage, 6);
      outputs.register_hints = {
        channel: `Select ADC channel: ${channel.name}${channel.note ? ` (${channel.note})` : ''}`,
        reference: `Select reference source: ${referenceSource.label}`,
        result_format: resolution === 12 ? '12-bit left-aligned model (0..4095)' : '10-bit right-aligned model (0..1023)'
      };
    }

    if (targetVoltage !== null) {
      const exactCode = (targetVoltage / referenceV) * maxCode;
      const clippedCode = Math.max(0, Math.min(maxCode, Math.round(exactCode)));
      outputs.target_voltage = shared.roundNumber(targetVoltage, 6);
      outputs.code_estimate = {
        exact: shared.roundNumber(exactCode, 6),
        rounded: clippedCode,
        rounded_hex: shared.formatHex(clippedCode, resolution > 10 ? 3 : 2)
      };

      if (targetVoltage < 0 || targetVoltage > referenceV) {
        notes.push('target-voltage exceeds reference voltage range; result saturated to limit.');
      }
    }

    return {
      status: 'ok',
      outputs,
      notes
    };
  }
};
