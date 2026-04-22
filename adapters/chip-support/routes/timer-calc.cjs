'use strict';

const shared = require('../core/shared.cjs');

module.exports = {
  runTool(context) {
    const options = shared.parseOptions(context);
    const identity = shared.resolveIdentity(options);
    const profiles = shared.resolveProfiles(identity);
    const binding = shared.resolveBinding('timer-calc', identity, profiles);

    if (!binding) {
      return shared.buildRouteRequired(context, 'timer-calc', options, identity, profiles, {
        notes: ['请先在 tool device/family profile 中声明 bindings.timer-calc。']
      });
    }

    if (binding.algorithm === 'unsupported') {
      return shared.buildUnsupported(context, 'timer-calc', options, identity, {
        notes: [binding.reason || '该 route 显式声明不支持 timer-calc。']
      });
    }

    const timerAlgorithm = shared.loadAlgorithm(binding.algorithm);
    const result = timerAlgorithm.run(options, binding, profiles);
    if (result.status !== 'ok') {
      return shared.buildUnsupported(context, 'timer-calc', options, identity, {
        notes: result.notes || []
      });
    }

    return shared.buildOk(context, 'timer-calc', options, identity, result.outputs, result.notes);
  }
};
