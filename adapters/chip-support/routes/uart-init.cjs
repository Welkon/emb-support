'use strict';

const shared = require('../core/shared.cjs');

module.exports = {
  runTool(context) {
    const options = shared.parseOptions(context);
    const identity = shared.resolveIdentity(options);
    const profiles = shared.resolveProfiles(identity);
    const binding = shared.resolveBinding('uart-init', identity, profiles);

    if (!binding) {
      return shared.buildRouteRequired(context, 'uart-init', options, identity, profiles, {
        notes: ['Declare bindings.uart-init in the tool device/family profile first.']
      });
    }

    if (binding.algorithm === 'unsupported') {
      return shared.buildUnsupported(context, 'uart-init', options, identity, {
        notes: [binding.reason || 'Chip does not support UART or is not configured.']
      });
    }

    const params = binding.params || {};
    const baud = Number(options.baud || options['baud-rate'] || 115200);
    const dataBits = Number(options['data-bits'] || options.data_bits || 8);
    const stopBits = Number(options['stop-bits'] || options.stop_bits || 1);
    const parity = String(options.parity || 'none').toUpperCase();
    const flowControl = String(options['flow-control'] || options.flow_control || 'none').toLowerCase();
    const clockHz = Number(options['clock-hz'] || options.clock_hz || (params.default_clock_hz || 80000000));

    const divider = clockHz / baud;
    const integerDiv = Math.round(divider);
    const actualBaud = clockHz / integerDiv;
    const errorPct = ((actualBaud - baud) / baud) * 100;

    const registerWrites = [];
    if (params.baud_reg) {
      registerWrites.push({
        register: params.baud_reg,
        value: `0x${integerDiv.toString(16).toUpperCase()}`,
        description: `Baud rate divider: ${clockHz} / ${integerDiv} = ${actualBaud.toFixed(0)}`
      });
    }
    if (params.ctrl_reg) {
      const dataBitsCode = { 5: '0x0', 6: '0x1', 7: '0x2', 8: '0x3' };
      const parityCode = { NONE: '0x0', EVEN: '0x1', ODD: '0x2' };
      registerWrites.push({
        register: params.ctrl_reg,
        value: `(data_bits=${dataBitsCode[dataBits] || '0x3'}, parity=${parityCode[parity] || '0x0'}, stop=${stopBits - 1})`,
        description: 'Control register configuration'
      });
    }

    return shared.buildOk(context, 'uart-init', options, identity, {
      init_code: `UART_Init(${params.peripheral || 'UART0'}, ${baud}, DATA_${dataBits}, STOP_${stopBits}, PARITY_${parity});`,
      register_writes: registerWrites,
      baud_rate: baud,
      actual_baud: Math.round(actualBaud),
      error_pct: parseFloat(errorPct.toFixed(2)),
      acceptable: Math.abs(errorPct) < 2.5
    }, [
      Math.abs(errorPct) >= 2.5
        ? `Baud rate error ${errorPct.toFixed(2)}% exceeds 2.5%; actual baud rate: ${actualBaud.toFixed(0)}`
        : `Baud rate error ${errorPct.toFixed(2)}% within acceptable range`,
      'Run a loopback test at the target baud rate to verify communication.'
    ]);
  }
};
