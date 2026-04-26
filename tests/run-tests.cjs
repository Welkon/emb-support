#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const ADAPTERS_DIR = path.resolve(__dirname, '..', 'adapters');
const ALGORITHMS_DIR = path.join(ADAPTERS_DIR, 'chip-support', 'algorithms');
const ROUTES_DIR = path.join(ADAPTERS_DIR, 'chip-support', 'routes');

let passed = 0;
let failed = 0;
let skipped = 0;

function logResult(name, status, detail) {
  const prefix = status === 'pass' ? '✓' : status === 'fail' ? '✗' : '○';
  console.log(`  ${prefix} ${name}${detail ? ` — ${detail}` : ''}`);
}

function extractTestVectors(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const lines = content.split('\n');
  const vectors = [];
  for (const line of lines) {
    const match = line.match(/@test_vector:\s*(.+)/);
    if (match) {
      vectors.push(match[1].trim());
    }
  }
  return vectors;
}

function loadDeviceBinding(algorithmName) {
  const devicesDir = path.join(ADAPTERS_DIR, 'extensions', 'tools', 'devices');
  if (!fs.existsSync(devicesDir)) return null;

  const files = fs.readdirSync(devicesDir).filter(f => f.endsWith('.json'));
  for (const file of files) {
    try {
      const binding = JSON.parse(fs.readFileSync(path.join(devicesDir, file), 'utf8'));
      if (binding.bindings) {
        for (const [, b] of Object.entries(binding.bindings)) {
          if (b.algorithm === algorithmName) {
            return b.params || {};
          }
        }
      }
    } catch {}
  }
  return null;
}

function runTest(algorithmName, algorithmPath, vectorRaw) {
  const algorithm = require(algorithmPath);
  const options = {};
  const assignments = vectorRaw.split(',').map(s => s.trim());

  for (const a of assignments) {
    const eqIdx = a.indexOf('=');
    if (eqIdx === -1) continue;
    const key = a.substring(0, eqIdx).trim();
    const value = a.substring(eqIdx + 1).trim();

    if (key === 'expected') {
      continue;
    }
    const num = Number(value);
    options[key] = Number.isNaN(num) ? value : num;
  }

  const expectedMatch = vectorRaw.match(/expected=([^,]+)/);
  const expectedStr = expectedMatch ? expectedMatch[1].trim() : null;

  const bindingParams = loadDeviceBinding(algorithmName) || {};

  try {
    const result = algorithm.run(options, { algorithm: algorithmName, params: bindingParams }, {});
    if (!result) {
      return { status: 'fail', detail: 'algorithm returned null' };
    }
    if (result.status === 'unsupported') {
      return { status: 'skip', detail: (result.notes || []).join('; ') };
    }
    if (result.status === 'ok') {
      if (expectedStr) {
        const actualReload = result.outputs && (result.outputs.best ? result.outputs.best.reload : result.outputs.reload);
        const expectedNum = Number(expectedStr);
        if (!Number.isNaN(expectedNum) && actualReload === expectedNum) {
          return { status: 'pass' };
        }
        return { status: 'fail', detail: `expected=${expectedStr}, got=${actualReload}` };
      }
      return { status: 'pass' };
    }
    return { status: 'fail', detail: (result && result.notes) ? result.notes.join('; ') : 'no result' };
  } catch (err) {
    return { status: 'fail', detail: err.message };
  }
}

function runAllTests() {
  console.log('emb-support algorithm verification\n');

  const algoFiles = fs.readdirSync(ALGORITHMS_DIR).filter(f => f.endsWith('.cjs') && f !== 'shared.cjs');

  for (const algoFile of algoFiles) {
    const algoName = algoFile.replace('.cjs', '');
    const algoPath = path.join(ALGORITHMS_DIR, algoFile);
    const vectors = extractTestVectors(algoPath);

    console.log(`${algoName}:`);

    if (vectors.length === 0) {
      logResult('(no test vectors)', 'skip', 'add @test_vector comment in source');
      skipped++;
      continue;
    }

    for (const vector of vectors) {
      const result = runTest(algoName, algoPath, vector);
      if (result.status === 'pass') passed++;
      else if (result.status === 'skip') skipped++;
      else failed++;
      logResult(vector, result.status, result.detail);
    }
  }

  console.log(`\n---`);
  console.log(`Passed: ${passed}  Failed: ${failed}  Skipped: ${skipped}`);
  console.log(`Total algorithms: ${algoFiles.length}`);

  if (failed > 0) {
    process.exit(1);
  }
}

runAllTests();
