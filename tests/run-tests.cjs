#!/usr/bin/env node
'use strict';

// Checks that need no probe, no instrument and no supply: the XC8 build helper
// and the altium-pcb skill tests. The chip-adapter vectors left with adapters/
// (2026-10); the arithmetic that mattered is prose in
// skills/mcu-debug/references/sources/calculators.md.

const fs = require('fs');
const os = require('os');
const path = require('path');
const childProcess = require('child_process');

let passed = 0;
let failed = 0;
let skipped = 0;

function logResult(name, status, detail) {
  const prefix = status === 'pass' ? '✓' : status === 'fail' ? '✗' : '○';
  console.log(`  ${prefix} ${name}${detail ? ` — ${detail}` : ''}`);
}


function runXc8BuildScriptTests() {
  const scriptPath = path.resolve(__dirname, '..', 'skills', 'mcu-debug', 'scripts', 'xc8', 'build_xc8.py');
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'emb-support-xc8-test-'));
  const fakeToolchain = path.join(tempRoot, 'SCMCU_IDE');
  const cfgDir = path.join(fakeToolchain, 'mcu', 'config');
  const binDir = path.join(fakeToolchain, 'data', 'bin');
  fs.mkdirSync(cfgDir, { recursive: true });
  fs.mkdirSync(binDir, { recursive: true });
  fs.writeFileSync(path.join(binDir, 'xc8.exe'), '', 'utf8');
  fs.writeFileSync(
    path.join(cfgDir, 'SC8P062BD.cfg'),
    [
      '[WDT]',
      'DISPMODE=0',
      'DISABLE=1,11,1:1,10,0:1,9,1:1,8,0',
      'ENABLE=1,11,1:1,10,1:1,9,1:1,8,1',
      '',
      '[EXT_RESET]',
      'DISPMODE=0',
      'DISABLE=0,13,1',
      'ENABLE=0,13,0',
      ''
    ].join('\n'),
    'utf8'
  );

  const pythonCode = `
import importlib.util
import json
from pathlib import Path
spec = importlib.util.spec_from_file_location('build_xc8', ${JSON.stringify(scriptPath)})
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
project = {
  'chip': 'SC8P062BD',
  'scw_chip': 'SC8F072',
  'chip_substitutes': [{'target': 'SC8P062BD', 'substitute': 'SC8F072', 'reason': 'debug substitute'}],
}
relation = mod.summarize_chip_relation(project)
decode = mod.decode_scmcu_config('FFFF,FAEF,FFFF,', {'chip': 'SC8P062BD', 'scw_chip': 'SC8P062BD'}, ${JSON.stringify(path.join(binDir, 'xc8.exe'))})
print(json.dumps({'relation': relation, 'decode': decode}, sort_keys=True))
`;

  const result = childProcess.spawnSync('python3', ['-c', pythonCode], { encoding: 'utf8' });
  if (result.error && result.error.code === 'ENOENT') {
    logResult('xc8-build script helpers', 'skip', 'python3 not found');
    skipped++;
    return;
  }
  if (result.status !== 0) {
    logResult('xc8-build script helpers', 'fail', result.stderr || result.stdout || 'python failed');
    failed++;
    return;
  }

  try {
    const output = JSON.parse(result.stdout.trim());
    if (output.relation.source !== 'project' || output.relation.known_debug_substitute !== true) {
      logResult('xc8-build chip relation', 'fail', 'project chip substitute was not recognized');
      failed++;
      return;
    }
    if (output.decode.critical.WDT !== 'DISABLE' || output.decode.critical.EXT_RESET !== 'DISABLE') {
      logResult('xc8-build config decode', 'fail', 'critical config fields were not decoded');
      failed++;
      return;
    }
    passed += 2;
    logResult('xc8-build chip relation', 'pass');
    logResult('xc8-build config decode', 'pass');
  } catch (err) {
    logResult('xc8-build script helpers', 'fail', err.message);
    failed++;
  }
}


function runAltiumSkillTests() {
  const root = path.resolve(__dirname, '..');
  const testsDir = path.join(root, 'skills', 'altium-pcb', 'tests');
  if (!fs.existsSync(testsDir)) {
    logResult('altium-pcb skill tests', 'skip', 'tests directory missing');
    skipped++;
    return;
  }
  const result = childProcess.spawnSync(
    'python3',
    ['-m', 'unittest', 'discover', '-s', testsDir, '-p', 'test_*.py'],
    { encoding: 'utf8', cwd: root }
  );
  if (result.error && result.error.code === 'ENOENT') {
    logResult('altium-pcb skill tests', 'skip', 'python3 not found');
    skipped++;
    return;
  }
  const summary = ((result.stderr || result.stdout || '').trim().split('\n').pop()) || '';
  if (result.status === 0) {
    logResult('altium-pcb skill tests', 'pass', summary);
    passed++;
  } else {
    logResult('altium-pcb skill tests', 'fail', summary || 'python failed');
    failed++;
  }
}


function runAllTests() {
  console.log('emb-support checks\n');

  console.log('xc8-build:');
  runXc8BuildScriptTests();

  console.log('\naltium-pcb:');
  runAltiumSkillTests();

  console.log('\n---');
  console.log(`Passed: ${passed}  Failed: ${failed}  Skipped: ${skipped}`);

  if (failed > 0) {
    process.exit(1);
  }
}

runAllTests();
