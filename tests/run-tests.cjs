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


function runScmcuMapTests() {
  const script = path.resolve(
    __dirname,
    '..',
    'skills',
    'mcu-debug',
    'scripts',
    'scmcu',
    'sfr_extract.py'
  );
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'emb-support-scmcu-'));
  const include = path.join(root, 'include');
  const out = path.join(root, 'out');
  fs.mkdirSync(include, { recursive: true });

  const header = (registers, bits) =>
    [
      '#ifndef TEST_H',
      '#define TEST_H',
      '',
      ...registers.map(([name, address]) => `volatile \tunsigned char \t${name}\t\t@\t${address};`),
      '',
      ...bits.map(([name, register, index]) => `volatile \t bit \t ${name}\t @ ((unsigned)&${register}*8)+${index};`),
      '',
      '#endif',
      ''
    ].join('\n');

  fs.writeFileSync(
    path.join(include, 'SC8T001.h'),
    header(
      [
        ['PORTB', '0x06'],
        ['TRISB', '0x05']
      ],
      [
        ['RB0', 'PORTB', 0],
        ['RB1', 'PORTB', 1]
      ]
    ),
    'utf8'
  );
  fs.writeFileSync(
    path.join(include, 'SC8T002.h'),
    header(
      [
        ['PORTC', '0x106'],
        ['TRISC', '0x105']
      ],
      [['RC0', 'PORTC', 0]]
    ),
    'utf8'
  );

  const run = args =>
    childProcess.spawnSync('python3', [script, ...args], { encoding: 'utf8' });

  let result = run(['--include-dir', include, '--out-dir', out, '--ide-version', 'TEST']);
  if (result.error && result.error.code === 'ENOENT') {
    logResult('scmcu map extractor', 'skip', 'python3 not found');
    skipped++;
    return;
  }
  const problems = [];
  if (result.status !== 0) problems.push('generate failed: ' + (result.stderr || '').trim());
  const plain = fs.existsSync(path.join(out, 'SC8T001.md'))
    ? fs.readFileSync(path.join(out, 'SC8T001.md'), 'utf8')
    : '';
  const banked = fs.existsSync(path.join(out, 'SC8T002.md'))
    ? fs.readFileSync(path.join(out, 'SC8T002.md'), 'utf8')
    : '';
  if (!plain.includes('`RB0`')) problems.push('bit column missing');
  if (!plain.includes('Addressing: 8-bit')) problems.push('8-bit addressing not reported');
  if (!banked.includes('0x106')) problems.push('banked address truncated');
  if (!banked.includes('banked')) problems.push('banked addressing not reported');
  const index = fs.existsSync(path.join(out, 'index.json'))
    ? JSON.parse(fs.readFileSync(path.join(out, 'index.json'), 'utf8'))
    : { parts: [] };
  if (index.parts.length !== 2) problems.push('index has ' + index.parts.length + ' parts');

  result = run(['--check', '--include-dir', include, '--out-dir', out]);
  if (result.status !== 0) problems.push('check on a fresh map failed');

  fs.appendFileSync(path.join(out, 'SC8T001.md'), '\nstale\n');
  result = run(['--check', '--include-dir', include, '--out-dir', out]);
  if (result.status === 0) problems.push('check accepted a stale file');

  fs.writeFileSync(
    path.join(include, 'SC8T003.h'),
    header([['PORTD', '0x07']], [['RD0', 'PORTD', 8]]),
    'utf8'
  );
  result = run(['--include-dir', include, '--out-dir', out, '--only', 'SC8T003']);
  if (result.status === 0) problems.push('accepted a bit index above 7');
  if (!(result.stderr || '').includes('index 8')) problems.push('bit index error not explained');

  if (problems.length === 0) {
    logResult('scmcu map extractor', 'pass', '2 parts, banked addresses, drift and validation');
    passed++;
  } else {
    logResult('scmcu map extractor', 'fail', problems.join('; '));
    failed++;
  }
  fs.rmSync(root, { recursive: true, force: true });
}

