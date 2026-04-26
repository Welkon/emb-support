'use strict';

const fs = require('fs');
const path = require('path');

function normalizeValue(value) {
  return String(value || '')
    .trim()
    .toLowerCase();
}

function normalizeLookupToken(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[_\s-]+/g, '');
}

function parseOptions(context) {
  return context.parseLongOptions(context.tokens || []);
}

function parseBoolean(value, fallback) {
  if (value === undefined || value === null || value === '') {
    return Boolean(fallback);
  }

  const normalized = normalizeValue(value);
  if (['1', 'true', 'yes', 'y', 'on'].includes(normalized)) return true;
  if (['0', 'false', 'no', 'n', 'off'].includes(normalized)) return false;
  return Boolean(fallback);
}

function parseNumber(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    throw new Error(`${label} must be a finite number`);
  }
  return number;
}

function parsePositiveNumber(value, label) {
  const number = parseNumber(value, label);
  if (number <= 0) {
    throw new Error(`${label} must be > 0`);
  }
  return number;
}

function roundNumber(value, digits) {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

function formatHex(value, width) {
  return `0x${Number(value).toString(16).toUpperCase().padStart(width, '0')}`;
}

function parseScalar(value) {
  const text = String(value || '').trim();
  if (!text) {
    return '';
  }

  if (/^(true|false)$/i.test(text)) {
    return text.toLowerCase() === 'true';
  }

  return text.replace(/^['"]|['"]$/g, '');
}

function parseScalarByKey(content, key) {
  const line = String(content || '')
    .split(/\r?\n/)
    .find(item => item.trim().startsWith(`${key}:`));

  if (!line) {
    return '';
  }

  return parseScalar(
    line
      .split(':')
      .slice(1)
      .join(':')
      .trim()
  );
}

function parseYamlObjectLine(line, prefix) {
  if (!line.startsWith(prefix)) {
    return null;
  }

  const body = line.slice(prefix.length);
  const separator = body.indexOf(':');
  if (separator === -1) {
    return null;
  }

  return {
    key: body.slice(0, separator).trim(),
    value: parseScalar(body.slice(separator + 1).trim())
  };
}

function readObjectList(content, keyLine, listIndent) {
  const lines = String(content || '').split(/\r?\n/);
  const start = lines.findIndex(line => line === keyLine);
  if (start === -1) {
    return [];
  }

  const entries = [];
  let current = null;

  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index];
    if (!line.trim()) {
      continue;
    }
    if (!line.startsWith(listIndent)) {
      break;
    }

    if (line.startsWith(`${listIndent}- `)) {
      if (current && Object.values(current).some(Boolean)) {
        entries.push(current);
      }
      current = {};
      const parsed = parseYamlObjectLine(line, `${listIndent}- `);
      if (parsed) {
        current[parsed.key] = parsed.value;
      }
      continue;
    }

    if (current && line.startsWith(`${listIndent}  `)) {
      const parsed = parseYamlObjectLine(line, `${listIndent}  `);
      if (parsed) {
        current[parsed.key] = parsed.value;
      }
    }
  }

  if (current && Object.values(current).some(Boolean)) {
    entries.push(current);
  }

  return entries;
}

function normalizeSignalEntry(entry) {
  return {
    name: String((entry && entry.name) || '').trim(),
    pin: String((entry && entry.pin) || '').trim(),
    direction: String((entry && entry.direction) || '').trim(),
    note: String((entry && entry.note) || '').trim()
  };
}

function readProjectHardwareTruth() {
  const hwPath = path.join(process.cwd(), '.emb-agent', 'hw.yaml');
  if (!fs.existsSync(hwPath)) {
    return {
      vendor: '',
      model: '',
      signals: [],
      peripherals: []
    };
  }

  const content = fs.readFileSync(hwPath, 'utf8');

  return {
    vendor: String(parseScalarByKey(content, 'vendor') || ''),
    model: String(parseScalarByKey(content, 'model') || ''),
    signals: readObjectList(content, 'signals:', '  ').map(normalizeSignalEntry),
    peripherals: readObjectList(content, 'peripherals:', '  ')
  };
}

function readHwIdentity() {
  return readProjectHardwareTruth();
}

function buildProjectSignalAliases(options) {
  const config = options && typeof options === 'object' ? options : {};
  const target = String(config.target || '').trim().toLowerCase();
  const direction = normalizeValue(config.direction);
  const keywords = Array.isArray(config.keywords)
    ? config.keywords
        .map(item => normalizeLookupToken(item))
        .filter(Boolean)
    : [];

  if (!target) {
    return {};
  }

  const hardware = readProjectHardwareTruth();
  const signals = Array.isArray(hardware.signals) ? hardware.signals : [];
  const aliases = {};

  signals.forEach(signal => {
    const signalDirection = normalizeValue(signal.direction);
    const haystack = normalizeLookupToken(`${signal.name} ${signal.note}`);
    const matchesDirection = !direction || !signalDirection || signalDirection === direction;
    const matchesKeyword =
      keywords.length === 0 ||
      keywords.some(keyword => haystack.includes(keyword));

    if (!matchesDirection || !matchesKeyword) {
      return;
    }

    [signal.name, signal.pin].forEach(raw => {
      const key = normalizeLookupToken(raw);
      if (key && !aliases[key]) {
        aliases[key] = target;
      }
    });
  });

  return aliases;
}

function resolveAliasValue(value, aliases) {
  const requested = normalizeLookupToken(value);
  if (!requested) {
    return '';
  }

  const table = {};
  Object.entries(aliases || {}).forEach(([key, resolved]) => {
    const normalizedKey = normalizeLookupToken(key);
    const normalizedValue = String(resolved || '').trim().toLowerCase();
    if (normalizedKey && normalizedValue) {
      table[normalizedKey] = normalizedValue;
    }
  });

  const candidates = [requested];
  const portMatch = requested.match(/^p([a-z]\d+)$/);
  if (portMatch) {
    candidates.push(`r${portMatch[1]}`);
  }
  const registerMatch = requested.match(/^r([a-z]\d+)$/);
  if (registerMatch) {
    candidates.push(`p${registerMatch[1]}`);
  }

  for (const candidate of candidates) {
    if (table[candidate]) {
      return table[candidate];
    }
  }

  return '';
}

function uniqueDisplayValues(values, limit) {
  const items = Array.isArray(values) ? values : [];
  const max = Number.isFinite(limit) ? limit : 6;
  const seen = new Set();
  const output = [];

  items.forEach(raw => {
    const text = String(raw || '').trim();
    const normalized = normalizeLookupToken(text);
    if (!text || !normalized || seen.has(normalized) || output.length >= max) {
      return;
    }
    seen.add(normalized);
    output.push(text);
  });

  return output;
}

function resolveIdentity(options) {
  const hw = readHwIdentity();
  return {
    vendor: normalizeValue(options.vendor || hw.vendor),
    family: normalizeValue(options.family),
    device: normalizeValue(options.device),
    chip: normalizeValue(options.chip || options.mcu || options.model || hw.model)
  };
}

function routeFromIdentity(identity) {
  return {
    family: identity.family,
    device: identity.device,
    chip: identity.chip
  };
}

function chipSupportRoot() {
  return path.resolve(__dirname, '..');
}

function extensionsRoot() {
  return path.resolve(chipSupportRoot(), '..', 'extensions');
}

function loadAlgorithm(name) {
  const normalized = normalizeValue(name);
  if (!normalized) {
    throw new Error('algorithm name is required');
  }

  const filePath = path.join(chipSupportRoot(), 'algorithms', `${normalized}.cjs`);
  if (!fs.existsSync(filePath)) {
    throw new Error(`Missing chip-support algorithm: ${normalized}`);
  }

  const loaded = require(filePath);
  if (!loaded || typeof loaded.run !== 'function') {
    throw new Error(`Chip-support algorithm must export run(): ${filePath}`);
  }

  return loaded;
}

function readJsonIfExists(filePath) {
  if (!fs.existsSync(filePath)) {
    return null;
  }
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function loadChipProfile(slug) {
  if (!slug) return null;
  return readJsonIfExists(path.join(extensionsRoot(), 'chips', 'devices', `${slug}.json`));
}

function loadToolDeviceProfile(slug) {
  if (!slug) return null;
  return readJsonIfExists(path.join(extensionsRoot(), 'tools', 'devices', `${slug}.json`));
}

function loadToolFamilyProfile(slug) {
  if (!slug) return null;
  return readJsonIfExists(path.join(extensionsRoot(), 'tools', 'families', `${slug}.json`));
}

function resolveProfiles(identity) {
  const chipProfile = loadChipProfile(identity.chip || identity.device);
  const deviceProfile = loadToolDeviceProfile(identity.device || identity.chip);
  const familySlug =
    identity.family || (deviceProfile && deviceProfile.family) || (chipProfile && chipProfile.family) || '';
  const familyProfile = loadToolFamilyProfile(familySlug);

  return {
    chip: chipProfile,
    device: deviceProfile,
    family: familyProfile
  };
}

function resolveBinding(toolName, identity, profiles) {
  const deviceBindings = (profiles.device && profiles.device.bindings) || {};
  const familyBindings = (profiles.family && profiles.family.bindings) || {};

  return deviceBindings[toolName] || familyBindings[toolName] || null;
}

function buildRouteRequired(context, toolName, options, identity, profiles, extras) {
  const route = routeFromIdentity(identity);
  const chipSupportPath = context.chipSupportPath || context.adapterPath || '';
  const knownTargets = [
    profiles.device && profiles.device.name,
    profiles.chip && profiles.chip.name,
    profiles.family && profiles.family.name
  ].filter(Boolean);

  return {
    tool: toolName,
    status: 'route-required',
    implementation: 'chip-support-catalog',
    chip_support_path: chipSupportPath,
    route,
    inputs: {
      raw_tokens: context.tokens || [],
      options
    },
    notes: [
      `${toolName} is managed by the external chip-support catalog, but no executable route binding was matched.`,
      knownTargets.length > 0
        ? `Recognized profiles: ${knownTargets.join(', ')}`
        : 'No matching chip/device/family profile recognized.'
    ].concat((extras && extras.notes) || [])
  };
}

function buildUnsupported(context, toolName, options, identity, extras) {
  const chipSupportPath = context.chipSupportPath || context.adapterPath || '';
  return {
    tool: toolName,
    status: 'unsupported',
    implementation: 'external-chip-support',
    chip_support_path: chipSupportPath,
    route: routeFromIdentity(identity),
    inputs: {
      raw_tokens: context.tokens || [],
      options
    },
    notes: ((extras && extras.notes) || []).slice()
  };
}

function buildOk(context, toolName, options, identity, outputs, notes) {
  const chipSupportPath = context.chipSupportPath || context.adapterPath || '';
  return {
    tool: toolName,
    status: 'ok',
    implementation: 'external-chip-support',
    chip_support_path: chipSupportPath,
    route: routeFromIdentity(identity),
    inputs: {
      raw_tokens: context.tokens || [],
      options
    },
    outputs,
    notes: notes || []
  };
}

module.exports = {
  buildProjectSignalAliases,
  buildOk,
  buildRouteRequired,
  buildUnsupported,
  chipSupportRoot,
  formatHex,
  loadAlgorithm,
  normalizeLookupToken,
  parseBoolean,
  parseNumber,
  parseOptions,
  parsePositiveNumber,
  readJsonIfExists,
  readProjectHardwareTruth,
  resolveAliasValue,
  resolveBinding,
  resolveIdentity,
  resolveProfiles,
  roundNumber,
  uniqueDisplayValues
};
