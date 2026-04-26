'use strict';

const shared = require('../core/shared.cjs');

module.exports = {
  runTool(context) {
    const options = shared.parseOptions(context);
    const identity = shared.resolveIdentity(options);
    const profiles = shared.resolveProfiles(identity);
    const binding = shared.resolveBinding('adc-scale', identity, profiles);

    if (!binding) {
      return shared.buildRouteRequired(context, 'adc-scale', options, identity, profiles, {
        notes: ['Declare bindings.adc-scale in the tool device/family profile first.']
      });
    }

    if (binding.algorithm === 'unsupported') {
      return shared.buildUnsupported(context, 'adc-scale', options, identity, {
        notes: [binding.reason || 'This route explicitly declares no support for adc-scale.']
      });
    }

    const adcAlgorithm = shared.loadAlgorithm(binding.algorithm);
    const result = adcAlgorithm.run(options, binding, profiles);
    if (result.status !== 'ok') {
      return shared.buildUnsupported(context, 'adc-scale', options, identity, {
        notes: result.notes || []
      });
    }

    return shared.buildOk(context, 'adc-scale', options, identity, result.outputs, result.notes);
  }
};
