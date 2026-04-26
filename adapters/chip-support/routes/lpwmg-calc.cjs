'use strict';

const shared = require('../core/shared.cjs');

module.exports = {
  runTool(context) {
    const options = shared.parseOptions(context);
    const identity = shared.resolveIdentity(options);
    const profiles = shared.resolveProfiles(identity);
    const binding = shared.resolveBinding('lpwmg-calc', identity, profiles);

    if (!binding) {
      return shared.buildRouteRequired(context, 'lpwmg-calc', options, identity, profiles, {
        notes: ['Declare bindings.lpwmg-calc in the tool device/family profile first.']
      });
    }

    if (binding.algorithm === 'unsupported') {
      return shared.buildUnsupported(context, 'lpwmg-calc', options, identity, {
        notes: [binding.reason || 'This route explicitly declares no support for lpwmg-calc.']
      });
    }

    const algorithm = shared.loadAlgorithm(binding.algorithm);
    const result = algorithm.run(options, binding, profiles);
    if (result.status !== 'ok') {
      return shared.buildUnsupported(context, 'lpwmg-calc', options, identity, {
        notes: result.notes || []
      });
    }

    return shared.buildOk(context, 'lpwmg-calc', options, identity, result.outputs, result.notes);
  }
};