function runPadaukMapTests() {
  const script = path.resolve(
    __dirname,
    '..',
    'skills',
    'mcu-debug',
    'scripts',
    'padauk',
    'inc_extract.py'
  );
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'emb-support-padauk-'));
  const inc = path.join(root, 'INC_PDK');
  const out = path.join(root, 'out');
  fs.mkdirSync(inc, { recursive: true });
  const incFile = (rom, registers) =>
    [
      '.Assembly\tINC_VER\t\t01',
      `.Assembly\tROM_Size\t${rom}`,
      '.Assembly\tRAM_Size\t0x40',
      '',
      ...registers,
      ''
    ].join('\n');

  fs.writeFileSync(
    path.join(inc, 'PMSX1.INC'),
    incFile('400h', ['\tPA\t\tIO_RW\t\t0x10 : 0xF9', '\tPAC\t\tIO_RW\t\t0x11 : 0xF9']),
    'utf8'
  );
  // A part that states the same name twice on purpose must keep both rows.
  fs.writeFileSync(
    path.join(inc, 'PMSX2.INC'),
    incFile('800h', ['\tPB\t\tIO_RW\t\t0x13', '\tPB\t\tIO_RW\t\t0x14 : 0x83']),
    'utf8'
  );

  const run = args => childProcess.spawnSync('python3', [script, ...args], { encoding: 'utf8' });
  let result = run(['--inc-dir', inc, '--out-dir', out, '--ide-version', 'TEST']);
  if (result.error && result.error.code === 'ENOENT') {
    logResult('padauk map extractor', 'skip', 'python3 not found');
    skipped++;
    return;
  }
  const problems = [];
  if (result.status !== 0) problems.push('generate failed: ' + (result.stderr || '').trim());
  const plain = fs.existsSync(path.join(out, 'PMSX1.md'))
    ? fs.readFileSync(path.join(out, 'PMSX1.md'), 'utf8')
    : '';
  const alias = fs.existsSync(path.join(out, 'PMSX2.md'))
    ? fs.readFileSync(path.join(out, 'PMSX2.md'), 'utf8')
    : '';
  if (!plain.includes('`0xF9` (0, 3, 4, 5, 6, 7)')) problems.push('usable-bit mask not decoded');
  if (!plain.includes('- ROM_Size: `400h`')) problems.push('memory budget missing');
  if ((alias.match(/\| `PB` \|/g) || []).length !== 2) problems.push('conditional duplicate rows dropped');
  const index = fs.existsSync(path.join(out, 'index.json'))
    ? JSON.parse(fs.readFileSync(path.join(out, 'index.json'), 'utf8'))
    : { parts: [] };
  if (index.parts.length !== 2) problems.push('index has ' + index.parts.length + ' parts');

  result = run(['--check', '--inc-dir', inc, '--out-dir', out]);
  if (result.status !== 0) problems.push('check on a fresh map failed');
  fs.appendFileSync(path.join(out, 'PMSX1.md'), '\nstale\n');
  result = run(['--check', '--inc-dir', inc, '--out-dir', out]);
  if (result.status === 0) problems.push('check accepted a stale file');

  if (problems.length === 0) {
    logResult('padauk map extractor', 'pass', '2 parts, masks, budgets, aliases, drift');
    passed++;
  } else {
    logResult('padauk map extractor', 'fail', problems.join('; '));
    failed++;
  }
  fs.rmSync(root, { recursive: true, force: true });
}

function runAllTests() {
  console.log('emb-support checks\n');

  console.log('xc8-build:');
  runXc8BuildScriptTests();

  console.log('\naltium-pcb:');
  runAltiumSkillTests();

  console.log('\nscmcu map:');
  runScmcuMapTests();

  console.log('\npadauk map:');
  runPadaukMapTests();

  console.log('\n---');
  console.log(`Passed: ${passed}  Failed: ${failed}  Skipped: ${skipped}`);

  if (failed > 0) {
    process.exit(1);
  }
}

runAllTests();
